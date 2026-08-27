# -*- coding: utf-8 -*-
"""Testes automatizados do Script.py, rodando FORA do Revit.

Como isto e' possivel: revit_stubs.py substitui a API do Revit/WinForms por
dubles - geometria de verdade (XYZ/Line fazem as contas reais) e controles
de janela falsos que guardam a arvore de controles. Ver o cabecalho de la'.

Rodar:  python tests/run_tests.py
"""

import load_script
import revit_stubs

XYZ = revit_stubs.XYZ
Line = revit_stubs.Line
m = load_script.load()
F = m.FEET_PER_METER

CASES = []


def case(func):
    CASES.append(func)
    return func


# --------------------------------------------------------------- helpers
def ft(cm):
    return cm / 100.0 * F


def to_cm(value_ft):
    return value_ft / F * 100.0


def seg(x0, y0, x1, y1):
    return Line.CreateBound(XYZ(ft(x0), ft(y0), 0.0), XYZ(ft(x1), ft(y1), 0.0))


def _cell(center_cm, size_cm, width_cm=8.0):
    return {"center_local": (ft(center_cm), 0.0), "size_local": (ft(size_cm), ft(width_cm))}


def _block(code, length_cm, cells):
    return {
        "symbol": None, "logical_code": code, "length_cm": float(length_cm),
        "height_cm": 19.0, "width_cm": 14.0, "cells_local": cells,
        "is_special_bond": code in ("B34", "B54"),
        "is_compensator": code in ("C09", "C04"),
        "source_instance_id": None,
    }


# Catalogo com as MESMAS medidas de celula lidas da familia real do projeto
# (ver PLANO_MODULACAO_BLOCOS.md): B54 com 3 celulas (a central menor), B34
# com 2 (a menor de 10,7cm), B39 com 2, B19 com 1, compensadores macicos.
CATALOG = {
    "B39": _block("B39", 39, [_cell(-9.9, 15.7), _cell(9.9, 15.8)]),
    "B34": _block("B34", 34, [_cell(-10.2, 10.7), _cell(7.4, 15.7)]),
    "B54": _block("B54", 54, [_cell(-19.5, 15.8), _cell(0.0, 12.5), _cell(19.5, 15.8)]),
    "B19": _block("B19", 19, [_cell(0.0, 15.7)]),
    "C09": _block("C09", 9, []),
    "C04": _block("C04", 4, []),
}


def solve_layout(raw_lines, thickness_cm=14.0, openings=None):
    walls = [(line, ft(thickness_cm), (False, False)) for line in raw_lines]
    walls, junction_map = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    per_wall = openings or dict((i, []) for i in range(len(walls)))
    result = m.solve_building_blocks(nodes, walls, end_to_node, per_wall, CATALOG)
    return result, nodes, walls


# ------------------------------------------------------------- geometria
@case
def test_par_de_linhas_vira_uma_parede_no_eixo():
    lines = [seg(0, 0, 500, 0), seg(0, 14, 500, 14)]
    diagnostics = {
        "parallel_pairs": 0, "min_dist_ft": None, "max_dist_ft": None,
        "offset_suspect_count": 0, "offset_suspect_max_ft": 0.0, "cap_clipped_count": 0,
    }
    walls, unused = m.find_wall_pairs(
        lines, [ft(14)], m.compute_detection_tolerance_ft([ft(14)]), lines, [], diagnostics
    )
    assert len(walls) == 1, walls
    assert not unused
    centerline, thickness_ft, _locks = walls[0]
    assert abs(to_cm(thickness_ft) - 14.0) < 0.01
    # eixo exatamente no meio das duas faces
    assert abs(to_cm(centerline.GetEndPoint(0).Y) - 7.0) < 0.01
    assert abs(to_cm(centerline.GetEndPoint(1).Y) - 7.0) < 0.01


@case
def test_espessura_fora_da_tolerancia_nao_vira_parede():
    lines = [seg(0, 0, 500, 0), seg(0, 25, 500, 25)]
    diagnostics = {
        "parallel_pairs": 0, "min_dist_ft": None, "max_dist_ft": None,
        "offset_suspect_count": 0, "offset_suspect_max_ft": 0.0, "cap_clipped_count": 0,
    }
    walls, unused = m.find_wall_pairs(
        lines, [ft(14)], m.compute_detection_tolerance_ft([ft(14)]), lines, [], diagnostics
    )
    assert not walls
    assert len(unused) == 2


@case
def test_find_wall_pairs_prioridade_preservada_apos_otimizacao_de_performance():
    """Regressao de PERFORMANCE: find_wall_pairs passou a calcular todos os
    pares candidatos numa unica passada O(n^2) e escolhe-los greedily numa
    lista ja ordenada, em vez de recalcular o "melhor par restante" varrendo
    tudo de novo a cada parede aceita (O(n^3) no Layer inteiro). Este teste
    planta um conflito real: a linha B tem DOIS parceiros paralelos e na
    mesma espessura (A, com sobreposicao total, e D, com sobreposicao
    parcial) - so' A-B deve vencer (maior fracao de sobreposicao), deixando
    D sem parede, exatamente como a versao anterior (que recalculava a cada
    rodada) decidia."""
    a = seg(0, 0, 1000, 0)
    b = seg(0, 14, 1000, 14)       # A-B: mesma faixa inteira -> sobreposicao 100%
    d = seg(600, 28, 1400, 28)     # B-D: so' 400 de 800cm -> sobreposicao 50%
    e = seg(2000, 0, 2500, 0)
    f = seg(2000, 14, 2500, 14)    # E-F: par independente, tambem 100%
    lines = [a, b, d, e, f]
    diagnostics = {
        "parallel_pairs": 0, "min_dist_ft": None, "max_dist_ft": None,
        "offset_suspect_count": 0, "offset_suspect_max_ft": 0.0, "cap_clipped_count": 0,
    }
    walls, unused = m.find_wall_pairs(
        lines, [ft(14)], m.compute_detection_tolerance_ft([ft(14)]), lines, [], diagnostics
    )
    assert len(walls) == 2, walls
    assert unused == [d], "D perde para A-B (sobreposicao maior) e fica sem par"


@case
def test_scan_possible_missed_bonecas_prioridade_preservada_apos_otimizacao():
    """Mesma reestruturacao de performance (ver teste acima), agora em
    scan_possible_missed_bonecas: com um empate de prioridade entre dois
    pares independentes e um terceiro par perdedor (linha ja' "roubada"
    pelo par de maior sobreposicao), o resultado tem que ser identico ao
    algoritmo anterior de recalculo por rodada."""
    a = seg(0, 0, 1000, 0)
    b = seg(0, 14, 1000, 14)
    d = seg(600, 28, 1400, 28)
    e = seg(2000, 0, 2500, 0)
    f = seg(2000, 14, 2500, 14)
    found = m.scan_possible_missed_bonecas([a, b, d, e, f])
    assert len(found) == 2, found
    dists = sorted(round(item[0]) for item in found)
    assert dists == [14, 14], found


@case
def test_merge_collinear_fragments_religamento_em_cascata_apos_particionamento():
    """Regressao de PERFORMANCE: a fusao de clusters via abertura real
    (segunda passada de merge_collinear_fragments) passou a agrupar
    primeiro os clusters por Union-Find (mesmo teste de paralelismo/
    distancia que _clusters_bridge_via_opening ja exige) e so' rodar a
    cascata cara DENTRO de cada grupo, em vez de sobre o Layer inteiro a
    cada fusao aceita. Este teste planta 3 fragmentos da MESMA face de
    parede, cada um com um leve desalinhamento (1cm) em relacao ao
    vizinho - fora da tolerancia apertada de colinearidade (2mm, logo
    3 clusters distintos na 1a passada), mas dentro da tolerancia de
    fusao (3cm) - religados por DUAS aberturas reais em cascata (a
    fusao dos dois primeiros precisa acontecer ANTES de o terceiro poder
    ser avaliado contra o intervalo ja' estendido)."""
    frag_a = seg(0, 0.0, 300, 0.0)
    frag_b = seg(400, 1.0, 700, 1.0)
    frag_c = seg(800, 2.0, 1100, 2.0)
    opening1 = {"center_xy": XYZ(ft(350), 0.0, 0.0), "width_ft": ft(100)}
    opening2 = {"center_xy": XYZ(ft(750), 0.0, 0.0), "width_ft": ft(100)}

    result = m.merge_collinear_fragments(
        [frag_a, frag_b, frag_c], m.COLLINEAR_MATCH_TOLERANCE_FT, m.MAX_JUNCTION_GAP_FT,
        [opening1, opening2], m.OPENING_GAP_PERP_TOLERANCE_FT, m.OPENING_GAP_WIDTH_SLACK_FT
    )
    assert len(result) == 1, result
    p0, p1 = result[0].GetEndPoint(0), result[0].GetEndPoint(1)
    lo, hi = sorted((to_cm(p0.X), to_cm(p1.X)))
    assert abs(lo - 0.0) < 0.5, result
    assert abs(hi - 1100.0) < 0.5, result


@case
def test_bridge_clusters_via_openings_nao_mistura_paredes_distintas():
    """O particionamento por Union-Find (ver teste de cascata acima) NUNCA
    pode misturar fragmentos de paredes fisicamente diferentes so' porque
    ambas tem uma quebra do mesmo tamanho: aqui ha duas paredes paralelas
    bem afastadas uma da outra (y~0 e y~500cm), cada uma com sua propria
    abertura religando sua propria quebra, mais uma TERCEIRA quebra (sem
    abertura nenhuma cobrindo-a) que deve permanecer como dois fragmentos
    separados."""
    wall1_a = seg(0, 0.0, 300, 0.0)
    wall1_b = seg(400, 1.0, 700, 1.0)
    wall2_a = seg(0, 500.0, 300, 500.0)
    wall2_b = seg(400, 501.0, 700, 501.0)
    unrelated_a = seg(0, 1000.0, 300, 1000.0)
    unrelated_b = seg(500, 1001.0, 800, 1001.0)

    opening1 = {"center_xy": XYZ(ft(350), 0.0, 0.0), "width_ft": ft(100)}
    opening2 = {"center_xy": XYZ(ft(350), ft(500.0), 0.0), "width_ft": ft(100)}

    result = m.merge_collinear_fragments(
        [wall1_a, wall1_b, wall2_a, wall2_b, unrelated_a, unrelated_b],
        m.COLLINEAR_MATCH_TOLERANCE_FT, m.MAX_JUNCTION_GAP_FT,
        [opening1, opening2], m.OPENING_GAP_PERP_TOLERANCE_FT, m.OPENING_GAP_WIDTH_SLACK_FT
    )

    # As duas paredes religam (1 linha cada, 700cm), a terceira fica como
    # dois fragmentos distintos (300cm e 300cm) por falta de abertura.
    lengths_cm = sorted(round(to_cm(line.Length)) for line in result)
    assert lengths_cm == [300, 300, 700, 700], result


@case
def test_varredura_sugere_a_espessura_desenhada():
    counts = m.scan_candidate_thicknesses_cm([seg(0, 0, 400, 0), seg(0, 14, 400, 14)])
    assert counts.get(14.0) == 1, counts


# ------------------------------------------ grafo de encontros (Etapa 2)
@case
def test_canto_L_e_um_unico_no():
    """Regressao: extend_wall_ends_to_junctions afasta as duas pontas do
    canto em meia espessura de cada parede; agrupando pelo ponto puxado, o
    MESMO canto virava dois nos L_CORNER e era resolvido duas vezes."""
    _res, nodes, _walls = solve_layout([seg(0, 0, 300, 0), seg(0, 0, 0, 300)])
    corners = [n for n in nodes if n["kind"] == "L_CORNER"]
    assert len(corners) == 1, [n["kind"] for n in nodes]
    assert sorted(corners[0]["arms"]) == [(0, 0), (1, 0)]


@case
def test_cruz_de_quatro_pontas_e_reconhecida_como_X():
    _res, nodes, _walls = solve_layout([
        seg(0, 0, 200, 0), seg(200, 0, 400, 0), seg(200, 0, 200, 200), seg(200, -200, 200, 0),
    ])
    kinds = [n["kind"] for n in nodes]
    assert kinds.count("X_INTERSECTION") == 1, kinds
    assert "L_CORNER" not in kinds, kinds


@case
def test_ponta_no_meio_da_parede_e_um_T():
    _res, nodes, _walls = solve_layout([seg(0, 0, 400, 0), seg(200, 0, 200, 300)])
    tees = [n for n in nodes if n["kind"] == "T_INTERSECTION"]
    assert len(tees) == 1, [n["kind"] for n in nodes]
    assert tees[0]["main_wall_idx"] == 0 and tees[0]["incoming_wall_idx"] == 1


@case
def test_parede_continua_quebrada_em_duas_ainda_e_um_T():
    _res, nodes, _walls = solve_layout([
        seg(0, 0, 200, 0), seg(200, 0, 400, 0), seg(200, 0, 200, 300),
    ])
    kinds = [n["kind"] for n in nodes]
    assert kinds.count("T_INTERSECTION") == 1, kinds


# ------------------------------------------------ solver de blocos (E4)
@case
def test_canto_L_gera_exatamente_duas_pecas_amarradas():
    result, _nodes, _walls = solve_layout([seg(0, 0, 307, 0), seg(0, 0, 0, 307)])
    corner = [c for c in result["candidates"] if c["placement_reason"] == "L_CORNER"]
    assert len(corner) == 2, len(corner)
    assert sorted(c["course"] for c in corner) == ["A", "B"]
    assert all(c["logical_code"] == "B34" for c in corner)
    assert m.validate_l_corner(corner[0], corner[1])["ok"]
    assert not result["collisions"], result["collisions"]


@case
def test_canto_L_modular_fecha_sem_sobra():
    """L de 307cm de eixo desenhado fecha as duas fiadas das duas paredes."""
    result, _nodes, _walls = solve_layout([seg(0, 0, 307, 0), seg(0, 0, 0, 307)])
    assert not result["non_modular"], result["non_modular"]
    assert not result["collisions"], result["collisions"]
    assert not result["intersection_failures"], result["intersection_failures"]


@case
def test_nenhuma_topologia_produz_colisao_na_mesma_fiada():
    """Propriedade central do solver: quando nao ha' solucao modular ele
    RELATA (NON_MODULAR_WALL); o que ele nunca pode fazer e' empilhar duas
    pecas no mesmo lugar da mesma fiada."""
    for length in range(200, 340, 7):
        layouts = {
            "reta": [seg(0, 0, length, 0)],
            "L": [seg(0, 0, length, 0), seg(0, 0, 0, length)],
            "T": [seg(0, 0, length, 0), seg(length / 2.0, 0, length / 2.0, length)],
            "X": [seg(0, 0, length, 0), seg(length, 0, 2 * length, 0),
                  seg(length, 0, length, length), seg(length, -length, length, 0)],
        }
        for name, raw in layouts.items():
            result, _nodes, _walls = solve_layout(raw)
            assert not result["collisions"], (name, length, result["collisions"])


@case
def test_cruz_nao_quebra_o_preenchimento():
    """Regressao: reservas de meio-de-parede repetidas geravam a sequencia
    de fronteiras (MIDSPAN_LO, MIDSPAN_LO), que caia no ramo de abertura
    com indice None e derrubava a execucao inteira com TypeError."""
    result, _nodes, _walls = solve_layout([
        seg(0, 0, 200, 0), seg(200, 0, 400, 0), seg(200, 0, 200, 200), seg(200, -200, 200, 0),
    ])
    assert isinstance(result["candidates"], list)


@case
def test_intervalos_de_meio_de_parede_sao_mesclados():
    assert m._merge_intervals_cm([(7.0, 41.0), (7.0, 41.0)]) == [(7.0, 41.0)]
    assert m._merge_intervals_cm([(0.0, 10.0), (5.0, 20.0), (40.0, 45.0)]) == \
        [(0.0, 20.0), (40.0, 45.0)]
    assert m._merge_intervals_cm([]) == []


@case
def test_canto_L_desenhado_com_paredes_se_ultrapassando_e_um_unico_no():
    """Bug real medido na planta do usuario (2026-08-21): quando o CAD ja'
    desenha as duas paredes do canto passando uma pela outra, nao ha' nada
    para extend_wall_ends_to_junctions esticar - a ponta fica FORA do
    junction_map, ancora nela mesma, e o canto vira DOIS nos FREE_END a
    9,9cm um do outro. As duas paredes entao nao reservam nada uma para a
    outra e o preenchimento das duas nasce por cima do cruzamento (eram 77
    das 118 colisoes que sobravam)."""
    # canto em L de 14cm, cada parede ultrapassando a outra em meia
    # espessura (7cm) - exatamente a geometria medida
    horizontal = seg(0, 0, 107, 0)
    vertical = seg(100, -7, 100, 200)
    walls = [(horizontal, ft(14.0), (False, False)), (vertical, ft(14.0), (False, False))]
    nodes, end_to_node = m.build_wall_graph(walls, {})   # junction_map VAZIO de proposito
    kinds = sorted(n["kind"] for n in nodes)
    assert "L_CORNER" in kinds, kinds
    assert kinds.count("FREE_END") <= 2, kinds   # so' as duas pontas soltas
    corner = [n for n in nodes if n["kind"] == "L_CORNER"][0]
    assert len(corner["arms"]) == 2, corner["arms"]


@case
def test_ruido_de_geometria_do_cad_nao_reprova_pilarete():
    """O empacotador comparava com 1e-6cm. Coordenadas vindas do CAD +
    conversoes pes<->cm produzem erro da ordem de 0,002cm (medido: uma borda
    de encontro em 829,99791cm em vez de 830cm), e isso reprovava trechos
    perfeitamente construiveis - 116 dos 344 'nao-modulares' medidos."""
    exato = m._pier_ordered_layout(200.0, CATALOG, 1, 0)
    assert exato, "200cm com junta 1+0 tem que fechar"
    ruidoso = m._pier_ordered_layout(199.99791436, CATALOG, 1, 0)
    assert ruidoso, "0,002cm de ruido nao pode reprovar o mesmo trecho"
    assert len(ruidoso) == len(exato)
    # e um erro de projeto DE VERDADE continua reprovando
    assert m._pier_ordered_layout(198.0, CATALOG, 1, 0) is None


@case
def test_compensadores_ligados_por_default():
    """Sem C09/C04 as unicas pecas de preenchimento sao B39 (passo 40cm) e
    B19 (passo 20cm) - so' fechariam pilaretes multiplos de 20cm. Medido na
    planta real: 7 paredes validas com eles desligados, 37 com eles
    ligados."""
    assert m.BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT is True
    assert m._pier_ordered_layout(25.0, CATALOG, 1, 0, allow_compensators=False) is None
    fechado = m._pier_ordered_layout(25.0, CATALOG, 1, 0)
    assert fechado, "25cm tem que fechar com compensador"
    # o compensador e' ULTIMO recurso: 200cm nao pode usar nenhum
    codes = [c for c, _a, _b in m._pier_ordered_layout(200.0, CATALOG, 1, 0)]
    assert not any(CATALOG[c]["is_compensator"] for c in codes), codes


@case
def test_jamb_nao_e_lancado_sem_espaco_fisico():
    """Abertura colada demais num encontro: o jamb era emitido do mesmo
    jeito, DENTRO do bloco de amarracao. Agora o trecho e' reportado como
    conflito SEM_ESPACO e nenhuma peca e' lancada ali."""
    # parede com uma abertura a 20cm da ponta, e um encontro em T que
    # reserva 34cm daquela ponta -> nao cabe nada entre os dois
    lines = [seg(0, 0, 400, 0), seg(0, -200, 0, 200)]
    walls = [(l, ft(14.0), (False, False)) for l in lines]
    walls, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, jmap)
    per_wall = {0: [(ft(20.0), ft(100.0), 0.0, ft(210.0))], 1: []}
    result = m.solve_building_blocks(nodes, walls, end_to_node, per_wall, CATALOG)
    conflitos = [e for e in result["non_modular"] if e.get("conflict") == "SEM_ESPACO"]
    assert conflitos, "o trecho sem espaco tem que ser reportado"
    for e in conflitos:
        assert e["current_length_cm"] < 0
        # diagnostico (2026-08-25): precisa dizer QUAL fronteira de cada
        # lado, senao e' impossivel reproduzir o conflito fora do projeto
        # real so' com "current_length_cm negativo".
        assert e.get("left_kind") is not None, e
        assert e.get("right_kind") is not None, e
        assert isinstance(e.get("left_t_cm"), float), e
        assert isinstance(e.get("right_t_cm"), float), e


# ------------------------------------------------- regras de modulacao
@case
def test_regra_de_digito_final_das_paredes_nao_existe_mais():
    """A antiga regra "a parede tem que terminar em 0/5 (ou 0/1/6/9)" foi
    REMOVIDA. Nao pode voltar nem como constante nem como funcao."""
    assert not hasattr(m, "MODULATION_VALID_LAST_DIGITS_CM")
    assert not hasattr(m, "PIER_AT_OPENING_VALID_LAST_DIGITS_CM")
    # os exemplos que o usuario deu como "nao sao erro" precisam passar
    assert m.evaluate_wall_block_length(111.0)["compatible"], "111cm e' valida"
    assert m.evaluate_wall_block_length(129.0)["compatible"], "129cm e' valida"
    # e o que a regra antiga aprovava/reprovava por digito nao decide nada:
    # 110 (5m), 111 (5m+1) e 129 (5m-1) fecham, cada um com as suas juntas
    assert m.pier_closes_with_blocks_cm(110.0, 1, 0)
    assert m.pier_closes_with_blocks_cm(111.0, 1, 1)
    assert m.pier_closes_with_blocks_cm(129.0, 0, 0)
    # nenhuma combinacao de junta fecha 113cm - reprovado pela aritmetica
    # dos blocos, nao por digito
    assert not m.wall_length_closes_with_blocks_cm(113.0)
    assert not m.evaluate_wall_block_length(400.4)["is_whole_cm"]


@case
def test_largura_de_abertura_mantem_a_regra_propria():
    """So' a regra das PAREDES foi removida - a das ABERTURAS (terminar em
    1, 6 ou 9cm) continua valendo."""
    valid = m.OPENING_VALID_LAST_DIGITS_CM
    assert m._evaluate_modulation_length(81.0, valid)["compatible"]
    assert not m._evaluate_modulation_length(80.0, valid)["compatible"]


@case
def test_ordem_de_processamento_e_geometrica():
    """Horizontais primeiro (cima -> baixo, esquerda -> direita); depois
    verticais (esquerda -> direita, baixo -> cima). A ordem NAO pode
    depender da ordem em que as paredes aparecem na lista."""
    # 4 horizontais em 2 niveis + 4 verticais em 2 alinhamentos, embaralhadas
    raw = [
        seg(0, 0, 100, 0),      # 0 H  nivel y=0   (o mais BAIXO)
        seg(300, 200, 400, 200),  # 1 H  nivel y=200 (o mais ALTO), direita
        seg(0, 200, 100, 200),  # 2 H  nivel y=200, esquerda
        seg(300, 0, 400, 0),    # 3 H  nivel y=0, direita
        seg(400, 100, 400, 200),  # 4 V  x=400, em cima
        seg(0, 0, 0, 100),      # 5 V  x=0, embaixo
        seg(400, 0, 400, 100),  # 6 V  x=400, embaixo
        seg(0, 100, 0, 200),    # 7 V  x=0, em cima
    ]
    walls = [(line, ft(14.0), (False, False)) for line in raw]
    order = m.order_walls_for_processing(walls)
    assert order == [2, 1, 0, 3, 5, 7, 6, 4], order
    assert m.classify_wall_orientation(walls, 0) == "H"
    assert m.classify_wall_orientation(walls, 5) == "V"


@case
def test_plano_nunca_pode_aumentar_a_parede():
    """Regra #1: nenhum plano com fronteira fora do eixo original passa -
    e' assim que "dente"/prolongamento fica impossivel por construcao."""
    axis = {
        "wall_idx": 0, "axis_len_ft": ft(400.0),
        "piers": [{"index": 0, "element_id": 1, "t_a": 0.0, "t_b": ft(160.0)},
                  {"index": 1, "element_id": 2, "t_a": ft(240.0), "t_b": ft(400.0)}],
        "openings": [{"opening_index": 0, "t_lo": ft(160.0), "t_hi": ft(240.0),
                      "sill_z_abs": 0.0, "head_z_abs": ft(210.0), "infill_ids": [3]}],
    }
    solution = {"gaps_after_cm": [160.0, 160.0], "opening_shifts_cm": [0.0],
                "max_shift_cm": 0.0, "within_auto_apply_limit": True, "changed": False}
    matched = {0: {"element_id_obj": None}}

    encurtar = m._build_axis_opening_plan(0, axis, matched, solution, [0], "trim",
                                          {"side": 1, "delta_cm": -3.0})
    assert encurtar["feasible"] is True
    assert encurtar["length_delta_cm"] < 0

    aumentar = m._build_axis_opening_plan(0, axis, matched, solution, [0], "trim",
                                          {"side": 1, "delta_cm": +3.0})
    assert aumentar["feasible"] is False
    assert "AUMENTARIA" in aumentar["reason"]

    aumentar_pela_outra_ponta = m._build_axis_opening_plan(
        0, axis, matched, solution, [0], "trim", {"side": 0, "delta_cm": +3.0}
    )
    assert aumentar_pela_outra_ponta["feasible"] is False


@case
def test_validacao_final_reprova_aumento_de_parede():
    """validate_wall_modulation e' a rede de seguranca da regra #1/#2: uma
    parede que ficou MAIOR que a original nao passa, mesmo com a modulacao
    fechando."""
    walls = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    fill_ok = {"candidates": [], "jamb_exceptions": [], "non_modular": []}
    ok = m.validate_wall_modulation(0, walls, [[]], fill_ok, original_length_cm=400.0)
    assert ok["ok"] is True
    assert ok["checks"]["sem_aumento"] and ok["checks"]["sem_dentes"]

    cresceu = m.validate_wall_modulation(0, walls, [[]], fill_ok, original_length_cm=395.0)
    assert cresceu["ok"] is False
    assert cresceu["checks"]["sem_aumento"] is False


@case
def test_solver_de_eixo_aceita_restos_alem_de_zero():
    """O resto exigido de cada pilarete vem das JUNTAS reais daquele trecho,
    nao de um digito - por isso o solver aceita restos 0, 1 e 4."""
    assert m.PIER_POSSIBLE_RESIDUES_CM == (0, 1, 4)
    # soma 131: impossivel com todos os pilaretes em 5m (a hipotese antiga)
    gaps = [47.0, 33.0, 51.0]
    assert m.solve_axis_opening_modulation(gaps) is None
    assert m.enumerate_axis_opening_modulations(gaps, include_alternatives=False) == []
    # mas ha' solucao assim que os restos reais entram em jogo
    alternativas = m.enumerate_axis_opening_modulations(gaps)
    assert alternativas, "com restos 0/1/4 tem que existir particao valida"
    assert sum(alternativas[0]["gaps_after_cm"]) == sum(gaps)


@case
def test_pilarete_so_fecha_em_multiplo_de_cinco():
    blocks, leftover = m.pack_pier_with_blocks(55)
    assert blocks == [34, 19] and leftover == 0
    assert m.pack_pier_with_blocks(53) == (None, 53)


@case
def test_primeira_fiada_nasce_em_1cm_nao_em_0cm():
    """Secao 4 do prompt (REGRA CRITICA): Fiada 1 -> Z=1cm, Fiada 2 ->
    Z=21cm, Fiada 3 -> Z=41cm ... nunca comecando em Z=0cm relativo ao
    nivel. Numeros CONFIRMADOS 2026-08-21 pelo usuario direto no Revit,
    depois de ver os blocos criados: "segunda fiada seja lancada no nivel
    21" (reverteu uma correcao anterior para 20 feita na mesma sessao - ver
    historico em _course_height_ft; NAO alternar de novo sem reconfirmar)."""
    course_height_ft, err = m._course_height_ft(CATALOG, [{"logical_code": "B39"}])
    assert err is None
    assert abs(to_cm(course_height_ft) - 20.0) < 1e-6  # 19cm de bloco + 1cm de junta
    base_z_abs = ft(0.0)
    zs_cm = [to_cm(m._course_z_abs(base_z_abs, i, course_height_ft)) for i in range(4)]
    assert [round(z, 6) for z in zs_cm] == [1.0, 21.0, 41.0, 61.0], zs_cm


