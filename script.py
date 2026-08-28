#! python3
# -*- coding: utf-8 -*-
"""LOADER - Abrir Modelador Externo.

Este arquivo e' a unica parte que precisa existir fisicamente solta na pasta
do botao do pyRevit. A cada clique, ele tenta baixar do GitHub a versao mais
recente de tudo que fica em `nuvem/` (motor real, exportador JSON e
`ModulacaoVisualizador3D/`) e da copia propria de `core/` dentro deste
repositorio. Se a rede falhar, roda a ultima sincronizacao completa em cache
local. A pasta `nuvem/` pode ser apagada localmente.

AUTENTICACAO POR SENHA (2026-08-28): com o repositorio PRIVADO de novo, o
download precisa de token - mas o usuario digita apenas uma SENHA. O PAT de
leitura do mantenedor viaja CIFRADO aqui dentro (constante TOKEN_CIFRADO, ou
o arquivo `token_cifrado.dat` ao lado deste script) e e' aberto com essa
senha, uma unica vez por computador; depois disso o token decifrado fica
salvo com DPAPI e nada mais e' perguntado. Ver README_LOADER.md e
ferramentas/gerar_token_cifrado.py.
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

# --------------------------------------------------------------------
# TOKEN CIFRADO POR SENHA (repositorio PRIVADO - 2026-08-28)
# --------------------------------------------------------------------
# O usuario digita uma SENHA, nao um Personal Access Token: o PAT de
# leitura do mantenedor mora aqui embaixo, cifrado com essa senha, e so'
# e' aberto em memoria quando a senha correta for digitada.
#
# LIMITE HONESTO: quem tiver este arquivo E a senha consegue extrair o
# token - a senha e' um cadeado, nao um cofre. Por isso o PAT usado aqui
# DEVE ser fine-grained, com `Contents: Read-only`, e so' nos dois
# repositorios dos botoes.
#
# Para preencher/trocar: `python3 ferramentas/gerar_token_cifrado.py` e
# cole a linha `MB1$...` abaixo (ou salve-a em `token_cifrado.dat` ao lado
# deste script, que tem prioridade sobre a constante). O MESMO blob dos
# dois botoes pode ser usado, se o token tiver leitura nos dois repos.
#
# Vazio = comportamento de antes (repositorio publico, download anonimo).
TOKEN_CIFRADO = ""


def _pasta_do_loader():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


TOKEN_CIFRADO_FILE = os.path.join(_pasta_do_loader(), "token_cifrado.dat")


# ==== INICIO BLOCO CRIPTO (copia identica em ferramentas/cripto_token.py) ====
# Cifra/decifra o PAT do GitHub com uma SENHA escolhida pelo mantenedor.
#
# Por que existe: com os repositorios PRIVADOS, o download exige um token.
# Pedir o PAT para cada pessoa e' inviavel (cada uma precisaria gerar o
# seu no GitHub). Em vez disso, o token do mantenedor viaja CIFRADO dentro
# do proprio loader (constante TOKEN_CIFRADO / arquivo token_cifrado.dat) e
# so' e' aberto quando a pessoa digita a senha combinada.
#
# Formato do blob (uma unica linha ASCII, seguro para colar no codigo):
#   MB1$<iteracoes>$<sal_b64>$<nonce_b64>$<cifrado_b64>$<tag_b64>
#
# Algoritmo (so' com a biblioteca padrao - nada de AES/.NET, para o MESMO
# codigo rodar identico no engine CPython do pyRevit, no IronPython e no
# python3 comum que gera o blob):
#   chave      = PBKDF2-HMAC-SHA256(senha, sal, iteracoes) -> 64 bytes
#   k_cifra    = chave[:32]   k_tag = chave[32:]
#   keystream  = HMAC-SHA256(k_cifra, nonce || contador) por bloco de 32 B
#   cifrado    = (marcador || token) XOR keystream
#   tag        = HMAC-SHA256(k_tag, nonce || cifrado)   (encrypt-then-MAC)
# A tag e' o que diferencia "senha errada" de "arquivo adulterado" de
# "deu certo" - sem ela, uma senha errada devolveria lixo silenciosamente.
import base64
import hashlib
import hmac
import os
import struct

CRIPTO_PREFIXO = "MB1"
CRIPTO_ITERACOES = 200000
_CRIPTO_MARCADOR = b"tok1:"


class SenhaIncorreta(ValueError):
    """Senha errada, ou blob adulterado/corrompido (a tag HMAC nao bate)."""


class BlobInvalido(ValueError):
    """O texto passado nao tem o formato MB1$...$...$...$...$..."""


def _bytes_senha(senha):
    if isinstance(senha, bytes):
        return senha
    return senha.encode("utf-8")


def _pbkdf2(senha_bytes, sal, iteracoes, tamanho):
    pronto = getattr(hashlib, "pbkdf2_hmac", None)
    if pronto is not None:
        return pronto("sha256", senha_bytes, sal, iteracoes, tamanho)
    # Fallback manual (IronPython 2.7 nao tem pbkdf2_hmac): mesma conta,
    # so' que em Python puro - custa alguns segundos UMA vez, e o token
    # decifrado ja' fica salvo em DPAPI depois disso.
    derivado = b""
    bloco = 1
    while len(derivado) < tamanho:
        u = hmac.new(senha_bytes, sal + struct.pack(">I", bloco), hashlib.sha256).digest()
        acumulado = bytearray(u)
        for _ in range(iteracoes - 1):
            u = hmac.new(senha_bytes, u, hashlib.sha256).digest()
            for i, byte in enumerate(bytearray(u)):
                acumulado[i] ^= byte
        derivado += bytes(acumulado)
        bloco += 1
    return derivado[:tamanho]


def _keystream_xor(chave, nonce, dados):
    dados = bytearray(dados)
    saida = bytearray(len(dados))
    posicao = 0
    contador = 0
    while posicao < len(dados):
        bloco = bytearray(
            hmac.new(chave, nonce + struct.pack(">I", contador), hashlib.sha256).digest()
        )
        for byte in bloco:
            if posicao >= len(dados):
                break
            saida[posicao] = dados[posicao] ^ byte
            posicao += 1
        contador += 1
    return bytes(saida)


def _iguais(a, b):
    comparar = getattr(hmac, "compare_digest", None)
    if comparar is not None:
        return comparar(a, b)
    if len(a) != len(b):
        return False
    diferenca = 0
    for x, y in zip(bytearray(a), bytearray(b)):
        diferenca |= x ^ y
    return diferenca == 0


def _b64(dados):
    return base64.b64encode(dados).decode("ascii")


def _de_b64(texto):
    return base64.b64decode(texto.encode("ascii"))


def cifrar_token(token, senha, iteracoes=CRIPTO_ITERACOES, sal=None, nonce=None):
    """Devolve o blob (str) para colar em TOKEN_CIFRADO / token_cifrado.dat.
    `sal`/`nonce` so' sao passados nos testes - em uso real vem de
    os.urandom, entao cifrar duas vezes o mesmo token nunca gera o mesmo
    texto."""
    sal = os.urandom(16) if sal is None else sal
    nonce = os.urandom(16) if nonce is None else nonce
    chave = _pbkdf2(_bytes_senha(senha), sal, iteracoes, 64)
    k_cifra, k_tag = chave[:32], chave[32:]
    aberto = _CRIPTO_MARCADOR + token.encode("utf-8")
    cifrado = _keystream_xor(k_cifra, nonce, aberto)
    tag = hmac.new(k_tag, nonce + cifrado, hashlib.sha256).digest()
    return "$".join(
        [CRIPTO_PREFIXO, str(iteracoes), _b64(sal), _b64(nonce), _b64(cifrado), _b64(tag)]
    )


def decifrar_token(blob, senha):
    """Devolve o token em texto puro. Levanta SenhaIncorreta se a senha
    estiver errada (ou o blob tiver sido adulterado) e BlobInvalido se o
    texto nem for um blob deste formato."""
    if not blob:
        raise BlobInvalido("nenhum token cifrado configurado")
    partes = blob.strip().split("$")
    if len(partes) != 6 or partes[0] != CRIPTO_PREFIXO:
        raise BlobInvalido(
            "token cifrado fora do formato esperado "
            "(MB1$iteracoes$sal$nonce$cifrado$tag)"
        )
    try:
        iteracoes = int(partes[1])
        sal = _de_b64(partes[2])
        nonce = _de_b64(partes[3])
        cifrado = _de_b64(partes[4])
        tag = _de_b64(partes[5])
    except Exception:
        raise BlobInvalido("token cifrado corrompido (base64/iteracoes invalidos)")
    if iteracoes < 1000:
        raise BlobInvalido("token cifrado com iteracoes de menos")

    chave = _pbkdf2(_bytes_senha(senha), sal, iteracoes, 64)
    k_cifra, k_tag = chave[:32], chave[32:]
    tag_conferida = hmac.new(k_tag, nonce + cifrado, hashlib.sha256).digest()
    if not _iguais(tag, tag_conferida):
        raise SenhaIncorreta("senha incorreta")
    aberto = _keystream_xor(k_cifra, nonce, cifrado)
    if not aberto.startswith(_CRIPTO_MARCADOR):
        raise SenhaIncorreta("senha incorreta")
    return aberto[len(_CRIPTO_MARCADOR):].decode("utf-8")
# ==== FIM BLOCO CRIPTO ====


def _blob_cifrado():
    """Blob do token cifrado: `token_cifrado.dat` ao lado do loader tem
    prioridade (troca o token sem editar codigo); senao, a constante
    TOKEN_CIFRADO. None quando nada esta' configurado."""
    try:
        if os.path.isfile(TOKEN_CIFRADO_FILE):
            with io.open(TOKEN_CIFRADO_FILE, "r", encoding="utf-8") as fh:
                do_arquivo = fh.read().strip()
            if do_arquivo:
                return do_arquivo
    except Exception:
        pass
    return TOKEN_CIFRADO.strip() or None



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
    """Fallback antigo: pede o PAT direto. So' e' usado quando NAO ha'
    token cifrado configurado (ver _get_token) - com o blob preenchido, o
    usuario so' ve' a janela de senha."""
    token = _ask_for_string(
        default="",
        prompt=(
            "Cole aqui o seu GitHub Personal Access Token (fine-grained, "
            "somente leitura de 'Contents' no repositorio {0}/{1}).\n\n"
            "Este botao normalmente pede so' uma SENHA - esta janela so' "
            "aparece quando nao ha' token cifrado configurado no loader."
        ).format(GITHUB_OWNER, GITHUB_REPO),
        title="Modelador Externo - autenticacao necessaria",
    )
    if token:
        token = token.strip()
    if not token:
        return None
    _save_token(token)
    return token


