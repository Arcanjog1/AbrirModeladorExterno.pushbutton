#! python3
# -*- coding: utf-8 -*-
"""Abrir Modelador Externo - PushButton independente.

Ver o plano da "arquitetura do modelador externo" (2026-08-26,
C:\\Users\\CIVIX\\.claude\\plans\\stateful-tickling-thunder.md): em vez de
criar paredes/blocos reais direto no Revit, este botao so' CAPTURA os
dados necessarios (linhas do CAD por layer, aberturas ja colocadas,
Walls ja posicionadas, catalogo fixo de blocos) e exporta um JSON que o modelador externo
(ModulacaoVisualizador3D, projeto irmao, fora do Revit) consome para fazer
TODO o processamento pesado (correcao de paredes, modulacao de blocos) de
forma interativa, sem escrever nada no Revit ate' o usuario aprovar e
clicar em "Enviar para o Revit" (fase futura, ainda nao implementada
nem neste botao nem no modelador externo).

Reaproveita, SEM REESCREVER, as mesmas funcoes de captura copiadas para
este repositorio (import de core.wall_modeling, em `nuvem/core/`):
extract_lines_by_layer,
_build_opening_dict, load_fixed_block_catalog e os tipos/constantes
necessarios para validar Walls selecionadas. A conversao para o
schema JSON puro deste fluxo mora no arquivo duplicado
capture_export_external.py, dentro da pasta nuvem/ deste proprio botao.

ATENCAO - NAO TESTADO AO VIVO dentro do Revit (pedido explicito do
usuario, 2026-08-26: outra sessao estava usando a mesma conexao MCP com o
Revit neste momento, entao a verificacao ficou limitada a
`py -m py_compile` deste arquivo e aos testes automatizados de
core/capture_export.py). Validar na pratica (escolher um CAD real,
conferir o JSON gerado) antes de confiar no resultado.
"""
import json
import os
import sys
import tempfile
import time

from pyrevit import forms, revit, script