@case
def test_fiada_b_desencontra_junta_vertical_da_fiada_a():
    """Secao 6 do prompt: nos trechos de preenchimento comum, a Fiada B deve
    evitar repetir a posicao das juntas internas ja' usadas pela Fiada A
    sempre que houver alternativa que feche o mesmo trecho.

    NUMEROS ATUALIZADOS 2026-08-21 (prioridade nova B39->B19->B34->
    compensadores): pier=81cm fecha so' com 2xB39 (unica composicao
    possivel com essa denominacao - nada para desencontrar, ver
    test_desencontro_de_junta_mantem_layout_padrao_quando_nao_ha_alternativa_melhor
    para esse caso). Trocado para pier=46cm, que so' fecha usando 1
    compensador (B39+C04) - e' dentro do tier de compensador que ainda
    existem varias composicoes alternativas (C09+B34, etc.) para
    desencontrar a junta."""
    baseline = m._pier_ordered_layout(46.0, CATALOG, 1.0, 1.0)
    joints_a = m._layout_internal_joint_positions_cm(baseline, 0.0)
    assert joints_a  # trecho com mais de um bloco, tem pelo menos 1 junta interna

    staggered = m._pier_layout_avoiding_joints(46.0, CATALOG, 1.0, 1.0, 0.0, joints_a)
    joints_b = m._layout_internal_joint_positions_cm(staggered, 0.0)
    # cobre o mesmo trecho inteiro (mesmo comprimento total)
    assert staggered[0][1] == baseline[0][1] and staggered[-1][2] == baseline[-1][2]
    assert m._count_joint_coincidences_cm(joints_b, joints_a) == 0, (joints_a, joints_b)


@case
def test_desencontro_de_junta_mantem_layout_padrao_quando_nao_ha_alternativa_melhor():
    # trecho fechado por uma unica peca: nao ha' junta interna nenhuma, e
    # portanto nada para desencontrar - deve devolver o layout padrao.
    baseline = m._pier_ordered_layout(41.0, CATALOG, 1.0, 1.0)
    result = m._pier_layout_avoiding_joints(41.0, CATALOG, 1.0, 1.0, 0.0, [20.5])
    assert result == baseline


@case
def test_desencontra_junta_mesmo_quando_so_fecha_com_b39_puro_dos_dois_lados_fechados():
    """CAUSA-RAIZ corrigida (2026-08-25) da maioria das juntas verticais
    corridas medidas numa execucao real (paredes com a MESMA junta repetida
    em ate' 15 fiadas seguidas - ver PENALTY_CONTINUOUS_VERTICAL_JOINT no
    log real do usuario). O comentario de
    test_fiada_b_desencontra_junta_vertical_da_fiada_a ja documentava o
    problema ('pier=81cm fecha so' com 2xB39... nada para desencontrar') e
    contornou trocando o pier de teste - mas exatamente esse caso (trecho
    entre dois encontros L/T/X, as duas pontas FECHADAS - sem onde B19
    encostar - fechando como um multiplo EXATO de 40cm, so' B39) e' comum
    em paredes reais sem nenhuma abertura no meio, e ate' agora nao tinha
    NENHUMA alternativa: `_pier_ordered_layout(first_code=...)` sempre
    devolve o resultado do tier 1 (so' B39) quando ele fecha, silenciando
    qualquer pedido de B34/compensador como primeiro bloco (esses tiers
    nunca chegavam a ser tentados). `_pier_forced_bypass_layouts` (chamada
    por `_pier_layout_avoiding_joints`) resolve isso: 1 B34 no inicio +
    B39 o quanto couber SEMPRE sobra exatamente 5cm (prova no docstring),
    que fecha com exatamente 1 C04 - dentro do teto de 1 compensador."""
    pier_cm, lead_cm, trail_cm = 201.0, 1.0, 1.0  # remaining = 200 = 5*(39+1)
    baseline = m._pier_ordered_layout(pier_cm, CATALOG, lead_cm, trail_cm)
    assert [code for code, _s, _e in baseline] == ["B39"] * 5, baseline
    joints_a = m._layout_internal_joint_positions_cm(baseline, 0.0)
    assert len(joints_a) == 4, joints_a

    staggered = m._pier_layout_avoiding_joints(
        pier_cm, CATALOG, lead_cm, trail_cm, 0.0, joints_a,
        leading_is_open=False, trailing_is_open=False,
    )
    assert staggered is not None
    # cobre o mesmo trecho inteiro (mesmo comprimento total, mesmas pontas)
    assert staggered[0][1] == baseline[0][1] and staggered[-1][2] == baseline[-1][2]
    joints_b = m._layout_internal_joint_positions_cm(staggered, 0.0)
    assert m._count_joint_coincidences_cm(joints_b, joints_a) == 0, (joints_a, joints_b)
    # nunca mais que 1 compensador (regra absoluta), e a peca especial que
    # permite o desencontro sem B19 (ponta fechada) e' o B34.
    comp_count = sum(1 for code, _a, _b in staggered if CATALOG[code]["is_compensator"])
    assert comp_count <= 1, staggered
    assert "B34" in [code for code, _a, _b in staggered], staggered
    assert "B19" not in [code for code, _a, _b in staggered], staggered


@case
def test_coincidencia_de_junta_vence_alinhamento_de_vazio_na_prioridade():
    """BUG REAL corrigido (2026-08-25, achado ao rodar a suite inteira
    depois de tornar a regra #1 bloqueante - ver alignment_conflicts):
    ANTES desta correcao, `_score` comparava (alinhamento de vazio
    [PRIMARIO], coincidencia de junta [desempate]). Isso e' inofensivo na
    maioria dos casos, mas da' resultado ERRADO exatamente quando o layout
    PADRAO da Fiada B (sem nenhuma alternativa) e' IDENTICO ao da Fiada A -
    o que acontece sempre que as duas fiadas tem o MESMO pilarete e as
    MESMAS juntas de contorno (nenhuma abertura no meio para diferenciar
    as duas, como um pilarete isolado entre duas pontas livres): comparado
    contra si mesmo, o alinhamento de vazio sai PERFEITO por construcao
    (trivial), mas junto com a PIOR coincidencia de junta possivel (tambem
    consigo mesmo, 100%) - com align primeiro, essa "copia identica"
    vencia QUALQUER alternativa de verdade (ex.: B34+B34, sem alinhamento
    de vazio nenhum mas SEM coincidencia de junta), simplesmente porque
    seu alinhamento (trivial) era maior. Reproduzido exatamente pelo
    pilarete de teste da ETAPA 3C (309cm, as duas pontas livres, sem
    abertura no meio) - a Fiada B saia 100% igual a Fiada A ate' esta
    correcao."""
    pier_cm, lead_cm, trail_cm = 309.0, 0.0, 0.0
    baseline = m._pier_ordered_layout(pier_cm, CATALOG, lead_cm, trail_cm)
    joints_a = m._layout_internal_joint_positions_cm(baseline, 0.0)
    voids_a = m._layout_void_positions_cm(baseline, CATALOG, 0.0)
    assert len(joints_a) >= 2 and voids_a, (joints_a, voids_a)

    staggered = m._pier_layout_avoiding_joints(
        pier_cm, CATALOG, lead_cm, trail_cm, 0.0, joints_a,
        target_void_positions_cm=voids_a,
        leading_is_open=True, trailing_is_open=True,
    )
    assert staggered is not None
    assert staggered[0][1] == baseline[0][1] and staggered[-1][2] == baseline[-1][2]
    joints_b = m._layout_internal_joint_positions_cm(staggered, 0.0)
    # a regra #1 (ausencia de coincidencia de junta) e' ABSOLUTA - nunca
    # aceita uma "copia identica" so' porque o alinhamento de vazio dela
    # (contra si mesma) parece perfeito.
    assert m._count_joint_coincidences_cm(joints_b, joints_a) == 0, (joints_a, joints_b)
    assert staggered != baseline, "a copia identica nao pode vencer uma alternativa real"


@case
def test_fiada_b_alinha_vazios_com_deslocamento_de_meio_bloco():
    """Pedido explicito do usuario (2026-08-21): "para o bloco de 39cm, o
    deslocamento entre a 1a e a 2a fiada deve ser de aproximadamente 20cm,
    de forma que os vaos fiquem corretamente alinhados" - a modulacao deve
    considerar a posicao dos VAZIOS internos, nao so' o comprimento total.

    Trecho fechado com 3xB39 (nada para desencontrar por junta - o unico
    jeito de fechar so' com blocos inteiros): a Fiada A vira 3 blocos
    colados; a Fiada B, buscando alinhar vazios, deve inserir 1 B19 logo
    no inicio (mesmo com as duas pontas FECHADAS contra outro
    bloco/no' - lead=trail=1.0) para produzir o deslocamento de meio
    modulo, e os vazios resultantes devem cair muito proximos dos vazios
    da Fiada A."""
    pier_cm = 121.0  # remaining = 121 - 1 - 1 + 1 = 120 = 3*(39+1)
    baseline = m._pier_ordered_layout(pier_cm, CATALOG, 1.0, 1.0)
    assert [code for code, _s, _e in baseline] == ["B39", "B39", "B39"], baseline
    voids_a = m._layout_void_positions_cm(baseline, CATALOG, 0.0)
    assert len(voids_a) == 6  # 2 vazios por B39, 3 blocos
    joints_a = m._layout_internal_joint_positions_cm(baseline, 0.0)

    # avoid_positions_cm (joints_a) PRECISA ir junto: sem ele, uma copia
    # LITERAL da Fiada A "alinha" os vazios trivialmente (sao os mesmos
    # blocos, nas mesmas posicoes) mas deixa TODAS as juntas coincidindo -
    # o oposto de uma amarracao de verdade. E' o desencontro de junta que
    # descarta essa copia trivial em favor do deslocamento real.
    staggered = m._pier_layout_avoiding_joints(
        pier_cm, CATALOG, 1.0, 1.0, 0.0, joints_a, allow_compensators=True,
        target_void_positions_cm=voids_a,
    )
    # cobre o mesmo trecho inteiro (mesmo comprimento total)
    assert staggered[0][1] == baseline[0][1] and staggered[-1][2] == baseline[-1][2]
    # o deslocamento de meio modulo so' aparece via 1 B19 no INICIO -
    # mesmo a ponta sendo fechada (regra normal de preenchimento comum
    # continua proibindo B19 espremido no meio, ver
    # test_meio_bloco_e_ultimo_recurso_nunca_no_meio_do_trecho).
    assert staggered[0][0] == "B19", staggered
    voids_b = m._layout_void_positions_cm(staggered, CATALOG, 0.0)
    aligned = m._count_void_alignment_cm(voids_b, voids_a)
    assert aligned == len(voids_b), (voids_a, voids_b)
    # o deslocamento medido bate com os ~20cm que o usuario descreveu.
    assert abs((staggered[1][1] - baseline[0][1]) - 20.0) <= 1.0, staggered


@case
def test_sem_alvo_de_vazio_nao_forca_meio_bloco_no_trecho_fechado():
    # Comportamento antigo preservado: sem target_void_positions_cm, o
    # trecho que fecha com blocos inteiros continua fechando so' com
    # blocos inteiros (nunca introduz B19 numa ponta fechada so' para
    # desencontrar junta).
    pier_cm = 121.0
    baseline = m._pier_ordered_layout(pier_cm, CATALOG, 1.0, 1.0)
    result = m._pier_layout_avoiding_joints(pier_cm, CATALOG, 1.0, 1.0, 0.0, [])
    assert result == baseline
    assert [code for code, _s, _e in result] == ["B39", "B39", "B39"], result


@case
def test_layout_ordenado_respeita_juntas_de_contorno():
    # 41 = junta 1 + B39 + junta 1 (a junta final entra no proximo trecho)
    layout = m._pier_ordered_layout(41.0, CATALOG, 1.0, 1.0)
    assert layout == [("B39", 1.0, 40.0)], layout
    # 42 nao fecha: sobra 1cm, que nao e' multiplo do modulo de 5cm
    assert m._pier_ordered_layout(42.0, CATALOG, 1.0, 1.0) is None


@case
def test_meio_bloco_e_ultimo_recurso_nunca_no_meio_do_trecho():
    """Regras do usuario (2026-08-21, com imagens de referencia): o B19 so'
    entra quando B39+compensadores nao fecham, e mesmo assim so' encostado
    numa ponta ABERTA (abertura/extremidade sem amarracao) - nunca
    espremido entre dois blocos no meio."""
    catalog_no_comp = {k: v for k, v in CATALOG.items() if k not in ("C09", "C04")}

    # Ponta de ENTRADA aberta (leading=0), saida amarrada (trailing=1):
    # pier=60cm sem compensadores so' fecha usando 1 B19 - tem que nascer
    # na ponta ABERTA (posicao 0), com o B39 depois dele, nunca o inverso.
    layout = m._pier_ordered_layout(60.0, catalog_no_comp, 0.0, 1.0)
    assert layout[0][0] == "B19", layout
    assert layout[0][1] == 0.0, layout          # encostado na ponta aberta
    assert [c for c, _a, _b in layout[1:]] == ["B39"]

    # Espelhado: ponta de SAIDA aberta, entrada amarrada - B19 tem que
    # nascer no FINAL do trecho, nao no comeco.
    layout2 = m._pier_ordered_layout(60.0, catalog_no_comp, 1.0, 0.0)
    assert layout2[-1][0] == "B19", layout2
    assert abs(layout2[-1][2] - 60.0) < 1e-6      # encostado na ponta aberta (fim)
    assert [c for c, _a, _b in layout2[:-1]] == ["B39"]

    # Com compensadores DISPONIVEIS (default do projeto) e SO' 1 necessario
    # para fechar (pier=45: B39+C04), fica com o compensador UNICO - 1
    # compensador e' "realmente necessario" (regra do usuario), nao vale
    # trocar por um B19 fora de posicao ideal so' por trocar.
    layout3a = m._pier_ordered_layout(45.0, CATALOG, 0.0, 1.0)
    assert "B19" not in [c for c, _a, _b in layout3a], layout3a
    assert sum(1 for c, _a, _b in layout3a if CATALOG[c]["is_compensator"]) == 1

    # MESMO catalogo, mas o pier de 60cm so' fecha sem B19 usando DOIS C09
    # seguidos - pedido explicito do usuario (2026-08-21): "evitar ao
    # maximo o uso repetitivo de compensadores/pastilhas... nao podem virar
    # solucao recorrente" - MAX_COMPENSATORS_PER_TRECHO=1 faz o solver
    # preferir 1 UNICO B19 (mesmo fora da ponta ideal, se preciso) a uma
    # fileira de compensadores.
    layout3b = m._pier_ordered_layout(60.0, CATALOG, 0.0, 1.0)
    assert "B19" in [c for c, _a, _b in layout3b], layout3b
    assert sum(1 for c, _a, _b in layout3b if CATALOG[c]["is_compensator"]) == 0

    # As duas pontas AMARRADAS (nenhuma aberta) - sem compensadores, so'
    # fecha usando B19 mesmo sem ponta aberta disponivel; o solver nao pode
    # desistir so' porque a posicao "ideal" nao existe (regra #6 do usuario:
    # sempre tentar a melhor solucao possivel antes de declarar sem solucao).
    layout4 = m._pier_ordered_layout(61.0, catalog_no_comp, 1.0, 1.0)
    assert layout4 is not None
    assert "B19" in [c for c, _a, _b in layout4]


@case
def test_t_intersection_room_ok_detecta_espaco_insuficiente_por_causa_de_porta():
    """Pedido explicito do usuario (2026-08-21, com exemplo real corrigido a
    mao): nao forcar B54/B34 num encontro em T quando nao ha' espaco fisico
    real - uma porta perto demais do no' (ou uma boneca curta demais) tem
    que ser detectada ANTES de tentar colocar as pecas."""
    main_wall = (seg(0, 0, 1000, 0), ft(14.0), (False, False))
    inc_wall = (seg(200, 0, 200, -40), ft(14.0), (False, False))  # boneca de 40cm
    walls_to_create = [main_wall, inc_wall]
    node = {"point": XYZ(ft(200.0), 0.0, 0.0), "main_wall_idx": 0, "incoming_wall_idx": 1}

    # porta a so' 5cm do no' (180-195cm) - bem menos que os 27cm exigidos
    # para cada lado do B54.
    openings_tight = [[(ft(180.0), ft(195.0), ft(0.0), ft(210.0))], []]
    assert m._t_intersection_room_ok(node, walls_to_create, openings_tight) is False

    # porta longe (0-50cm) - folga real de sobra, boneca de 40cm > 34cm exigidos.
    openings_far = [[(ft(0.0), ft(50.0), ft(0.0), ft(210.0))], []]
    assert m._t_intersection_room_ok(node, walls_to_create, openings_far) is True

    # boneca curta demais (so' 20cm, precisa de 34cm) mesmo sem porta nenhuma.
    inc_wall_curto = (seg(200, 0, 200, -20), ft(14.0), (False, False))
    walls_curto = [main_wall, inc_wall_curto]
    assert m._t_intersection_room_ok(node, walls_curto, [[], []]) is False

    # chamador antigo, sem openings_per_wall - nunca bloqueia (retrocompatibilidade).
    assert m._t_intersection_room_ok(node, walls_to_create, None) is True