def _ask_for_password():
    return _ask_for_string(
        default="",
        prompt=(
            "Digite a senha de acesso do botao Abrir Modelador Externo.\n\n"
            "Ela sera' pedida UMA UNICA VEZ neste computador: depois disso o "
            "acesso fica salvo criptografado (ligado a sua conta do Windows) "
            "e o botao abre direto.\n\n"
            "Se nao souber a senha, peca ao responsavel pelo botao."
        ),
        title="Modelador Externo - senha de acesso",
    )


def _token_por_senha(blob, tentativas=3):
    """Pede a senha e devolve o token decifrado (ja' salvo em DPAPI), ou
    None se o usuario cancelar/errar todas as tentativas. A caixa de texto
    usada (`InputBox`) NAO mascara o que e' digitado."""
    for tentativa in range(tentativas):
        senha = _ask_for_password()
        if senha is None:
            return None
        senha = senha.strip()
        if not senha:
            return None
        try:
            token = decifrar_token(blob, senha)
        except SenhaIncorreta:
            restantes = tentativas - tentativa - 1
            _alert(
                "Senha incorreta." + (
                    "\n\nTente de novo ({0} tentativa(s) restante(s)).".format(restantes)
                    if restantes else "\n\nO botao vai tentar rodar a ultima copia em cache."
                ),
                title="Modelador Externo - senha incorreta",
            )
            continue
        except BlobInvalido as erro:
            _alert(
                "O token cifrado deste botao esta' invalido ou corrompido "
                "({0}).\n\nAvise o responsavel: e' preciso gerar o blob de "
                "novo com ferramentas/gerar_token_cifrado.py.".format(erro),
                title="Modelador Externo - configuracao invalida",
            )
            return None
        _save_token(token)
        return token
    return None


