# -*- coding: utf-8 -*-
"""Conversao dos dados capturados de um documento Revit REAL (linhas do
CAD por layer, aberturas ja colocadas, catalogo fixo de blocos) para um
payload JSON puro, consumido pelo modelador externo (`ModulacaoVisualizador3D`,
projeto irmao) - ver plano da "arquitetura do modelador externo"
(2026-08-26, `C:\\Users\\CIVIX\\.claude\\plans\\stateful-tickling-thunder.md`).

Este modulo NAO reimplementa nenhuma regra de captura: quem chama estas
funcoes continua usando `extract_lines_by_layer`/`collect_opening_instances`/
`load_fixed_block_catalog`, ja existentes e validados em `core/wall_modeling.py`
- aqui so' moram as conversoes pes->cm e a remocao dos objetos vivos do
Revit (Symbol/ElementId) que um FamilySymbol/FamilyInstance carregam, para
que o resultado seja `json.dumps`-avel.

Schema do payload (ver `build_capture_payload`):
    {"schema_version": 1, "generated_at": "...", "source": "...",
     "level": "pb", "wall_height_m": 2.8,
     "segments": [{"layer": "A-PAREDE", "start": [x_cm, y_cm],
                   "end": [x_cm, y_cm]}, ...],
     "openings": [{"element_id": "123", "center_cm": [x, y],
                   "width_cm": 86.0, "sill_cm": 0.0, "head_cm": 220.0,
                   "center_source": "geometria"}, ...],
     "catalog": {"B34": {"logical_code": "B34", "length_cm": 34.0,
                          "height_cm": 19.0, "width_cm": 14.0,
                          "cells_local_cm": [{"center_cm": [x, y],
                                              "size_cm": [dx, dy]}, ...],
                          "is_special_bond": True, "is_compensator": False,
                          "color_rgb": [r, g, b]}, ...},
     "setup": {"layer": "A-PAREDE", "thicknesses_cm": [14.0],
               "openings_mode": "auto"}}

`segments` usa EXATAMENTE o mesmo schema que
`ModulacaoVisualizador3D/dxf_reader.py::read_dxf_segments` ja produz a
partir de um DXF - o `wall_pairing.py` de la' (`pair_walls_from_segments`)
consome os dois sem nenhuma distincao."""

import datetime

try:
    from Autodesk.Revit.DB import GeometryInstance, Solid, ElementId
except ImportError:  # pragma: no cover - ambiente sem Revit (testes/standalone)
    try:
        from tests import revit_stubs
        GeometryInstance = revit_stubs.GeometryInstance
        Solid = revit_stubs.Solid
        ElementId = revit_stubs.ElementId
    except Exception:
        GeometryInstance = object
        Solid = object
        class _ElementId:
            InvalidElementId = -1
        ElementId = _ElementId

try:
    from core.engine.tolerances import FEET_PER_METER
except ImportError:  # pragma: no cover - so' acontece fora do layout real do botao
    FEET_PER_METER = 0.3048


# Cor de reserva (RGB 0-255) por codigo logico, usada SO' quando nenhum
# material com cor propria e' encontrado na geometria do simbolo (comum
# quando o bloco usa o material "por categoria", sem cor definida na
# propria familia) - garante que o modelador externo sempre tenha alguma
# cor para desenhar, mesmo sem material configurado no projeto.
FALLBACK_BLOCK_COLORS_RGB = {
    "B39": (196, 164, 132),
    "B34": (140, 172, 196),
    "B54": (172, 140, 196),
    "B19": (196, 140, 164),
    "C09": (150, 150, 150),
    "C04": (196, 188, 120),
}
DEFAULT_BLOCK_COLOR_RGB = (170, 170, 170)


def _ft_to_cm(value_ft):
    return value_ft * 100.0 / FEET_PER_METER