@case
def test_solve_l_corner_troca_por_compensador_quando_porta_perto_do_canto():
    """Achado ao vivo via MCP (2026-08-21): depois de corrigir o T, a MESMA
    invasao de vao de porta apareceu em encontros L de verdade (32
    violacoes, todas L_CORNER) - solve_l_corner nunca tinha checagem de
    espaco. Porta perto de UM dos lados do canto tem que trocar B34 por 1
    unico compensador/pastilha SO' naquele lado, mantendo B34 no lado que
    tem espaco."""
    lines = [seg(0, 0, 200, 0), seg(200, 0, 200, -300)]
    walls, junction_map = m.extend_wall_ends_to_junctions(
        [(l, ft(14.0), (False, False)) for l in lines], m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    node = [n for n in nodes if n.get("kind") == "L_CORNER"][0]

    # sem openings_per_wall - comportamento historico, sempre B34 nos dois lados.
    result_default = m.solve_l_corner(node, walls, CATALOG)
    assert result_default["course_a"]["logical_code"] == "B34"
    assert result_default["course_b"]["logical_code"] == "B34"
    assert not result_default.get("degraded")

    # porta a so' 5cm do canto na parede A (0-200cm, canto em 200) - bem
    # menos que os 34cm exigidos; parede B (vertical, 300cm) sem abertura -
    # continua com espaco de sobra.
    openings_tight = [[(ft(180.0), ft(195.0), ft(0.0), ft(210.0))], []]
    result = m.solve_l_corner(node, walls, CATALOG, openings_per_wall=openings_tight)
    assert result["ok"] is True
    assert result.get("degraded") is True
    assert result["course_a"]["logical_code"] in ("C09", "C04")
    assert result["course_a"]["logical_code"] != "B19"
    assert result["course_b"]["logical_code"] == "B34"  # lado com espaco continua B34


@case
def test_solve_l_corner_considera_reserva_do_encontro_na_outra_ponta_da_mesma_parede():
    """Bug real medido ao vivo (2026-08-24, log do usuario apos refazer o
    modelo do zero): uma parede MUITO CURTA ligando duas paredes longas
    forma um encontro em L em CADA ponta dela. Sem saber da reserva do
    encontro do lado OPOSTO, cada L_CORNER media espaco so' contra a
    ponta FISICA da propria parede (ou a abertura mais proxima) - os dois
    lados "viam" espaco de sobra para B34 (34cm) independentemente um do
    outro, e colidiam entre si (a mesma causa das "colisoes residuais"
    reportadas pelo solver, e dos trechos de preenchimento comum com
    comprimento NEGATIVO em cascata pela planta - centenas deles no log
    real)."""
    left = seg(0, 0, 0, 300)
    right = seg(40, 0, 40, 300)
    bottom = seg(0, 0, 40, 0)
    walls, junction_map = m.extend_wall_ends_to_junctions(
        [(w, ft(14.0), (False, False)) for w in (left, right, bottom)], m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    per_wall = dict((i, []) for i in range(len(walls)))

    kinds = [n.get("kind") for n in nodes]
    assert kinds.count("L_CORNER") == 2, kinds  # as duas pontas da parede curta (indice 2)

    # SEM a checagem cruzada (comportamento antigo, chamador que nao
    # passa nodes/end_to_node): reproduz o bug - os dois lados forcam B34
    # cheio e colidem entre si.
    old = m.solve_all_intersections(nodes, walls, CATALOG, openings_per_wall=per_wall)
    old_collisions = m.validate_same_course_collision(old["candidates"])
    assert old_collisions, "esperava reproduzir a colisao SEM a checagem cruzada"

    # COM a checagem cruzada (a correcao, thread'ando nodes/end_to_node):
    # sem colisao nenhuma. A ESTRATEGIA que resolve isso mudou desde que
    # este teste foi escrito (2026-08-25, giro do B34 do canto quando ha'
    # outro encontro perto - ver solve_l_corner/_corner_bond_blocked_by_
    # other_node): antes so' existia degradar para compensador; agora os
    # DOIS cantos primeiro tentam GIRAR o B34 para a propria parede LONGA
    # (preferivel - mantem a peca cheia, nenhum compensador) e so' degradam
    # se nem isso resolver. Aqui, com as duas paredes longas se afastando
    # o suficiente uma da outra, girar sozinho ja' basta: a parede CURTA
    # fica sem nenhuma peca de amarracao propria (vira preenchimento comum
    # normal) - por isso a checagem e' "nenhuma colisao", nao mais "algum
    # lado degradado".
    new = m.solve_all_intersections(nodes, walls, CATALOG, openings_per_wall=per_wall,
                                    end_to_node=end_to_node)
    new_collisions = m.validate_same_course_collision(new["candidates"])
    assert not new_collisions, new_collisions


@case
def test_solve_t_intersection_degrada_para_l_depois_para_elemento_unico():
    """Duas correcoes do usuario (2026-08-21) sobre o fallback do encontro
    em T sem espaco: (1) nao usar B19 ali - vira um canto em L com uma
    boneca, nao uma ponta livre; (2) "amarracao em L usa o bloco de 34
    (sempre)" - so' cai para compensador/pastilha quando nem o B34 cabe na
    boneca."""
    main_wall = (seg(0, 0, 1000, 0), ft(14.0), (False, False))
    node = {"point": XYZ(ft(200.0), 0.0, 0.0), "main_wall_idx": 0, "incoming_wall_idx": 1}
    # porta perto SO' de um lado (180-195) - o lado oposto (t>200) fica com
    # 800cm livres, de sobra para o "braco" do L na parede principal.
    openings_tight = [[(ft(180.0), ft(195.0), ft(0.0), ft(210.0))], []]

    # boneca de 40cm (>= 34cm exigidos pelo B34) - tem que degradar para L,
    # NUNCA usar B19.
    inc_wall_34 = (seg(200, 0, 200, -40), ft(14.0), (False, False))
    walls_34 = [main_wall, inc_wall_34]
    result_l = m.solve_t_intersection(node, walls_34, CATALOG, openings_per_wall=openings_tight)
    assert result_l["ok"] is True
    assert result_l.get("degraded") is True
    assert result_l["course_a"]["logical_code"] == "B34"
    assert result_l["course_b"]["logical_code"] == "B34"
    assert result_l["course_a"]["wall_idx"] == 0  # parede principal recebe B34 (nao fica vazia)
    # Pedido explicito do usuario (2026-08-21): "o bloco 34 tem que estar
    # encostado na face da outra parede" e os vaos MENORES das duas fiadas
    # tem que ficar sobrepostos em projecao (mesma prova geometrica de um
    # L_CORNER de verdade - reusa validate_l_corner sem alteracao nenhuma).
    validation = m.validate_l_corner(result_l["course_a"], result_l["course_b"])
    assert validation["ok"], validation["problems"]

    # boneca de 20cm (< 34cm) - B34 nao cabe, tem que cair para 1 UNICO
    # compensador/pastilha (C09, o maior que cabe em 20cm), nunca B19, e
    # SEM peca na parede principal.
    inc_wall_20 = (seg(200, 0, 200, -20), ft(14.0), (False, False))
    walls_20 = [main_wall, inc_wall_20]
    result_single = m.solve_t_intersection(node, walls_20, CATALOG, openings_per_wall=openings_tight)
    assert result_single["ok"] is True
    assert result_single.get("degraded") is True
    # as DUAS fiadas do elemento unico ficam na boneca (wall_idx=1) - nada
    # e' reservado na parede principal (wall_idx=0) neste tier.
    assert result_single["course_a"]["wall_idx"] == 1
    assert result_single["course_b"]["wall_idx"] == 1
    assert result_single["course_a"]["logical_code"] == "C09"
    assert result_single["course_b"]["logical_code"] == "C09"
    assert "B19" not in (result_single["course_a"]["logical_code"], result_single["course_b"]["logical_code"])

    # boneca de 3cm - nem o C04 cabe - sem solucao automatica.
    inc_wall_3 = (seg(200, 0, 200, -3), ft(14.0), (False, False))
    walls_3 = [main_wall, inc_wall_3]
    result_none = m.solve_t_intersection(node, walls_3, CATALOG, openings_per_wall=openings_tight)
    assert result_none["ok"] is False


@case
def test_b34_no_meio_da_parede_priorizado_sobre_compensadores():
    """Pedido explicito do usuario (2026-08-21): "o bloco de 34cm tambem
    pode ser utilizado no meio de uma parede... para reduzir o uso de
    compensadores", com prioridade B39 -> B19 -> B34 -> compensadores.
    pier=76cm com as duas pontas AMARRADAS (nao ha' onde encostar um B19)
    so' fecha sem compensador usando B39+B34 - tem que preferir isso a
    qualquer compensador."""
    layout = m._pier_ordered_layout(76.0, CATALOG, 1.0, 1.0)
    codes = [c for c, _a, _b in layout]
    assert codes == ["B39", "B34"], layout
    assert sum(1 for c in codes if CATALOG[c]["is_compensator"]) == 0
    assert "B19" not in codes


@case
def test_proibido_dois_compensadores_consecutivos_como_solucao():
    """Regra absoluta do usuario (2026-08-21): "extremamente proibido...
    duas pastilhas ou combinacoes consecutivas de compensadores... usados
    apenas de forma pontual, nunca em sequencia" - nenhum layout devolvido
    por _pier_ordered_layout (com o catalogo completo, compensadores
    ligados) pode ter 2+ pecas is_compensator=True."""
    # varre uma faixa de pilaretes (multiplos de 5, as duas pontas amarradas
    # - o caso mais dificil, sem B19/ponta aberta para ajudar) e confere que
    # NENHUM resultado usa 2+ compensadores.
    for pier_cm in range(20, 400, 5):
        layout = m._pier_ordered_layout(float(pier_cm), CATALOG, 1.0, 1.0)
        if layout is None:
            continue
        comp_count = sum(1 for c, _a, _b in layout if CATALOG[c]["is_compensator"])
        assert comp_count <= 1, (pier_cm, layout)


@case
def test_merge_9_mais_9_vira_19():
    """Regra #2 explicita do usuario (2026-08-24): "quando houver 9+9,
    substitua preferencialmente por 19" - 9+1(junta)+9=19cm bate EXATO com
    o comprimento do B19 neste catalogo (coincidencia matematica do
    catalogo, nao hardcoded)."""
    layout = [("C09", 0.0, 9.0), ("C09", 10.0, 19.0)]
    merged = m._merge_adjacent_compensator_pairs(layout, CATALOG)
    assert merged == [("B19", 0.0, 19.0)], merged

    # 3 consecutivos: o par ADJACENTE funde, sobra 1 compensador isolado
    # (nunca mais 2+ em sequencia) - nao ha' garantia de zero compensador,
    # so' de nenhuma SEQUENCIA.
    layout3 = [("C09", 0.0, 9.0), ("C09", 10.0, 19.0), ("C09", 20.0, 29.0)]
    merged3 = m._merge_adjacent_compensator_pairs(layout3, CATALOG)
    assert merged3 == [("B19", 0.0, 19.0), ("C09", 20.0, 29.0)], merged3

    # codigos diferentes ou nao-adjacentes nao sao mexidos.
    layout_mixed = [("C09", 0.0, 9.0), ("C04", 10.0, 14.0)]
    assert m._merge_adjacent_compensator_pairs(layout_mixed, CATALOG) == layout_mixed
    assert m._merge_adjacent_compensator_pairs([], CATALOG) == []


@case
def test_merge_9_mais_9_nao_vira_19_encostado_em_no_fechado():
    """BUG REAL corrigido (2026-08-25): a fusao 9+9->19 (regra #2 de
    2026-08-24, ver teste acima) e' uma otimizacao "inocente" que nao
    sabia se a posicao onde o B19 resultante nasce e' uma ponta ABERTA de
    verdade - ela conseguia colocar um B19 encostado direto num no' de
    amarracao FECHADO so' porque a aritmetica batia (2 compensadores
    adjacentes do mesmo codigo, span == B19), violando a regra #2 do
    usuario ("nao utilizar meio bloco... como recurso para fechar uma
    amarracao") por uma porta lateral que nenhuma checagem de
    leading_is_open/trailing_is_open nos outros tiers cobria (elas so'
    guardam ONDE um B19 e' ESCOLHIDO de proposito, nao um que nasce de
    uma fusao de otimizacao)."""
    layout = [("C09", 0.0, 9.0), ("C09", 10.0, 19.0)]

    # ponta ABERTA de verdade (default, comportamento antigo preservado -
    # ver teste acima): funde normalmente.
    assert m._merge_adjacent_compensator_pairs(
        layout, CATALOG, leading_open=True, trailing_open=True
    ) == [("B19", 0.0, 19.0)]

    # AMBAS as pontas fechadas (contra um no' L/T/X, sem onde B19
    # encostar): o par fica INTOCADO - nunca vira B19 so' porque a
    # aritmetica bate. O chamador (que confere o teto de compensadores
    # DEPOIS da fusao) e' quem decide o que fazer com 2 compensadores
    # nao fundidos (ex.: cair para o proximo tier).
    assert m._merge_adjacent_compensator_pairs(
        layout, CATALOG, leading_open=False, trailing_open=False
    ) == layout

    # so' a ponta de SAIDA aberta: o par esta' na ponta de ENTRADA (i==0)
    # de um layout so' com essas 2 pecas - span cobre a ponta de entrada E
    # a de saida ao mesmo tempo (layout inteiro e' so' o par) - qualquer
    # lado aberto basta.
    assert m._merge_adjacent_compensator_pairs(
        layout, CATALOG, leading_open=False, trailing_open=True
    ) == [("B19", 0.0, 19.0)]

    # o mesmo par, agora no MEIO de um layout maior (B34 antes E depois) -
    # NUNCA pode virar B19, mesmo com as duas pontas do TRECHO abertas:
    # B19 no meio de um trecho e' proibido incondicionalmente (secao 2),
    # nao so' contra no' fechado.
    layout_meio = [("B34", 0.0, 34.0), ("C09", 35.0, 44.0), ("C09", 45.0, 54.0), ("B34", 55.0, 89.0)]
    assert m._merge_adjacent_compensator_pairs(
        layout_meio, CATALOG, leading_open=True, trailing_open=True
    ) == layout_meio


@case
def test_pier_ordered_layout_nunca_devolve_dois_compensadores_iguais_adjacentes():
    """Integra a fusao (`_merge_adjacent_compensator_pairs`) ao pipeline
    real de `_pier_ordered_layout` - varre a mesma faixa do teste "proibido
    dois compensadores consecutivos" e confirma que, alem da contagem total
    (ja' coberta), NENHUM par ADJACENTE do mesmo codigo compensador
    sobrevive no layout final."""
    for pier_cm in range(20, 400, 5):
        layout = m._pier_ordered_layout(float(pier_cm), CATALOG, 1.0, 1.0)
        if layout is None:
            continue
        for i in range(len(layout) - 1):
            code_a, code_b = layout[i][0], layout[i + 1][0]
            same_adjacent_comp = (
                code_a == code_b and CATALOG[code_a]["is_compensator"]
            )
            assert not same_adjacent_comp, (pier_cm, layout)


# ------------------------------------------------------------------------
# Orientacao dos compensadores (regra #3, pedido explicito do usuario,
# 2026-08-25): lado fechado sempre voltado para a abertura.
# ------------------------------------------------------------------------

def _comp_candidate(wall_idx, center_cm, length_cm, x_dir=(1.0, 0.0, 0.0), code="C04"):
    return {
        "wall_idx": wall_idx, "origin_world": XYZ(ft(center_cm), 0.0, 0.0),
        "x_dir": XYZ(*x_dir), "y_dir": XYZ(0.0, 1.0, 0.0),
        "length_cm": length_cm, "width_cm": 14.0, "course": "A",
        "logical_code": code,
    }


@case
def test_compensador_exige_espelhamento_conforme_lado_da_abertura():
    """Regra #3 explicita do usuario (2026-08-25): "o lado fechado deve
    estar sempre voltado para a abertura... a orientacao deve ser
    determinada automaticamente de acordo com a posicao da abertura"."""
    walls_to_create = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    p0, _p1, wall_dir, _len, _t = m._wall_axis_and_length(walls_to_create, 0)
    openings_cm = [(100.0, 150.0)]  # (t_lo, t_hi) em cm

    # As asserts abaixo comparam RELATIVO a' premissa (COMPENSATOR_CLOSED_
    # SIDE_IS_PLUS_X_WHEN_UNMIRRORED) em vez de hardcodar True/False - a
    # LOGICA testada (o espelhamento inverte conforme o lado da abertura e
    # conforme x_dir) tem que valer QUALQUER que seja o valor real da
    # premissa fisica (documentada como nao confirmada - ver a constante).
    premissa = m.COMPENSATOR_CLOSED_SIDE_IS_PLUS_X_WHEN_UNMIRRORED

    # compensador de 5cm ENCOSTADO na jamba ESQUERDA da abertura (95-100) -
    # a abertura fica do lado +t (direita) da peca -> lado fechado tem que
    # apontar para +t -> so' precisa espelhar se a premissa disser "fechado
    # e' -x sem espelhar" (i.e., premissa False).
    right_of_piece_opening = _comp_candidate(0, 97.5, 5.0)
    required = m._compensator_required_mirror(right_of_piece_opening, openings_cm, p0, wall_dir)
    assert required is (not premissa), required

    # compensador ENCOSTADO na jamba DIREITA da abertura (150-155) - a
    # abertura fica do lado -t (esquerda) da peca -> exige o espelhamento
    # OPOSTO do caso acima, qualquer que seja a premissa.
    left_of_piece_opening = _comp_candidate(0, 152.5, 5.0)
    required2 = m._compensator_required_mirror(left_of_piece_opening, openings_cm, p0, wall_dir)
    assert required2 is premissa, required2
    assert required2 != required

    # compensador longe de qualquer abertura - nenhuma orientacao exigida.
    far = _comp_candidate(0, 300.0, 4.0)
    assert m._compensator_required_mirror(far, openings_cm, p0, wall_dir) is None

    # mesmo caso da jamba esquerda, mas com x_dir INVERTIDO (antiparalelo
    # a wall_dir) - a exigencia fisica (lado fechado voltado para a
    # abertura, aqui do lado +t) e' a MESMA, mas como o +x LOCAL da peca
    # aponta para o lado ERRADO da parede, o espelhamento exigido inverte
    # em relacao ao caso original (`required`), sempre.
    reversed_x = _comp_candidate(0, 97.5, 5.0, x_dir=(-1.0, 0.0, 0.0))
    required_reversed = m._compensator_required_mirror(reversed_x, openings_cm, p0, wall_dir)
    assert required_reversed != required


@case
def test_orient_compensator_candidates_corrige_todos_de_uma_vez():
    """orient_compensator_candidates e' o passo de "validar e corrigir
    automaticamente qualquer um que esteja invertido" pedido pelo usuario -
    roda sobre a lista inteira e escreve/CORRIGE "mirrored" em cada
    compensador, sem tocar em pecas que nao sao compensadores."""
    walls_to_create = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    openings_per_wall = [[(ft(100.0), ft(150.0), ft(0.0), ft(210.0))]]
    catalog = {
        "C04": {"is_compensator": True, "length_cm": 4.0},
        "B39": {"is_compensator": False, "length_cm": 39.0},
    }
    comp_needs_mirror = _comp_candidate(0, 152.5, 5.0, code="C04")
    comp_no_mirror = _comp_candidate(0, 97.5, 5.0, code="C04")
    comp_far = _comp_candidate(0, 300.0, 4.0, code="C04")
    # os dois JA' vem com um valor ERRADO (o OPOSTO do que deveriam ter,
    # qualquer que seja a premissa fisica) de uma rodada anterior - a
    # funcao precisa CORRIGIR os dois, nao so' preencher quando ausente.
    premissa = m.COMPENSATOR_CLOSED_SIDE_IS_PLUS_X_WHEN_UNMIRRORED
    comp_needs_mirror["mirrored"] = not premissa   # correto seria `premissa`
    comp_no_mirror["mirrored"] = premissa          # correto seria `not premissa`
    whole_block = _comp_candidate(0, 250.0, 39.0, code="B39")

    candidates = [comp_needs_mirror, comp_no_mirror, comp_far, whole_block]
    m.orient_compensator_candidates(candidates, walls_to_create, openings_per_wall, catalog)

    # valores CORRIGIDOS (nao os que foram pre-setados acima) - confirma
    # que a funcao SEMPRE recalcula, mesmo quando "mirrored" ja' existia.
    assert comp_needs_mirror["mirrored"] is premissa, comp_needs_mirror
    assert comp_no_mirror["mirrored"] is (not premissa), comp_no_mirror
    # longe de qualquer abertura - nunca espelhado.
    assert comp_far["mirrored"] is False
    # bloco inteiro (nao-compensador) nunca recebe "mirrored".
    assert "mirrored" not in whole_block


# ------------------------------------------------------------------------
# Relatorio final consolidado (item 4/5 do pedido do usuario, 2026-08-25).
# ------------------------------------------------------------------------

@case
def test_build_final_modulation_report_junta_etapa_3b_e_4c():
    """Pedido explicito do usuario (2026-08-25): "quantidade de paredes
    analisadas; quantidade inicialmente com erro; quantidade corrigida;
    quantidade modulada com sucesso; quantidade que permaneceu sem
    solucao; motivo de cada parede que nao pode ser resolvida" - juntando
    as duas fontes de problema (Etapa 3B: modulacao aritmetica; Etapa 4C:
    amarracao entre fiadas) que o script conhece, nunca uma so'."""
    walls_to_create = [
        (seg(0, 0, 100, 0), ft(14.0), (False, False)),  # 0: sem erro nenhum
        (seg(0, 0, 100, 10), ft(14.0), (False, False)), # 1: erro corrigido (Etapa 3B)
        (seg(0, 0, 100, 20), ft(14.0), (False, False)), # 2: erro NAO corrigido (Etapa 3B)
        (seg(0, 0, 100, 30), ft(14.0), (False, False)), # 3: fecha, mas reprovada na amarracao (Etapa 4C)
        (seg(0, 0, 100, 40), ft(14.0), (False, False)), # 4: erro NAO corrigido E reprovada nas duas
    ]
    error_rows = [
        {"wall_idx": 1, "problem_text": "modulacao nao fecha - trecho X", "resolved": True},
        {"wall_idx": 2, "problem_text": "modulacao nao fecha - trecho Y", "resolved": False},
        {"wall_idx": 4, "problem_text": "modulacao nao fecha - trecho Z", "resolved": False},
    ]
    wall_bond_audits = {
        3: {"ok": False, "problems": ["CONTINUOUS_VERTICAL_JOINT: junta corrida em X~10.0cm"]},
        4: {"ok": False, "problems": ["HALF_BLOCK_NEAR_TIE: meio bloco a 0.0cm de uma amarracao"]},
    }
    skipped_wall_idxs = [3, 4]

    report = m.build_final_modulation_report(
        walls_to_create, error_rows, wall_bond_audits=wall_bond_audits,
        skipped_wall_idxs=skipped_wall_idxs,
    )
    assert report["total_analyzed"] == 5, report
    assert report["initially_with_error"] == 3, report  # len(error_rows), nunca muda
    assert report["corrected_automatically"] == 1, report  # so' o eixo 1
    # sem solucao: eixo 2 (3B nao corrigido), 3 (4C reprovada), 4 (as duas).
    assert report["unresolved_count"] == 3, report
    assert report["modulated_successfully"] == 2, report  # eixos 0 e 1

    by_wall = dict((e["wall_idx"], e["reasons"]) for e in report["unresolved"])
    assert set(by_wall.keys()) == {2, 3, 4}
    assert any("Etapa 3B" in r for r in by_wall[2])
    assert any("Etapa 4C" in r for r in by_wall[3])
    # eixo 4 falhou nas DUAS etapas - os DOIS motivos aparecem juntos.
    assert any("Etapa 3B" in r for r in by_wall[4])
    assert any("Etapa 4C" in r for r in by_wall[4])

    text = m._format_final_modulation_report(report)
    assert "Paredes (eixos) analisadas: 5" in text
    assert "Moduladas com sucesso" in text and "2" in text
    assert "eixo 4" in text


@case
def test_on_create_done_anexa_o_relatorio_final_consolidado_no_log():
    """Wiring fim-a-fim: _on_create_done (fim de "Lancar Blocos - criar",
    o ultimo passo da janela unica) precisa montar e anexar o relatorio
    final consolidado (item 4/5 do pedido do usuario) no log - nao basta
    a funcao existir, ela precisa realmente ser chamada com os dados
    certos (error_rows da Etapa 3B + wall_bond_audits/skipped_wall_idxs
    da Etapa 4C, ambos so' disponiveis depois de "criar")."""
    report_dict = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 0, "wall_ids": [], "problem_text": "modulacao nao fecha", "resolved": False,
         "auto_fixable": False, "fix_plan": None},
    ])
    handler.walls_to_create = [
        (seg(0, 0, 100, 0), ft(14.0), (False, False)),
        (seg(0, 0, 100, 10), ft(14.0), (False, False)),
    ]
    handler.solve_result = {
        "wall_bond_audits": {
            1: {"ok": False, "problems": ["CONTINUOUS_VERTICAL_JOINT: junta corrida em X~5.0cm"]},
        },
        "collisions": [], "door_void_violations": [],
    }
    handler.create_result = {
        "created_count": 3, "failures": [], "created_instances": [],
        "course_height_ft": ft(20.0), "course_height_error": None,
        "skipped_wall_count": 0, "skipped_wall_idxs": [],
        "reproved_wall_count": 1, "reproved_wall_idxs": [1],
    }

    form = m._PostCreationForm(report_dict, None, handler, [])
    form._on_create_done("create", None)

    log_text = form._log_box.Text
    assert "Relatorio final de modulacao" in log_text
    assert "Paredes (eixos) analisadas: 2" in log_text
    assert "Moduladas com sucesso" in log_text
    # os DOIS eixos sem solucao aparecem, cada um com o motivo da etapa certa.
    assert "eixo 0" in log_text and "Etapa 3B" in log_text
    assert "eixo 1" in log_text and "Etapa 4C" in log_text


@case
def test_jamb_bloco_principal_repetido_e_recusado_mesmo_alinhado():
    """REGRA CRITICA #1 (excecao), pedido explicito do usuario (2026-08-24):
    junta vertical coincidente entre fiadas so' e' tolerada perto de
    abertura para pecas PEQUENAS (4/9/19cm) - blocos principais (34/39cm)
    NUNCA, mesmo quando repetir o MESMO bloco nas duas fiadas seria a
    UNICA combinacao que fecha o pilarete (offset 0, alinhamento
    perfeito)."""
    only_b39 = {"B39": CATALOG["B39"]}
    walls = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    # abertura terminando 40cm antes do fim da parede -> pilarete direito
    # de 40cm, que so' fecha com B39 (39+1cm de junta = 40cm exato).
    openings_sorted = [(ft(0.0), ft(360.0), 0.0, ft(210.0))]
    result = m.solve_opening_jamb(walls, 0, openings_sorted, 0, "right", only_b39)
    assert result["exception"] is True
    assert result["reason"].startswith("JOINT_ALIGNMENT_FORBIDDEN_MAIN_BLOCK"), result["reason"]
    assert result["course_a"]["logical_code"] == "B39"
    assert result["course_b"]["logical_code"] == "B39"


@case
def test_jamb_bloco_pequeno_repetido_continua_permitido():
    """Contraparte do teste acima: para pecas PEQUENAS (aqui C09, 9cm) a
    excecao da regra critica #1 continua valendo normalmente - repetir o
    MESMO bloco pequeno nas duas fiadas perto de uma abertura NAO e' um
    erro."""
    only_c09 = {"C09": CATALOG["C09"]}
    walls = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    # pilarete direito de 10cm - so' fecha com C09 (9+1cm de junta = 10cm).
    openings_sorted = [(ft(0.0), ft(390.0), 0.0, ft(210.0))]
    result = m.solve_opening_jamb(walls, 0, openings_sorted, 0, "right", only_c09)
    assert result["ok"] is True
    assert result["exception"] is False
    assert result["course_a"]["logical_code"] == "C09"
    assert result["course_b"]["logical_code"] == "C09"


@case
def test_jamb_variant_count_gera_variantes_distintas_sem_repetir_cruzado():
    """Secao 11.7 (2026-08-25): `solve_opening_jamb(..., variant_count=K)`
    gera ate' K blocos de jamb DISTINTOS por familia (par/impar), a partir
    do MESMO catalogo que a busca de alinhamento original ja considerava -
    peca central da correcao do bug real (118/128 paredes reprovadas na
    auditoria de amarracao): sem variar o jamb tambem, so' variar o
    preenchimento comum nao bastava (o jamb continuava identico em 100%
    das fiadas da mesma paridade). Confere tres coisas:
      1. a variante 0 de cada familia e' EXATAMENTE igual a "course_a"/
         "course_b" (a mesma busca de alinhamento de sempre - retro-
         compatibilidade byte-a-byte com todo chamador que nao pediu
         variantes, ver os dois testes acima);
      2. NENHUM codigo de uma variante da familia A e' igual a NENHUM
         codigo de NENHUMA variante da familia B (generaliza a REGRA
         CRITICA #1 - "bloco principal repetido no mesmo lugar e' junta
         continua proibida" - de um unico par A/B para todo par cruzado);
      3. com pilarete grande o bastante para o catalogo oferecer varios
         codigos iniciais, as variantes extras sao FISICAMENTE distintas
         entre si (nao apenas repeticoes da variante 0)."""
    walls = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    openings_sorted = [(ft(0.0), ft(200.0), 0.0, ft(210.0))]
    result = m.solve_opening_jamb(walls, 0, openings_sorted, 0, "right", CATALOG, variant_count=3)
    assert result["ok"] is True

    variants_a = result["course_a_variants"]
    variants_b = result["course_b_variants"]
    assert len(variants_a) == 3 and len(variants_b) == 3

    # 1. variante 0 == resultado historico.
    assert variants_a[0]["logical_code"] == result["course_a"]["logical_code"]
    assert variants_b[0]["logical_code"] == result["course_b"]["logical_code"]

    # 2. nenhum codigo cruza entre familias (regra critica #1 generalizada).
    codes_a = {v["logical_code"] for v in variants_a}
    codes_b = {v["logical_code"] for v in variants_b}
    assert not (codes_a & codes_b), (codes_a, codes_b)

    # 3. o catalogo completo (varios codigos possiveis para um pilarete de
    # 200cm) permite variantes de verdade, nao so' repeticoes da 0.
    assert len(codes_a) > 1, codes_a
    assert len(codes_b) > 1, codes_b


@case
def test_validacao_pega_compensadores_de_trechos_diferentes_adjacentes():
    """Regra #2/#8: a fusao de `_pier_ordered_layout` so' enxerga UM
    trecho por vez - dois compensadores de TRECHOS diferentes (ex.: o
    compensador de um jamb de abertura encostado no compensador do
    preenchimento comum vizinho) podem ficar fisicamente adjacentes sem
    que nenhuma das duas chamadas veja o problema. `validate_wall_
    modulation` (regra #8, com `catalog` informado) tem que pegar isso
    DEPOIS de tudo posicionado."""
    walls = [(seg(0, 0, 100, 0), ft(14.0), (False, False))]
    p0, _p1, direction, _len_ft, _th = m._wall_axis_and_length(walls, 0)
    # dois candidatos C09 vindos de duas chamadas SEPARADAS de
    # _place_pier_layout (simulando duas origens/trechos diferentes),
    # posicionados fisicamente adjacentes (junta de 1cm entre eles).
    cand_a = m._place_pier_layout([("C09", 0.0, 9.0)], CATALOG, p0, direction, "A", 0)[0]
    cand_b = m._place_pier_layout([("C09", 10.0, 19.0)], CATALOG, p0, direction, "A", 0)[0]
    candidates = [cand_a, cand_b]

    runs = m._find_consecutive_compensators(0, walls, candidates, CATALOG)
    assert runs, "tem que detectar os dois C09 adjacentes"
    assert runs[0]["course"] == "A"

    fill_result = {"candidates": candidates, "non_modular": [], "jamb_exceptions": []}
    validation = m.validate_wall_modulation(0, walls, [[]], fill_result, catalog=CATALOG)
    assert validation["checks"]["sem_compensadores_consecutivos"] is False
    assert not validation["ok"]

    # sem `catalog` (chamadores antigos/testes que nao passam), o check
    # nao pode ser calculado - fica True para nao quebrar retrocompat.
    validation_no_catalog = m.validate_wall_modulation(0, walls, [[]], fill_result)
    assert validation_no_catalog["checks"]["sem_compensadores_consecutivos"] is True


@case
def test_ajuste_de_abertura_mantem_pilaretes_em_multiplo_de_cinco():
    plan = m.solve_opening_modulation(400, 80, 160, 160)
    assert plan is not None
    assert plan["width_cm"] % 10 in (1, 6, 9) or str(plan["width_cm"])[-1] in "169"
    assert plan["left_cm"] % 5 == 0 and plan["right_cm"] % 5 == 0
    assert plan["left_cm"] + plan["right_cm"] + plan["width_cm"] == plan["axis_cm"]


# ------------------------------------------- ETAPA 3B (correcao pos-criacao)
@case
def test_solver_de_eixo_generaliza_para_duas_aberturas():
    # 3 gaps (2 aberturas), soma 130 (multiplo de 5) mas nenhum gap
    # individualmente e' - confirma que o novo solver acha uma particao
    # valida preservando a soma total (largura/eixo nunca mudam aqui).
    gaps = [47.0, 33.0, 50.0]
    result = m.solve_axis_opening_modulation(gaps)
    assert result is not None
    assert sum(result["gaps_after_cm"]) == sum(gaps)
    assert all(g % 5 == 0 for g in result["gaps_after_cm"])
    assert result["max_shift_cm"] <= 5.0
    assert result["within_auto_apply_limit"] is True


@case
def test_solver_de_eixo_impossivel_quando_soma_nao_e_multiplo_de_cinco():
    # soma = 131 - prova matematica: soma de multiplos de 5 e' sempre
    # multiplo de 5, entao nenhum deslocamento resolve isto (nao e' "fora
    # do raio de busca", e' impossivel).
    gaps = [47.0, 33.0, 51.0]
    assert m.solve_axis_opening_modulation(gaps) is None


@case
def test_solver_de_eixo_marca_acima_do_teto_como_nao_automatico():
    gaps = [47.0, 83.0]
    result = m.solve_axis_opening_modulation(gaps, max_shift_cm=1.0)
    assert result is not None
    assert result["within_auto_apply_limit"] is False
    assert result["max_shift_cm"] > 1.0


class _FakeWall(object):
    def __init__(self, curve):
        # precisa ser instancia de m.LocationCurve de verdade - o codigo
        # sob teste confere `isinstance(wall.Location, LocationCurve)`.
        self.Location = m.LocationCurve()
        self.Location.Curve = curve


class _FakeDoc(object):
    """Doc minimo so' para GetElement/Regenerate - _classify_wall_axis_segments/
    plan_axis_opening_fix/apply_wall_group_shift nunca fazem mais nada com
    o doc alem de ler Location.Curve e chamar Regenerate() (sempre um
    no-op aqui - os Wall falsos ja refletem a edicao na hora)."""

    def __init__(self, elements):
        self._elements = elements

    def GetElement(self, element_id):
        return self._elements.get(element_id)

    def Regenerate(self):
        pass


def _one_opening_axis_fixture(pier_left_cm, width_cm, pier_right_cm):
    """Eixo reto de pier_left+width+pier_right cm, com os 3 segmentos
    reais (pilar/infill/pilar) ja' 'criados' como Wall falsos - o mesmo
    layout que build_wall_segments produz para 1 abertura floor-to-head."""
    axis_len_cm = pier_left_cm + width_cm + pier_right_cm
    axis = seg(0, 0, axis_len_cm, 0)
    pier_left_curve = seg(0, 0, pier_left_cm, 0)
    infill_curve = seg(pier_left_cm, 0, pier_left_cm + width_cm, 0)
    pier_right_curve = seg(pier_left_cm + width_cm, 0, axis_len_cm, 0)
    id_pier_left, id_infill, id_pier_right = 201, 202, 203
    fake_doc = _FakeDoc({
        id_pier_left: _FakeWall(pier_left_curve),
        id_infill: _FakeWall(infill_curve),
        id_pier_right: _FakeWall(pier_right_curve),
    })
    walls_to_create = [(axis, ft(14.0), (False, False))]
    openings_per_wall = [[(ft(pier_left_cm), ft(pier_left_cm + width_cm), 0.0, ft(210.0))]]
    created_walls_by_axis = {
        0: [(id_pier_left, "cad"), (id_infill, "abertura"), (id_pier_right, "cad")]
    }
    center_t_ft = ft(pier_left_cm + width_cm / 2.0)
    opening = {
        "element_id_obj": 999, "element_id": "999",
        "center_xy": XYZ(axis.GetEndPoint(0).X + center_t_ft, 0.0, 0.0),
        "width_ft": ft(width_cm),
    }
    return fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, [opening], id_infill


@case
def test_classifica_segmentos_reais_de_um_eixo_com_uma_abertura():
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, _openings, id_infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    result = m._classify_wall_axis_segments(
        fake_doc, 0, walls_to_create, openings_per_wall, created_walls_by_axis
    )
    assert result is not None
    assert len(result["piers"]) == 2
    assert len(result["openings"]) == 1
    assert result["openings"][0]["infill_ids"] == [id_infill]
    assert abs(to_cm(result["piers"][0]["t_b"] - result["piers"][0]["t_a"]) - 162.0) < 0.01
    assert abs(to_cm(result["piers"][1]["t_b"] - result["piers"][1]["t_a"]) - 158.0) < 0.01


@case
def test_classifica_segmentos_a_partir_do_snapshot_sem_target_doc():
    """MUDANCA 1 do plano de arquitetura "solver em memoria/aplicacao
    unica" (2026-08-26): com wall_segment_geometry fornecido,
    _classify_wall_axis_segments nunca toca target_doc (passado como None
    de proposito aqui - se algo ainda chamasse target_doc.GetElement, isto
    quebraria com AttributeError) - mesmo resultado que a leitura ao vivo
    (ver test_classifica_segmentos_reais_de_um_eixo_com_uma_abertura,
    acima), so' que a partir do snapshot que main() captura uma unica vez
    na criacao das Walls (mesma formula, _axis_t_of_point)."""
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, _openings, id_infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    axis, _thickness_ft, _locks = walls_to_create[0]
    wall_segment_geometry = {0: []}
    for element_id, seg_origin in created_walls_by_axis[0]:
        curve = fake_doc.GetElement(element_id).Location.Curve
        t_a = m._axis_t_of_point(axis, curve.GetEndPoint(0))
        t_b = m._axis_t_of_point(axis, curve.GetEndPoint(1))
        if t_a > t_b:
            t_a, t_b = t_b, t_a
        wall_segment_geometry[0].append({
            "element_id": element_id, "seg_origin": seg_origin, "t_a": t_a, "t_b": t_b,
        })

    result = m._classify_wall_axis_segments(
        None, 0, walls_to_create, openings_per_wall, created_walls_by_axis,
        wall_segment_geometry=wall_segment_geometry,
    )
    assert result is not None
    assert len(result["piers"]) == 2
    assert len(result["openings"]) == 1
    assert result["openings"][0]["infill_ids"] == [id_infill]
    assert abs(to_cm(result["piers"][0]["t_b"] - result["piers"][0]["t_a"]) - 162.0) < 0.01
    assert abs(to_cm(result["piers"][1]["t_b"] - result["piers"][1]["t_a"]) - 158.0) < 0.01


@case
def test_classifica_segmentos_com_snapshot_incompleto_devolve_none_sem_cair_para_leitura_ao_vivo():
    """Contrato de seguranca (ver docstring de _classify_wall_axis_segments):
    quando wall_segment_geometry e' fornecido mas a entrada do eixo esta'
    incompleta (len diferente de created_walls_by_axis[wall_idx]), devolve
    None - NUNCA cai de volta para leitura ao vivo via target_doc, que
    exigiria um contexto de API valido indisponivel numa thread de fundo
    (ver Mudanca 2)."""
    _fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, _openings, _id_infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    result = m._classify_wall_axis_segments(
        None, 0, walls_to_create, openings_per_wall, created_walls_by_axis,
        wall_segment_geometry={0: []},  # incompleto de proposito (faltam os 3 segmentos)
    )
    assert result is None