def _get_token(force_reprompt=False):
    """Ordem: token ja' salvo em DPAPI -> senha (destrava o token cifrado)
    -> PAT digitado a mao (so' quando nao ha' token cifrado configurado)."""
    if not force_reprompt:
        token = _load_token()
        if token:
            return token

    blob = _blob_cifrado()
    if blob:
        return _token_por_senha(blob)

    if force_reprompt:
        return _ask_for_token()
    return None


def _new_web_client(token, accept):
    client = WebClient()
    client.Encoding = Encoding.GetEncoding("UTF-8")
    if token:
        client.Headers.Add("Authorization", "Bearer " + token)
    client.Headers.Add("Accept", accept)
    client.Headers.Add("User-Agent", "AbrirModeladorExternoPushbutton-Loader")
    client.Headers.Add("X-GitHub-Api-Version", "2022-11-28")
    return client


def _raise_for_web_exception(web_error, context, token=None):
    status_code = None
    if web_error.Response is not None:
        try:
            status_code = int(web_error.Response.StatusCode)
        except Exception:
            status_code = None
    if status_code == 401:
        if token:
            raise RuntimeError("Token salvo invalido ou expirado (HTTP 401).")
        raise RuntimeError(
            "GitHub recusou a requisicao sem credencial (HTTP 401) - o "
            "repositorio e' privado e nenhuma senha valida foi informada."
        )
    if status_code == 403:
        if token:
            raise RuntimeError(
                "Acesso negado com o token salvo - permissao insuficiente "
                "ou limite de requisicoes do GitHub atingido (HTTP 403)."
            )
        raise RuntimeError(
            "GitHub recusou o acesso publico ou o limite de requisicoes foi "
            "atingido (HTTP 403)."
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
        _raise_for_web_exception(web_error, "listagem da arvore do repositorio", token)

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
        _raise_for_web_exception(web_error, repo_path, token)


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
    # Na primeira vez pede a SENHA (se houver token cifrado configurado);
    # depois disso reusa o token salvo em DPAPI. Sem token cifrado e sem
    # token salvo, `_get_token` devolve None e o download sai anonimo,
    # exatamente como quando o repositorio era publico.
    token = _get_token()
    try:
        return _sync_package(token)
    except Exception as first_error:
        error_text = str(first_error)
        if "401" in error_text or "403" in error_text:
            if token:
                _forget_token()
            # Token expirado/revogado, blob trocado ou repositorio privado
            # sem credencial: pede a senha (ou o PAT) de novo.
            retry_token = _get_token(force_reprompt=True)
            if retry_token:
                try:
                    return _sync_package(retry_token)
                except Exception as second_error:
                    first_error = second_error
            elif token:
                # Usuario cancelou: ainda vale tentar anonimo, caso o
                # repositorio tenha voltado a ser publico.
                try:
                    return _sync_package(None)
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
