#! python3
# -*- coding: utf-8 -*-
"""LOADER - Abrir Modelador Externo.

Este arquivo e' a unica parte que precisa existir fisicamente solta na pasta
do botao do pyRevit. A cada clique, ele tenta baixar do GitHub a versao mais
recente de tudo que fica em `nuvem/` (motor real, exportador JSON e
`ModulacaoVisualizador3D/`) e da copia propria de `core/` dentro deste
repositorio. Se a rede falhar, roda a ultima sincronizacao completa em cache
local. A pasta `nuvem/` pode ser apagada localmente.
"""

import io
import json
import os
import shutil
import sys
import traceback

import clr
clr.AddReference("System")
clr.AddReference("System.Security")

from System.Net import ServicePointManager, SecurityProtocolType, WebClient, WebException
from System.Security.Cryptography import ProtectedData, DataProtectionScope
from System.Text import Encoding
from System.IO import File as DotNetFile

from pyrevit import forms

try:
    ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
except Exception:
    pass


GITHUB_OWNER = "Arcanjog1"
GITHUB_REPO = "AbrirModeladorExterno.pushbutton"
GITHUB_BRANCH = "main"

EXTERNAL_CLOUD_DIR = "nuvem"
CORE_REPO_PREFIX = EXTERNAL_CLOUD_DIR + "/core/"
ENTRY_POINT_REPO_PATH = EXTERNAL_CLOUD_DIR + "/external_modelador.py"

TREE_API_URL = "https://api.github.com/repos/{0}/{1}/git/trees/{2}?recursive=1".format(
    GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
)

APP_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AbrirModeladorExternoPushbutton"
)
TOKEN_FILE = os.path.join(APP_DATA_DIR, "token.dat")
CACHE_ROOT = os.path.join(APP_DATA_DIR, "external_modelador_cache")
CACHE_TMP_ROOT = os.path.join(APP_DATA_DIR, "external_modelador_cache_tmp")


def _contents_api_url(repo_path):
    return "https://api.github.com/repos/{0}/{1}/contents/{2}?ref={3}".format(
        GITHUB_OWNER, GITHUB_REPO, repo_path, GITHUB_BRANCH
    )


def _txt(value):
    return value if isinstance(value, str) else str(value)


def _alert(message, title="Modelador Externo"):
    try:
        forms.alert(_txt(message), title=title)
    except Exception:
        try:
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import MessageBox
            MessageBox.Show(_txt(message))
        except Exception:
            pass


def _ask_for_string(default="", prompt="", title=""):
    try:
        return forms.ask_for_string(default=default, prompt=prompt, title=title)
    except Exception:
        try:
            clr.AddReference("Microsoft.VisualBasic")
            from Microsoft.VisualBasic import Interaction
            value = Interaction.InputBox(_txt(prompt), _txt(title), _txt(default))
            return value if value else None
        except Exception:
            return None


def _ensure_app_data_dir():
    if not os.path.isdir(APP_DATA_DIR):
        os.makedirs(APP_DATA_DIR)


def _save_token(token):
    _ensure_app_data_dir()
    raw_bytes = Encoding.GetEncoding("UTF-8").GetBytes(token)
    protected_bytes = ProtectedData.Protect(raw_bytes, None, DataProtectionScope.CurrentUser)
    DotNetFile.WriteAllBytes(TOKEN_FILE, protected_bytes)


def _load_token():
    if not os.path.isfile(TOKEN_FILE):
        return None
    try:
        protected_bytes = DotNetFile.ReadAllBytes(TOKEN_FILE)
        raw_bytes = ProtectedData.Unprotect(protected_bytes, None, DataProtectionScope.CurrentUser)
        return Encoding.GetEncoding("UTF-8").GetString(raw_bytes)
    except Exception:
        return None


def _forget_token():
    try:
        if os.path.isfile(TOKEN_FILE):
            os.remove(TOKEN_FILE)
    except Exception:
        pass


def _ask_for_token():
    token = _ask_for_string(
        default="",
        prompt=(
            "Cole aqui o seu GitHub Personal Access Token (fine-grained, "
            "somente leitura de 'Contents' no repositorio {0}/{1}).\n\n"
            "O repositorio publico baixa sem token; ele so' e' necessario se "
            "houver limite de requisicoes ou se o repositorio voltar a ficar privado."
        ).format(GITHUB_OWNER, GITHUB_REPO),
        title="Modelador Externo - autenticacao necessaria",
    )
    if token:
        token = token.strip()
    if not token:
        return None
    _save_token(token)
    return token


def _new_web_client(token, accept):
    client = WebClient()
    client.Encoding = Encoding.GetEncoding("UTF-8")
    if token:
        client.Headers.Add("Authorization", "Bearer " + token)
    client.Headers.Add("Accept", accept)
    client.Headers.Add("User-Agent", "AbrirModeladorExternoPushbutton-Loader")
    client.Headers.Add("X-GitHub-Api-Version", "2022-11-28")
    return client