@case
def test_plano_de_ajuste_pos_criacao_desloca_o_minimo_e_preserva_largura():
    # pilaretes 162/158 (nenhum multiplo de 5, soma 320 = multiplo de 5) ->
    # a unica correcao so'-de-posicao fecha em 160/160, deslocamento -2cm.
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _id_infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    plan = m.plan_axis_opening_fix(
        fake_doc, 0, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings
    )
    assert plan["feasible"] is True, plan.get("reason")
    assert len(plan["new_openings"]) == 1
    new_op = plan["new_openings"][0]
    # largura da abertura JAMAIS muda - regra nova do usuario
    assert abs(to_cm(new_op["t_hi_new"] - new_op["t_lo_new"]) - 80.0) < 0.01
    # pilaretes resultantes, todos multiplos de 5
    for pier in plan["new_piers"]:
        length_cm = to_cm(pier["t_b_new"] - pier["t_a_new"])
        assert abs(round(length_cm / 5.0) * 5.0 - length_cm) < 0.01, length_cm
    assert abs(to_cm(new_op["shift_ft"]) - (-2.0)) < 0.01
    assert plan["max_shift_cm"] <= 5.0


@case
def test_plano_de_ajuste_pos_criacao_eixo_ja_modular_nao_muda_nada():
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _id_infill = (
        _one_opening_axis_fixture(160.0, 80.0, 160.0)
    )
    plan = m.plan_axis_opening_fix(
        fake_doc, 0, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings
    )
    assert plan["feasible"] is True
    assert plan["already_ok"] is True
    assert plan["new_openings"] == [] and plan["new_piers"] == []


@case
def test_boneca_compensated_solutions_gera_padrao_correto():
    """Unidade pura de `_boneca_compensated_solutions`: boneca na PONTA 0
    cresce OU encolhe (generalizado 2026-08-24 - ver docstring da funcao),
    ponta oposta (ultimo pilarete) compensa em sentido contrario pelo
    mesmo valor, soma total preservada, ordem = |delta| crescente com o
    sentido positivo (cresce) antes do negativo (encolhe) em cada
    magnitude: +1, -1, +2, -2."""
    gaps = [15.0, 20.0]  # 1 abertura, pilaretes 15/20
    solutions = list(m._boneca_compensated_solutions(gaps, [0], min_pier_cm=5.0))
    assert len(solutions) == int(m.BONECA_ADJUST_MAX_CM) * 2
    first = solutions[0]
    assert first["gaps_after_cm"] == [16.0, 19.0]
    assert sum(first["gaps_after_cm"]) == sum(gaps)
    assert first["opening_shifts_cm"] == [1.0]
    assert first["boneca_delta_cm"] == 1
    # segundo candidato: MESMA magnitude (1cm), sentido invertido - a boneca
    # ENCOLHE em vez de crescer (o caso concreto reportado pelo usuario:
    # boneca 11cm -> 10cm, trecho oposto 144cm -> 145cm).
    second = solutions[1]
    assert second["gaps_after_cm"] == [14.0, 21.0]
    assert second["opening_shifts_cm"] == [-1.0]
    assert second["boneca_delta_cm"] == -1
    third = solutions[2]
    assert third["gaps_after_cm"] == [17.0, 18.0]

    # boneca na ponta OPOSTA (1): pilarete 1 cresce, pilarete 0 encolhe, e
    # a abertura desloca no sentido NEGATIVO (mesmo sentido do crescimento).
    solutions_end1 = list(m._boneca_compensated_solutions(gaps, [1], min_pier_cm=5.0))
    assert solutions_end1[0]["gaps_after_cm"] == [14.0, 21.0]
    assert solutions_end1[0]["opening_shifts_cm"] == [-1.0]

    # ENCOLHER a boneca pode fechar um caso que CRESCER nao fecha (pilarete
    # oposto pequeno demais para ceder espaco) - exatamente o caso real do
    # usuario: o lado oposto tinha pouca folga para encolher, mas sobra
    # espaco de sobra para CRESCER quando a boneca encolhe.
    tiny_gaps = [15.0, 5.5]
    tiny_solutions = list(m._boneca_compensated_solutions(tiny_gaps, [0], min_pier_cm=5.0))
    assert len(tiny_solutions) == 2  # so' os 2 candidatos de ENCOLHER (delta -1 e -2)
    assert all(s["boneca_delta_cm"] < 0 for s in tiny_solutions)
    assert tiny_solutions[0]["gaps_after_cm"] == [14.0, 6.5]  # 5.5-1=4.5<5 ao crescer, mas 5.5+1=6.5 ok ao encolher

    # compensacao fisicamente impossivel nos DOIS sentidos (os dois
    # pilaretes ja' estao no minimo) e' descartada silenciosamente, nunca
    # lanca excecao.
    both_tiny_gaps = [5.5, 5.5]
    both_tiny_solutions = list(m._boneca_compensated_solutions(both_tiny_gaps, [0], min_pier_cm=5.0))
    assert both_tiny_solutions == []


@case
def test_boneca_caso_real_reportado_pelo_usuario_23_e_107():
    """Regressao com os numeros reais reportados pelo usuario (2026-08-21,
    print de uma porta 80x210 com boneca de 23cm e parede oposta de 107cm):
    boneca 23->24cm (1o candidato, menor delta), porta desloca +1cm no MESMO
    sentido do crescimento, parede oposta 107->106cm compensando - soma
    preservada (130cm nos dois casos)."""
    gaps = [23.0, 107.0]
    solutions = list(m._boneca_compensated_solutions(gaps, [0], min_pier_cm=5.0))
    first = solutions[0]
    assert first["gaps_after_cm"] == [24.0, 106.0]
    assert first["opening_shifts_cm"] == [1.0]
    assert sum(first["gaps_after_cm"]) == sum(gaps) == 130.0


# --------------------------- JANELA NAO INTERROMPE A FIADA (2026-08-21) ---
@case
def test_opening_active_in_course_band_so_conta_sobreposicao_real():
    sill, head = ft(50.0), ft(70.0)
    # fiada inteiramente ABAIXO do peitoril - abertura nao conta ali
    assert m._opening_active_in_course_band(sill, head, ft(1.0), ft(20.0)) is False
    # fiada inteiramente ACIMA da verga - idem
    assert m._opening_active_in_course_band(sill, head, ft(81.0), ft(100.0)) is False
    # fiada que cruza o peitoril (parte dentro, parte fora) - conta
    assert m._opening_active_in_course_band(sill, head, ft(41.0), ft(60.0)) is True
    # fiada inteira DENTRO do vao - conta
    assert m._opening_active_in_course_band(sill, head, ft(55.0), ft(58.0)) is True


@case
def test_group_course_indices_by_opening_band_janela_deixa_fiadas_solidas_fora_do_vao():
    """Reproduz o pedido do usuario (2026-08-21, com imagens de
    referencia): uma janela com peitoril 50cm/verga 70cm NAO deve interromper
    as fiadas fisicas 1, 2 e 5 (fora do vao) - so' as fiadas 3 e 4 (que
    cruzam o vao real) ficam com a abertura ativa."""
    opening = (ft(10.0), ft(30.0), ft(50.0), ft(70.0))
    openings_per_wall = [[opening]]
    base_z_abs = ft(0.0)
    course_height_ft = ft(20.0)   # bloco 19cm + junta 1cm
    block_height_ft = ft(19.0)
    groups = m._group_course_indices_by_opening_band(
        openings_per_wall, base_z_abs, course_height_ft, block_height_ft, num_courses=5
    )
    # localiza o grupo de cada fiada fisica (indices 0-based: fiadas 1..5)
    course_to_group = {}
    for group_index, (course_indices, _filtered) in enumerate(groups):
        for ci in course_indices:
            course_to_group[ci] = group_index

    # fiadas 1,2,5 (indices 0,1,4) - abaixo do peitoril ou acima da verga -
    # tem que cair no MESMO grupo (sinal "sem abertura"), diferente do grupo
    # das fiadas 3,4 (indices 2,3), que cruzam o vao.
    solid_group = course_to_group[0]
    assert course_to_group[1] == solid_group
    assert course_to_group[4] == solid_group
    window_group = course_to_group[2]
    assert course_to_group[3] == window_group
    assert window_group != solid_group

    solid_filtered = groups[solid_group][1]
    assert solid_filtered == [[]]  # nenhuma abertura ativa - parede continua
    window_filtered = groups[window_group][1]
    assert window_filtered == [[opening]]  # abertura real preservada intacta


@case
def test_solve_building_blocks_all_courses_colisoes_apontam_para_a_peca_certa():
    """Bug real medido ao vivo via MCP (2026-08-21): `solve_building_blocks_all_courses`
    concatenava `result["candidates"]` de CADA banda em `all_candidates`
    sem realinhar os pares (i, j) de `result["collisions"]`, que sao
    indices RELATIVOS a lista de candidatos DAQUELA banda - apos a
    concatenacao, os pares apontavam para pecas erradas (medido: duas
    pecas reportadas como "colidindo" a 2500cm/270cm de distancia uma da
    outra). Cenario com X_INTERSECTION + 2 bandas (janela numa parede) e
    paredes propositalmente coladas para garantir colisoes reais - todo
    par (i, j) devolvido tem que apontar para DUAS pecas com sobreposicao
    REAL positiva (_obb_min_overlap > 0), nunca negativa/absurda."""
    lines = [seg(0, 0, 800, 0), seg(400, -400, 400, 400), seg(400, 4, 800, 4)]
    walls, junction_map = m.extend_wall_ends_to_junctions(
        [(l, ft(14.0), (False, False)) for l in lines], m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    openings_per_wall = [[(ft(100.0), ft(180.0), ft(50.0), ft(70.0))], [], []]
    result = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), 5
    )
    assert len(result["bands"]) >= 2, "cenario precisa de 2+ bandas para exercitar o bug"
    assert len(result["collisions"]) > 0, "cenario precisa de pelo menos 1 colisao real"
    candidates = result["candidates"]
    for i, j in result["collisions"]:
        a, b = candidates[i], candidates[j]
        overlap = m._obb_min_overlap(m._candidate_obb(a), m._candidate_obb(b))
        assert overlap > 0, (
            "par ({},{}) reportado como colisao mas sem sobreposicao real "
            "(overlap={:.3f}ft) - indices desalinhados entre bandas".format(i, j, overlap)
        )


# --------- SECAO 11.7: RODIZIO DE VARIANTES DE FIADA (bug real: 118/128 ---
# paredes reprovadas na auditoria de amarracao, 2026-08-25) -------------
@case
def test_solve_building_blocks_all_courses_variantes_evitam_alternating_joint_pattern():
    """Regressao do bug real medido em producao (2026-08-25): rodando o
    pipeline inteiro contra um CAD real de 128 paredes, 118 foram
    reprovadas por `audit_wall_bond_quality`/ALTERNATING_JOINT_PATTERN e
    NAO receberam nenhum bloco. Causa-raiz: `solve_building_blocks_all_
    courses` resolvia o preenchimento comum UMA UNICA VEZ por banda
    (par="A"/impar="B") e repetia CEGAMENTE o MESMO layout em 100% das
    fiadas fisicas da mesma paridade - sempre >= o limite de 60% de
    BOND_ALTERNATING_JOINT_RATIO, para qualquer parede com >=1 junta
    interna (praticamente toda parede real).

    Este teste passa `variants_per_course=1` PRIMEIRO (o default
    retrocompativel desta funcao, que preserva o comportamento ANTERIOR a
    esta correcao byte-a-byte) para provar que o cenario abaixo REPRODUZ
    o padrao de verdade (nao e' um caso inventado); so' depois roda a MESMA
    parede com `variants_per_course=PIER_LAYOUT_VARIANTS_PER_COURSE` (o
    que o chamador de producao, `_execute_solve`, agora sempre passa) e
    confere que a geracao de fato varia o suficiente para eliminar a
    repeticao - via `solve_building_blocks_all_courses` de verdade (nao
    `audit_wall_bond_quality` isolada), para exercitar o CAMINHO REAL de
    geracao (secao 11.7 do REGRAS_MODULACAO_BLOCOS.md).

    ATUALIZADO 2026-08-26: `abb46b5` (2026-08-25, commit POSTERIOR a este
    teste no mesmo dia) corrigiu uma causa-raiz DIFERENTE e mais funda -
    ALTERNATING_JOINT_PATTERN e' o proprio funcionamento correto de fiadas
    alternadas (o defeito real, junta coincidindo nas DUAS paridades, ja'
    e' CONTINUOUS_VERTICAL_JOINT) - e parou de somar penalidade/entrar em
    `problems`/bloquear `ok` (`alternating_joints` continua populado, so'
    para diagnostico). Por isso `old_audit["ok"]` e' `True` MESMO sem a
    variacao de layout deste teste - `ok` deixou de ser o sinal certo pra
    provar que o cenario reproduz o padrao. O que ainda prova isso, e
    continua verdadeiro, e' `old_audit["alternating_joints"]` nao-vazio
    (a mesma junta realmente se repete em toda fiada da paridade sem a
    variacao) virando vazio COM a variacao - a auditoria em si (thresholds/
    logica de audit_wall_bond_quality) continua intocada."""
    walls = [(seg(0, 0, 399, 0), ft(14.0), (False, False))]
    walls, junction_map = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    openings_per_wall = [[]]
    num_courses = 15  # pe-direito tipico (~3m com bloco de 19cm+1cm de junta)

    old = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), num_courses,
    )
    assert old["error"] is None
    old_audit = old["wall_bond_audits"][0]
    # NOTA (2026-08-26): `alternating_joints` deixou de derrubar "ok"/
    # "problems" (ver comentario extenso em audit_wall_bond_quality, secao
    # CAUSA-RAIZ) - o sinal de que este cenario REPRODUZ o padrao repetido
    # antigo agora e' a propria lista `alternating_joints` vir no formato
    # "toda fiada par idêntica / toda fiada impar idêntica", nao mais
    # "ok"==False. Ver tambem o `new_audit["alternating_joints"] == []`
    # abaixo, que confere que a variacao extra FAZ a lista ficar vazia.
    assert old_audit["alternating_joints"], old_audit["problems"]

    new = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), num_courses,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
    )
    assert new["error"] is None
    new_audit = new["wall_bond_audits"][0]
    assert new_audit["ok"], new_audit["problems"]
    assert new_audit["alternating_joints"] == [], new_audit["alternating_joints"]
    assert new_audit["continuous_joints"] == [], new_audit["continuous_joints"]

    # controle: a variacao extra nao pode ter deixado NENHUM trecho sem
    # fechar em blocos - regra do usuario, "nenhuma parede pode ser
    # silenciosamente pulada" (ver process_walls_one_by_one/validate_wall_
    # modulation). "non_modular"/"alignment_conflicts" continuam existindo
    # como mecanismo de report, so' nao podem disparar NESTE cenario (uma
    # parede simples, sem vao, de comprimento modular).
    assert all(len(band["result"]["non_modular"]) == 0 for band in new["bands"]), new["bands"]


# ------------------- FEEDBACK DA ETAPA FINAL DO SOLVER (2026-08-27) ------
@case
def test_stage_cb_anuncia_as_etapas_globais_do_solver():
    """A ETAPA FINAL do Solver 18 (colisoes globais, vaos de porta,
    compensadores, auditoria de amarracao) roda DEPOIS da ultima parede,
    quando nenhum callback por parede dispara mais. Ate' 2026-08-27 ela era
    ao mesmo tempo o trecho mais lento do solver e o unico completamente
    mudo - a combinacao que fazia a janela parecer travada em 99% (queixa
    real em producao, planta de 306 eixos). `stage_cb` existe para que essa
    etapa NUNCA mais rode em silencio.

    Confere as quatro etapas, a contagem certa (as duas primeiras sao POR
    BANDA, as duas ultimas rodam uma vez sobre a planta inteira) e - o mais
    importante - que omitir o callback continua funcionando: `stage_cb` e'
    opcional de proposito, todo chamador anterior a esta mudanca (e os
    proprios testes acima) chama sem ele."""
    lines = [seg(0, 0, 600, 0), seg(0, 300, 600, 300), seg(0, 0, 0, 300), seg(600, 0, 600, 300)]
    walls = [(l, ft(14.0), (False, False)) for l in lines]
    walls, junction_map = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    # janela (peitoril 90cm) numa parede: garante MAIS DE UMA banda vertical,
    # sem isso as etapas por banda nao teriam como ser distinguidas das globais.
    openings_per_wall = [[(ft(150.0), ft(300.0), ft(90.0), ft(200.0))], [], [], []]

    seen = []
    result = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), 15,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
        stage_cb=lambda label: seen.append(label),
    )
    bands = len(result["bands"])
    assert bands >= 2, "cenario precisa de 2+ bandas para separar etapa por banda de etapa global"

    per_band = [s for s in seen if "colisoes" in s]
    doors = [s for s in seen if "vaos de porta" in s]
    compensators = [s for s in seen if "compensadores" in s]
    audit = [s for s in seen if "amarracao" in s]
    assert len(per_band) == bands, (len(per_band), bands, seen)
    assert len(doors) == bands, (len(doors), bands, seen)
    assert len(compensators) == 1, seen
    assert len(audit) == 1, seen

    # um stage_cb que EXPLODE nao pode derrubar o solver - a etapa final e'
    # calculo de verdade, feedback de tela nunca pode custar o resultado.
    def _boom(_label):
        raise RuntimeError("callback quebrado")

    survived = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), 15,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE, stage_cb=_boom,
    )
    assert survived["error"] is None
    assert len(survived["candidates"]) == len(result["candidates"])

    # e omitir o callback continua sendo o caminho normal
    without = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings_per_wall, CATALOG, ft(0.0), 15,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
    )
    assert len(without["candidates"]) == len(result["candidates"])


# ------------------- ZONA DE EXCLUSAO: VAO DE PORTA SEM PEITORIL (2026-08-21) ---
@case
def test_is_door_without_sill_so_conta_peitoril_praticamente_no_chao():
    base_z_abs = ft(0.0)
    assert m._is_door_without_sill(ft(0.0), base_z_abs) is True    # porta de verdade
    assert m._is_door_without_sill(ft(0.5), base_z_abs) is True    # ruido de leitura
    assert m._is_door_without_sill(ft(100.0), base_z_abs) is False  # janela (peitoril real)


@case
def test_find_door_void_violations_pega_bloco_dentro_do_vao_mas_nao_fora():
    """Regra absoluta do usuario (2026-08-21): nenhum bloco pode invadir o
    vao de uma porta sem peitoril. Um candidato cujo OBB cai DENTRO do vao
    (100-180cm) tem que ser reportado; um fora (em 250cm) nao."""
    walls_to_create = [(seg(0, 0, 500, 0), ft(14.0), (False, False))]
    door = (ft(100.0), ft(180.0), ft(0.0), ft(210.0))  # sill=0 -> porta sem peitoril
    openings_per_wall = [[door]]
    base_z_abs = ft(0.0)

    def _candidate(x_cm):
        return {
            "wall_idx": 0, "origin_world": XYZ(ft(x_cm), 0.0, 0.0),
            "x_dir": XYZ(1.0, 0.0, 0.0), "y_dir": XYZ(0.0, 1.0, 0.0),
            "length_cm": 39.0, "width_cm": 14.0, "course": "A", "logical_code": "B39",
        }

    inside = _candidate(140.0)   # bem no meio do vao (100-180cm)
    outside = _candidate(250.0)  # fora do vao, mais adiante na parede

    violations = m.find_door_void_violations([inside, outside], walls_to_create, openings_per_wall, base_z_abs)
    assert len(violations) == 1, violations
    assert violations[0]["candidate"] is inside
    assert violations[0]["wall_idx"] == 0
    assert violations[0]["overlap_cm"] > 0

    # a MESMA abertura, mas com peitoril real (janela) - fora do escopo
    # desta regra, mesmo com um candidato no mesmo lugar "dentro" do vao.
    window = (ft(100.0), ft(180.0), ft(100.0), ft(210.0))
    no_violations = m.find_door_void_violations([inside], walls_to_create, [[window]], base_z_abs)
    assert no_violations == []


@case
def test_axis_corner_end_sides_so_reconhece_encontro_l_t_x():
    nodes = [{"kind": "L_CORNER"}, {"kind": "FREE_END"}, {"kind": "STRAIGHT_CONTINUATION"}]
    end_to_node = {(0, 0): 0, (0, 1): 1, (7, 0): 2}
    assert m._axis_corner_end_sides(0, end_to_node, nodes) == [0]
    assert m._axis_corner_end_sides(7, end_to_node, nodes) == []
    # sem grafo (None) - nunca lanca excecao, devolve vazio
    assert m._axis_corner_end_sides(0, None, None) == []


@case
def test_plano_de_ajuste_prioriza_boneca_quando_ponta_encosta_em_encontro():
    """Fim-a-fim via plan_axis_opening_fix: pilaretes 15/20 (nenhum multiplo
    de 5) com a ponta 0 classificada como L_CORNER no grafo. Um `verify`
    fajuto que SO' aceita tier=="boneca" prova que a OPCAO 0 e' tentada e
    funciona antes de qualquer alternativa - se o codigo caisse direto na
    OPCAO 1 (shift geral), o plano devolvido teria tier=="shift" e o verify
    o rejeitaria, fazendo o teste falhar com feasible=False."""
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _infill = (
        _one_opening_axis_fixture(15.0, 80.0, 20.0)
    )
    wall_end_to_node = {(0, 0): 0}
    wall_graph_nodes = [{"kind": "L_CORNER"}]

    def _verify(plan):
        return plan.get("tier") == "boneca"

    plan = m.plan_axis_opening_fix(
        fake_doc, 0, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings,
        wall_end_to_node=wall_end_to_node, wall_graph_nodes=wall_graph_nodes, verify=_verify
    )
    assert plan["feasible"] is True, plan.get("reason")
    assert plan["tier"] == "boneca"
    # comprimento do eixo inteiro intocado (regra #1 - nada foi "aumentado")
    assert abs(plan["length_delta_cm"]) < 1e-9
    piers_cm = sorted(to_cm(p["t_b_new"] - p["t_a_new"]) for p in plan["new_piers"])
    assert abs(piers_cm[0] - 16.0) < 0.01 and abs(piers_cm[1] - 19.0) < 0.01, piers_cm
    new_op = plan["new_openings"][0]
    # largura da abertura preservada, so' a POSICAO desloca +1cm (mesmo
    # sentido do crescimento da boneca na ponta 0)
    assert abs(to_cm(new_op["t_hi_new"] - new_op["t_lo_new"]) - 80.0) < 0.01
    assert abs(to_cm(new_op["shift_ft"]) - 1.0) < 0.01


@case
def test_pipeline_lanca_blocos_e_ajusta_na_mesma_passada():
    """Regra #3: o ajuste so' e' aceito porque o RE-LANCAMENTO dos blocos
    comprovou que fechou - e o ajuste escolhido ENCURTA a parede, nunca a
    aumenta (regra #1)."""
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    walls_to_create, junction_map = m.extend_wall_ends_to_junctions(
        walls_to_create, m.JUNCTION_FACE_SEARCH_FT
    )
    nodes, end_to_node = m.build_wall_graph(walls_to_create, junction_map)
    antes = [list(row) for row in openings_per_wall]

    rows = m.analyze_created_walls_for_errors(
        fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings,
        nodes, end_to_node, CATALOG, [], [], []
    )
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["auto_fixable"] is True, row["problem_text"]
    plan = row["fix_plan"]
    assert plan["tier"] == "trim"
    assert plan["length_delta_cm"] <= 1e-9, "o ajuste NAO pode aumentar a parede"
    assert plan["axis_start_t_ft"] >= -1e-9
    assert plan["axis_end_t_ft"] <= walls_to_create[0][0].Length + 1e-9

    # a analise NAO pode ter mexido no estado do chamador (que espelha o
    # modelo Revit) - quem aplica de verdade e' o passo "Ajustar Erros"
    assert [list(r) for r in openings_per_wall] == antes


@case
def test_pipeline_processa_na_ordem_e_valida_cada_parede():
    lines = [seg(0, 0, 400, 0), seg(0, 0, 0, 300), seg(400, 0, 400, 300)]
    result, _nodes, walls = solve_layout(lines)
    assert result["order"] == m.order_walls_for_processing(walls)
    assert [entry["wall_idx"] for entry in result["per_wall"]] == result["order"]
    for entry in result["per_wall"]:
        checks = entry["validation"]["checks"]
        # a parede pode nao fechar em blocos (geometria de teste arbitraria),
        # mas NUNCA pode ter crescido nem ganhado dente
        assert checks["sem_aumento"], entry
        assert checks["sem_dentes"], entry


@case
def test_sem_catalogo_a_analise_nao_inventa_uma_regra():
    """Sem catalogo o solver nao roda - e como nao existe mais nenhuma regra
    de digito para usar no lugar, a analise tem que DIZER isso em vez de
    devolver um veredito qualquer."""
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _infill = (
        _one_opening_axis_fixture(162.0, 80.0, 158.0)
    )
    nodes, end_to_node = m.build_wall_graph(walls_to_create, {})
    rows = m.analyze_created_walls_for_errors(
        fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings,
        nodes, end_to_node, {}, ["B39"], [], []
    )
    assert len(rows) == 1
    assert rows[0]["wall_idx"] is None
    assert rows[0]["auto_fixable"] is False
    assert "catalogo" in rows[0]["problem_text"]


@case
def test_aplicacao_recusa_plano_que_aumentaria_a_parede():
    """Ultima barreira: mesmo um plano invalido chegando em
    apply_axis_opening_fix nao pode tocar no modelo."""
    fake_doc, walls_to_create, openings_per_wall, created_walls_by_axis, all_openings, _infill = (
        _one_opening_axis_fixture(160.0, 80.0, 160.0)
    )
    axis_len_ft = walls_to_create[0][0].Length
    plano_ruim = {
        "feasible": True, "already_ok": False, "wall_idx": 0, "tier": "trim",
        "axis_start_t_ft": 0.0, "axis_end_t_ft": axis_len_ft + ft(3.0),
        "new_openings": [], "new_piers": [],
    }
    applied, failures = m.apply_axis_opening_fix(fake_doc, plano_ruim, walls_to_create)
    assert applied == 0
    assert failures and "aumentaria a parede" in failures[0]


# --------------------------------------------------------------- janelas
@case
def test_janela_de_configuracao_monta_e_valida():
    lines_by_layer = {
        "PAREDES": [seg(0, 0, 400, 0), seg(0, 14, 400, 14)],
        "COTAS": [seg(0, 100, 50, 100)],
    }
    form = m._SetupForm(lines_by_layer, ["Nivel 1", "Nivel 2"], {})
    # o Layer com mais linhas vem primeiro e ja' nasce selecionado
    assert form._layer_grid.Items[0].Text == "PAREDES"
    assert form._selected_layer == "PAREDES"
    # a espessura medida no desenho aparece como opcao
    assert form._thickness_values_cm == [14.0], form._thickness_values_cm
    # sem espessura marcada, Executar fica desabilitado e o rodape diz o porque
    assert form._run_button.Enabled is False
    assert "espessura" in form._status.Text
    form._thickness_list.SetItemChecked(0, True)
    assert form._validate() is True
    assert form._run_button.Enabled is True
    form._on_run(None, None)
    assert form.result["layer"] == "PAREDES"
    assert form.result["thicknesses_cm"] == [14.0]
    assert form.result["level"] == "Nivel 1"
    assert abs(form.result["height_m"] - 2.80) < 1e-9
    assert form.result["openings_mode"] == "pick"


@case
def test_janela_de_configuracao_recusa_altura_invalida():
    form = m._SetupForm({"PAREDES": [seg(0, 0, 400, 0), seg(0, 14, 400, 14)]}, ["Nivel 1"], {})
    form._thickness_list.SetItemChecked(0, True)
    form._height_box.Text = "zero"
    assert form._validate() is False
    assert form._run_button.Enabled is False
    form._on_run(None, None)
    assert form.result is None


