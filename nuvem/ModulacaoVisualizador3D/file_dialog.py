# -*- coding: utf-8 -*-
"""Abre a caixa de selecao de arquivos nativa do Windows (o mesmo dialogo
do Explorer) para escolher um .dwg, sem depender de nenhuma biblioteca
externa - so' subprocess + PowerShell (ja disponiveis em qualquer Windows).

Roda num processo separado (nao usa tkinter dentro do proprio servidor)
para nao ter que lidar com threads/apartments do Tk dentro do
ThreadingHTTPServer do server.py.
"""

import base64
import subprocess

_PS_SCRIPT = r"""
# Sem isso, caminhos com acentuacao (ex.: "USUARIOS", "MODULACAO") voltam
# corrompidos: por padrao o PowerShell escreve a saida redirecionada numa
# codificacao (OEM) diferente da que o Python usa para decodificar.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type -AssemblyName System.Drawing | Out-Null
# O dialogo e' acionado por um processo em background (o servidor local),
# sem janela propria em primeiro plano. Sem um "owner" TopMost, o Windows
# pode nao dar foco ao dialogo e ele fecha sozinho como Cancel. Um form
# invisivel TopMost como owner evita isso.
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(0, 0)
$owner.Show()
$owner.Activate()

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = "Arquivos DWG (*.dwg)|*.dwg|Todos os arquivos (*.*)|*.*"
$dialog.Title = "Selecionar arquivo DWG"
$dialog.CheckFileExists = $true
$result = $dialog.ShowDialog($owner)
$owner.Close()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    Write-Output $dialog.FileName
}
"""

DIALOG_TIMEOUT_SECONDS = 300


class DialogError(RuntimeError):
    """Falha ao abrir ou operar a caixa de selecao de arquivo."""


def _encode_command(script):
    # -EncodedCommand (Base64 de UTF-16LE) evita qualquer problema de
    # quoting/escaping ao passar um script multi-linha como argumento de
    # processo (passar o texto direto via -Command corrompe o parsing do
    # PowerShell quando o argumento contem quebras de linha).
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def pick_dwg_file():
    """Mostra o dialogo nativo do Windows para escolher um .dwg.

    Retorna o caminho absoluto escolhido, ou None se o usuario cancelar.
    Lanca DialogError se nao for possivel abrir o dialogo.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-EncodedCommand", _encode_command(_PS_SCRIPT)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=DIALOG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise DialogError("A caixa de selecao de arquivo demorou demais para responder.")
    except OSError as exc:
        raise DialogError("Falha ao abrir a caixa de selecao de arquivo: {}".format(exc))

    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise DialogError(
            "Falha ao abrir a caixa de selecao de arquivo."
            + (" Detalhes: {}".format(detail) if detail else "")
        )

    path = result.stdout.strip()
    return path or None


_PS_JSON_SCRIPT = _PS_SCRIPT.replace(
    'Arquivos DWG (*.dwg)|*.dwg|Todos os arquivos (*.*)|*.*',
    'Arquivos JSON (*.json)|*.json|Todos os arquivos (*.*)|*.*'
).replace(
    'Selecionar arquivo DWG',
    'Selecionar arquivo JSON de Captura'
)


def pick_json_file():
    """Mostra o dialogo nativo do Windows para escolher um arquivo .json de captura do Revit.

    Retorna o caminho absoluto escolhido, ou None se o usuario cancelar.
    Lanca DialogError se nao for possivel abrir o dialogo.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-EncodedCommand", _encode_command(_PS_JSON_SCRIPT)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=DIALOG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise DialogError("A caixa de selecao de arquivo demorou demais para responder.")
    except OSError as exc:
        raise DialogError("Falha ao abrir a caixa de selecao de arquivo: {}".format(exc))

    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise DialogError(
            "Falha ao abrir a caixa de selecao de arquivo."
            + (" Detalhes: {}".format(detail) if detail else "")
        )

    path = result.stdout.strip()
    return path or None
