# -*- coding: utf-8 -*-
"""Testes de wall_validation.py."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wall_validation import validate_walls


def _wall(single_line):
    return {"single_line": single_line}


class TestWallValidation(unittest.TestCase):
    def test_sem_paredes_e_invalido(self):
        result = validate_walls([], {"possible_bonecas": []})
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["issues"]), 1)

    def test_maioria_face_unica_gera_alerta(self):
        walls = [_wall(True)] * 6 + [_wall(False)] * 4
        result = validate_walls(walls, {"possible_bonecas": []})
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["single_line_ratio"], 0.6, places=2)

    def test_minoria_face_unica_nao_gera_alerta(self):
        walls = [_wall(True)] * 2 + [_wall(False)] * 8
        result = validate_walls(walls, {"possible_bonecas": []})
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_bonecas_possiveis_geram_alerta_mesmo_com_pareamento_bom(self):
        walls = [_wall(False)] * 10
        result = validate_walls(walls, {"possible_bonecas": [(9.0, 40.0)]})
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["issues"]), 1)


if __name__ == "__main__":
    unittest.main()
