# -*- coding: utf-8 -*-
"""Integracao com o ODA File Converter (Open Design Alliance) ja instalado
no computador, para converter DWG -> DXF automaticamente.

Nao empacota, nao baixa e nao redistribui o ODA File Converter - esse
modulo so localiza o executavel de uma instalacao existente (tipicamente
em ``C:\\Program Files\\ODA\\ODAFileConverter <versao>\\ODAFileConverter.exe``)
e o aciona via linha de comando, no modo batch documentado pela propria
ODA (pasta de entrada -> pasta de saida), sem precisar abrir a interface
grafica manualmente. Ver README.md, secao "Convertendo DWG para DXF".
"""

import glob
import os
import shutil
import subprocess
import tempfile

try:
    import winreg
except ImportError:  # nao-Windows: deteccao via registro fica indisponivel
    winreg = None

_CANDIDATE_GLOBS = [
    r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
]

_UNINSTALL_KEYS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]

# Versao de saida do DXF (ACAD2018 e' lida sem problemas pelo ezdxf).
DXF_OUTPUT_VERSION = "ACAD2018"
CONVERT_TIMEOUT_SECONDS = 120

ODA_DOWNLOAD_HINT = (
    "ODA File Converter (gratuito, "
    "https://www.opendesign.com/guestfiles/oda_file_converter)"
)


class OdaNotFoundError(RuntimeError):
    """O ODA File Converter nao foi encontrado instalado no computador."""


class OdaConversionError(RuntimeError):
    """A conversao foi acionada mas nao terminou com sucesso."""


def find_oda_converter():
    """Procura o ODAFileConverter.exe instalado no computador.

    Retorna o caminho completo do executavel, ou None se nao encontrar.
    """
    for pattern in _CANDIDATE_GLOBS:
        # ordena decrescente pelo nome da pasta para pegar a versao mais nova
        # quando houver mais de uma instalada.
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]

    if winreg is not None:
        for subkey in _UNINSTALL_KEYS:
            exe = _find_in_uninstall_key(subkey)
            if exe:
                return exe

    return None


def _find_in_uninstall_key(subkey):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
            count = winreg.QueryInfoKey(key)[0]
            for i in range(count):
                try:
                    name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, name) as sub:
                        display_name = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if "ODA File Converter" not in display_name:
                            continue
                        install_location = winreg.QueryValueEx(sub, "InstallLocation")[0]
                except (FileNotFoundError, OSError):
                    continue
                if install_location:
                    candidate = os.path.join(install_location, "ODAFileConverter.exe")
                    if os.path.isfile(candidate):
                        return candidate
    except FileNotFoundError:
        pass
    return None


def convert_dwg_to_dxf(dwg_path, output_path=None, oda_exe=None):
    """Converte um .dwg para .dxf usando o ODA File Converter instalado.

    dwg_path: caminho do .dwg de origem (deve existir).
    output_path: caminho completo do .dxf de destino. Se None, usa a
        mesma pasta e o mesmo nome do .dwg original, so' trocando a
        extensao (convencao do projeto: DXF ao lado do DWG de origem).
    oda_exe: caminho do executavel, se ja conhecido. Senao e' localizado
        automaticamente via find_oda_converter().

    Retorna o caminho do .dxf gerado.

    Lanca OdaNotFoundError se o ODA nao estiver instalado, ou
    OdaConversionError se a conversao falhar.
    """
    if oda_exe is None:
        oda_exe = find_oda_converter()
    if not oda_exe or not os.path.isfile(oda_exe):
        raise OdaNotFoundError(
            "ODA File Converter nao foi encontrado neste computador. "
            "Instale o {} para habilitar a conversao automatica de "
            "DWG para DXF.".format(ODA_DOWNLOAD_HINT)
        )

    if not os.path.isfile(dwg_path):
        raise OdaConversionError("Arquivo DWG nao encontrado: {}".format(dwg_path))

    base_name = os.path.splitext(os.path.basename(dwg_path))[0]
    if output_path is None:
        output_path = os.path.join(os.path.dirname(os.path.abspath(dwg_path)), base_name + ".dxf")

    with tempfile.TemporaryDirectory(prefix="oda_conv_in_") as in_dir, \
            tempfile.TemporaryDirectory(prefix="oda_conv_out_") as out_dir:
        staged_dwg = os.path.join(in_dir, os.path.basename(dwg_path))
        shutil.copyfile(dwg_path, staged_dwg)

        # Sintaxe de linha de comando do ODA File Converter (modo batch):
        # ODAFileConverter <entrada> <saida> <versao> <tipo> <recursivo 0/1> <audit 0/1>
        args = [oda_exe, in_dir, out_dir, DXF_OUTPUT_VERSION, "DXF", "0", "1"]
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=CONVERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise OdaConversionError(
                "O ODA File Converter nao respondeu dentro do tempo esperado "
                "({}s).".format(CONVERT_TIMEOUT_SECONDS)
            )
        except OSError as exc:
            raise OdaConversionError("Falha ao executar o ODA File Converter: {}".format(exc))

        generated = os.path.join(out_dir, base_name + ".dxf")
        if not os.path.isfile(generated):
            detail = (result.stderr or result.stdout or "").strip()
            msg = "O ODA File Converter nao gerou o arquivo DXF esperado."
            if detail:
                msg += " Detalhes: {}".format(detail)
            raise OdaConversionError(msg)

        out_parent = os.path.dirname(output_path)
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)
        shutil.copyfile(generated, output_path)

    return output_path