def _raise_for_web_exception(web_error, context):
    status_code = None
    if web_error.Response is not None:
        try:
            status_code = int(web_error.Response.StatusCode)
        except Exception:
            status_code = None
    if status_code == 401:
        raise RuntimeError("Token invalido ou expirado (HTTP 401).")
    if status_code == 403:
        raise RuntimeError(
            "Acesso negado - token sem permissao de leitura neste repositorio "
            "ou limite de requisicoes do GitHub atingido (HTTP 403)."
        )
    if status_code == 404:
        raise RuntimeError(
            "{0} nao encontrado no repositorio (HTTP 404).".format(context)
        )
    raise RuntimeError("Falha ao contatar o GitHub ({0}): {1}".format(context, web_error.Message))


def _list_remote_files(token):
    client = _new_web_client(token, "application/vnd.github+json")
    try:
        raw = client.DownloadString(TREE_API_URL)
    except WebException as web_error:
        _raise_for_web_exception(web_error, "listagem da arvore do repositorio")

    data = json.loads(raw)
    if data.get("truncated"):
        raise RuntimeError("A API do GitHub truncou a listagem da arvore do repositorio.")

    files = []
    for entry in data.get("tree", []):
        repo_path = entry.get("path", "")
        if entry.get("type") != "blob":
            continue
        if repo_path.startswith(EXTERNAL_CLOUD_DIR + "/") or repo_path.startswith(CORE_REPO_PREFIX):
            files.append(repo_path)

    if ENTRY_POINT_REPO_PATH not in files:
        raise RuntimeError("external_modelador.py nao apareceu na listagem do GitHub.")
    return files


def _fetch_file_bytes(token, repo_path):
    client = _new_web_client(token, "application/vnd.github.raw")
    try:
        return client.DownloadData(_contents_api_url(repo_path))
    except WebException as web_error:
        _raise_for_web_exception(web_error, repo_path)


def _write_bytes(path, data):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    DotNetFile.WriteAllBytes(path, data)


def _sync_package(token):
    files = _list_remote_files(token)

    if os.path.isdir(CACHE_TMP_ROOT):
        shutil.rmtree(CACHE_TMP_ROOT)
    os.makedirs(CACHE_TMP_ROOT)

    for repo_path in files:
        local_path = os.path.join(CACHE_TMP_ROOT, *repo_path.split("/"))
        _write_bytes(local_path, _fetch_file_bytes(token, repo_path))

    if os.path.isdir(CACHE_ROOT):
        shutil.rmtree(CACHE_ROOT)
    os.rename(CACHE_TMP_ROOT, CACHE_ROOT)

    return os.path.join(CACHE_ROOT, *ENTRY_POINT_REPO_PATH.split("/"))


def _entry_point_from_existing_cache():
    entry_point = os.path.join(CACHE_ROOT, *ENTRY_POINT_REPO_PATH.split("/"))
    if os.path.isfile(entry_point):
        return entry_point
    return None


def _load_entry_point():
    token = _load_token()
    try:
        return _sync_package(token)
    except Exception as first_error:
        error_text = str(first_error)
        if "401" in error_text or "403" in error_text:
            if token:
                _forget_token()
            retry_token = _ask_for_token()
            if retry_token:
                try:
                    return _sync_package(retry_token)
                except Exception as second_error:
                    first_error = second_error

        cached_entry = _entry_point_from_existing_cache()
        if cached_entry:
            _alert(
                "Nao foi possivel baixar a versao mais recente do GitHub:\n\n"
                "{0}\n\nRodando a ultima copia em cache (pode estar desatualizada).".format(
                    first_error
                ),
                title="Modelador Externo - usando cache",
            )
            return cached_entry

        _alert(
            "Nao foi possivel baixar o Modelador Externo do GitHub e nao ha' "
            "copia em cache neste computador:\n\n{0}".format(first_error),
            title="Modelador Externo - erro",
        )
        sys.exit()


_entry_point_path = _load_entry_point()
_external_root = os.path.dirname(_entry_point_path)
_core_root = _external_root

for _mod_name in list(sys.modules.keys()):
    if (
        _mod_name == "core"
        or _mod_name.startswith("core.")
        or _mod_name in ("capture_export_external", "external_modelador")
    ):
        del sys.modules[_mod_name]

if _external_root not in sys.path:
    sys.path.insert(0, _external_root)
if _core_root not in sys.path:
    sys.path.insert(0, _core_root)

with io.open(_entry_point_path, "r", encoding="utf-8") as _fh:
    _source_code = _fh.read()

globals()["__file__"] = _entry_point_path

try:
    exec(compile(_source_code, _entry_point_path, "exec"), globals())
except SystemExit:
    raise
except Exception:
    _alert(
        "O Modelador Externo baixado do GitHub encontrou um erro ao executar:\n\n{0}".format(
            traceback.format_exc()
        ),
        title="Modelador Externo - erro na execucao",
    )
    raise
