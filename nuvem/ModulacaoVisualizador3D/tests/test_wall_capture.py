# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wall_capture import (
    walls_from_capture, enrich_openings_for_view, adjust_capture_opening,
    adjust_capture_openings,
    solve_capture_block_candidates,
)


class TestWallsFromCapture(unittest.TestCase):
    def test_paredes_em_sequencia_formam_uma_parede_continua(self):
        capture = {
            "walls": [
                {"element_id": "101", "start": [0, 0], "end": [120, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0},
                {"element_id": "102", "start": [120, 0], "end": [300, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0},
            ],
            "openings": [
                {"element_id": "201", "host_wall_id": "102", "center_cm": [210, 0],
                 "width_cm": 80, "sill_cm": 0, "head_cm": 210},
            ],
        }

        walls, diagnostics = walls_from_capture(capture)

        self.assertEqual(len(walls), 1)
        self.assertAlmostEqual(walls[0]["length_cm"], 300.0, places=2)
        self.assertEqual(walls[0]["source_wall_ids"], ["101", "102"])
        self.assertEqual(walls[0]["openings_count"], 1)
        self.assertEqual(diagnostics["revit_walls_received"], 2)
        self.assertEqual(diagnostics["continuous_wall_count"], 1)

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
        self.assertEqual(len(walls), 1)
        self.assertEqual(walls[0]["id"], "101")
        self.assertEqual(walls[0]["source"], "revit_wall")
        self.assertAlmostEqual(walls[0]["length_cm"], 300.0, places=2)
        self.assertEqual(walls[0]["openings_count"], 1)
        self.assertEqual(len(walls[0]["cutout_segments"]), 3)
        lintel = [s for s in walls[0]["cutout_segments"] if s["origin"] == "abertura"][0]
        self.assertAlmostEqual(lintel["length_cm"], 80.0, places=2)
        self.assertAlmostEqual(lintel["base_z_cm"], 210.0, places=2)
        self.assertAlmostEqual(lintel["height_cm"], 70.0, places=2)

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

    def test_enriquece_abertura_na_parede_hospedeira_em_niveis_coincidentes(self):
        walls = [
            {"id": "101", "element_id": "101", "wall_group_id": "101", "level": "Nivel 1",
             "start": (0.0, 0.0), "end": (300.0, 0.0), "thickness_cm": 14.0},
            {"id": "102", "element_id": "102", "wall_group_id": "102", "level": "Nivel 2",
             "start": (0.0, 0.0), "end": (300.0, 0.0), "thickness_cm": 14.0},
        ]
        openings = [{"element_id": "201", "host_wall_id": "102", "level": "Nivel 2",
                     "center_cm": [150.0, 0.0], "width_cm": 80.0}]

        enriched = enrich_openings_for_view(walls, openings)

        self.assertEqual(enriched[0]["wall_id"], "102")

    def test_paredes_coincidentes_em_niveis_diferentes_nao_compartilham_abertura(self):
        capture = {
            "wall_height_m": 2.8,
            "walls": [
                {"element_id": "101", "start": [0, 0], "end": [300, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0, "level": "Nivel 1"},
                {"element_id": "102", "start": [0, 0], "end": [300, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 300, "level": "Nivel 2"},
            ],
            "openings": [
                {"element_id": "201", "host_wall_id": "102", "level": "Nivel 2",
                 "center_cm": [150, 0], "width_cm": 80, "sill_cm": 300, "head_cm": 510},
            ],
        }

        walls, diagnostics = walls_from_capture(capture)

        lower = [wall for wall in walls if wall["wall_group_id"] == "101"]
        upper = [wall for wall in walls if wall["wall_group_id"] == "102"]
        self.assertEqual(len(lower), 1)
        self.assertEqual(lower[0]["base_z_cm"], 0.0)
        self.assertEqual(len(upper), 1)
        lintel = [s for s in upper[0]["cutout_segments"] if s["origin"] == "abertura"][0]
        self.assertEqual(lintel["base_z_cm"], 510.0)
        self.assertEqual(lintel["height_cm"], 70.0)
        self.assertEqual(diagnostics["revit_walls_used"], 2)

    def test_aberturas_empilhadas_preservam_alvenaria_entre_e_acima(self):
        capture = {
            "walls": [
                {"element_id": "101", "start": [0, 0], "end": [300, 0],
                 "thickness_cm": 14, "height_cm": 600, "base_z_cm": 0, "level": "Nivel 1"},
            ],
            "openings": [
                {"element_id": "201", "host_wall_id": "101", "center_cm": [150, 0],
                 "width_cm": 80, "sill_cm": 0, "head_cm": 210},
                {"element_id": "202", "host_wall_id": "101", "center_cm": [150, 0],
                 "width_cm": 80, "sill_cm": 300, "head_cm": 500},
            ],
        }

        walls, _diagnostics = walls_from_capture(capture)
        infills = sorted(
            (segment["base_z_cm"], segment["height_cm"])
            for wall in walls
            for segment in wall["cutout_segments"]
            if segment["origin"] == "abertura"
        )
        self.assertIn((210.0, 90.0), infills)
        self.assertIn((500.0, 100.0), infills)

    def test_solver_fisico_respeita_base_e_retorna_acima_da_porta(self):
        def block(length, cells, special=False, compensator=False):
            return {
                "length_cm": length, "height_cm": 19, "width_cm": 14,
                "cells_local_cm": [
                    {"center_cm": [center, 0], "size_cm": [size, 14]}
                    for center, size in cells
                ],
                "is_special_bond": special, "is_compensator": compensator,
                "color_rgb": [10, 20, 30],
            }

        catalog = {
            "B39": block(39, [(-9.9, 15.7), (9.9, 15.8)]),
            "B34": block(34, [(-10.2, 10.7), (7.4, 15.7)], special=True),
            "B54": block(54, [(-19.5, 15.8), (0, 12.5), (19.5, 15.8)], special=True),
            "B19": block(19, [(0, 15.7)]),
            "C09": block(9, [], compensator=True),
            "C04": block(4, [], compensator=True),
        }
        capture = {
            "walls": [
                {"element_id": "101", "start": [0, 0], "end": [119, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 300, "level": "Nivel 2"},
            ],
            "openings": [
                {"element_id": "201", "host_wall_id": "101", "level": "Nivel 2",
                 "center_cm": [59.5, 0], "width_cm": 39, "sill_cm": 300, "head_cm": 510},
            ],
            "catalog": catalog,
        }

        candidates, diagnostics = solve_capture_block_candidates(capture)

        self.assertEqual(diagnostics["status"], "ok")
        self.assertTrue(candidates)
        self.assertTrue(all(candidate["z_cm"] >= 1.0 for candidate in candidates))
        self.assertTrue(any(candidate["z_cm"] >= 221.0 for candidate in candidates))
        self.assertEqual(diagnostics["z_reference_cm"], 300.0)
        self.assertEqual(diagnostics["blocks_below_reference_count"], 0)
        self.assertEqual(diagnostics["lintel_missing_count"], 0)
        self.assertTrue(all(candidate["color_rgb"] == [10, 20, 30] for candidate in candidates))
        self.assertTrue(any(candidate["cells_local_cm"] for candidate in candidates))

        edge_capture = dict(capture)
        edge_capture["openings"] = [dict(capture["openings"][0], center_cm=[19.5, 0])]
        _adjusted, action, _candidates, _diagnostics = adjust_capture_opening(
            edge_capture, "201", delta_cm=-1, automatic=False
        )
        self.assertFalse(action["accepted"])

        _adjusted, report, _candidates, diagnostics = adjust_capture_openings(capture)
        self.assertEqual(diagnostics["status"], "ok")
        self.assertEqual(len(report["actions"]), 1)

    def test_cota_negativa_da_planta_vira_zero_sem_mover_as_aberturas_relativas(self):
        capture = {
            "walls": [
                {"element_id": "101", "start": [0, 0], "end": [300, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": -75,
                 "level": "Nivel Terreo"},
            ],
            "openings": [
                {"element_id": "201", "host_wall_id": "101", "center_cm": [150, 0],
                 "width_cm": 80, "sill_cm": -75, "head_cm": 135},
            ],
        }

        walls, diagnostics = walls_from_capture(capture)

        self.assertEqual(diagnostics["z_reference_cm"], -75.0)
        self.assertEqual(walls[0]["base_z_cm"], 0.0)
        lintel = [s for s in walls[0]["cutout_segments"] if s["origin"] == "abertura"][0]
        self.assertEqual(lintel["base_z_cm"], 210.0)
        self.assertEqual(diagnostics["walls_below_reference_count"], 0)


if __name__ == "__main__":
    unittest.main()
