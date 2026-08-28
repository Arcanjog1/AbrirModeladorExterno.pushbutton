# -*- coding: utf-8 -*-
"""Cifra/decifra o PAT do GitHub com uma senha (usado pelo loader).

Este arquivo NAO e' baixado pelo loader nem roda dentro do Revit: ele
existe para `gerar_token_cifrado.py` (que cria o blob) e para os testes.
O bloco entre os marcadores abaixo e' uma COPIA IDENTICA do que esta'
dentro do loader (`Script.py` / `script.py`) - o loader precisa ser um
arquivo unico e autossuficiente, entao a duplicacao e' proposital. O
teste `tests/test_cripto_token.py` compara os dois textos e falha se
alguem alterar um sem alterar o outro.
"""

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
