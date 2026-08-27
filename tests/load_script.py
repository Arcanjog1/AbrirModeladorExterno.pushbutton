# -*- coding: utf-8 -*-
"""Importa core/wall_modeling.py como modulo, com a API do Revit substituida
pelos dubles de revit_stubs - ver o cabecalho de la'.

Ate' 2026-08-24 este modulo carregava Script.py, que continha toda a logica
do motor. Desde entao Script.py virou so' um loader (baixa wall_modeling.py
do GitHub via System.Net/System.Security, que revit_stubs.py nao simula) e
a logica real passou para core/wall_modeling.py - e' isso que os testes
precisam exercitar."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# LAYOUT-AGNOSTICO (2026-08-27): esta suite precisa rodar em DOIS layouts
# diferentes, porque o repositorio unico foi dividido em um repo por
# .pushbutton:
#
#   a) pasta de extensao do pyRevit (o que existe em disco na maquina do
#      usuario): <raiz>/MinhaAba.tab/MeuPainel.panel/MeuBotao.pushbutton/nuvem/core/
#   b) repositorio independente MeuBotao.pushbutton, onde o conteudo do
#      botao esta' na RAIZ: <raiz>/nuvem/core/
#
# Em vez de fixar um dos dois (e quebrar no outro - ja aconteceu duas vezes,
# ver o historico de correcao de caminho aqui e em nuvem/tests/
# test_capture_export.py), procura o motor subindo a arvore. Falha com uma
# mensagem que diz ONDE procurou, nunca com um ImportError opaco.
def _find_engine():
    relative = os.path.join("nuvem", "core", "wall_modeling.py")
    tried = []
    directory = ROOT
    for _level in range(6):
        direct = os.path.join(directory, relative)
        tried.append(direct)
        if os.path.isfile(direct):
            return direct
        nested = os.path.join(
            directory, "MinhaAba.tab", "MeuPainel.panel", "MeuBotao.pushbutton", relative
        )
        tried.append(nested)
        if os.path.isfile(nested):
            return nested
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    raise RuntimeError(
        "nao achei core/wall_modeling.py. Procurei em: " + " | ".join(tried)
    )


SCRIPT_PATH = _find_engine()

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import revit_stubs  # noqa: E402

revit_stubs.install()


def load():
    """Devolve o modulo do Script.py ja importado (uma unica vez)."""
    if "script_under_test" in sys.modules:
        return sys.modules["script_under_test"]
    import types
    module = types.ModuleType("script_under_test")
    module.__file__ = SCRIPT_PATH
    with open(SCRIPT_PATH, "rb") as handle:
        source = handle.read().decode("utf-8")
    sys.modules["script_under_test"] = module
    exec(compile(source, SCRIPT_PATH, "exec"), module.__dict__)
    return module