@case
def test_janela_de_configuracao_aceita_espessura_digitada():
    form = m._SetupForm({"PAREDES": [seg(0, 0, 400, 0)]}, ["Nivel 1"], {})
    form._extra_box.Text = "15;20,5"
    chosen, error = form._checked_thicknesses_cm()
    assert error is None and chosen == [15.0, 20.5], (chosen, error)
    form._extra_box.Text = "15;abc"
    chosen, error = form._checked_thicknesses_cm()
    assert chosen is None and "invalida" in error


@case
def test_janela_de_configuracao_lembra_a_execucao_anterior():
    defaults = {"layer": "COTAS", "thicknesses_cm": [14.0], "level": "Nivel 2",
                "height_m": 3.1, "openings_mode": "auto"}
    lines_by_layer = {
        "PAREDES": [seg(0, 0, 400, 0), seg(0, 14, 400, 14)],
        "COTAS": [seg(0, 100, 50, 100), seg(0, 114, 50, 114)],
    }
    form = m._SetupForm(lines_by_layer, ["Nivel 1", "Nivel 2"], defaults)
    assert form._selected_layer == "COTAS"
    assert form._level_combo.SelectedItem == "Nivel 2"
    assert form._height_box.Text == "3.1"
    assert form._openings_auto.Checked is True


def _make_post_creation_handler(error_rows=None, catalog=None, catalog_missing=None):
    handler = m._PostCreationEventHandler()
    handler.error_rows = error_rows or []
    # vazio (nao "faltando") por padrao - so' precisa bater com
    # _apply_catalog_status, que so' itera as entradas se catalog nao for
    # vazio; testes que precisam de tipos de verdade passam `catalog=`.
    handler.catalog = catalog if catalog is not None else {}
    handler.catalog_missing = catalog_missing or []
    return handler


@case
def test_janela_de_resultado_monta_a_tela_unica_sem_abas():
    # pedido explicito do usuario: nada de abas, tudo numa tela so'.
    report = {
        "title": "Automacao concluida - 12 parede(s) criada(s)",
        "subtitle": "Layer 'PAREDES'",
        "kpis": [("Paredes criadas", 12, m.UI_ACCENT), ("A conferir", 2, m.UI_WARN)],
        "highlights": ["PAREDES", "  12 eixos"],
        "issues": [("erro", "Falha", "algo falhou"), ("atencao", "Conferir", "algo suspeito")],
        "log": "linha 1\nlinha 2",
        "log_path": "C:/temp/log.txt",
    }
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 0, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
        {"wall_idx": 3, "wall_ids": [revit_stubs.ElementId(2)],
         "problem_text": "largura de abertura fora da modulacao", "auto_fixable": False, "fix_plan": None},
    ])
    form = m._PostCreationForm(report, None, handler, [revit_stubs.ElementId(1), revit_stubs.ElementId(2)])
    tabs = [c for c in form.descendants() if isinstance(c, revit_stubs.TabControl)]
    assert tabs == [], tabs
    grids = [c for c in form.descendants() if isinstance(c, revit_stubs.ListView)]
    assert len(grids) == 1
    assert grids[0].Items.Count == 2
    for row in grids[0].Items:
        assert len(row.SubItems) == len(grids[0].Columns), len(row.SubItems)
    # log inicial ja' traz resumo/ocorrencias - nao existe mais aba separada
    assert "PAREDES" in form._log_box.Text
    assert "algo falhou" in form._log_box.Text
    # 1 dos 2 erros e' auto-corrigivel -> botao "Ajustar Erros" habilitado
    assert form._fix_button.Enabled is True


@case
def test_janela_de_resultado_sem_erros_libera_lancar_blocos_direto():
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler = _make_post_creation_handler(error_rows=[])
    form = m._PostCreationForm(report, None, handler, [])
    assert form._fix_button.Enabled is False
    # sem erro nenhum para ajustar, "Lancar Blocos" ja' libera sozinho - nao
    # faz sentido obrigar um clique em "Ajustar Erros" sem nada a fazer.
    assert form._solve_button.Enabled is True
    assert "nenhum eixo fora da modulacao" in form._errors_status.Text.lower()


@case
def test_ajustar_erros_sem_canal_mostra_aviso():
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 0, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
    ])
    form = m._PostCreationForm(report, None, handler, [revit_stubs.ElementId(1)])
    form._on_fix_click(None, None)
    assert "indisponivel" in form._errors_status.Text


@case
def test_clicar_linha_de_erro_prepara_o_zoom():
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    wall_ids = [revit_stubs.ElementId(5), revit_stubs.ElementId(6)]
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 7, "wall_ids": wall_ids,
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
    ])
    external_event = revit_stubs._Inert()
    form = m._PostCreationForm(report, external_event, handler, wall_ids)
    form._errors_grid.Items[0].Selected = True
    form._on_error_row_selected(None, None)
    assert handler.pending_zoom_ids == wall_ids
    assert handler.on_done == form._on_zoom_done

    # duplo-clique na MESMA linha ja' selecionada precisa continuar
    # disparando o zoom, mesmo sem o indice selecionado mudar (SelectedIndexChanged
    # so' dispara quando o indice MUDA - ver comentario no wiring do DoubleClick).
    handler.pending_zoom_ids = []
    form._errors_grid.DoubleClick.fire(None, None)
    assert handler.pending_zoom_ids == wall_ids


@case
def test_execute_repara_globais_stale_antes_de_ajustar_erros():
    """Regressao do crash relatado ao vivo: 'IronPython.Runtime.
    UnboundNameException: name 'SubTransaction' is not defined' dentro de
    fix_all_wall_modulation_errors, ao clicar 'Ajustar Erros' numa janela
    que ficou aberta entre reexecucoes do Script.py (o dicionario de
    globais do modulo perde nomes - mesma causa raiz ja' documentada para
    os updaters ao vivo, ver _LiveUpdaterBase).

    Simula a divergencia dando ao handler um `self._g` DIFERENTE do
    `m.__dict__` atual (que teve SubTransaction removido, como aconteceria
    numa reexecucao real que deixasse esse nome de fora desta janela).
    `Execute()` precisa reinjetar esse snapshot em `globals()` ANTES de
    chamar fix_all_wall_modulation_errors, senao a busca de nome bare
    dentro dela (SubTransaction, _invalidate_opening_gap_cache, ...)
    quebra."""
    handler = m._PostCreationEventHandler()
    handler.walls_to_create = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    handler.openings_per_wall = []
    handler.error_rows = [{
        "wall_idx": 0, "wall_ids": [], "problem_text": "x",
        "auto_fixable": True, "fix_plan": {
            "feasible": True, "already_ok": False, "wall_idx": 0,
            "new_piers": [], "new_openings": [], "max_shift_cm": 0.0,
        },
    }]

    # snapshot BOM, capturado enquanto SubTransaction ainda existia no modulo.
    handler._g = dict(m.__dict__)

    # simula a divergencia: o dicionario de globais "atual" do modulo
    # perdeu SubTransaction.
    saved = m.__dict__.pop("SubTransaction")
    try:
        events = []
        handler.on_done = lambda kind, err: events.append((kind, err))
        handler.action = "fix_errors"

        fake_uidoc = revit_stubs._Inert()
        fake_uidoc.Document = revit_stubs._Inert()
        fake_uiapp = revit_stubs._Inert()
        fake_uiapp.ActiveUIDocument = fake_uidoc

        handler.Execute(fake_uiapp)

        assert events, "on_done nunca foi chamado"
        kind, err = events[0]
        assert kind == "fix_errors" and err is None, (kind, err)
    finally:
        m.__dict__["SubTransaction"] = saved


@case
def test_snapshot_de_globais_e_copia_e_nao_o_dicionario_vivo():
    """Regressao do erro "Falha ao disparar a correcao: SubTransaction"
    (relatado ao vivo DEPOIS da correcao coberta pelo teste acima).

    Aquele teste monta a divergencia a mao (`handler._g = dict(m.__dict__)`),
    entao ele passava mesmo com o codigo real guardando a REFERENCIA viva do
    dicionario do modulo. Nesse caso `self._g` perde os nomes JUNTO com o
    modulo, `.update(self._g)` vira no-op e `g["SubTransaction"]` levanta
    KeyError - cujo str() e' so' 'SubTransaction', exatamente a mensagem que
    o usuario viu. Aqui o handler e' construido NORMALMENTE, sem tocar em
    `_g`."""
    handler = m._PostCreationEventHandler()
    assert handler._g is not m.__dict__, (
        "o snapshot precisa ser uma COPIA - guardar o dicionario vivo do "
        "modulo nao protege de nada"
    )
    updater = m._LiveUpdaterBase("addin-id-falso", "guid-falso")
    assert updater._g is not m.__dict__, (
        "mesmo motivo do handler: _LiveUpdaterBase tambem precisa copiar"
    )

    handler.walls_to_create = [(seg(0, 0, 400, 0), ft(14.0), (False, False))]
    handler.openings_per_wall = []
    handler.error_rows = [{
        "wall_idx": 0, "wall_ids": [], "problem_text": "x",
        "auto_fixable": True, "fix_plan": {
            "feasible": True, "already_ok": False, "wall_idx": 0,
            "new_piers": [], "new_openings": [], "max_shift_cm": 0.0,
        },
    }]

    saved = m.__dict__.pop("SubTransaction")
    try:
        events = []
        handler.on_done = lambda kind, err: events.append((kind, err))
        handler.action = "fix_errors"

        fake_uidoc = revit_stubs._Inert()
        fake_uidoc.Document = revit_stubs._Inert()
        fake_uiapp = revit_stubs._Inert()
        fake_uiapp.ActiveUIDocument = fake_uidoc

        handler.Execute(fake_uiapp)

        assert events, "on_done nunca foi chamado"
        kind, err = events[0]
        assert kind == "fix_errors" and err is None, (kind, err)
    finally:
        m.__dict__["SubTransaction"] = saved


@case
def test_execute_create_apaga_lote_anterior_antes_de_recriar():
    """Bug real corrigido (2026-08-25, reportado pelo usuario com imagem):
    clicar 'Lancar Blocos - criar' mais de uma vez na MESMA janela (ex.:
    recalcular apos 'Ajustar Erros' mudar uma abertura, e criar de novo)
    empilhava um SEGUNDO lote de instancias por cima do primeiro -
    create_building_blocks nunca apaga nada, so' cria (ver seu proprio
    docstring). Como as pecas de encontro L/T/X nao mudam de posicao entre
    dois calculos (o no' e' o mesmo ponto fisico), elas ficavam
    PERFEITAMENTE sobrepostas (invisiveis) enquanto o preenchimento comum
    (que SIM muda quando uma abertura se deslocou) sobrava DUPLICADO nas
    duas posicoes ao mesmo tempo - metade da parede parecia ter "andado",
    a outra metade parecia ter "ficado parada". `_execute_create` agora
    apaga o lote anterior POR COMPLETO antes de criar o novo - cada
    clique em "criar" e' uma SUBSTITUICAO atomica, nunca uma soma."""
    handler = m._PostCreationEventHandler()
    old_id_1, old_id_2 = revit_stubs.ElementId(101), revit_stubs.ElementId(102)
    handler.create_result = {
        "created_count": 2, "failures": [], "created_instances": [
            {"id": old_id_1, "logical_code": "B39", "course": "A", "course_index": 0},
            {"id": old_id_2, "logical_code": "B39", "course": "B", "course_index": 1},
        ],
    }
    # solve_result com 0 fiadas -> _execute_create toma o atalho de "numero
    # de fiadas invalido" e NUNCA chama create_building_blocks de verdade -
    # isola o teste na logica de limpeza do lote anterior, sem precisar
    # simular FamilySymbol/NewFamilyInstance do Revit.
    handler.solve_result = {"candidates": [], "course_candidates": {}, "num_courses": 0, "error": None}

    deleted_ids = []
    existing_ids = set([old_id_1, old_id_2])

    class _FakeDeletableDoc(object):
        def GetElement(self, element_id):
            return object() if element_id in existing_ids else None

        def Delete(self, element_id):
            deleted_ids.append(element_id)
            existing_ids.discard(element_id)

    events = []
    handler.on_done = lambda kind, err: events.append((kind, err))
    handler.action = "create"
    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = _FakeDeletableDoc()
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert events and events[0] == ("create", None), events
    assert set(deleted_ids) == set([old_id_1, old_id_2]), deleted_ids
    # create_result foi substituido pelo resultado (vazio) da nova rodada -
    # nunca continua apontando para instancias ja' apagadas do modelo.
    assert handler.create_result["created_instances"] == []

    # Uma SEGUNDA chamada (ex.: terceiro clique em "criar") so' tenta
    # apagar o que o create_result ATUAL realmente tem - aqui, nada -
    # entao nao tenta apagar de novo os ids ja' removidos.
    deleted_count_before = len(deleted_ids)
    handler.action = "create"
    handler.Execute(fake_uiapp)
    assert len(deleted_ids) == deleted_count_before, deleted_ids


@case
def test_execute_create_cria_paredes_reprovadas_na_auditoria_de_amarracao_e_marca_vermelho():
    """Regra REVISTA 2026-08-26 (pedido explicito do usuario: "o
    diagnostico nao pode impedir a geracao dos blocos" - reverte a regra
    #1 absoluta de 2026-08-25): uma parede reprovada na auditoria de
    amarracao entre fiadas (audit_all_walls_bond_quality/ETAPA 4C) RECEBE
    bloco normalmente, igual a qualquer outra - nenhum candidato e'
    excluido de create_building_blocks. As pecas criadas para ela ficam
    marcadas em VERMELHO na vista para revisao manual (mesmo mecanismo
    ja' usado para colisao entre pecas)."""
    handler = m._PostCreationEventHandler()
    handler.created_walls_by_axis = {
        0: [(revit_stubs.ElementId(1), "cad")],
        1: [(revit_stubs.ElementId(2), "cad")],
    }
    handler.solve_result = {
        "candidates": [
            {"wall_idx": 0, "logical_code": "B39", "course": "A"},
            {"wall_idx": 1, "logical_code": "B39", "course": "A"},
        ],
        "course_candidates": {
            0: [{"wall_idx": 0, "logical_code": "B39", "course": "A"}],
            1: [{"wall_idx": 1, "logical_code": "B39", "course": "A"}],
        },
        "num_courses": 2,
        "collisions": [],
        "wall_bond_audits": {
            0: {"ok": False, "problems": ["CONTINUOUS_VERTICAL_JOINT: junta corrida em X~10.0cm"],
                "penalty": 50000.0},
            1: {"ok": True, "problems": [], "penalty": 0.0},
        },
    }

    captured = {}

    def _fake_create_building_blocks(app_doc, candidates, catalog, base_z_abs, level, num_courses,
                                      course_candidates=None):
        captured["candidates"] = candidates
        captured["course_candidates"] = course_candidates
        created = [
            {"id": revit_stubs.ElementId(100 + i), "logical_code": c["logical_code"],
             "course": c["course"], "course_index": 0, "candidate_key": id(c)}
            for i, c in enumerate(candidates)
        ]
        return {"created_count": len(candidates), "failures": [], "created_instances": created}
    handler._create_building_blocks = _fake_create_building_blocks

    highlighted = []
    handler._apply_solid_color_override = lambda view, ids, color, target_doc=None: highlighted.extend(ids)

    events = []
    handler.on_done = lambda kind, err: events.append((kind, err))
    handler.action = "create"
    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = revit_stubs._Inert()
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert events and events[0] == ("create", None), events
    # AMBAS as paredes (reprovada e aprovada) chegam a create_building_blocks -
    # nenhum candidato e' excluido por causa da auditoria de amarracao.
    assert {c["wall_idx"] for c in captured["candidates"]} == {0, 1}, captured["candidates"]
    assert captured["course_candidates"][0] and captured["course_candidates"][1]
    assert handler.create_result["skipped_wall_count"] == 0
    assert handler.create_result["skipped_wall_idxs"] == []
    assert handler.create_result["reproved_wall_count"] == 1
    assert handler.create_result["reproved_wall_idxs"] == [0]
    # a PECA criada para a parede reprovada (Id 100, primeiro candidato,
    # wall_idx 0) e' marcada em vermelho - a peca em si, ja' que ela FOI
    # criada (nao mais a parede de referencia vazia).
    assert revit_stubs.ElementId(100) in highlighted, highlighted
    assert revit_stubs.ElementId(101) not in highlighted, highlighted
    assert revit_stubs.ElementId(2) not in highlighted, highlighted


@case
def test_execute_delete_preserva_parede_de_referencia_sem_bloco():
    """Regra #4 (pedido explicito do usuario): uma parede reprovada na
    auditoria de amarracao (regra #1, ver teste acima) fica sem bloco
    nenhum de proposito - "Finalizar - Excluir paredes de referencia"
    NUNCA pode apagar a parede de referencia DESSE eixo tambem, senao o
    vao fica completamente vazio (nem parede, nem bloco) - exatamente o
    "parede some sem explicacao" que a regra #4 probe. So' a parede de
    referencia de um eixo QUE RECEBEU bloco pode ser excluida."""
    handler = m._PostCreationEventHandler()
    wall_ref_0 = revit_stubs.ElementId(1)   # eixo 0: reprovado, sem bloco - PRESERVAR
    wall_ref_1 = revit_stubs.ElementId(2)   # eixo 1: aprovado, com bloco - pode excluir
    handler.created_walls_by_axis = {0: [(wall_ref_0, "cad")], 1: [(wall_ref_1, "cad")]}
    handler.created_wall_ids_all = [wall_ref_0, wall_ref_1]
    handler.create_result = {"skipped_wall_idxs": [0]}

    existing_ids = {wall_ref_0, wall_ref_1}
    deleted_ids = []

    class _FakeDoc(object):
        def GetElement(self, element_id):
            return object() if element_id in existing_ids else None

        def Delete(self, element_id):
            deleted_ids.append(element_id)
            existing_ids.discard(element_id)

    events = []
    handler.on_done = lambda kind, err: events.append((kind, err))
    handler.action = "delete"
    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = _FakeDoc()
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert events and events[0] == ("delete", None), events
    assert deleted_ids == [wall_ref_1], deleted_ids
    assert wall_ref_0 in existing_ids, "a parede de referencia sem bloco tem que sobreviver"
    assert handler.create_result["deleted_wall_count"] == 1
    assert handler.create_result["kept_wall_count_no_blocks"] == 1


@case
def test_pilarete_junto_de_abertura_nao_segue_mais_regra_de_digito():
    """Pedido explicito do usuario (2026-08-21): remover a regra 'terminar
    em 0 ou 5' dos pilaretes junto de abertura - eles devem sempre voltar
    compatible=True de evaluate_wall_modulation (so' o solver de blocos real,
    Etapa 3B, decide se precisam de ajuste)."""
    # pilarete de 124cm: 124 % 10 == 4, INVALIDO tanto pela regra geral das
    # paredes (0,1,6,9) quanto pela antiga regra do pilarete (0,5) - o valor
    # foi escolhido de proposito para nao passar por coincidencia.
    wall = _FakeWall(seg(0, 0, 124, 0))
    fake_doc = _FakeDoc({901: wall})
    # abertura logo apos a ponta da parede -> ela vira PILARETE (ver
    # _wall_is_pier_at_opening: centro do vao FORA do segmento, encostado
    # na ponta).
    opening_gaps = [(XYZ(ft(154.0), 0.0, 0.0), ft(30.0))]

    results = m.evaluate_wall_modulation([901], fake_doc, opening_gaps)
    assert len(results) == 1
    assert results[0]["pier_at_opening"] is True
    assert results[0]["compatible"] is True, results[0]


@case
def test_execute_erro_sem_mensagem_nao_vira_sucesso_silencioso():
    """Regra do usuario: nunca usar so' `if command.error:` para detectar
    falha de um ExternalEvent - uma excecao levantada SEM mensagem (ex.:
    `raise Exception()`) tem `str(ex) == ""`, uma string vazia (falsy em
    Python). Execute() precisa (a) nunca repassar essa string vazia como
    'error' adiante (troca por repr(ex) - ver comentario no except de
    Execute) e (b) os `_on_*_done` de _PostCreationForm precisam checar
    `kind == "error"`, nunca `if error:` - senao uma falha REAL sem
    mensagem passaria despercebida como sucesso."""
    handler = m._PostCreationEventHandler()

    def _boom(app_doc):
        raise Exception()  # de proposito: sem nenhuma mensagem

    handler._execute_zoom = _boom
    handler.action = "zoom"
    events = []
    handler.on_done = lambda kind, err: events.append((kind, err))

    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = revit_stubs._Inert()
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    # _execute_zoom normal recebe so' app_uidoc, nao app_doc - o stub acima
    # aceita qualquer coisa (so' precisa do nome do parametro pra bater com
    # a chamada de dentro de Execute: `self._execute_zoom(app_uidoc)`).
    handler.Execute(fake_uiapp)

    assert events, "on_done nunca foi chamado"
    kind, err = events[0]
    assert kind == "error", (kind, err)
    # NUNCA vazio - repr(Exception()) == "Exception()", sempre verdadeiro.
    assert err, "mensagem de erro nao pode ficar vazia mesmo sem str(ex)"

    # e o consumo do lado da janela (_PostCreationForm._on_zoom_done) tem
    # que reconhecer esta falha mesmo com `err` no formato repr() em vez de
    # uma frase - o que importa e' `kind`, nunca o CONTEUDO de `err`.
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler2 = _make_post_creation_handler()
    form = m._PostCreationForm(report, revit_stubs._Inert(), handler2, [])
    form._on_zoom_done(kind, err)
    assert "Falha ao dar zoom" in form._errors_status.Text
    assert err in form._errors_status.Text


# ------------------- ETAPA 1 / ETAPA 2 SEPARADAS (2026-08-26) -------------
# Regra do usuario: criar as Walls e lancar os blocos sao operacoes
# DIFERENTES - terminar a criacao das Walls nunca pode, sozinho, comecar a
# modulacao. Os testes abaixo cobrem, isoladamente (sem depender de main()
# inteira, que precisa de um Document/CAD real), as pecas que implementam
# essa separacao: a acao "analyze" de _PostCreationEventHandler (so' roda
# analyze_created_walls_for_errors quando o Revit processa o ExternalEvent -
# ver _execute_analyze) e _WallReviewForm (so' dispara esse evento quando
# "Iniciar Modulacao" e' clicado - nunca sozinha, so' por existir).
#
# NOTA (2026-08-26, apos o primeiro teste ao vivo em producao): a primeira
# versao desta separacao usava uma classe SEPARADA (_StartModulationEvent
# Handler) so' para a acao "analyze". Isso quebrou em producao com
# "TypeError: interface takes exactly one argument" ao instanciar essa
# classe (engine CPython/pyRevitLabs.PythonNet nao parece suportar bem DUAS
# classes Python distintas implementando a MESMA interface .NET, IExternal
# EventHandler, no mesmo modulo exec()'d) - corrigido incorporando "analyze"
# em _PostCreationEventHandler (a UNICA classe que implementa a interface
# neste modulo). Os testes abaixo cobrem o comportamento ATUAL.
@case
def test_execute_analyze_roda_analyze_created_walls_for_errors_e_guarda_em_error_rows():
    """_PostCreationEventHandler._execute_analyze (acao "analyze") precisa
    rodar analyze_created_walls_for_errors de verdade (leitura pura -
    nenhuma Transaction, ver docstring dela), guardar o resultado em
    self.error_rows e reportar ("analyze", None) - e' o UNICO ponto onde a
    Etapa 2 comeca a fazer alguma coisa."""
    walls = [(seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM + 7.0), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[]]

    handler = m._PostCreationEventHandler()
    handler.walls_to_create = walls_ext
    handler.openings_per_wall = openings_per_wall
    handler.created_walls_by_axis = {}
    handler.all_openings = []
    handler.wall_graph_nodes = nodes
    handler.wall_end_to_node = end_to_node
    handler.catalog = CATALOG
    handler.catalog_missing = []
    handler.modulation_results = []
    handler.opening_incompatible_modulation = []
    handler.action = "analyze"

    events = []
    handler.on_done = lambda kind, error: events.append((kind, error))

    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = None
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert events, "on_done nunca foi chamado"
    kind, error = events[0]
    assert kind == "analyze" and error is None, (kind, error)
    assert isinstance(handler.error_rows, list)
    assert len(handler.error_rows) == 1, "a fixture tem 1 parede fora da modulacao (V curto demais)"
    # sem abertura no eixo (2026-08-26: ETAPA 3C/deslocamento de parede
    # conectada foi removida) - nenhuma correcao automatica disponivel,
    # fica marcada para revisao manual (azul).
    assert handler.error_rows[0]["auto_fixable"] is False


@case
def test_execute_analyze_com_ui_invoke_cb_roda_em_thread_e_marshala_o_resultado():
    """MUDANCA 2 do plano de arquitetura em memoria (2026-08-26): com
    ui_invoke_cb configurado (como _WallReviewForm._on_start_click faz de
    verdade), _execute_analyze despacha analyze_created_walls_for_errors
    numa System.Threading.Thread (aqui, o stub de tests/revit_stubs.py -
    roda o callback sincrono; concorrencia real so' e' verificavel ao vivo
    no Revit) em vez de rodar direto dentro de Execute(), e SO' chama
    on_done atraves de ui_invoke_cb - provando que o resultado final chega
    identico ao caminho sincrono antigo (ver o teste logo acima), so' que
    marshalado."""
    walls = [(seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM + 7.0), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[]]

    handler = m._PostCreationEventHandler()
    handler.walls_to_create = walls_ext
    handler.openings_per_wall = openings_per_wall
    handler.created_walls_by_axis = {}
    handler.wall_segment_geometry = {}
    handler.all_openings = []
    handler.wall_graph_nodes = nodes
    handler.wall_end_to_node = end_to_node
    handler.catalog = CATALOG
    handler.catalog_missing = []
    handler.modulation_results = []
    handler.opening_incompatible_modulation = []
    handler.action = "analyze"

    invoke_calls = []

    def _ui_invoke(fn):
        invoke_calls.append(fn)
        fn()

    handler.ui_invoke_cb = _ui_invoke

    events = []
    handler.on_done = lambda kind, error: events.append((kind, error))

    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = None
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert invoke_calls, "ui_invoke_cb nunca foi chamado - on_done nao foi marshalado para a UI"
    assert events, "on_done nunca foi chamado"
    kind, error = events[0]
    assert kind == "analyze" and error is None, (kind, error)
    assert isinstance(handler.error_rows, list)
    assert len(handler.error_rows) == 1
    # sem abertura no eixo (2026-08-26: ETAPA 3C removida) - manual.
    assert handler.error_rows[0]["auto_fixable"] is False


@case
def test_execute_analyze_erro_sem_mensagem_nunca_fica_vazio():
    """Mesma regra do usuario ja coberta para as outras acoes (ver
    test_execute_erro_sem_mensagem_nao_vira_sucesso_silencioso):
    kind=="error" e' o sinal real de falha, e a mensagem nunca pode ficar
    vazia so' porque a excecao original nao tinha nenhuma."""
    handler = m._PostCreationEventHandler()
    handler.action = "analyze"

    def _boom(*args, **kwargs):
        raise Exception()

    handler._analyze_created_walls_for_errors = _boom
    events = []
    handler.on_done = lambda kind, error: events.append((kind, error))
    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Document = None
    fake_uiapp = revit_stubs._Inert()
    fake_uiapp.ActiveUIDocument = fake_uidoc

    handler.Execute(fake_uiapp)

    assert events, "on_done nunca foi chamado"
    kind, error = events[0]
    assert kind == "error", (kind, error)
    assert error, "mensagem de erro nao pode ficar vazia"


