# -*- coding: utf-8 -*-
"""Preview de modulacao POR PAREDE ISOLADA, usando a aritmetica real e
testada de `core/engine/modulation_math.py` (via engine_bridge) - o mesmo
`pack_pier_with_blocks`/`wall_length_closes_with_blocks_cm` que o motor
real usa.

LIMITACAO HONESTA: isto NAO e' o solver completo. O solver de verdade
(`solve_l_corner`/`solve_t_intersection`/`solve_all_wall_fill` etc., em
wall_modeling.py) considera amarracao entre paredes, aberturas, prisma
entre fiadas e ajuste de menor impacto - nada disso foi extraido ainda
(ver ARQUITETURA_INTERATIVA.md, "Extracao fisica do motor - iniciada, nao
completa"). Este preview trata cada parede como um pilarete isolado
(junta 1cm nas duas pontas), so' para dar uma resposta visual imediata no
editor externo enquanto a extracao do solver de encontros/aberturas nao
avança. Uma parede marcada aqui como "fecha" pode ainda vir a mudar de
peca quando entrar em contato com uma amarracao real - isso e' esperado,
nao um bug."""

from engine_bridge import (
    pack_pier_with_blocks, pier_closes_with_blocks_cm,
    wall_length_closes_with_blocks_cm, nearest_wall_lengths_cm,
    suggested_block_length_cm, PIER_BOUNDARY_JOINT_COMBINATIONS_CM,
    _pier_remaining_cm,
)


def preview_wall_blocks(length_cm):
    """Dict com o preview de UMA parede isolada, comprimento `length_cm`:
        {"closes": bool, "blocks": [39, 39, 19, ...] ou None,
         "boundary_joints_cm": (lead, trail) ou None,
         "suggested_length_cm": float, "delta_cm": float}

    Sem contexto de encontro/abertura, nao da' para saber de antemao QUAL
    das 4 combinacoes de junta de contorno (parede/parede=1, parede/
    abertura=0, nas duas pontas) esta parede vai realmente ter quando
    entrar no solver de verdade. Por isso testamos as 4 (mesma ordem de
    `wall_length_closes_with_blocks_cm`) e usamos a PRIMEIRA que fecha -
    reportando tambem qual foi, para o editor poder mostrar a suposicao
    ao usuario em vez de esconde-la."""
    length_cm_rounded = round(length_cm)
    blocks = None
    boundary_joints_cm = None
    for lead, trail in PIER_BOUNDARY_JOINT_COMBINATIONS_CM:
        if not pier_closes_with_blocks_cm(length_cm, lead, trail):
            continue
        remaining_cm = _pier_remaining_cm(length_cm_rounded, lead, trail)
        packed, leftover = pack_pier_with_blocks(remaining_cm)
        if packed is not None and abs(leftover) < 1e-6:
            blocks = packed
            boundary_joints_cm = (lead, trail)
            break

    return {
        "closes": blocks is not None,
        "blocks": blocks,
        "boundary_joints_cm": boundary_joints_cm,
        "suggested_length_cm": suggested_block_length_cm(length_cm),
        "delta_cm": suggested_block_length_cm(length_cm) - length_cm,
    }


def preview_walls(walls):
    """Aplica `preview_wall_blocks` a cada parede de `walls` (lista no
    formato de `wall_pairing.pair_walls_from_segments`) e devolve a MESMA
    lista, com uma chave `"modulation"` adicionada em cada dict."""
    result = []
    for wall in walls:
        preview = preview_wall_blocks(wall["length_cm"])
        wall_with_preview = dict(wall)
        wall_with_preview["modulation"] = preview
        result.append(wall_with_preview)
    return result
