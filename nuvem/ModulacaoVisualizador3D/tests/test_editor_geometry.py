# -*- coding: utf-8 -*-
"""Edição geométrica usada pelo editor 3D, independente do Revit."""

import unittest

from wall_capture import (
    delete_capture_opening,
    duplicate_capture_opening,
    edit_capture_opening,
    edit_capture_wall,
)


def sample_capture():
    return {
        "wall_height_m": 2.8,
        "walls": [{
            "element_id": "W1", "start_cm": [0, 0], "end_cm": [400, 0],
            "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0,
        }],
        "openings": [{
            "element_id": "P1", "host_wall_id": "W1", "center_cm": [100, 0],
            "width_cm": 80, "height_cm": 210, "sill_cm": 0, "head_cm": 210,
        }],
    }


class TestEditorGeometry(unittest.TestCase):
    def test_porta_de_80_em_parede_de_4m_move_1m_em_uma_operacao(self):
        capture = sample_capture()

        edited, action = edit_capture_opening(
            capture, "P1", center_cm=[200, 35], width_cm=80,
            height_cm=210, sill_cm=0,
        )

        self.assertTrue(action["accepted"])
        self.assertEqual(edited["openings"][0]["center_cm"], [200.0, 0.0])
        self.assertEqual(action["affected_wall_ids"], ["W1"])
        self.assertEqual(capture["openings"][0]["center_cm"], [100, 0])

    def test_edita_altura_peitoril_e_largura_sem_sair_do_prisma(self):
        capture = sample_capture()

        edited, action = edit_capture_opening(
            capture, "P1", width_cm=100, height_cm=120, sill_cm=90,
        )

        self.assertTrue(action["accepted"])
        opening = edited["openings"][0]
        self.assertEqual(opening["width_cm"], 100.0)
        self.assertEqual(opening["sill_cm"], 90.0)
        self.assertEqual(opening["head_cm"], 210.0)
        _unchanged, rejected = edit_capture_opening(
            capture, "P1", height_cm=220, sill_cm=90,
        )
        self.assertFalse(rejected["accepted"])
        self.assertIn("altura da parede", rejected["reason"])

    def test_duplica_e_exclui_abertura_sem_mutar_snapshot_anterior(self):
        capture = sample_capture()

        duplicated, action = duplicate_capture_opening(capture, "P1", 100)

        self.assertTrue(action["accepted"])
        self.assertEqual(len(duplicated["openings"]), 2)
        self.assertEqual(len(capture["openings"]), 1)
        removed, delete_action = delete_capture_opening(duplicated, action["opening_id"])
        self.assertTrue(delete_action["accepted"])
        self.assertEqual(len(removed["openings"]), 1)

    def test_edita_comprimento_direcao_espessura_e_altura_da_parede(self):
        capture = sample_capture()

        edited, action = edit_capture_wall(
            capture, "W1", [10, 20], [10, 520], thickness_cm=19, height_cm=300,
        )

        self.assertTrue(action["accepted"])
        wall = edited["walls"][0]
        self.assertEqual(wall["start_cm"], [10.0, 20.0])
        self.assertEqual(wall["end_cm"], [10.0, 520.0])
        self.assertEqual(wall["thickness_cm"], 19.0)
        self.assertEqual(wall["height_cm"], 300.0)
        self.assertEqual(edited["openings"][0]["center_cm"], [10.0, 145.0])


if __name__ == "__main__":
    unittest.main()
