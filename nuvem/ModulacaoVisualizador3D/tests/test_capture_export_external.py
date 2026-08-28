# -*- coding: utf-8 -*-
import os
import sys
import unittest

NUVEM_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, NUVEM_DIR)

from capture_export_external import (  # noqa: E402
    BLOCK_DISPLAY_NAMES, FALLBACK_BLOCK_COLORS_RGB, catalog_to_json,
    openings_to_json, walls_to_json,
)


class Point(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class Curve(object):
    def __init__(self, start, end):
        self.points = [start, end]

    def GetEndPoint(self, index):
        return self.points[index]


class Param(object):
    def __init__(self, value):
        self.value = value

    def AsDouble(self):
        return self.value


class Id(object):
    def __init__(self, value):
        self.value = value

    def ToString(self):
        return str(self.value)


class Wall(object):
    def __init__(self):
        self.Location = type("Location", (), {"Curve": Curve(Point(0, 0, 0), Point(10, 0, 0))})()
        self.LevelId = Id(3)
        self.Id = Id(101)
        self.Width = 0.5

    def get_Parameter(self, param_id):
        return Param({"height": 9.0, "offset": 1.0}[param_id])


class TestCaptureExportExternal(unittest.TestCase):
    def test_wall_base_uses_level_elevation_plus_offset(self):
        level = type("Level", (), {"Name": "Nivel 2", "Elevation": 10.0})()
        doc = type("Doc", (), {"GetElement": lambda self, _id: level})()

        result = walls_to_json([Wall()], doc, "height", "offset")[0]

        self.assertEqual(result["element_id"], "101")
        self.assertEqual(result["level"], "Nivel 2")
        self.assertAlmostEqual(result["base_z_cm"], 11.0 * 30.48)
        self.assertAlmostEqual(result["top_z_cm"], 20.0 * 30.48)

    def test_opening_preserves_host_level_and_dimensions(self):
        opening = {
            "element_id": "201", "host_wall_id": "101", "type": "Porta 91",
            "family_name": "Portas", "level": "Nivel 2", "level_elevation_ft": 10.0,
            "center_xy": Point(5, 2, 0), "width_ft": 3.0,
            "sill_z_abs": 10.0, "head_z_abs": 17.0,
        }

        result = openings_to_json([opening])[0]

        self.assertEqual(result["host_wall_id"], "101")
        self.assertEqual(result["level"], "Nivel 2")
        self.assertAlmostEqual(result["height_cm"], 7.0 * 30.48)

    def test_catalog_identifies_types_and_uses_reference_colors(self):
        catalog = {
            code: {
                "symbol": object(), "length_cm": length, "height_cm": 19.0,
                "width_cm": 14.0, "cells_local": [],
                "is_special_bond": False, "is_compensator": code.startswith("C"),
            }
            for code, length in (("B39", 39), ("B34", 34), ("B54", 54),
                                 ("B19", 19), ("C09", 9), ("C04", 4))
        }

        result = catalog_to_json(catalog, lambda _symbol, code: FALLBACK_BLOCK_COLORS_RGB[code])

        self.assertEqual(set(result), set(BLOCK_DISPLAY_NAMES))
        for code, entry in result.items():
            self.assertEqual(entry["type_name"], BLOCK_DISPLAY_NAMES[code])
            self.assertEqual(entry["color_rgb"], list(FALLBACK_BLOCK_COLORS_RGB[code]))


if __name__ == "__main__":
    unittest.main()
