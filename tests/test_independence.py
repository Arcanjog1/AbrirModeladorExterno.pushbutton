# -*- coding: utf-8 -*-

import os


def test_script_uses_local_core_not_meu_botao():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(repo_root, "script.py")
    with open(script_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert 'os.path.join(_PANEL_ROOT, "MeuBotao.pushbutton")' not in source
    assert "if _HERE not in sys.path" in source


def test_local_core_copy_exists():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.isfile(os.path.join(repo_root, "core", "wall_modeling.py"))
    assert os.path.isfile(os.path.join(repo_root, "core", "capture_export.py"))
