# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulation_calculator import (
    calculate_capture_solutions, calculate_project_solutions, calculate_wall_solutions,
)


class TestModulationCalculator(unittest.TestCase):
    def test_calcula_com_junta_real_entre_blocos(self):
        result = calculate_wall_solutions({
            "length_cm": 79, "left_tie": "livre", "right_tie": "livre", "max_results": 10,
        })

        self.assertTrue(result["ok"])
        self.assertTrue(any(solution["sequence"] == ["B39", "B39"] for solution in result["solutions"]))
        solution = next(solution for solution in result["solutions"] if solution["sequence"] == ["B39", "B39"])
        self.assertEqual(solution["occupied_length_cm"], 79.0)

    def test_alias_free_da_interface_e_tratado_como_ponta_livre(self):
        result = calculate_wall_solutions({
            "length_cm": 79, "left_tie": "free", "right_tie": "open",
        })

        self.assertTrue(result["ok"])
        self.assertFalse(result["rejected_conditions"])
        self.assertTrue(any(solution["sequence"] == ["B39", "B39"] for solution in result["solutions"]))

    def test_amarração_l_exige_b34_sem_subtracao_manual(self):
        result = calculate_wall_solutions({
            "length_cm": 74, "left_tie": "L", "right_tie": "livre",
        })

        self.assertTrue(result["ok"])
        solution = next(solution for solution in result["solutions"] if solution["sequence"] == ["B34", "B39"])
        self.assertEqual(solution["left_required"], ["B34"])
        self.assertEqual(solution["occupied_length_cm"], 74.0)

    def test_meio_bloco_nao_fecha_trecho_entre_duas_amarrações(self):
        result = calculate_wall_solutions({
            "length_cm": 89, "left_tie": "L", "right_tie": "L", "allowed_codes": ["B34", "B19"],
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["total_found"], 0)

    def test_t_apresenta_variantes_com_hipotese_explicita(self):
        result = calculate_wall_solutions({
            "length_cm": 94, "left_tie": "T", "right_tie": "livre", "allowed_codes": ["B54", "B39", "B34"],
        })

        self.assertTrue(result["ok"])
        self.assertTrue(any("T — parede principal" == solution["left_tie"] for solution in result["solutions"]))
        self.assertTrue(any(solution["assumptions"] for solution in result["solutions"]))

    def test_modo_projeto_expoe_limite_da_otimizacao_global(self):
        result = calculate_project_solutions({"walls": [
            {"id": "P1", "length_cm": 79, "left_tie": "livre", "right_tie": "livre"},
        ]})

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "independent_walls")
        self.assertEqual(result["global_optimization"], "pending_geometry_graph")
        self.assertEqual(result["walls"][0]["wall_id"], "P1")

    def test_captura_usa_solver_completo_e_expoe_dependencias(self):
        def block(length, cells, special=False, compensator=False):
            return {
                "length_cm": length, "height_cm": 19, "width_cm": 14,
                "cells_local_cm": [
                    {"center_cm": [center, 0], "size_cm": [size, 14]}
                    for center, size in cells
                ],
                "is_special_bond": special, "is_compensator": compensator,
            }

        capture = {
            "walls": [{"element_id": "W1", "start_cm": [0, 0], "end_cm": [119, 0],
                       "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0, "level": "N1"}],
            "openings": [{"element_id": "D1", "host_wall_id": "W1", "center_cm": [59.5, 0],
                          "width_cm": 39, "sill_cm": 0, "head_cm": 210}],
            "catalog": {
                "B39": block(39, [(-9.9, 15.7), (9.9, 15.8)]),
                "B34": block(34, [(-10.2, 10.7), (7.4, 15.7)], special=True),
                "B54": block(54, [(-19.5, 15.8), (0, 12.5), (19.5, 15.8)], special=True),
                "B19": block(19, [(0, 15.7)]),
                "C09": block(9, [], compensator=True), "C04": block(4, [], compensator=True),
            },
        }
        result = calculate_capture_solutions(capture)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "capture_solver")
        self.assertEqual(result["source_of_truth"], "core.engine.wall_stepper.solve_building_blocks")
        self.assertTrue(result["selected_solution"]["blocks"])
        self.assertEqual(result["sectors"][0]["wall_id"], "W1")
        self.assertIn("wall_statuses", result["selected_solution"])


if __name__ == "__main__":
    unittest.main()
