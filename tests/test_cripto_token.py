# -*- coding: utf-8 -*-
"""Testes do token cifrado por senha usado pelo loader.

Dois objetivos:

1. Garantir que o BLOCO CRIPTO embutido no loader e' identico ao de
   `ferramentas/cripto_token.py`. O loader tem que ser um arquivo unico e
   autossuficiente (e' o unico que fica solto na pasta do botao), entao o
   codigo e' duplicado de proposito - este teste e' o que impede as duas
   copias de divergirem em silencio.
2. Exercitar cifra/decifra de verdade: ida e volta, senha errada, blob
   adulterado, formato invalido e um vetor fixo (sal/nonce fixos), que
   pega qualquer mudanca acidental no algoritmo - uma mudanca dessas
   invalidaria todos os blobs ja' distribuidos.
"""

import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(ROOT, "ferramentas"))

import cripto_token  # noqa: E402

INICIO = "# ==== INICIO BLOCO CRIPTO"
FIM = "# ==== FIM BLOCO CRIPTO ===="

LOADER = os.path.join(ROOT, "script.py")


def _extrair_bloco(caminho):
    with io.open(caminho, encoding="utf-8") as fh:
        texto = fh.read()
    inicio = texto.find(INICIO)
    fim = texto.find(FIM)
    assert inicio != -1, "marcador de INICIO nao achado em " + caminho
    assert fim != -1, "marcador de FIM nao achado em " + caminho
    return texto[inicio:fim + len(FIM)]


def test_bloco_do_loader_e_identico_ao_de_ferramentas():
    do_loader = _extrair_bloco(LOADER)
    do_modulo = _extrair_bloco(os.path.join(ROOT, "ferramentas", "cripto_token.py"))
    assert do_loader == do_modulo, (
        "o bloco cripto do loader divergiu de ferramentas/cripto_token.py - "
        "as duas copias PRECISAM ser identicas (ver docstring deste teste)"
    )


def test_ida_e_volta():
    blob = cripto_token.cifrar_token("github_pat_abc123", "senha secreta")
    assert cripto_token.decifrar_token(blob, "senha secreta") == "github_pat_abc123"


def test_token_nao_aparece_em_texto_puro_no_blob():
    blob = cripto_token.cifrar_token("github_pat_abc123", "senha secreta")
    assert "github_pat_abc123" not in blob
    assert "tok1:" not in blob


def test_cada_cifragem_gera_blob_diferente():
    a = cripto_token.cifrar_token("mesmo_token", "mesma senha")
    b = cripto_token.cifrar_token("mesmo_token", "mesma senha")
    assert a != b  # sal/nonce aleatorios
    assert cripto_token.decifrar_token(a, "mesma senha") == "mesmo_token"
    assert cripto_token.decifrar_token(b, "mesma senha") == "mesmo_token"


def test_senha_errada():
    blob = cripto_token.cifrar_token("github_pat_abc123", "certa")
    with pytest.raises(cripto_token.SenhaIncorreta):
        cripto_token.decifrar_token(blob, "errada")


def test_blob_adulterado():
    blob = cripto_token.cifrar_token("github_pat_abc123", "senha")
    partes = blob.split("$")
    cifrado = bytearray(cripto_token._de_b64(partes[4]))
    cifrado[0] ^= 0xFF
    partes[4] = cripto_token._b64(bytes(cifrado))
    with pytest.raises(cripto_token.SenhaIncorreta):
        cripto_token.decifrar_token("$".join(partes), "senha")


@pytest.mark.parametrize(
    "blob",
    [
        "",
        "nao e' um blob",
        "MB1$200000$aaa$bbb",
        "XX9$200000$YWFh$YmJi$Y2Nj$ZGRk",
        "MB1$10$YWFh$YmJi$Y2Nj$ZGRk",  # iteracoes de menos
    ],
)
def test_blob_invalido(blob):
    with pytest.raises(cripto_token.BlobInvalido):
        cripto_token.decifrar_token(blob, "senha")


def test_vetor_fixo_nao_pode_mudar():
    """Sal/nonce fixos -> saida FIXA. Se este teste quebrar, o algoritmo
    mudou e TODO blob ja' distribuido (nos loaders instalados por ai)
    deixou de abrir - so' aceite a quebra se essa troca for intencional e
    acompanhada da redistribuicao dos loaders."""
    blob = cripto_token.cifrar_token(
        "github_pat_exemplo",
        "senha-de-teste",
        iteracoes=1000,
        sal=b"0123456789abcdef",
        nonce=b"fedcba9876543210",
    )
    assert blob == (
        "MB1$1000$MDEyMzQ1Njc4OWFiY2RlZg==$ZmVkY2JhOTg3NjU0MzIxMA==$"
        "2fbPHyFXQt3g0h3X9PEofcJ6mWjmyPI=$"
        "HLdy9QVP6jrXjnWW//OIpuGGNHl5dCzavV4v7SDyyGE="
    )
    assert cripto_token.decifrar_token(blob, "senha-de-teste") == "github_pat_exemplo"


def test_fallback_manual_do_pbkdf2_bate_com_o_do_hashlib(monkeypatch):
    """No IronPython nao existe hashlib.pbkdf2_hmac e o modulo cai na
    implementacao manual - ela precisa dar exatamente o mesmo resultado,
    senao um blob gerado aqui nao abriria la'."""
    import hashlib

    esperado = cripto_token._pbkdf2(b"senha", b"sal-fixo-16bytes", 1000, 64)
    monkeypatch.delattr(hashlib, "pbkdf2_hmac", raising=False)
    manual = cripto_token._pbkdf2(b"senha", b"sal-fixo-16bytes", 1000, 64)
    assert manual == esperado
