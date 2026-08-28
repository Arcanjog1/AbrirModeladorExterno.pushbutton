# -*- coding: utf-8 -*-
"""Exportacao JSON exclusiva do botao AbrirModeladorExterno.

Este arquivo existe para manter as mudancas do Modelador Externo isoladas
neste repositorio independente.
"""

import datetime

try:
    from Autodesk.Revit.DB import GeometryInstance, Solid, ElementId
except ImportError:  # pragma: no cover
    GeometryInstance = object
    Solid = object

    class _ElementId(object):
        InvalidElementId = -1

    ElementId = _ElementId

try:
    from core.engine.tolerances import FEET_PER_METER
except ImportError:  # pragma: no cover
    FEET_PER_METER = 0.3048


FALLBACK_BLOCK_COLORS_RGB = {
    # Referencia visual fornecida a partir das familias exibidas no Revit.
    # A cor do material real continua tendo prioridade quando esta disponivel.
    "B39": (245, 245, 245),
    "B34": (155, 255, 155),
    "B54": (113, 186, 255),
    "B19": (255, 160, 200),
    "C09": (100, 150, 150),
    "C04": (155, 100, 50),
}
DEFAULT_BLOCK_COLOR_RGB = (170, 170, 170)

BLOCK_DISPLAY_NAMES = {
    "B39": "BLOCO INTEIRO - 14x19x39",
    "B34": "BLOCO 34 - 14x19x34",
    "B54": "BLOCO 54 - 14x19x54",
    "B19": "MEIO BLOCO - 14x19x19",
    "C09": "COMPENSADOR 14x19x9",
    "C04": "PASTILHA - 14x19X4",
}


def _ft_to_cm(value_ft):
    return value_ft * 100.0 / FEET_PER_METER


def lines_by_layer_to_segments_cm(lines_by_layer):
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
    result = []
    for opening in all_openings:
        center = opening.get("center_xy")
        width_ft = opening.get("width_ft")
        if center is None or width_ft is None:
            continue
        result.append({
            "element_id": opening.get("element_id"),
            "host_wall_id": opening.get("host_wall_id"),
            "type": opening.get("type") or opening.get("type_name"),
            "family": opening.get("family_name"),
            "level": opening.get("level"),
            "level_elevation_cm": _ft_to_cm(opening.get("level_elevation_ft", 0.0)),
            "center_cm": [_ft_to_cm(center.X), _ft_to_cm(center.Y)],
            "width_cm": _ft_to_cm(width_ft),
            "height_cm": _ft_to_cm(
                opening.get("head_z_abs", 0.0) - opening.get("sill_z_abs", 0.0)
            ),
            "sill_cm": _ft_to_cm(opening.get("sill_z_abs", 0.0)),
            "head_cm": _ft_to_cm(opening.get("head_z_abs", 0.0)),
            "center_source": opening.get("center_source"),
        })
    return result


def walls_to_json(walls, doc=None, height_param_id=None, base_offset_param_id=None):
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
        level_elevation_ft = None
        try:
            if doc is not None:
                level = doc.GetElement(wall.LevelId)
                level_name = getattr(level, "Name", "") or ""
                level_elevation_ft = getattr(level, "Elevation", None)
        except Exception:
            level_name = ""
            level_elevation_ft = None

        base_offset_ft = 0.0
        if base_offset_param_id is not None:
            try:
                param = wall.get_Parameter(base_offset_param_id)
                if param is not None:
                    base_offset_ft = param.AsDouble()
            except Exception:
                base_offset_ft = 0.0

        curve_base_z_ft = min(getattr(p0, "Z", 0.0), getattr(p1, "Z", 0.0))
        if level_elevation_ft is None:
            base_z_ft = curve_base_z_ft
        else:
            base_z_ft = level_elevation_ft + base_offset_ft

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
            "base_z_cm": _ft_to_cm(base_z_ft),
            "base_offset_cm": _ft_to_cm(base_offset_ft),
            "level_elevation_cm": _ft_to_cm(level_elevation_ft or 0.0),
            "top_z_cm": _ft_to_cm(base_z_ft + height_ft) if height_ft > 1e-9 else None,
            "thickness_cm": _ft_to_cm(getattr(wall, "Width", 0.0) or 0.0),
            "height_cm": _ft_to_cm(height_ft) if height_ft > 1e-9 else None,
            "level": level_name,
        })
    return result


def _symbol_representative_color_rgb(symbol, logical_code):
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
            "type_name": BLOCK_DISPLAY_NAMES.get(logical_code, logical_code),
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
    return {
        "schema_version": 2,
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
            "wall_source_mode": setup.get("wall_source_mode"),
        },
    }
