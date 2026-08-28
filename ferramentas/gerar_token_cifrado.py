# -*- coding: utf-8 -*-
"""Gera o TOKEN CIFRADO que o loader destrava com uma senha.

Rode isto UMA VEZ (na maquina do mantenedor, nunca na do usuario final):

    python3 ferramentas/gerar_token_cifrado.py

Ele pergunta o PAT do GitHub e a senha que voce quer usar, e imprime uma
linha `MB1$...`. Cole essa linha em `TOKEN_CIFRADO = "..."` dentro do
loader dos DOIS repositorios (Script.py / script.py) - ou salve-a num
arquivo `token_cifrado.dat` ao lado do loader, se preferir trocar o token
sem mexer no codigo.

O PAT NAO fica em texto puro em lugar nenhum: quem tiver o arquivo mas nao
souber a senha nao consegue le'-lo (PBKDF2-HMAC-SHA256, 200000 iteracoes).
Quem souber a senha E tiver o arquivo consegue - por isso o token deve ser
fine-grained, so' `Contents: Read-only`, so' nesses dois repositorios.

Para conferir um blob ja' existente:

    python3 ferramentas/gerar_token_cifrado.py --verificar
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cripto_token import (  # noqa: E402
    BlobInvalido,
    SenhaIncorreta,
    cifrar_token,
    decifrar_token,
)


def _perguntar_oculto(rotulo):
    try:
        return getpass.getpass(rotulo)
    except Exception:
        # Terminal sem suporte a entrada oculta (alguns consoles do Windows).
        sys.stdout.write(rotulo + " (VISIVEL na tela) ")
        sys.stdout.flush()
        return sys.stdin.readline().rstrip("\n")


def _verificar():
    blob = input("Cole o blob MB1$... : ").strip()
    senha = _perguntar_oculto("Senha: ")
    try:
        token = decifrar_token(blob, senha)
    except SenhaIncorreta:
        print("\nSENHA INCORRETA (ou blob adulterado).")
        return 1
    except BlobInvalido as erro:
        print("\nBlob invalido: {0}".format(erro))
        return 1
    print("\nOK - senha confere. Token: {0}...{1} ({2} caracteres)".format(
        token[:8], token[-4:], len(token)
    ))
    return 0


def _gerar():
    token = _perguntar_oculto("Cole o PAT do GitHub (github_pat_... ou ghp_...): ").strip()
    if not token:
        print("Nenhum token informado - nada a fazer.")
        return 1

    senha = _perguntar_oculto("Senha que os usuarios vao digitar: ").strip()
    if not senha:
        print("Senha vazia - nada a fazer.")
        return 1
    if senha != _perguntar_oculto("Repita a senha: ").strip():
        print("As senhas nao conferem - nada a fazer.")
        return 1
    if len(senha) < 8:
        print("AVISO: senha com menos de 8 caracteres e' facil de adivinhar "
              "para quem tiver o arquivo em maos.")

    blob = cifrar_token(token, senha)
    # Confere na hora: se decifrar nao devolver o mesmo token, algo esta'
    # errado e e' melhor descobrir agora do que dentro do Revit.
    assert decifrar_token(blob, senha) == token, "falha na verificacao interna"

    print("\n" + "=" * 70)
    print("Cole a linha abaixo em TOKEN_CIFRADO nos DOIS loaders")
    print("(ou salve-a em token_cifrado.dat ao lado do loader):")
    print("=" * 70)
    print(blob)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    if "--verificar" in sys.argv:
        sys.exit(_verificar())
    sys.exit(_gerar())
