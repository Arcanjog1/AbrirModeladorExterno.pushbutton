# -*- coding: utf-8 -*-
"""Testes de dxf_reader.py - geram um DXF sintetico com ezdxf (a mesma
biblioteca usada para ler) e conferem o que read_dxf_segments devolve.
Nao depende de nenhum arquivo DWG/DXF real."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf

from dxf_reader import read_dxf_segments, list_layers_with_counts, detect_unit_scale_to_cm


def _make_dxf(tmp_path, insunits=5):
    doc = ezdxf.new(setup=False)
    doc.header["$INSUNITS"] = insunits
    doc.layers.add("A-WALL")
    doc.layers.add("A-DOOR")
    msp = doc.modelspace()
    # duas linhas paralelas em A-WALL, 14 "unidades" de distancia (uma parede)
    msp.add_line((0, 0), (300, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0, 14), (300, 14), dxfattribs={"layer": "A-WALL"})
    # uma polyline fechada (retangulo) em A-WALL
    msp.add_lwpolyline(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        close=True,
        dxfattribs={"layer": "A-WALL"},
    )
    # uma linha em outra layer, para testar o filtro
    msp.add_line((0, 0), (50, 50), dxfattribs={"layer": "A-DOOR"})
    doc.saveas(tmp_path)


class TestDxfReader(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)

    def tearDown(self):
        os.remove(self.path)

    def test_le_linhas_simples_com_layer(self):
        _make_dxf(self.path)
        segments = read_dxf_segments(self.path, layers=["A-WALL"])
        line_segments = [s for s in segments if s["start"][1] in (0, 14) and s["end"][1] in (0, 14)
                          and s["start"][0] in (0, 300) and abs(s["end"][0] - s["start"][0]) == 300]
        self.assertEqual(len(line_segments), 2)
        for seg in line_segments:
            self.assertEqual(seg["layer"], "A-WALL")

    def test_filtra_por_layer_case_insensitive(self):
        _make_dxf(self.path)
        segments = read_dxf_segments(self.path, layers=["a-wall"])
        self.assertTrue(all(s["layer"] == "A-WALL" for s in segments))
        self.assertGreater(len(segments), 0)

        segments_door = read_dxf_segments(self.path, layers=["A-DOOR"])
        self.assertEqual(len(segments_door), 1)

    def test_sem_filtro_le_todas_as_layers(self):
        _make_dxf(self.path)
        segments = read_dxf_segments(self.path)
        layers_found = set(s["layer"] for s in segments)
        self.assertEqual(layers_found, {"A-WALL", "A-DOOR"})

    def test_polyline_fechada_vira_4_segmentos(self):
        _make_dxf(self.path)
        segments = read_dxf_segments(self.path, layers=["A-WALL"])
        # 2 linhas soltas + 4 lados do retangulo fechado = 6
        self.assertEqual(len(segments), 6)

    def test_conversao_de_unidade_milimetros_para_cm(self):
        _make_dxf(self.path, insunits=4)  # 4 = milimetros
        segments = read_dxf_segments(self.path, layers=["A-WALL"])
        lengths = sorted(
            round(((s["end"][0] - s["start"][0]) ** 2 + (s["end"][1] - s["start"][1]) ** 2) ** 0.5, 3)
            for s in segments
        )
        # a linha de 300 unidades desenhada em mm deve virar 30cm
        self.assertIn(30.0, lengths)

    def test_unit_scale_override_ignora_o_cabecalho(self):
        _make_dxf(self.path, insunits=5)  # 5 = cm (fator 1.0)
        segments_default = read_dxf_segments(self.path, layers=["A-WALL"])
        segments_forced_mm = read_dxf_segments(self.path, layers=["A-WALL"], unit_scale_to_cm=0.1)
        len_default = max(abs(s["end"][0] - s["start"][0]) for s in segments_default)
        len_forced = max(abs(s["end"][0] - s["start"][0]) for s in segments_forced_mm)
        self.assertAlmostEqual(len_forced, len_default * 0.1)

    def test_list_layers_with_counts(self):
        _make_dxf(self.path)
        counts = list_layers_with_counts(self.path)
        self.assertEqual(counts.get("A-WALL"), 3)  # 2 linhas + 1 polyline
        self.assertEqual(counts.get("A-DOOR"), 1)

    def test_detect_unit_scale_to_cm_milimetros(self):
        _make_dxf(self.path, insunits=4)
        doc = ezdxf.readfile(self.path)
        self.assertAlmostEqual(detect_unit_scale_to_cm(doc), 0.1)

    def test_detect_unit_scale_to_cm_metros(self):
        _make_dxf(self.path, insunits=6)
        doc = ezdxf.readfile(self.path)
        self.assertAlmostEqual(detect_unit_scale_to_cm(doc), 100.0)

    def test_insert_e_explodido_e_linha_0_herda_layer_do_insert(self):
        doc = ezdxf.new(setup=False)
        doc.header["$INSUNITS"] = 5
        doc.layers.add("A-WALL")
        block = doc.blocks.new(name="SIMBOLO_PAREDE")
        # linha desenhada em "0" DENTRO do bloco - deve herdar a layer do
        # INSERT (convencao ByBlock), nao ficar em "0".
        block.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
        msp = doc.modelspace()
        msp.add_blockref("SIMBOLO_PAREDE", insert=(10, 20), dxfattribs={"layer": "A-WALL"})
        doc.saveas(self.path)

        counts = list_layers_with_counts(self.path)
        self.assertEqual(counts.get("A-WALL"), 1)
        self.assertNotIn("0", counts)

        segments = read_dxf_segments(self.path, layers=["A-WALL"])
        self.assertEqual(len(segments), 1)
        # a linha foi deslocada pelo ponto de insercao do bloco (10, 20).
        seg = segments[0]
        self.assertEqual(sorted([seg["start"][0], seg["end"][0]]), [10.0, 110.0])
        self.assertEqual(seg["start"][1], 20.0)
        self.assertEqual(seg["end"][1], 20.0)

    def test_linha_degenerada_e_ignorada(self):
        doc = ezdxf.new(setup=False)
        doc.header["$INSUNITS"] = 5
        doc.layers.add("A-WALL")
        msp = doc.modelspace()
        msp.add_line((5, 5), (5, 5), dxfattribs={"layer": "A-WALL"})
        doc.saveas(self.path)
        segments = read_dxf_segments(self.path, layers=["A-WALL"])
        self.assertEqual(segments, [])


if __name__ == "__main__":
    unittest.main()