def _patch_pyrevit_forms_for_cpython():
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
    except Exception:
        return

    from System.Windows.Forms import (
        Form, Label, TextBox, Button, ListBox, DialogResult,
        FormStartPosition, FormBorderStyle, MessageBox, MessageBoxButtons,
        MessageBoxIcon, SelectionMode, SaveFileDialog, OpenFileDialog,
        FolderBrowserDialog,
    )

    def _txt(value):
        return value if isinstance(value, str) else str(value)

    def _compat_alert(msg, title=None, exitscript=False, yes=False, no=False, **kwargs):
        caption = _txt(title) if title else "Modulacao Automatica"
        if yes or no:
            result = MessageBox.Show(
                _txt(msg), caption, MessageBoxButtons.YesNo, MessageBoxIcon.Question
            )
            return result == DialogResult.Yes
        MessageBox.Show(_txt(msg), caption, MessageBoxButtons.OK, MessageBoxIcon.Information)
        if exitscript:
            sys.exit()
        return None

    def _compat_ask_for_string(default="", prompt="", title="", **kwargs):
        form = Form()
        form.Text = _txt(title) if title else "Modulacao Automatica"
        form.StartPosition = FormStartPosition.CenterScreen
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.MinimizeBox = False
        form.MaximizeBox = False
        form.Width = 460
        form.Height = 180

        label = Label()
        label.Text = _txt(prompt) if prompt else ""
        label.SetBounds(12, 12, 420, 60)
        label.AutoSize = False
        form.Controls.Add(label)

        textbox = TextBox()
        textbox.SetBounds(12, 78, 420, 24)
        textbox.Text = _txt(default) if default else ""
        form.Controls.Add(textbox)

        ok_button = Button()
        ok_button.Text = "OK"
        ok_button.DialogResult = DialogResult.OK
        ok_button.SetBounds(276, 112, 75, 28)
        form.Controls.Add(ok_button)

        cancel_button = Button()
        cancel_button.Text = "Cancelar"
        cancel_button.DialogResult = DialogResult.Cancel
        cancel_button.SetBounds(357, 112, 75, 28)
        form.Controls.Add(cancel_button)

        form.AcceptButton = ok_button
        form.CancelButton = cancel_button

        result = form.ShowDialog()
        if result == DialogResult.OK:
            return textbox.Text
        return None

    def _compat_select_from_list(items, title="", button_name="OK", multiselect=False, **kwargs):
        items = list(items)
        if not items:
            return [] if multiselect else None

        form = Form()
        form.Text = _txt(title) if title else "Modulacao Automatica"
        form.StartPosition = FormStartPosition.CenterScreen
        form.FormBorderStyle = FormBorderStyle.FixedDialog
        form.MinimizeBox = False
        form.MaximizeBox = False
        form.Width = 420
        form.Height = 420

        listbox = ListBox()
        listbox.SetBounds(12, 12, 380, 300)
        listbox.SelectionMode = (
            SelectionMode.MultiExtended if multiselect else SelectionMode.One
        )
        for item in items:
            listbox.Items.Add(_txt(item))
        listbox.SetSelected(0, True)
        form.Controls.Add(listbox)

        ok_button = Button()
        ok_button.Text = _txt(button_name) if button_name else "OK"
        ok_button.DialogResult = DialogResult.OK
        ok_button.SetBounds(216, 324, 75, 28)
        form.Controls.Add(ok_button)

        cancel_button = Button()
        cancel_button.Text = "Cancelar"
        cancel_button.DialogResult = DialogResult.Cancel
        cancel_button.SetBounds(297, 324, 75, 28)
        form.Controls.Add(cancel_button)

        form.AcceptButton = ok_button
        form.CancelButton = cancel_button

        result = form.ShowDialog()
        if result != DialogResult.OK:
            return None

        selected_indices = list(listbox.SelectedIndices)
        if not selected_indices:
            return None
        selected_items = [items[i] for i in selected_indices]
        return selected_items if multiselect else selected_items[0]

    class _CompatSelectFromList(object):
        @staticmethod
        def show(items, **kwargs):
            return _compat_select_from_list(items, **kwargs)

    def _compat_save_file(file_ext="", default_name="", title="", **kwargs):
        dialog = SaveFileDialog()
        dialog.Title = _txt(title) if title else "Salvar arquivo de captura"
        if file_ext:
            ext = _txt(file_ext).lstrip(".")
            dialog.Filter = "{0} files (*.{1})|*.{1}|All files (*.*)|*.*".format(ext.upper(), ext)
            dialog.DefaultExt = ext
            dialog.AddExtension = True
        else:
            dialog.Filter = "All files (*.*)|*.*"
        if default_name:
            dialog.FileName = _txt(default_name)
        dialog.RestoreDirectory = True
        result = dialog.ShowDialog()
        if result == DialogResult.OK:
            return dialog.FileName
        return None

    def _compat_pick_file(file_ext="", title="", **kwargs):
        dialog = OpenFileDialog()
        dialog.Title = _txt(title) if title else "Selecionar arquivo"
        if file_ext:
            ext = _txt(file_ext).lstrip(".")
            dialog.Filter = "{0} files (*.{1})|*.{1}|All files (*.*)|*.*".format(ext.upper(), ext)
            dialog.DefaultExt = ext
        else:
            dialog.Filter = "All files (*.*)|*.*"
        dialog.RestoreDirectory = True
        result = dialog.ShowDialog()
        if result == DialogResult.OK:
            return dialog.FileName
        return None

    def _compat_pick_folder(title="", **kwargs):
        dialog = FolderBrowserDialog()
        if title:
            dialog.Description = _txt(title)
        result = dialog.ShowDialog()
        if result == DialogResult.OK:
            return dialog.SelectedPath
        return None

    forms.alert = _compat_alert
    forms.ask_for_string = _compat_ask_for_string
    forms.SelectFromList = _CompatSelectFromList
    forms.save_file = _compat_save_file
    forms.pick_file = _compat_pick_file
    forms.pick_folder = _compat_pick_folder


try:
    _forms_already_patched = callable(forms.alert)
except Exception:
    _forms_already_patched = False
if not _forms_already_patched:
    _patch_pyrevit_forms_for_cpython()

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUTTON_SELF_ROOT = os.path.dirname(_HERE)
_PANEL_ROOT = os.path.dirname(_BUTTON_SELF_ROOT)
if _HERE in sys.path:
    sys.path.remove(_HERE)
sys.path.insert(0, _HERE)

import capture_export_external as capture_export  # noqa: E402
from core import wall_modeling  # noqa: E402

doc = revit.doc
uidoc = revit.uidoc

output = script.get_output()


