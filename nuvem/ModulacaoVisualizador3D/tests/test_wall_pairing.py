# -*- coding: utf-8 -*-
"""Testes de wall_pairing.py - segmentos sinteticos (sem DXF nenhum).

Desde a extracao do pareamento real para core/engine/wall_pairing.py (ver
ARQUITETURA_INTERATIVA.md), este modulo e' um
adaptador fino sobre o motor real - estes testes cobrem principalmente a
adaptacao (conversao cm<->pe', agrupamento por layer, formato do dict de
saida) e os casos que o pareamento simplificado anterior NAO cobria
(encontros em L/T, bonecas fora das espessuras escolhidas, duplicatas)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wall_pairing import pair_walls_from_segments, associate_entities_with_walls


def _seg(layer, x0, y0, x1, y1):
    return {"layer": layer, "start": (x0, y0), "end": (x1, y1)}


class TestWallPairing(unittest.TestCase):
    def test_par_simples_vira_uma_parede_com_eixo_no_meio(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 300, 14),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 1)
        wall = walls[0]
        self.assertAlmostEqual(wall["thickness_cm"], 14.0, places=2)
        self.assertAlmostEqual(wall["start"][1], 7.0, places=2)
        self.assertAlmostEqual(wall["end"][1], 7.0, places=2)
        self.assertAlmostEqual(wall["length_cm"], 300.0, places=2)
        self.assertFalse(wall["single_line"])
        # ponta livre nos dois lados - nenhuma outra parede por perto.
        self.assertEqual(wall["junctions"], ["FREE_END", "FREE_END"])

    def test_linhas_de_layers_diferentes_nao_pareiam(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-DOOR", 0, 14, 300, 14),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(w["single_line"] for w in walls))

    def test_distancia_fora_da_faixa_de_espessura_nao_pareia(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 100, 300, 100),  # 100cm de distancia - fora da faixa fisica (5-35cm)
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(w["single_line"] for w in walls))

    def test_linhas_nao_paralelas_nao_pareiam(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 0, 300),  # perpendicular
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(w["single_line"] for w in walls))

    def test_sobreposicao_insuficiente_nao_pareia(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            # paralela, distancia ok, mas so' 20cm de sobreposicao (~6%)
            _seg("A-WALL", 280, 14, 320, 14),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(w["single_line"] for w in walls))

    def test_multiplas_paredes_independentes(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 300, 14),
            _seg("A-WALL", 500, 0, 500, 200),
            _seg("A-WALL", 514, 0, 514, 200),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(not w["single_line"] for w in walls))
        thicknesses = sorted(round(w["thickness_cm"], 2) for w in walls)
        self.assertEqual(thicknesses, [14.0, 14.0])

    def test_ids_sao_sequenciais_e_unicos(self):
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 300, 14),
            _seg("A-WALL", 500, 0, 500, 200),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        ids = [w["id"] for w in walls]
        self.assertEqual(len(ids), len(set(ids)))

    def test_encontro_em_l_fecha_o_canto_e_marca_junction(self):
        # parede horizontal (0..500) + parede vertical (0..300), encontrando
        # perto da origem - o motor real deve ESTICAR as duas pontas ate' a
        # face oposta uma da outra e marcar o encontro como L_CORNER (o
        # pareamento simplificado anterior nao tinha nocao de junction
        # nenhuma).
        segments = [
            _seg("A-WALL", 0, 0, 500, 0),
            _seg("A-WALL", 0, 14, 500, 14),
            _seg("A-WALL", 14, 14, 14, 300),
            _seg("A-WALL", 0, 14, 0, 300),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(not w["single_line"] for w in walls))
        junction_kinds = sorted(k for w in walls for k in w["junctions"])
        self.assertEqual(junction_kinds, ["FREE_END", "FREE_END", "L_CORNER", "L_CORNER"])

    def test_boneca_fora_das_espessuras_escolhidas_e_reportada_no_diagnostico(self):
        # linha de 14cm (escolhida) + par isolado de 9cm (boneca) que o
        # usuario nao escolheu modelar - nao vira parede, mas aparece em
        # diagnostics["possible_bonecas"] (ver scan_possible_missed_bonecas).
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 300, 14),
            _seg("A-WALL", 400, 0, 420, 0),
            _seg("A-WALL", 400, 9, 420, 9),
        ]
        walls, diag = pair_walls_from_segments(segments, target_thicknesses_cm=[14.0])
        paired = [w for w in walls if not w["single_line"]]
        self.assertEqual(len(paired), 1)
        self.assertAlmostEqual(paired[0]["thickness_cm"], 14.0, places=2)
        self.assertEqual(len(diag["possible_bonecas"]), 1)
        dist_cm, _overlap_cm = diag["possible_bonecas"][0]
        self.assertAlmostEqual(dist_cm, 9.0, places=1)

    def test_duplicata_e_removida_e_contada_no_diagnostico(self):
        # duas linhas quase coincidentes (hachura duplicada) alem do par
        # real - deduplicate_walls deve manter so' uma parede aqui.
        segments = [
            _seg("A-WALL", 0, 0, 300, 0),
            _seg("A-WALL", 0, 14, 300, 14),
            _seg("A-WALL", 0, 0.5, 300, 0.5),
            _seg("A-WALL", 0, 14.5, 300, 14.5),
        ]
        walls, diag = pair_walls_from_segments(segments, target_thicknesses_cm=[14.0])
        paired = [w for w in walls if not w["single_line"]]
        self.assertEqual(len(paired), 1)
        self.assertGreaterEqual(diag["duplicates_removed"], 1)


    def test_duplicata_mais_encontro_em_l_nao_quebra_o_indice_de_juncao(self):
        # Regressao (2026-08-26): deduplicate_walls precisa rodar ANTES de
        # extend_wall_ends_to_junctions (mesma ordem do motor real em
        # wall_modeling.py) - na ordem errada, o junction_map calculado
        # antes da deduplicacao referencia indices de uma lista que depois
        # e' reordenada/encolhida por deduplicate_walls, causando
        # "IndexError: list index out of range" dentro de build_wall_graph
        # (reproduzido com um DWG real de ~900 linhas). Este caso sintetico
        # junta os dois ingredientes (parede duplicada + encontro em L) na
        # mesma chamada para travar a ordem certa.
        segments = [
            # parede A: desenhada duas vezes (hachura/cota duplicada) -
            # deduplicate_walls precisa colapsar isso em 1 so'.
            _seg("A-WALL", 0, 0, 500, 0),
            _seg("A-WALL", 0, 14, 500, 14),
            _seg("A-WALL", 0, 0.3, 500, 0.3),
            _seg("A-WALL", 0, 14.3, 500, 14.3),
            # parede B: encontra a parede A num canto em L perto da origem.
            _seg("A-WALL", 14, 14, 14, 300),
            _seg("A-WALL", 0, 14, 0, 300),
        ]
        walls, _diag = pair_walls_from_segments(segments, target_thicknesses_cm=[14.0])
        paired = [w for w in walls if not w["single_line"]]
        self.assertEqual(len(paired), 2)
        junction_kinds = sorted(k for w in paired for k in w["junctions"])
        self.assertIn("L_CORNER", junction_kinds)

    def test_associacao_entidade_parede_marca_wall_id_das_duas_faces(self):
        segments = [
            _seg("A-WALL", 0, 0, 500, 0),
            _seg("A-WALL", 0, 14, 500, 14),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        entities = [dict(s) for s in segments]
        associate_entities_with_walls(entities, walls)
        self.assertTrue(all(e["wall_id"] == "W001" for e in entities))

    def test_entidade_sem_parede_correspondente_fica_com_wall_id_none(self):
        segments = [
            _seg("A-WALL", 0, 0, 500, 0),
            _seg("A-WALL", 0, 14, 500, 14),
        ]
        walls, _diag = pair_walls_from_segments(segments)
        # entidade solta, bem longe de qualquer parede - nao deve associar.
        soltas = [_seg("A-WALL", 2000, 2000, 2050, 2000)]
        associate_entities_with_walls(soltas, walls)
        self.assertIsNone(soltas[0]["wall_id"])


if __name__ == "__main__":
    unittest.main()
