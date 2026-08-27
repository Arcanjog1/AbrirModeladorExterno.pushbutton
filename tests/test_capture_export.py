# -*- coding: utf-8 -*-
"""Testes de core/capture_export.py - conversao dos dados capturados de um
Revit real (linhas por layer, aberturas, catalogo de blocos) para o
payload JSON puro que o modelador externo (ModulacaoVisualizador3D)
consome. Ver o plano da "arquitetura do modelador externo" em
C:\\Users\\CIVIX\\.claude\\plans\\stateful-tickling-thunder.md.

So' testa a CONVERSAO (dados ja extraidos -> dict JSON-puro em cm), no'
a extracao em si (extract_lines_by_layer/collect_opening_instances/
load_fixed_block_catalog ja tem cobertura propria em test_script.py, na
raiz do repo) - por isso usa objetos XYZ/Line de `revit_stubs` (a mesma
geometria REAL usada pelo resto da suite) em vez de uma sessao do Revit.
"""
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BUTTON_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_BUTTON_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import revit_stubs  # noqa: E402

revit_stubs.install()

from core import capture_export  # noqa: E402

XYZ = revit_stubs.XYZ
Line = revit_stubs.Line
FEET_PER_METER = capture_export.FEET_PER_METER


def ft(cm):
    return cm / 100.0 * FEET_PER_METER


def seg(x0_cm, y0_cm, x1_cm, y1_cm):
    return Line.CreateBound(XYZ(ft(x0_cm), ft(y0_cm), 0.0), XYZ(ft(x1_cm), ft(y1_cm), 0.0))


class _Location(object):
    def __init__(self, curve):
        self.Curve = curve


class _Param(object):
    def __init__(self, value):
        self._value = value

    def AsDouble(self):
        return self._value


class _Wall(object):
    def __init__(self):
        self.Id = revit_stubs.ElementId(101)
        self.Location = _Location(seg(0, 0, 300, 0))
        self.Width = ft(14.0)
        self.LevelId = revit_stubs.ElementId(7)

    def get_Parameter(self, _param_id):
        return _Param(ft(280.0))


class _Doc(object):
    def GetElement(self, element_id):
        level = type("LevelObj", (), {})()
        level.Name = "Nivel 1" if element_id == revit_stubs.ElementId(7) else ""
        return level


class TestLinesByLayerToSegmentsCm(unittest.TestCase):
    def test_converte_pes_para_cm_preservando_layer(self):
        lines_by_layer = {
            "A-PAREDE": [seg(0, 0, 300, 0), seg(0, 14, 300, 14)],
            "A-PORTA": [seg(50, 0, 50, 14)],
        }
        segments = capture_export.lines_by_layer_to_segments_cm(lines_by_layer)
        self.assertEqual(len(segments), 3)
        by_layer = {}
        for s in segments:
            by_layer.setdefault(s["layer"], []).append(s)
        self.assertEqual(len(by_layer["A-PAREDE"]), 2)
        self.assertEqual(len(by_layer["A-PORTA"]), 1)
        first = by_layer["A-PAREDE"][0]
        self.assertAlmostEqual(first["start"][0], 0.0, places=3)
        self.assertAlmostEqual(first["end"][0], 300.0, places=2)


class TestOpeningsToJson(unittest.TestCase):
    def test_converte_abertura_completa(self):
        opening = {
            "element_id": "12345",
            "center_xy": XYZ(ft(120.0), ft(50.0), 0.0),
            "width_ft": ft(86.0),
            "sill_z_abs": ft(0.0),
            "head_z_abs": ft(220.0),
            "center_source": "geometria",
        }
        result = capture_export.openings_to_json([opening])
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["element_id"], "12345")
        self.assertAlmostEqual(entry["center_cm"][0], 120.0, places=2)
        self.assertAlmostEqual(entry["center_cm"][1], 50.0, places=2)
        self.assertAlmostEqual(entry["width_cm"], 86.0, places=2)
        self.assertAlmostEqual(entry["head_cm"], 220.0, places=2)
        self.assertEqual(entry["center_source"], "geometria")

    def test_ignora_abertura_sem_centro_ou_largura(self):
        openings = [
            {"element_id": "1", "center_xy": None, "width_ft": ft(86.0),
             "sill_z_abs": 0.0, "head_z_abs": ft(220.0)},
            {"element_id": "2", "center_xy": XYZ(0.0, 0.0, 0.0), "width_ft": None,
             "sill_z_abs": 0.0, "head_z_abs": ft(220.0)},
        ]
        result = capture_export.openings_to_json(openings)
        self.assertEqual(result, [])


