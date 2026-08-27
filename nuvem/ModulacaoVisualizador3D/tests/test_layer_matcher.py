# -*- coding: utf-8 -*-
"""Testes de layer_matcher.py - DXF sintetico com um layer de paredes de
verdade e um layer de "ruido" (linhas soltas, sem cara de parede)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf

from layer_matcher import analyze_layers


def _make_dxf(tmp_path, wall_layer_name="A-WALL-1"):
    doc = ezdxf.new(setup=False)
    doc.header["$INSUNITS"] = 5  # cm
    doc.layers.add(wall_layer_name)
    doc.layers.add("TEXTO")
    msp = doc.modelspace()
    # layer de paredes de verdade: 3 pares paralelos (6 linhas, todas pareiam)
    for base_x in (0, 400, 800):
        msp.add_line((base_x, 0), (base_x + 300, 0), dxfattribs={"layer": wall_layer_name})
        msp.add_line((base_x, 14), (base_x + 300, 14), dxfattribs={"layer": wall_layer_name})
    # layer de ruido: linhas curtas, nao paralelas entre si, sem par valido
    msp.add_line((0, 0), (10, 37), dxfattribs={"layer": "TEXTO"})
    msp.add_line((50, 0), (55, 5), dxfattribs={"layer": "TEXTO"})
    msp.add_line((100, 100), (100, 250), dxfattribs={"layer": "TEXTO"})
    doc.saveas(tmp_path)


class TestLayerMatcher(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)

    def tearDown(self):
        os.remove(self.path)

    def test_layer_de_paredes_tem_confianca_alta_so_com_geometria(self):
        _make_dxf(self.path)
        results = analyze_layers(self.path)
        by_layer = {r["layer"]: r for r in results}
        self.assertAlmostEqual(by_layer["A-WALL-1"]["geometry_score"], 1.0, places=2)
        self.assertEqual(by_layer["A-WALL-1"]["status"], "OK")
        self.assertIsNone(by_layer["A-WALL-1"]["name_score"])

    def test_layer_de_ruido_tem_confianca_baixa(self):
        _make_dxf(self.path)
        results = analyze_layers(self.path)
        by_layer = {r["layer"]: r for r in results}
        self.assertAlmostEqual(by_layer["TEXTO"]["geometry_score"], 0.0, places=2)
        self.assertEqual(by_layer["TEXTO"]["status"], "ATENCAO")

    def test_nome_esperado_e_reconhecido_mesmo_com_sufixo(self):
        _make_dxf(self.path, wall_layer_name="A-WALL-1")
        results = analyze_layers(self.path, expected_layers=["A-WALL"])
        by_layer = {r["layer"]: r for r in results}
        wall_result = by_layer["A-WALL-1"]
        self.assertEqual(wall_result["matched_expected"], "A-WALL")
        self.assertGreater(wall_result["name_score"], 0.7)
        self.assertEqual(wall_result["status"], "OK")

    def test_resultado_ordenado_por_confianca_decrescente(self):
        _make_dxf(self.path)
        results = analyze_layers(self.path)
        confidences = [r["confidence"] for r in results]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_entity_count_bate_com_quantidade_de_linhas(self):
        _make_dxf(self.path)
        results = analyze_layers(self.path)
        by_layer = {r["layer"]: r for r in results}
        self.assertEqual(by_layer["A-WALL-1"]["entity_count"], 6)
        self.assertEqual(by_layer["TEXTO"]["entity_count"], 3)


if __name__ == "__main__":
    unittest.main()
