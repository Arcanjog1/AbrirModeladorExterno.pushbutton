# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulation_calculator import calculate_project_solutions, calculate_wall_solutions


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


if __name__ == "__main__":
    unittest.main()