class TestWallsToJson(unittest.TestCase):
    def test_converte_wall_real_para_geometria_base(self):
        result = capture_export.walls_to_json([_Wall()], doc=_Doc(), height_param_id=object())
        self.assertEqual(len(result), 1)
        wall = result[0]
        self.assertEqual(wall["element_id"], "101")
        self.assertEqual(wall["level"], "Nivel 1")
        self.assertAlmostEqual(wall["start"][0], 0.0, places=2)
        self.assertAlmostEqual(wall["end"][0], 300.0, places=2)
        self.assertAlmostEqual(wall["thickness_cm"], 14.0, places=2)
        self.assertAlmostEqual(wall["height_cm"], 280.0, places=2)


class TestCatalogToJson(unittest.TestCase):
    def test_converte_catalogo_e_usa_color_lookup_injetado(self):
        catalog = {
            "B34": {
                "symbol": object(),
                "length_cm": 34.0, "height_cm": 19.0, "width_cm": 14.0,
                "cells_local": [
                    {"center_local": (ft(5.0), ft(5.0)), "size_local": (ft(2.0), ft(3.0))},
                ],
                "is_special_bond": True, "is_compensator": False,
                "source_instance_id": revit_stubs.ElementId(1),
            },
        }
        colors = {"B34": (10, 20, 30)}
        result = capture_export.catalog_to_json(
            catalog, color_lookup_fn=lambda symbol, code: colors[code]
        )
        self.assertIn("B34", result)
        entry = result["B34"]
        self.assertEqual(entry["length_cm"], 34.0)
        self.assertEqual(entry["color_rgb"], [10, 20, 30])
        self.assertEqual(len(entry["cells_local_cm"]), 1)
        cell = entry["cells_local_cm"][0]
        self.assertAlmostEqual(cell["center_cm"][0], 5.0, places=2)
        self.assertAlmostEqual(cell["size_cm"][1], 3.0, places=2)
        # objetos vivos do Revit (symbol/source_instance_id) nao vazam para o JSON.
        self.assertNotIn("symbol", entry)
        self.assertNotIn("source_instance_id", entry)

    def test_color_lookup_default_nunca_lanca_com_simbolo_sem_geometria(self):
        catalog = {
            "C09": {
                "symbol": object(),  # sem get_Geometry - simula falha real
                "length_cm": 9.0, "height_cm": 19.0, "width_cm": 14.0,
                "cells_local": [],
                "is_special_bond": False, "is_compensator": True,
                "source_instance_id": revit_stubs.ElementId(2),
            },
        }
        result = capture_export.catalog_to_json(catalog)
        self.assertEqual(
            result["C09"]["color_rgb"],
            list(capture_export.FALLBACK_BLOCK_COLORS_RGB["C09"]),
        )


class TestBuildCapturePayload(unittest.TestCase):
    def test_monta_payload_com_schema_esperado(self):
        setup = {
            "layer": "A-PAREDE", "thicknesses_cm": [14.0],
            "level": "pb", "height_m": 2.8, "openings_mode": "auto",
            "extra_thicknesses": "",
        }
        payload = capture_export.build_capture_payload(
            segments=[{"layer": "A-PAREDE", "start": [0, 0], "end": [300, 0]}],
            openings_json=[],
            catalog_json={},
            setup=setup,
            level_name="pb",
            source_label="TESTE MODULACAO",
        )
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["level"], "pb")
        self.assertEqual(payload["wall_height_m"], 2.8)
        self.assertEqual(payload["setup"]["layer"], "A-PAREDE")
        self.assertEqual(payload["setup"]["openings_mode"], "auto")
        self.assertEqual(payload["walls"], [])
        self.assertNotIn("extra_thicknesses", payload["setup"])
        self.assertIn("generated_at", payload)


if __name__ == "__main__":
    unittest.main()