@case
def test_wall_review_form_so_dispara_modulacao_apos_clique_no_botao():
    """REGRA PRINCIPAL do usuario: so' construir _WallReviewForm (o que
    acontece assim que a Etapa 1 - criacao das Walls - termina) NUNCA pode
    disparar a modulacao sozinho. So' o clique em 'Iniciar Modulacao' (via
    _on_start_click) prepara (action="analyze") e dispara o ExternalEvent;
    e o callback de sucesso (on_start_modulation, quem monta/abre a janela
    de resultado de verdade da Etapa 2) so' roda quando
    _on_analyze_done("analyze", None) chega - nunca antes, nunca sozinho."""

    class _FakeHandler(object):
        def __init__(self):
            self.on_done = None
            self.action = None
            self.error_rows = []

    handler = _FakeHandler()
    stage1_report = {
        "title": "Etapa 1 concluida - 3 parede(s) criada(s)",
        "subtitle": "s", "kpis": [("Paredes criadas", 3, m.UI_ACCENT)],
        "log": "log da etapa 1",
    }
    stage2_calls = []
    error_calls = []
    external_event = revit_stubs._Inert()
    form = m._WallReviewForm(
        stage1_report, external_event, handler,
        lambda payload: stage2_calls.append(payload),
        lambda payload: error_calls.append(payload),
    )

    # construir a janela sozinha NAO chama nada - nenhum bloco, nenhuma
    # analise, nenhuma correcao de parede.
    assert stage2_calls == [] and error_calls == []
    assert handler.on_done is None and handler.action is None
    assert form._start_button.Enabled is True
    assert form._start_button.Text == "Iniciar Modulacao das Paredes"

    # clique: so' PREPARA o handler (action="analyze") e dispara o evento
    # (Execute() roda depois, quando o Revit processar o ExternalEvent -
    # aqui o stub _Inert.Raise() e' um no-op, entao o callback ainda NAO
    # corre).
    form._on_start_click(None, None)
    assert handler.action == "analyze"
    assert handler.on_done == form._on_analyze_done
    assert form._start_button.Enabled is False
    assert stage2_calls == [] and error_calls == []

    # so' agora, simulando o Revit chamando Execute() (que ja teria escrito
    # o resultado em handler.error_rows) e reportando sucesso, a Etapa 2
    # realmente comeca.
    handler.error_rows = [{"wall_idx": 0, "problem_text": "x"}]
    form._on_analyze_done("analyze", None)
    assert stage2_calls == [handler.error_rows]
    assert error_calls == []


@case
def test_wall_review_form_erro_na_analise_nao_fecha_a_janela_nem_chama_etapa2():
    class _FakeHandler(object):
        def __init__(self):
            self.on_done = None
            self.action = None
            self.error_rows = []

    handler = _FakeHandler()
    stage1_report = {"title": "t", "subtitle": "s", "kpis": [], "log": ""}
    stage2_calls = []
    error_calls = []
    external_event = revit_stubs._Inert()
    form = m._WallReviewForm(
        stage1_report, external_event, handler,
        lambda payload: stage2_calls.append(payload),
        lambda payload: error_calls.append(payload),
    )

    form._on_start_click(None, None)
    form._on_analyze_done("error", "Exception()")

    assert stage2_calls == [], "erro na analise nao pode disparar a Etapa 2"
    assert error_calls == ["Exception()"]
    assert form._start_button.Enabled is True
    assert form._start_button.Text == "Iniciar Modulacao das Paredes"
    assert "Exception()" in form._status_label.Text


@case
def test_ajustar_erros_zero_corrigidas_nao_parece_sucesso_mudo():
    """Regressao do relato 'clico em Ajustar Erros e nada acontece': quando
    fix_all_wall_modulation_errors nao corrige NENHUM eixo, o botao antes
    virava "Concluido" (parece sucesso) e o motivo de cada eixo so' existia
    na coluna estreita da grade - facil de nao notar. Agora o botao reflete
    o resultado real e o log traz o motivo de cada eixo nao corrigido."""
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 4, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
    ])
    form = m._PostCreationForm(report, revit_stubs._Inert(), handler, [revit_stubs.ElementId(1)])
    # simula fix_all_wall_modulation_errors tendo rodado e falhado no unico eixo
    handler.error_rows = [
        {"wall_idx": 4, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "nao foi possivel aplicar: espaco insuficiente - requer revisao manual",
         "auto_fixable": False, "fix_plan": None},
    ]
    form._on_fix_done("fix_errors", None)
    assert form._fix_button.Text == "Nenhuma corrigida"
    assert "espaco insuficiente" in form._log_box.Text
    assert "eixo 4" in form._log_box.Text


@case
def test_zoom_com_falha_aparece_no_status_em_vez_de_ficar_mudo():
    report = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 0, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
    ])
    form = m._PostCreationForm(report, revit_stubs._Inert(), handler, [revit_stubs.ElementId(1)])
    form._on_zoom_done("error", "GetOpenUIViews indisponivel")
    assert "GetOpenUIViews indisponivel" in form._errors_status.Text


@case
def test_relatorio_estruturado_classifica_ocorrencias():
    issues = m.build_report_issues(
        failures=["Wall.Create falhou"], ambiguous_lines=["- 3 paredes fora dos limites"],
        modulation_results=[], opening_incompatible_modulation=[],
        unassigned_openings=[{}], possible_missed_bonecas=[(20.0, 250.0)],
        recovery_mode_used=False, openings_capped_at_top=0,
    )
    severities = [severity for severity, _item, _text in issues]
    assert severities[0] == "erro"
    assert "atencao" in severities
    assert any("20cm" in text for _s, _i, text in issues)


@case
def test_log_salva_com_acento_sem_quebrar():
    path = m._save_log_to_file(u"Nivel 1 - Ceramica\nLayer PAREDE ALVENARIA \u00c1REA")
    assert path is not None
    import io as _io
    with _io.open(path, encoding="utf-8") as handle:
        assert u"\u00c1REA" in handle.read()


@case
def test_realce_usa_a_cor_do_revit():
    """Regressao: a secao de interface importa System.Drawing.Color com o
    nome `Color`, no mesmo escopo de modulo em que Autodesk.Revit.DB.Color
    tinha sido importado antes. Como o corpo de uma funcao resolve globais
    na hora da chamada, o realce azul/vermelho passava a construir a cor do
    WinForms (que nao tem construtor r,g,b) e falhava - em silencio, porque
    as duas chamadas em main() sao protegidas por try/except."""
    assert m.RevitColor is not m.Color
    view = revit_stubs._Inert()
    m._apply_broken_length_overrides(view, [revit_stubs.ElementId(1)])
    m._apply_modulation_incompatible_overrides(view, [revit_stubs.ElementId(2)])


@case
def test_controles_dock_fill_entram_antes_dos_ancorados():
    """O WinForms ancora os controles na ordem INVERSA do indice: um
    Dock.Fill adicionado DEPOIS de um Dock.Top/Bottom ocuparia o painel
    inteiro e esconderia o outro. Este teste percorre a arvore das janelas
    e cobra a convencao (Fill primeiro) em todo painel que mistura os
    dois."""
    report = {
        "kpis": [("Paredes criadas", 12, m.UI_ACCENT)], "highlights": ["x"],
        "issues": [], "log": "log", "log_path": None,
    }
    handler = _make_post_creation_handler(error_rows=[
        {"wall_idx": 0, "wall_ids": [revit_stubs.ElementId(1)],
         "problem_text": "pilarete fora da modulacao", "auto_fixable": True, "fix_plan": {}},
    ])
    forms_to_check = [
        m._PostCreationForm(report, None, handler, [revit_stubs.ElementId(1)]),
        m._SetupForm({"PAREDES": [seg(0, 0, 400, 0), seg(0, 14, 400, 14)]}, ["Nivel 1"], {}),
    ]
    fill = "DockStyle.Fill"
    edges = ("DockStyle.Top", "DockStyle.Bottom", "DockStyle.Left", "DockStyle.Right")
    for form in forms_to_check:
        for container in [form] + list(form.descendants()):
            docks = [str(getattr(c, "Dock", "")) for c in container.Controls]
            if fill not in docks:
                continue
            first_edge = next((i for i, d in enumerate(docks) if d in edges), None)
            if first_edge is None:
                continue
            assert docks.index(fill) < first_edge, (type(container).__name__, docks)


# --------- AUDITORIA DE AMARRACAO ENTRE FIADAS: bug real da junta fantasma ---
@case
def test_auditoria_de_amarracao_nao_fabrica_junta_no_meio_de_abertura():
    """Bug real encontrado ao vivo (2026-08-24): dois candidatos de TRECHOS
    diferentes da MESMA parede, separados por uma abertura (nao encostados
    de verdade), sao vizinhos na ordenacao por t_start - sem excluir gaps
    grandes, o codigo fabricava uma "junta" no MEIO do vao da abertura, que
    (por a abertura ficar na mesma posicao X em toda fiada) virava um falso
    CONTINUOUS_VERTICAL_JOINT em praticamente toda parede com abertura (125
    de 127 paredes reprovadas numa execucao real, a maioria sem nenhum
    problema de amarracao de verdade)."""
    walls_to_create = [(seg(0, 0, 100, 0), ft(14.0), (False, False))]
    catalog = {"B39": {"is_special_bond": False, "is_compensator": False}}

    def _piece(center_cm, length_cm=39.0):
        return {
            "wall_idx": 0, "origin_world": XYZ(ft(center_cm), 0.0, 0.0),
            "x_dir": XYZ(1.0, 0.0, 0.0), "y_dir": XYZ(0.0, 1.0, 0.0),
            "length_cm": length_cm, "width_cm": 14.0, "course": "A",
            "logical_code": "B39",
        }

    # trecho 1: t=[0,39]; abertura: t=[39,61] (22cm - bem maior que um gap
    # de junta real); trecho 2: t=[61,100]. Identico em todas as fiadas -
    # exatamente o padrao que dispara o falso positivo antigo.
    num_courses = 6
    course_candidates = {
        ci: [_piece(19.5), _piece(80.5)] for ci in range(num_courses)
    }

    audit = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
        openings_per_wall=[[(ft(39.0), ft(61.0), ft(0.0), ft(210.0))]],
    )
    assert audit["ok"], audit["problems"]
    assert audit["continuous_joints"] == [], audit["continuous_joints"]

    # controle: dois candidatos REALMENTE encostados (gap ~1cm, junta de
    # assentamento de verdade) repetindo em toda fiada CONTINUA sendo
    # pego como CONTINUOUS_VERTICAL_JOINT - a correcao nao pode silenciar
    # o caso genuino, so' o fantasma do vao de abertura.
    course_candidates_real_joint = {
        ci: [_piece(19.5), _piece(59.5)] for ci in range(num_courses)
    }
    audit_real = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates_real_joint, catalog, num_courses,
    )
    assert not audit_real["ok"]
    assert len(audit_real["continuous_joints"]) == 1, audit_real["continuous_joints"]


@case
def test_auditoria_de_amarracao_nao_fabrica_faixa_falsa_em_no_de_meio_de_parede():
    """BUG REAL corrigido (2026-08-25, log de execucao real do usuario): um
    no' T/X no MEIO de uma parede (a mainWall de um T, ou qualquer parede
    de um X) recebe a MESMA peca de amarracao na MESMA posicao X em TODA
    fiada, por construcao (o no' nao muda de lugar entre fiadas - ver
    secao 5 de REGRAS_MODULACAO_BLOCOS.md, "T verdadeiro: B54 centrado no
    no'"). Isso e' CORRETO, nunca uma faixa vertical repetitiva de defeito -
    mas sem saber onde estao os nos de meio de parede, a auditoria nao tem
    como distinguir isso de uma faixa repetitiva de verdade, e reprovava a
    parede so' por isso (reproduzido no log real de uma execucao: paredes
    4/5/6/7/9, todas com um B54/B34 de no' de meio de parede, marcadas
    REPEATED_VERTICAL_COMPENSATOR_STRIP sem nenhum problema de amarracao
    de verdade - a mesma categoria de falso positivo ja' corrigida para o
    vao de abertura no teste acima, agora para NOS)."""
    walls_to_create = [(seg(0, 0, 300, 0), ft(14.0), (False, False))]
    catalog = {"B54": {"is_special_bond": True, "is_compensator": False}}
    node = {"point": XYZ(ft(150.0), 0.0, 0.0), "kind": "T_INTERSECTION",
            "main_wall_idx": 0, "incoming_wall_idx": 1}

    def _piece(course):
        return {
            "wall_idx": 0, "origin_world": XYZ(ft(150.0), 0.0, 0.0),
            "x_dir": XYZ(1.0, 0.0, 0.0), "y_dir": XYZ(0.0, 1.0, 0.0),
            "length_cm": 54.0, "width_cm": 14.0, "course": course,
            "logical_code": "B54",
        }

    num_courses = 6
    course_candidates = {
        ci: [_piece("A" if ci % 2 == 0 else "B")] for ci in range(num_courses)
    }

    # Sem `nodes` (chamador antigo/retrocompativel): reproduz o falso positivo.
    audit_no_nodes = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
    )
    assert not audit_no_nodes["ok"]
    assert audit_no_nodes["compensator_strips"], audit_no_nodes

    # COM `nodes` (a correcao): a peca do no' de meio de parede fica isenta.
    audit_with_nodes = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
        nodes=[node],
    )
    assert audit_with_nodes["ok"], audit_with_nodes["problems"]
    assert audit_with_nodes["compensator_strips"] == []


@case
def test_auditoria_nao_reprova_padrao_normal_de_fiadas_alternadas():
    """CAUSA-RAIZ real de "parede corrigida continua reprovada / bloco nunca
    e' lancado" (log de execucao real do usuario, 2026-08-25): como
    `solve_building_blocks_all_courses` resolve UM UNICO par de fiadas A/B
    e repete ESSE MESMO par fisicamente em toda fiada par (A) e toda fiada
    impar (B) do pe-direito, QUALQUER junta comum entre blocos B39 inteiros
    (o preenchimento padrao de qualquer parede real) aparece, por
    construcao, em 100% das fiadas da mesma paridade - exatamente o efeito
    esperado de uma amarracao alternada correta (a junta da fiada A e'
    coberta pelo corpo do bloco da fiada B, e reaparece na proxima fiada A).
    A antiga verificacao ALTERNATING_JOINT_PATTERN tratava isso como defeito
    e bloqueava a criacao de blocos (regra #1 absoluta) - na pratica,
    reprovava quase toda parede real (118 de 128 numa execucao real),
    mesmo paredes sem nenhum erro de geometria/modulacao e mesmo apos a
    etapa "Ajustar Erros" corrigir tudo que a Etapa 3B sabia corrigir. Este
    teste fixa o padrao TIPICO de fiadas alternadas (fiada A com juntas em
    X=39/78cm, fiada B na mesma posicao - o offset entre A e B fica nos
    candidatos passados aqui, nao neste teste simplificado) e confirma que
    a auditoria NAO reprova so' por causa disso."""
    walls_to_create = [(seg(0, 0, 200, 0), ft(14.0), (False, False))]
    catalog = {"B39": {"is_special_bond": False, "is_compensator": False}}

    def _piece(center_cm):
        return {
            "wall_idx": 0, "origin_world": XYZ(ft(center_cm), 0.0, 0.0),
            "x_dir": XYZ(1.0, 0.0, 0.0), "y_dir": XYZ(0.0, 1.0, 0.0),
            "length_cm": 39.0, "width_cm": 14.0, "course": "A",
            "logical_code": "B39",
        }

    # 15 fiadas fisicas (pe-direito real), MESMA fiada A repetida em todas
    # as pares e MESMA fiada B (com juntas OFFSET, sem coincidir com A - se
    # coincidissem seria um CONTINUOUS_VERTICAL_JOINT genuino, testado a
    # parte acima) repetida em todas as impares - exatamente como
    # `create_building_blocks` fisicamente lanca os blocos hoje.
    num_courses = 15
    course_candidates = {}
    for ci in range(num_courses):
        if ci % 2 == 0:
            course_candidates[ci] = [_piece(19.5), _piece(58.5), _piece(97.5),
                                      _piece(136.5), _piece(175.5)]
        else:
            course_candidates[ci] = [_piece(39.0), _piece(78.0), _piece(117.0),
                                      _piece(156.0)]

    audit = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
    )
    assert audit["ok"], audit["problems"]
    assert audit["continuous_joints"] == [], audit["continuous_joints"]
    # o padrao alternado continua sendo IDENTIFICADO (dado disponivel para
    # diagnostico), so' nao conta mais como reprovacao.
    assert audit["alternating_joints"], "deveria continuar detectando o padrao, so' nao bloquear"


@case
def test_auditoria_rejeita_meio_bloco_perto_de_amarracao():
    """Rede de seguranca da regra #2 (pedido explicito do usuario,
    2026-08-25): "nao utilizar meio bloco proximo a encontros L, T ou
    Cruz... penalizar fortemente ou rejeitar qualquer solucao que coloque
    um meio bloco proximo a uma amarracao". A geracao ja' proibe isso por
    construcao (_pier_ordered_layout/_pier_layout_avoiding_joints/
    _merge_adjacent_compensator_pairs), mas esta e' a SEGUNDA verificacao
    INDEPENDENTE que o usuario pediu (regra #7) - confere de novo, direto
    da geometria REAL das pecas ja' posicionadas, sem confiar que a
    geracao acertou."""
    walls_to_create = [(seg(0, 0, 300, 0), ft(14.0), (False, False)),
                        (seg(0, 0, 0, 300), ft(14.0), (False, False))]
    catalog = {"B19": {"is_special_bond": False, "is_compensator": False}}
    # L_CORNER na ponta 0 da parede 0 (e na ponta 0 da parede 1).
    node = {"point": XYZ(0.0, 0.0, 0.0), "kind": "L_CORNER", "arms": [(0, 0), (1, 0)]}
    nodes = [node]
    end_to_node = {(0, 0): 0, (1, 0): 0}

    def _b19(center_cm, course):
        return {
            "wall_idx": 0, "origin_world": XYZ(ft(center_cm), 0.0, 0.0),
            "x_dir": XYZ(1.0, 0.0, 0.0), "y_dir": XYZ(0.0, 1.0, 0.0),
            "length_cm": 19.0, "width_cm": 14.0, "course": course,
            "logical_code": "B19",
        }

    num_courses = 6
    # B19 encostado bem na ponta (t=0..19cm) - a amarracao esta' em t=0.
    course_candidates = {
        ci: [_b19(9.5, "A" if ci % 2 == 0 else "B")] for ci in range(num_courses)
    }
    audit = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
        nodes=nodes, end_to_node=end_to_node,
    )
    assert not audit["ok"]
    assert audit["half_blocks_near_ties"], audit["problems"]
    assert any("HALF_BLOCK_NEAR_TIE" in p for p in audit["problems"]), audit["problems"]
    # penalidade forte de proposito (pedido explicito: "penalize fortemente").
    assert audit["penalty"] >= m.PENALTY_HALF_BLOCK_NEAR_TIE

    # controle: o MESMO B19, so' que longe de qualquer amarracao (meio da
    # parede de 300cm) - nao dispara nada.
    course_candidates_far = {
        ci: [_b19(150.5, "A" if ci % 2 == 0 else "B")] for ci in range(num_courses)
    }
    audit_far = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates_far, catalog, num_courses,
        nodes=nodes, end_to_node=end_to_node,
    )
    assert audit_far["ok"], audit_far["problems"]
    assert audit_far["half_blocks_near_ties"] == []

    # controle: sem `nodes`/`end_to_node` (chamador antigo/retrocompativel) -
    # nunca acusa nada, so' porque nao tem como saber onde estao as
    # amarracoes (mesmo padrao de retrocompatibilidade do resto do arquivo).
    audit_no_context = m.audit_wall_bond_quality(
        0, walls_to_create, course_candidates, catalog, num_courses,
    )
    assert audit_no_context["half_blocks_near_ties"] == []


# ------------------------------------------------------------------------
# Auditoria de aberturas em alvenaria ja construida (secao 10 do
# REGRAS_MODULACAO_BLOCOS.md) - funcoes puras, sem Revit.
# ------------------------------------------------------------------------

@case
def test_merge_axis_intervals_funde_com_tolerancia_de_junta():
    merged = m.merge_axis_intervals([(0, 39), (40, 79), (100, 139)], joint_tolerance_cm=3.0)
    assert merged == [(0, 79), (100, 139)], merged


@case
def test_gaps_between_intervals_ignora_pontas():
    merged = [(0, 39), (100, 139), (200, 239)]
    gaps = m.gaps_between_intervals(merged)
    assert gaps == [(39, 100), (139, 200)], gaps


@case
def test_detect_wall_openings_classifica_janela_quando_nao_toca_a_base():
    # 6 fiadas: as 2 primeiras (base) sao cheias; das fiadas 2-5 (4
    # fiadas, >= OPENING_MIN_CONSEC_COURSES) tem um vao de 90cm no meio -
    # replica o padrao real medido (peitoril acima da base do trecho).
    full_row = [(0, 100, "BLOCO INTEIRO")]
    row_with_gap = [(0, 40, "BLOCO INTEIRO"), (130, 170, "BLOCO INTEIRO")]
    courses = [
        (0.0, full_row), (20.0, full_row),
        (40.0, row_with_gap), (60.0, row_with_gap),
        (80.0, row_with_gap), (100.0, row_with_gap),
    ]
    openings = m.detect_wall_openings_from_courses(courses)
    assert len(openings) == 1, openings
    op = openings[0]
    assert op["tipo_provavel"] == "JANELA", op
    assert op["width_cm"] == 90, op
    assert op["n_courses"] == 4, op


@case
def test_detect_wall_openings_classifica_porta_quando_toca_a_base():
    row_with_gap = [(0, 40, "BLOCO INTEIRO"), (130, 170, "BLOCO INTEIRO")]
    full_row = [(0, 100, "BLOCO INTEIRO")]
    # vao comeca JA' na fiada mais baixa da linha (z=0) - porta.
    courses = [
        (0.0, row_with_gap), (20.0, row_with_gap),
        (40.0, row_with_gap), (60.0, row_with_gap),
        (80.0, full_row),
    ]
    openings = m.detect_wall_openings_from_courses(courses)
    assert len(openings) == 1, openings
    assert openings[0]["tipo_provavel"] == "PORTA", openings[0]


@case
def test_detect_wall_openings_ignora_gap_pequeno_demais_e_grande_demais():
    # gap de 20cm (junta/no de amarracao, abaixo de OPENING_GAP_MIN_CM) -
    # nao deve virar abertura.
    row_gap_pequeno = [(0, 40, "BLOCO INTEIRO"), (60, 100, "BLOCO INTEIRO")]
    courses_pequeno = [(z, row_gap_pequeno) for z in (0.0, 20.0, 40.0, 60.0)]
    assert m.detect_wall_openings_from_courses(courses_pequeno) == []

    # gap de 400cm (outra parede, acima de OPENING_GAP_MAX_CM) - tambem
    # nao deve virar abertura.
    row_gap_grande = [(0, 40, "BLOCO INTEIRO"), (440, 480, "BLOCO INTEIRO")]
    courses_grande = [(z, row_gap_grande) for z in (0.0, 20.0, 40.0, 60.0)]
    assert m.detect_wall_openings_from_courses(courses_grande) == []


@case
def test_detect_wall_openings_ignora_vao_com_poucas_fiadas():
    # gap plausivel (90cm) mas so' em 2 fiadas seguidas (< MIN_CONSEC) -
    # provavelmente ruido/no de amarracao pontual, nao abertura de verdade.
    row_with_gap = [(0, 40, "BLOCO INTEIRO"), (130, 170, "BLOCO INTEIRO")]
    full_row = [(0, 100, "BLOCO INTEIRO")]
    courses = [(0.0, full_row), (20.0, row_with_gap), (40.0, row_with_gap), (60.0, full_row)]
    assert m.detect_wall_openings_from_courses(courses) == []


@case
def test_is_cut_block_justified_by_opening_perto_vs_longe():
    openings = [{"x_range": (40.0, 130.0), "width_cm": 90.0,
                 "z_range": (40.0, 100.0), "n_courses": 4, "tipo_provavel": "JANELA"}]
    # a 10cm da jamba esquerda (40) - dentro do teto de justificativa.
    assert m.is_cut_block_justified_by_opening(30.0, openings) is True
    # a 200cm de qualquer jamba - nao justificado por esta abertura.
    assert m.is_cut_block_justified_by_opening(-160.0, openings) is False
    # sem nenhuma abertura na linha - nunca justificado por proximidade.
    assert m.is_cut_block_justified_by_opening(35.0, []) is False


@case
def test_family_name_matchers_da_secao_10():
    assert m.is_canaleta_family_name("CANALETA J - 14x19-29x19")
    assert m.is_canaleta_family_name("CANALETA INTEIRA - 14x19x39")
    assert not m.is_canaleta_family_name("BLOCO INTEIRO - 14x19x39")
    assert m.is_cortado_family_name("BLOCO 34 CORTADO - 14x9x34")
    assert not m.is_cortado_family_name("BLOCO 34 - 14x19x34")
    assert m.is_verga_or_contraverga_family_name("VERGA JANELA")
    assert m.is_verga_or_contraverga_family_name("CONTRAVERGA1")
    assert not m.is_verga_or_contraverga_family_name("CANALETA J - 14x19-29x19")


@case
def test_meio_bloco_nao_aparece_contra_encontro_lt_x_fechado():
    """Regressao real reportada pelo usuario com imagens do Revit
    (2026-08-24): MEIO BLOCO (B19) aparecendo repetido em encontros L/T/X
    inteiros do predio, nao so' em aberturas/pontas livres - porque o
    criterio antigo de "ponta aberta" (`leading_joint_cm <=
    BLOCK_OPENING_JOINT_CM`) nao distinguia ponta fechada contra no' de
    ponta aberta contra abertura (as duas zeram a junta de contorno)."""
    pier_cm, lead_cm, trail_cm = 200.0, 1.0, 0.0
    # Fiada A: fecha so' com B39 (tier 1), nao depende do override.
    layout_a = m._pier_ordered_layout(pier_cm, CATALOG, lead_cm, trail_cm)
    assert layout_a is not None and all(c != "B19" for c, _s, _e in layout_a), layout_a
    joints_a = m._layout_internal_joint_positions_cm(layout_a, 0.0)
    voids_a = m._layout_void_positions_cm(layout_a, CATALOG, 0.0)

    # Fiada B contra um encontro L/T/X FECHADO dos dois lados: mesmo o
    # mecanismo de alinhamento de vazio (secao 6) tentando B19 pra' bater
    # o deslocamento de 20cm, ele NUNCA pode aparecer aqui.
    layout_b_closed = m._pier_layout_avoiding_joints(
        pier_cm, CATALOG, lead_cm, trail_cm, 0.0, joints_a, target_void_positions_cm=voids_a,
        leading_is_open=False, trailing_is_open=False,
    )
    assert layout_b_closed is not None
    assert all(code != "B19" for code, _s, _e in layout_b_closed), layout_b_closed

    # controle: com a ponta de ENTRADA aberta de verdade (abertura/ponta
    # livre), o deslocamento de meio modulo continua funcionando como
    # antes - B19 de 20cm no inicio da Fiada B.
    layout_b_open = m._pier_layout_avoiding_joints(
        pier_cm, CATALOG, lead_cm, trail_cm, 0.0, joints_a, target_void_positions_cm=voids_a,
        leading_is_open=True, trailing_is_open=True,
    )
    assert layout_b_open[0][0] == "B19", layout_b_open
    joints_b_open = m._layout_internal_joint_positions_cm(layout_b_open, 0.0)
    assert joints_a[0] - joints_b_open[0] == 20.0, (joints_a, joints_b_open)


# ------------------- ETAPA 3C: deslocamento de grupo de paredes conectadas
# (2026-08-24) - ver o cabecalho da secao em wall_modeling.py, logo apos
# apply_axis_opening_fix, para o contexto completo (excecao nova e escopada
# a regra #1, so' translacao perpendicular, so' vizinhos diretos em
# L_CORNER real).

