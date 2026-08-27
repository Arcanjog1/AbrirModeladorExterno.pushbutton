# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulation_preview import preview_wall_blocks, preview_walls


class TestModulationPreview(unittest.TestCase):
    def test_parede_que_fecha_exatamente_com_blocos_inteiros(self):
        # 40cm = junta(1) + B39(39) -> pier = 39, fecha com [39]
        preview = preview_wall_blocks(40.0)
        self.assertTrue(preview["closes"])
        self.assertEqual(preview["blocks"], [39])

    def test_parede_incompativel_ainda_devolve_sugestao(self):
        preview = preview_wall_blocks(43.0)
        self.assertIsNotNone(preview["suggested_length_cm"])
        self.assertIsInstance(preview["delta_cm"], float)

    def test_preview_walls_preserva_campos_originais(self):
        walls = [{"id": "W001", "start": (0, 0), "end": (300, 0),
                  "thickness_cm": 14.0, "length_cm": 40.0, "layer": "A-WALL",
                  "single_line": False}]
        result = preview_walls(walls)
        self.assertEqual(result[0]["id"], "W001")
        self.assertIn("modulation", result[0])
        self.assertTrue(result[0]["modulation"]["closes"])


if __name__ == "__main__":
    unittest.main()