def lines_by_layer_to_segments_cm(lines_by_layer):
    """Converte `{layer: [Line, ...]}` (pes, ver `extract_lines_by_layer`)
    para a lista plana `[{"layer","start","end"}]` (cm) - mesmo schema de
    `dxf_reader.read_dxf_segments` no `ModulacaoVisualizador3D`."""
    segments = []
    for layer, lines in lines_by_layer.items():
        for line in lines:
            p0 = line.GetEndPoint(0)
            p1 = line.GetEndPoint(1)
            segments.append({
                "layer": layer,
                "start": [_ft_to_cm(p0.X), _ft_to_cm(p0.Y)],
                "end": [_ft_to_cm(p1.X), _ft_to_cm(p1.Y)],
            })
    return segments


def openings_to_json(all_openings):
    """Converte a lista de dicts de `get_opening_instances`/
    `collect_opening_instances` (pes, com objetos XYZ/ElementId reais) para
    dicts JSON-puros (cm, `element_id` como string). Aberturas sem
    `center_xy` (nunca deveria acontecer - `_build_opening_dict` sempre
    preenche antes de devolver - mas sem risco de derrubar a exportacao por
    causa de uma unica abertura malformada) sao ignoradas."""
    result = []
    for opening in all_openings:
        center = opening.get("center_xy")
        width_ft = opening.get("width_ft")
        if center is None or width_ft is None:
            continue
        result.append({
            "element_id": opening.get("element_id"),
            "center_cm": [_ft_to_cm(center.X), _ft_to_cm(center.Y)],
            "width_cm": _ft_to_cm(width_ft),
            "sill_cm": _ft_to_cm(opening.get("sill_z_abs", 0.0)),
            "head_cm": _ft_to_cm(opening.get("head_z_abs", 0.0)),
            "center_source": opening.get("center_source"),
        })
    return result


def walls_to_json(walls, doc=None, height_param_id=None):
    """Converte Walls reais selecionadas no Revit para JSON puro.

    O modelador externo usa esta lista como geometria base, em vez de
    recriar paredes a partir de pares de linhas do CAD. A planta CAD segue
    no payload apenas como referencia visual (`segments`).
    """
    result = []
    for wall in walls or []:
        location = getattr(wall, "Location", None)
        curve = getattr(location, "Curve", None)
        if curve is None:
            continue
        try:
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
        except Exception:
            continue

        height_ft = 0.0
        if height_param_id is not None:
            try:
                param = wall.get_Parameter(height_param_id)
                if param is not None:
                    height_ft = param.AsDouble()
            except Exception:
                height_ft = 0.0
        if height_ft <= 1e-9:
            try:
                bbox = wall.get_BoundingBox(None)
                if bbox is not None:
                    height_ft = bbox.Max.Z - bbox.Min.Z
            except Exception:
                height_ft = 0.0

        level_name = ""
        try:
            if doc is not None:
                level = doc.GetElement(wall.LevelId)
                level_name = getattr(level, "Name", "") or ""
        except Exception:
            level_name = ""

        wall_id = getattr(wall, "Id", None)
        try:
            wall_id_text = wall_id.ToString()
        except Exception:
            wall_id_text = str(wall_id) if wall_id is not None else ""

        result.append({
            "element_id": wall_id_text,
            "id": wall_id_text or None,
            "start": [_ft_to_cm(p0.X), _ft_to_cm(p0.Y)],
            "end": [_ft_to_cm(p1.X), _ft_to_cm(p1.Y)],
            "base_z_cm": _ft_to_cm(min(getattr(p0, "Z", 0.0), getattr(p1, "Z", 0.0))),
            "thickness_cm": _ft_to_cm(getattr(wall, "Width", 0.0) or 0.0),
            "height_cm": _ft_to_cm(height_ft) if height_ft > 1e-9 else None,
            "level": level_name,
        })
    return result