@case
def test_wall_group_shift_targets_encontra_vizinho_l_corner_real():
    """Grafo REAL (extend_wall_ends_to_junctions + build_wall_graph) de uma
    parede horizontal W e uma vertical V que se encontram em (0,0): a ponta
    0 de CADA uma e' um L_CORNER real, e cada uma aponta para a OUTRA como
    vizinha."""
    walls = [(seg(0, 0, 500, 0), ft(14.0), (False, False)),
             (seg(0, 0, 0, 300), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)

    targets_w = m._wall_group_shift_targets(0, end_to_node, nodes)
    assert len(targets_w) == 1, targets_w
    assert targets_w[0]["neighbor_wall_idx"] == 1
    assert targets_w[0]["neighbor_end_index"] == 0
    assert targets_w[0]["shift_end"] == 0

    targets_v = m._wall_group_shift_targets(1, end_to_node, nodes)
    assert len(targets_v) == 1, targets_v
    assert targets_v[0]["neighbor_wall_idx"] == 0
    assert targets_v[0]["neighbor_end_index"] == 0


@case
def test_wall_group_shift_targets_ignora_no_sem_l_corner_real():
    """So' L_CORNER conta (ver docstring de _wall_group_shift_targets: um
    T_INTERSECTION em que wall_idx e' a incoming so' desliza o ponto de
    contato, nunca muda o comprimento de ninguem - nao serve como alvo de
    grupo). FREE_END/STRAIGHT_CONTINUATION tambem ficam de fora."""
    nodes = [
        {"kind": "L_CORNER", "arms": [(0, 0), (1, 0)],
         "neighbor_wall_idx": 1, "neighbor_end_index": 0},
        {"kind": "FREE_END", "arms": [(0, 1)]},
        {"kind": "T_INTERSECTION", "arms": [(2, 0)],
         "main_wall_idx": 9, "incoming_wall_idx": 2},
        {"kind": "STRAIGHT_CONTINUATION", "arms": [(3, 0), (4, 1)]},
    ]
    end_to_node = {(0, 0): 0, (1, 0): 0, (0, 1): 1, (2, 0): 2, (3, 0): 3}
    assert m._wall_group_shift_targets(0, end_to_node, nodes) == [
        {"shift_end": 0, "node_index": 0, "neighbor_wall_idx": 1, "neighbor_end_index": 0}
    ]
    assert m._wall_group_shift_targets(2, end_to_node, nodes) == []
    assert m._wall_group_shift_targets(3, end_to_node, nodes) == []
    # sem grafo (None) - nunca lanca excecao, devolve vazio
    assert m._wall_group_shift_targets(0, None, None) == []


@case
def test_wall_has_third_party_midspan_contact_detecta_t_e_x():
    nodes = [
        {"kind": "T_INTERSECTION", "main_wall_idx": 5, "incoming_wall_idx": 9},
        {"kind": "X_INTERSECTION", "crossing_walls": (2, 3)},
    ]
    assert m._wall_has_third_party_midspan_contact(5, nodes) is True   # e' a parede PRINCIPAL do T
    assert m._wall_has_third_party_midspan_contact(9, nodes) is False  # e' so' a incoming - nao conta
    assert m._wall_has_third_party_midspan_contact(2, nodes) is True   # participa do X
    assert m._wall_has_third_party_midspan_contact(7, nodes) is False


@case
def test_wall_shift_is_topologically_safe_regras():
    walls = [(seg(0, 0, 500, 0), ft(14.0), (False, False)),
             (seg(0, 0, 0, 300), ft(14.0), (False, False))]
    nodes = [
        {"kind": "L_CORNER", "arms": [(0, 0), (1, 0)]},
        {"kind": "FREE_END", "arms": [(0, 1)]},
        {"kind": "FREE_END", "arms": [(1, 1)]},
    ]
    end_to_node = {(0, 0): 0, (1, 0): 0, (0, 1): 1, (1, 1): 2}
    assert m._wall_shift_is_topologically_safe(0, walls, end_to_node, nodes) is True

    # ponta travada (testa real do CAD) - nunca deslocavel
    walls_locked = [(walls[0][0], walls[0][1], (True, False)), walls[1]]
    assert m._wall_shift_is_topologically_safe(0, walls_locked, end_to_node, nodes) is False

    # ponta STRAIGHT_CONTINUATION - deslocar separaria do fragmento colinear
    nodes_straight = list(nodes)
    nodes_straight[1] = {"kind": "STRAIGHT_CONTINUATION", "arms": [(0, 1), (9, 0)]}
    assert m._wall_shift_is_topologically_safe(0, walls, end_to_node, nodes_straight) is False

    # contato de terceiro no meio da parede (T em que wall_idx e' a principal)
    nodes_third_party = list(nodes) + [{"kind": "T_INTERSECTION", "main_wall_idx": 0, "incoming_wall_idx": 7}]
    assert m._wall_shift_is_topologically_safe(0, walls, end_to_node, nodes_third_party) is False


# Fixture geometrica verificada numericamente (nao apenas suposta): W
# horizontal de 482cm (fecha em blocos sozinha) + V vertical de 301cm (NAO
# fecha) formando um L_CORNER em (0,0) - extend_wall_ends_to_junctions
# empurra cada ponta 7cm (metade da espessura de 14cm da OUTRA parede),
# entao os comprimentos REAIS ficam W=489cm/V=308cm. So' com esses numeros
# exatos process_walls_one_by_one reproduz W ok / V nao-ok, e um
# deslocamento de -1cm em W fecha V (308->309cm) sem quebrar W.
_GROUP_SHIFT_W_RAW_CM = 482.0
_GROUP_SHIFT_V_RAW_CM = 301.0


def _group_shift_axis_fixture():
    walls = [(seg(0, 0, _GROUP_SHIFT_W_RAW_CM, 0), ft(14.0), (False, False)),
             (seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    return walls_ext, nodes, end_to_node


@case
def test_shift_wall_line_perpendicular_preserva_comprimento_da_propria_parede():
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    original_len_cm = to_cm(walls_ext[0][0].Length)
    for delta_cm in (1.0, -1.0, 2.0, -2.0):
        new_line = m._shift_wall_line_perpendicular(
            walls_ext, 0, ft(delta_cm), end_to_node, nodes
        )
        assert new_line is not None
        assert abs(to_cm(new_line.Length) - original_len_cm) < 0.01, (delta_cm, to_cm(new_line.Length))


@case
def test_recompute_neighbor_line_after_shift_muda_comprimento_no_sentido_certo():
    """Deslocar W nos DOIS sentidos (generalizado na mesma sessao para
    _boneca_compensated_solutions - mesmo principio aqui) muda o
    comprimento do vizinho em sinais OPOSTOS, sempre por |delta_cm| exatos
    (geometria axis-aligned - a formula de extend_wall_ends_to_junctions
    reaplicada contra a NOVA reta de W, ver _pushed_corner_point)."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    w_thickness_ft = walls_ext[0][1]
    original_v_len_cm = to_cm(walls_ext[1][0].Length)

    deltas_and_signs = []
    for delta_cm in (1.0, -1.0):
        new_w_line = m._shift_wall_line_perpendicular(
            walls_ext, 0, ft(delta_cm), end_to_node, nodes
        )
        w_new_p0 = new_w_line.GetEndPoint(0)
        w_dir = (new_w_line.GetEndPoint(1) - w_new_p0).Normalize()
        new_v_line, delta_len_ft = m._recompute_neighbor_line_after_shift(
            walls_ext, 1, 0, w_new_p0, w_dir, w_thickness_ft
        )
        assert new_v_line is not None
        # a ponta OPOSTA (end 1) do vizinho nunca muda
        assert new_v_line.GetEndPoint(1).DistanceTo(walls_ext[1][0].GetEndPoint(1)) < 1e-9
        new_v_len_cm = to_cm(new_v_line.Length)
        assert abs((new_v_len_cm - original_v_len_cm) - to_cm(delta_len_ft)) < 0.01
        assert abs(abs(to_cm(delta_len_ft)) - abs(delta_cm)) < 0.01, (delta_cm, to_cm(delta_len_ft))
        deltas_and_signs.append(to_cm(delta_len_ft))
    # +1cm e -1cm em W produzem deltas de SINAL OPOSTO no vizinho
    assert deltas_and_signs[0] * deltas_and_signs[1] < 0, deltas_and_signs


@case
def test_find_wall_group_shift_fixes_fecha_parede_sem_abertura_deslocando_vizinha():
    """Fim-a-fim: V (301cm bruto / 308cm real) NAO fecha sozinha e NAO tem
    abertura nenhuma (plan_axis_opening_fix nunca seria nem tentado - ver
    plan_hook em analyze_created_walls_for_errors), mas desloca W em -1cm
    e a modulacao de V passa a fechar - achado e VERIFICADO rodando
    process_walls_one_by_one de verdade na planta inteira (nao so'
    aritmetica)."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    openings_per_wall = [[], []]

    def plan_hook(wall_idx, fill_result, verify):
        return None  # nunca ha' abertura nesta fixture - fora de escopo do plan_hook normal

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    ok_by_wall = dict((e["wall_idx"], e["validation"]["ok"]) for e in run["per_wall"])
    assert ok_by_wall[0] is True, "W sozinha precisa fechar (senao o teste nao isola nada)"
    assert ok_by_wall[1] is False, "V sozinha precisa FALHAR (senao nao ha' nada para o grupo consertar)"

    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    assert set(fixes.keys()) == {0, 1}, fixes
    plan = fixes[0]
    assert fixes[0] is fixes[1], "os dois membros do MESMO grupo compartilham o MESMO plano"
    assert plan["kind"] == "group_shift"
    assert plan["shifted_wall_idx"] == 0
    assert abs(plan["shift_delta_cm"]) <= 1.0 + 1e-9, "o menor delta que fecha e' 1cm - tem que ser o escolhido"
    members_by_idx = dict((mm["wall_idx"], mm) for mm in plan["members"])
    assert abs(members_by_idx[0]["new_length_cm"] - to_cm(walls_ext[0][0].Length)) < 0.01, \
        "a parede deslocada nunca muda de comprimento (translacao rigida)"
    assert m.wall_length_closes_with_blocks_cm(members_by_idx[1]["new_length_cm"])


@case
def test_process_walls_one_by_one_progress_cb_reporta_avanco():
    """PERFORMANCE: progress_cb(done, total) existe para dar visibilidade
    ao vivo no solver principal (ver docstring de process_walls_one_by_one) -
    confere que e' chamado, que a ultima chamada fecha em done==total (a
    barra "termina" de verdade) e que nunca reporta alem do total."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    openings_per_wall = [[], []]
    calls = []

    def progress_cb(done, total):
        calls.append((done, total))

    m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG,
        progress_cb=progress_cb,
    )

    assert calls, "progress_cb tem que ser chamado pelo menos uma vez"
    assert calls[-1] == (2, 2), calls  # 2 paredes na fixture - a ultima chamada fecha em done==total
    for done, total in calls:
        assert 1 <= done <= total, calls


@case
def test_find_wall_group_shift_fixes_progress_cb_reporta_cada_tentativa():
    """PERFORMANCE: progress_cb(tentativa, total_tentativas, wall_idx, tipo)
    existe porque cada tentativa de find_wall_group_shift_fixes RE-SOLVE A
    PLANTA INTEIRA so' para verificar um candidato (ver docstring) - sem
    isso, ate' WALL_GROUP_SHIFT_VERIFY_BUDGET tentativas rodavam em
    silencio total. Reusa o mesmo fixture/cenario do teste
    "fecha_parede_sem_abertura_deslocando_vizinha" (que ja' comprova que o
    deslocamento de grupo E' encontrado) - aqui so' confere que cada
    tentativa de verdade foi reportada, em ordem, sem pular nem repetir."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    openings_per_wall = [[], []]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )

    calls = []

    def progress_cb(*args):
        calls.append(args)

    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook,
        progress_cb=progress_cb,
    )

    assert set(fixes.keys()) == {0, 1}, "a fixture tem que ter encontrado o mesmo ajuste de sempre"
    assert calls, "progress_cb tem que ser chamado a cada tentativa de re-solve"
    # Heartbeats de UMA linha de texto (ver _solver_progress_cb em main()) -
    # anunciam a entrada na ETAPA 3C e cada parede tentada, MESMO quando
    # nenhum orcamento de verificacao chega a ser gasto - nao fazem parte da
    # numeracao de tentativas abaixo.
    heartbeats = [c for c in calls if len(c) == 1]
    assert heartbeats, "tem que anunciar a entrada na ETAPA 3C e cada parede tentada"
    attempt_calls = [c for c in calls if len(c) == 4]
    assert attempt_calls, "progress_cb tem que ser chamado a cada tentativa de re-solve"
    for attempt, total_attempts, wall_idx, kind in attempt_calls:
        assert 1 <= attempt <= total_attempts, attempt_calls
        assert total_attempts == m.WALL_GROUP_SHIFT_VERIFY_BUDGET
        assert wall_idx in (0, 1)
        assert kind in ("deslocamento de grupo", "ajuste de comprimento na ponta livre")
    assert [c[0] for c in attempt_calls] == list(range(1, len(attempt_calls) + 1)), \
        "tentativas numeradas em ordem crescente, sem pular nem repetir"


@case
def test_extend_wall_line_axial_move_so_a_ponta_pedida():
    walls = [(seg(0, 0, 300, 0), ft(14.0), (False, False))]
    original_p0 = walls[0][0].GetEndPoint(0)
    original_p1 = walls[0][0].GetEndPoint(1)

    grown_at_1 = m._extend_wall_line_axial(walls, 0, ft(2.0), 1)
    assert grown_at_1 is not None
    assert abs(to_cm(grown_at_1.Length) - 302.0) < 0.01
    assert grown_at_1.GetEndPoint(0).DistanceTo(original_p0) < 1e-9, "ponta 0 nunca muda quando side=1"

    shrunk_at_0 = m._extend_wall_line_axial(walls, 0, ft(-2.0), 0)
    assert shrunk_at_0 is not None
    assert abs(to_cm(shrunk_at_0.Length) - 298.0) < 0.01
    assert shrunk_at_0.GetEndPoint(1).DistanceTo(original_p1) < 1e-9, "ponta 1 nunca muda quando side=0"

    # nunca colapsa abaixo do minimo
    assert m._extend_wall_line_axial(walls, 0, ft(-299.0), 0) is None


@case
def test_find_wall_group_shift_fixes_alonga_parede_isolada_sem_vizinho():
    """Parede UNICA, sem nenhuma vizinha (as duas pontas FREE_END) - mesmo
    comprimento V=308cm que a fixture de grupo (_group_shift_axis_fixture)
    ja comprova que NAO fecha sozinho, e que +1cm (309cm) fecha. Sem
    candidato de deslocamento de grupo (candidates fica vazio, sem
    _wall_group_shift_targets nenhum), o fallback de parede ISOLADA precisa
    achar esse mesmo +1cm alongando a propria parede."""
    walls = [(seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM + 7.0), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    assert abs(to_cm(walls_ext[0][0].Length) - (_GROUP_SHIFT_V_RAW_CM + 7.0)) < 0.01, \
        "sem vizinho nao ha' push de junction - o comprimento fica exatamente o bruto"
    openings_per_wall = [[]]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    assert run["per_wall"][0]["validation"]["ok"] is False, \
        "308cm precisa FALHAR sozinho (senao o teste nao isola nada)"

    candidates = m._candidate_walls_to_shift_for(0, walls_ext, end_to_node, nodes)
    assert candidates == [], "parede isolada nao pode ter candidato de deslocamento de grupo"

    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    assert set(fixes.keys()) == {0}, fixes
    plan = fixes[0]
    assert plan["kind"] == "wall_length_adjust"
    assert plan["shifted_wall_idx"] == 0
    assert abs(abs(plan["shift_delta_cm"]) - 1.0) < 1e-9, \
        "o menor delta que fecha esta parede e' 1cm (ver _group_shift_axis_fixture)"
    member = plan["members"][0]
    assert member["role"] == "neighbor", "nunca 'shifted' aqui - o comprimento muda de verdade"
    assert m.wall_length_closes_with_blocks_cm(member["new_length_cm"])


@case
def test_analyze_created_walls_for_errors_grupo_nao_desloca_parede_conectada():
    """REGRESSAO/mudanca de comportamento (2026-08-26, pedido explicito do
    usuario): analyze_created_walls_for_errors NAO deve mais deslocar uma
    parede CONECTADA para fechar a modulacao de outra (a antiga ETAPA 3C,
    find_wall_group_shift_fixes, foi retirada do pipeline - a funcao
    continua existindo/testada isoladamente, so' nao e' mais chamada
    daqui). Das duas paredes da fixture, so' V (wall_idx 1) tem modulacao
    propria que nao fecha - W (wall_idx 0) e' valida por si so' (so'
    aparecia antes porque era a parede "shifted" do grupo); sem a ETAPA 3C,
    V fica marcada para revisao manual (azul) e W nem aparece na lista de
    erros."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    rows = m.analyze_created_walls_for_errors(
        None, walls_ext, [[], []], {}, [], nodes, end_to_node, CATALOG, [], [], []
    )
    assert len(rows) == 1, rows
    assert rows[0]["wall_idx"] == 1, rows
    assert rows[0]["auto_fixable"] is False, rows
    assert rows[0]["fix_plan"] is None, rows


@case
def test_apply_wall_group_shift_translada_shifted_e_reposiciona_vizinho():
    """apply_wall_group_shift sobre Wall falsos (_FakeWall/_FakeDoc): o
    membro 'shifted' e' translado rigidamente (mesmo vetor em toda a
    curva), o membro 'neighbor' so' tem a ponta afetada movida - a ponta
    OPOSTA (e o Z dela) fica bit-a-bit identica a' original."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    openings_per_wall = [[], []]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    plan = fixes[0]

    id_w, id_v = 501, 502
    fake_doc = _FakeDoc({
        id_w: _FakeWall(walls_ext[0][0]),
        id_v: _FakeWall(walls_ext[1][0]),
    })
    created_walls_by_axis = {0: [(id_w, "cad")], 1: [(id_v, "cad")]}
    original_v_far = walls_ext[1][0].GetEndPoint(1)

    applied, failures = m.apply_wall_group_shift(
        fake_doc, plan, walls_ext, openings_per_wall, created_walls_by_axis, []
    )
    assert failures == [], failures
    assert applied == 2

    new_w_curve = fake_doc.GetElement(id_w).Location.Curve
    assert abs(to_cm(new_w_curve.Length) - to_cm(walls_ext[0][0].Length)) < 0.01, \
        "translacao rigida - comprimento de W nunca muda"

    new_v_curve = fake_doc.GetElement(id_v).Location.Curve
    assert new_v_curve.GetEndPoint(1).DistanceTo(original_v_far) < 1e-9, \
        "a ponta OPOSTA do vizinho nunca e' tocada"
    assert m.wall_length_closes_with_blocks_cm(to_cm(new_v_curve.Length))


@case
def test_apply_wall_group_shift_aplica_plano_wall_length_adjust():
    """apply_wall_group_shift, sem NENHUMA alteracao, precisa aplicar
    corretamente um plano kind='wall_length_adjust' (role sempre 'neighbor') -
    so' a ponta que mudou e' editada, a ponta oposta fica intocada."""
    walls = [(seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM + 7.0), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[]]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    plan = fixes[0]

    id_w = 601
    fake_doc = _FakeDoc({id_w: _FakeWall(walls_ext[0][0])})
    created_walls_by_axis = {0: [(id_w, "cad")]}
    original_p0 = walls_ext[0][0].GetEndPoint(0)
    original_p1 = walls_ext[0][0].GetEndPoint(1)

    applied, failures = m.apply_wall_group_shift(
        fake_doc, plan, walls_ext, openings_per_wall, created_walls_by_axis, []
    )
    assert failures == [], failures
    assert applied == 1

    new_curve = fake_doc.GetElement(id_w).Location.Curve
    assert m.wall_length_closes_with_blocks_cm(to_cm(new_curve.Length))
    # uma das duas pontas (a que o plano diz que mudou) fica intocada
    unchanged_end_kept = (
        new_curve.GetEndPoint(0).DistanceTo(original_p0) < 1e-9
        or new_curve.GetEndPoint(1).DistanceTo(original_p1) < 1e-9
    )
    assert unchanged_end_kept, "pelo menos uma ponta precisa ficar exatamente onde estava"


@case
def test_x_intersection_degrada_quando_perto_de_um_L_CORNER():
    """Achado num fuzzer sintetico (2026-08-25), nao no caso do usuario:
    X_INTERSECTION nunca verificava espaco - forcava B54 (54cm, CENTRADO
    no cruzamento) incondicionalmente. Perto de um canto em L, o B54
    colidia fisicamente com o B34 do canto (o corpo dele comeca ate' 27cm
    ANTES do ponto do X) - mesma familia de sintoma do T perto de canto,
    so' que do lado do X. Precisa fechar sem nenhum trecho negativo."""
    walls = [(seg(0, 0, 600, 0), ft(14.0), (False, False)),
             (seg(0, 0, 0, 300), ft(14.0), (False, False)),
             (seg(20, -300, 20, 300), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[], [], []]

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=lambda a, b, c: None
    )
    e0 = [e for e in run["per_wall"] if e["wall_idx"] == 0][0]
    negatives = [x for x in e0["non_modular"] if x["current_length_cm"] < 0]
    assert negatives == [], "X perto do canto nao pode roubar a reserva do inicio de A: %s" % negatives


@case
def test_x_intersection_sem_openings_per_wall_mantem_comportamento_antigo():
    """`openings_per_wall=None` (chamador antigo) pula a checagem de
    espaco inteira - sempre forca B54 nas duas paredes, como antes desta
    correcao. Garante que quem ainda nao thread'a openings_per_wall/nodes/
    end_to_node continua recebendo o comportamento historico."""
    node = {"kind": "X_INTERSECTION", "point": XYZ(ft(20.0), 0.0, 0.0), "crossing_walls": (0, 1)}
    walls = [(seg(0, 0, 600, 0), ft(14.0), (False, False)),
             (seg(20, -300, 20, 300), ft(14.0), (False, False))]
    result = m.solve_x_intersection(node, walls, CATALOG)
    assert result["ok"] is True
    assert result["course_a"]["logical_code"] == "B54"
    assert result["course_b"]["logical_code"] == "B54"


@case
def test_reserva_de_ponta_ignora_encontro_de_meio_de_parede_proximo():
    """REGRESSAO do defeito mais profundo por tras dos trechos NEGATIVOS
    (42 dos 57 eixos em revisao manual na planta real do usuario):
    _node_involved_wall_ends usava uma heuristica de DISTANCIA (40cm) para
    decidir se um no' toca a ponta de uma parede - e um encontro em T no
    MEIO da parede podia cair, por coincidencia, a menos de 40cm da ponta
    de verdade dessa mesma parede (exatamente o caso de um T logo apos um
    canto em L). A reserva de INICIO da parede principal era entao
    calculada a partir da peca do T (muito mais longe do inicio real),
    gerando um trecho de comprimento NEGATIVO.

    Com a mesma geometria de test_canto_em_L_gira_o_b34_quando_ha_um_T_a_menos_de_34cm
    (T a 20cm de um canto em L), a parede principal precisa fechar sem
    NENHUM trecho negativo - so' um pilarete pequeno (que fecha com
    compensador) e o preenchimento normal do resto do eixo."""
    walls = [(seg(0, 0, 500, 0), ft(14.0), (False, False)),
             (seg(0, 0, 0, 300), ft(14.0), (False, False)),
             (seg(20, 0, 20, 300), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[], [], []]

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=lambda a, b, c: None
    )
    e0 = [e for e in run["per_wall"] if e["wall_idx"] == 0][0]
    negatives = [x for x in e0["non_modular"] if x["current_length_cm"] < 0]
    assert negatives == [], "nenhum trecho negativo - o T nao pode roubar a reserva do inicio de A: %s" % negatives

    # o eixo aparece na lista de erros mas SEM correcao automatica (sem
    # abertura por perto - 2026-08-26: ETAPA 3C/deslocamento de parede
    # conectada foi removida) - fica marcado para revisao manual (azul).
    rows = m.analyze_created_walls_for_errors(
        None, walls_ext, openings_per_wall, {}, [], nodes, end_to_node, CATALOG, [], [], []
    )
    row0 = [r for r in rows if r["wall_idx"] == 0][0]
    assert row0["auto_fixable"] is False, row0["problem_text"]


@case
def test_canto_em_L_gira_o_b34_quando_ha_um_T_a_menos_de_34cm():
    """Com um encontro em T a 20cm de um canto em L na MESMA parede, as
    duas pecas de 34cm ficavam uma sobre a outra (14cm de sobreposicao):
    o solver detectava a colisao, desfazia AS DUAS e a parede terminava
    sem bloco nenhum. Agora a peca do canto GIRA para a parede
    perpendicular, nas DUAS fiadas.

    Girar nas duas e' proposital: apenas trocar qual fiada vai em qual
    parede nao resolve, porque o T tambem alterna - a sobreposicao de
    14cm apenas migrava de fiada (medido)."""
    walls = [(seg(0, 0, 500, 0), ft(14.0), (False, False)),    # A - principal
             (seg(0, 0, 0, 300), ft(14.0), (False, False)),    # C - canto em L
             (seg(20, 0, 20, 300), ft(14.0), (False, False))]  # B - T a 20cm
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    cands = m.solve_all_intersections(nodes, walls_ext, CATALOG, [[], [], []], end_to_node)["candidates"]

    p0, _p1, wall_dir, _len, _th = m._wall_axis_and_length(walls_ext, 0)
    extents = {}
    for c in cands:
        lo, hi = m._candidate_extent_on_wall_axis(c, p0, wall_dir)
        extents.setdefault(c["course"], []).append((round(lo, 1), round(hi, 1)))

    for course in ("A", "B"):
        spans = sorted(extents[course])
        assert len(spans) == 2, spans
        (lo1, hi1), (lo2, hi2) = spans
        overlap = min(hi1, hi2) - max(lo1, lo2)
        assert overlap <= 1e-6, "fiada %s: pecas de amarracao sobrepoem %.1fcm %s" % (
            course, overlap, spans)
        # a peca do canto foi GIRADA: ocupa a LARGURA (14cm) no eixo de A,
        # nao o comprimento (34cm) - nas duas fiadas
        assert abs((hi1 - lo1) - 14.0) < 0.01, (course, spans)


@case
def test_wall_length_snap_targets_encurta_antes_de_alongar_e_aceita_fracao():
    """A correcao central do ajuste de comprimento: o delta vem do ALVO,
    nao de um range() inteiro. Com passo inteiro, 89.5cm NUNCA alcanca um
    comprimento valido (90.5/88.5/91.5... todos preservam a fracao) - era
    esse o motivo de o ajuste automatico nunca acontecer na planta real."""
    targets = m._wall_length_snap_targets_cm(89.5, 5.0)
    assert targets, "89.5cm precisa ter alvo valido por perto"

    # 89 e 90 empatam em |delta|=0.5; ENCURTAR vem primeiro (regra do usuario)
    assert abs(targets[0][0] - 89.0) < 1e-9, targets[:3]
    assert abs(targets[0][1] - (-0.5)) < 1e-9, targets[:3]
    assert abs(targets[1][0] - 90.0) < 1e-9, targets[:3]

    # todo alvo e' INTEIRO (a revalidacao pos-aplicacao exige whole cm) e
    # de fato fecha em blocos; e nenhum passa do teto pedido
    for target_cm, delta_cm in targets:
        assert abs(target_cm - round(target_cm)) < 1e-9, target_cm
        assert m.wall_length_closes_with_blocks_cm(target_cm), target_cm
        assert abs(delta_cm) <= 5.0 + 1e-9, delta_cm
        assert abs((target_cm - delta_cm) - 89.5) < 1e-9

    # ordenado pelo MENOR |delta|
    deltas = [abs(d) for _t, d in targets]
    assert deltas == sorted(deltas), deltas

    # nenhum delta inteiro resolveria 89.5 - a prova do bug original
    assert not any(m.wall_length_closes_with_blocks_cm(89.5 + d)
                   for d in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5))

    assert m._wall_length_snap_targets_cm(89.5, 0.0) == []


@case
def test_find_wall_group_shift_fixes_ajusta_parede_de_comprimento_FRACIONARIO():
    """Regressao do bug principal: uma parede de comprimento FRACIONARIO
    que nao fecha era impossivel de corrigir (todo delta inteiro preserva a
    fracao). Agora o alvo inteiro mais proximo e' alcancado."""
    raw_cm = _GROUP_SHIFT_V_RAW_CM + 7.0 + 0.5   # 308.5cm - fracionario
    walls = [(seg(0, 0, 0, raw_cm), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[]]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    assert run["per_wall"][0]["validation"]["ok"] is False

    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    assert set(fixes.keys()) == {0}, fixes
    plan = fixes[0]
    assert plan["kind"] == "wall_length_adjust"
    # delta FRACIONARIO - exatamente o que era inexprimivel antes
    assert abs(plan["shift_delta_cm"] - round(plan["shift_delta_cm"])) > 1e-9, plan["shift_delta_cm"]
    new_len = plan["members"][0]["new_length_cm"]
    assert abs(new_len - round(new_len)) < 0.01, "o comprimento final tem que ser inteiro"
    assert m.wall_length_closes_with_blocks_cm(new_len)


@case
def test_find_wall_group_shift_fixes_ajusta_com_apenas_UMA_ponta_livre():
    """Basta UMA ponta FREE_END: mover a ponta livre ao longo do eixo nao
    cria dente (ela nao encosta em nada), e a ponta em L_CORNER nunca e'
    tocada. Antes exigia-se as DUAS pontas livres, o que numa planta real
    praticamente nunca acontece."""
    walls_ext, nodes, end_to_node = _group_shift_axis_fixture()
    free_v = m._axis_free_end_sides(1, end_to_node, nodes)
    assert free_v == [1], "V tem UMA ponta livre (a outra e' o L_CORNER)"

    targets = m._wall_length_snap_targets_cm(to_cm(walls_ext[1][0].Length), 5.0)
    assert targets, "V (308cm) precisa ter alvo valido dentro de 5cm"
    new_line = m._extend_wall_line_axial(walls_ext, 1, ft(targets[0][1]), free_v[0])
    assert new_line is not None
    # a ponta CONECTADA (index 0, o L_CORNER) fica exatamente onde estava
    assert new_line.GetEndPoint(0).DistanceTo(walls_ext[1][0].GetEndPoint(0)) < 1e-9


@case
def test_fix_all_wall_modulation_errors_despacha_group_shift_e_wall_length_adjust():
    """fix_all_wall_modulation_errors ainda sabe APLICAR um fix_plan
    kind='group_shift'/'wall_length_adjust' quando um `row` chega com um
    desses (apply_wall_group_shift, dispatch por `is_wall_geometry_plan`) -
    a funcao em si nao foi removida, so' analyze_created_walls_for_errors
    parou de GERAR esse tipo de plano automaticamente (2026-08-26, ETAPA 3C
    retirada do pipeline por pedido explicito do usuario: deslocar uma
    parede CONECTADA sem relacao com abertura deixou de ser automatico -
    a parede fica azul para o usuario ajustar manualmente). Este teste
    monta o `row` diretamente com find_wall_group_shift_fixes (que continua
    existindo e testada isoladamente, ver os testes
    test_find_wall_group_shift_fixes_*/test_apply_wall_group_shift_* acima)
    em vez de passar por analyze_created_walls_for_errors, provando que o
    DESPACHO de fix_all_wall_modulation_errors continua correto para quem
    ainda montar um plano assim manualmente."""
    walls = [(seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM + 7.0), ft(14.0), (False, False))]
    walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
    openings_per_wall = [[]]

    def plan_hook(wall_idx, fill_result, verify):
        return None

    run = m.process_walls_one_by_one(
        walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
    )
    fixes = m.find_wall_group_shift_fixes(
        run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
    )
    plan = fixes[0]
    assert plan["kind"] == "wall_length_adjust"
    rows = [{
        "wall_idx": 0, "wall_ids": [], "problem_text": "modulacao nao fecha",
        "auto_fixable": True, "fix_plan": plan,
    }]

    id_w = 701
    fake_doc = _FakeDoc({id_w: _FakeWall(walls_ext[0][0])})
    created_walls_by_axis = {0: [(id_w, "cad")]}

    original_evaluate = m.evaluate_wall_modulation

    def _stub_evaluate(wall_ids, target_doc=None, opening_gaps=None):
        return [{"id": wid, "compatible": True} for wid in wall_ids]

    m.evaluate_wall_modulation = _stub_evaluate
    try:
        fixed_count, manual_review_count, updated_rows = m.fix_all_wall_modulation_errors(
            fake_doc, rows, walls_ext, openings_per_wall,
            created_walls_by_axis=created_walls_by_axis, all_openings=[],
        )
    finally:
        m.evaluate_wall_modulation = original_evaluate

    assert fixed_count == 1, updated_rows
    assert manual_review_count == 0, updated_rows
    assert updated_rows[0].get("resolved") is True, updated_rows
    assert "comprimento da parede ajustado" in updated_rows[0]["problem_text"], \
        updated_rows[0]["problem_text"]
    assert m.wall_length_closes_with_blocks_cm(to_cm(walls_ext[0][0].Length)), \
        to_cm(walls_ext[0][0].Length)


@case
def test_find_wall_group_shift_fixes_resolve_parcial_bate_com_resolve_completo():
    """Regressao de seguranca do RESOLVE PARCIAL da ETAPA 3C (ver
    ETAPA_3C_PARTIAL_RESOLVE_ENABLED/_expand_dirty_wall_idxs, pedido
    explicito do usuario de 'mais velocidade' 2026-08-26): numa planta com
    o mesmo encontro em L de _group_shift_axis_fixture MAIS uma terceira
    parede ISOLADA (sem no' compartilhado com as outras duas, ja fechando a
    modulacao sozinha), o resultado de find_wall_group_shift_fixes tem que
    ser IDENTICO com o resolve parcial ligado ou desligado - E a parede
    isolada nunca pode ser recalculada de verdade (tem que vir REUSADA do
    baseline `run`, nao ser dirty)."""
    w_line = seg(0, 0, _GROUP_SHIFT_W_RAW_CM, 0)
    v_line = seg(0, 0, 0, _GROUP_SHIFT_V_RAW_CM)

    def plan_hook(wall_idx, fill_result, verify):
        return None

    # A parede isolada precisa fechar a modulacao SOZINHA (bem longe de W/V,
    # sem no' compartilhado com nenhuma delas) - varre alguns multiplos
    # simples de B39 ate' achar um comprimento que feche livre-livre, em vez
    # de supor um valor de cabeca (o mesmo comprimento de W, testado
    # primeiro, NAO fecha isolado porque a ponta de W na fixture original
    # esta' presa ao encontro com V, condicao diferente de uma ponta
    # totalmente livre).
    run = walls_ext = nodes = end_to_node = openings_per_wall = None
    for z_len_cm in (156.0, 195.0, 234.0, 273.0, 312.0, 351.0, 390.0):
        z_line = seg(1000, 1000, 1000 + z_len_cm, 1000)
        walls = [(w_line, ft(14.0), (False, False)),
                 (v_line, ft(14.0), (False, False)),
                 (z_line, ft(14.0), (False, False))]
        walls_ext, jmap = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
        nodes, end_to_node = m.build_wall_graph(walls_ext, jmap)
        openings_per_wall = [[], [], []]
        run = m.process_walls_one_by_one(
            walls_ext, nodes, end_to_node, openings_per_wall, CATALOG, plan_hook=plan_hook
        )
        ok_by_wall = dict((e["wall_idx"], e["validation"]["ok"]) for e in run["per_wall"])
        if ok_by_wall.get(2):
            break
    assert ok_by_wall[0] is True, "W sozinha precisa fechar (senao o teste nao isola nada)"
    assert ok_by_wall[1] is False, "V sozinha precisa FALHAR (senao nao ha' nada para o grupo consertar)"
    assert ok_by_wall[2] is True, (
        "nenhum multiplo de B39 testado fechou a parede isolada sozinha - "
        "ajustar a lista de comprimentos tentados"
    )

    seen_wall_idxs = []
    original_solve_wall_free_fill = m.solve_wall_free_fill

    def _spy_solve(wall_idx, *args, **kwargs):
        seen_wall_idxs.append(wall_idx)
        return original_solve_wall_free_fill(wall_idx, *args, **kwargs)

    m.solve_wall_free_fill = _spy_solve
    try:
        fixes_partial = m.find_wall_group_shift_fixes(
            run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
        )
    finally:
        m.solve_wall_free_fill = original_solve_wall_free_fill

    assert 2 not in seen_wall_idxs, (
        "RESOLVE PARCIAL deveria ter REUSADO a parede isolada (2) do baseline, "
        "nunca chamado solve_wall_free_fill de verdade para ela"
    )

    original_flag = m.ETAPA_3C_PARTIAL_RESOLVE_ENABLED
    m.ETAPA_3C_PARTIAL_RESOLVE_ENABLED = False
    try:
        fixes_full = m.find_wall_group_shift_fixes(
            run, walls_ext, openings_per_wall, nodes, end_to_node, CATALOG, plan_hook
        )
    finally:
        m.ETAPA_3C_PARTIAL_RESOLVE_ENABLED = original_flag

    assert set(fixes_partial.keys()) == set(fixes_full.keys()) == {0, 1}, (fixes_partial, fixes_full)
    assert fixes_partial[0]["kind"] == fixes_full[0]["kind"] == "group_shift"
    assert fixes_partial[0]["shift_delta_cm"] == fixes_full[0]["shift_delta_cm"], (
        "resolve parcial e completo tem que escolher o MESMO candidato vencedor"
    )


# ==========================================
# REGRESSAO 2026-08-26: create_building_blocks (Etapa 5, cria as
# instancias REAIS no Revit) nunca era exercitada de ponta a ponta pela
# suite offline - todo teste que passava por _execute_create mockava
# `_create_building_blocks` inteira (_fake_create_building_blocks, ver
# acima), entao um bug real na linha `target_doc.Create.NewFamilyInstance`
# (ou na Transaction ao redor dela) nao seria pego por nenhum teste. Com
# `_StubCreate.NewFamilyInstance` (ver revit_stubs.py), os testes abaixo
# chamam create_building_blocks DE VERDADE.
# ==========================================

class _FakeSymbol(object):
    """FamilySymbol falso - so' o suficiente (IsActive/Activate) para o
    bloco de ativacao no inicio de create_building_blocks nao explodir."""

    def __init__(self):
        self.IsActive = False

    def Activate(self):
        self.IsActive = True


def _real_catalog_entry(code, height_cm=19.0):
    return {
        "symbol": _FakeSymbol(), "logical_code": code, "length_cm": 39.0,
        "height_cm": height_cm, "width_cm": 14.0, "cells_local": [],
        "is_special_bond": False, "is_compensator": False,
        "source_instance_id": None,
    }


@case
def test_create_building_blocks_cria_instancias_reais_via_stub_newfamilyinstance():
    """Chama create_building_blocks (a funcao real, nao um mock) contra o
    stub de Document (_StubDoc/_StubCreate) e confirma que created_count/
    created_instances vem de instancias REALMENTE criadas (Id devolvido
    pelo stub de Create.NewFamilyInstance a cada chamada, nunca fabricado
    pelo teste) - fecha o gap de cobertura descrito acima."""
    catalog = {"B39": _real_catalog_entry("B39", height_cm=19.0)}
    candidates = [
        {"wall_idx": 0, "logical_code": "B39", "course": "A",
         "origin_world": XYZ(ft(0), ft(0), 0.0), "rotation_deg": 0.0,
         "mirrored": False, "placement_reason": "preenchimento"},
        {"wall_idx": 0, "logical_code": "B39", "course": "B",
         "origin_world": XYZ(ft(39), ft(0), 0.0), "rotation_deg": 0.0,
         "mirrored": False, "placement_reason": "preenchimento"},
    ]
    target_doc = revit_stubs._StubDoc()
    level = revit_stubs._Inert()

    result = m.create_building_blocks(
        target_doc, candidates, catalog, base_z_abs=0.0, selected_level=level, num_courses=2,
    )

    assert result["created_count"] == 2, result
    assert not result["failures"], result["failures"]
    assert len(result["created_instances"]) == 2
    ids = [item["id"].IntegerValue for item in result["created_instances"]]
    assert len(set(ids)) == 2, "cada chamada ao stub tem que devolver um Id REAL diferente"
    assert catalog["B39"]["symbol"].IsActive is True, (
        "create_building_blocks precisa ativar o FamilySymbol antes de criar"
    )


@case
def test_create_building_blocks_um_candidato_com_erro_nao_derruba_os_outros():
    """Regra ja documentada em create_building_blocks (try/except por
    candidato): um bloco que falha na criacao real (NewFamilyInstance
    lancando excecao) precisa aparecer em `failures` com parede/fiada/
    tipo/posicao/excecao real - e NUNCA impedir os demais candidatos,
    validos, de serem criados normalmente na mesma chamada."""
    catalog = {"B39": _real_catalog_entry("B39", height_cm=19.0)}
    candidates = [
        {"wall_idx": 0, "logical_code": "B39", "course": "A",
         "origin_world": XYZ(ft(0), ft(0), 0.0), "rotation_deg": 0.0,
         "mirrored": False, "placement_reason": "preenchimento"},
        {"wall_idx": 0, "logical_code": "B39", "course": "A",
         "origin_world": XYZ(ft(39), ft(0), 0.0), "rotation_deg": 0.0,
         "mirrored": False, "placement_reason": "preenchimento"},
    ]
    target_doc = revit_stubs._StubDoc()

    call_count = [0]
    real_new_instance = target_doc.Create.NewFamilyInstance

    def _flaky_new_instance(point, symbol, level, structural_type):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("erro real simulado do Revit (ex.: geometria invalida)")
        return real_new_instance(point, symbol, level, structural_type)

    target_doc.Create.NewFamilyInstance = _flaky_new_instance

    result = m.create_building_blocks(
        target_doc, candidates, catalog, base_z_abs=0.0, selected_level=revit_stubs._Inert(),
        num_courses=1,
    )

    assert result["created_count"] == 1, result
    assert len(result["failures"]) == 1, result["failures"]
    assert "erro real simulado" in result["failures"][0]
    assert len(result["created_instances"]) == 1


@case
def test_refresh_geometry_from_document_enxerga_ajuste_manual_feito_direto_no_revit():
    """Regressao 2026-08-26 (pedido explicito do usuario): um ajuste
    manual feito DIRETO no Revit (arrastando a ponta de uma parede, fora
    do botao "Ajustar Erros" - o UNICO lugar que atualizava esta geometria
    antes) tem que ser enxergado na proxima acao (analyze/solve/create) -
    a geometria ATUAL do documento e' sempre a fonte da verdade, nunca o
    snapshot velho capturado na Etapa 1. `_refresh_geometry_from_document`
    e' chamado no inicio de Execute() para "analyze"/"solve"/"create" -
    aqui ele e' testado isoladamente, releindo uma parede que "cresceu" de
    100cm para 150cm fora do script."""
    handler = m._PostCreationEventHandler()
    old_axis = seg(0, 0, 100, 0)
    handler.walls_to_create = [(old_axis, ft(14.0), (False, False))]
    wall_id = 501
    handler.created_walls_by_axis = {0: [(wall_id, "cad")]}
    handler.wall_segment_geometry = {
        0: [{"element_id": wall_id, "seg_origin": "cad", "t_a": 0.0, "t_b": ft(100.0)}]
    }

    # usuario esticou a parede manualmente no proprio Revit: 100cm -> 150cm.
    new_curve = seg(0, 0, 150, 0)
    fake_doc = _FakeDoc({wall_id: _FakeWall(new_curve)})

    handler._refresh_geometry_from_document(fake_doc)

    new_centerline, thickness_ft, _locks = handler.walls_to_create[0]
    new_len_cm = to_cm(new_centerline.GetEndPoint(0).DistanceTo(new_centerline.GetEndPoint(1)))
    assert abs(new_len_cm - 150.0) < 1e-6, (
        "walls_to_create[0] continua com o comprimento ANTIGO (100cm) - "
        "o ajuste manual nao foi enxergado: {}".format(new_len_cm)
    )
    seg_info = handler.wall_segment_geometry[0][0]
    seg_len_cm = to_cm(seg_info["t_b"] - seg_info["t_a"])
    assert abs(seg_len_cm - 150.0) < 1e-6, seg_info


@case
def test_refresh_geometry_from_document_ignora_eixo_com_wall_apagada():
    """Um eixo cuja Wall real foi apagada/invalidada fora do script
    (GetElement devolve None) e' deixado como estava - nunca derruba o
    refresh dos DEMAIS eixos nem lanca excecao (mesma regra ja' aplicada
    por _classify_wall_axis_segments para o caso "fora de escopo")."""
    handler = m._PostCreationEventHandler()
    axis_ok = seg(0, 0, 100, 0)
    axis_deleted = seg(0, 200, 100, 200)
    handler.walls_to_create = [
        (axis_ok, ft(14.0), (False, False)),
        (axis_deleted, ft(14.0), (False, False)),
    ]
    wall_id_ok = 601
    wall_id_deleted = 602
    handler.created_walls_by_axis = {
        0: [(wall_id_ok, "cad")],
        1: [(wall_id_deleted, "cad")],
    }
    handler.wall_segment_geometry = {
        0: [{"element_id": wall_id_ok, "seg_origin": "cad", "t_a": 0.0, "t_b": ft(100.0)}],
        1: [{"element_id": wall_id_deleted, "seg_origin": "cad", "t_a": 0.0, "t_b": ft(100.0)}],
    }
    new_curve_ok = seg(0, 0, 130, 0)
    # so' o eixo 0 tem Wall real no doc - o eixo 1 "sumiu" (apagado fora do script).
    fake_doc = _FakeDoc({wall_id_ok: _FakeWall(new_curve_ok)})

    handler._refresh_geometry_from_document(fake_doc)  # nunca lanca excecao

    updated_centerline, _thk, _locks = handler.walls_to_create[0]
    assert abs(to_cm(updated_centerline.Length) - 130.0) < 1e-6
    unchanged_centerline, _thk2, _locks2 = handler.walls_to_create[1]
    assert abs(to_cm(unchanged_centerline.Length) - 100.0) < 1e-6, (
        "eixo com Wall apagada deveria manter a geometria antiga, nao quebrar nem mudar"
    )


# ==========================================
# FLUXO "UTILIZAR PAREDES EXISTENTES" (pedido explicito do usuario,
# 2026-08-26 - opcao "Pular criacao/verificacao inicial das paredes").
# ==========================================

class _FakeParamForSelection(object):
    def __init__(self, value):
        self._value = value

    def AsDouble(self):
        return self._value


_fake_selection_next_id = [7000]


def _next_fake_selection_id():
    _fake_selection_next_id[0] += 1
    return revit_stubs.ElementId(_fake_selection_next_id[0])


class _FakeLevelForSelection(m.Level):
    def __init__(self, name, elevation_ft):
        self.Name = name
        self.Elevation = elevation_ft
        self.Id = _next_fake_selection_id()


class _FakeExistingWall(m.Wall):
    def __init__(self, curve, width_ft, level_id, height_ft=None, bbox_height_ft=None):
        self.Location = m.LocationCurve()
        self.Location.Curve = curve
        self.Width = width_ft
        self.Id = _next_fake_selection_id()
        self.LevelId = level_id
        self._height_ft = height_ft
        self._bbox_height_ft = bbox_height_ft

    def get_Parameter(self, param_id):
        if self._height_ft is None:
            return None
        return _FakeParamForSelection(self._height_ft)

    def get_BoundingBox(self, view):
        if self._bbox_height_ft is None:
            return None
        box = revit_stubs._Inert()
        box.Min = XYZ(0.0, 0.0, 0.0)
        box.Max = XYZ(0.0, 0.0, self._bbox_height_ft)
        return box


class _FakeSelectionDoc(object):
    def __init__(self, elements):
        self._elements = elements

    def GetElement(self, element_id):
        return self._elements.get(element_id)


class _FakeSelectionRef(object):
    def __init__(self, element_id):
        self.ElementId = element_id


class _FakeSelectionForPick(object):
    def __init__(self, refs):
        self._refs = refs

    def PickObjects(self, obj_type, prompt):
        return self._refs


@case
def test_select_existing_walls_for_modulation_monta_estrutura_a_partir_da_selecao():
    """_select_existing_walls_for_modulation (Etapa 1 "pular criacao" -
    usar paredes ja' modeladas): monta walls_to_create/created_walls_by_axis
    a partir da geometria REAL das Wall selecionadas (Location.Curve/Width,
    lidas agora, nunca um snapshot antigo), descarta Wall menor que
    MIN_SEGMENT_LENGTH_FT e qualquer elemento que nao seja Wall, escolhe o
    Nivel MAIS COMUM entre as selecionadas e usa a altura MAXIMA entre elas
    (caindo para bounding box quando WALL_USER_HEIGHT_PARAM nao existir)."""
    level_a = _FakeLevelForSelection("Nivel 1", ft(0.0))
    level_b = _FakeLevelForSelection("Nivel 2", ft(300.0))
    curve1 = seg(0, 0, 100, 0)
    curve2 = seg(0, 0, 200, 0)
    curve_tiny = seg(0, 0, 0.5, 0)
    wall1 = _FakeExistingWall(curve1, ft(14.0), level_a.Id, height_ft=ft(280.0))
    wall2 = _FakeExistingWall(curve2, ft(19.0), level_a.Id, height_ft=None, bbox_height_ft=ft(260.0))
    wall3 = _FakeExistingWall(curve1, ft(14.0), level_b.Id, height_ft=ft(300.0))
    wall_tiny = _FakeExistingWall(curve_tiny, ft(14.0), level_a.Id, height_ft=ft(280.0))

    elements = {
        wall1.Id: wall1, wall2.Id: wall2, wall3.Id: wall3, wall_tiny.Id: wall_tiny,
        level_a.Id: level_a, level_b.Id: level_b,
    }
    fake_doc = _FakeSelectionDoc(elements)
    refs = [
        _FakeSelectionRef(wall1.Id), _FakeSelectionRef(wall2.Id),
        _FakeSelectionRef(wall3.Id), _FakeSelectionRef(wall_tiny.Id),
        _FakeSelectionRef(revit_stubs.ElementId(999999)),  # nao resolve para nenhum elemento
    ]
    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Selection = _FakeSelectionForPick(refs)

    original_doc, original_uidoc = m.doc, m.uidoc
    m.doc, m.uidoc = fake_doc, fake_uidoc
    try:
        walls_to_create, created_walls_by_axis, wall_ids, selected_level, wall_height_ft, skipped_count = (
            m._select_existing_walls_for_modulation()
        )
    finally:
        m.doc, m.uidoc = original_doc, original_uidoc

    assert len(walls_to_create) == 3, walls_to_create
    assert wall_ids == [wall1.Id, wall2.Id, wall3.Id]
    assert created_walls_by_axis == {
        0: [(wall1.Id, "cad")], 1: [(wall2.Id, "cad")], 2: [(wall3.Id, "cad")],
    }
    assert selected_level is level_a, "nivel 1 tem 2 votos (wall1/wall2) contra 1 (wall3)"
    assert abs(to_cm(wall_height_ft) - 300.0) < 1e-6, (
        "altura devolvida deveria ser a MAXIMA entre as paredes (wall3, 300cm)"
    )
    assert walls_to_create[1][1] == ft(19.0), "espessura de cada eixo vem de Wall.Width"
    assert skipped_count == 2, "wall_tiny (curta demais) + ref que nao resolve para elemento"


@case
def test_select_existing_walls_for_modulation_cancelada_devolve_none():
    """ESC durante a selecao (PickObjects lanca excecao) devolve
    (None, None, None, None, None, 0) - nunca propaga a excecao."""
    class _CanceledSelection(object):
        def PickObjects(self, obj_type, prompt):
            raise Exception("selecao cancelada pelo usuario")

    fake_uidoc = revit_stubs._Inert()
    fake_uidoc.Selection = _CanceledSelection()
    original_uidoc = m.uidoc
    m.uidoc = fake_uidoc
    try:
        result = m._select_existing_walls_for_modulation()
    finally:
        m.uidoc = original_uidoc
    assert result == (None, None, None, None, None, 0)


@case
def test_ask_wall_source_mode_despacha_conforme_a_escolha():
    """_ask_wall_source_mode (primeira tela do script, Etapa 1 -
    "Preparacao das paredes"): despacha para "existing", "cad" ou None
    conforme o result da _WallSourceModeForm."""

    class _FakeForm(object):
        def __init__(self_inner):
            self_inner.result = None
        def ShowDialog(self_inner):
            pass  # preenchido pelo chamador via _patch_result abaixo

    original_class = m._WallSourceModeForm
    try:
        def _make_form(result_value):
            class _F(_FakeForm):
                def ShowDialog(self_inner):
                    self_inner.result = result_value
            return _F

        m._WallSourceModeForm = _make_form("existing")
        assert m._ask_wall_source_mode() == "existing"

        m._WallSourceModeForm = _make_form("cad")
        assert m._ask_wall_source_mode() == "cad"

        m._WallSourceModeForm = _make_form(None)
        assert m._ask_wall_source_mode() is None
    finally:
        m._WallSourceModeForm = original_class


# ==========================================
# CACHE DE solve_result/create_result POR CONJUNTO DE PAREDES (pedido
# explicito do usuario, 2026-08-27: fechar a janela de "Lancar Blocos"
# ANTES de clicar em "criar" nao pode obrigar a recalcular o solver do
# zero, ao reabrir sobre o MESMO conjunto de paredes).
# ==========================================

@case
def test_wall_ids_signature_e_estavel_e_ignora_ordem():
    """_wall_ids_signature e' a chave do cache - precisa ser a MESMA
    independente da ordem de selecao, e None para conjunto vazio/invalido
    (nunca bate por acidente com uma entrada real do cache)."""
    ids_a = [revit_stubs.ElementId(3), revit_stubs.ElementId(1), revit_stubs.ElementId(2)]
    ids_b = [revit_stubs.ElementId(1), revit_stubs.ElementId(2), revit_stubs.ElementId(3)]
    assert m._wall_ids_signature(ids_a) == m._wall_ids_signature(ids_b)
    assert m._wall_ids_signature([]) is None
    assert m._wall_ids_signature(None) is None


@case
def test_save_modulation_state_cache_grava_so_quando_ha_candidatos():
    """_save_modulation_state_cache (chamado no fim de _execute_solve/
    _execute_create) so' grava em _LAST_MODULATION_STATE quando o solve
    de fato calculou algum candidato - nunca sobrescreve com um resultado
    vazio (ex.: erro de altura de fiada), e a chave e' a assinatura de
    created_wall_ids_all."""
    handler = m._PostCreationEventHandler()
    wall_ids = [revit_stubs.ElementId(501), revit_stubs.ElementId(502)]
    handler.created_wall_ids_all = wall_ids
    sig = m._wall_ids_signature(wall_ids)
    m._LAST_MODULATION_STATE.pop(sig, None)
    try:
        # solve_result vazio (sem candidatos) - nao deve gravar nada.
        handler.solve_result = {"candidates": [], "num_courses": 0}
        handler.create_result = None
        handler._save_modulation_state_cache()
        assert sig not in m._LAST_MODULATION_STATE

        # agora com candidatos de verdade - grava solve_result E o
        # create_result atual (mesmo que ainda None nesse ponto).
        handler.solve_result = {"candidates": [{"wall_idx": 0, "logical_code": "B39"}]}
        handler._save_modulation_state_cache()
        assert sig in m._LAST_MODULATION_STATE
        assert m._LAST_MODULATION_STATE[sig]["solve_result"] is handler.solve_result
        assert m._LAST_MODULATION_STATE[sig]["create_result"] is None

        # depois de criar de verdade, o cache tambem passa a guardar o
        # create_result correspondente.
        handler.create_result = {"created_count": 2, "created_instances": []}
        handler._save_modulation_state_cache()
        assert m._LAST_MODULATION_STATE[sig]["create_result"] is handler.create_result
    finally:
        m._LAST_MODULATION_STATE.pop(sig, None)


@case
def test_show_post_creation_window_reaproveita_resultado_anterior():
    """_show_post_creation_window, quando recebe initial_solve_result/
    initial_create_result (fluxo "utilizar paredes existentes" reabrindo
    sobre o MESMO conjunto de paredes - ver _run_stage2_existing_walls),
    pre-popula o handler e atualiza a janela pelo MESMO caminho de um
    solve/create de verdade (_on_solve_done/_on_create_done) - o botao
    'Lancar Blocos - criar' fica habilitado e o status reflete os blocos
    ja' criados, sem exigir clicar em 'calcular' de novo."""
    solve_result = {
        "candidates": [{"wall_idx": 0, "logical_code": "B39", "course": "A"}],
        "collisions": [], "door_void_violations": [], "wall_bond_audits": {},
        "num_courses": 1, "intersection_failures": [], "jamb_exceptions": [],
        "non_modular": [], "per_wall": [], "validations": [],
    }
    create_result = {
        "created_count": 1, "failures": [], "created_instances": [],
        "course_height_ft": ft(20.0), "course_height_error": None,
        "skipped_wall_count": 0, "skipped_wall_idxs": [],
        "reproved_wall_count": 0, "reproved_wall_idxs": [],
        "colliding_instance_count": 0,
    }
    report_dict = {"kpis": [], "highlights": [], "issues": [], "log": "", "log_path": None}

    original_active = list(m._ACTIVE_MODELESS_WINDOWS)
    try:
        m._show_post_creation_window(
            report_dict, [(seg(0, 0, 100, 0), ft(14.0), (False, False))], [[]], {0: []},
            [], [], [], {}, revit_stubs._Inert(), 0.0, ft(280.0), [],
            catalog=CATALOG, catalog_missing=[],
            initial_solve_result=solve_result, initial_create_result=create_result,
        )
        assert len(m._ACTIVE_MODELESS_WINDOWS) == len(original_active) + 1
        window, _external_event, handler = m._ACTIVE_MODELESS_WINDOWS[-1]
        assert handler.solve_result is solve_result
        assert handler.create_result is create_result
        assert window._create_button.Enabled is True
        assert "1 bloco(s) criado(s)" in window._create_status.Text
    finally:
        # limpeza - nunca deixar uma janela falsa "ativa" contaminando
        # outros testes que iteram _ACTIVE_MODELESS_WINDOWS.
        del m._ACTIVE_MODELESS_WINDOWS[len(original_active):]