def main():
    forms.alert(
        "Etapa 1 de 2\n\n"
        "Selecione a planta baixa/importacao/vinculo do AutoCAD que sera usada "
        "apenas como referencia visual no Modelador 3D.\n\n"
        "Depois de fechar este aviso, clique na planta no Revit.",
        title="Modelador 3D - Selecionar planta baixa",
    )
    cad_ref = revit.pick_element("Selecione a planta baixa/importacao/vinculo do AutoCAD")
    if not cad_ref:
        return

    # 2. Extrai as linhas por Layer (MESMA funcao do botao real).
    options = wall_modeling.Options()
    options.IncludeNonVisibleObjects = True
    geom_element = cad_ref.get_Geometry(options)
    if geom_element is None:
        forms.alert(
            "O elemento selecionado nao possui geometria (nao parece ser um CAD).",
            exitscript=True,
        )
        return

    cad_lines_by_layer = {}
    wall_modeling.extract_lines_by_layer(geom_element, cad_lines_by_layer)
    if not cad_lines_by_layer:
        forms.alert(
            "Nenhuma linha valida foi encontrada no CAD selecionado.\n"
            "Verifique se o elemento e' realmente um vinculo/importacao de CAD "
            "e se ha linhas retas (LINE) visiveis nele.",
            exitscript=True,
        )
        return

    selected_walls, all_openings, skipped_selection, estimated_openings = _select_walls_and_openings()
    if selected_walls is None:
        return
    if not selected_walls:
        forms.alert(
            "Nenhuma Wall valida foi selecionada. Selecione pelo menos uma "
            "Wall existente junto com as aberturas e tente novamente.",
            title="Modelador Externo",
        )
        return

    openings_source_note = (
        "selecao conjunta: {} Wall(s), {} abertura(s), {} elemento(s) ignorado(s), "
        "{} abertura(s) estimada(s) por bounding box"
        .format(len(selected_walls), len(all_openings), skipped_selection, estimated_openings)
    )
    output.print_md("- {}".format(openings_source_note))

    # 5. Catalogo fixo de blocos (MESMA funcao do botao real) - precisa do
    # projeto ja ter os tipos de bloco carregados, exatamente como a
    # Etapa 1 do botao real ja exige hoje.
    output.print_md("**Carregando catalogo fixo de blocos...**")
    catalog, missing = wall_modeling.load_fixed_block_catalog(doc)
    if missing:
        missing_desc = "\n".join(
            "- {} / {}: {}".format(m["family_name"], m["type_name"], m["reason"])
            for m in missing
        )
        proceed = forms.alert(
            "Alguns tipos de bloco do catalogo fixo nao foram encontrados no "
            "projeto:\n\n{}\n\n"
            "Continuar mesmo assim? (o modelador externo so' vai poder "
            "desenhar/modular com os blocos ENCONTRADOS)".format(missing_desc),
            yes=True, no=True,
        )
        if not proceed:
            return

    segments = capture_export.lines_by_layer_to_segments_cm(cad_lines_by_layer)
    walls_json = capture_export.walls_to_json(
        selected_walls,
        doc=doc,
        height_param_id=wall_modeling.BuiltInParameter.WALL_USER_HEIGHT_PARAM,
    )
    openings_json = capture_export.openings_to_json(all_openings)
    catalog_json = capture_export.catalog_to_json(catalog)
    setup = _build_setup_from_selected_walls(walls_json)

    payload = capture_export.build_capture_payload(
        segments=segments,
        walls_json=walls_json,
        openings_json=openings_json,
        catalog_json=catalog_json,
        setup=setup,
        level_name=setup.get("level") or "",
        source_label=doc.Title,
    )

    save_path = os.path.join(
        tempfile.gettempdir(),
        "{}_captura_modelador_externo_{}.json".format(
            _safe_filename(os.path.splitext(doc.Title)[0] or "modulacao"),
            time.strftime("%Y%m%d_%H%M%S"),
        ),
    )

    with open(save_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    output.print_md(
        "**Captura salva em:** `{}`\n\n"
        "- **Segmentos da planta baixa:** {}\n"
        "- **Walls selecionadas:** {}{}\n"
        "- **Aberturas coletadas:** {}\n"
        "- **Tipos de bloco no catalogo:** {}\n\n"
        "**Abrindo o Modelador 3D externo automaticamente...**".format(
            save_path,
            len(segments),
            len(walls_json),
            " ({} elemento(s) ignorado(s) na selecao conjunta)".format(skipped_selection) if skipped_selection else "",
            len(openings_json),
            len(catalog_json),
        )
    )

    launched = _launch_visualizer(save_path)
    if launched:
        output.print_md("Visualizador 3D aberto no navegador com a planta e modulação já carregadas.")


def _select_walls_and_openings():
    forms.alert(
        "Etapa 2 de 2\n\n"
        "Selecione JUNTO, na mesma selecao:\n"
        "- as Walls existentes que serao a base da modulacao;\n"
        "- as portas/janelas/aberturas relacionadas a essas Walls.\n\n"
        "Nao selecione linhas, blocos, cotas ou textos. Quando terminar, clique "
        "em Concluir na barra de opcoes do Revit.",
        title="Modelador 3D - Selecionar Walls e aberturas",
    )
    try:
        refs = uidoc.Selection.PickObjects(
            wall_modeling.ObjectType.Element,
            "Selecione Walls e aberturas juntas, depois clique em Concluir"
        )
    except Exception:
        return None, None, 0, 0

    walls = []
    openings = []
    skipped = 0
    estimated = 0
    for ref in refs:
        element = doc.GetElement(ref.ElementId)
        if isinstance(element, wall_modeling.Wall):
            location = getattr(element, "Location", None)
            if not isinstance(location, wall_modeling.LocationCurve):
                skipped += 1
                continue
            curve = getattr(location, "Curve", None)
            try:
                if curve is None or curve.Length < wall_modeling.MIN_SEGMENT_LENGTH_FT:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue
            walls.append(element)
            continue

        if isinstance(element, wall_modeling.FamilyInstance):
            opening, used_fallback = wall_modeling._build_opening_dict(element, True)
            if opening is None:
                skipped += 1
                continue
            if used_fallback:
                estimated += 1
            openings.append(opening)
            continue

        skipped += 1

    return walls, openings, skipped, estimated


def _build_setup_from_selected_walls(walls_json):
    thicknesses = sorted(set(
        round(w["thickness_cm"], 1)
        for w in walls_json
        if w.get("thickness_cm") and w["thickness_cm"] > 0
    ))
    level_votes = {}
    max_height_cm = 0.0
    for wall in walls_json:
        level = wall.get("level") or ""
        if level:
            level_votes[level] = level_votes.get(level, 0) + 1
        height = wall.get("height_cm") or 0.0
        if height > max_height_cm:
            max_height_cm = height
    level = max(level_votes.items(), key=lambda item: item[1])[0] if level_votes else ""
    return {
        "layer": None,
        "thicknesses_cm": thicknesses,
        "level": level,
        "height_m": (max_height_cm / 100.0) if max_height_cm else None,
        "openings_mode": "pick",
        "wall_source_mode": "revit_walls",
    }


def _safe_filename(value):
    chars = []
    for ch in value:
        chars.append(ch if (ch.isalnum() or ch in ("-", "_")) else "_")
    return "".join(chars).strip("_") or "modulacao"


def _find_visualizer_dir():
    env_dir = os.environ.get("MODULACAO_VISUALIZADOR_PATH")
    if env_dir and os.path.isdir(env_dir) and os.path.isfile(os.path.join(env_dir, "server.py")):
        return env_dir

    candidates = [
        os.path.join(_HERE, "ModulacaoVisualizador3D"),
        os.path.join(_BUTTON_SELF_ROOT, "ModulacaoVisualizador3D"),
        r"C:\Users\CIVIX\OneDrive\Área de Trabalho\Github\ModulacaoVisualizador3D",
        r"C:\Users\CIVIX\OneDrive\Área de Trabalho\Nova pasta\ModulacaoVisualizador3D",
        r"C:\Users\CIVIX\OneDrive\Área de Trabalho\ModulacaoVisualizador3D",
        os.path.normpath(os.path.join(_PANEL_ROOT, "..", "..", "..", "Github", "ModulacaoVisualizador3D")),
        os.path.normpath(os.path.join(_PANEL_ROOT, "..", "..", "..", "Nova pasta", "ModulacaoVisualizador3D")),
        os.path.normpath(os.path.join(_PANEL_ROOT, "..", "..", "..", "ModulacaoVisualizador3D")),
        os.path.normpath(os.path.join(_PANEL_ROOT, "..", "..", "ModulacaoVisualizador3D")),
    ]
    for c in candidates:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "server.py")):
            return os.path.abspath(c)
    return None


