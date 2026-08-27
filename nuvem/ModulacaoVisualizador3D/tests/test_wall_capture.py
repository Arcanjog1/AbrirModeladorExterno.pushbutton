# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulation_preview import preview_walls
from wall_capture import walls_from_capture, auto_adjust_walls, enrich_openings_for_view


class TestWallsFromCapture(unittest.TestCase):
    def test_usa_walls_existentes_como_base_geometrica(self):
        capture = {
            "level": "Nivel 1",
            "wall_height_m": 3.0,
            "walls": [
                {
                    "element_id": "101",
                    "start": [0.0, 0.0],
                    "end": [300.0, 0.0],
                    "thickness_cm": 14.0,
                    "height_cm": 280.0,
                }
            ],
            "openings": [
                {
                    "element_id": "201",
                    "center_cm": [150.0, 0.0],
                    "width_cm": 80.0,
                    "sill_cm": 0.0,
                    "head_cm": 210.0,
                }
            ],
        }

        walls, diagnostics = walls_from_capture(capture)

        self.assertEqual(diagnostics["source_mode"], "revit_walls")
        self.assertEqual(len(walls), 3)
        self.assertEqual(walls[0]["id"], "101_01")
        self.assertEqual(walls[0]["source"], "revit_wall")
        self.assertAlmostEqual(walls[0]["length_cm"], 110.0, places=2)
        self.assertEqual(walls[0]["openings_count"], 1)
        self.assertEqual(walls[1]["origin"], "abertura")
        self.assertAlmostEqual(walls[1]["length_cm"], 80.0, places=2)
        self.assertAlmostEqual(walls[1]["base_z_cm"], 210.0, places=2)
        self.assertAlmostEqual(walls[1]["height_cm"], 70.0, places=2)

    def test_enriquece_abertura_com_orientacao_da_parede(self):
        walls = [
            {
                "id": "101",
                "wall_group_id": "101",
                "start": (50.0, 0.0),
                "end": (50.0, 300.0),
                "thickness_cm": 14.0,
            }
        ]
        openings = [{"element_id": "201", "center_cm": [50.0, 120.0], "width_cm": 80.0}]

        enriched = enrich_openings_for_view(walls, openings)

        self.assertEqual(enriched[0]["wall_id"], "101")
        self.assertEqual(enriched[0]["axis_cm"], [0.0, 1.0])
        self.assertAlmostEqual(enriched[0]["angle_rad"], 1.57079632679, places=6)
        self.assertEqual(enriched[0]["wall_thickness_cm"], 14.0)


class TestAutoAdjustWalls(unittest.TestCase):
    def test_move_no_compartilhado_atualiza_parede_conectada(self):
        walls = preview_walls([
            {
                "id": "W001",
                "start": (0.0, 0.0),
                "end": (43.0, 0.0),
                "thickness_cm": 14.0,
                "length_cm": 43.0,
                "height_cm": 280.0,
                "base_z_cm": 0.0,
                "layer": "Walls Revit",
                "single_line": False,
            },
            {
                "id": "W002",
                "start": (43.0, 0.0),
                "end": (43.0, 100.0),
                "thickness_cm": 14.0,
                "length_cm": 100.0,
                "height_cm": 280.0,
                "base_z_cm": 0.0,
                "layer": "Walls Revit",
                "single_line": False,
            },
            {
                "id": "W003",
                "start": (0.0, 0.0),
                "end": (0.0, -100.0),
                "thickness_cm": 14.0,
                "length_cm": 100.0,
                "height_cm": 280.0,
                "base_z_cm": 0.0,
                "layer": "Walls Revit",
                "single_line": False,
            },
        ])

        adjusted, adjustment = auto_adjust_walls(walls)
        by_id = {wall["id"]: wall for wall in adjusted}

        self.assertTrue(adjustment["actions"])
        self.assertNotEqual(by_id["W001"]["end"], (43.0, 0.0))
        self.assertEqual(by_id["W001"]["end"], by_id["W002"]["start"])


if __name__ == "__main__":
    unittest.main()