def _symbol_representative_color_rgb(symbol, logical_code):
    """Tenta ler a cor do MATERIAL atribuido a' geometria real do simbolo
    (mesma varredura de solidos de `_extract_block_cells_local_from_symbol`
    - a `symbol` precisa estar ATIVA, o que `load_fixed_block_catalog` ja
    garante antes de montar o catalogo). Devolve a primeira cor VALIDA
    encontrada em qualquer face de qualquer solido; nunca lanca - cai em
    `FALLBACK_BLOCK_COLORS_RGB`/`DEFAULT_BLOCK_COLOR_RGB` se nao achar
    nenhuma (comum quando o material e' "por categoria", sem cor propria,
    ou quando a geometria nao pode ser lida por qualquer motivo)."""
    try:
        from Autodesk.Revit.DB import Options, ViewDetailLevel
        options = Options()
        options.DetailLevel = ViewDetailLevel.Fine
        options.IncludeNonVisibleObjects = False
        geometry = symbol.get_Geometry(options)
        if geometry is None:
            return FALLBACK_BLOCK_COLORS_RGB.get(logical_code, DEFAULT_BLOCK_COLOR_RGB)

        solids = []

        def collect(geom_iterable):
            for item in geom_iterable:
                if isinstance(item, Solid) and item.Volume > 1e-9:
                    solids.append(item)
                elif isinstance(item, GeometryInstance):
                    collect(item.GetInstanceGeometry())

        collect(geometry)
        doc_of_symbol = symbol.Document
        for solid in solids:
            for face in solid.Faces:
                mat_id = face.MaterialElementId
                if mat_id is None or mat_id == ElementId.InvalidElementId:
                    continue
                material = doc_of_symbol.GetElement(mat_id)
                color = getattr(material, "Color", None)
                if color is not None and getattr(color, "IsValid", False):
                    return (color.Red, color.Green, color.Blue)
    except Exception:
        pass
    return FALLBACK_BLOCK_COLORS_RGB.get(logical_code, DEFAULT_BLOCK_COLOR_RGB)


def catalog_to_json(catalog, color_lookup_fn=_symbol_representative_color_rgb):
    """Converte o `catalog` de `load_fixed_block_catalog` (dict
    logical_code -> {symbol, length_cm, height_cm, width_cm, cells_local,
    is_special_bond, is_compensator, source_instance_id}) para uma forma
    JSON-pura: remove `symbol`/`source_instance_id` (objetos vivos do
    Revit), converte `cells_local` de pes para cm, e adiciona `color_rgb`
    (ver `_symbol_representative_color_rgb`).

    `color_lookup_fn` e' injetavel de proposito (testes passam um stub sem
    geometria real do Revit; o uso real dentro do Revit usa o default)."""
    result = {}
    for logical_code, entry in catalog.items():
        cells_cm = [
            {
                "center_cm": [_ft_to_cm(cell["center_local"][0]), _ft_to_cm(cell["center_local"][1])],
                "size_cm": [_ft_to_cm(cell["size_local"][0]), _ft_to_cm(cell["size_local"][1])],
            }
            for cell in entry.get("cells_local", [])
        ]
        result[logical_code] = {
            "logical_code": logical_code,
            "length_cm": entry["length_cm"],
            "height_cm": entry["height_cm"],
            "width_cm": entry["width_cm"],
            "cells_local_cm": cells_cm,
            "is_special_bond": entry["is_special_bond"],
            "is_compensator": entry["is_compensator"],
            "color_rgb": list(color_lookup_fn(entry["symbol"], logical_code)),
        }
    return result


def build_capture_payload(segments, openings_json, catalog_json, setup, level_name, source_label="", walls_json=None):
    """Monta o payload final (dict pronto para `json.dumps`) consumido pelo
    modelador externo. `setup` e' o dict devolvido por `ask_setup` (layer/
    thicknesses_cm/level/height_m/openings_mode) - so' os campos relevantes
    para o modelador externo sao repassados em `"setup"`."""
    return {
        "schema_version": 1,
        "generated_at": datetime.datetime.now().isoformat(),
        "source": source_label,
        "level": level_name,
        "wall_height_m": setup.get("height_m"),
        "segments": segments,
        "walls": walls_json or [],
        "openings": openings_json,
        "catalog": catalog_json,
        "setup": {
            "layer": setup.get("layer"),
            "thicknesses_cm": setup.get("thicknesses_cm"),
            "openings_mode": setup.get("openings_mode"),
        },
    }