def _is_server_running(port=8080):
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _launch_visualizer(json_path, port=8080):
    import subprocess
    import time
    try:
        import urllib.parse as urlparse
    except ImportError:
        import urllib as urlparse

    vis_dir = _find_visualizer_dir()
    if not vis_dir:
        forms.alert(
            "Pasta do ModulacaoVisualizador3D nao encontrada.\n"
            "Verifique se o visualizador esta' na pasta em nuvem do botao: "
            "'AbrirModeladorExterno.pushbutton\\nuvem\\ModulacaoVisualizador3D' "
            "ou configure MODULACAO_VISUALIZADOR_PATH.",
            title="Modelador Externo",
        )
        return False

    if not _is_server_running(port):
        server_py = os.path.join(vis_dir, "server.py")
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW

        try:
            subprocess.Popen(
                ["py", "server.py", str(port)],
                cwd=vis_dir,
                creationflags=flags,
                shell=True,
                close_fds=True,
            )
        except Exception:
            try:
                subprocess.Popen(
                    [sys.executable, server_py, str(port)],
                    cwd=vis_dir,
                    creationflags=flags,
                    close_fds=True,
                )
            except Exception:
                pass

        for _ in range(25):
            time.sleep(0.1)
            if _is_server_running(port):
                break

    abs_path = os.path.abspath(json_path)
    try:
        quote_fn = urlparse.quote
    except AttributeError:
        quote_fn = lambda s: s.replace(" ", "%20")
    encoded_path = quote_fn(abs_path)
    url = "http://localhost:{}/?capture={}".format(port, encoded_path)

    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        os.system('start "" "{}"'.format(url))
    return True


if __name__ == "__main__":
    main()
