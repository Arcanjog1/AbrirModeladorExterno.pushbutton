# -*- coding: utf-8 -*-
"""Motor de PROCESSAMENTO/MODULACAO parede-a-parede (encontros L/T/X, jambs
de abertura, preenchimento comum/pilaretes, validacao final de cada parede,
o laco principal `process_walls_one_by_one` e o deslocamento de grupo de
paredes conectadas da ETAPA 3C) - EXTRAIDO VERBATIM de `core/wall_modeling.py`
(linhas ~2793-7017 e ~9862-10739 na versao de origem, imediatamente antes de
`apply_wall_group_shift`), mesmo padrao ja' usado para
`core/engine/wall_pairing.py` (pareamento de paredes/grafo de encontros).

Nenhuma formula mudou - so' o arquivo onde moram. `wall_modeling.py` importa
tudo daqui via `from core.engine.wall_stepper import *` nos dois pontos de
onde estes blocos sairam.

Modulo PURO quanto a UI/Revit-document: nao abre Transaction, nao le' `doc`,
nao chama forms.*, nao usa FilteredElementCollector/GetElement - so' os
tipos geometricos XYZ/Line (reais no Revit, ou o shim leve usado pelos
testes/pelo visualizador externo) e as funcoes/constantes puras de
`core.engine.geometry`, `core.engine.tolerances`, `core.engine.modulation_math`
e `core.engine.wall_pairing`. E' isso que permite uma ferramenta externa (o
visualizador 3D, fora do Revit) rodar o MESMO laco de correcao/modulacao que
o botao real usa, sem duplicar nenhuma regra.

UMA EXCECAO PONTUAL, ja' existente no comportamento ORIGINAL (nao introduzida
por esta extracao): `find_wall_group_shift_fixes` pode pausar a UI do
pyRevit chamando `Application.DoEvents()` (System.Windows.Forms) quando o
CHAMADOR passa `should_pause_cb`/`should_pause_cb() == True` - uso real
so' dentro do pyRevit, onde o CLR/System.Windows.Forms sempre esta'
disponivel. Antes, `Application` vinha resolvido por `wall_modeling.py` ja'
ter importado `System.Windows.Forms` mais abaixo no MESMO modulo (nomes de
modulo sao resolvidos so' na hora da CHAMADA, nao na hora da definicao); como
a funcao agora mora neste arquivo, que precisa continuar importavel FORA do
Revit (sem CLR nenhum) para o visualizador externo, o import de
`System.Windows.Forms` foi tornado PREGUICOSO (so' acontece se
`should_pause_cb` for de fato usado) - ver `_pump_ui_events_if_needed`
abaixo. Nenhum teste existente exercita `should_pause_cb` (grep confirmado
antes desta mudanca), e o caminho sem pausa (o unico usado pelo
visualizador externo e por todos os testes) nunca toca nesse import.
"""

import math

from Autodesk.Revit.DB import XYZ, Line

from core.engine.tolerances import (  # noqa: F401
    FEET_PER_METER, MIN_SEGMENT_LENGTH_FT, JUNCTION_FACE_SEARCH_FT,
)
from core.engine.geometry import *  # noqa: F401,F403
from core.engine.wall_pairing import *  # noqa: F401,F403
from core.engine.modulation_math import *  # noqa: F401,F403

# `__all__` inclui os nomes com underscore de proposito - `import *` os
# ignoraria por padrao, e varias funcoes "privadas" daqui sao chamadas por
# nome solto de FORA deste arquivo, dentro de wall_modeling.py (mesmo motivo/
# padrao de core/engine/wall_pairing.py).
__all__ = [
    # ---- ETAPA 4 - encontros L/T/X ----
    "_wall_axis_and_length", "_wall_end_and_dir_near_point", "_perp_dir",
    "_block_smaller_cell", "_block_more_central_cell", "_block_smaller_cell_sign",
    "_node_contact_point_for_wall", "_asymmetric_bond_origin_and_axis",
    "_make_block_candidate", "_obb_2d", "_obb_corners", "_obb_min_overlap",
    "_obb_overlap", "_candidate_obb", "_cell_obb",
    "_l_corner_wall_pair", "_wall_reserved_range_ft", "_corner_wall_room_ft",
    "solve_l_corner", "T_INTERSECTION_B54_HALF_ROOM_FT", "CORNER_B34_ROOM_FT",
    "_t_of_point_on_wall", "_wall_junction_ts_ft", "_corner_bond_blocked_by_other_node",
    "_room_at_t_on_wall", "_t_intersection_room_assessment", "_t_intersection_room_ok",
    "CORNER_SINGLE_ELEMENT_CODES", "_corner_single_element_candidate",
    "solve_t_intersection", "X_INTERSECTION_B54_HALF_ROOM_FT",
    "X_INTERSECTION_DEGRADED_CODES", "_x_intersection_wall_room_ft",
    "_x_intersection_centered_candidate", "solve_x_intersection",
    "solve_all_intersections", "validate_l_corner", "validate_t_intersection",
    "validate_x_intersection", "collisions_between",
    "DOOR_NO_SILL_MAX_SILL_CM", "DOOR_NO_SILL_MAX_SILL_FT", "_is_door_without_sill",
    "_door_void_obb", "find_door_void_violations", "candidates_near_wall",
    "validate_same_course_collision",
    # ---- jambs de abertura + layout de pilarete ----
    "describe_block_candidate", "_format_world_point_cm",
    "describe_block_candidate_oneline", "_is_small_joint_exception_code",
    "_opening_side_pier_length_ft", "_opening_jamb_point_and_dir",
    "_pier_first_block_candidates", "_nearest_cell_to_point",
    "_jamb_build_course_variants", "solve_opening_jamb", "solve_all_opening_jambs",
    "describe_opening_jamb_exception", "_pier_codes_by_len_desc",
    "_greedy_fill_blocks", "_greedy_fill_blocks_any_first", "_exact_fill_blocks",
    "_merge_adjacent_compensator_pairs",
    "_pier_remaining_snapped_cm", "_pier_ordered_layout",
    "_layout_internal_joint_positions_cm", "_count_joint_coincidences_cm",
    "_layout_min_joint_stagger_cm", "MIN_JOINT_STAGGER_TARGET_CM",
    "OPENING_ALIGNED_EXEMPT_CODES", "_layout_compensator_run_excess",
    "_block_void_offsets_cm", "_layout_void_positions_cm", "_count_void_alignment_cm",
    "_half_block_leading_layout", "_pier_forced_bypass_layouts",
    "_pier_layout_avoiding_joints", "_place_pier_layout",
    "_candidate_extent_on_wall_axis", "_node_candidates_by_index",
    "_node_involved_wall_ends", "_index_node_candidates_by_wall_end",
    "_candidate_t_range_on_wall", "_node_default_reservation_cm",
    "_wall_end_default_start_cm", "_node_offset_along_wall_cm",
    "_midspan_node_wall_ids", "_index_node_candidates_midspan",
    "_merge_intervals_cm", "solve_wall_free_fill",
    # ---- ordem de processamento / validacao / pipeline principal ----
    "WALL_ORIENTATION_TOLERANCE", "WALL_ALIGNMENT_TOLERANCE_FT",
    "WALL_NO_GROWTH_TOLERANCE_CM", "WALL_COLLISION_REACH_CM",
    "classify_wall_orientation", "_cluster_values_ft", "order_walls_for_processing",
    "openings_for_wall", "_copy_openings_per_wall", "_wall_opening_intervals_cm",
    "_find_consecutive_compensators", "validate_wall_modulation",
    "_apply_axis_plan_in_memory", "_rebase_node_indexes_for_wall",
    "process_walls_one_by_one", "solve_all_wall_fill", "solve_building_blocks",
    # ---- ETAPA 3C - deslocamento de grupo de paredes conectadas ----
    "WALL_GROUP_SHIFT_MAX_CM", "WALL_GROUP_SHIFT_VERIFY_BUDGET",
    "WALL_GROUP_SHIFT_PER_WALL_BUDGET", "ETAPA_3C_PARTIAL_RESOLVE_ENABLED",
    "ISOLATED_WALL_LENGTH_ADJUST_MAX_CM", "_pushed_corner_point",
    "_corner_reference_wall", "_wall_group_shift_targets",
    "_wall_has_third_party_midspan_contact", "_wall_shift_is_topologically_safe",
    "_shift_wall_line_perpendicular", "_extend_wall_line_axial",
    "_recompute_neighbor_line_after_shift", "_candidate_walls_to_shift_for",
    "_wall_ok_map", "_wall_node_neighbors", "_expand_dirty_wall_idxs",
    "_group_shift_trial_improves", "_group_shift_trial_score",
    "_build_group_shift_plan", "_build_isolated_extend_plan",
    "_pump_ui_events_if_needed", "find_wall_group_shift_fixes",
    "_cm_to_ft", "_ft_to_cm", "CELL_ALIGNMENT_TOLERANCE_CM",
    "CELL_ALIGNMENT_TOLERANCE_FT", "BOND_PERPENDICULAR_DOT_TOLERANCE",
    "BOND_COLLISION_EPS_CM", "BOND_COLLISION_EPS_FT",
    # ---- constantes internas do bloco de jambs/preenchimento, tambem
    # consultadas por nome solto de FORA deste arquivo (audit_wall_bond_
    # quality e familia, que continuam em wall_modeling.py) ----
    "OPENING_JAMB_MIN_PIER_CM", "OPENING_JAMB_BLOCK_CODES",
    "JOINT_ALIGNMENT_EXCEPTION_LENGTHS_CM", "HALF_BLOCK_CODE",
    "MID_WALL_BLOCK_CODE", "COMMON_FILL_BLOCK_CODES",
    "MAX_COMPENSATORS_PER_TRECHO", "VERTICAL_JOINT_STAGGER_TOLERANCE_CM",
    "VOID_ALIGNMENT_TOLERANCE_CM", "_axis_free_end_sides",
]


# Intervalo de espera (segundos) quando _pump_ui_events_if_needed roda numa
# thread de fundo (ver docstring dela).
PAUSE_POLL_INTERVAL_S = 0.05


def _pump_ui_events_if_needed():
    """DoEvents() do WinForms QUANDO chamado na thread principal da UI, ou
    um `time.sleep` curto quando chamado de uma thread de fundo - os dois
    imports sao SOB DEMANDA (ver docstring do modulo): so' e' alcancada
    quando o chamador de find_wall_group_shift_fixes passa should_pause_cb -
    uso real e' so' dentro do pyRevit, onde System.Windows.Forms/System.
    Threading sempre estao disponiveis. Mantem este arquivo importavel fora
    do Revit (visualizador externo/testes) sem exigir CLR nenhum no caminho
    comum (sem pausa).

    MUDANCA 2 do plano de arquitetura "solver em memoria/aplicacao unica"
    (2026-08-26): `analyze_created_walls_for_errors` (wall_modeling.py) pode
    agora rodar `process_walls_one_by_one`/`find_wall_group_shift_fixes`
    numa `System.Threading.Thread` de VERDADE (nao mais so' dentro da thread
    de UI do Revit) quando o chamador configura `ui_invoke_cb` - ver
    `_PostCreationEventHandler._execute_analyze`. Numa thread de fundo (
    `Thread.CurrentThread.IsBackground`) NAO ha' loop de mensagens do
    Windows para bombear - `Application.DoEvents()` so' faz sentido/e'
    seguro na thread de UI de verdade; `time.sleep` e' o equivalente
    correto/seguro em qualquer thread."""
    from System.Threading import Thread
    if Thread.CurrentThread.IsBackground:
        import time
        time.sleep(PAUSE_POLL_INTERVAL_S)
        return
    from System.Windows.Forms import Application
    Application.DoEvents()


def _axis_free_end_sides(wall_idx, wall_end_to_node, nodes=None):
    """Devolve a lista de extremidades (0 e/ou 1) de `wall_idx` classificadas
    como FREE_END pelo grafo de paredes (ver build_wall_graph) - pontas que
    nao encostam em nenhuma outra parede, portanto seguras de esticar/
    encurtar sem perturbar nenhum encontro L/T/X vizinho.

    MOVIDA de wall_modeling.py (ficava logo antes da ETAPA 3B de ajuste de
    abertura, que continua la') porque find_wall_group_shift_fixes (aqui)
    tambem depende dela - compartilhada pelos dois lados, exatamente como
    outros helpers puros deste arquivo (ver cabecalho do modulo).

    ATENCAO (bug real, corrigido 2026-08-20): `wall_end_to_node` mapeia
    (wall_idx, end_index) -> INDICE do no' em `nodes`, NAO o dict do no' -
    tratar o valor como dict lancava `'int' object has no attribute 'get'`
    em ~60 dos 128 eixos da planta de teste, o que abortava
    analyze_created_walls_for_errors inteiro (a excecao propagava e o log
    simplesmente parava, dando a falsa impressao de "travado/lento").

    `wall_end_to_node` e/ou `nodes` podem ser None (chamador antigo/teste
    sem grafo): devolve lista vazia (equivale a "nenhuma ponta livre
    disponivel"), nunca lanca excecao."""
    if not wall_end_to_node or not nodes:
        return []
    sides = []
    for end_index in (0, 1):
        node_index = wall_end_to_node.get((wall_idx, end_index))
        if node_index is None:
            continue
        try:
            node = nodes[node_index]
        except (IndexError, TypeError):
            continue
        if isinstance(node, dict) and node.get("kind") == "FREE_END":
            sides.append(end_index)
    return sides

# ==========================================
# ETAPA 4 - ENCONTROS (L, T, X)
#
# Resolve os tres encontros estruturais obrigatorios deste projeto (secoes
# 10/11/12 do prompt de especificacao) como pares de BlockPlacementCandidate
# (secao 18) em DUAS fiadas alternadas - nada e' criado no Revit aqui, e' so'
# o modelo geometrico da solucao (a Etapa 7, solver global, e' quem decide
# como combinar isto com o preenchimento comum; a Etapa 9 e' quem materializa
# FamilyInstance de verdade).
#
# CONVENCAO DE ORIENTACAO - MEDIDA na geometria real das 6 pecas da familia
# deste projeto (via MCP, nao suposta):
#   - a origem local (0,0) de QUALQUER peca desta familia e' o CENTRO
#     GEOMETRICO do bloco (a face superior e' simetrica em X e Y ao redor da
#     origem da instancia em todas as 6 pecas testadas: B39/B34/B54/B19/
#     C09/C04); eixo local X e' o comprimento (39/34/54/19/9/4cm), eixo
#     local Y e' a largura (14cm);
#   - por isso QUALQUER peca desta familia pode ser posicionada so' com
#     (ponto_mundo, direcao_X_mundo): origem_mundo = ponto + direcao *
#     (comprimento/2), sempre que uma das PONTAS da peca precisa encostar em
#     `ponto` (ver _asymmetric_bond_origin_and_axis);
#   - o B34 (amarracao L/T) NAO e' simetrico ao longo de X: das duas
#     celulas, uma e' MENOR (~97cm2 contra ~142cm2 na peca real deste
#     projeto) e fica deslocada para um dos lados - e' o "vao menor" que as
#     secoes 10/11 pedem virado para o encontro;
#   - o B54 (amarracao T/X) E' simetrico: a celula CENTRAL fica exatamente
#     em local (0,0), o que permite usar o proprio ponto do no' como origem
#     do bloco (a celula central cai automaticamente ali).
#
# Estas duas propriedades sao LIDAS da geometria real a cada chamada (ver
# _block_smaller_cell/_block_more_central_cell), nunca hardcoded - se a
# familia do projeto for reautorada (posicao das celulas mudar), o solver se
# adapta sozinho, conforme a secao 37 do prompt exige.
# ==========================================

def _cm_to_ft(value_cm):
    return value_cm / 100.0 * FEET_PER_METER


def _ft_to_cm(value_ft):
    return value_ft / FEET_PER_METER * 100.0


# Folga (cm) aceita entre a celula "relevante" de uma peca de amarracao e a
# da fiada oposta para ainda contar como "sobreposta/alinhada em projecao"
# (secoes 10/11/12) - cobre folga de junta de argamassa (BLOCK_JOINT_CM) e
# pequenas imprecisoes geometricas, sem aceitar um desalinhamento grande o
# bastante para a amarracao deixar de fazer sentido estrutural.
CELL_ALIGNMENT_TOLERANCE_CM = 1.5
CELL_ALIGNMENT_TOLERANCE_FT = _cm_to_ft(CELL_ALIGNMENT_TOLERANCE_CM)

# Produto escalar de dois vetores UNITARIOS considerado "90 graus o
# suficiente" entre duas pecas de amarracao - mesma escala/raciocinio de
# WALL_GRAPH_PERPENDICULAR_TOLERANCE (secao ETAPA 2 acima).
BOND_PERPENDICULAR_DOT_TOLERANCE = 0.05

# Penetracao MINIMA (cm), alem de ruido de ponto flutuante, para dois
# candidatos da MESMA fiada contarem como COLISAO real (INVALID_OVERLAP,
# secao 19) - uma folga/junta prevista (EXPECTED_MORTAR_GAP) nao deve
# disparar isto; so' overlap solido de verdade.
BOND_COLLISION_EPS_CM = 0.1
BOND_COLLISION_EPS_FT = _cm_to_ft(BOND_COLLISION_EPS_CM)


def _wall_axis_and_length(walls_to_create, wall_idx):
    """(p0, p1, direcao_unit_p0->p1, comprimento_ft, espessura_ft) de
    `wall_idx`, achatado em Z=0 (mesma convencao de _wall_node_arms)."""
    line, thickness_ft, _locks = walls_to_create[wall_idx]
    p0_raw = line.GetEndPoint(0)
    p1_raw = line.GetEndPoint(1)
    p0 = XYZ(p0_raw.X, p0_raw.Y, 0.0)
    p1 = XYZ(p1_raw.X, p1_raw.Y, 0.0)
    vec = p1 - p0
    length = vec.GetLength()
    direction = vec.Normalize() if length > 1e-9 else XYZ(1.0, 0.0, 0.0)
    return p0, p1, direction, length, thickness_ft


def _wall_end_and_dir_near_point(walls_to_create, wall_idx, point):
    """A ponta de `wall_idx` mais proxima de `point` e a direcao unitaria
    que sai DELA em direcao ao INTERIOR da propria parede (a outra ponta).
    Usada tanto para os dois bracos de um L_CORNER quanto para a
    incomingWall de um T_INTERSECTION - qualquer parede cuja ponta encosta
    em `point`, independente do sentido em que foi desenhada (Etapa 2 ja'
    normaliza isso; aqui so' se reusa o mesmo raciocinio)."""
    p0, p1, _dir, length, thickness_ft = _wall_axis_and_length(walls_to_create, wall_idx)
    if p0.DistanceTo(point) <= p1.DistanceTo(point):
        end_point, far_point = p0, p1
    else:
        end_point, far_point = p1, p0
    vec = far_point - end_point
    outward_dir = vec.Normalize() if vec.GetLength() > 1e-9 else XYZ(1.0, 0.0, 0.0)
    return end_point, outward_dir, length, thickness_ft


def _perp_dir(direction):
    """Rotaciona `direction` (XYZ unitario, Z=0) 90 graus no plano XY."""
    return XYZ(-direction.Y, direction.X, 0.0)


def _block_smaller_cell(entry):
    """A celula de MENOR AREA de `entry` (BlockTypeDefinition) - o "vao
    menor" que as secoes 10/11 do prompt pedem virado para o encontro.
    None se a peca tiver menos de 2 celulas (nada para comparar)."""
    cells = entry.get("cells_local") or []
    if len(cells) < 2:
        return None
    return min(cells, key=lambda c: c["size_local"][0] * c["size_local"][1])


def _block_more_central_cell(entry):
    """A celula mais PROXIMA do centro geometrico (local x=0) de `entry` -
    a "celula central" que as secoes 11/12 usam como referencia de
    amarracao no B54. None se a peca nao tiver celulas legiveis."""
    cells = entry.get("cells_local") or []
    if not cells:
        return None
    return min(cells, key=lambda c: abs(c["center_local"][0]))


def _block_smaller_cell_sign(entry):
    """Sinal (−1, 0 ou +1) do local_x da celula menor (ver
    _block_smaller_cell) - diz de qual LADO do bloco (em X local) fica o
    vao menor. 0 quando a peca nao tem celula menor identificavel (peca
    simetrica ou sem celulas) - o chamador deve tratar como "sem lado
    preferencial"."""
    cell = _block_smaller_cell(entry)
    if cell is None:
        return 0
    x = cell["center_local"][0]
    if abs(x) < 1e-6:
        return 0
    return -1 if x < 0 else 1


def _node_contact_point_for_wall(node, wall_idx):
    """Ponto em que uma peca de amarracao ASSIMETRICA (B34) vinda de
    `wall_idx` deve ENCOSTAR neste no'.

    E' a ponta da propria parede (`arm_points`), nao o centro do encontro:
    a ponta ja' foi levada por extend_wall_ends_to_junctions ate' a face
    OPOSTA da parede vizinha, que e' exatamente onde a peca precisa
    comecar para atravessar o quadrado do canto e amarrar. Encostar no
    centro do no' deixaria meia espessura do canto vazia naquela fiada.

    Cai para o ponto do no' quando aquela parede nao tem ponta neste no'
    (encontro em que so' uma das duas paredes termina aqui)."""
    arm_points = node.get("arm_points") or {}
    for end_index in (0, 1):
        point = arm_points.get((wall_idx, end_index))
        if point is not None:
            return point
    return node["point"]


def _asymmetric_bond_origin_and_axis(entry, point, dir_away, small_sign):
    """Posiciona uma peca ASSIMETRICA (B34, ou qualquer peca com um lado de
    celula menor - ver _block_smaller_cell_sign) de forma que a PONTA do
    lado da celula menor encoste em `point`, com o bloco se estendendo ao
    longo de `dir_away` (unitario, Z=0) para dentro da parede.

    O CENTRO da peca fica sempre a meio comprimento de distancia de
    `point` na direcao `dir_away` (e' sempre o centro geometrico do bloco,
    ver cabecalho da secao) - o que muda com `small_sign` e' so' o SENTIDO
    do eixo local X, ou seja, qual ponta fisica da peca fica em `point`.
    Devolve (origem_mundo, direcao_X_mundo)."""
    half_length_ft = _cm_to_ft(entry["length_cm"]) / 2.0
    origin = point + dir_away * half_length_ft
    if small_sign < 0:
        x_dir = dir_away
    else:
        x_dir = dir_away.Negate()
    return origin, x_dir


def _make_block_candidate(logical_code, entry, course, origin, x_dir, placement_reason,
                          node_index=None, wall_idx=None, secondary_wall_idx=None):
    """Monta um BlockPlacementCandidate (secao 18) a partir de uma peca do
    catalogo (`entry`) ja' posicionada (`origin`, `x_dir` - y_dir e'
    derivado por rotacao de 90 graus, ver _perp_dir). Transforma as
    celulas locais do catalogo para coordenadas de MUNDO (cellCentersWorld
    da secao 15)."""
    y_dir = _perp_dir(x_dir)
    cells_world = []
    for cell in entry.get("cells_local") or []:
        cx, cy = cell["center_local"]
        world_point = origin + x_dir * cx + y_dir * cy
        cells_world.append({"point": world_point, "size_local": cell["size_local"]})
    rotation_deg = math.degrees(math.atan2(x_dir.Y, x_dir.X)) % 360.0
    return {
        "logical_code": logical_code,
        "course": course,
        "origin_world": origin,
        "x_dir": x_dir,
        "y_dir": y_dir,
        "length_cm": entry["length_cm"],
        "width_cm": entry["width_cm"],
        "cells_world": cells_world,
        "placement_reason": placement_reason,
        "node_index": node_index,
        "wall_idx": wall_idx,
        "secondary_wall_idx": secondary_wall_idx,
        "rotation_deg": rotation_deg,
    }


# ---- geometria auxiliar: retangulos orientados (OBB) em projecao XY -----
#
# Usada tanto para validar alinhamento de celulas (secoes 10/11/12) quanto
# para colisao entre pecas da mesma fiada (secao 19) - o mesmo teste SAT
# (Separating Axis Theorem) serve para os dois casos, so' o SINAL da
# tolerancia muda (ver _obb_overlap).

def _obb_2d(center, half_x, half_y, x_dir, y_dir):
    return {"center": center, "half_x": half_x, "half_y": half_y, "x_dir": x_dir, "y_dir": y_dir}


def _obb_corners(obb):
    # DESEMPENHO (2026-08-27): os 4 cantos so' dependem dos campos que
    # `_obb_2d` ja' congelou na criacao - o mesmo OBB e' comparado contra
    # dezenas/centenas de outros dentro de `validate_same_course_collision`
    # / `collisions_between`, e recalcular 4 XYZ (2 somas + 2 escalares
    # cada) a cada par era ~60% do custo do SAT. O cache fica no proprio
    # dict do OBB (nunca iterado por ninguem - ver os unicos consumidores,
    # `_obb_min_overlap` e esta funcao) e morre junto com ele.
    cached = obb.get("_corners")
    if cached is not None:
        return cached
    c = obb["center"]
    x_dir = obb["x_dir"]
    y_dir = obb["y_dir"]
    hx = obb["half_x"]
    hy = obb["half_y"]
    corners = [c + x_dir * (sx * hx) + y_dir * (sy * hy)
               for sx in (-1.0, 1.0) for sy in (-1.0, 1.0)]
    obb["_corners"] = corners
    return corners


def _obb_aabb(obb):
    """Caixa alinhada aos eixos (x_min, y_min, x_max, y_max, em ft) que
    envolve `obb` - pre-filtro BARATO e CONSERVADOR: se duas AABB nao se
    tocam, os OBB dentro delas tambem nao se tocam (nunca o contrario), o
    que permite descartar um par sem rodar o SAT completo. Tambem e' a
    chave do indice espacial de `_collision_candidate_pairs`."""
    cached = obb.get("_aabb")
    if cached is not None:
        return cached
    xs, ys = [], []
    for corner in _obb_corners(obb):
        xs.append(corner.X)
        ys.append(corner.Y)
    box = (min(xs), min(ys), max(xs), max(ys))
    obb["_aabb"] = box
    return box


def _obb_min_overlap(obb_a, obb_b):
    """Menor overlap (ft) entre as projecoes de obb_a/obb_b nos 4 eixos
    (SAT: os eixos X/Y locais de cada retangulo, suficiente e exato para
    dois retangulos convexos). POSITIVO significa interpenetracao real
    daquele tanto; ZERO/NEGATIVO significa toque exato ou folga de pelo
    menos esse valor absoluto."""
    axes = [obb_a["x_dir"], obb_a["y_dir"], obb_b["x_dir"], obb_b["y_dir"]]
    corners_a = _obb_corners(obb_a)
    corners_b = _obb_corners(obb_b)
    min_overlap = None
    for axis in axes:
        proj_a = [c.DotProduct(axis) for c in corners_a]
        proj_b = [c.DotProduct(axis) for c in corners_b]
        overlap = min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b))
        if min_overlap is None or overlap < min_overlap:
            min_overlap = overlap
    return min_overlap


def _obb_overlap(obb_a, obb_b, tolerance_ft=0.0):
    """True se os dois OBB se sobrepoem alem de `tolerance_ft`. Tolerancia
    POSITIVA exige uma penetracao MINIMA para contar como sobreposicao (uso:
    colisao - toque/junta pequena nao deve contar); tolerancia NEGATIVA
    aceita uma FOLGA pequena ainda como "sobreposto o suficiente" (uso:
    alinhamento de celulas entre fiadas)."""
    return _obb_min_overlap(obb_a, obb_b) > tolerance_ft


def _candidate_obb(candidate):
    return _obb_2d(
        candidate["origin_world"],
        _cm_to_ft(candidate["length_cm"]) / 2.0,
        _cm_to_ft(candidate["width_cm"]) / 2.0,
        candidate["x_dir"], candidate["y_dir"],
    )


def _cell_obb(cell_world, x_dir, y_dir):
    sx, sy = cell_world["size_local"]
    return _obb_2d(cell_world["point"], sx / 2.0, sy / 2.0, x_dir, y_dir)


# ---- LCornerSolver / TIntersectionSolver / XIntersectionSolver ----------

def _l_corner_wall_pair(node):
    """As duas paredes de um WallNode L_CORNER (ver _classify_wall_node):
    tanto o caso de DUAS pontas no mesmo cluster (arms com 2 entradas)
    quanto o caso de UMA ponta so' encostando no meio/ponta da vizinha
    (arms com 1 entrada + neighbor_wall_idx). (None, None) se nao der para
    identificar as duas."""
    arms = node.get("arms") or []
    if len(arms) == 2:
        return arms[0][0], arms[1][0]
    if len(arms) == 1 and node.get("neighbor_wall_idx") is not None:
        return arms[0][0], node["neighbor_wall_idx"]
    return None, None


def _wall_reserved_range_ft(walls_to_create, nodes, end_to_node, wall_idx, exclude_node_index=None):
    """(t_lo_ft, t_hi_ft) - a faixa REALMENTE livre (ft, ao longo do eixo
    de `wall_idx`) depois de descontar a reserva de amarracao em CADA
    PONTA desta parede (mesma formula de `_wall_end_default_start_cm`, a
    que o preenchimento comum ja' usa) - exceto a reserva do proprio
    `exclude_node_index` (o no' que esta' sendo resolvido agora e ja'
    mede o espaco a partir do seu proprio ponto de contato, nao precisa
    contar a propria reserva de novo).

    Usada pelos room-checks de L/T (`_corner_wall_room_ft`/
    `_t_intersection_room_assessment`) para nao prometer espaco que a
    OUTRA PONTA desta mesma parede tambem precisa: sem isso, dois
    encontros em pontas opostas de uma parede curta podiam cada um "ver"
    espaco livre ate' o fim fisico da parede (a checagem so' olhava
    aberturas e a ponta fisica, nunca o outro encontro) - as duas
    forcavam peca de amarracao cheia (B34/B54), e a soma das duas
    reservas passava do comprimento real da parede. Bug real medido ao
    vivo (2026-08-24): colisoes entre pecas de encontros vizinhos E
    trechos de preenchimento comum com comprimento NEGATIVO (a mesma
    invasao, so' que pega ANTES de lancar peca nenhuma).

    A reserva usada para a OUTRA ponta e' o PIOR CASO
    (CORNER_B34_ROOM_FT, os mesmos 34cm que qualquer amarracao em L ou em
    T degradado exige de um lado), nao a reserva GENERICA e' menor de
    `_node_default_reservation_cm` (so' a metade da espessura da parede,
    pensada para cobrir o CORPO fisico de uma peca ja' escolhida, nao
    para prever quanto espaco ela vai llegar a EXIGIR) - as duas pontas
    de uma mesma parede curta sao resolvidas de forma independente, uma
    sem saber ainda a escolha final da outra, entao supor o minimo
    generico aqui ainda deixava a dupla se prometer espaco demais e
    colidir (medido escrevendo o teste desta correcao: o minimo generico
    nao bastava). Superestimar aqui so' custa uma degradacao a mais que o
    estritamente necessario nalguns casos-limite - nunca uma colisao, que
    e' o que bloqueia a criacao no Revit.

    `nodes`/`end_to_node` ausentes (chamador antigo) devolve o intervalo
    fisico inteiro da parede - comportamento historico, sem essa
    checagem cruzada."""
    _p0, _p1, _dir, length_ft, _t = _wall_axis_and_length(walls_to_create, wall_idx)
    if nodes is None or end_to_node is None:
        return 0.0, length_ft
    lo_ft, hi_ft = 0.0, length_ft
    for end_index in (0, 1):
        node_index = end_to_node.get((wall_idx, end_index))
        if node_index is None or node_index == exclude_node_index:
            continue
        reserve_cm, _joint_cm = _wall_end_default_start_cm(
            nodes, end_to_node, walls_to_create, wall_idx, end_index
        )
        reserve_ft = max(_cm_to_ft(reserve_cm), CORNER_B34_ROOM_FT)
        if end_index == 0:
            lo_ft = max(lo_ft, reserve_ft)
        else:
            hi_ft = min(hi_ft, length_ft - reserve_ft)
    return lo_ft, hi_ft


def _corner_wall_room_ft(walls_to_create, openings_per_wall, wall_idx, contact_point, dir_away,
                         nodes=None, end_to_node=None, exclude_node_index=None):
    """Espaco real (ft) disponivel em `wall_idx` a partir de
    `contact_point`, andando em `dir_away` (para dentro do corpo da
    parede) - mesma medicao de `_room_at_t_on_wall`, so' que a partir de
    um ponto/direcao ja calculados (usado por solve_l_corner e pela
    degradacao de solve_t_intersection). `openings_per_wall=None`
    (chamador antigo) devolve None - "sem restricao conhecida".

    `nodes`/`end_to_node` (opcionais): quando dados, o espaco tambem para
    na reserva da OUTRA PONTA desta mesma parede (ver
    `_wall_reserved_range_ft`), nao so' em abertura/ponta fisica -
    `exclude_node_index` e' o proprio no' sendo resolvido agora."""
    if openings_per_wall is None:
        return None
    _p0, _p1, wall_dir, _len, _thick = _wall_axis_and_length(walls_to_create, wall_idx)
    sign = 1 if dir_away.DotProduct(wall_dir) >= 0 else -1
    t = _t_of_point_on_wall(walls_to_create, wall_idx, contact_point)
    safe_range_ft = _wall_reserved_range_ft(walls_to_create, nodes, end_to_node, wall_idx,
                                            exclude_node_index=exclude_node_index) \
        if (nodes is not None and end_to_node is not None) else None
    return _room_at_t_on_wall(walls_to_create, openings_per_wall, wall_idx, t, sign,
                              safe_range_ft=safe_range_ft)


def solve_l_corner(node, walls_to_create, catalog, node_index=None, openings_per_wall=None,
                   nodes=None, end_to_node=None):
    """Resolve o encontro em L (secao 10 do prompt): dois B34, um por
    fiada, cada um com a ponta do VAO MENOR encostada no no' (ver
    _asymmetric_bond_origin_and_axis) - e' o que faz as duas celulas
    menores ficarem sobrepostas em projecao dentro do quadrado do canto
    (conferido geometricamente contra a familia real deste projeto).

    ANTES de forcar B34 (pedido do usuario, 2026-08-21 - mesma regra
    aplicada primeiro a solve_t_intersection e depois estendida para ca'
    ao medir violacoes reais de vao de porta perto de L_CORNER de
    verdade): confere se ha' espaco fisico real
    (CORNER_B34_ROOM_FT = 34cm) em CADA parede, independentemente
    uma da outra - uma porta perto demais de UM dos dois lados do canto
    nao pode empurrar o B34 para dentro do vao. O lado sem espaco recebe 1
    unico compensador/pastilha (nunca B19, ver CORNER_SINGLE_ELEMENT_CODES);
    o outro lado, se tiver espaco, continua recebendo B34 normalmente
    (nesse caso a prova geometrica de vao menor sobreposto - validate_l_corner -
    deixa de se aplicar, ja' que so' um lado e' B34).

    `openings_per_wall=None` (chamador antigo) pula a checagem - sempre
    forca B34 nos dois lados, comportamento historico. `nodes`/
    `end_to_node` (opcionais): quando dados, o espaco tambem para na
    reserva de um encontro na OUTRA PONTA de cada parede (ver
    `_corner_wall_room_ft`/`_wall_reserved_range_ft`) - sem isso, dois
    encontros em pontas opostas de uma parede curta podiam cada um
    "prometer" B34 cheio sem saber do outro, invadindo-se mutuamente.

    Devolve {"ok", "reason", "course_a", "course_b"} - "reason" so'
    preenchido quando ok=False (nunca lanca; um no' sem solucao e'
    reportado, nao ignorado em silencio - secao 33 do prompt)."""
    entry = catalog.get("B34") if catalog else None
    if entry is None or not entry.get("cells_local"):
        return {"ok": False, "reason": "Catalogo nao tem B34 com celulas legiveis para o encontro em L.",
                "course_a": None, "course_b": None}

    wall_a_idx, wall_b_idx = _l_corner_wall_pair(node)
    if wall_a_idx is None or wall_b_idx is None:
        return {"ok": False, "reason": "No' L_CORNER sem as duas paredes identificaveis.",
                "course_a": None, "course_b": None}

    point_a = _node_contact_point_for_wall(node, wall_a_idx)
    point_b = _node_contact_point_for_wall(node, wall_b_idx)
    _end_a, dir_a, _len_a, _t_a = _wall_end_and_dir_near_point(walls_to_create, wall_a_idx, point_a)
    _end_b, dir_b, _len_b, _t_b = _wall_end_and_dir_near_point(walls_to_create, wall_b_idx, point_b)

    # GIRAR o bloco de 34 do canto (pedido do usuario, 2026-08-25)
    # ------------------------------------------------------------------
    # Por padrao o canto ALTERNA: a peca da fiada A deita sobre
    # `wall_a_idx` e a da fiada B sobre `wall_b_idx`. Quando uma dessas
    # paredes tem OUTRO encontro dentro dos 34cm que a peca ocuparia
    # (tipicamente um T logo ali), as duas pecas de 34 ficam uma sobre a
    # outra; o solver detecta a colisao, desfaz AS DUAS, e a parede
    # termina sem bloco nenhum - o trecho de comprimento NEGATIVO que
    # respondia por 42 dos 57 eixos em revisao manual da planta real.
    #
    # A saida e' GIRAR a peca do canto para a outra parede - nas DUAS
    # fiadas. Apenas trocar quem leva qual fiada nao resolve: o T tambem
    # alterna, entao a colisao so' migra de fiada (medido: sobreposicao
    # de 14cm nos dois casos). Girando nas duas, a sobreposicao vai a
    # zero e ainda sobra um pilarete de 4cm entre o canto e o T - que
    # fecha exato com um compensador C04.
    #
    # CUSTO: neste canto especifico as duas fiadas passam a ter a peca do
    # mesmo lado, ou seja, o canto perde a alternancia entre fiadas. E' a
    # unica configuracao sem colisao quando as duas junçoes estao a menos
    # de 34cm; so' e' aplicada nesse caso.
    #
    # Gate em `nodes is not None AND end_to_node is not None` (nao so'
    # `nodes`) de proposito: e' o MESMO padrao que _wall_reserved_range_ft/
    # _t_intersection_room_ok ja' usam para "chamador antigo pula a
    # checagem" - um teste depende de chamar SEM end_to_node para
    # reproduzir o comportamento historico de proposito
    # (test_solve_l_corner_considera_reserva_do_encontro_na_outra_ponta_da_mesma_parede).
    if nodes is not None and end_to_node is not None:
        blocked_a = _corner_bond_blocked_by_other_node(
            walls_to_create, nodes, wall_a_idx, point_a, dir_a,
            CORNER_B34_ROOM_FT, node_index)
        blocked_b = _corner_bond_blocked_by_other_node(
            walls_to_create, nodes, wall_b_idx, point_b, dir_b,
            CORNER_B34_ROOM_FT, node_index)
        if blocked_a != blocked_b:
            # As DUAS fiadas vao para a parede NAO bloqueada - de proposito,
            # NAO e' uma troca (course_a<->course_b): uma troca simples so'
            # move a colisao de fiada para fiada (medido a mao antes desta
            # mudanca - ver o commit que introduziu esta funcao: "trocar a
            # alternancia" ainda colide 14cm, so' que na OUTRA fiada, porque
            # o encontro vizinho tambem alterna). Com as duas fiadas na
            # mesma parede livre, a sobreposicao vai a ZERO e ainda sobra um
            # pilarete que fecha com um compensador simples. O CUSTO,
            # documentado no cabecalho desta funcao: este canto especifico
            # perde a alternancia normal entre fiadas.
            unblocked_idx, unblocked_point, unblocked_dir = (
                (wall_b_idx, point_b, dir_b) if blocked_a else (wall_a_idx, point_a, dir_a)
            )
            wall_a_idx, point_a, dir_a = unblocked_idx, unblocked_point, unblocked_dir
            wall_b_idx, point_b, dir_b = unblocked_idx, unblocked_point, unblocked_dir

    room_a = _corner_wall_room_ft(walls_to_create, openings_per_wall, wall_a_idx, point_a, dir_a,
                                  nodes=nodes, end_to_node=end_to_node, exclude_node_index=node_index)
    room_b = _corner_wall_room_ft(walls_to_create, openings_per_wall, wall_b_idx, point_b, dir_b,
                                  nodes=nodes, end_to_node=end_to_node, exclude_node_index=node_index)
    b34_ok_a = room_a is None or room_a + 1e-6 >= CORNER_B34_ROOM_FT
    b34_ok_b = room_b is None or room_b + 1e-6 >= CORNER_B34_ROOM_FT

    small_sign = _block_smaller_cell_sign(entry)

    if b34_ok_a:
        origin_a, x_a = _asymmetric_bond_origin_and_axis(entry, point_a, dir_a, small_sign)
        course_a = _make_block_candidate("B34", entry, "A", origin_a, x_a, "L_CORNER",
                                         node_index=node_index, wall_idx=wall_a_idx,
                                         secondary_wall_idx=wall_b_idx)
    else:
        course_a = _corner_single_element_candidate(
            catalog, point_a, dir_a, room_a, "A", wall_a_idx, wall_b_idx, node_index,
            placement_reason="L_CORNER_DEGRADED"
        )

    if b34_ok_b:
        origin_b, x_b = _asymmetric_bond_origin_and_axis(entry, point_b, dir_b, small_sign)
        course_b = _make_block_candidate("B34", entry, "B", origin_b, x_b, "L_CORNER",
                                         node_index=node_index, wall_idx=wall_b_idx,
                                         secondary_wall_idx=wall_a_idx)
    else:
        course_b = _corner_single_element_candidate(
            catalog, point_b, dir_b, room_b, "B", wall_b_idx, wall_a_idx, node_index,
            placement_reason="L_CORNER_DEGRADED"
        )

    if course_a is None or course_b is None:
        return {"ok": False,
                "reason": "Sem espaco fisico suficiente para B34 em um dos lados deste encontro em L "
                          "(precisa de {:.0f}cm) e nem o menor compensador (4cm) cabe - requer ajuste "
                          "de geometria (mover abertura) antes de modular este encontro.".format(
                              34.0),
                "course_a": None, "course_b": None}

    degraded = not (b34_ok_a and b34_ok_b)
    result = {"ok": True, "reason": None, "course_a": course_a, "course_b": course_b}
    if degraded:
        result["degraded"] = True
    return result


# B54 fica CENTRADO no ponto do no' (secao 11/29) - precisa de metade do
# proprio comprimento livre PARA OS DOIS LADOS ao longo da parede continua
# (mainWall) sem invadir abertura nenhuma. B34 encosta no' e se estende
# PARA DENTRO da parede que chega (incomingWall) - precisa do proprio
# comprimento inteiro livre naquele sentido. Pedido explicito do usuario
# (2026-08-21, com imagens de referencia de um caso real corrigido a mao):
# "nao usar bloco de 54cm apenas porque foi identificado um encontro em T -
# primeiro verifique se existe comprimento suficiente... para evitar
# sobreposicao, blocos fora do limite da parede ou modulacoes forcadas".
T_INTERSECTION_B54_HALF_ROOM_FT = _cm_to_ft(54.0 / 2.0)
CORNER_B34_ROOM_FT = _cm_to_ft(34.0)


def _t_of_point_on_wall(walls_to_create, wall_idx, point):
    """Parametro `t` (ft, desde p0) da projecao de `point` no eixo de
    `wall_idx` - mesma convencao usada em toda a Etapa 3B."""
    p0, _p1, direction, _len, _thick = _wall_axis_and_length(walls_to_create, wall_idx)
    vec = XYZ(point.X - p0.X, point.Y - p0.Y, 0.0)
    return vec.DotProduct(direction)


def _wall_junction_ts_ft(walls_to_create, nodes, wall_idx, exclude_node_index=None):
    """`t` (ft) de cada no' de encontro REAL que toca `wall_idx` - contando
    tambem os de MEIO DE PAREDE (T/X), que `_wall_reserved_range_ft` nunca
    enxerga: aquele so' varre as DUAS PONTAS (`for end_index in (0, 1)`).

    Era essa a lacuna que produzia os trechos de comprimento NEGATIVO
    reportados pelo usuario (2026-08-25): um canto em L e um encontro em T
    a 20cm um do outro, na MESMA parede, cada um prometendo os 34cm que a
    sua peca de amarracao precisa, sem saber do outro. Mesma classe de bug
    que o cabecalho de `_wall_reserved_range_ft` ja' descreve para as duas
    PONTAS de uma parede curta - so' que pelo meio dela."""
    found = []
    if not nodes:
        return found
    for idx, node in enumerate(nodes):
        if idx == exclude_node_index or not isinstance(node, dict):
            continue
        if node.get("kind") in (None, "FREE_END"):
            continue
        involved = set()
        for arm in (node.get("arms") or []):
            if arm:
                involved.add(arm[0])
        for key in ("main_wall_idx", "incoming_wall_idx", "neighbor_wall_idx"):
            if node.get(key) is not None:
                involved.add(node[key])
        for w in (node.get("crossing_walls") or []):
            if w is not None:
                involved.add(w)
        if wall_idx not in involved:
            continue
        point = node.get("point")
        if point is None:
            continue
        found.append(_t_of_point_on_wall(walls_to_create, wall_idx, point))
    return found


def _corner_bond_blocked_by_other_node(walls_to_create, nodes, wall_idx, contact_point,
                                       dir_away, span_ft, exclude_node_index=None):
    """True quando OUTRO encontro desta mesma parede cai perto o
    suficiente para a peca de amarracao deste canto (`span_ft`, deitada
    sobre `wall_idx`) colidir com a peca QUE AQUELE OUTRO ENCONTRO vai
    colocar - ou seja, quando as duas pecas ficariam uma em cima da
    outra.

    GUARDA (bug real, medido 2026-08-25, achado num fuzzer sintetico de
    encontros proximos): comparar so' contra `span_ft` checa se o PONTO do
    outro no' cai dentro do alcance da peca deste canto, mas ignora que a
    peca DAQUELE outro no' tambem se estende de volta na nossa direcao -
    um X_INTERSECTION coloca um B54 CENTRADO no proprio ponto, alcancando
    ate' T_INTERSECTION_B54_HALF_ROOM_FT (27cm) para TRAS dele. Um X a
    37cm do canto (fora dos 34cm de `span_ft`) ainda colidia: seu B54
    comecava em 37-27=10cm, bem dentro do quadrado do canto (0-34cm).
    Por isso a margem usada aqui e' `span_ft + T_INTERSECTION_B54_HALF_ROOM_FT`
    - o maior alcance-para-tras que qualquer peca de amarracao (B34 do
    outro lado de um L, B54 de um T ou de um X) pode ter, superestimando
    de proposito (mais seguro rotacionar a mais do que colidir)."""
    _p0, _p1, wall_dir, _len, _thick = _wall_axis_and_length(walls_to_create, wall_idx)
    sign = 1.0 if dir_away.DotProduct(wall_dir) >= 0 else -1.0
    t0_ft = _t_of_point_on_wall(walls_to_create, wall_idx, contact_point)
    danger_ft = span_ft + T_INTERSECTION_B54_HALF_ROOM_FT
    for t_other_ft in _wall_junction_ts_ft(walls_to_create, nodes, wall_idx, exclude_node_index):
        along_ft = (t_other_ft - t0_ft) * sign
        if 1e-6 < along_ft < danger_ft - 1e-6:
            return True
    return False


def _room_at_t_on_wall(walls_to_create, openings_per_wall, wall_idx, t_ft, sign, safe_range_ft=None):
    """Distancia (ft, nunca negativa) de `t_ft` ate' o proximo obstaculo
    REAL (borda de abertura, a reserva de um encontro na OUTRA ponta da
    parede, ou a propria ponta fisica) andando no sentido `sign` (+1 = t
    crescente, -1 = t decrescente) ao longo do eixo de `wall_idx`. Usada
    so' para MEDIR espaco disponivel antes de forcar uma peca de
    amarracao (B54/B34) num encontro em T/L - nunca altera nada.

    `safe_range_ft` (opcional): `(lo_ft, hi_ft)` de `_wall_reserved_range_ft`
    - quando dado, o "fim fisico da parede" some' como limite e vira esse
    intervalo (ja' descontada a reserva de outro encontro na ponta
    oposta). `None` (chamador antigo) usa o comprimento fisico inteiro,
    comportamento historico."""
    if wall_idx is None or wall_idx >= len(walls_to_create):
        return 0.0
    _p0, _p1, _dir, total_len_ft, _thick = _wall_axis_and_length(walls_to_create, wall_idx)
    lo_ft, hi_ft = (0.0, total_len_ft) if safe_range_ft is None else safe_range_ft
    openings_here = openings_per_wall[wall_idx] if (openings_per_wall and wall_idx < len(openings_per_wall)) else []
    if sign >= 0:
        boundary = hi_ft
        for (t_lo, _t_hi, _s, _h) in openings_here:
            if t_lo >= t_ft - 1e-6 and t_lo < boundary:
                boundary = t_lo
        return max(0.0, boundary - t_ft)
    boundary = lo_ft
    for (_t_lo, t_hi, _s, _h) in openings_here:
        if t_hi <= t_ft + 1e-6 and t_hi > boundary:
            boundary = t_hi
    return max(0.0, t_ft - boundary)


def _t_intersection_room_assessment(node, walls_to_create, openings_per_wall,
                                    nodes=None, end_to_node=None, node_index=None):
    """Mede o espaco fisico real neste no' T - so' MEDE, nunca decide nem
    posiciona nada (ver solve_t_intersection para a decisao). Devolve None
    se o no' nao tiver mainWall/incomingWall identificaveis, senao:
        {"main_idx", "inc_idx", "point", "contact_i", "main_dir",
         "incoming_dir", "room_plus_ft", "room_minus_ft", "room_incoming_ft"}
    `room_plus_ft`/`room_minus_ft` sao o espaco na parede PRINCIPAL nos
    dois sentidos a partir do no' (+main_dir e -main_dir); `room_incoming_ft`
    e' o espaco na boneca (incomingWall) se afastando do no'.

    `nodes`/`end_to_node` (opcionais): quando dados, o espaco tambem para
    na reserva de outro encontro nas PONTAS de `main_idx`/`inc_idx` (ver
    `_wall_reserved_range_ft`) - este no' T e' sempre MEIO de `main_idx`
    (nunca uma das pontas dela, entao nada para excluir ali) mas e' a
    propria PONTA de `inc_idx` (por isso `exclude_node_index=node_index`
    so' entra na medicao de `inc_idx`)."""
    main_idx = node.get("main_wall_idx")
    inc_idx = node.get("incoming_wall_idx")
    if main_idx is None or inc_idx is None:
        return None
    have_graph = nodes is not None and end_to_node is not None
    point = node["point"]
    _p0, _p1, main_dir, _len, _thick = _wall_axis_and_length(walls_to_create, main_idx)
    t_main = _t_of_point_on_wall(walls_to_create, main_idx, point)
    main_range = _wall_reserved_range_ft(walls_to_create, nodes, end_to_node, main_idx) if have_graph else None
    room_plus = _room_at_t_on_wall(walls_to_create, openings_per_wall, main_idx, t_main, 1, main_range)
    room_minus = _room_at_t_on_wall(walls_to_create, openings_per_wall, main_idx, t_main, -1, main_range)

    contact_i = _node_contact_point_for_wall(node, inc_idx)
    _end_i, dir_i, _len_i, _thick_i = _wall_end_and_dir_near_point(walls_to_create, inc_idx, contact_i)
    _p0_i, _p1_i, wall_dir_i, _len_i2, _thick_i2 = _wall_axis_and_length(walls_to_create, inc_idx)
    sign_i = 1 if dir_i.DotProduct(wall_dir_i) >= 0 else -1
    t_i = _t_of_point_on_wall(walls_to_create, inc_idx, contact_i)
    inc_range = _wall_reserved_range_ft(walls_to_create, nodes, end_to_node, inc_idx,
                                        exclude_node_index=node_index) if have_graph else None
    room_i = _room_at_t_on_wall(walls_to_create, openings_per_wall, inc_idx, t_i, sign_i, inc_range)

    return {
        "main_idx": main_idx, "inc_idx": inc_idx, "point": point, "contact_i": contact_i,
        "main_dir": main_dir, "incoming_dir": dir_i,
        "room_plus_ft": room_plus, "room_minus_ft": room_minus, "room_incoming_ft": room_i,
    }


def _t_intersection_room_ok(node, walls_to_create, openings_per_wall,
                            nodes=None, end_to_node=None, node_index=None):
    """True se ha' espaco fisico real para o B54 (mainWall, centrado,
    precisa de T_INTERSECTION_B54_HALF_ROOM_FT PARA OS DOIS LADOS) e o B34
    (incomingWall, precisa de CORNER_B34_ROOM_FT no sentido que se
    afasta do no') - o T "de verdade" (ver cabecalho acima). `openings_per_wall=
    None` (chamador antigo que ainda nao thread essa informacao) pula a
    checagem e sempre devolve True, para nao quebrar quem ainda nao passa
    esse dado. Quando isto devolve False, `solve_t_intersection` ainda
    tenta um padrao degradado (L com B34 nos dois lados, ou por ultimo 1
    unico compensador/pastilha na boneca) antes de desistir - ver la'."""
    if openings_per_wall is None:
        return True
    assessment = _t_intersection_room_assessment(node, walls_to_create, openings_per_wall,
                                                 nodes=nodes, end_to_node=end_to_node, node_index=node_index)
    if assessment is None:
        return True  # sem paredes identificadas, o chamador ja' vai reportar erro por outro motivo
    if min(assessment["room_plus_ft"], assessment["room_minus_ft"]) + 1e-6 < T_INTERSECTION_B54_HALF_ROOM_FT:
        return False
    return assessment["room_incoming_ft"] + 1e-6 >= CORNER_B34_ROOM_FT


# Ordem de preferencia do elemento UNICO que fecha uma parede curta demais
# para o B34 num encontro (L ou T degradado para L) - maior primeiro. SO'
# compensador/pastilha, NUNCA B19 (corrigido 2026-08-21, o usuario apontou
# o motivo: um lado curto demais de um encontro continua sendo um
# encontro/amarracao, nao uma ponta livre - a regra do B19 (so' em vao de
# abertura ou PONTA SEM AMARRACAO) nao se aplica aqui. "canaleta ou
# compensador, conforme o espaco disponivel", pedido explicito do usuario.
CORNER_SINGLE_ELEMENT_CODES = ("C09", "C04")


def _corner_single_element_candidate(catalog, contact_point, dir_away, room_ft, course,
                                     wall_idx, secondary_wall_idx, node_index,
                                     placement_reason="CORNER_DEGRADED"):
    """UM UNICO elemento (o maior entre C09/C04 que caiba no espaco real
    disponivel - NUNCA B19, ver CORNER_SINGLE_ELEMENT_CODES) para fechar
    uma parede curta demais para o B34 normal num encontro (L de verdade
    OU T degradado para L - ver solve_l_corner/solve_t_intersection) -
    substitui a amarracao especial quando ela nao cabe fisicamente.
    Encosta em `contact_point` (o ponto do no'), estendendo-se por
    `dir_away` (unitario, para dentro da parede - o mesmo sentido em que
    o B34 normal se estenderia). Devolve None se nem o menor (C04, 4cm)
    couber em `room_ft` - nesse caso nao ha' solucao automatica, precisa
    de ajuste de geometria antes."""
    best_code = None
    for code in CORNER_SINGLE_ELEMENT_CODES:
        entry = catalog.get(code)
        if entry is None or not entry.get("length_cm"):
            continue
        if _cm_to_ft(entry["length_cm"]) <= room_ft + 1e-6:
            best_code = code
            break
    if best_code is None:
        return None
    entry = catalog[best_code]
    half_len_ft = _cm_to_ft(entry["length_cm"]) / 2.0
    origin = contact_point + dir_away * half_len_ft
    return _make_block_candidate(best_code, entry, course, origin, dir_away,
                                 placement_reason,
                                 node_index=node_index, wall_idx=wall_idx,
                                 secondary_wall_idx=secondary_wall_idx)


def solve_t_intersection(node, walls_to_create, catalog, node_index=None, openings_per_wall=None,
                         nodes=None, end_to_node=None):
    """Resolve o encontro em T (secao 11 do prompt): B54 na parede
    continua (mainWall, Fiada A) com a celula central no ponto do no' + B34
    na parede que chega (incomingWall, Fiada B) com o vao menor voltado
    para o no' (portanto para o B54). A inversao A/B que a secao 11 permite
    para a paginacao global fica para a Etapa 7 (solver global) decidir -
    aqui a atribuicao e' sempre esta (B54->Fiada A, B34->Fiada B); o que
    NAO muda, aqui ou depois, e' a relacao de amarracao B54<->B34.

    ANTES de forcar B54/B34 (pedido explicito do usuario, 2026-08-21, com
    exemplo real corrigido a mao): confere se ha' espaco fisico real (ver
    _t_intersection_room_ok) - sem isso, um vao de porta ou uma boneca
    curta perto do no' fazia o B54/B34 invadir a abertura ou passar do
    limite da parede.

    Sem espaco para o T "de verdade", tenta NESTA ORDEM (o usuario
    corrigiu o design 2x ate' chegar nesta versao):
      1. DEGRADA PARA L: quando o no' deixa de caber como T, na pratica
         vira um CANTO EM L com uma boneca - e "amarracao em L usa o
         bloco de 34 (sempre)" (regra explicita do usuario). Tenta B34 na
         boneca (precisa dos mesmos 34cm de sempre) + B34 na parede
         PRINCIPAL, mas so' esticando para o lado que TEM espaco (>=34cm) -
         exatamente como solve_l_corner resolveria se essas duas paredes
         se encontrassem "de verdade" num canto.
      2. So' quando nem isso cabe (a boneca tem menos de 34cm de espaco
         real): 1 UNICO compensador/pastilha (NUNCA B19 - a boneca
         continua sendo um encontro, nao uma ponta livre, entao a regra
         do B19 - so' em vao de abertura/ponta sem amarracao - nao se
         aplica aqui) fecha a boneca sozinho, sem peca nenhuma na parede
         principal (o preenchimento comum dela, ja existente, cuida do
         trecho ate' a ponta com bloco comum, reservando so' a metade da
         espessura da parede mais larga no' - _node_default_reservation_cm -
         para nao colidir).
      3. Se nem o menor compensador (C04, 4cm) couber na boneca, devolve
         `ok=False` (o no' vira `intersection_failures`, reportado
         explicitamente) - precisa de ajuste de geometria (mover
         abertura/crescer a boneca) antes, nao da' para inventar peca.

    Devolve {"ok", "reason", "course_a", "course_b"}."""
    b54 = catalog.get("B54") if catalog else None
    b34 = catalog.get("B34") if catalog else None
    if b54 is None or not b54.get("cells_local"):
        return {"ok": False, "reason": "Catalogo nao tem B54 com celulas legiveis para o encontro em T.",
                "course_a": None, "course_b": None}
    if b34 is None or not b34.get("cells_local"):
        return {"ok": False, "reason": "Catalogo nao tem B34 com celulas legiveis para o encontro em T.",
                "course_a": None, "course_b": None}

    main_idx = node.get("main_wall_idx")
    inc_idx = node.get("incoming_wall_idx")
    if main_idx is None or inc_idx is None:
        return {"ok": False, "reason": "No' T_INTERSECTION sem mainWall/incomingWall identificaveis.",
                "course_a": None, "course_b": None}

    if not _t_intersection_room_ok(node, walls_to_create, openings_per_wall,
                                   nodes=nodes, end_to_node=end_to_node, node_index=node_index):
        assessment = _t_intersection_room_assessment(node, walls_to_create, openings_per_wall,
                                                     nodes=nodes, end_to_node=end_to_node, node_index=node_index)
        point = assessment["point"]
        contact_i = assessment["contact_i"]
        main_dir = assessment["main_dir"]
        dir_i = assessment["incoming_dir"]
        room_i_ft = assessment["room_incoming_ft"]

        # 1) DEGRADA PARA L: B34 nos dois lados, se couberem.
        if room_i_ft + 1e-6 >= CORNER_B34_ROOM_FT:
            l_dir = None
            if assessment["room_plus_ft"] + 1e-6 >= CORNER_B34_ROOM_FT:
                l_dir = main_dir
            elif assessment["room_minus_ft"] + 1e-6 >= CORNER_B34_ROOM_FT:
                l_dir = main_dir.Negate()
            if l_dir is not None:
                # O "arm_point" de um L_CORNER de verdade fica do lado
                # OPOSTO de onde a peca se estende (extend_wall_ends_to_
                # junctions empurra a ponta ATRAVESSANDO a parede
                # perpendicular, ate' a FACE OPOSTA dela - ver
                # _node_contact_point_for_wall) - so' assim o bloco, ao
                # estender de volta em dir_away (para dentro do proprio
                # corpo da parede), acaba encostando exatamente na face da
                # parede vizinha. Confirmado medindo um L_CORNER de
                # verdade (validate_l_corner) e reproduzindo o MESMO
                # deslocamento aqui: o ponto de contato fica deslocado PARA
                # O LADO CONTRARIO de `l_dir` (para dentro da boneca), e o
                # bloco se estende de volta em `l_dir` (onde esta' o
                # espaco real) - primeira versao desta correcao deslocava
                # para o lado ERRADO e desalinhava os vaos menores entre
                # fiadas (pego pelo proprio validate_l_corner num teste).
                _p0_i, _p1_i, _dir_i2, _len_i2, thick_i = _wall_axis_and_length(walls_to_create, inc_idx)
                contact_main = point - l_dir * (thick_i / 2.0)
                small_sign = _block_smaller_cell_sign(b34)
                origin_main, x_main = _asymmetric_bond_origin_and_axis(b34, contact_main, l_dir, small_sign)
                course_a = _make_block_candidate("B34", b34, "A", origin_main, x_main,
                                                 "T_INTERSECTION_DEGRADED_L",
                                                 node_index=node_index, wall_idx=main_idx,
                                                 secondary_wall_idx=inc_idx)
                origin_inc, x_inc = _asymmetric_bond_origin_and_axis(b34, contact_i, dir_i, small_sign)
                course_b = _make_block_candidate("B34", b34, "B", origin_inc, x_inc,
                                                 "T_INTERSECTION_DEGRADED_L",
                                                 node_index=node_index, wall_idx=inc_idx,
                                                 secondary_wall_idx=main_idx)
                return {"ok": True, "reason": None, "course_a": course_a, "course_b": course_b,
                        "degraded": True}

        # 2) SO' compensador/pastilha na boneca (nunca B19 - ver
        #    CORNER_SINGLE_ELEMENT_CODES), nada na parede principal.
        single_a = _corner_single_element_candidate(
            catalog, contact_i, dir_i, room_i_ft, "A", inc_idx, main_idx, node_index,
            placement_reason="T_INTERSECTION_INCOMING_DEGRADED"
        )
        single_b = _corner_single_element_candidate(
            catalog, contact_i, dir_i, room_i_ft, "B", inc_idx, main_idx, node_index,
            placement_reason="T_INTERSECTION_INCOMING_DEGRADED"
        )
        if single_a is None or single_b is None:
            return {"ok": False,
                    "reason": "Sem espaco fisico suficiente para B54/B34 neste encontro em T, nem "
                              "para degradar para um canto em L (precisa de {:.0f}cm para cada lado na "
                              "parede principal e {:.0f}cm na boneca para o T; {:.0f}cm na boneca para "
                              "o L) - e nem o menor compensador (4cm) cabe no espaco real da boneca "
                              "({:.1f}cm). Requer ajuste de geometria (mover abertura/crescer a "
                              "boneca) antes de modular este encontro.".format(
                                  54.0 / 2.0, 34.0, 34.0, room_i_ft * 100.0 / FEET_PER_METER),
                    "course_a": None, "course_b": None}
        # 3) Nenhuma peca na parede PRINCIPAL, nas duas fiadas - o
        # preenchimento comum dela (ja existente) cuida do trecho ate' a
        # ponta com bloco comum, so' reservando a metade da espessura da
        # parede mais larga no' (_node_default_reservation_cm) para nao
        # colidir com o elemento unico da boneca. Na boneca, as DUAS
        # fiadas (A e B) recebem o MESMO elemento unico (nao so' uma) -
        # "deixe apenas um unico elemento" pedido pelo usuario significa
        # "um so' TIPO de peca fechando ali", nao "so' uma fiada recebe
        # algo" (a outra fiada ficaria sem nada reservado, o que abriria
        # buraco/colisao).
        return {"ok": True, "reason": None, "course_a": single_a, "course_b": single_b, "degraded": True}

    point = node["point"]
    contact_i = _node_contact_point_for_wall(node, inc_idx)
    _p0, _p1, main_dir, _len_m, _t_m = _wall_axis_and_length(walls_to_create, main_idx)
    _end_i, dir_i, _len_i, _t_i = _wall_end_and_dir_near_point(walls_to_create, inc_idx, contact_i)

    # Celula central do B54 fica em local (0,0) (medido na familia real,
    # ver cabecalho da secao) - o proprio ponto do no' e' a origem do bloco.
    course_a = _make_block_candidate("B54", b54, "A", point, main_dir, "T_INTERSECTION_MAIN",
                                     node_index=node_index, wall_idx=main_idx, secondary_wall_idx=inc_idx)

    small_sign = _block_smaller_cell_sign(b34)
    origin_b, x_b = _asymmetric_bond_origin_and_axis(b34, contact_i, dir_i, small_sign)
    course_b = _make_block_candidate("B34", b34, "B", origin_b, x_b, "T_INTERSECTION_INCOMING",
                                     node_index=node_index, wall_idx=inc_idx, secondary_wall_idx=main_idx)

    return {"ok": True, "reason": None, "course_a": course_a, "course_b": course_b}


# Mesmo teto do T (T_INTERSECTION_B54_HALF_ROOM_FT): o B54 de um X fica
# CENTRADO no ponto do cruzamento, entao precisa da METADE do comprimento
# dele livre em CADA sentido - exatamente a mesma conta, so' aplicada nas
# DUAS paredes do X em vez de uma so'.
X_INTERSECTION_B54_HALF_ROOM_FT = T_INTERSECTION_B54_HALF_ROOM_FT

# Ordem de degradacao do B54 de um X_INTERSECTION quando nao ha' espaco
# (bug real, medido 2026-08-25): ao contrario de L_CORNER/T_INTERSECTION,
# X_INTERSECTION nunca verificava espaco NENHUM - forcava B54 (54cm)
# incondicionalmente nas duas paredes, mesmo quando um encontro vizinho
# (outro L/T/X) estava perto demais. O B54 fisicamente colidia com a peca
# do encontro vizinho, e o preenchimento comum via SEM_ESPACO (trecho de
# comprimento NEGATIVO) - a mesma familia de sintoma da correcao anterior
# (T perto de canto), so' que pelo lado do X. B34 primeiro (mesma peca
# especial que L/T usam na degradacao), compensadores por ultimo - NUNCA
# B19 (mesma regra do usuario ja' aplicada em CORNER_SINGLE_ELEMENT_CODES:
# um cruzamento continua sendo amarracao, nao ponta livre).
X_INTERSECTION_DEGRADED_CODES = ("B34",) + CORNER_SINGLE_ELEMENT_CODES


def _x_intersection_wall_room_ft(walls_to_create, openings_per_wall, wall_idx, point,
                                 nodes=None, end_to_node=None, exclude_node_index=None):
    """(room_plus_ft, room_minus_ft) em `wall_idx` a partir do ponto do
    cruzamento X, nos dois sentidos do proprio eixo - mesma medicao de
    `_t_intersection_room_assessment` para a parede principal do T
    (tambem centrada no no'), reaproveitada aqui para as DUAS paredes do
    X."""
    t = _t_of_point_on_wall(walls_to_create, wall_idx, point)
    wall_range = (
        _wall_reserved_range_ft(walls_to_create, nodes, end_to_node, wall_idx,
                                exclude_node_index=exclude_node_index)
        if nodes is not None and end_to_node is not None else None
    )
    room_plus = _room_at_t_on_wall(walls_to_create, openings_per_wall, wall_idx, t, 1, wall_range)
    room_minus = _room_at_t_on_wall(walls_to_create, openings_per_wall, wall_idx, t, -1, wall_range)
    return room_plus, room_minus


def _x_intersection_centered_candidate(catalog, point, x_dir, room_ft, course, wall_idx,
                                       secondary_wall_idx, node_index, placement_reason):
    """Melhor peca CENTRADA em `point` (ao longo de `x_dir`) dentre
    X_INTERSECTION_DEGRADED_CODES que caiba inteira nos dois sentidos
    (metade do comprimento dela <= `room_ft`, que ja' e' o MENOR dos dois
    lados) - usada para degradar o B54 de um X_INTERSECTION sem espaco.
    Devolve None se nem o menor compensador (C04) couber - nesse caso o
    no' vira `ok=False`, reportado explicitamente (nunca inventa peca).

    GUARDA (bug real, medido 2026-08-25, achado num fuzzer sintetico de
    encontros proximos): `room_ft` mede ate' a BORDA do proximo obstaculo,
    mas o preenchimento comum ainda vai exigir BLOCK_JOINT_CM (1cm) de
    junta entre a ponta desta peca e esse obstaculo - sem descontar isso
    aqui, uma peca aceita "raspando" o limite (half_len == room) sobrava
    exatamente -1cm no trecho seguinte. Por isso o teste e'
    `half_len_ft + BLOCK_JOINT_CM(em ft) <= room_ft`, nao so' `half_len_ft`."""
    joint_ft = _cm_to_ft(BLOCK_JOINT_CM)
    for code in X_INTERSECTION_DEGRADED_CODES:
        entry = catalog.get(code)
        if entry is None or not entry.get("length_cm"):
            continue
        half_len_ft = _cm_to_ft(entry["length_cm"]) / 2.0
        if half_len_ft + joint_ft <= room_ft + 1e-6:
            return _make_block_candidate(code, entry, course, point, x_dir, placement_reason,
                                         node_index=node_index, wall_idx=wall_idx,
                                         secondary_wall_idx=secondary_wall_idx)
    return None


def solve_x_intersection(node, walls_to_create, catalog, node_index=None,
                         openings_per_wall=None, nodes=None, end_to_node=None):
    """Resolve o cruzamento em X (secao 12 do prompt): dois B54 alternados
    entre as fiadas, rotacionados 90 graus um do outro, ambos centrados no
    ponto do no' - que e' automaticamente onde a celula central de CADA um
    cai, pela convencao medida na familia real (ver cabecalho da secao).
    Cobre tanto o cruzamento no MEIO de duas paredes continuas
    (`node["crossing_walls"]` vindo de _find_wall_midspan_crossings) quanto
    o caso raro de 4 pontas de parede coincidindo exatamente no mesmo ponto
    (_classify_wall_node, ramo de 4 bracos).

    ANTES de forcar B54 nas duas paredes (bug real, medido 2026-08-25):
    confere se ha' espaco fisico real - o B54 fica CENTRADO no no', entao
    precisa de X_INTERSECTION_B54_HALF_ROOM_FT livre em CADA sentido, em
    CADA uma das duas paredes (mesma conta que T_INTERSECTION ja' faz para
    a parede principal dele, que tambem centraliza um B54). Ao contrario
    de L_CORNER/T_INTERSECTION, esta checagem nao existia: um X perto
    demais de outro encontro (L, T ou outro X) forcava o B54 mesmo assim,
    e ele colidia fisicamente com a peca do vizinho - reportado como
    trecho de preenchimento comum com comprimento NEGATIVO (SEM_ESPACO),
    a mesma familia de sintoma da correcao anterior (T perto de canto), so'
    que pelo lado do X.

    Quando uma das duas paredes nao tem espaco, SO' A PECA DAQUELA parede
    degrada (B34 centrado, depois compensador - ver
    X_INTERSECTION_DEGRADED_CODES) - a peca da OUTRA parede continua B54
    normal se ela tiver espaco. `openings_per_wall=None` (chamador antigo)
    pula a checagem inteira - sempre forca B54 nas duas, comportamento
    historico.

    Devolve {"ok", "reason", "course_a", "course_b"}."""
    entry = catalog.get("B54") if catalog else None
    if entry is None or not entry.get("cells_local"):
        return {"ok": False, "reason": "Catalogo nao tem B54 com celulas legiveis para o cruzamento.",
                "course_a": None, "course_b": None}

    walls_pair = node.get("crossing_walls")
    if not walls_pair or walls_pair[0] is None or walls_pair[1] is None:
        return {"ok": False, "reason": "No' X_INTERSECTION sem as duas paredes identificaveis.",
                "course_a": None, "course_b": None}
    wall_a_idx, wall_b_idx = walls_pair

    point = node["point"]
    _pa0, _pa1, dir_a, _len_a, _t_a = _wall_axis_and_length(walls_to_create, wall_a_idx)
    _pb0, _pb1, dir_b, _len_b, _t_b = _wall_axis_and_length(walls_to_create, wall_b_idx)

    if openings_per_wall is None:
        course_a = _make_block_candidate("B54", entry, "A", point, dir_a, "X_INTERSECTION",
                                         node_index=node_index, wall_idx=wall_a_idx, secondary_wall_idx=wall_b_idx)
        course_b = _make_block_candidate("B54", entry, "B", point, dir_b, "X_INTERSECTION",
                                         node_index=node_index, wall_idx=wall_b_idx, secondary_wall_idx=wall_a_idx)
        return {"ok": True, "reason": None, "course_a": course_a, "course_b": course_b}

    room_plus_a, room_minus_a = _x_intersection_wall_room_ft(
        walls_to_create, openings_per_wall, wall_a_idx, point, nodes, end_to_node, node_index)
    room_plus_b, room_minus_b = _x_intersection_wall_room_ft(
        walls_to_create, openings_per_wall, wall_b_idx, point, nodes, end_to_node, node_index)
    # Mesma junta de 1cm que falta em _x_intersection_centered_candidate -
    # sem ela, um B54 aceito "raspando" o limite deixava exatamente -1cm
    # no trecho de preenchimento comum seguinte (medido).
    b54_half_room_needed_ft = X_INTERSECTION_B54_HALF_ROOM_FT + _cm_to_ft(BLOCK_JOINT_CM)

    if min(room_plus_a, room_minus_a) + 1e-6 >= b54_half_room_needed_ft:
        course_a = _make_block_candidate("B54", entry, "A", point, dir_a, "X_INTERSECTION",
                                         node_index=node_index, wall_idx=wall_a_idx, secondary_wall_idx=wall_b_idx)
    else:
        course_a = _x_intersection_centered_candidate(
            catalog, point, dir_a, min(room_plus_a, room_minus_a), "A", wall_a_idx, wall_b_idx,
            node_index, "X_INTERSECTION_DEGRADED")

    if min(room_plus_b, room_minus_b) + 1e-6 >= b54_half_room_needed_ft:
        course_b = _make_block_candidate("B54", entry, "B", point, dir_b, "X_INTERSECTION",
                                         node_index=node_index, wall_idx=wall_b_idx, secondary_wall_idx=wall_a_idx)
    else:
        course_b = _x_intersection_centered_candidate(
            catalog, point, dir_b, min(room_plus_b, room_minus_b), "B", wall_b_idx, wall_a_idx,
            node_index, "X_INTERSECTION_DEGRADED")

    if course_a is None or course_b is None:
        return {"ok": False,
                "reason": "Sem espaco fisico suficiente para B54 em uma das paredes deste cruzamento em X "
                          "(precisa de {:.0f}cm para cada lado) e nem o menor compensador (4cm) cabe - "
                          "requer ajuste de geometria (mover abertura) antes de modular este encontro."
                          .format(54.0 / 2.0),
                "course_a": None, "course_b": None}

    return {"ok": True, "reason": None, "course_a": course_a, "course_b": course_b}


def solve_all_intersections(nodes, walls_to_create, catalog, openings_per_wall=None, end_to_node=None):
    """Roda o solver adequado (L/T/X) em TODOS os nos de `nodes` (ver
    build_wall_graph) - fluxo SolveXIntersections/SolveTIntersections/
    SolveLCorners da secao 17/32 do prompt. Nos FREE_END/
    STRAIGHT_CONTINUATION/AMBIGUOUS sao ignorados aqui (nao sao encontros de
    amarracao especial).

    `openings_per_wall` (opcional): passado adiante so' para
    `solve_t_intersection`/`solve_l_corner`, que o usa para checar espaco
    fisico real antes de forcar B54/B34 (ver _t_intersection_room_ok) -
    `None` mantem o comportamento antigo (sem checagem) para quem ainda
    nao passa esse dado. `end_to_node` (opcional, precisa vir junto de
    `openings_per_wall` para ter efeito): thread'ado aos dois solvers para
    que o espaco medido tambem pare na reserva de um encontro na OUTRA
    ponta da mesma parede, nao so' em abertura/ponta fisica (ver
    `_wall_reserved_range_ft` - bug real medido ao vivo 2026-08-24: duas
    amarracoes em pontas opostas de uma parede curta, cada uma sem saber
    da outra, produziam trechos de preenchimento comum com comprimento
    NEGATIVO em cascata pela planta toda).

    Devolve {"candidates": [...], "failures": [(node_index, motivo), ...]}:
    `candidates` e' uma lista PLANA de BlockPlacementCandidate (2 por no'
    resolvido, Fiada A e Fiada B) - pronta para a Etapa 7 (solver global)
    consumir, ou para o modo de debug (Etapa 25) desenhar. Um no' que
    deveria ser um encontro mas nao tem solucao (catalogo incompleto, por
    exemplo) entra em `failures`, nunca e' descartado em silencio."""
    candidates = []
    failures = []
    for node_index, node in enumerate(nodes):
        kind = node.get("kind")
        if kind == "L_CORNER":
            result = solve_l_corner(node, walls_to_create, catalog, node_index=node_index,
                                    openings_per_wall=openings_per_wall,
                                    nodes=nodes, end_to_node=end_to_node)
        elif kind == "T_INTERSECTION":
            result = solve_t_intersection(node, walls_to_create, catalog, node_index=node_index,
                                          openings_per_wall=openings_per_wall,
                                          nodes=nodes, end_to_node=end_to_node)
        elif kind == "X_INTERSECTION":
            result = solve_x_intersection(node, walls_to_create, catalog, node_index=node_index,
                                          openings_per_wall=openings_per_wall,
                                          nodes=nodes, end_to_node=end_to_node)
        else:
            continue
        if not result["ok"]:
            failures.append((node_index, result["reason"]))
            continue
        candidates.append(result["course_a"])
        candidates.append(result["course_b"])
    return {"candidates": candidates, "failures": failures}


# ---- validacao geometrica dos encontros (secoes 10/11/12/19) ------------

def validate_l_corner(course_a, course_b, tolerance_ft=CELL_ALIGNMENT_TOLERANCE_FT):
    """Confirma o encontro em L (secao 10/29 Teste 03): dois B34, fiadas
    diferentes, 90 graus reais, e as duas celulas MENORES sobrepostas em
    projecao XY (a prova geometrica de que a amarracao realmente "trava" no
    canto). Devolve {"ok": bool, "problems": [str, ...]}."""
    problems = []
    if course_a is None or course_b is None:
        return {"ok": False, "problems": ["Faltam candidatos das duas fiadas."]}
    if course_a["logical_code"] != "B34" or course_b["logical_code"] != "B34":
        problems.append("Encontro em L precisa de B34 nas duas fiadas.")
    if course_a["course"] == course_b["course"]:
        problems.append("As duas pecas do L estao na mesma fiada.")
    dot = course_a["x_dir"].DotProduct(course_b["x_dir"])
    if abs(dot) > BOND_PERPENDICULAR_DOT_TOLERANCE:
        problems.append("Pecas do L nao estao a 90 graus (dot={:.3f}).".format(dot))

    cell_a = min(course_a["cells_world"], key=lambda c: c["size_local"][0] * c["size_local"][1]) \
        if course_a["cells_world"] else None
    cell_b = min(course_b["cells_world"], key=lambda c: c["size_local"][0] * c["size_local"][1]) \
        if course_b["cells_world"] else None
    if cell_a is None or cell_b is None:
        problems.append("Peca sem celulas legiveis - nao da' para validar o vao menor.")
    else:
        obb_a = _cell_obb(cell_a, course_a["x_dir"], course_a["y_dir"])
        obb_b = _cell_obb(cell_b, course_b["x_dir"], course_b["y_dir"])
        if not _obb_overlap(obb_a, obb_b, -tolerance_ft):
            problems.append("Vaos menores dos dois B34 nao ficam sobrepostos/alinhados em projecao.")

    return {"ok": not problems, "problems": problems}


def validate_t_intersection(course_a, course_b, tolerance_ft=CELL_ALIGNMENT_TOLERANCE_FT):
    """Confirma o encontro em T (secao 11/29 Teste 04): um B54 (mainWall) e
    um B34 (incomingWall), fiadas diferentes, 90 graus reais, e o vao MENOR
    do B34 sobreposto/alinhado com a celula CENTRAL do B54. Devolve
    {"ok": bool, "problems": [str, ...]}."""
    problems = []
    if course_a is None or course_b is None:
        return {"ok": False, "problems": ["Faltam candidatos das duas fiadas."]}
    codes = sorted([course_a["logical_code"], course_b["logical_code"]])
    if codes != ["B34", "B54"]:
        problems.append("Encontro em T precisa de um B54 e um B34 (um em cada fiada).")
        return {"ok": False, "problems": problems}
    if course_a["course"] == course_b["course"]:
        problems.append("B54 e B34 do T estao na mesma fiada.")

    b54_cand = course_a if course_a["logical_code"] == "B54" else course_b
    b34_cand = course_b if b54_cand is course_a else course_a
    dot = b54_cand["x_dir"].DotProduct(b34_cand["x_dir"])
    if abs(dot) > BOND_PERPENDICULAR_DOT_TOLERANCE:
        problems.append("B54 e B34 do T nao estao a 90 graus (dot={:.3f}).".format(dot))

    central_cell = min(b54_cand["cells_world"],
                       key=lambda c: (c["point"] - b54_cand["origin_world"]).GetLength()) \
        if b54_cand["cells_world"] else None
    small_cell = min(b34_cand["cells_world"], key=lambda c: c["size_local"][0] * c["size_local"][1]) \
        if b34_cand["cells_world"] else None
    if central_cell is None or small_cell is None:
        problems.append("Peca sem celulas legiveis - nao da' para validar o vao central/menor.")
    else:
        obb_central = _cell_obb(central_cell, b54_cand["x_dir"], b54_cand["y_dir"])
        obb_small = _cell_obb(small_cell, b34_cand["x_dir"], b34_cand["y_dir"])
        if not _obb_overlap(obb_central, obb_small, -tolerance_ft):
            problems.append("Vao menor do B34 nao fica voltado/alinhado para a celula central do B54.")

    return {"ok": not problems, "problems": problems}


def validate_x_intersection(course_a, course_b, tolerance_ft=CELL_ALIGNMENT_TOLERANCE_FT):
    """Confirma o cruzamento em X (secao 12/29 Teste 05): dois B54, fiadas
    diferentes, 90 graus reais, e as celulas CENTRAIS dos dois alinhadas em
    projecao (centro contra centro, dentro de `tolerance_ft`). Devolve
    {"ok": bool, "problems": [str, ...]}."""
    problems = []
    if course_a is None or course_b is None:
        return {"ok": False, "problems": ["Faltam candidatos das duas fiadas."]}
    if course_a["logical_code"] != "B54" or course_b["logical_code"] != "B54":
        problems.append("Cruz precisa de B54 nas duas fiadas.")
    if course_a["course"] == course_b["course"]:
        problems.append("As duas pecas da cruz estao na mesma fiada.")
    dot = course_a["x_dir"].DotProduct(course_b["x_dir"])
    if abs(dot) > BOND_PERPENDICULAR_DOT_TOLERANCE:
        problems.append("Pecas da cruz nao estao a 90 graus (dot={:.3f}).".format(dot))

    central_a = min(course_a["cells_world"], key=lambda c: (c["point"] - course_a["origin_world"]).GetLength()) \
        if course_a["cells_world"] else None
    central_b = min(course_b["cells_world"], key=lambda c: (c["point"] - course_b["origin_world"]).GetLength()) \
        if course_b["cells_world"] else None
    if central_a is None or central_b is None:
        problems.append("Peca sem celulas legiveis - nao da' para validar a celula central.")
    else:
        dist_ft = central_a["point"].DistanceTo(central_b["point"])
        if dist_ft > tolerance_ft:
            problems.append("Celulas centrais dos dois B54 nao ficam alinhadas (dist={:.2f}cm)."
                            .format(dist_ft / FEET_PER_METER * 100.0))

    return {"ok": not problems, "problems": problems}


def collisions_between(candidates, others, eps_ft=BOND_COLLISION_EPS_FT):
    """Pares (indice em `candidates`, indice em `others`) que colidem na
    MESMA fiada. Complementa `validate_same_course_collision`, que compara
    TODOS contra TODOS: aqui so' interessa "o que acabei de lancar nesta
    parede bate em alguma coisa que ja' estava la'", que e' O(n*m) em vez
    de O((n+m)^2) - e' o que torna viavel checar colisao a cada parede (e
    a cada tentativa de ajuste) em vez de so' uma vez no fim."""
    found = []
    if not candidates or not others:
        return found

    # DESEMPENHO (2026-08-27): antes, CADA par (i, j) reconstruia os dois
    # OBB do zero - 8 XYZ novos por par, com a peca `i` remontada `m` vezes
    # e a peca `j` remontada `n` vezes. Agora cada OBB e' construido UMA vez
    # por chamada, e um indice espacial (por FIADA, mesma ideia de
    # `_collision_candidate_pairs`) evita comparar pecas que estao longe
    # demais para se tocarem. Esta funcao roda uma vez por parede POR
    # TENTATIVA de ajuste, entao era o segundo maior custo do Solver 18
    # depois de `validate_same_course_collision`. Os pares devolvidos - e a
    # ORDEM deles (i crescente, j crescente dentro de cada i) - continuam
    # exatamente os do laco duplo.
    other_obbs = [_candidate_obb(o) for o in others]
    other_boxes = [_obb_aabb(obb) for obb in other_obbs]
    margin_ft = abs(eps_ft)

    cell = COLLISION_GRID_MIN_CELL_FT
    for x0, y0, x1, y1 in other_boxes:
        span = x1 - x0
        if span > cell:
            cell = span
        span = y1 - y0
        if span > cell:
            cell = span
    cell += margin_ft

    floor = math.floor
    grid = {}
    for j, other in enumerate(others):
        x0, y0, x1, y1 = other_boxes[j]
        course = other["course"]
        for gx in range(int(floor((x0 - margin_ft) / cell)),
                        int(floor((x1 + margin_ft) / cell)) + 1):
            for gy in range(int(floor((y0 - margin_ft) / cell)),
                            int(floor((y1 + margin_ft) / cell)) + 1):
                key = (course, gx, gy)
                bucket = grid.get(key)
                if bucket is None:
                    grid[key] = [j]
                else:
                    bucket.append(j)

    for i, cand in enumerate(candidates):
        obb_i = _candidate_obb(cand)
        ax0, ay0, ax1, ay1 = _obb_aabb(obb_i)
        ax0 -= margin_ft
        ay0 -= margin_ft
        ax1 += margin_ft
        ay1 += margin_ft
        course = cand["course"]
        node_index = cand.get("node_index")
        nearby = set()
        for gx in range(int(floor(ax0 / cell)), int(floor(ax1 / cell)) + 1):
            for gy in range(int(floor(ay0 / cell)), int(floor(ay1 / cell)) + 1):
                bucket = grid.get((course, gx, gy))
                if bucket:
                    nearby.update(bucket)
        if not nearby:
            continue
        for j in sorted(nearby):
            other = others[j]
            if cand is other:
                continue
            if node_index is not None and node_index == other.get("node_index"):
                continue
            bx0, by0, bx1, by1 = other_boxes[j]
            if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                continue
            if _obb_overlap(obb_i, other_obbs[j], eps_ft):
                found.append((i, j))
    return found


# ==========================================
# ZONA DE EXCLUSAO ABSOLUTA - VAO DE PORTA SEM PEITORIL (pedido explicito do
# usuario, 2026-08-21): "e' extremamente proibido posicionar qualquer bloco
# dentro do vao de portas que nao possuem peitoril... nenhum bloco,
# compensador ou pastilha [pode ser] inserido nessa regiao".
#
# O restante do pipeline (jambs de abertura + preenchimento comum, ver
# solve_wall_free_fill) ja' foi desenhado para NUNCA colocar candidatos
# dentro de [t_lo, t_hi] de uma abertura - mas essa e' uma garantia
# IMPLICITA (decorre de como os trechos livres sao calculados). A funcao
# abaixo e' uma REDE DE SEGURANCA EXPLICITA, geometrica (nao confia na
# logica de fronteiras de trechos): mede a sobreposicao real, em planta,
# entre o OBB de cada candidato e o vao real da porta - se algo escapar por
# qualquer caminho do solver (encontro L/T/X, jamb, preenchimento), aparece
# aqui como violacao detectada, nunca em silencio.
# ==========================================

# Peitoril (cm acima da base do nivel) ate' o qual uma abertura conta como
# "porta sem peitoril" para esta regra - portas reais tem peitoril 0 (vao
# ate' o piso); um pouco de folga absorve ruido de leitura do parametro
# Peitoril da familia real.
DOOR_NO_SILL_MAX_SILL_CM = 1.0
DOOR_NO_SILL_MAX_SILL_FT = DOOR_NO_SILL_MAX_SILL_CM / 100.0 * FEET_PER_METER


def _is_door_without_sill(sill_z_abs, base_z_abs):
    """True se o peitoril desta abertura estiver praticamente no piso (vao
    ate' o chao - a definicao de "porta sem peitoril" do usuario), dentro
    de DOOR_NO_SILL_MAX_SILL_FT. Uma janela (peitoril > 0 de verdade) nunca
    entra nesta regra - so' as portas."""
    return (sill_z_abs - base_z_abs) <= DOOR_NO_SILL_MAX_SILL_FT


def _door_void_obb(wall_idx, walls_to_create, t_lo_ft, t_hi_ft):
    """OBB (em planta) do vao real de uma abertura - mesma largura
    [t_lo_ft, t_hi_ft] e espessura da parede, no eixo local dela. Usado
    so' para medir sobreposicao com candidatos de bloco (ver
    find_door_void_violations), nunca para posicionar nada."""
    centerline, thickness_ft, _locks = walls_to_create[wall_idx]
    p0 = centerline.GetEndPoint(0)
    x_dir = XYZ(centerline.Direction.X, centerline.Direction.Y, 0.0).Normalize()
    y_dir = _perp_dir(x_dir)
    mid_t = (t_lo_ft + t_hi_ft) / 2.0
    center = XYZ(p0.X + x_dir.X * mid_t, p0.Y + x_dir.Y * mid_t, 0.0)
    return _obb_2d(center, (t_hi_ft - t_lo_ft) / 2.0, thickness_ft / 2.0, x_dir, y_dir)


def find_door_void_violations(candidates, walls_to_create, openings_per_wall, base_z_abs,
                              eps_ft=BOND_COLLISION_EPS_FT):
    """Varre TODAS as portas sem peitoril de `openings_per_wall` e devolve
    a lista de violacoes reais - candidato de bloco cujo OBB invade o vao
    real da porta alem de `eps_ft` (mesma tolerancia de toque/junta que
    `collisions_between` usa, para nao acusar um encoste raspando como
    violacao). Lista vazia significa "nenhuma violacao encontrada" - o
    caso esperado, ja que o resto do pipeline JA evita isso por
    construcao; esta funcao existe para PROVAR isso, nao para corrigir
    nada (nenhum candidato e' alterado aqui).

    Cada violacao: {"wall_idx", "opening_index", "candidate", "overlap_cm"}."""
    violations = []
    # DESEMPENHO (2026-08-27): UMA passada montando o indice parede ->
    # pecas, em vez de reler a lista INTEIRA de candidatos uma vez por
    # parede (que era O(paredes x pecas) - com 306 eixos e ~18k pecas, ~5.5
    # milhoes de leituras so' para descobrir de quem e' cada peca). Mesmo
    # criterio de antes: a peca conta para a parede "dona" (`wall_idx`) E
    # para a secundaria de um encontro (`secondary_wall_idx`).
    candidates_by_wall = {}
    for cand in candidates:
        for key in ("wall_idx", "secondary_wall_idx"):
            idx = cand.get(key)
            if idx is None:
                continue
            bucket = candidates_by_wall.get(idx)
            if bucket is None:
                candidates_by_wall[idx] = [cand]
            elif bucket[-1] is not cand:
                # `wall_idx == secondary_wall_idx` (peca cujas duas paredes
                # sao a mesma) nao pode entrar duas vezes no mesmo balde.
                bucket.append(cand)

    for wall_idx, openings in enumerate(openings_per_wall):
        if wall_idx >= len(walls_to_create):
            continue
        same_wall_candidates = candidates_by_wall.get(wall_idx)
        if not same_wall_candidates:
            continue
        for opening_index, (t_lo, t_hi, sill_z_abs, _head_z_abs) in enumerate(openings):
            if not _is_door_without_sill(sill_z_abs, base_z_abs):
                continue  # janela (tem peitoril de verdade) - fora do escopo desta regra
            void_obb = _door_void_obb(wall_idx, walls_to_create, t_lo, t_hi)
            for candidate in same_wall_candidates:
                overlap_ft = _obb_min_overlap(_candidate_obb(candidate), void_obb)
                if overlap_ft > eps_ft:
                    violations.append({
                        "wall_idx": wall_idx, "opening_index": opening_index,
                        "candidate": candidate,
                        "overlap_cm": overlap_ft / FEET_PER_METER * 100.0,
                    })
    return violations


def candidates_near_wall(candidates, wall_p0, wall_dir, wall_length_ft, reach_ft):
    """So' os candidatos que podem, geometricamente, encostar nesta parede -
    pre-filtro barato (projecao no eixo + distancia perpendicular) para a
    checagem de colisao nao varrer a planta inteira a cada tentativa."""
    near = []
    for cand in candidates:
        offset = cand["origin_world"] - wall_p0
        along = offset.DotProduct(wall_dir)
        if along < -reach_ft or along > wall_length_ft + reach_ft:
            continue
        perpendicular = offset - wall_dir * along
        if abs(perpendicular.GetLength()) > reach_ft:
            continue
        near.append(cand)
    return near


# Lado MINIMO da celula do indice espacial de `_collision_candidate_pairs`
# (ft). O lado real e' o maior lado de AABB do proprio lote (mais a
# margem), para que nenhuma peca ocupe mais de 2x2 celulas; este piso so'
# evita uma grade absurdamente fina num lote degenerado de pecas
# minusculas. Qualquer valor daria o MESMO resultado (a corretude nao
# depende do lado - ver docstring); o valor so' regula memoria x varredura.
COLLISION_GRID_MIN_CELL_FT = 20.0 / 100.0 * FEET_PER_METER


def _collision_candidate_pairs(indexes, boxes, margin_ft):
    """Pares (i, j), i < j, de `indexes` cujas AABB (lidas de `boxes`, uma
    por indice) estao a menos de `margin_ft` uma da outra - ou seja, TODO
    par que ainda tem chance de colidir, nunca menos.

    Substitui a varredura "todos contra todos" O(n^2) por um indice
    espacial em grade uniforme: cada peca entra em TODAS as celulas que sua
    AABB (dilatada pela margem) cobre, e so' pecas que dividem alguma
    celula sao comparadas. Isso NAO e' uma heuristica - duas AABB que se
    tocam tem intersecao nao vazia, e todo ponto dessa intersecao cai em
    alguma celula coberta pelas DUAS, entao o par sempre aparece em pelo
    menos um balde. O conjunto devolvido e' exatamente o mesmo que o laco
    duplo produzia, so' que sem visitar os pares distantes (que numa planta
    real sao a esmagadora maioria: pecas em paredes a dezenas de metros de
    distancia nunca poderiam se tocar).

    CAUSA-RAIZ do travamento relatado em producao (2026-08-27, planta de
    306 eixos): com ~12k pecas por banda, o laco duplo fazia ~70 milhoes de
    pares POR BANDA - medido em profiler, 95% do tempo total do Solver 18
    ficava aqui, todo ele DEPOIS da ultima parede processada (por isso a
    barra travava em 99%/"nao esta respondendo")."""
    if len(indexes) < 2:
        return []
    cell = COLLISION_GRID_MIN_CELL_FT
    for k in indexes:
        x0, y0, x1, y1 = boxes[k]
        span = x1 - x0
        if span > cell:
            cell = span
        span = y1 - y0
        if span > cell:
            cell = span
    cell += margin_ft

    grid = {}
    floor = math.floor
    for k in indexes:
        x0, y0, x1, y1 = boxes[k]
        gx0 = int(floor((x0 - margin_ft) / cell))
        gx1 = int(floor((x1 + margin_ft) / cell))
        gy0 = int(floor((y0 - margin_ft) / cell))
        gy1 = int(floor((y1 + margin_ft) / cell))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                key = (gx, gy)
                bucket = grid.get(key)
                if bucket is None:
                    grid[key] = [k]
                else:
                    bucket.append(k)

    pairs = set()
    for bucket in grid.values():
        count = len(bucket)
        if count < 2:
            continue
        for a in range(count):
            ia = bucket[a]
            ax0, ay0, ax1, ay1 = boxes[ia]
            ax0 -= margin_ft
            ay0 -= margin_ft
            ax1 += margin_ft
            ay1 += margin_ft
            for b in range(a + 1, count):
                ib = bucket[b]
                bx0, by0, bx1, by1 = boxes[ib]
                if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                    continue
                pairs.add((ia, ib) if ia < ib else (ib, ia))
    return pairs


# Lado da celula (ft) do indice espacial de pecas JA LANCADAS
# (`_placed_index_*`). 1m e' um pouco maior que WALL_COLLISION_REACH_CM
# (80cm), entao a consulta de uma parede toca poucas celulas por metro de
# eixo. Como em `_collision_candidate_pairs`, o valor NAO muda o resultado -
# so' o equilibrio entre numero de baldes e tamanho de cada um.
PLACED_INDEX_CELL_FT = 100.0 / 100.0 * FEET_PER_METER


def _placed_index_new():
    """Indice espacial INCREMENTAL das pecas ja' lancadas, para
    `_placed_index_near_wall`.

    `items` guarda as pecas na MESMA ordem em que entraram (a ordem de
    `all_candidates` em `process_walls_one_by_one`) e `cells` mapeia
    celula da grade -> posicoes em `items`, pela ORIGEM da peca (que e'
    exatamente o ponto que `candidates_near_wall` testa)."""
    return {"cells": {}, "items": []}


def _placed_index_add(index, candidates):
    """Acrescenta `candidates` ao indice, preservando a ordem de chegada."""
    cells = index["cells"]
    items = index["items"]
    floor = math.floor
    for cand in candidates:
        position = len(items)
        items.append(cand)
        origin = cand["origin_world"]
        key = (int(floor(origin.X / PLACED_INDEX_CELL_FT)),
               int(floor(origin.Y / PLACED_INDEX_CELL_FT)))
        bucket = cells.get(key)
        if bucket is None:
            cells[key] = [position]
        else:
            bucket.append(position)
    return index


def _placed_index_near_wall(index, wall_p0, wall_dir, wall_length_ft, reach_ft,
                            exclude_wall_idx=None):
    """As pecas do indice que podem encostar nesta parede, EXCLUINDO as da
    propria `exclude_wall_idx` - o mesmo conjunto, na mesma ordem, que
    `candidates_near_wall(...)` devolveria varrendo a lista inteira.

    DESEMPENHO (2026-08-27): `process_walls_one_by_one` refazia, A CADA
    PAREDE, uma copia filtrada de TODOS os candidatos ja' lancados e depois
    passava a lista inteira por `candidates_near_wall` - O(paredes x pecas),
    com conta vetorial (subtracao + DotProduct + GetLength) em cada peca.
    Como `all_candidates` cresce a cada parede processada, o custo por
    parede subia ao longo do laco: as ULTIMAS paredes da planta eram, de
    longe, as mais lentas (a queixa real de "demora muito na etapa final").
    Aqui so' as celulas cobertas pelo proprio eixo (dilatado por `reach_ft`)
    sao lidas - o resto da planta nem e' tocado.

    CORRETUDE: toda peca aprovada por `candidates_near_wall` tem projecao no
    eixo dentro de [-reach, comprimento+reach] e distancia perpendicular
    <= reach, logo sua ORIGEM esta' dentro da caixa do eixo dilatada por
    `reach_ft` - que e' exatamente a regiao consultada. O conjunto lido e'
    um SUPERconjunto, e o teste exato de `candidates_near_wall` roda por
    cima dele; as posicoes sao ordenadas antes para a lista sair na mesma
    ordem de insercao de antes."""
    cells = index["cells"]
    items = index["items"]
    if not items:
        return []
    p1 = wall_p0 + wall_dir * wall_length_ft
    x_lo = min(wall_p0.X, p1.X) - reach_ft
    x_hi = max(wall_p0.X, p1.X) + reach_ft
    y_lo = min(wall_p0.Y, p1.Y) - reach_ft
    y_hi = max(wall_p0.Y, p1.Y) + reach_ft
    floor = math.floor
    positions = []
    for gx in range(int(floor(x_lo / PLACED_INDEX_CELL_FT)),
                    int(floor(x_hi / PLACED_INDEX_CELL_FT)) + 1):
        for gy in range(int(floor(y_lo / PLACED_INDEX_CELL_FT)),
                        int(floor(y_hi / PLACED_INDEX_CELL_FT)) + 1):
            bucket = cells.get((gx, gy))
            if bucket:
                positions.extend(bucket)
    if not positions:
        return []
    positions.sort()
    nearby = []
    for position in positions:
        cand = items[position]
        if exclude_wall_idx is not None and cand.get("wall_idx") == exclude_wall_idx:
            continue
        nearby.append(cand)
    return candidates_near_wall(nearby, wall_p0, wall_dir, wall_length_ft, reach_ft)


def validate_same_course_collision(candidates, eps_ft=BOND_COLLISION_EPS_FT):
    """Secao 19 do prompt: nenhum par de candidatos da MESMA fiada pode
    colidir (interpenetracao solida) - sobreposicao entre fiadas
    DIFERENTES e' esperada (e' a propria amarracao). Candidatos do MESMO
    no' (ex.: nao deveria acontecer hoje, mas protege o futuro preenchimento
    da Etapa 6 reusando esta funcao) nunca contam como colisao entre si.

    Devolve a lista de pares de INDICES (i, j) em `candidates` que colidem,
    ordenada por (i, j) - vazia significa nenhuma colisao encontrada.

    DESEMPENHO (2026-08-27): o filtro por fiada e o pre-filtro geometrico
    saem na frente do SAT (`_obb_overlap`), que e' de longe a parte cara -
    primeiro separa as pecas por FIADA (pecas de fiadas diferentes nunca
    colidem entre si, entao nem entram no mesmo lote), depois usa o indice
    espacial de `_collision_candidate_pairs` dentro de cada lote. As REGRAS
    testadas (mesma fiada, mesmo no' isento, SAT com `eps_ft`) e o
    resultado sao exatamente os de antes; so' os pares que nao tinham como
    colidir deixaram de ser visitados."""
    collisions = []
    if len(candidates) < 2:
        return collisions

    obbs = [_candidate_obb(c) for c in candidates]
    boxes = [_obb_aabb(obb) for obb in obbs]

    by_course = {}
    for i, cand in enumerate(candidates):
        course = cand["course"]
        bucket = by_course.get(course)
        if bucket is None:
            by_course[course] = [i]
        else:
            bucket.append(i)

    # `eps_ft` pode ser negativo (ver `_obb_overlap`: tolerancia negativa
    # aceita uma folga pequena como "sobreposto o suficiente"), e nesse caso
    # o pre-filtro precisa ser MAIS folgado, nao mais apertado - por isso o
    # valor absoluto.
    margin_ft = abs(eps_ft)
    for indexes in by_course.values():
        for i, j in _collision_candidate_pairs(indexes, boxes, margin_ft):
            node_index = candidates[i].get("node_index")
            if node_index is not None and node_index == candidates[j].get("node_index"):
                continue
            if _obb_overlap(obbs[i], obbs[j], eps_ft):
                collisions.append((i, j))
    collisions.sort()
    return collisions


def describe_block_candidate(candidate):
    """Texto de debug de UM candidato, no formato pedido pela secao 25 do
    prompt ('B54 / Wall: 127 / Course: A / Reason: ... / Node: 42 /
    Rotation: 90')."""
    return (
        "{code}\n"
        "Wall: {wall}\n"
        "Course: {course}\n"
        "Reason: {reason}\n"
        "Node: {node}\n"
        "Rotation: {rot:.0f} graus"
    ).format(
        code=candidate["logical_code"],
        wall=candidate.get("wall_idx"),
        course=candidate["course"],
        reason=candidate["placement_reason"],
        node=candidate.get("node_index"),
        rot=candidate["rotation_deg"],
    )


def _format_world_point_cm(point):
    """'(X, Y)cm' a partir de um XYZ em pes - usado para dar ao usuario uma
    coordenada localizavel (ex.: colar no campo de coordenadas do Revit ou
    comparar com o CAD) quando ainda nao existe nenhum ElementId real para
    zoom (candidatos de bloco so' viram Wall/FamilyInstance depois do passo
    "criar no Revit")."""
    ft_to_cm = 100.0 / FEET_PER_METER
    return "({:.1f}, {:.1f})cm".format(point.X * ft_to_cm, point.Y * ft_to_cm)


def describe_block_candidate_oneline(candidate):
    """Como `describe_block_candidate`, mas compacto numa linha so' - usado
    para listar VARIOS candidatos (ex.: um par em colisao) sem inflar o
    relatorio com 5 linhas por peca."""
    return "{code} (parede {wall}, fiada {course}, {reason}) em {pos}".format(
        code=candidate["logical_code"],
        wall=candidate.get("wall_idx"),
        course=candidate["course"],
        reason=candidate.get("placement_reason", "?"),
        pos=_format_world_point_cm(candidate["origin_world"]),
    )


# ==========================================
# ETAPA 5 - JAMBS DE ABERTURA (OpeningJambSolver)
#
# Resolve o bloco que encosta em CADA lado (LEFT_JAMB/RIGHT_JAMB, secao 13
# do prompt) de cada abertura, nas duas fiadas, e valida se os VAZIOS
# desses blocos ficam alinhados entre as fiadas (secao 14) - a mesma ideia
# de amarracao da Etapa 4, so' que aqui o "encontro" e' bloco-contra-vao em
# vez de bloco-contra-bloco, e por isso reusa toda a infraestrutura de
# candidato/celula/OBB ja' construida ali
# (_asymmetric_bond_origin_and_axis, _make_block_candidate, CELL_ALIGNMENT_
# TOLERANCE_FT).
#
# Junta ZERO contra a abertura (BLOCK_OPENING_JOINT_CM) e junta normal
# (BLOCK_JOINT_CM) contra o proximo bloco/no' - por isso QUALQUER peca do
# catalogo (exceto as de amarracao especial B34/B54, reservadas para a
# Etapa 4) pode ser o bloco do jamb, desde que o RESTO do pilarete depois
# dela ainda feche em blocos (ver pack_pier_with_blocks, ja' existente).
#
# ACHADO IMPORTANTE (nao e' limitacao, e' consequencia da propria geometria
# medida na Etapa 4): como o bloco do jamb sempre encosta no MESMO ponto
# (o vao) com a MESMA convencao de orientacao, usar o MESMO codigo de peca
# nas duas fiadas SEMPRE alinha perfeitamente (celula identica, mesma
# posicao relativa ao vao) - entao a excecao de alinhamento (secao 14) so'
# pode acontecer quando NENHUM bloco do catalogo fecha o pilarete (nao
# quando blocos fecham mas desalinham). O desencontro de juntas verticais
# entre fiadas (secao 6) continua existindo mais adiante no pilarete (fora
# do escopo desta etapa) - a secao 6 do prompt da' prioridade menor a isso
# do que a jambas/encontros (ver ordem da secao 6: "1. encontros L/T/X; 2.
# aberturas; ..."), entao alinhar o jamb primeiro, mesmo que replique o
# mesmo bloco nas duas fiadas ali, esta' de acordo com a prioridade pedida
# - a Etapa 6 (preenchimento) e' quem cuida do desencontro no resto do
# pilarete.
# ==========================================

# Pilaretes menores que isto (cm) sao tratados como "sem jamb" (a abertura
# encosta direto no no'/na abertura vizinha) em vez de reportar uma
# excecao - cobre so' ruido geometrico, nao um pilarete genuinamente
# pequeno mas real (que ainda cai nas regras normais de PIER_MODULE_CM).
OPENING_JAMB_MIN_PIER_CM = 0.5

# Pecas do catalogo elegiveis para SER o bloco do jamb - as de amarracao
# especial (B34/B54) ficam reservadas para os encontros da Etapa 4 (ver
# comentario da secao ETAPA 1, "B54 ... NAO entra no preenchimento comum de
# fiada"). Ordem = ordem de PREFERENCIA (secao 7: maximizar B39, minimizar
# B19, minimizar compensadores) - quem chama nao precisa reordenar.
OPENING_JAMB_BLOCK_CODES = ("B39", "B19", "C09", "C04")

# REGRA CRITICA #1 (excecao), pedido explicito do usuario (2026-08-24):
# junta vertical coincidente entre fiadas SO' pode ser tolerada perto de
# aberturas quando a peca envolvida for PEQUENA (4/9/19cm) - blocos
# principais (34/39cm) NUNCA podem gerar junta continua entre fiadas,
# nem mesmo nesta excecao. Comprimentos, nao nomes de codigo (generico
# para qualquer catalogo/familia que venha a ser usada).
JOINT_ALIGNMENT_EXCEPTION_LENGTHS_CM = (4.0, 9.0, 19.0)


def _is_small_joint_exception_code(code, catalog, tolerance_cm=0.5):
    """True se `code` (do catalogo) tiver comprimento dentro da lista de
    pecas PEQUENAS que a excecao da regra critica #1 permite alinhar
    entre fiadas perto de aberturas (ver JOINT_ALIGNMENT_EXCEPTION_LENGTHS_CM).
    Blocos principais (34/39cm) devolvem False - nunca se qualificam para
    a excecao, mesmo que sejam a UNICA combinacao que fecha o pilarete."""
    entry = catalog.get(code) or {}
    length_cm = entry.get("length_cm")
    if length_cm is None:
        return False
    return any(abs(length_cm - v) <= tolerance_cm for v in JOINT_ALIGNMENT_EXCEPTION_LENGTHS_CM)


def _opening_side_pier_length_ft(openings_sorted, total_len_ft, opening_index, side):
    """Comprimento (ft) do trecho de parede entre a abertura
    `openings_sorted[opening_index]` (lista de (t_lo, t_hi, sill, head),
    MESMO formato de assign_openings_to_walls, ja' ordenada por t_lo) e o
    proximo obstaculo em `side` ("left" ou "right") - a abertura vizinha
    mais proxima nesse lado, ou a propria ponta da parede se nao houver
    mais nenhuma abertura ali. Implementa a divisao "no' -> abertura,
    abertura -> abertura, abertura -> no'" da secao 13 do prompt, so' que
    calculando diretamente o comprimento de cada trecho (o que a Etapa 5
    precisa), sem materializar uma lista de segmentos completa (isso fica
    para a Etapa 6, que tambem precisa dos trechos SEM abertura nenhuma)."""
    t_lo, t_hi, _sill, _head = openings_sorted[opening_index]
    if side == "left":
        if opening_index == 0:
            return t_lo
        prev_t_hi = openings_sorted[opening_index - 1][1]
        return t_lo - prev_t_hi
    if opening_index == len(openings_sorted) - 1:
        return total_len_ft - t_hi
    next_t_lo = openings_sorted[opening_index + 1][0]
    return next_t_lo - t_hi


def _opening_jamb_point_and_dir(walls_to_create, wall_idx, t_value, side):
    """Ponto de mundo (Z=0) no parametro `t_value` (ft, desde p0) do eixo
    de `wall_idx`, e a direcao unitaria que se AFASTA da abertura ao longo
    da parede nesse lado ("left" -> sentido -direcao do eixo, "right" ->
    sentido +direcao) - o mesmo papel de `dir_away` que
    _wall_end_and_dir_near_point tem na Etapa 4, aqui calculado a partir de
    um `t` no MEIO do eixo (a abertura), nao de uma ponta real da parede."""
    p0, _p1, direction, _length, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
    point = p0 + direction * t_value
    dir_away = direction.Negate() if side == "left" else direction
    return point, dir_away


def _pier_first_block_candidates(pier_cm, catalog, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT):
    """Codigos de OPENING_JAMB_BLOCK_CODES (em ordem de preferencia) que
    podem ser o PRIMEIRO bloco de um pilarete de `pier_cm` - o bloco que
    encosta na abertura, junta ZERO desse lado - deixando um RESTO que
    ainda feche em blocos (via pack_pier_with_blocks, contando a junta que
    fica entre este bloco e o resto do pilarete). Lista vazia significa
    que NENHUM bloco do catalogo fecha este pilarete."""
    candidates = []
    for code in OPENING_JAMB_BLOCK_CODES:
        entry = catalog.get(code)
        if entry is None or not entry.get("length_cm"):
            continue
        if entry.get("is_compensator") and not allow_compensators:
            continue
        block_cm = entry["length_cm"]
        remaining = pier_cm - (block_cm + BLOCK_JOINT_CM)
        if remaining < -1e-6:
            continue
        if abs(remaining) <= 1e-6:
            candidates.append(code)
            continue
        blocks, leftover = pack_pier_with_blocks(remaining)
        if blocks is not None and abs(leftover) <= 1e-6:
            candidates.append(code)
    return candidates


def _nearest_cell_to_point(candidate, point):
    """A celula (de `candidate["cells_world"]`) mais proxima de `point` -
    usada para achar o vazio "relevante" (o que fica voltado para a
    abertura) de um bloco de jamb. None se a peca nao tiver celulas
    (compensador macico) - nesse caso nao ha' vazio para desalinhar."""
    cells = candidate.get("cells_world") or []
    if not cells:
        return None
    return min(cells, key=lambda c: c["point"].DistanceTo(point))


# ETAPA 4/11.7 (2026-08-25, ver REGRAS_MODULACAO_BLOCOS.md secao 11.7):
# quantas variacoes FISICAMENTE DISTINTAS de bloco de jamb cada familia
# de fiada (par/impar) precisa para nao cair na MESMA posicao de junta em
# toda fiada da familia - mesma constante conceitual de
# PIER_LAYOUT_VARIANTS_PER_COURSE (ver comentario la'), aplicada aqui
# porque o jamb e' resolvido por uma busca PROPRIA (_pier_first_block_
# candidates + alinhamento de celula), independente do preenchimento
# comum (_pier_ordered_layout/_pier_layout_avoiding_joints).
def _jamb_build_course_variants(catalog, first_options, code_a, code_b, point, dir_away,
                                reason_code, node_index, wall_idx, variant_count):
    """Gera ate' `variant_count` variacoes por familia (par/impar) do
    bloco de jamb, a partir do MESMO pool de codigos que a busca de
    alinhamento de `solve_opening_jamb` ja considerou (`first_options` -
    ver _pier_first_block_candidates). A variante 0 de cada familia e'
    SEMPRE o par (code_a, code_b) que a busca de alinhamento escolheu
    (nunca muda o resultado ja' validado, nem os testes que o conferem
    diretamente via jamb["course_a"]/["course_b"]); as demais preferem
    codigos AINDA NAO usados por NENHUMA das duas familias (generaliza a
    REGRA CRITICA #1 - "bloco principal igual no mesmo lugar e' junta
    continua proibida" - de um unico par A/B para todo par cruzado entre
    variantes). Quando o pilarete so' fecha com 1-2 codigos do catalogo
    (`first_options` curto), repete o ultimo codigo disponivel dentro da
    propria familia - caso residual documentado (pilarete fisicamente
    pequeno demais para variar mais que isso; NUNCA inventa geometria que
    o catalogo nao suporta)."""
    codes_a = [code_a]
    codes_b = [code_b]
    used = {code_a, code_b}
    pool_i = 0
    while len(codes_a) < variant_count or len(codes_b) < variant_count:
        candidate_code = None
        while pool_i < len(first_options):
            c = first_options[pool_i]
            pool_i += 1
            if c not in used:
                candidate_code = c
                break
        if candidate_code is None:
            # Pool esgotado sem nenhum codigo inedito - repete o ultimo de
            # cada familia que ainda precisa completar (caso residual, ver
            # docstring acima).
            if len(codes_a) < variant_count:
                codes_a.append(codes_a[-1])
            if len(codes_b) < variant_count:
                codes_b.append(codes_b[-1])
            continue
        used.add(candidate_code)
        if len(codes_a) <= len(codes_b) and len(codes_a) < variant_count:
            codes_a.append(candidate_code)
        elif len(codes_b) < variant_count:
            codes_b.append(candidate_code)
        else:
            codes_a.append(candidate_code)

    def _cands(codes, letter):
        out = []
        for code in codes[:variant_count]:
            entry = catalog[code]
            origin, x_dir = _asymmetric_bond_origin_and_axis(entry, point, dir_away, -1)
            out.append(_make_block_candidate(code, entry, letter, origin, x_dir, reason_code,
                                              node_index=node_index, wall_idx=wall_idx))
        return out

    return _cands(codes_a, "A"), _cands(codes_b, "B")


def solve_opening_jamb(walls_to_create, wall_idx, openings_sorted, opening_index, side, catalog,
                       allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                       node_index=None, variant_count=1):
    """Resolve o jamb (LEFT_JAMB ou RIGHT_JAMB) de UMA abertura, nas duas
    fiadas (secao 14 do prompt). Tenta TODAS as combinacoes (codigo_A,
    codigo_B) dentre os blocos validos para este pilarete (ver
    _pier_first_block_candidates), na ordem de preferencia de
    OPENING_JAMB_BLOCK_CODES, ate achar uma cuja celula mais proxima da
    abertura fique alinhada entre as fiadas (CELL_ALIGNMENT_TOLERANCE_FT).

    Devolve um dict:
        {"ok": bool, "exception": bool, "reason": str ou None,
         "course_a", "course_b": BlockPlacementCandidate ou None,
         "course_a_variants", "course_b_variants": [BlockPlacementCandidate
             ou None, ...] (comprimento `variant_count`, indice 0 e' SEMPRE
             igual a "course_a"/"course_b" - ver _jamb_build_course_variants,
             secao 11.7 do REGRAS_MODULACAO_BLOCOS.md),
         "offset_cm": float, "tried": [(codigo_A, codigo_B, offset_ft), ...]}

    `exception`=True cobre dois casos, cada um com "reason" proprio:
    nenhum bloco do catalogo fecha o pilarete, OU (na pratica nunca deveria
    acontecer com este catalogo - ver cabecalho da secao) nenhuma
    combinacao alinhou dentro da tolerancia - de qualquer forma, a MELHOR
    tentativa encontrada ainda vem em "course_a"/"course_b" (nunca None so'
    por causa da excecao), para a Etapa 6 poder usa-la mesmo assim, como a
    secao 14 pede ("nao esconder a falha", nao "recusar a solucao
    inteira"). Pilaretes praticamente nulos (ver OPENING_JAMB_MIN_PIER_CM)
    nao geram excecao nenhuma - nao ha' jamb ali porque a abertura encosta
    direto no' proximo obstaculo."""
    total_len_ft = walls_to_create[wall_idx][0].GetEndPoint(0).DistanceTo(
        walls_to_create[wall_idx][0].GetEndPoint(1)
    )
    pier_ft = _opening_side_pier_length_ft(openings_sorted, total_len_ft, opening_index, side)
    pier_cm = pier_ft / FEET_PER_METER * 100.0
    reason_code = "OPENING_LEFT_JAMB" if side == "left" else "OPENING_RIGHT_JAMB"

    if pier_cm < -OPENING_JAMB_MIN_PIER_CM:
        return {"ok": False, "exception": True,
                "reason": "Pilarete de comprimento negativo ({:.1f}cm) - a abertura "
                         "invade a vizinha ou o limite da parede.".format(pier_cm),
                "course_a": None, "course_b": None,
                "course_a_variants": [None] * variant_count, "course_b_variants": [None] * variant_count,
                "offset_cm": None, "tried": []}
    if pier_cm <= OPENING_JAMB_MIN_PIER_CM:
        return {"ok": True, "exception": False, "reason": None,
                "course_a": None, "course_b": None,
                "course_a_variants": [None] * variant_count, "course_b_variants": [None] * variant_count,
                "offset_cm": 0.0, "tried": []}

    point, dir_away = _opening_jamb_point_and_dir(walls_to_create, wall_idx,
                                                   openings_sorted[opening_index][0] if side == "left"
                                                   else openings_sorted[opening_index][1], side)

    first_options = _pier_first_block_candidates(pier_cm, catalog, allow_compensators)
    if not first_options:
        return {"ok": False, "exception": True,
                "reason": "Nenhum bloco do catalogo fecha este pilarete ({:.1f}cm).".format(pier_cm),
                "course_a": None, "course_b": None,
                "course_a_variants": [None] * variant_count, "course_b_variants": [None] * variant_count,
                "offset_cm": None, "tried": []}

    best = None            # melhor tentativa QUALQUER (para o relatorio de excecao)
    best_allowed = None    # melhor tentativa que RESPEITA a regra critica #1
    tried = []
    for code_a in first_options:
        entry_a = catalog[code_a]
        origin_a, x_a = _asymmetric_bond_origin_and_axis(entry_a, point, dir_away, -1)
        cand_a = _make_block_candidate(code_a, entry_a, "A", origin_a, x_a, reason_code,
                                       node_index=node_index, wall_idx=wall_idx)
        cell_a = _nearest_cell_to_point(cand_a, point)

        for code_b in first_options:
            entry_b = catalog[code_b]
            origin_b, x_b = _asymmetric_bond_origin_and_axis(entry_b, point, dir_away, -1)
            cand_b = _make_block_candidate(code_b, entry_b, "B", origin_b, x_b, reason_code,
                                           node_index=node_index, wall_idx=wall_idx)
            cell_b = _nearest_cell_to_point(cand_b, point)

            if cell_a is None or cell_b is None:
                offset_ft = 0.0  # peca(s) macica(s) - nada para desalinhar
            else:
                offset_ft = cell_a["point"].DistanceTo(cell_b["point"])

            tried.append((code_a, code_b, offset_ft))
            if best is None or offset_ft < best[0]:
                best = (offset_ft, cand_a, cand_b)

            # REGRA CRITICA #1 (excecao): duas pecas IGUAIS no mesmo lugar
            # alinham perfeitamente por construcao (mesma peca, mesma
            # posicao relativa ao vao) - so' e' uma excecao TOLERADA quando
            # a peca e' PEQUENA (4/9/19cm). Blocos principais (34/39cm)
            # repetidos nas duas fiadas criam junta continua PROIBIDA, mesmo
            # perto de abertura - nunca aceitos aqui, mesmo com offset 0.
            forbidden_main_block_coincidence = (
                code_a == code_b and not _is_small_joint_exception_code(code_a, catalog)
            )
            if forbidden_main_block_coincidence:
                continue
            if best_allowed is None or offset_ft < best_allowed[0]:
                best_allowed = (offset_ft, cand_a, cand_b)
            if offset_ft <= CELL_ALIGNMENT_TOLERANCE_FT:
                variants_a, variants_b = _jamb_build_course_variants(
                    catalog, first_options, code_a, code_b, point, dir_away,
                    reason_code, node_index, wall_idx, variant_count,
                )
                return {"ok": True, "exception": False, "reason": None,
                        "course_a": cand_a, "course_b": cand_b,
                        "course_a_variants": variants_a, "course_b_variants": variants_b,
                        "offset_cm": offset_ft / FEET_PER_METER * 100.0, "tried": tried}

    # Nenhuma combinacao permitida fechou dentro da tolerancia - usa a
    # melhor tentativa PERMITIDA se houver uma (ainda respeita a regra
    # critica #1), senao cai na melhor tentativa QUALQUER (so' resta a
    # coincidencia proibida de bloco principal - reportada com um motivo
    # especifico, para nao ser confundida com um simples desalinhamento).
    if best_allowed is not None:
        offset_ft, cand_a, cand_b = best_allowed
        variants_a, variants_b = _jamb_build_course_variants(
            catalog, first_options, cand_a["logical_code"], cand_b["logical_code"], point, dir_away,
            reason_code, node_index, wall_idx, variant_count,
        )
        return {
            "ok": False, "exception": True,
            "reason": "OPENING_CELL_ALIGNMENT_EXCEPTION: nenhuma combinacao de blocos de jamb "
                     "alinhou dentro de {:.1f}cm - melhor tentativa {}+{} com {:.2f}cm de desvio."
                     .format(CELL_ALIGNMENT_TOLERANCE_CM, cand_a["logical_code"], cand_b["logical_code"],
                             offset_ft / FEET_PER_METER * 100.0),
            "course_a": cand_a, "course_b": cand_b,
            "course_a_variants": variants_a, "course_b_variants": variants_b,
            "offset_cm": offset_ft / FEET_PER_METER * 100.0, "tried": tried,
        }

    offset_ft, cand_a, cand_b = best
    variants_a, variants_b = _jamb_build_course_variants(
        catalog, first_options, cand_a["logical_code"], cand_b["logical_code"], point, dir_away,
        reason_code, node_index, wall_idx, variant_count,
    )
    return {
        "ok": False, "exception": True,
        "course_a_variants": variants_a, "course_b_variants": variants_b,
        "reason": "JOINT_ALIGNMENT_FORBIDDEN_MAIN_BLOCK: so' fecha este pilarete repetindo o "
                 "bloco principal {} nas duas fiadas (junta vertical continua PROIBIDA pela "
                 "regra critica #1, mesmo perto de abertura) - requer ajuste de geometria "
                 "(deslocar abertura/parede) para liberar uma combinacao com pecas diferentes."
                 .format(cand_a["logical_code"]),
        "course_a": cand_a, "course_b": cand_b,
        "offset_cm": offset_ft / FEET_PER_METER * 100.0, "tried": tried,
    }


def solve_all_opening_jambs(walls_to_create, openings_per_wall, catalog, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT):
    """Roda solve_opening_jamb nos dois lados de TODAS as aberturas de
    TODAS as paredes (secao 13/32 do prompt: aberturas participam do
    solver ANTES do preenchimento comum). `openings_per_wall` e' a lista
    paralela a `walls_to_create` que assign_openings_to_walls devolve.

    Devolve {"candidates": [...], "exceptions": [...]}: `candidates` e' a
    lista PLANA de BlockPlacementCandidate (Fiada A + Fiada B por lado
    resolvido, pulando pilaretes praticamente nulos - ver
    OPENING_JAMB_MIN_PIER_CM); `exceptions` e' a lista dos resultados com
    `exception`=True (ver solve_opening_jamb), cada um ja' anotado com
    "wall_idx"/"opening_index"/"side" para o relatorio (secao 14/28)."""
    candidates = []
    exceptions = []
    for wall_idx, openings in enumerate(openings_per_wall):
        if not openings:
            continue
        openings_sorted = sorted(openings, key=lambda o: o[0])
        for opening_index in range(len(openings_sorted)):
            for side in ("left", "right"):
                result = solve_opening_jamb(
                    walls_to_create, wall_idx, openings_sorted, opening_index, side,
                    catalog, allow_compensators=allow_compensators,
                )
                result["wall_idx"] = wall_idx
                result["opening_index"] = opening_index
                result["side"] = side
                if result.get("course_a") is not None:
                    candidates.append(result["course_a"])
                    candidates.append(result["course_b"])
                if result.get("exception"):
                    exceptions.append(result)
    return {"candidates": candidates, "exceptions": exceptions}


def describe_opening_jamb_exception(result):
    """Texto de relatorio de UMA OPENING_CELL_ALIGNMENT_EXCEPTION (secao
    14 do prompt: parede, abertura, lado, deslocamento, alternativas
    testadas, motivo)."""
    tried_str = ", ".join(
        "{}+{}={:.2f}cm".format(a, b, off / FEET_PER_METER * 100.0)
        for a, b, off in result.get("tried", [])
    ) or "-"
    offset_cm = result.get("offset_cm")
    offset_str = "{:.2f}cm".format(offset_cm) if offset_cm is not None else "N/A"
    return (
        "OPENING_CELL_ALIGNMENT_EXCEPTION\n"
        "Wall: {wall}\n"
        "Abertura (indice na parede): {opening}\n"
        "Lado: {side}\n"
        "Desvio encontrado: {offset}\n"
        "Alternativas testadas: {tried}\n"
        "Motivo: {reason}"
    ).format(
        wall=result.get("wall_idx"),
        opening=result.get("opening_index"),
        side=result.get("side"),
        offset=offset_str,
        tried=tried_str,
        reason=result.get("reason"),
    )


# ==========================================
# ETAPA 4 (continuacao) - PREENCHIMENTO COMUM DOS TRECHOS LIVRES
#
# Depois de reservados os encontros (L/T/X, inclusive os de MEIO de parede -
# ver node_midspan_by_wall_course) e os jambs de abertura, o que sobra de
# cada parede - "no' -> abertura, abertura -> abertura, abertura -> no'"
# (secao 13) - precisa ser preenchido com B39/B19 (+ compensadores se
# autorizado), priorizando B39 (secao 7).
#
# Reusa a MESMA convencao de posicionamento das Etapas 4/5 (bloco
# posicionado pelo CENTRO, eixo local X = comprimento) e o mesmo modelo de
# junta de pack_pier_with_blocks (cada bloco "carrega" sua propria junta de
# saida); a novidade aqui e' contabilizar corretamente as juntas de
# CONTORNO (contra abertura = 0, contra no'/outro bloco = BLOCK_JOINT_CM,
# contra ponta livre = 0) dos dois lados de cada trecho - ver
# _pier_ordered_layout.
#
# DESENCONTRO DE JUNTA VERTICAL ENTRE FIADAS (secao 6 - "sempre que
# geometricamente possivel" evitar junta vertical continua entre fiadas
# consecutivas): a Fiada A de cada parede e' preenchida com o greedy PADRAO
# (maior bloco primeiro); a Fiada B reusa `_pier_ordered_layout(first_code=
# ...)` tentando cada bloco do catalogo como PRIMEIRO da fiada e escolhe a
# opcao cujas juntas internas (em coordenadas GLOBAIS ao longo da parede,
# nao so' dentro do mesmo trecho - um encontro de meio de parede pode dar
# fronteiras DIFERENTES para cada fiada) menos coincidem com as juntas ja'
# usadas pela Fiada A - ver `_pier_layout_avoiding_joints`. Nao ha' garantia
# de zero coincidencias (a propria secao 6 so' pede "sempre que
# geometricamente possivel"); quando nenhuma alternativa reduz o numero de
# coincidencias, mantem o layout padrao.
# ==========================================


# Codigo logico do meio-bloco (14x19x19cm) - ver regras de posicionamento
# abaixo. Pedido explicito do usuario (2026-08-21, com imagens de
# referencia de como ele modula manualmente): o B19 QUEBRA o ritmo/prisma
# da alvenaria (deslocamento de meia peca no ritmo de junta vertical do
# resto do trecho) e por isso NAO pode ser tratado como mais uma peca de
# preenchimento comum - so' entra quando nenhuma combinacao das outras
# pecas (B39 + compensadores) fecha o trecho, e mesmo assim so' encostado
# numa ponta ABERTA (abertura ou extremidade de parede sem amarracao -
# BLOCK_OPENING_JOINT_CM=0 dos dois lados), nunca espremido entre dois
# blocos no meio do trecho.
HALF_BLOCK_CODE = "B19"

# Codigo do bloco de amarracao especial (14x19x34cm) quando usado no
# PREENCHIMENTO COMUM de um trecho (nao so' em encontros L/T/X, onde ja era
# usado). Pedido explicito do usuario (2026-08-21): "o bloco de 34cm
# tambem pode ser utilizado no meio de uma parede... para reduzir o uso de
# compensadores", com prioridade B39 -> B19 -> B34 -> compensadores.
MID_WALL_BLOCK_CODE = "B34"

# Pool de codigos que o preenchimento comum (_pier_ordered_layout) pode
# usar - OPENING_JAMB_BLOCK_CODES (B39/B19/C09/C04, tambem usado pelos
# jambs de abertura) MAIS o B34 de meio-de-parede acima. Um pool proprio
# (nao altera OPENING_JAMB_BLOCK_CODES) para nao mudar o comportamento dos
# jambs, que o usuario nao pediu para alterar.
COMMON_FILL_BLOCK_CODES = OPENING_JAMB_BLOCK_CODES + (MID_WALL_BLOCK_CODE,)

# Quantos compensadores/pastilhas (C09/C04) um UNICO trecho pode usar antes
# de ser considerado "uma fileira repetitiva" - pedido explicito do usuario
# (2026-08-21): "evitar ao maximo o uso repetitivo de compensadores e
# pastilhas... nao podem virar uma solucao recorrente"; e depois reforcado:
# "extremamente proibido... duas pastilhas ou combinacoes consecutivas de
# compensadores... usados apenas de forma pontual, nunca em sequencia".
# Acima deste limite, `_pier_ordered_layout` prefere B34 e depois 1 UNICO
# meio-bloco (mesmo fora da ponta ideal) a uma sequencia de pecas pequenas.
MAX_COMPENSATORS_PER_TRECHO = 1


def _pier_codes_by_len_desc(catalog, allow_compensators, exclude=(), pool=OPENING_JAMB_BLOCK_CODES):
    """Codigos de `pool` disponiveis no catalogo, ordenados do MAIOR para o
    menor comprimento - o pool que o guloso de `_greedy_fill_blocks`
    percorre a cada passo. `exclude` tira codigos especificos do pool
    (usado para montar a tentativa "sem meio-bloco"); `pool` (default
    OPENING_JAMB_BLOCK_CODES, o mesmo de sempre) deixa o chamador usar um
    conjunto maior - ver COMMON_FILL_BLOCK_CODES, usado pelo preenchimento
    comum para incluir o B34 de meio-de-parede sem afetar os jambs."""
    return sorted(
        (c for c in pool if c in catalog and catalog[c].get("length_cm") and
         c not in exclude and
         (allow_compensators or not catalog[c].get("is_compensator"))),
        key=lambda c: -catalog[c]["length_cm"]
    )


def _greedy_fill_blocks(remaining, pos_cm, catalog, codes_by_len_desc, first_code=None):
    """Nucleo guloso (MAIOR bloco do pool que ainda cabe a cada passo):
    preenche `remaining` cm (ja' na convencao de `_pier_ordered_layout` -
    cada peca "carrega" sua propria junta de saida) a partir da posicao
    `pos_cm`, devolvendo a lista ORDENADA [(codigo, start_cm, end_cm), ...]
    ou None se o `codes_by_len_desc` dado nao fechar esse resto
    EXATAMENTE. `first_code` (quando presente no pool) forca o primeiro
    bloco escolhido. Extraida de `_pier_ordered_layout` para ser reusada
    tanto na tentativa "sem meio-bloco" quanto nos dois lados de uma
    sequencia que teve o meio-bloco reservado manualmente numa ponta (ver
    `_pier_ordered_layout`)."""
    if remaining <= 1e-6:
        return []
    if not codes_by_len_desc:
        return None
    layout = []
    pending_first = first_code if first_code in codes_by_len_desc else None
    guard = 0
    while remaining > 1e-6:
        guard += 1
        if guard > 10000:
            return None  # protecao - nao deveria acontecer (prova da secao 3)
        chosen = None
        if pending_first is not None:
            if catalog[pending_first]["length_cm"] + BLOCK_JOINT_CM <= remaining + 1e-6:
                chosen = pending_first
            pending_first = None
        if chosen is None:
            for code in codes_by_len_desc:
                if catalog[code]["length_cm"] + BLOCK_JOINT_CM <= remaining + 1e-6:
                    chosen = code
                    break
        if chosen is None:
            return None
        block_cm = catalog[chosen]["length_cm"]
        layout.append((chosen, pos_cm, pos_cm + block_cm))
        pos_cm += block_cm + BLOCK_JOINT_CM
        remaining -= block_cm + BLOCK_JOINT_CM
    return layout


def _greedy_fill_blocks_any_first(remaining, pos_cm, catalog, codes_by_len_desc, first_code=None):
    """`_greedy_fill_blocks` com uma segunda chance: quando o guloso PURO
    nao fecha o resto exatamente (e o chamador nao impos um `first_code`),
    tenta cada codigo do pool como PRIMEIRO bloco antes de desistir.

    Motivo (bug real medido ao vivo via MCP, 2026-08-28): o guloso pega
    sempre a maior peca que ainda cabe e nunca volta atras, entao ele
    falha em trechos que SO' fecham com uma peca menor mais cedo. Caso
    real, trecho de 469cm entre dois encontros (pool B39+B34, tier 3):
    o guloso puro poe 11xB39, sobra 29cm, o B34 nao cabe mais e o tier 3
    inteiro devolve None - a parede caia no tier 5 e fechava com
    `11xB39 + 3xC09`, TRES compensadores em sequencia, reprovada em
    seguida pela regra #2. Bastava comecar por um B34: `B34 + 10xB39 +
    B34` fecha os mesmos 469cm com ZERO compensadores. (Existem 5
    composicoes sem compensador nenhum para esse trecho; o guloso puro
    nao achava nenhuma.)

    Nao altera nenhum caso em que o guloso puro ja' fecha - so' amplia o
    alcance dos tiers BONS de `_pier_ordered_layout`, evitando que eles
    caiam para um tier pior sem necessidade.

    Variar o primeiro bloco cobre muitos casos, mas nao todos: 139cm fecha
    com QUATRO B34 e nenhum B39, e nenhuma escolha de primeiro bloco leva
    o guloso ate' la'. Por isso, se nem isso fechar, cai para
    `_exact_fill_blocks` (busca exata)."""
    layout = _greedy_fill_blocks(remaining, pos_cm, catalog, codes_by_len_desc, first_code)
    if layout is not None or first_code is not None:
        return layout
    for code in codes_by_len_desc:
        alt = _greedy_fill_blocks(remaining, pos_cm, catalog, codes_by_len_desc, code)
        if alt is not None:
            return alt
    return _exact_fill_blocks(remaining, pos_cm, catalog, codes_by_len_desc)


# Passo de discretizacao da busca exata: decimos de centimetro. Todas as
# medidas do catalogo e das juntas sao multiplos de 0,1cm na pratica, e
# trabalhar em inteiros evita erro de ponto flutuante acumulado na soma.
_EXACT_FILL_SCALE = 10
# Teto de seguranca do vetor de programacao dinamica (decimos de cm): 40m
# de trecho e' muito acima de qualquer parede real deste projeto.
_EXACT_FILL_MAX_STEPS = 40000


def _exact_fill_blocks(remaining, pos_cm, catalog, codes_by_len_desc):
    """Busca EXATA (programacao dinamica) de uma composicao que feche
    `remaining` exatamente com os codigos de `codes_by_len_desc`, na mesma
    convencao de `_greedy_fill_blocks` (cada peca carrega sua propria junta
    de saida). Devolve o layout ORDENADO [(codigo, start_cm, end_cm), ...]
    ou None quando nenhuma combinacao fecha.

    Criterio: MENOS pecas primeiro (o que naturalmente prefere as pecas
    maiores, mesma intencao do guloso), desempatando pela peca mais longa.
    As pecas saem ordenadas da maior para a menor - a mesma "cara" que o
    guloso produz, para nao mudar o formato dos layouts que ja' funcionam;
    quando a ordem importa para o desencontro entre fiadas,
    `_pier_layout_avoiding_joints` ja' explora as alternativas por cima
    disto.

    Existe porque o guloso nunca volta atras (ver
    `_greedy_fill_blocks_any_first`): medido ao vivo via MCP em 2026-08-28,
    33 eixos de um projeto real eram reprovados pela regra #2
    (compensadores em sequencia) tendo TODOS uma composicao limpa
    disponivel - por exemplo 139cm = 4xB34, que nenhuma escolha de
    primeiro bloco alcanca."""
    steps = []
    for code in codes_by_len_desc:
        entry = catalog.get(code)
        if not entry:
            continue
        passo = int(round((entry["length_cm"] + BLOCK_JOINT_CM) * _EXACT_FILL_SCALE))
        if passo > 0:
            steps.append((passo, code, entry["length_cm"]))
    if not steps:
        return None
    alvo = int(round(remaining * _EXACT_FILL_SCALE))
    if alvo <= 0 or alvo > _EXACT_FILL_MAX_STEPS:
        return None

    # dp[v] = (n_pecas, comprimento_da_peca_escolhida, code, passo) da
    # melhor solucao para exatamente `v` decimos; None = inalcancavel.
    dp = [None] * (alvo + 1)
    dp[0] = (0, 0.0, None, 0)
    for v in range(1, alvo + 1):
        melhor = None
        for passo, code, comp_cm in steps:
            if passo > v:
                continue
            anterior = dp[v - passo]
            if anterior is None:
                continue
            cand = (anterior[0] + 1, -comp_cm)
            if melhor is None or cand < (melhor[0], -melhor[1]):
                melhor = (anterior[0] + 1, comp_cm, code, passo)
        dp[v] = melhor
    if dp[alvo] is None:
        return None

    escolhidos = []
    v = alvo
    while v > 0:
        _n, comp_cm, code, passo = dp[v]
        escolhidos.append((code, comp_cm))
        v -= passo
    escolhidos.sort(key=lambda it: -it[1])

    layout = []
    pos = pos_cm
    for code, comp_cm in escolhidos:
        layout.append((code, pos, pos + comp_cm))
        pos += comp_cm + BLOCK_JOINT_CM
    return layout


def _merge_adjacent_compensator_pairs(layout, catalog, leading_open=True, trailing_open=True):
    """REGRA GERAL (secao 2 do pedido do usuario, 2026-08-24): "nao quero
    solucoes como 9+9+9 quando existir uma composicao melhor utilizando
    blocos maiores... quando houver 9+9, substitua preferencialmente por
    19". Nao e' um patch para o caso da imagem - roda sobre QUALQUER
    `layout` (lista ordenada [(codigo, start_cm, end_cm), ...], a mesma
    devolvida por `_pier_ordered_layout`/`_half_block_leading_layout`) e
    mescla repetidamente qualquer PAR ADJACENTE de compensadores do MESMO
    codigo cujo vao combinado (do inicio do primeiro ao fim do segundo,
    JA incluindo a junta de argamassa entre eles) bata com o comprimento
    de outra peca do catalogo dentro de PIER_LAYOUT_TOLERANCE_CM -
    generico: funciona para qualquer catalogo (nao hardcoda "C09"/"B19"),
    a coincidencia matematica exata do catalogo atual e' 9+1+9=19=B19,
    mas se o catalogo mudar (outro compensador, outra junta) a funcao se
    adapta sozinha. So' aceita substituto NAO-compensador (preferindo o
    MAIOR disponivel) - substituir compensador por compensador nao reduz
    nada. Devolve uma lista NOVA (nunca muta `layout`); sem nenhum par
    fechavel, devolve `layout` inalterado (mesma identidade de conteudo).
    Aplicada em TODO retorno de _pier_ordered_layout/_half_block_leading_
    layout - nenhum trecho da parede (comum, jamb-side do preenchimento,
    encontro) escapa desta checagem.

    GUARDA (bug real corrigido 2026-08-25): quando o substituto e'
    EXATAMENTE o HALF_BLOCK_CODE (B19 - a coincidencia matematica deste
    catalogo, 9+1+9=19), a fusao so' pode acontecer numa PONTA do
    `layout` (i==0 ou o par ser os 2 ultimos itens) E o lado
    correspondente (`leading_open`/`trailing_open`) realmente ser uma
    ponta aberta - a MESMA regra que proibe B19 fora de ponta aberta em
    qualquer outro lugar deste arquivo (secao 2). Sem esta guarda, a fusao
    "inocente" (so' otimizando pecas) conseguia colocar um B19 encostado
    direto num no' de amarracao fechado (2 compensadores adjacentes no
    tier de compensador, que so' sao gerados na PONTA da sobra do guloso -
    prova: `remaining` so' diminui, entao um tier so' cai para compensador
    quando B39/B34 pararam de caber, e isso so' acontece na cauda da
    sequencia) - violando a regra #2 do usuario por uma porta lateral que
    nenhuma das checagens de `leading_is_open`/`trailing_is_open` nos
    tiers 2/4/6 cobria (elas so' guardam ONDE um B19 e' escolhido de
    proposito, nao um B19 que nasce de uma fusao de otimizacao). Quando o
    B19 nao se qualifica, o par de compensadores fica INTOCADO (nunca
    vira outro codigo so' para "resolver" o problema) - o chamador (que
    confere `_compensator_count` <= MAX_COMPENSATORS_PER_TRECHO DEPOIS da
    fusao) rejeita esse tier corretamente e cai para o proximo."""
    if not layout or len(layout) < 2:
        return layout
    result = list(layout)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 1:
            code_a, start_a, _end_a = result[i]
            code_b, _start_b, end_b = result[i + 1]
            entry_a = catalog.get(code_a) or {}
            entry_b = catalog.get(code_b) or {}
            if entry_a.get("is_compensator") and entry_b.get("is_compensator") and code_a == code_b:
                span_cm = end_b - start_a
                at_leading = i == 0
                at_trailing = (i + 2) == len(result)
                half_allowed_here = (at_leading and leading_open) or (at_trailing and trailing_open)
                replacement = None
                for code, entry in catalog.items():
                    if code == code_a or entry.get("is_compensator"):
                        continue
                    if code == HALF_BLOCK_CODE and not half_allowed_here:
                        continue
                    length_cm = entry.get("length_cm")
                    if not length_cm:
                        continue
                    if abs(length_cm - span_cm) <= PIER_LAYOUT_TOLERANCE_CM:
                        if replacement is None or length_cm > catalog[replacement]["length_cm"]:
                            replacement = code
                if replacement is not None:
                    repl_len = catalog[replacement]["length_cm"]
                    result[i:i + 2] = [(replacement, start_a, start_a + repl_len)]
                    changed = True
                    continue
            i += 1
    return result


def _pier_remaining_snapped_cm(pier_cm, leading_joint_cm, trailing_joint_cm):
    """`remaining` (cm) que um trecho realmente tem para preencher com
    pecas, depois de descontar as juntas de contorno e absorver o ruido de
    conversao pes<->cm (mesma tolerancia/arredondamento para o modulo de
    5cm que `_pier_ordered_layout` sempre usou - extraida daqui para ser
    reusada tambem por `_pier_forced_bypass_layouts`, sem duplicar a
    logica). Devolve None quando o trecho NAO fecha (negativo, ou nao e'
    multiplo de 5cm dentro de PIER_LAYOUT_TOLERANCE_CM); 0.0 (nunca None)
    para um trecho de comprimento praticamente zero."""
    remaining = _pier_remaining_cm(pier_cm, leading_joint_cm, trailing_joint_cm)
    if remaining < -PIER_LAYOUT_TOLERANCE_CM:
        return None
    if remaining <= PIER_LAYOUT_TOLERANCE_CM:
        return 0.0
    # TOLERANCIA REAL, NAO 1e-6 (corrigido 2026-08-21). `pier_cm` vem de
    # coordenadas do CAD que passaram por conversoes pes<->cm e por
    # extend_wall_ends_to_junctions: medido na planta real do usuario, uma
    # borda de encontro sai em 829,99791cm em vez de 830cm - 0,002cm de
    # ruido. Com o teste antigo (1e-6) isso REPROVAVA o trecho como
    # "modulacao nao fecha": 116 dos 344 trechos nao-modulares medidos
    # tinham o comprimento certo e falhavam so' por isso.
    snapped = PIER_MODULE_CM * round(remaining / PIER_MODULE_CM)
    if abs(remaining - snapped) > PIER_LAYOUT_TOLERANCE_CM:
        return None
    # Devolve o valor EXATO (arredondado ao modulo): assim o ruido nao se
    # acumula bloco a bloco no laco guloso do chamador (a peca final
    # sairia fora por fracao de milimetro).
    return snapped


def _pier_ordered_layout(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                         first_code=None, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                         leading_open_override=None, trailing_open_override=None):
    """Lista ORDENADA [(codigo, start_cm, end_cm), ...], do inicio ao fim
    do trecho, que preenche `pier_cm` INTEIRO (incluindo as juntas de
    contorno): `leading_joint_cm`/`trailing_joint_cm` sao BLOCK_JOINT_CM
    quando ha' algo para encostar naquele lado (outro bloco/no') ou
    BLOCK_OPENING_JOINT_CM (0) quando o lado encosta numa abertura ou e'
    uma ponta livre de parede.

    Greedy MAIOR-bloco-que-ainda-cabe a cada passo (ver `_greedy_fill_blocks`):
    sempre valido enquanto o resto ficar >= 0 e multiplo de PIER_MODULE_CM,
    porque QUALQUER multiplo de 5 e' construivel com o catalogo padrao
    (prova na secao 3 do prompt) - entao o resto nunca fica "preso" num
    valor sem solucao.

    PRIORIDADE COMPLETA (pedido explicito do usuario, 2026-08-21, revisada
    apos ver o resultado real no Revit; tiers 5/6 TROCADOS DE ORDEM em
    2026-08-25 - ver o comentario junto do tier 5 abaixo): "blocos
    inteiros -> meio bloco de 19cm numa ponta ABERTA -> bloco de 34cm ->
    compensadores/pastilhas -> meio bloco fora de ponta aberta, so' como
    ULTIMISSIMO recurso". Cada tier so' e' tentado se o(s) anterior(es)
    nao fecharem:
      1. So' B39 (nem B19, nem B34, nem compensador).
      2. 1 UNICO B19, encostado numa ponta ABERTA do trecho (abertura ou
         extremidade sem amarracao - junta de contorno 0 daquele lado),
         preenchendo o resto so' com B39 (tenta a ponta de ENTRADA
         primeiro, depois a de SAIDA - ver HALF_BLOCK_CODE).
      3. B39 + B34 (sem B19, sem compensador) - o B34 pode cair em
         QUALQUER posicao do trecho, inclusive no meio (diferente do B19).
         ATENCAO - LIMITACAO CONHECIDA: esta funcao NAO alinha ainda a
         celula do B34 desta fiada com a da fiada oposta (regra do vao
         menor/vao maior entre 1a/2a fiada que o usuario pediu) - a
         orientacao usada aqui e' so' uma convencao fixa (ver
         _place_pier_layout/_asymmetric_bond_origin_and_axis). Alinhamento
         cruzado entre fiadas fica para uma proxima etapa.
      4. 1 UNICO B19 numa ponta ABERTA, mas preenchendo o resto com B39+B34
         (ainda sem compensador).
      5. B39 (+B34 se precisar) + no maximo MAX_COMPENSATORS_PER_TRECHO
         compensador(es)/pastilha(s) - pedido explicito do usuario:
         "extremamente proibido... duas pastilhas ou combinacoes
         consecutivas de compensadores... usados apenas de forma pontual,
         nunca em sequencia".
      6. 1 UNICO B19 MESMO SEM ponta aberta - ULTIMISSIMO recurso "limpo"
         (0 ou 1 compensador), so' tentado se nem o tier 5 (compensador)
         fechou. TROCADO DE LUGAR com o tier de compensador em 2026-08-25
         (pedido explicito do usuario): "o meio bloco deve ser priorizado
         EXCLUSIVAMENTE em situacoes relacionadas as aberturas... nao
         utilizar meio bloco para simplesmente corrigir uma modulacao ruim
         nem como recurso para fechar uma amarracao" - antes disto, B19
         SEM ponta aberta (ou seja, exatamente contra um no' L/T/X) vinha
         ANTES do compensador na prioridade; um trecho entre dois
         encontros que so' fechava aqui (nem tier 1-4) preferia colocar um
         B19 encostado no proprio no' de amarracao a usar 1 compensador -
         a violacao literal da regra #2 que o usuario reportou.
      7. Ultimo recurso irrestrito (qualquer posicao, qualquer contagem) -
         preferir uma solucao "feia" a reportar NON_MODULAR_WALL quando
         ela existe.

    `first_code`, se dado, forca o PRIMEIRO bloco (usado por
    `_pier_layout_avoiding_joints` para tentar desencontrar juntas entre
    fiadas - secao 6). Se `first_code` for o proprio HALF_BLOCK_CODE mas a
    ponta de entrada NAO for aberta, a regra do meio-bloco tem prioridade:
    o pedido e' ignorado silenciosamente (a tentativa "sem B19" roda
    normalmente) em vez de violar a regra so' para desencontrar uma junta.

    `leading_open_override`/`trailing_open_override`: BUG REAL corrigido
    em 2026-08-24 - o criterio padrao "ponta aberta" (`leading_joint_cm <=
    BLOCK_OPENING_JOINT_CM`) NAO CONSEGUE distinguir uma ponta contra um
    encontro L/T/X (fechada, `lead_cm=0`) de uma ponta contra uma abertura
    de verdade (aberta, tambem `lead_cm=0` quando ja' tem jamb resolvido) -
    os dois casos zeram a junta de contorno pelo MESMO motivo (nao ha'
    junta de argamassa ali), entao o valor sozinho nao basta. Isso fazia
    B19 aparecer repetido em praticamente todo encontro L/T/X do predio
    (reportado pelo usuario com imagens reais). Quando o chamador SABE a
    resposta certa (`solve_wall_free_fill`, a partir de kind_left/
    kind_right), passa aqui um bool explicito que SUBSTITUI o calculo pelo
    valor da junta; `None` (default) mantem o comportamento antigo, para
    os demais chamadores (jambs de abertura, encontros) que ja' passam
    juntas sem essa ambiguidade.

    Devolve None se `pier_cm` nao fechar (nao e' multiplo de 5 depois de
    descontar as juntas de contorno, ou e' negativo) - o chamador trata
    isso como NON_MODULAR_WALL, nunca em silencio."""
    remaining = _pier_remaining_snapped_cm(pier_cm, leading_joint_cm, trailing_joint_cm)
    if remaining is None:
        return None
    if remaining <= PIER_LAYOUT_TOLERANCE_CM:
        return []

    all_codes = _pier_codes_by_len_desc(catalog, allow_compensators, pool=COMMON_FILL_BLOCK_CODES)
    if not all_codes:
        return None
    is_comp = lambda code: catalog.get(code, {}).get("is_compensator")  # noqa: E731
    plain_codes = [c for c in all_codes if c != HALF_BLOCK_CODE and c != MID_WALL_BLOCK_CODE and not is_comp(c)]
    codes_b34 = [c for c in all_codes if c != HALF_BLOCK_CODE and not is_comp(c)]
    codes_no_half = [c for c in all_codes if c != HALF_BLOCK_CODE]

    def _compensator_count(layout):
        return sum(1 for code, _a, _b in layout if is_comp(code))

    half_cm = catalog.get(HALF_BLOCK_CODE, {}).get("length_cm") if HALF_BLOCK_CODE in all_codes else None
    half_step = (half_cm + BLOCK_JOINT_CM) if half_cm is not None else None
    leading_open = (leading_open_override if leading_open_override is not None
                    else leading_joint_cm <= BLOCK_OPENING_JOINT_CM + 1e-6)
    trailing_open = (trailing_open_override if trailing_open_override is not None
                     else trailing_joint_cm <= BLOCK_OPENING_JOINT_CM + 1e-6)
    half_fits = half_step is not None and half_step <= remaining + 1e-6

    def _half_at_leading(fill_pool, fill_first_code=None):
        if not (leading_open and half_fits):
            return None
        tail = _greedy_fill_blocks(remaining - half_step, leading_joint_cm + half_step,
                                   catalog, fill_pool, fill_first_code)
        if tail is None:
            return None
        return [(HALF_BLOCK_CODE, leading_joint_cm, leading_joint_cm + half_cm)] + tail

    def _half_at_trailing(fill_pool, fill_first_code=None):
        if not (trailing_open and half_fits):
            return None
        head = _greedy_fill_blocks(remaining - half_step, leading_joint_cm, catalog, fill_pool, fill_first_code)
        if head is None:
            return None
        start = head[-1][2] + BLOCK_JOINT_CM if head else leading_joint_cm
        return head + [(HALF_BLOCK_CODE, start, start + half_cm)]

    def _half_anywhere_leading(fill_pool):
        if half_step is None or half_step > remaining + 1e-6:
            return None
        tail = _greedy_fill_blocks(remaining - half_step, leading_joint_cm + half_step, catalog, fill_pool, None)
        if tail is None:
            return None
        return [(HALF_BLOCK_CODE, leading_joint_cm, leading_joint_cm + half_cm)] + tail

    half_first_requested = first_code == HALF_BLOCK_CODE
    plain_first_code = None if half_first_requested else first_code

    # Todo retorno passa por `_finish` (fusao de pares de compensadores
    # adjacentes - secao 2 do pedido: "9+9 -> 19" - generico, ver
    # `_merge_adjacent_compensator_pairs`). Nenhum dos 8 niveis abaixo
    # escapa desta checagem final. `leading_open`/`trailing_open` viajam
    # junto (bug real corrigido 2026-08-25 - ver docstring da funcao):
    # sem isso, a propria fusao podia "nascer" um B19 encostado num no'
    # fechado, driblando a regra que os tiers 2/4/6 respeitam.
    def _finish(result_layout):
        return _merge_adjacent_compensator_pairs(result_layout, catalog, leading_open, trailing_open)

    # 1) so' B39.
    layout = _greedy_fill_blocks(remaining, leading_joint_cm, catalog, plain_codes, plain_first_code)
    if layout is not None:
        return _finish(layout)

    # 2) 1 B19 numa ponta ABERTA, resto so' com B39.
    layout = _half_at_leading(plain_codes) or _half_at_trailing(plain_codes)
    if layout is not None:
        return _finish(layout)

    # 3) B39 + B34 (sem B19, sem compensador) - B34 pode ir em qualquer
    #    posicao (ver LIMITACAO no docstring: alinhamento entre fiadas
    #    ainda nao aplicado aqui). `_any_first` (2026-08-28): quando o
    #    guloso puro nao fecha, varia o primeiro bloco antes de descer de
    #    tier - sem isso um trecho que fecha com `B34 + 10xB39 + B34` caia
    #    para o tier 5 e virava `11xB39 + 3xC09`.
    layout = _greedy_fill_blocks_any_first(remaining, leading_joint_cm, catalog,
                                           codes_b34, plain_first_code)
    if layout is not None:
        return _finish(layout)

    # 4) 1 B19 numa ponta ABERTA, resto com B39+B34.
    layout = _half_at_leading(codes_b34) or _half_at_trailing(codes_b34)
    if layout is not None:
        return _finish(layout)

    # 5) B39 (+B34) + no maximo MAX_COMPENSATORS_PER_TRECHO compensador(es) -
    #    so' chega aqui quando NENHUMA combinacao sem compensador fechou.
    #    A fusao (_finish) roda ANTES da checagem do teto: 9+9 vira 19
    #    (0 compensadores) e pode passar a caber dentro do teto mesmo
    #    quando o layout guloso cru usou 2. TENTADO ANTES do B19-sem-
    #    ponta-aberta (tier 6, ver comentario la' e no docstring) - regra
    #    #2 do usuario (2026-08-25): meio bloco nunca e' o recurso pra
    #    fechar uma amarracao quando um compensador resolve.
    layout_with_comp = _greedy_fill_blocks_any_first(remaining, leading_joint_cm, catalog,
                                                     codes_no_half, plain_first_code)
    if layout_with_comp is not None:
        merged_with_comp = _finish(layout_with_comp)
        if _compensator_count(merged_with_comp) <= MAX_COMPENSATORS_PER_TRECHO:
            return merged_with_comp

    # 6) 1 B19 mesmo SEM ponta aberta (ou seja, exatamente contra um no'
    #    L/T/X) - ULTIMISSIMO recurso "limpo", so' tentado se nem o
    #    compensador (tier 5) fechou dentro do teto. Tenta a ponta de
    #    entrada por padrao, so' para ter uma posicao definida (nao ha'
    #    ponta "certa" quando nenhuma e' aberta).
    layout_forced_half = _half_anywhere_leading(codes_b34)
    if layout_forced_half is not None:
        return _finish(layout_forced_half)

    # 7) fica com o "com compensadores" (ja' fundido) mesmo acima do teto,
    #    se existir - sempre melhor que reportar NON_MODULAR sem precisar.
    if layout_with_comp is not None:
        return merged_with_comp

    # 8) ultimo recurso irrestrito (B19 em qualquer posicao, qualquer
    #    contagem de compensadores).
    layout_last_resort = _greedy_fill_blocks(remaining, leading_joint_cm, catalog, all_codes, first_code)
    return _finish(layout_last_resort) if layout_last_resort is not None else None


VERTICAL_JOINT_STAGGER_TOLERANCE_CM = 1.0  # secao 6: juntas mais proximas que
# isso, em coordenadas GLOBAIS ao longo da parede, contam como "a mesma
# junta vertical continua" entre Fiada A e Fiada B.


# Pecas de FECHAMENTO pequenas cuja junta contra o vizinho NAO conta como
# junta vertical continua quando elas estao encostadas numa ABERTURA (regra
# do usuario, 2026-08-28, a partir de uma parede modulada a mao: "os blocos
# B4, B9 e B19 podem ficar alinhados quando estao encostados nas aberturas,
# principalmente o b4 e o b9"). Ver EXCECAO na secao 11 de
# REGRAS_MODULACAO_BLOCOS.md.
OPENING_ALIGNED_EXEMPT_CODES = ("C04", "C09", "B19")


def _layout_internal_joint_positions_cm(layout, seg_start_cm,
                                        leading_is_open=False, trailing_is_open=False):
    """Posicao absoluta (cm, ao longo do eixo da parede) do CENTRO de cada
    junta INTERNA de `layout` (a lista devolvida por _pier_ordered_layout) -
    isto e', as juntas entre dois blocos consecutivos do mesmo trecho, sem
    contar as juntas de CONTORNO (contra abertura/no'/ponta livre, essas nao
    sao "verticais continuas entre fiadas" no sentido da secao 6). `layout`
    guarda posicoes relativas ao inicio do trecho (pos_cm comeca em
    leading_joint_cm) - `seg_start_cm` converte para absoluto na parede.

    `leading_is_open`/`trailing_is_open`: quando a ponta correspondente do
    trecho e' uma ABERTURA (nao um no' de amarracao), a junta que separa a
    peca de fechamento dessa ponta do seu vizinho e' OMITIDA da lista -
    isto e', deixa de contar como coincidencia de junta vertical entre
    fiadas - desde que essa peca seja uma das
    `OPENING_ALIGNED_EXEMPT_CODES` (C04/C09/B19). E' a EXCECAO a' regra #1
    pedida pelo usuario (2026-08-28): pastilha/compensador/meio-bloco
    encostados no vao PODEM ficar alinhados entre a Fiada A e a Fiada B.
    Os defaults `False` preservam exatamente o comportamento anterior para
    todo chamador que ainda nao informa as pontas."""
    joints = []
    n = len(layout)
    for i in range(n - 1):
        # Junta i separa layout[i] de layout[i+1]. Ela e' isenta quando a
        # peca ENCOSTADA na ponta aberta e' pequena (C04/C09/B19): na ponta
        # inicial isso e' layout[0] (junta 0); na final, layout[-1] (junta
        # n-2).
        if i == 0 and leading_is_open and layout[0][0] in OPENING_ALIGNED_EXEMPT_CODES:
            continue
        if i == n - 2 and trailing_is_open and layout[-1][0] in OPENING_ALIGNED_EXEMPT_CODES:
            continue
        gap_center_local = layout[i][2] + BLOCK_JOINT_CM / 2.0
        joints.append(seg_start_cm + gap_center_local)
    return joints


def _count_joint_coincidences_cm(positions_cm, avoid_positions_cm,
                                 tolerance_cm=VERTICAL_JOINT_STAGGER_TOLERANCE_CM):
    """Quantas posicoes de `positions_cm` caem a menos de `tolerance_cm` de
    alguma posicao em `avoid_positions_cm` - usado para comparar candidatos
    de layout da Fiada B contra as juntas ja' usadas pela Fiada A."""
    if not positions_cm or not avoid_positions_cm:
        return 0
    count = 0
    for pos in positions_cm:
        for other in avoid_positions_cm:
            if abs(pos - other) <= tolerance_cm:
                count += 1
                break
    return count


# Tolerancia (cm) para considerar o VAZIO/vao interno de uma peca "alinhado"
# com o vazio de uma peca da outra fiada - reusa CELL_ALIGNMENT_TOLERANCE_CM
# (mesma folga ja' usada pela prova geometrica de L/T, validate_l_corner).
VOID_ALIGNMENT_TOLERANCE_CM = CELL_ALIGNMENT_TOLERANCE_CM


def _block_void_offsets_cm(entry):
    """Offsets (cm), medidos a partir do INICIO do bloco ao longo do seu
    proprio comprimento, dos centros dos vazios/celulas internas de `entry`
    (BlockTypeDefinition) - [] para pecas macicas (compensador/pastilha,
    sem cells_local) ou sem comprimento/celulas legiveis.

    `cells_local` guarda `center_local[0]` com origem no CENTRO geometrico
    do bloco (x local em [-comprimento/2, +comprimento/2], mesma convencao
    de `_make_block_candidate`/`_asymmetric_bond_origin_and_axis`) - por
    isso soma-se metade do comprimento para virar "distancia desde o
    inicio", a mesma referencia usada pelos layouts 1D de
    `_pier_ordered_layout` (start_cm/end_cm)."""
    length_cm = entry.get("length_cm") if entry else None
    cells = entry.get("cells_local") if entry else None
    if not length_cm or not cells:
        return []
    half_len_cm = length_cm / 2.0
    return [half_len_cm + _ft_to_cm(cell["center_local"][0]) for cell in cells]


def _layout_void_positions_cm(layout, catalog, seg_start_cm):
    """Posicao absoluta (cm, ao longo do eixo da parede) do CENTRO de CADA
    vazio/celula interna das pecas de `layout` (a lista devolvida por
    `_pier_ordered_layout`) - usado para checar o alinhamento vertical dos
    vazios entre Fiada A e Fiada B (secao 6), pedido explicito do usuario
    (2026-08-21): "a modulacao... deve considerar tambem a posicao dos seus
    vazios internos", nao so' o comprimento total dos blocos. Pecas macicas
    (compensador/pastilha) nao contribuem nenhuma posicao."""
    positions = []
    for code, start_cm, _end_cm in layout:
        entry = catalog.get(code)
        if entry is None:
            continue
        for offset_cm in _block_void_offsets_cm(entry):
            positions.append(seg_start_cm + start_cm + offset_cm)
    return positions


def _count_void_alignment_cm(positions_cm, target_positions_cm,
                             tolerance_cm=VOID_ALIGNMENT_TOLERANCE_CM):
    """Quantas posicoes de `positions_cm` caem a MENOS de `tolerance_cm` de
    alguma posicao em `target_positions_cm` - o OPOSTO de
    `_count_joint_coincidences_cm`: aqui coincidir e' o objetivo (vazios
    alinhados/sobrepostos entre fiadas, para a amarracao ficar continua
    verticalmente), nao o contrario."""
    if not positions_cm or not target_positions_cm:
        return 0
    count = 0
    for pos in positions_cm:
        for other in target_positions_cm:
            if abs(pos - other) <= tolerance_cm:
                count += 1
                break
    return count


def _half_block_leading_layout(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                               allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                               trailing_is_open=True):
    """Layout do trecho com 1 HALF_BLOCK_CODE (B19) FORCADO no INICIO,
    seguido do preenchimento comum de sempre - usado SO' pela busca de
    alinhamento de vazios entre fiadas (`_pier_layout_avoiding_joints`),
    nunca pelo preenchimento comum em si: `_pier_ordered_layout` continua
    exigindo ponta ABERTA para usar B19 (regra inalterada, "nunca
    espremido entre dois blocos no meio do trecho" - secao 6/8). O
    CHAMADOR so' invoca esta funcao quando o lado ESQUERDO do trecho e'
    uma ponta aberta de verdade (`leading_is_open`, ver
    `_pier_layout_avoiding_joints`) - nunca contra um encontro L/T/X.

    Aqui o B19 tem um proposito DIFERENTE do de preenchimento: reproduzir
    o deslocamento de meio modulo (~20cm para B39, 19+1cm de junta) que a
    amarracao real entre fiadas exige (pedido explicito do usuario,
    2026-08-21).

    CORRECAO (2026-08-24, regressao real reportada pelo usuario): a versao
    anterior permitia o B19 "mesmo numa ponta FECHADA contra outro bloco/
    no'" - isso fazia B19 aparecer repetido em praticamente todo encontro
    L/T/X do predio, contrariando a secao 2 (B19 so' encosta em ponta
    aberta). Agora tanto a ponta de ENTRADA (controlada pelo chamador, que
    so' invoca esta funcao com `leading_is_open=True`) quanto a ponta de
    SAIDA do tier 3 abaixo (`trailing_is_open`) precisam ser aberturas ou
    pontas livres de verdade.

    O resto do trecho (depois do B19 de entrada) e' fechado tentando, NESTA
    ORDEM (mesma prioridade de `_pier_ordered_layout`, sem repetir as etapas
    de B19 - ja' usado uma vez - exceto a ultima abaixo):
      1. So' B39.
      2. B39 + B34.
      3. (so' se `trailing_is_open`) B39 (+B34) + 1 SEGUNDO B19 fechando a
         PONTA FINAL do trecho - necessario sempre que o trecho fechar como
         um multiplo EXATO de blocos inteiros na Fiada A (a sobra depois do
         deslocamento de meio modulo vira, ela mesma, outro meio modulo -
         40k-20 = 40(k-1)+20). Ainda sem nenhum compensador, e o segundo
         B19 fica numa PONTA (a final) - mesma regra de posicao do
         primeiro. PULADO quando a ponta final e' um encontro L/T/X.
      4. B39 (+B34) + no maximo MAX_COMPENSATORS_PER_TRECHO compensador(es),
         sem um segundo B19.
    Nao ha' um tier irrestrito de ultimo recurso aqui: se nada acima
    fechar respeitando o teto de compensadores, devolve None - alinhar
    vazios e' 'sempre que possivel', nunca pode violar a regra dura de
    'nunca 2+ compensadores em sequencia'; o chamador simplesmente fica
    com o layout padrao (sem o deslocamento) nesse caso.

    Devolve None se B19 nao existir no catalogo ou nao couber no trecho."""
    half_cm = catalog.get(HALF_BLOCK_CODE, {}).get("length_cm") if HALF_BLOCK_CODE in catalog else None
    if half_cm is None:
        return None
    half_step = half_cm + BLOCK_JOINT_CM
    remaining = _pier_remaining_cm(pier_cm, leading_joint_cm, trailing_joint_cm)
    if remaining < half_step - 1e-6:
        return None
    tail_remaining = remaining - half_step
    tail_pos = leading_joint_cm + half_step

    all_codes = _pier_codes_by_len_desc(catalog, allow_compensators, exclude=(HALF_BLOCK_CODE,),
                                        pool=COMMON_FILL_BLOCK_CODES)
    if not all_codes:
        return None
    is_comp = lambda code: catalog.get(code, {}).get("is_compensator")  # noqa: E731
    plain_codes = [c for c in all_codes if c != MID_WALL_BLOCK_CODE and not is_comp(c)]
    codes_b34 = [c for c in all_codes if not is_comp(c)]

    def _lead(head_and_tail):
        # Fusao de compensadores (secao 2, ver _merge_adjacent_compensator_
        # pairs) roda sobre a lista JA' completa (com o B19 de entrada),
        # nao so' sobre `head_and_tail` - um par 9+9 poderia, em teoria,
        # comecar logo apos o B19 de entrada. `leading_open=False`: a
        # posicao 0 do array ja' e' o B19 de entrada de verdade (nunca um
        # compensador) - nenhuma fusao pode legitimamente "ser a ponta de
        # entrada" aqui, so' `trailing_open` (=`trailing_is_open`, a ponta
        # de saida real do trecho) importa (bug real corrigido 2026-08-25 -
        # ver docstring de _merge_adjacent_compensator_pairs).
        return _merge_adjacent_compensator_pairs(
            [(HALF_BLOCK_CODE, leading_joint_cm, leading_joint_cm + half_cm)] + head_and_tail, catalog,
            leading_open=False, trailing_open=trailing_is_open,
        )

    # 1) so' B39.
    tail = _greedy_fill_blocks(tail_remaining, tail_pos, catalog, plain_codes)
    if tail is not None:
        return _lead(tail)

    # 2) B39 + B34.
    tail = _greedy_fill_blocks(tail_remaining, tail_pos, catalog, codes_b34)
    if tail is not None:
        return _lead(tail)

    # 3) B39 (+B34) + 1 segundo B19 fechando a PONTA FINAL - so' quando essa
    #    ponta e' aberta de verdade (senao um B19 apareceria contra um no'
    #    L/T/X, a mesma regressao que motivou esta funcao ganhar o
    #    parametro `trailing_is_open`).
    if trailing_is_open:
        inner_remaining = tail_remaining - half_step
        if inner_remaining >= -PIER_LAYOUT_TOLERANCE_CM:
            head = _greedy_fill_blocks(max(0.0, inner_remaining), tail_pos, catalog, codes_b34)
            if head is not None:
                start = head[-1][2] + BLOCK_JOINT_CM if head else tail_pos
                return _lead(head + [(HALF_BLOCK_CODE, start, start + half_cm)])

    # 4) B39 (+B34) + no maximo MAX_COMPENSATORS_PER_TRECHO compensador(es) -
    #    checagem do teto DEPOIS da fusao (mesmo raciocinio do tier 6 de
    #    _pier_ordered_layout: 9+9 vira 19 antes de contar).
    tail = _greedy_fill_blocks(tail_remaining, tail_pos, catalog, all_codes)
    if tail is not None:
        merged = _lead(tail)
        merged_comp_count = sum(1 for code, _a, _b in merged if is_comp(code))
        if merged_comp_count <= MAX_COMPENSATORS_PER_TRECHO:
            return merged

    return None


def _pier_forced_bypass_layouts(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                                leading_is_open=True, trailing_is_open=True):
    """Layouts adicionais para a busca de amarracao de `_pier_layout_
    avoiding_joints` que `_pier_ordered_layout(first_code=...)` sozinho
    NUNCA alcanca. CAUSA-RAIZ corrigida (2026-08-25) da maioria das juntas
    verticais corridas medidas numa execucao real (paredes inteiras com a
    MESMA junta repetida em todas as 15 fiadas): `_pier_ordered_layout`
    tenta seus proprios tiers em ORDEM FIXA (1: so' B39; 3: B39+B34; 6: +1
    compensador) e devolve o resultado do PRIMEIRO tier que fechar - o
    `first_code` pedido pelo chamador so' e' honrado quando pertence ao
    POOL desse mesmo tier. Pedir first_code="B34" (ou um compensador) NAO
    TEM NENHUM EFEITO sempre que o trecho ja fecha so' com B39 no tier 1
    (o pool do tier 1 nem contem B34/compensador - o tier 3/6 nunca chega
    a ser tentado, porque o tier 1 ja' devolveu). Como MUITOS trechos entre
    dois encontros L/T/X (as duas pontas FECHADAS, sem onde encostar um
    B19) fecham exatamente como um multiplo de 40cm (so' B39), a busca de
    `_pier_layout_avoiding_joints` ficava, para esses trechos, SEM NENHUMA
    alternativa real para tentar - a mesma sequencia identica de B39 saia
    na Fiada A e na Fiada B, 100% das juntas coincidindo, na altura
    inteira da parede.

    Chama `_greedy_fill_blocks` DIRETO (nunca `_pier_ordered_layout`), com
    o primeiro bloco ja' escolhido e o RESTO preenchido pelo mesmo guloso
    de sempre (maior peca do catalogo inteiro - B39/B34/compensadores -
    que ainda cabe a cada passo, MAX_COMPENSATORS_PER_TRECHO respeitado
    DEPOIS da fusao de pares adjacentes, identico ao criterio real do tier
    6) MESMO quando um tier mais cedo tambem fechasse. Nunca inclui B19 -
    quem decide se B19 pode entrar (regra da ponta aberta) e'
    exclusivamente `_half_block_leading_layout`/o candidato dedicado do
    chamador, nao esta funcao.

    PROVA da variante "B34 primeiro" (a que realmente resolve o caso do
    log real - trecho fechando como um multiplo EXATO de 40cm, so' B39):
    depois de 1 B34 (35cm de "remaining", 34+1cm de junta), o guloso
    continua colocando B39 (40cm) enquanto couber - como o trecho inteiro
    e' multiplo de 40, sobra SEMPRE exatamente 40k - 35 = 40(k-1) + 5, ou
    seja, depois de esgotar os B39 que cabem sobra SEMPRE 5cm - e'
    EXATAMENTE 1 C04 (4cm+1cm de junta). Fecha para QUALQUER comprimento
    de trecho (inclusive os curtos, onde a UNICA alternativa so'-B34/B39,
    sem nenhum compensador, exigiria pelo menos 8 B34 de uma vez - prova
    da secao 3 - inviavel na pratica para a maioria dos pilaretes reais).
    Sem esta prova bater, a busca de amarracao para um trecho "fechado dos
    dois lados" (sem onde B19 encostar) fechando como multiplo exato de
    B39 nao tinha NENHUMA alternativa real - a mesma sequencia identica de
    B39 saia na Fiada A e na Fiada B, 100% das juntas coincidindo, na
    altura inteira da parede (o padrao medido no log real: juntas corridas
    em ate' 15 fiadas seguidas).

    `leading_is_open`/`trailing_is_open` (2026-08-25): so' controlam se a
    FUSAO de compensadores adjacentes (ver _merge_adjacent_compensator_
    pairs) pode "nascer" um B19 numa ponta - a mesma guarda que os tiers
    2/4/6 de `_pier_ordered_layout` ja' respeitam. Nao afetam qual bloco
    e' forcado PRIMEIRO aqui (nunca B19, ver acima) - so' evitam que a
    fusao interna produza um B19 encostado num no' fechado sem querer.

    Devolve uma lista (0 a N layouts, tipicamente 1-2) - nunca lanca
    excecao, nunca exige espaco extra: cada variante fecha o MESMO
    `pier_cm` exato que o layout padrao."""
    remaining = _pier_remaining_snapped_cm(pier_cm, leading_joint_cm, trailing_joint_cm)
    if remaining is None or remaining <= PIER_LAYOUT_TOLERANCE_CM:
        return []
    is_comp = lambda code: catalog.get(code, {}).get("is_compensator")  # noqa: E731
    all_codes = _pier_codes_by_len_desc(catalog, allow_compensators, pool=COMMON_FILL_BLOCK_CODES)
    codes_no_half = [c for c in all_codes if c != HALF_BLOCK_CODE]

    def _forced_first(first_code):
        # `codes_no_half` (nao so' B34/B39) na CONTINUACAO tambem, nao so'
        # no primeiro bloco - e' o que permite o guloso encontrar sozinho
        # o "sobra exatamente 5cm -> 1 C04" da prova acima, sem precisar
        # calcular a aritmetica na mao aqui.
        if first_code not in codes_no_half:
            return None
        layout = _greedy_fill_blocks(remaining, leading_joint_cm, catalog, codes_no_half,
                                     first_code=first_code)
        if layout is None:
            return None
        merged = _merge_adjacent_compensator_pairs(layout, catalog, leading_is_open, trailing_is_open)
        comp_count = sum(1 for code, _a, _b in merged if is_comp(code))
        if comp_count > MAX_COMPENSATORS_PER_TRECHO:
            return None
        return merged

    out = []
    alt = _forced_first(MID_WALL_BLOCK_CODE)
    if alt is not None:
        out.append(alt)
    if allow_compensators:
        for comp_code in all_codes:
            if not is_comp(comp_code):
                continue
            alt = _forced_first(comp_code)
            if alt is not None:
                out.append(alt)
    return out


def _layout_compensator_run_excess(layout, catalog):
    """Quanto `layout` viola a regra #2 (secao 2 de
    REGRAS_MODULACAO_BLOCOS.md: "proibido usar 2 ou mais compensadores em
    sequencia no mesmo trecho"): 0 quando nenhuma sequencia passa de UM
    compensador; senao a soma dos EXCEDENTES de cada sequencia (dois
    seguidos -> 1, quatro seguidos -> 3). Medida continua de propositio,
    para a busca preferir a MENOR violacao quando toda alternativa viola.

    Usada como criterio PRIMARIO em `_pier_layout_avoiding_joints` (bug
    real medido ao vivo via MCP, 2026-08-28): sem ela, `_score` so' olhava
    coincidencia de junta, e um candidato como `C04+C09+C09+C04` (QUATRO
    compensadores seguidos) vencia o baseline `B19+C09` so' por
    desencontrar a junta - um layout que `validate_wall_modulation` reprova
    logo em seguida em `sem_compensadores_consecutivos`. Trocar uma junta
    coincidente (que o pipeline registra em `alignment_conflicts` e escala
    para ajuste geometrico) por uma parede REPROVADA nunca e' um bom
    negocio."""
    excess = 0
    run = 0
    for item in layout or []:
        entry = (catalog or {}).get(item[0]) or {}
        if entry.get("is_compensator"):
            run += 1
        else:
            excess += max(0, run - 1)
            run = 0
    return excess + max(0, run - 1)


# Afastamento (cm) que se BUSCA entre uma junta desta fiada e a junta mais
# proxima da fiada oposta - o "travamento" vertical do prisma. Nao e' um
# bloqueio: e' o alvo a partir do qual a composicao ja' e' considerada boa o
# bastante, usado como criterio de DESEMPATE em `_pier_layout_avoiding_
# joints` (regra 18.6). Conservador de proposito, abaixo dos ~15cm medidos
# num projeto real (secao 10.6), que ainda estao rotulados como PADRAO
# OBSERVADO AINDA NAO CONFIRMADO.
MIN_JOINT_STAGGER_TARGET_CM = 10.0


def _layout_min_joint_stagger_cm(layout, seg_start_cm, avoid_positions_cm):
    """Menor distancia entre uma junta INTERNA de `layout` e a junta mais
    proxima da fiada oposta (`avoid_positions_cm`). Quanto MAIOR, melhor o
    travamento vertical: e' o quanto o bloco de cima "monta" sobre a junta
    de baixo antes de terminar.

    Devolve `None` quando nao ha' com o que comparar (trecho de uma peca so,
    ou fiada oposta sem junta interna).

    REGRA 18.6 (2026-08-28, pedido do usuario): "a transicao entre um bloco
    de 34cm e um bloco de 39cm nao pode acontecer de forma aleatoria... so'
    deve ocorrer quando existir espaco suficiente na proxima fiada para que
    o bloco de 39cm seja encaixado corretamente e permita a continuidade do
    prisma". Duas composicoes podem ter ZERO coincidencia de junta (as duas
    passam na regra #1) e ainda assim uma travar muito melhor que a outra -
    e' esse o criterio que faltava."""
    if not avoid_positions_cm:
        return None
    juntas = _layout_internal_joint_positions_cm(layout, seg_start_cm)
    if not juntas:
        return None
    menor = None
    for pos in juntas:
        for outra in avoid_positions_cm:
            d = abs(pos - outra)
            if menor is None or d < menor:
                menor = d
    return menor


def _pier_layout_avoiding_joints(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                 seg_start_cm, avoid_positions_cm,
                                 allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                                 target_void_positions_cm=None,
                                 leading_is_open=True, trailing_is_open=True):
    """Como `_pier_ordered_layout`, mas escolhe entre variacoes do mesmo
    trecho (mudando so' o PRIMEIRO bloco, via `first_code`) pela AMARRACAO
    real entre Fiada A e Fiada B (secao 6 do prompt), em duas frentes:

      1. ALINHAR os vazios/celulas internas das pecas desta fiada com os
         vazios ja' usados pela fiada oposta no mesmo trecho
         (`target_void_positions_cm` - ver `_layout_void_positions_cm`).
         Pedido explicito do usuario (2026-08-21): "para o bloco de 39cm, o
         deslocamento entre a 1a e a 2a fiada deve ser de aproximadamente
         20cm, de forma que os vaos fiquem corretamente alinhados" - 20cm e'
         exatamente meio modulo de B39 (39+1cm de junta = 40cm, metade =
         20cm), o mesmo deslocamento que 1 UNICO B19 (19+1cm = 20cm) no
         inicio do trecho produz naturalmente - por isso HALF_BLOCK_CODE e'
         sempre a PRIMEIRA alternativa tentada abaixo.
      2. DESENCONTRAR as juntas de argamassa internas das ja' usadas pela
         fiada oposta (`avoid_positions_cm`) - com um deslocamento de meio
         modulo os dois objetivos quase sempre andam juntos (vazio de uma
         fiada cai sobre o vazio da outra exatamente quando a junta de uma
         cai fora da junta da outra).

    PRIORIDADE DA COMPARACAO (invertida em 2026-08-25 - CAUSA-RAIZ de um
    bug real medido nos proprios testes deste arquivo): coincidencia de
    junta e' o CRITERIO PRIMARIO/ABSOLUTO (regra #1, prioridade sobre
    qualquer outra coisa - pedido explicito do usuario, "nao pode ser
    flexibilizada"), alinhamento de vazio e' o desempate SECUNDARIO entre
    candidatos que ja' tem ZERO coincidencia. ANTES disto era o contrario
    (align primeiro, junta so' como desempate) - e' inofensivo enquanto os
    dois objetivos "andam juntos" (a maioria dos casos, ver item 2 acima),
    mas produz um resultado ERRADO exatamente no caso em que o layout
    PADRAO da Fiada B (sem nenhuma alternativa) e' IDENTICO ao da Fiada A
    (mesmo pilarete, mesmas juntas de contorno - o layout e' uma funcao
    deterministica dos mesmos parametros): comparado contra si mesmo, o
    alinhamento de vazio da PROPRIA copia sai PERFEITO por construcao
    (trivial - e' o mesmo vazio no mesmo lugar), mas junto com o PIOR
    resultado possivel de coincidencia de junta (tambem o mesmo lugar,
    100% coincidindo) - com align primeiro, esse "empate perfeito consigo
    mesmo" vencia QUALQUER alternativa real que evitasse a junta mas nao
    alinhasse vazio nenhum (medido nos testes de ETAPA 3C: um pilarete
    isolado, ambas as pontas livres, sem abertura no meio - a copia
    identica ganhava da alternativa de verdade). Com junta primeiro, isso
    nao acontece mais: qualquer candidato com ZERO coincidencia bate a
    copia identica (que tem coincidencia MAXIMA), nao importa o alinhamento.

    O layout PADRAO (sem forcar primeiro bloco) e' sempre calculado
    primeiro; so' e' trocado por uma alternativa se ela tiver MENOS
    coincidencia de junta (ou igual coincidencia e alinhamento de vazio
    ESTRITAMENTE MELHOR). Se nenhuma alternativa melhorar, devolve o
    layout padrao mesmo assim - so' pode acontecer quando literalmente
    nenhuma composicao do catalogo evita a coincidencia (ver
    alignment_conflicts em solve_wall_free_fill, que registra esse caso
    residual para o pipeline tentar um ajuste geometrico em vez de aceitar
    em silencio - regra #1 nunca e' flexibilizada, mas tambem nao pode
    inventar geometria que nao existe). Devolve None quando o trecho
    simplesmente nao fecha em blocos (mesmo caso de _pier_ordered_layout,
    tratado pelo chamador como NON_MODULAR_WALL).

    `leading_is_open`/`trailing_is_open`: True SO' quando aquele lado do
    trecho encosta numa abertura real ou numa PONTA LIVRE de verdade da
    parede - nunca num encontro L/T/X (ver `solve_wall_free_fill`, onde
    isto e' calculado a partir de kind_left/kind_right). Controla se o
    MEIO BLOCO (B19) pode ser tentado NAQUELE lado como deslocamento de
    meio modulo - regra da secao 2 (REGRAS_MODULACAO_BLOCOS.md): B19 so'
    encosta em ponta aberta, nunca contra um no' de amarracao. Corrige
    regressao real (2026-08-24): a permissao anterior "mesmo numa ponta
    FECHADA contra outro bloco/no'" (2026-08-21) fazia B19 aparecer
    repetido em praticamente todo encontro L/T/X do predio."""
    baseline = _pier_ordered_layout(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                    allow_compensators=allow_compensators,
                                    leading_open_override=leading_is_open,
                                    trailing_open_override=trailing_is_open)
    if baseline is None:
        return None
    if len(baseline) <= 1 or (not avoid_positions_cm and not target_void_positions_cm):
        return baseline

    def _score(layout):
        # (excesso de compensadores em sequencia [PRIMARIO, regra #2 - ver
        # _layout_compensator_run_excess], coincidencia de junta
        # [SECUNDARIO, regra #1], -alinhamento de vazio [desempate
        # TERCIARIO, maior align = melhor]) - MENOR e' melhor. Ver o
        # comentario longo no docstring sobre a inversao junta x align
        # (2026-08-25) e por que o align nao pode vir primeiro; a regra #2
        # entrou na frente das duas em 2026-08-28, porque um layout com
        # compensadores em sequencia e' REPROVADO por
        # validate_wall_modulation de qualquer jeito - nao e' uma solucao
        # melhor, e' uma nao-solucao que so' parecia boa por desencontrar.
        comp_excess = _layout_compensator_run_excess(layout, catalog)
        # NAO aplica a isencao de peca-encostada-em-abertura aqui de
        # proposito (ver _layout_internal_joint_positions_cm): a isencao diz
        # que essa junta PODE coincidir, nao que ela deva ser ignorada na
        # BUSCA. Contando todas as juntas, a busca continua preferindo uma
        # composicao que desencontra de verdade quando ela existe; a isencao
        # so' entra na hora de VALIDAR o resultado (alignment_conflicts /
        # audit_wall_bond_quality), para nao reprovar o que a regra permite.
        joint_coinc = _count_joint_coincidences_cm(
            _layout_internal_joint_positions_cm(layout, seg_start_cm), avoid_positions_cm
        ) if avoid_positions_cm else 0
        align = _count_void_alignment_cm(
            _layout_void_positions_cm(layout, catalog, seg_start_cm), target_void_positions_cm
        ) if target_void_positions_cm else 0
        # REGRA 18.6: entre candidatos que ja' empataram nos criterios
        # acima (mesma violacao da regra #2, mesma coincidencia de junta),
        # prefere o que TRAVA melhor - a junta mais proxima da fiada oposta
        # o mais longe possivel. Satura em MIN_JOINT_STAGGER_TARGET_CM:
        # passar disso nao e' melhor, so' diferente, e continuar premiando
        # empurraria o layout para extremos sem ganho construtivo.
        stagger = _layout_min_joint_stagger_cm(layout, seg_start_cm, avoid_positions_cm)
        trava = MIN_JOINT_STAGGER_TARGET_CM if stagger is None else min(
            stagger, MIN_JOINT_STAGGER_TARGET_CM)
        return (comp_excess, joint_coinc, -trava, -align)

    best = baseline
    best_score = _score(baseline)
    max_align = len(target_void_positions_cm) if target_void_positions_cm else 0
    perfect_score = (0, 0, -MIN_JOINT_STAGGER_TARGET_CM, -max_align)
    if best_score == perfect_score:
        return best

    # Candidato dedicado: B19 FORCADO no inicio do trecho (ver
    # _half_block_leading_layout) - o deslocamento de meio modulo que o
    # usuario descreveu explicitamente (~20cm para B39). So' entra na
    # busca quando ha' um ALVO de vazio para perseguir: sem
    # `target_void_positions_cm`, manter o comportamento antigo exato
    # (so' desencontro de junta) para nao introduzir B19 onde nenhum
    # chamador pediu alinhamento de vazio.
    if target_void_positions_cm and leading_is_open:
        forced_half = _half_block_leading_layout(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                                 allow_compensators=allow_compensators,
                                                 trailing_is_open=trailing_is_open)
        if forced_half is not None:
            forced_score = _score(forced_half)
            if forced_score < best_score:
                best, best_score = forced_half, forced_score
                if best_score == perfect_score:
                    return best

    # Candidatos "bypass de tier" (B34/compensador como primeiro bloco,
    # mesmo quando o tier 1 - so' B39 - tambem fecharia): CAUSA-RAIZ
    # corrigida (2026-08-25) da maioria das juntas verticais corridas
    # medidas numa execucao real - ver docstring de
    # `_pier_forced_bypass_layouts`. Sem isto, um trecho entre dois
    # encontros L/T/X (as duas pontas fechadas - sem onde B19 encostar)
    # que fecha como um multiplo exato de B39 NUNCA tinha nenhuma
    # alternativa real de desencontro - a Fiada B saia identica a Fiada A,
    # 100% das juntas coincidindo, na altura inteira da parede. Sempre
    # calculado (independente de target_void_positions_cm - mesmo so'
    # desencontrar junta, sem alvo de vazio, ja' e' melhor que nenhuma
    # alternativa nenhuma).
    for alt in _pier_forced_bypass_layouts(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                           allow_compensators=allow_compensators,
                                           leading_is_open=leading_is_open, trailing_is_open=trailing_is_open):
        alt_score = _score(alt)
        if alt_score < best_score:
            best, best_score = alt, alt_score
            if best_score == perfect_score:
                return best

    # Demais codigos como PRIMEIRO bloco (dentro das regras normais de
    # `_pier_ordered_layout`, B19 so' entra aqui se a ponta for aberta) -
    # so' como alternativa quando os candidatos dedicados acima nao se
    # aplicam ou nao chegam ao alinhamento maximo.
    codes_by_len_desc = _pier_codes_by_len_desc(catalog, allow_compensators, pool=OPENING_JAMB_BLOCK_CODES)
    if not leading_is_open:
        # B19 so' pode ser o PRIMEIRO bloco do trecho quando o lado
        # esquerdo e' uma ponta aberta de verdade - excluido da busca de
        # alternativas quando o trecho comeca contra um no' L/T/X.
        codes_by_len_desc = [c for c in codes_by_len_desc if c != HALF_BLOCK_CODE]

    for code in codes_by_len_desc:
        alt = _pier_ordered_layout(pier_cm, catalog, leading_joint_cm, trailing_joint_cm,
                                   first_code=code, allow_compensators=allow_compensators,
                                   leading_open_override=leading_is_open,
                                   trailing_open_override=trailing_is_open)
        if alt is None:
            continue
        alt_score = _score(alt)
        if alt_score < best_score:
            best, best_score = alt, alt_score
            if best_score == perfect_score:
                break
    return best


def _place_pier_layout(layout, catalog, origin_point, direction, course, wall_idx,
                       node_index=None, placement_reason="STANDARD_FILL"):
    """Converte um layout 1D (ver _pier_ordered_layout) em
    BlockPlacementCandidate - `origin_point` e' o t=0 do trecho (Z=0,
    mundo) e `direction` e' o sentido em que start_cm/end_cm crescem."""
    candidates = []
    for code, start_cm, end_cm in layout:
        entry = catalog[code]
        center_cm = (start_cm + end_cm) / 2.0
        origin = origin_point + direction * _cm_to_ft(center_cm)
        candidates.append(_make_block_candidate(
            code, entry, course, origin, direction, placement_reason,
            node_index=node_index, wall_idx=wall_idx,
        ))
    return candidates


def _candidate_extent_on_wall_axis(candidate, wall_p0, wall_dir):
    """(t_start_cm, t_end_cm) que o CORPO de `candidate` ocupa ao longo do
    eixo de uma parede (p0 + t*dir), valendo para QUALQUER orientacao
    relativa - projeta o retangulo orientado da peca (comprimento no x_dir
    dela, largura no y_dir) sobre `wall_dir`.

    Diferente de _candidate_t_range_on_wall, que so' vale quando a peca e'
    paralela a' parede: um B34 de canto pertence a UMA das paredes do L,
    mas atravessa fisicamente a OUTRA (pela largura), e e' exatamente essa
    invasao que o preenchimento da vizinha precisa respeitar na mesma
    fiada."""
    half_length_ft = _cm_to_ft(candidate["length_cm"]) / 2.0
    half_width_ft = _cm_to_ft(candidate["width_cm"]) / 2.0
    half_extent_ft = (
        abs(half_length_ft * candidate["x_dir"].DotProduct(wall_dir))
        + abs(half_width_ft * candidate["y_dir"].DotProduct(wall_dir))
    )
    center_t_ft = (candidate["origin_world"] - wall_p0).DotProduct(wall_dir)
    return ((center_t_ft - half_extent_ft) / FEET_PER_METER * 100.0,
            (center_t_ft + half_extent_ft) / FEET_PER_METER * 100.0)


def _node_candidates_by_index(intersection_candidates):
    """{node_index: [candidato, ...]} - agrupa os candidatos de amarracao
    (L/T/X) pelo no' em que foram gerados."""
    by_node = {}
    for cand in intersection_candidates:
        node_index = cand.get("node_index")
        if node_index is None:
            continue
        by_node.setdefault(node_index, []).append(cand)
    return by_node


def _node_involved_wall_ends(node, node_candidates, walls_to_create, end_to_node,
                             node_index, tolerance_ft=JUNCTION_FACE_SEARCH_FT):
    """{wall_idx: end_index} de TODAS as paredes que este no' realmente
    toca por uma PONTA - nao so' as declaradas em `node["arms"]`.

    Existe por causa de um caso real da planta do usuario (medido em
    2026-08-21): o no' 3 e' um L_CORNER com `arms = [(1, 1)]` - UM unico
    braco - mas o solver do canto coloca peca nas DUAS paredes (a Fiada A
    e' um B34 da parede 1, a Fiada B um B34 da parede 14). A ponta da
    parede 14 tinha sido classificada como FREE_END num no' SEPARADO
    alguns centimetros ao lado, entao ela nao aparecia em `arms`, nao
    reservava nada, e o preenchimento dela nascia em t=0 - DENTRO das duas
    pecas do canto. Era a maior fatia das 171 colisoes medidas.

    Em vez de mexer na classificacao do grafo (que tem outros usos e outros
    riscos), a reserva passa a olhar de quem sao as PECAS do no': se um
    candidato pertence a uma parede cuja ponta cai a `tolerance_ft` do
    ponto do no', aquela ponta tambem reserva.

    GUARDA (bug real, medido 2026-08-25): a heuristica de distancia acima
    confundia um encontro T/X que cai perto da PONTA de outra parede na
    MESMA parede principal - a distancia entre o no' T e a ponta da parede
    principal podia ser menor que `tolerance_ft` (40cm) so' porque as duas
    juncoes estao proximas uma da outra, sem a parede principal ESTAR perto
    da ponta dela mesma. O candidato da parede PRINCIPAL de um T (ou de
    QUALQUER parede que cruza num X) e' SEMPRE de meio de parede por
    construcao (ver _midspan_node_wall_ids) - nunca uma ponta de verdade -
    entao essas paredes sao excluidas aqui incondicionalmente, antes da
    checagem de distancia. Sem isto, a reserva de INICIO da parede
    principal era calculada a partir da peca do T (muito mais longe do
    real inicio da parede), gerando trechos de comprimento NEGATIVO no
    preenchimento comum."""
    ends = {}
    for wall_idx, end_index in node.get("arms") or []:
        if end_to_node.get((wall_idx, end_index)) == node_index:
            ends[wall_idx] = end_index
    point = node.get("point")
    if point is None:
        return ends
    midspan_wall_idxs = set(_midspan_node_wall_ids(node))
    for cand in node_candidates:
        wall_idx = cand.get("wall_idx")
        if wall_idx is None or wall_idx in ends or wall_idx >= len(walls_to_create):
            continue
        if wall_idx in midspan_wall_idxs:
            continue  # sempre meio de parede aqui - nunca ponta de verdade
        p0, p1, _wall_dir, _length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
        dist0 = XYZ(p0.X - point.X, p0.Y - point.Y, 0.0).GetLength()
        dist1 = XYZ(p1.X - point.X, p1.Y - point.Y, 0.0).GetLength()
        if min(dist0, dist1) > tolerance_ft:
            continue  # o no' cai no MEIO desta parede - quem trata e' o indexador midspan
        ends[wall_idx] = 0 if dist0 <= dist1 else 1
    return ends


def _index_node_candidates_by_wall_end(nodes, intersection_candidates, walls_to_create,
                                       end_to_node):
    """{(wall_idx, end_index, course): borda_cm} - ate' onde, na direcao do
    interior da parede, o preenchimento daquela fiada NAO pode entrar
    porque uma peca de amarracao do no' ja' esta' la'.

    A borda considera TODAS as pecas do no' naquela fiada, nao so' a que
    "pertence" aquela parede: num canto em L, a fiada A tem uma unica peca
    (o B34 de uma das duas paredes), e o corpo dela ocupa o quadrado do
    canto - ou seja, tambem o inicio da parede VIZINHA. Contabilizar so' a
    peca propria era o que fazia o preenchimento da vizinha nascer dentro
    do canto e colidir (reproduzido em L e em X nos testes)."""
    index = {}
    by_node = _node_candidates_by_index(intersection_candidates)
    for node_index, node in enumerate(nodes):
        node_candidates = by_node.get(node_index)
        if not node_candidates:
            continue
        involved = _node_involved_wall_ends(
            node, node_candidates, walls_to_create, end_to_node, node_index
        )
        for wall_idx, end_index in involved.items():
            p0, _p1, wall_dir, _len, _t = _wall_axis_and_length(walls_to_create, wall_idx)
            for cand in node_candidates:
                t_start_cm, t_end_cm = _candidate_extent_on_wall_axis(cand, p0, wall_dir)
                border_cm = t_end_cm if end_index == 0 else t_start_cm
                key = (wall_idx, end_index, cand["course"])
                current = index.get(key)
                if current is None:
                    index[key] = border_cm
                elif end_index == 0:
                    index[key] = max(current, border_cm)
                else:
                    index[key] = min(current, border_cm)
    return index


def _candidate_t_range_on_wall(candidate, wall_p0, wall_dir):
    """(t_start_cm, t_end_cm) que `candidate` ocupa ao longo do eixo de
    UMA parede (p0 + t*dir) - projeta o CENTRO no eixo e usa metade do
    comprimento fisico da peca (valido porque x_dir do candidato e' sempre
    paralelo/antiparalelo a `wall_dir` quando o candidato pertence a esta
    parede, por construcao das Etapas 4/5)."""
    half_ft = _cm_to_ft(candidate["length_cm"]) / 2.0
    center_t_ft = (candidate["origin_world"] - wall_p0).DotProduct(wall_dir)
    return ((center_t_ft - half_ft) / FEET_PER_METER * 100.0,
            (center_t_ft + half_ft) / FEET_PER_METER * 100.0)


def _node_default_reservation_cm(walls_to_create, node):
    """Reserva MINIMA (cm), a partir do ponto do no', para uma parede+fiada
    que NAO tem candidato de encontro proprio ali (ver
    _index_node_candidates_by_wall_end) mas cujo no' NAO e' FREE_END.
    Cobre o corpo de uma peca de amarracao da OUTRA parede deste no' (ela
    e' tao larga quanto a espessura dela - secao 15 - e atravessa
    fisicamente esta regiao mesmo sem um candidato proprio NESTA parede:
    e' exatamente o caso do B34 de um L_CORNER, cuja LARGURA se estende
    pela parede vizinha na fiada em que ela nao tem peca especial nenhuma -
    ver achado empirico no cabecalho da secao). Usa a MAIOR espessura entre
    as paredes deste no' - conservador, protege contra colisao sem
    precisar identificar qual peca especifica esta' la'."""
    wall_idxs = set()
    for w, _e in (node.get("arms") or []):
        wall_idxs.add(w)
    for key in ("main_wall_idx", "incoming_wall_idx", "neighbor_wall_idx"):
        if node.get(key) is not None:
            wall_idxs.add(node[key])
    crossing = node.get("crossing_walls")
    if crossing:
        wall_idxs.update(w for w in crossing if w is not None)
    thicknesses_ft = [walls_to_create[w][1] for w in wall_idxs if 0 <= w < len(walls_to_create)]
    if not thicknesses_ft:
        return 0.0
    return (max(thicknesses_ft) / 2.0) / FEET_PER_METER * 100.0


def _wall_end_default_start_cm(nodes, end_to_node, walls_to_create, wall_idx, end_index):
    """(reserva_cm, junta_cm) para a ponta `end_index` de `wall_idx` quando
    esta fiada NAO tem candidato de encontro proprio ali: FREE_END/
    STRAIGHT_CONTINUATION (ou ponta fora do grafo) -> nada para encostar
    (0, 0 - BLOCK_OPENING_JOINT_CM); qualquer outro tipo de no' -> reserva
    ao menos meia espessura da MAIOR parede deste no' (ver
    _node_default_reservation_cm) mais uma junta normal depois dela.

    STRAIGHT_CONTINUATION nao reserva nada (bug real corrigido 2026-08-28,
    medido ao vivo via MCP contra uma parede que o usuario modulou a mao
    para servir de referencia): a reserva de `_node_default_reservation_cm`
    existe para cobrir o CORPO de uma peca de amarracao da parede vizinha
    que atravessa esta regiao - e numa continuacao reta essa peca NAO
    EXISTE. `solve_all_intersections` ignora explicitamente os nos
    FREE_END/STRAIGHT_CONTINUATION/AMBIGUOUS ("nao sao encontros de
    amarracao especial"), entao nenhum candidato e' gerado ali; reservar
    meia espessura + junta so' encolhia o trecho livre em ~8cm e fazia a
    modulacao "nao fechar" por poucos centimetros. Numa parede real de
    319cm (L_CORNER de um lado, STRAIGHT_CONTINUATION do outro) isso
    derrubava as duas fiadas; com a reserva zerada, a Fiada A passou a
    sair IDENTICA, peca por peca e posicao por posicao, a' que o usuario
    montou a mao (B34 + 7xB39 + C04).

    AMBIGUOUS continua reservando de proposito: neste projeto ele aparece
    onde duas paredes ocupam o MESMO eixo em planta em faixas de altura
    diferentes (peitoril x acima da verga), e ali existe peca de verdade -
    zerar a reserva nesses nos dobrou as colisoes na medicao (44 mil ->
    73 mil)."""
    node_index = end_to_node.get((wall_idx, end_index))
    node = nodes[node_index] if node_index is not None else None
    if node is None or node["kind"] in ("FREE_END", "STRAIGHT_CONTINUATION"):
        return 0.0, BLOCK_OPENING_JOINT_CM
    # A reserva e' medida a partir do PONTO DO NO' (o encontro fisico), que
    # nao coincide com a ponta da parede: extend_wall_ends_to_junctions puxa
    # a ponta para ALEM do encontro, ate' a face oposta da vizinha (ver
    # _wall_node_arms). Sem somar esse recuo, o preenchimento comecava
    # dentro do corpo da peca de amarracao da parede vizinha e colidia com
    # ela - reproduzido em canto L e em cruz X nos testes.
    return (
        _node_offset_along_wall_cm(walls_to_create, wall_idx, end_index, node)
        + _node_default_reservation_cm(walls_to_create, node),
        BLOCK_JOINT_CM,
    )


def _node_offset_along_wall_cm(walls_to_create, wall_idx, end_index, node):
    """Distancia (cm, nunca negativa), medida ao longo do eixo de
    `wall_idx` e no sentido de DENTRO da parede, entre a ponta `end_index`
    e o ponto do no' - o recuo que extend_wall_ends_to_junctions aplicou
    naquela ponta. Zero quando a ponta ja' esta' no proprio no'."""
    point = node.get("point")
    if point is None:
        return 0.0
    p0, p1, wall_dir, _length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
    end_point, inward_dir = (p0, wall_dir) if end_index == 0 else (p1, wall_dir * -1.0)
    offset_ft = (point - end_point).DotProduct(inward_dir)
    if offset_ft <= 0.0:
        return 0.0
    return offset_ft / FEET_PER_METER * 100.0


def _midspan_node_wall_ids(node):
    """Paredes as quais `node` se relaciona no MEIO (nao numa ponta):
    T_INTERSECTION -> so' a mainWall (a incomingWall TERMINA ali, e' ponta
    dela, ja' coberta por _index_node_candidates_by_wall_end/
    _wall_end_default_start_cm); X_INTERSECTION de meio de parede -> as
    duas de crossing_walls. Lista vazia para qualquer outro tipo de no'."""
    if node["kind"] == "T_INTERSECTION" and node.get("main_wall_idx") is not None:
        return [node["main_wall_idx"]]
    if node["kind"] == "X_INTERSECTION" and node.get("crossing_walls"):
        return [w for w in node["crossing_walls"] if w is not None]
    return []


def _index_node_candidates_midspan(nodes, intersection_candidates, walls_to_create, end_to_node):
    """{(wall_idx, course): [(t_start_cm, t_end_cm), ...]} - trechos que o
    preenchimento comum precisa EXCLUIR por caírem no MEIO de `wall_idx`
    (nao numa ponta dela - o caso de T/X de meio de parede, ver
    _find_wall_midspan_crossings).

    Como no indexador das pontas (_index_node_candidates_by_wall_end), a
    reserva vem da EXTENSAO REAL de cada peca do no' projetada no eixo
    desta parede, em cada fiada - inclusive das pecas que pertencem a'
    OUTRA parede do encontro, que atravessam esta pela largura. So' quando
    uma fiada nao tem nenhuma peca no no' e' que entra a reserva minima
    generica (_node_default_reservation_cm)."""
    by_wall_course = {}
    by_node = _node_candidates_by_index(intersection_candidates)

    for node_index, node in enumerate(nodes):
        node_candidates = by_node.get(node_index) or []
        midspan_walls = _midspan_node_wall_ids(node)
        for wall_idx in midspan_walls:
            p0, _p1, wall_dir, _len, _t = _wall_axis_and_length(walls_to_create, wall_idx)
            node_t_cm = (node["point"] - p0).DotProduct(wall_dir) / FEET_PER_METER * 100.0
            for course in ("A", "B"):
                course_candidates = [c for c in node_candidates if c["course"] == course]
                if course_candidates:
                    for cand in course_candidates:
                        by_wall_course.setdefault((wall_idx, course), []).append(
                            _candidate_extent_on_wall_axis(cand, p0, wall_dir)
                        )
                    continue
                reservation_cm = _node_default_reservation_cm(walls_to_create, node)
                if reservation_cm <= 1e-6:
                    continue
                by_wall_course.setdefault((wall_idx, course), []).append(
                    (node_t_cm - reservation_cm, node_t_cm + reservation_cm)
                )
    return by_wall_course


def _merge_intervals_cm(intervals, tolerance_cm=1e-6):
    """Mescla intervalos (start_cm, end_cm) sobrepostos ou repetidos numa
    lista ordenada e disjunta - ver o uso em solve_wall_free_fill."""
    ordered = sorted(
        (min(a, b), max(a, b)) for a, b in intervals or []
    )
    merged = []
    for start_cm, end_cm in ordered:
        if merged and start_cm <= merged[-1][1] + tolerance_cm:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_cm))
        else:
            merged.append((start_cm, end_cm))
    return merged


def solve_wall_free_fill(wall_idx, walls_to_create, nodes, end_to_node, openings_per_wall,
                         node_candidates_by_wall_end, node_midspan_by_wall_course,
                         catalog, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                         variants_per_course=1):
    """Preenchimento comum (secao 13: 'no -> abertura, abertura ->
    abertura, abertura -> no') de UMA parede, nas duas FAMILIAS de fiada
    (par/impar - "A"/"B"). Para cada abertura, materializa tambem o bloco
    de jamb correspondente (Etapa 5, solve_opening_jamb) - a Etapa 5 so'
    calcula QUAL bloco encosta na abertura, quem preenche o RESTO do
    pilarete ate' o proximo obstaculo e' esta funcao. Tambem exclui os
    trechos ja' reservados por um encontro no MEIO da parede (ver
    node_midspan_by_wall_course) - PODE dar fronteiras DIFERENTES entre as
    duas familias (uma peca de meio-de-parede so' existe numa delas), por
    isso cada familia e' resolvida com sua PROPRIA lista de fronteiras,
    nao mais uma unica lista compartilhada.

    `variants_per_course` (secao 11.7 do REGRAS_MODULACAO_BLOCOS.md,
    2026-08-25 - CAUSA-RAIZ de um bug real medido em producao: 118/128
    paredes reprovadas na auditoria de amarracao so' porque cada familia
    A/B repetia CEGAMENTE o MESMO layout em 100% das fiadas fisicas da
    sua paridade, sempre >= o limite de 60% de BOND_ALTERNATING_JOINT_
    RATIO): quantas variacoes DISTINTAS gerar DENTRO de cada familia (>1
    faz `course_candidates` de solve_building_blocks_all_courses girar
    entre elas por fiada FISICA, em vez de repetir uma unica composicao
    para sempre). Cada variante K>=1 da familia A evita a UNIAO das
    juntas internas de TODAS as variantes 0..K-1 ja' geradas (generaliza
    `_pier_layout_avoiding_joints`, que antes so' via a Fiada B evitar A);
    a familia B faz o mesmo, comecando por evitar TODA a familia A (regra
    #1, absoluta, preservada integralmente) e depois suas proprias
    variantes anteriores. `variants_per_course=1` (default, usado por
    todo chamador que nao pediu explicitamente mais - ex.: os testes
    deste arquivo) reduz este laco a exatamente o comportamento historico
    (1 layout "A", 1 layout "B" evitando A) - nenhuma alteracao de
    resultado nesse caso.

    Devolve {"candidates": [...], "jamb_exceptions": [...],
    "non_modular": [...], "alignment_conflicts": [...]} - 'non_modular' e' a
    lista de trechos que nao fecharam em blocos (NON_MODULAR_WALL, secao
    21), com a sugestao de ajuste mais proxima (reusa
    _nearest_valid_lengths_cm). 'alignment_conflicts' (regra #1, absoluta,
    prioridade OBRIGATORIA sobre so' preencher o comprimento - pedido
    explicito do usuario, 2026-08-25): trechos em que, mesmo depois da
    busca de `_pier_layout_avoiding_joints` (que agora alcanca de verdade
    B34/compensador como alternativa - ver `_pier_forced_bypass_layouts`),
    uma variante nao encontrou NENHUMA composicao sem coincidencia de
    junta vertical com as variantes anteriores - nunca aceito em silencio
    (ver validate_wall_modulation/needs_fix em process_walls_one_by_one,
    que tenta um ajuste geometrico quando isto acontece, e o relatorio
    final, que reporta qualquer caso que sobreviva mesmo depois disso).
    Cada entrada de 'non_modular'/'alignment_conflicts' carrega tambem
    "variant_index" (0-based, dentro da familia "course") para o
    relatorio conseguir dizer EXATAMENTE qual das `variants_per_course`
    composicoes falhou, nao so' "a familia B falhou"."""
    _centerline, _thickness_ft, _locks = walls_to_create[wall_idx]
    p0, _p1, wall_dir, length_ft, _t = _wall_axis_and_length(walls_to_create, wall_idx)
    length_cm = length_ft / FEET_PER_METER * 100.0

    openings_sorted = sorted(openings_per_wall[wall_idx], key=lambda o: o[0]) \
        if openings_per_wall[wall_idx] else []

    base_boundaries = [(0.0, "WALL_START", None)]
    for oi, op in enumerate(openings_sorted):
        base_boundaries.append((op[0] / FEET_PER_METER * 100.0, "OPENING_LO", oi))
        base_boundaries.append((op[1] / FEET_PER_METER * 100.0, "OPENING_HI", oi))
    base_boundaries.append((length_cm, "WALL_END", None))

    candidates = []
    jamb_exceptions = []
    non_modular = []
    alignment_conflicts = []
    jamb_cache = {}
    # Juntas internas (cm, absolutas ao longo da parede) ja' usadas pela
    # Fiada A nos trechos de preenchimento comum - preenchido durante o
    # processamento de "A" (que roda primeiro, ver `for course in ("A",
    # "B")` abaixo) e consultado ao resolver "B", para o desencontro de
    # junta vertical entre fiadas da secao 6 (_pier_layout_avoiding_joints).
    course_a_joint_positions_cm = []
    # Centros dos vazios/celulas internas (cm, absolutos) ja' usados pela
    # Fiada A nos mesmos trechos - consultado ao resolver "B" para alinhar
    # os vazios entre fiadas (mesma secao 6, ver _pier_layout_avoiding_joints
    # e _layout_void_positions_cm). Pedido explicito do usuario (2026-08-21).
    course_a_void_positions_cm = []

    def get_jamb(opening_index, side):
        key = (opening_index, side)
        if key not in jamb_cache:
            result = solve_opening_jamb(walls_to_create, wall_idx, openings_sorted, opening_index,
                                        side, catalog, allow_compensators=allow_compensators,
                                        variant_count=variants_per_course)
            result["wall_idx"] = wall_idx
            result["opening_index"] = opening_index
            result["side"] = side
            jamb_cache[key] = result
            if result["exception"]:
                jamb_exceptions.append(result)
        return jamb_cache[key]

    for course in ("A", "B"):
        boundaries = list(base_boundaries)
        # Intervalos de meio-de-parede sao MESCLADOS antes de virar
        # fronteira: dois encontros muito proximos (ou o mesmo encontro
        # indexado duas vezes) produziam intervalos sobrepostos, e a
        # sequencia resultante (MIDSPAN_LO, MIDSPAN_LO) caia no ramo
        # "OPENING_HI" do laco abaixo com opening_index=None, quebrando a
        # execucao inteira com TypeError. Mesclando, cada regiao reservada
        # vira um unico par LO/HI e a sequencia volta a ser sempre valida.
        for t_start_cm, t_end_cm in _merge_intervals_cm(
            node_midspan_by_wall_course.get((wall_idx, course), [])
        ):
            boundaries.append((t_start_cm, "MIDSPAN_LO", None))
            boundaries.append((t_end_cm, "MIDSPAN_HI", None))
        boundaries.sort(key=lambda b: b[0])

        # Juntas internas ja' usadas por VARIANTES ANTERIORES desta MESMA
        # familia (secao 11.7) - comeca vazia a cada familia nova; a
        # familia "B" comeca sua PROPRIA busca considerando tambem tudo
        # que "A" acumulou (course_a_joint_positions_cm, abaixo), exatamente
        # como antes (regra #1, preservada integralmente).
        own_family_joint_positions_cm = []

        for variant_index in range(variants_per_course):
            for seg_i in range(len(boundaries) - 1):
                t_left, kind_left, oi_left = boundaries[seg_i]
                t_right, kind_right, oi_right = boundaries[seg_i + 1]
                # Marca onde comecam os candidatos DESTE trecho: se no fim
                # descobrirmos que ele nao tem espaco fisico nenhum, os jambs
                # emitidos abaixo precisam ser DESFEITOS (ver o teste de
                # `raw_pier_cm` mais adiante).
                seg_candidates_start = len(candidates)

                if kind_left == "OPENING_LO" and kind_right == "OPENING_HI" and oi_left == oi_right:
                    continue  # interior da propria abertura (vao)
                if kind_left == "MIDSPAN_LO" and kind_right == "MIDSPAN_HI":
                    continue  # interior do bloco de encontro de meio de parede

                # leading_is_open/trailing_is_open: True SO' quando a fronteira
                # deste lado do trecho e' uma abertura (porta/janela) real ou a
                # PONTA LIVRE de verdade da parede (sem no' nenhum ali) - NUNCA
                # quando e' um encontro L/T/X (WALL_START/END com `border` ja'
                # ocupado por um candidato de no', ou MIDSPAN_LO/HI). Controla
                # se o MEIO BLOCO (B19) pode aparecer aqui como deslocamento de
                # meio modulo (secao 6) - ver `_pier_layout_avoiding_joints`.
                # Corrige regressao real reportada pelo usuario (2026-08-24):
                # B19 aparecendo repetido em MUITOS encontros L/T/X do predio
                # inteiro (a permissao "mesmo numa ponta FECHADA contra outro
                # bloco/no'", de 2026-08-21, generalizava demais - a secao 2 e'
                # clara que B19 so' encosta em ponta aberta de verdade).
                #
                # NOTA (secao 11.7): boundaries/node_candidates_by_wall_end
                # dependem so' de `course` (par/impar), NUNCA de
                # `variant_index` - o encontro L/T/X reserva a MESMA posicao
                # em toda fiada da mesma paridade, por construcao (ver
                # BOND_STRIP_NODE_EXEMPT_CM). So' o JAMB (abaixo) varia por
                # variante.
                if kind_left == "WALL_START":
                    border = node_candidates_by_wall_end.get((wall_idx, 0, course))
                    if border is not None:
                        seg_start_cm = border + BLOCK_JOINT_CM
                        lead_cm = 0.0
                        leading_is_open = False
                    else:
                        seg_start_cm, lead_cm = _wall_end_default_start_cm(
                            nodes, end_to_node, walls_to_create, wall_idx, 0
                        )
                        leading_is_open = True
                elif kind_left == "MIDSPAN_HI":
                    seg_start_cm = t_left + BLOCK_JOINT_CM
                    lead_cm = 0.0
                    leading_is_open = False
                elif oi_left is None:
                    # Fronteira sem abertura associada que nao caiu em nenhum
                    # dos casos acima - nao ha' jamb para calcular; trata como
                    # inicio simples de trecho (rede de seguranca: antes disto
                    # o codigo seguia direto para o ramo de abertura e quebrava).
                    seg_start_cm = t_left
                    lead_cm = BLOCK_OPENING_JOINT_CM
                    leading_is_open = False
                else:  # OPENING_HI
                    jamb = get_jamb(oi_left, "right")
                    variant_key = "course_a_variants" if course == "A" else "course_b_variants"
                    cand = jamb[variant_key][variant_index]
                    if cand is not None:
                        cand["course_variant"] = variant_index
                        candidates.append(cand)
                        seg_start_cm = t_left + catalog[cand["logical_code"]]["length_cm"] + BLOCK_JOINT_CM
                        lead_cm = 0.0
                    else:
                        seg_start_cm = t_left
                        lead_cm = BLOCK_OPENING_JOINT_CM
                    leading_is_open = True

                if kind_right == "WALL_END":
                    border = node_candidates_by_wall_end.get((wall_idx, 1, course))
                    if border is not None:
                        seg_end_cm = border - BLOCK_JOINT_CM
                        trail_cm = 0.0
                        trailing_is_open = False
                    else:
                        reservation_cm, trail_cm = _wall_end_default_start_cm(
                            nodes, end_to_node, walls_to_create, wall_idx, 1
                        )
                        seg_end_cm = length_cm - reservation_cm
                        trailing_is_open = True
                elif kind_right == "MIDSPAN_LO":
                    seg_end_cm = t_right - BLOCK_JOINT_CM
                    trail_cm = 0.0
                    trailing_is_open = False
                elif oi_right is None:
                    seg_end_cm = t_right
                    trail_cm = BLOCK_OPENING_JOINT_CM
                    trailing_is_open = False
                else:  # OPENING_LO
                    jamb = get_jamb(oi_right, "left")
                    variant_key = "course_a_variants" if course == "A" else "course_b_variants"
                    cand = jamb[variant_key][variant_index]
                    if cand is not None:
                        cand["course_variant"] = variant_index
                        candidates.append(cand)
                        seg_end_cm = t_right - catalog[cand["logical_code"]]["length_cm"] - BLOCK_JOINT_CM
                        trail_cm = 0.0
                    else:
                        seg_end_cm = t_right
                        trail_cm = BLOCK_OPENING_JOINT_CM
                    trailing_is_open = True

                raw_pier_cm = seg_end_cm - seg_start_cm
                if raw_pier_cm < -PIER_LAYOUT_TOLERANCE_CM:
                    # NAO HA' ESPACO FISICO entre os dois limites deste trecho:
                    # tipicamente a abertura esta' dentro (ou colada demais) do
                    # que o encontro L/T/X reserva. Emitir o jamb aqui colocaria
                    # uma peca DENTRO do bloco de amarracao - era exatamente a
                    # colisao que bloqueava o botao "criar no Revit". Desfaz os
                    # jambs deste trecho e reporta como conflito, para o
                    # pipeline tentar AFASTAR a abertura (regra #3: o
                    # lancamento e' que decide o ajuste).
                    del candidates[seg_candidates_start:]
                    non_modular.append({
                        "wall_idx": wall_idx, "course": course, "variant_index": variant_index,
                        "segment_index": seg_i,
                        "current_length_cm": raw_pier_cm,
                        "leading_joint_cm": lead_cm, "trailing_joint_cm": trail_cm,
                        "seg_start_cm": seg_start_cm, "seg_end_cm": seg_end_cm,
                        "conflict": "SEM_ESPACO",
                        "lower_valid_cm": 0, "delta_to_lower_cm": 0,
                        "upper_valid_cm": 0, "delta_to_upper_cm": 0,
                        # Diagnostico (2026-08-25): a mensagem ate' aqui so' dizia
                        # "trecho com Xcm negativo", sem dizer QUAL fronteira
                        # (que encontro/abertura) esta' invadindo qual - impossivel
                        # de reproduzir fora do projeto real so' com isso. Guarda
                        # o TIPO de cada limite do trecho (WALL_START/WALL_END/
                        # OPENING_LO/OPENING_HI/MIDSPAN_LO/MIDSPAN_HI) e o `t`
                        # bruto de cada um (antes de qualquer reserva), para a
                        # mensagem no relatorio conseguir apontar exatamente onde
                        # o conflito esta'.
                        "left_kind": kind_left, "left_t_cm": t_left,
                        "right_kind": kind_right, "right_t_cm": t_right,
                    })
                    continue
                pier_cm = max(0.0, raw_pier_cm)
                origin = p0 + wall_dir * _cm_to_ft(seg_start_cm)

                if course == "A":
                    if variant_index == 0:
                        # Variante 0 e' sempre o layout PADRAO (guloso,
                        # maior bloco primeiro) - identico ao comportamento
                        # historico, nenhuma busca de desencontro.
                        layout = _pier_ordered_layout(pier_cm, catalog, lead_cm, trail_cm,
                                                      allow_compensators=allow_compensators,
                                                      leading_open_override=leading_is_open,
                                                      trailing_open_override=trailing_is_open)
                    else:
                        # Variantes 1+ da PROPRIA familia A (secao 11.7):
                        # desencontram as juntas das variantes A anteriores
                        # deste mesmo trecho - mesma busca que a Fiada B
                        # sempre usou contra A, generalizada para A evitar
                        # A. Sem alvo de vazio (nao ha' uma "familia oposta"
                        # fixa aqui para alinhar).
                        layout = _pier_layout_avoiding_joints(
                            pier_cm, catalog, lead_cm, trail_cm, seg_start_cm,
                            own_family_joint_positions_cm, allow_compensators=allow_compensators,
                            leading_is_open=leading_is_open, trailing_is_open=trailing_is_open,
                        )
                    if layout:
                        # Lista de juntas a EVITAR - sem isencao, pelo mesmo
                        # motivo do `_score` de _pier_layout_avoiding_joints:
                        # a Fiada B deve continuar tentando desencontrar
                        # todas, inclusive as isentas (a isencao so' vale na
                        # hora de validar o resultado final).
                        seg_joints_cm = _layout_internal_joint_positions_cm(layout, seg_start_cm)
                        own_family_joint_positions_cm.extend(seg_joints_cm)
                        course_a_joint_positions_cm.extend(seg_joints_cm)
                        course_a_void_positions_cm.extend(
                            _layout_void_positions_cm(layout, catalog, seg_start_cm)
                        )
                else:
                    # Fiada B (todas as variantes): tenta ALINHAR os vazios
                    # internos com os ja' usados por QUALQUER variante da
                    # Fiada A neste mesmo eixo (criterio principal) e
                    # desencontrar as juntas de argamassa internas de TODA a
                    # familia A e das variantes B ja' geradas (criterio de
                    # desempate) - secao 6/11.7. `course_a_joint_positions_cm`
                    # sozinho (sem own_family) e' EXATAMENTE o avoid-list
                    # historico quando variants_per_course=1.
                    layout = _pier_layout_avoiding_joints(
                        pier_cm, catalog, lead_cm, trail_cm, seg_start_cm,
                        course_a_joint_positions_cm + own_family_joint_positions_cm,
                        allow_compensators=allow_compensators,
                        target_void_positions_cm=course_a_void_positions_cm,
                        leading_is_open=leading_is_open, trailing_is_open=trailing_is_open,
                    )
                    if layout:
                        # Sem isencao aqui tambem - esta lista alimenta a
                        # BUSCA das variantes seguintes (ver acima).
                        own_family_joint_positions_cm.extend(
                            _layout_internal_joint_positions_cm(layout, seg_start_cm)
                        )
                if layout is None:
                    if pier_cm > 1e-6:
                        # Sugestao pela ARITMETICA REAL DOS BLOCOS deste trecho
                        # (juntas de contorno reais `lead_cm`/`trail_cm`), nunca
                        # mais pelo "termina em 0 ou 5" - ver a nota da regra
                        # de digito removida.
                        length_rounded = int(round(pier_cm))
                        lower, upper = nearest_block_lengths_cm(pier_cm, lead_cm, trail_cm)
                        non_modular.append({
                            "wall_idx": wall_idx, "course": course, "variant_index": variant_index,
                            "segment_index": seg_i,
                            "current_length_cm": pier_cm,
                            "leading_joint_cm": lead_cm, "trailing_joint_cm": trail_cm,
                            "seg_start_cm": seg_start_cm, "seg_end_cm": seg_end_cm,
                            "lower_valid_cm": lower, "delta_to_lower_cm": length_rounded - lower,
                            "upper_valid_cm": upper, "delta_to_upper_cm": upper - length_rounded,
                        })
                    continue
                if course == "B" and len(layout) > 1 and course_a_joint_positions_cm:
                    # Segunda checagem, INDEPENDENTE da busca de
                    # `_pier_layout_avoiding_joints` (regra #1, absoluta - ver
                    # docstring): mesmo com a busca melhorada, um trecho pode
                    # nao ter NENHUMA composicao sem coincidencia (ex.:
                    # compensadores desligados, ou um caso realmente sem
                    # solucao dentro do catalogo) - nunca aceitar isso calado.
                    residual = _count_joint_coincidences_cm(
                        _layout_internal_joint_positions_cm(
                            layout, seg_start_cm,
                            leading_is_open=leading_is_open, trailing_is_open=trailing_is_open,
                        ),
                        course_a_joint_positions_cm,
                    )
                    if residual:
                        alignment_conflicts.append({
                            "wall_idx": wall_idx, "course": course, "variant_index": variant_index,
                            "segment_index": seg_i,
                            "seg_start_cm": seg_start_cm, "seg_end_cm": seg_end_cm,
                            "coincidence_count": residual,
                        })
                placed = _place_pier_layout(
                    layout, catalog, origin, wall_dir, course, wall_idx,
                    placement_reason="STANDARD_FILL",
                )
                for placed_cand in placed:
                    placed_cand["course_variant"] = variant_index
                candidates.extend(placed)

    return {
        "candidates": candidates, "jamb_exceptions": jamb_exceptions,
        "non_modular": non_modular, "alignment_conflicts": alignment_conflicts,
    }


# ==========================================
# ETAPA 4 (continuacao) - ORDEM DE PROCESSAMENTO E PIPELINE PAREDE A PAREDE
#
# Regras #3/#4/#5 do usuario (2026-08-21):
#   - o lancamento dos blocos e o ajuste da parede acontecem JUNTOS, na
#     mesma passada, e o lancamento PARTICIPA da decisao de ajuste (nao
#     existe mais "primeiro conserta tudo, depois lanca");
#   - uma parede por vez, do inicio ao fim, antes de comecar a proxima;
#   - a ordem e' decidida pela POSICAO GEOMETRICA, nunca pela ordem em que
#     as paredes foram encontradas no CAD: primeiro TODAS as horizontais
#     (de cima para baixo, e da esquerda para a direita dentro de cada
#     nivel), depois TODAS as verticais (da esquerda para a direita, e de
#     baixo para cima dentro de cada alinhamento).
# ==========================================

# Quanto do vetor unitario do eixo pode "vazar" para o outro eixo e a
# parede ainda contar como horizontal/vertical (~3 graus).
WALL_ORIENTATION_TOLERANCE = 0.05

# Duas horizontais cujos eixos estao a menos disto uma da outra contam como
# o MESMO nivel (e duas verticais, como o mesmo alinhamento) - e' o que faz
# "da esquerda para a direita dentro do nivel" significar alguma coisa
# quando os eixos nao coincidem no milimetro.
WALL_ALIGNMENT_TOLERANCE_FT = 0.10 * FEET_PER_METER

# Crescimento de parede acima disto (cm) e' crescimento DE VERDADE, nao
# ruido numerico - ver validate_wall_modulation/regra #1.
WALL_NO_GROWTH_TOLERANCE_CM = 0.1

# Quao longe do eixo de uma parede uma peca ja lancada ainda pode estar e
# colidir com o preenchimento dela: meia diagonal da maior peca do catalogo
# (54cm x 14cm) com folga - o suficiente para nao perder nenhuma colisao
# real, e apertado o bastante para o pre-filtro de `candidates_near_wall`
# reduzir a planta inteira a uma dezena de pecas por parede.
WALL_COLLISION_REACH_CM = 80.0


def classify_wall_orientation(walls_to_create, wall_idx):
    """"H" (horizontal, ao longo de X), "V" (vertical, ao longo de Y) ou
    "D" (diagonal - nem uma nem outra)."""
    _p0, _p1, wall_dir, _length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
    dx = abs(wall_dir.X)
    dy = abs(wall_dir.Y)
    if dy <= WALL_ORIENTATION_TOLERANCE and dx > WALL_ORIENTATION_TOLERANCE:
        return "H"
    if dx <= WALL_ORIENTATION_TOLERANCE and dy > WALL_ORIENTATION_TOLERANCE:
        return "V"
    return "D"


def _cluster_values_ft(values, tolerance_ft):
    """Lista de chaves de grupo (uma por valor, na ordem de entrada)
    agrupando valores que diferem menos que `tolerance_ft`, por varredura
    ORDENADA - determinista, e sem o efeito de borda que quantizar por
    arredondamento teria (dois valores a 1mm um do outro caindo em baldes
    diferentes so' porque a fronteira passa entre eles). As chaves crescem
    junto com o valor, entao ordenar pela chave equivale a ordenar pelo
    valor."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    keys = [0] * len(values)
    group = 0
    anchor_value = None
    for i in order:
        if anchor_value is None or (values[i] - anchor_value) > tolerance_ft:
            group += 1
            anchor_value = values[i]
        keys[i] = group
    return keys


def order_walls_for_processing(walls_to_create, tolerance_ft=WALL_ALIGNMENT_TOLERANCE_FT):
    """Ordem OBRIGATORIA de processamento (regra #5), decidida so' pela
    geometria:

        ETAPA 1 - HORIZONTAIS: de cima para baixo (Y decrescente) e, dentro
                  de cada nivel, da esquerda para a direita (X crescente).
        ETAPA 2 - VERTICAIS: da esquerda para a direita (X crescente) e,
                  dentro de cada alinhamento, de baixo para cima (Y
                  crescente).
        ETAPA 3 - o que nao for nem uma nem outra (paredes diagonais), em
                  cima->baixo / esquerda->direita, so' para a ordem ser
                  deterministica em vez de arbitraria.

    Devolve a lista de `wall_idx` na ordem em que devem ser processados."""
    info = []
    for wall_idx in range(len(walls_to_create)):
        p0, p1, _wall_dir, _length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
        info.append({
            "idx": wall_idx,
            "orientation": classify_wall_orientation(walls_to_create, wall_idx),
            "x_min": min(p0.X, p1.X), "x_max": max(p0.X, p1.X),
            "y_min": min(p0.Y, p1.Y), "y_max": max(p0.Y, p1.Y),
        })

    horizontals = [w for w in info if w["orientation"] == "H"]
    verticals = [w for w in info if w["orientation"] == "V"]
    diagonals = [w for w in info if w["orientation"] == "D"]

    ordered = []
    if horizontals:
        bands = _cluster_values_ft([w["y_min"] for w in horizontals], tolerance_ft)
        for pos, w in enumerate(horizontals):
            w["band"] = bands[pos]
        horizontals.sort(key=lambda w: (-w["band"], w["x_min"], w["idx"]))
        ordered.extend(w["idx"] for w in horizontals)
    if verticals:
        bands = _cluster_values_ft([w["x_min"] for w in verticals], tolerance_ft)
        for pos, w in enumerate(verticals):
            w["band"] = bands[pos]
        verticals.sort(key=lambda w: (w["band"], w["y_min"], w["idx"]))
        ordered.extend(w["idx"] for w in verticals)
    if diagonals:
        diagonals.sort(key=lambda w: (-w["y_max"], w["x_min"], w["idx"]))
        ordered.extend(w["idx"] for w in diagonals)
    return ordered


def openings_for_wall(openings_per_wall, wall_idx):
    """As aberturas de UMA parede. `openings_per_wall` e' uma LISTA no fluxo
    real (uma entrada por eixo, na ordem de walls_to_create) mas um DICT
    indexado por wall_idx em chamadas parciais/de teste - esta funcao le os
    dois sem quebrar, e devolve [] quando o eixo nao tem entrada."""
    try:
        value = openings_per_wall[wall_idx]
    except (KeyError, IndexError, TypeError):
        return []
    return value or []


def _copy_openings_per_wall(openings_per_wall):
    """Copia rasa-por-eixo de `openings_per_wall`, preservando se era lista
    ou dict - o pipeline trabalha sobre esta copia para nunca dessincronizar
    a estrutura do chamador (que espelha o modelo Revit) de um ajuste que
    ainda nao foi aplicado de verdade."""
    if isinstance(openings_per_wall, dict):
        return dict((key, list(value or [])) for key, value in openings_per_wall.items())
    return [list(value or []) for value in openings_per_wall]


def _wall_opening_intervals_cm(walls_to_create, openings_per_wall, wall_idx):
    """Intervalos (cm ao longo do eixo) ocupados pelos VAOS das aberturas
    desta parede - o interior deles nao pode receber bloco nenhum."""
    ft_to_cm = 100.0 / FEET_PER_METER
    openings_here = openings_for_wall(openings_per_wall, wall_idx)
    return [(op[0] * ft_to_cm, op[1] * ft_to_cm) for op in openings_here]


def _find_consecutive_compensators(wall_idx, walls_to_create, candidates, catalog,
                                   tolerance_cm=None):
    """REGRA GERAL (secao 2/8 do pedido do usuario, 2026-08-24): mesmo
    depois da fusao dentro de um UNICO trecho
    (`_merge_adjacent_compensator_pairs`, chamada por
    `_pier_ordered_layout`), dois compensadores ainda podem ficar
    fisicamente ADJACENTES quando vem de TRECHOS DIFERENTES da MESMA
    fiada - por exemplo o compensador do jamb de uma abertura encostado
    no compensador do preenchimento comum vizinho, ou dois trechos
    separados por um encontro que nao reservou nada ali. A fusao de
    `_pier_ordered_layout` NAO enxerga essa fronteira (ela so' ve' o
    trecho que esta' calculando). Esta funcao varre os candidatos JA'
    POSICIONADOS desta parede (todas as origens: encontros, jambs,
    preenchimento comum), por FIADA, ordenados ao longo do eixo, e
    devolve as sequencias de 2+ compensadores adjacentes encontradas -
    generalizado (nao condicionado a nenhuma parede/posicao especifica
    deste projeto), usado por `validate_wall_modulation` (regra #8)."""
    if tolerance_cm is None:
        tolerance_cm = BLOCK_JOINT_CM + PIER_LAYOUT_TOLERANCE_CM
    p0, _p1, wall_dir, _length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
    by_course = {}
    for c in candidates:
        entry = catalog.get(c.get("logical_code")) if catalog else None
        if not entry or not entry.get("is_compensator"):
            continue
        t_lo_cm, t_hi_cm = _candidate_t_range_on_wall(c, p0, wall_dir)
        by_course.setdefault(c.get("course"), []).append((t_lo_cm, t_hi_cm, c.get("logical_code")))
    runs = []
    for course, items in by_course.items():
        items.sort(key=lambda it: it[0])
        i = 0
        while i < len(items) - 1:
            run = [items[i]]
            j = i
            while j + 1 < len(items) and (items[j + 1][0] - items[j][1]) <= tolerance_cm:
                run.append(items[j + 1])
                j += 1
            if len(run) >= 2:
                runs.append({"course": course, "codes": [r[2] for r in run],
                            "start_cm": run[0][0], "end_cm": run[-1][1]})
            i = j + 1
    return runs


def validate_wall_modulation(wall_idx, walls_to_create, openings_per_wall, fill_result,
                             plan=None, original_length_cm=None,
                             tolerance_cm=WALL_NO_GROWTH_TOLERANCE_CM,
                             placed_candidates=None, catalog=None):
    """VALIDACAO FINAL DE UMA PAREDE (regra #8) - roda antes de o pipeline
    passar para a proxima. Nao altera nada; so' confere.

    Cada item da lista de conferencia pedida pelo usuario vira uma chave de
    "checks" (True = passou):

        modulacao_fecha       - nenhum trecho ficou NON_MODULAR
        sem_alinhamento_vertical - nenhuma junta da Fiada B coincide com uma
                                junta da Fiada A no mesmo trecho (regra #1,
                                ABSOLUTA - pedido explicito do usuario,
                                2026-08-25: "tem prioridade sobre qualquer
                                tentativa de simplesmente preencher o
                                comprimento da parede", "nao pode ser
                                flexibilizada"). Ver alignment_conflicts em
                                solve_wall_free_fill.
        blocos_posicionados   - a parede recebeu bloco (ou esta' inteira
                                reservada pelos encontros/aberturas)
        juntas_ok             - nenhuma excecao de alinhamento de celula no
                                jamb de abertura (ADVISORY - ver abaixo)
        sem_aumento           - o comprimento final NAO passou do original
        sem_dentes            - nenhum bloco/limite fora do intervalo do
                                eixo (prolongamento artificial na ponta)
        aberturas_respeitadas - nenhum bloco invade o vao de uma abertura
        encontros_respeitados - nenhum bloco desta parede colide com outro
                                da MESMA fiada - nem entre si, nem contra
                                `placed_candidates` (tudo que ja' foi
                                lancado: pecas de encontro L/T/X e as
                                paredes ja' processadas). E' o que faz a
                                colisao ser detectada NA HORA, na parede
                                que a causou, em vez de so' no fim como um
                                numero global que ninguem consegue resolver
        geometria_coerente    - o eixo continua com comprimento positivo
        sem_compensadores_consecutivos - nenhuma sequencia de 2+
                                compensadores/pastilhas fisicamente
                                adjacentes na MESMA fiada (regra #2/#8 do
                                pedido do usuario, 2026-08-24) - cobre
                                mesmo os casos que `_pier_ordered_layout`
                                nao enxerga por vir de TRECHOS diferentes
                                (jamb + preenchimento comum vizinhos, por
                                exemplo). Requer `catalog` (opcional); sem
                                ele o check nao pode ser calculado e volta
                                True (nao bloqueia chamadores antigos/
                                testes que nao passam catalog).

    "ok" reune so' os checks BLOQUEANTES. `juntas_ok` fica de fora dele
    (vai para "warnings"): uma OPENING_CELL_ALIGNMENT_EXCEPTION e' um desvio
    de alinhamento de celula do bloco de jamb, herdado da geometria da
    abertura - o bloco e' colocado do mesmo jeito, e o desvio nao e' causado
    (nem curado) por um ajuste de modulacao. Trata-lo como bloqueante faria
    o pipeline RECUSAR ajustes que resolvem de fato a modulacao, so' porque
    uma imperfeicao pre-existente continua la'. Continua reportado, nunca
    escondido.

    Devolve {"wall_idx":, "ok": bool, "checks": {...}, "problems": [str],
    "warnings": [str]}."""
    checks = {}
    problems = []
    warnings = []
    ft_to_cm = 100.0 / FEET_PER_METER
    p0, _p1, wall_dir, length_ft, _thickness = _wall_axis_and_length(walls_to_create, wall_idx)
    length_cm = length_ft * ft_to_cm
    candidates = [c for c in fill_result.get("candidates", []) if c.get("wall_idx") == wall_idx]

    checks["geometria_coerente"] = length_cm > tolerance_cm
    if not checks["geometria_coerente"]:
        problems.append("eixo com comprimento praticamente zero")

    non_modular = fill_result.get("non_modular") or []
    checks["modulacao_fecha"] = not non_modular
    if non_modular:
        problems.append(
            "modulacao nao fecha em {} trecho(s) (o primeiro tem {:.1f}cm)"
            .format(len(non_modular), float(non_modular[0]["current_length_cm"]))
        )

    # --- regra #1 (ABSOLUTA): sem junta vertical corrida entre fiadas -----
    alignment_conflicts = [
        a for a in (fill_result.get("alignment_conflicts") or [])
        if a.get("wall_idx") == wall_idx
    ]
    checks["sem_alinhamento_vertical"] = not alignment_conflicts
    if alignment_conflicts:
        problems.append(
            "{} trecho(s) com junta vertical coincidindo entre Fiada A e "
            "Fiada B (proibido - regra #1, absoluta)".format(len(alignment_conflicts))
        )

    jamb_exceptions = fill_result.get("jamb_exceptions") or []
    checks["juntas_ok"] = not jamb_exceptions
    if jamb_exceptions:
        warnings.append(
            "{} excecao(oes) de alinhamento de celula no jamb de abertura "
            "(revisar, nao bloqueia)".format(len(jamb_exceptions))
        )

    checks["blocos_posicionados"] = bool(candidates) or not non_modular
    if not checks["blocos_posicionados"]:
        problems.append("nenhum bloco foi posicionado nesta parede")

    # --- regra #1: NUNCA aumentar a parede, NUNCA criar "dente" ----------
    if original_length_cm is None:
        original_length_cm = length_cm
    grew_cm = length_cm - original_length_cm
    checks["sem_aumento"] = grew_cm <= tolerance_cm
    if not checks["sem_aumento"]:
        problems.append("a parede AUMENTOU {:.1f}cm (proibido - regra #1)".format(grew_cm))

    over_cm = 0.0
    for candidate in candidates:
        # _candidate_t_range_on_wall JA DEVOLVE CENTIMETROS (converte
        # internamente) - nao reconverter.
        t_lo_cm, t_hi_cm = _candidate_t_range_on_wall(candidate, p0, wall_dir)
        if t_lo_cm < -tolerance_cm:
            over_cm = max(over_cm, -t_lo_cm)
        if t_hi_cm > length_cm + tolerance_cm:
            over_cm = max(over_cm, t_hi_cm - length_cm)
    if plan is not None and plan.get("feasible"):
        # ATENCAO: `axis_start_t_ft`/`axis_end_t_ft` sao offsets no eixo
        # ORIGINAL (e' assim que apply_axis_opening_fix os usa), entao a
        # comparacao tem que ser contra `original_length_cm` - nunca contra
        # `length_cm`, que aqui ja' pode ser o eixo ENCURTADO pelo proprio
        # plano. Comparar com o encurtado acusaria "dente" justamente nos
        # planos que fazem o oposto (encolher a parede).
        start_t_ft = plan.get("axis_start_t_ft") or 0.0
        end_t_ft = plan.get("axis_end_t_ft")
        if start_t_ft < 0:
            over_cm = max(over_cm, -start_t_ft * ft_to_cm)
        if end_t_ft is not None and (end_t_ft * ft_to_cm) > original_length_cm + tolerance_cm:
            over_cm = max(over_cm, end_t_ft * ft_to_cm - original_length_cm)
    checks["sem_dentes"] = over_cm <= tolerance_cm
    if not checks["sem_dentes"]:
        problems.append(
            "prolongamento/\"dente\" de {:.1f}cm para fora do eixo (proibido - regra #2)"
            .format(over_cm)
        )

    # --- aberturas: nenhum bloco pode entrar no vao ----------------------
    gaps_cm = _wall_opening_intervals_cm(walls_to_create, openings_per_wall, wall_idx)
    invaded = 0
    for candidate in candidates:
        t_lo_cm, t_hi_cm = _candidate_t_range_on_wall(candidate, p0, wall_dir)
        for gap_lo_cm, gap_hi_cm in gaps_cm:
            if (t_hi_cm - tolerance_cm) > gap_lo_cm and (t_lo_cm + tolerance_cm) < gap_hi_cm:
                invaded += 1
                break
    checks["aberturas_respeitadas"] = invaded == 0
    if invaded:
        problems.append("{} bloco(s) invadindo o vao de uma abertura".format(invaded))

    # --- encontros: nenhuma colisao na MESMA fiada -----------------------
    collisions = validate_same_course_collision(candidates)
    external = []
    if placed_candidates:
        external = collisions_between(candidates, placed_candidates)
    checks["encontros_respeitados"] = not collisions and not external
    if collisions:
        problems.append("{} colisao(oes) entre pecas desta parede".format(len(collisions)))
    if external:
        problems.append(
            "{} colisao(oes) com pecas ja lancadas (encontro L/T/X ou parede vizinha)"
            .format(len(external))
        )

    # --- regra #2/#8: sem sequencia de 2+ compensadores adjacentes -------
    if catalog is not None:
        comp_runs = _find_consecutive_compensators(wall_idx, walls_to_create, candidates, catalog)
        checks["sem_compensadores_consecutivos"] = not comp_runs
        if comp_runs:
            problems.append(
                "{} sequencia(s) de compensadores adjacentes (proibido - regra #2): {}".format(
                    len(comp_runs),
                    "; ".join(
                        "fiada {} [{}] {:.1f}-{:.1f}cm".format(
                            r["course"], "+".join(r["codes"]), r["start_cm"], r["end_cm"]
                        ) for r in comp_runs[:5]
                    )
                )
            )
    else:
        checks["sem_compensadores_consecutivos"] = True

    return {"wall_idx": wall_idx, "ok": not problems, "checks": checks,
            "problems": problems, "warnings": warnings}


def _apply_axis_plan_in_memory(working_walls, working_openings, plan):
    """Aplica SO' EM MEMORIA (nunca no modelo Revit) o efeito geometrico de
    um plano de `plan_axis_opening_fix`, para que o solver de blocos possa
    rodar DE NOVO sobre a parede ja' ajustada - e' isso que faz o
    lancamento dos blocos participar da decisao de ajuste (regra #3) em vez
    de so' ser executado depois.

    Devolve o deslocamento (em cm) que a origem do eixo sofreu, para quem
    precisar rebasear coordenadas ja' calculadas contra o eixo antigo."""
    wall_idx = plan["wall_idx"]
    centerline, thickness_ft, locks = working_walls[wall_idx]
    start_t_ft = plan.get("axis_start_t_ft") or 0.0
    end_t_ft = plan.get("axis_end_t_ft")
    if end_t_ft is None:
        end_t_ft = centerline.Length

    if abs(start_t_ft) > 1e-9 or abs(end_t_ft - centerline.Length) > 1e-9:
        p0 = centerline.GetEndPoint(0)
        direction = centerline.Direction
        new_p0 = XYZ(p0.X + direction.X * start_t_ft,
                     p0.Y + direction.Y * start_t_ft,
                     p0.Z + direction.Z * start_t_ft)
        new_p1 = XYZ(p0.X + direction.X * end_t_ft,
                     p0.Y + direction.Y * end_t_ft,
                     p0.Z + direction.Z * end_t_ft)
        working_walls[wall_idx] = (Line.CreateBound(new_p0, new_p1), thickness_ft, locks)

    openings_here = list(openings_for_wall(working_openings, wall_idx))
    for row in plan.get("new_openings") or []:
        index = row["opening_index"]
        if index < len(openings_here):
            openings_here[index] = (row["t_lo_new"] - start_t_ft, row["t_hi_new"] - start_t_ft,
                                     row["sill_z_abs"], row["head_z_abs"])
    working_openings[wall_idx] = openings_here
    return start_t_ft * (100.0 / FEET_PER_METER)


def _rebase_node_indexes_for_wall(node_candidates_by_wall_end, node_midspan_by_wall_course,
                                  wall_idx, origin_shift_cm):
    """Copias dos dois indices de encontro com as coordenadas de `wall_idx`
    rebaseadas depois de a origem do eixo ter andado `origin_shift_cm` (so'
    acontece quando um ajuste ENCURTA a parede pela ponta 0). Os demais
    eixos ficam intocados - por isso e' uma copia rasa dos dicts."""
    if abs(origin_shift_cm) < 1e-9:
        return node_candidates_by_wall_end, node_midspan_by_wall_course
    by_end = dict(node_candidates_by_wall_end)
    midspan = dict(node_midspan_by_wall_course)
    for key in list(by_end.keys()):
        if key[0] == wall_idx and by_end[key] is not None:
            by_end[key] = by_end[key] - origin_shift_cm
    for key in list(midspan.keys()):
        if key[0] == wall_idx:
            midspan[key] = [(lo - origin_shift_cm, hi - origin_shift_cm) for lo, hi in midspan[key]]
    return by_end, midspan


def process_walls_one_by_one(walls_to_create, nodes, end_to_node, openings_per_wall,
                             catalog, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                             plan_hook=None,
                             intersections=None, progress_cb=None,
                             variants_per_course=1,
                             wall_start_cb=None, wall_result_cb=None,
                             dirty_wall_idxs=None, baseline_per_wall=None,
                             baseline_candidates=None, stage_cb=None):
    """PIPELINE PRINCIPAL (regras #3, #4, #5, #8, #9): processa UMA parede
    de cada vez, na ordem geometrica de `order_walls_for_processing`, e
    para cada uma faz o ciclo completo antes de tocar na proxima:

        1-5. analisa encontros/aberturas/extremidades e escolhe a melhor
             combinacao de blocos  -> solve_wall_free_fill
        6.   "lanca" os blocos (calcula as pecas de verdade, com posicao)
        7.   verifica se a modulacao fechou
        8.   se nao fechou, pede um ajuste ao `plan_hook` - que NUNCA pode
             aumentar a parede nem criar dente (ver plan_axis_opening_fix)
        9.   aplica o ajuste EM MEMORIA e RECALCULA os blocos
        10.  valida a parede (validate_wall_modulation)
        11.  so' entao passa para a proxima

    O ajuste so' e' aceito se o RE-LANCAMENTO dos blocos melhorar de fato o
    resultado - e' o lancamento que decide, nao a aritmetica sozinha (regra
    #3/#9). Nada aqui escreve no modelo Revit: `walls_to_create` e
    `openings_per_wall` sao copiados antes de qualquer alteracao, e os
    planos aceitos saem em "plans" para o chamador aplicar de verdade
    depois, dentro de uma Transacao.

    `plan_hook(wall_idx, fill_result, verify)` -> plano ou None. `verify` e'
    uma funcao que o hook pode chamar com um plano candidato para saber se
    ele realmente fecha a modulacao desta parede (e' o solver de blocos de
    verdade rodando sobre a parede ja' ajustada em memoria).

    Devolve:
        {"order": [...], "candidates": [...], "intersection_failures": [...],
         "jamb_exceptions": [...], "non_modular": [...], "collisions": [...],
         "per_wall": [...], "plans": {wall_idx: plano}, "validations": [...],
         "walls_after": [...], "openings_after": [...]}

    `progress_cb(done, total)`, se fornecido, e' chamado periodicamente
    (nao a cada parede - a cada ~10% do total) conforme o laco avanca - so'
    para dar VISIBILIDADE num pipeline que, sem isso, nao imprime nada ate'
    processar TODAS as paredes (ver PERFORMANCE em main()). Omitido (None)
    nas re-solucoes de tentativa de find_wall_group_shift_fixes de
    proposito - ali quem reporta progresso e' a PROPRIA
    find_wall_group_shift_fixes, uma linha por tentativa, nao esta funcao
    imprimindo o avanco parede-a-parede de cada uma das ate'
    WALL_GROUP_SHIFT_VERIFY_BUDGET tentativas.

    `wall_start_cb(wall_idx, total, pos)`/`wall_result_cb(wall_idx, total, ok,
    detail)`, se fornecidos, sao chamados a CADA parede (nao a cada ~10% como
    `progress_cb`) - `wall_start_cb` antes de resolver a parede, `wall_result_cb`
    logo depois de validar (ok=True/False, detail=motivo quando ok=False).
    Existem para dar feedback AO VIVO, parede a parede, do que o solver de
    blocos de verdade esta fazendo (qual parede, se fechou ou nao) em vez de
    so' um contador agregado - pedido explicito do usuario (2026-08-26) para
    acabar com o "carregamento infinito sem feedback" durante o lancamento de
    blocos (Etapa 4, o solver mais pesado do pipeline).

    `dirty_wall_idxs`/`baseline_per_wall`/`baseline_candidates` (RESOLVE
    PARCIAL, FASE 3 do plano em
    C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md - so' usado
    pelas re-solucoes de tentativa de find_wall_group_shift_fixes, NUNCA
    pela resolucao principal de analyze_created_walls_for_errors): quando
    os tres sao fornecidos, so' as paredes em `dirty_wall_idxs` sao
    resolvidas de verdade (solve_wall_free_fill + plan_hook + validacao) -
    as demais REUSAM o resultado ja' validado de `baseline_per_wall[wall_idx]`
    (dict {wall_idx: entry de per_wall} de uma resolucao anterior sobre a
    MESMA topologia/grafo) sem gastar tempo nenhum nelas. `baseline_candidates`
    (a lista `run["candidates"]` dessa mesma resolucao anterior) e'
    necessaria para que as paredes REUSADAS continuem contribuindo com suas
    pecas REAIS para `candidates_near_wall` das paredes dirty vizinhas -
    sem isso, uma parede dirty perto de uma parede limpa reusada perderia o
    contexto de colisao/encontro contra pecas que na verdade EXISTEM.

    SEGURANCA: `dirty_wall_idxs` PRECISA conter toda parede cuja
    geometria/abertura realmente mudou MAIS toda parede que compartilha um
    NO' com alguma delas (ver _expand_dirty_wall_idxs/_wall_node_neighbors)
    - a mesma regra de alcance de 1 salto ja' confirmada com o usuario para
    _candidate_walls_to_shift_for (2026-08-25), aqui aplicada a "quem
    precisa ser REVALIDADO" em vez de "quem pode ser deslocado". Uma parede
    de FORA desse fecho, por definicao, nao teve nenhum vizinho de encontro
    tocado - sua modulacao so' depende da propria geometria (inalterada) e
    do que esta' encostado nela (tambem inalterado), entao o resultado
    baseline continua exato. Devolve o `per_wall`/`validations`/`plans`
    resultantes ja' MISTURANDO dirty (recalculado) e limpo (reusado) na
    MESMA ordem de `order`, para que `_wall_ok_map` (o UNICO consumidor
    deste modo) enxergue a planta inteira normalmente.
    """
    if intersections is None:
        intersections = solve_all_intersections(nodes, walls_to_create, catalog,
                                                 openings_per_wall=openings_per_wall,
                                                 end_to_node=end_to_node)

    working_walls = list(walls_to_create)
    working_openings = _copy_openings_per_wall(openings_per_wall)
    original_lengths_cm = [
        _wall_axis_and_length(walls_to_create, i)[3] * (100.0 / FEET_PER_METER)
        for i in range(len(walls_to_create))
    ]

    by_end = _index_node_candidates_by_wall_end(
        nodes, intersections["candidates"], walls_to_create, end_to_node
    )
    midspan = _index_node_candidates_midspan(
        nodes, intersections["candidates"], walls_to_create, end_to_node
    )

    order = order_walls_for_processing(walls_to_create)
    all_candidates = list(intersections["candidates"])
    # Espelho espacial de `all_candidates` - alimentado nos MESMOS pontos em
    # que a lista cresce (ver _placed_index_near_wall).
    placed_index = _placed_index_add(_placed_index_new(), all_candidates)
    jamb_exceptions = []
    non_modular = []
    alignment_conflicts = []
    per_wall = []
    validations = []
    plans = {}

    partial_resolve = dirty_wall_idxs is not None and baseline_per_wall is not None
    if partial_resolve and baseline_candidates is not None:
        # Semeia com as pecas REAIS das paredes REUSADAS (ver docstring) -
        # sem isso, `candidates_near_wall` (mais abaixo) enxergaria uma
        # parede limpa vizinha como se nao tivesse nenhum bloco lancado
        # ainda, perdendo o contexto de colisao/encontro contra pecas que
        # de fato existem no baseline.
        seeded = [c for c in baseline_candidates if c.get("wall_idx") not in dirty_wall_idxs]
        all_candidates.extend(seeded)
        _placed_index_add(placed_index, seeded)

    reach_ft = WALL_COLLISION_REACH_CM / (100.0 / FEET_PER_METER)

    total_walls = len(order)
    # Reporta a cada ~10% do total (minimo 1, para nao dividir por zero nem
    # spammar uma linha por parede em plantas grandes) - ver docstring.
    progress_stride = max(1, total_walls // 10)

    for _pos, wall_idx in enumerate(order):
        if progress_cb is not None and (_pos % progress_stride == 0 or _pos == total_walls - 1):
            progress_cb(_pos + 1, total_walls)
        if wall_start_cb is not None:
            try:
                wall_start_cb(wall_idx, total_walls, _pos + 1)
            except Exception:
                pass

        if partial_resolve and wall_idx not in dirty_wall_idxs and wall_idx in baseline_per_wall:
            # RESOLVE PARCIAL (ver docstring "dirty_wall_idxs") - esta
            # parede nao mudou nem tem vizinho de encontro que mudou nesta
            # tentativa, entao o resultado anterior continua exato. Pula
            # solve_wall_free_fill/plan_hook/validate_wall_modulation
            # inteiros (o trecho caro desta funcao) e so' REPETE o mesmo
            # registro no formato esperado - suas pecas ja' foram semeadas
            # em all_candidates antes do laco comecar.
            entry = baseline_per_wall[wall_idx]
            non_modular.extend(entry["non_modular"])
            alignment_conflicts.extend(entry.get("alignment_conflicts") or [])
            validations.append(entry["validation"])
            per_wall.append(entry)
            if entry.get("plan") is not None:
                plans[wall_idx] = entry["plan"]
            if wall_result_cb is not None:
                try:
                    validation = entry["validation"]
                    wall_result_cb(
                        wall_idx, total_walls, bool(validation and validation.get("ok")), None
                    )
                except Exception:
                    pass
            continue

        wall_by_end, wall_midspan = by_end, midspan
        # Tudo que ja' foi lancado e pode encostar NESTA parede: as pecas de
        # encontro L/T/X e as paredes ja' processadas. Filtrado uma unica
        # vez por parede (nao a cada tentativa de ajuste) - ver
        # candidates_near_wall.
        wall_p0, _wall_p1, wall_dir, wall_len_ft, _th = _wall_axis_and_length(
            working_walls, wall_idx
        )
        neighbours = _placed_index_near_wall(
            placed_index, wall_p0, wall_dir, wall_len_ft, reach_ft,
            exclude_wall_idx=wall_idx,
        )

        def _solve(walls_arg, openings_arg, by_end_arg, midspan_arg):
            return solve_wall_free_fill(
                wall_idx, walls_arg, nodes, end_to_node, openings_arg,
                by_end_arg, midspan_arg, catalog, allow_compensators,
                variants_per_course=variants_per_course,
            )

        result = _solve(working_walls, working_openings, wall_by_end, wall_midspan)
        first_validation = validate_wall_modulation(
            wall_idx, working_walls, working_openings, result, None,
            original_length_cm=original_lengths_cm[wall_idx],
            placed_candidates=neighbours, catalog=catalog,
        )
        plan = None
        plan_rejected = None
        adjusted = False

        # COLISAO TAMBEM DISPARA O AJUSTE (nao so' "a modulacao nao fecha"):
        # uma peca desta parede batendo num bloco de encontro/parede vizinha
        # e' um conflito que o usuario nao tem como resolver sozinho na tela
        # de resultado - e' justamente o tipo de coisa que se resolve
        # afastando a abertura, que e' o que o plan_hook tenta. JUNTA
        # VERTICAL CORRIDA tambem dispara o ajuste (regra #1, ABSOLUTA,
        # pedido explicito do usuario 2026-08-25: "tem prioridade sobre
        # qualquer tentativa de simplesmente preencher o comprimento da
        # parede") - um deslocamento de poucos cm na abertura muda a
        # aritmetica do trecho o suficiente para desbloquear uma
        # composicao sem coincidencia (ver _pier_forced_bypass_layouts).
        needs_fix = (
            bool(result["non_modular"])
            or bool(result.get("alignment_conflicts"))
            or not first_validation["checks"]["encontros_respeitados"]
        )
        if needs_fix and plan_hook is not None:
            # `verify` roda o SOLVER DE VERDADE sobre uma copia da parede ja
            # ajustada - e' o passo que faz "lancar blocos" participar da
            # decisao de ajuste em vez de vir depois dela.
            trial_state = {}

            def verify(candidate_plan):
                # Zera o estado a cada chamada: assim `trial_state` sempre
                # corresponde a ULTIMA verificacao, e nunca sobra o
                # resultado de um candidato anterior para ser aplicado no
                # lugar do candidato que o hook realmente escolheu.
                trial_state.clear()
                if not candidate_plan or not candidate_plan.get("feasible"):
                    return False
                trial_walls = list(working_walls)
                trial_openings = _copy_openings_per_wall(working_openings)
                shift_cm = _apply_axis_plan_in_memory(trial_walls, trial_openings, candidate_plan)
                trial_by_end, trial_midspan = _rebase_node_indexes_for_wall(
                    wall_by_end, wall_midspan, wall_idx, shift_cm
                )
                trial_result = _solve(trial_walls, trial_openings, trial_by_end, trial_midspan)
                trial_validation = validate_wall_modulation(
                    wall_idx, trial_walls, trial_openings, trial_result, candidate_plan,
                    original_length_cm=original_lengths_cm[wall_idx],
                    placed_candidates=neighbours, catalog=catalog,
                )
                if trial_result["non_modular"] or not trial_validation["ok"]:
                    return False
                trial_state["walls"] = trial_walls
                trial_state["openings"] = trial_openings
                trial_state["by_end"] = trial_by_end
                trial_state["midspan"] = trial_midspan
                trial_state["result"] = trial_result
                trial_state["validation"] = trial_validation
                return True

            try:
                plan = plan_hook(wall_idx, result, verify)
            except Exception:
                plan = None

            if plan is not None and plan.get("feasible") and not plan.get("already_ok"):
                if "result" not in trial_state:
                    verify(plan)   # hook que nao chamou verify: conferir aqui
                if "result" in trial_state:
                    working_walls = trial_state["walls"]
                    working_openings = trial_state["openings"]
                    wall_by_end = trial_state["by_end"]
                    wall_midspan = trial_state["midspan"]
                    by_end, midspan = wall_by_end, wall_midspan
                    result = trial_state["result"]
                    adjusted = True
                    plans[wall_idx] = plan
                else:
                    plan_rejected = plan
                    plan = None   # o ajuste nao fechou de verdade: descartado

        if adjusted:
            validation = validate_wall_modulation(
                wall_idx, working_walls, working_openings, result, plan,
                original_length_cm=original_lengths_cm[wall_idx],
                placed_candidates=neighbours, catalog=catalog,
            )
        else:
            validation = first_validation

        all_candidates.extend(result["candidates"])
        _placed_index_add(placed_index, result["candidates"])
        jamb_exceptions.extend(result["jamb_exceptions"])
        non_modular.extend(result["non_modular"])
        alignment_conflicts.extend(result.get("alignment_conflicts") or [])
        validations.append(validation)
        per_wall.append({
            "wall_idx": wall_idx,
            "orientation": classify_wall_orientation(walls_to_create, wall_idx),
            "adjusted": adjusted,
            "plan": plan,
            "plan_rejected": plan_rejected,
            "validation": validation,
            "candidate_count": len(result["candidates"]),
            "non_modular": result["non_modular"],
            "alignment_conflicts": result.get("alignment_conflicts") or [],
        })
        if wall_result_cb is not None:
            try:
                ok = bool(validation and validation.get("ok"))
                detail = None
                if not ok:
                    if result["non_modular"]:
                        detail = "{} trecho(s) nao modular(es)".format(len(result["non_modular"]))
                    elif result.get("alignment_conflicts"):
                        detail = "{} conflito(s) de alinhamento".format(len(result["alignment_conflicts"]))
                    elif plan_rejected is not None:
                        detail = "ajuste tentado nao fechou a modulacao"
                    else:
                        detail = "modulacao nao fechou"
                wall_result_cb(wall_idx, total_walls, ok, detail)
            except Exception:
                pass

    # ETAPA FINAL - roda DEPOIS da ultima parede, entao nenhum dos callbacks
    # por parede (wall_start_cb/wall_result_cb/progress_cb) dispara mais aqui.
    # Ate' 2026-08-27 esse trecho era o mais lento do solver inteiro E o unico
    # sem nenhum feedback na tela - a combinacao que fazia a janela parecer
    # travada em 99%. O custo ja foi resolvido (indices espaciais); `stage_cb`
    # resolve o silencio, para que uma futura regressao de desempenho aqui
    # apareca como "parado em X" em vez de "travado".
    if stage_cb is not None:
        try:
            stage_cb("verificando colisoes entre todas as pecas")
        except Exception:
            pass
    collisions = validate_same_course_collision(all_candidates)

    return {
        "order": order,
        "candidates": all_candidates,
        "intersection_failures": intersections["failures"],
        "jamb_exceptions": jamb_exceptions,
        "non_modular": non_modular,
        "alignment_conflicts": alignment_conflicts,
        "collisions": collisions,
        "per_wall": per_wall,
        "validations": validations,
        "plans": plans,
        "walls_after": working_walls,
        "openings_after": working_openings,
    }


def solve_all_wall_fill(walls_to_create, nodes, end_to_node, openings_per_wall,
                        intersection_candidates, catalog, allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT):
    """Roda solve_wall_free_fill em TODAS as paredes de `walls_to_create` -
    o passo 'trechos livres' da ordem X->T->L->jambs->trechos da Etapa 4
    (jambs e trechos ficam juntos aqui porque um preenche exatamente o que
    o outro deixa faltando dentro do MESMO pilarete - ver docstring de
    solve_wall_free_fill).

    Devolve {"candidates": [...], "jamb_exceptions": [...],
    "non_modular": [...], "alignment_conflicts": [...]}."""
    node_candidates_by_wall_end = _index_node_candidates_by_wall_end(
        nodes, intersection_candidates, walls_to_create, end_to_node
    )
    node_midspan_by_wall_course = _index_node_candidates_midspan(
        nodes, intersection_candidates, walls_to_create, end_to_node
    )
    candidates = []
    jamb_exceptions = []
    non_modular = []
    alignment_conflicts = []
    # UMA PAREDE POR VEZ, na ordem geometrica obrigatoria (regras #4/#5) -
    # nunca mais `range(len(walls_to_create))`, que seguia a ordem em que as
    # paredes sairam do CAD.
    for wall_idx in order_walls_for_processing(walls_to_create):
        result = solve_wall_free_fill(
            wall_idx, walls_to_create, nodes, end_to_node, openings_per_wall,
            node_candidates_by_wall_end, node_midspan_by_wall_course, catalog, allow_compensators,
        )
        candidates.extend(result["candidates"])
        jamb_exceptions.extend(result["jamb_exceptions"])
        non_modular.extend(result["non_modular"])
        alignment_conflicts.extend(result.get("alignment_conflicts") or [])
    return {
        "candidates": candidates, "jamb_exceptions": jamb_exceptions,
        "non_modular": non_modular, "alignment_conflicts": alignment_conflicts,
    }


def solve_building_blocks(nodes, walls_to_create, end_to_node, openings_per_wall, catalog,
                          allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                          base_z_abs=None, variants_per_course=1,
                          progress_cb=None, wall_start_cb=None, wall_result_cb=None,
                          stage_cb=None):
    """Ponto de entrada UNICO da Etapa 4 completa (X -> T -> L -> jambs ->
    trechos livres): roda solve_all_intersections (X/T/L) e depois entrega
    tudo a `process_walls_one_by_one`, que percorre as paredes UMA A UMA na
    ordem geometrica obrigatoria (horizontais de cima para baixo e da
    esquerda para a direita; depois verticais da esquerda para a direita e
    de baixo para cima) e valida cada uma antes de passar para a proxima.

    `base_z_abs` (opcional): quando dado, roda tambem `find_door_void_violations`
    (rede de seguranca da regra "nenhum bloco dentro do vao de porta sem
    peitoril", pedido explicito do usuario 2026-08-21) e devolve o
    resultado em `"door_void_violations"`. `None` (default, retrocompativel
    com todo chamador existente) pula essa checagem - `"door_void_violations"`
    sai como `[]`, nunca ausente.

    Aqui NAO se ajusta nada (plan_hook=None) - este e' o caminho de
    "lancar blocos" puro. O caminho integrado, em que o lancamento
    participa da decisao de ajuste da parede, e'
    analyze_created_walls_for_errors, que chama o MESMO pipeline com um
    plan_hook - por isso os dois nunca divergem sobre o que fecha e o que
    nao fecha.

    Devolve {"candidates": [...], "intersection_failures": [...],
    "jamb_exceptions": [...], "non_modular": [...], "collisions": [...],
    "per_wall": [...], "validations": [...], "order": [...]}."""
    result = process_walls_one_by_one(
        walls_to_create, nodes, end_to_node, openings_per_wall, catalog,
        allow_compensators=allow_compensators, plan_hook=None,
        variants_per_course=variants_per_course,
        progress_cb=progress_cb, wall_start_cb=wall_start_cb, wall_result_cb=wall_result_cb,
        stage_cb=stage_cb,
    )
    if base_z_abs is not None:
        if stage_cb is not None:
            try:
                stage_cb("conferindo vaos de porta sem peitoril")
            except Exception:
                pass
        result["door_void_violations"] = find_door_void_violations(
            result["candidates"], walls_to_create, openings_per_wall, base_z_abs
        )
    else:
        result["door_void_violations"] = []
    return result


# ==========================================
# ETAPA 3C - DESLOCAMENTO DE GRUPO DE PAREDES CONECTADAS (2026-08-24).
#
# NOVA EXCECAO, deliberada e escopada, a regra #1 - NAO e' a reintroducao do
# mecanismo removido em 2026-08-21 (ver comentario "REMOVIDA COMPLETAMENTE"
# no cabecalho da ETAPA 3B, poucas centenas de linhas acima: find_wall_loops/
# suggest_room_enlargement/apply_room_axis_enlargement/_classify_rectangle/
# _walls_share_endpoint/_wall_endpoint_index_touching/
# _rebuild_curve_with_endpoint). Aquele mecanismo ESTICAVA o EIXO DE UMA
# PAREDE PARA AUMENTAR ELA MESMA - proibido, continua proibido, nao mexemos
# nisso (plan_axis_opening_fix/apply_axis_opening_fix acima permanecem
# inalterados nessa regra).
#
# Esta ETAPA e' outra coisa: desloca uma parede W PERPENDICULARMENTE ao
# PROPRIO eixo dela (ex.: parede horizontal sobe/desce alguns cm) - o
# comprimento de W NUNCA muda (e' uma translacao rigida). O efeito
# colateral AUTORIZADO pelo usuario (2026-08-24, apos confirmar
# explicitamente que isto e' uma excecao nova a regra #1, so' para este
# tipo de ajuste) e' que isso desloca o CANTO real (L_CORNER) nas pontas de
# W, o que muda o COMPRIMENTO das paredes PERPENDICULARES que terminam
# contra W naquele canto - exatamente o tipo de ajuste que fecha uma
# modulacao que nem boneca (OPCAO 0 de plan_axis_opening_fix) nem
# shift/trim de abertura (OPCOES 1/2) resolvem, porque a parede em questao
# nao tem NENHUMA abertura por perto (ver o "sem abertura por perto -
# nenhuma correcao automatica disponivel" que plan_hook, mais abaixo,
# devolve de cara para esses casos).
#
# Regras de escopo confirmadas com o usuario:
#   - so' translacao perpendicular da parede INTEIRA, nunca esticamento ao
#     longo do proprio eixo dela;
#   - so' vizinhos DIRETOS (as paredes que encostam nas DUAS pontas da
#     parede deslocada) - sem propagacao em cadeia;
#   - area do comodo PODE mudar - nao ha' compensacao automatica deslocando
#     a parede oposta;
#   - so' roda DEPOIS que plan_axis_opening_fix (ajuste de abertura) ja'
#     esgotou as proprias opcoes para a parede que esta' falhando.
#
# Arquitetura: process_walls_one_by_one (ETAPA 4, bem acima) e' tratado
# como CAIXA-PRETA de verificacao - a mesma disciplina "propoe barato,
# verifica caro" do resto do arquivo, so' que na granularidade da PLANTA
# INTEIRA em vez de UM eixo (o `verify()` interno daquela funcao e'
# estritamente escopado a uma unica parede - _rebase_node_indexes_for_wall
# so' sabe re-basear deslocamentos DENTRO do proprio eixo t da MESMA
# parede - reaproveita-lo aqui para um grupo de 2+ paredes exigiria
# reescrever a indexacao incremental do pipeline inteiro, risco grande
# demais para o ganho). Cada candidato de deslocamento e' testado
# reconstruindo o grafo de paredes do zero (extend_wall_ends_to_junctions +
# build_wall_graph) sobre uma copia com a geometria alterada, e rodando
# process_walls_one_by_one NELA - mais caro por tentativa, mas MUITO mais
# simples e seguro de implementar corretamente. O custo fica limitado por
# WALL_GROUP_SHIFT_VERIFY_BUDGET (esta etapa so' roda para o conjunto
# residual de paredes que sobrou depois do passo normal, tipicamente uma
# duzia, nao centenas).
# ==========================================

# Teto (cm) de deslocamento PERPENDICULAR automatico de uma parede INTEIRA
# (ETAPA 3C) - "poucos centimetros" pedido pelo usuario; mesma ordem de
# grandeza de AXIS_OPENING_SHIFT_MAX_CM (5cm)/BONECA_ADJUST_MAX_CM (2cm).
WALL_GROUP_SHIFT_MAX_CM = 3.0

# Teto de resolucoes COMPLETAS DA PLANTA (process_walls_one_by_one) que esta
# etapa pode gastar verificando candidatos, no TOTAL (nao por parede) - cada
# verificacao aqui e' MUITO mais cara que as de plan_axis_opening_fix
# (resolve TODAS as paredes, nao uma so'), entao o orcamento e' bem mais
# apertado que AXIS_VERIFY_ATTEMPT_LIMIT (40). Mesmo espirito do incidente
# de performance ja documentado em _solve_axis_width_increase - nunca deixar
# "Ajustar Erros" travar por minutos numa planta grande.
WALL_GROUP_SHIFT_VERIFY_BUDGET = 120

# Teto de tentativas verificadas POR PAREDE. Sem ele, as primeiras paredes
# da ordem de processamento consumiam o orcamento GLOBAL inteiro e todas as
# demais ficavam sem NENHUMA tentativa (bug de starvation: numa planta com
# uma duzia de paredes falhando, so' as duas primeiras eram tratadas).
WALL_GROUP_SHIFT_PER_WALL_BUDGET = 8

# RESOLVE PARCIAL da ETAPA 3C (pedido explicito do usuario, 2026-08-26 -
# "mais velocidade"): cada candidato testado por find_wall_group_shift_fixes
# so' re-resolve de verdade (solve_wall_free_fill/validacao) a(s) parede(s)
# cuja LINHA mudou + toda parede que compartilha um no' de encontro com
# elas (ver _expand_dirty_wall_idxs/_wall_node_neighbors,
# process_walls_one_by_one "dirty_wall_idxs") - as demais REUSAM o
# resultado ja' validado da resolucao principal (`run`), em vez de
# re-resolver a planta INTEIRA a cada tentativa (o gargalo medido da
# ETAPA 3C). Flag de seguranca: False volta ao comportamento antigo
# (re-solve completo sempre) sem precisar reverter nenhuma outra mudanca.
ETAPA_3C_PARTIAL_RESOLVE_ENABLED = True

# Teto (cm) de ALONGAMENTO OU ENCURTAMENTO automatico do comprimento de uma
# parede (pedido explicito do usuario, 2026-08-25). O ajuste so' acontece numa
# ponta FREE_END - basta UMA: ela nao encosta em nada, entao move-la ao longo
# do proprio eixo NAO cria "dente" nenhum, porque nenhum encontro L/T/X
# depende dela (a ponta CONECTADA nunca e' tocada por este mecanismo - e' essa
# a invariante que sustenta a regra "nunca criar dentes"). Exigir as DUAS
# pontas livres, como na primeira versao, descrevia um murete solto: numa
# planta real praticamente nunca acontecia, e por isso o usuario nao via
# ajuste nenhum. Reaproveita o MESMO mecanismo de verificacao da ETAPA
# 3C (find_wall_group_shift_fixes/_group_shift_trial_improves): so' um plano
# que o solver de blocos de verdade confirma que fecha e' aceito. Mesma ordem
# de grandeza dos outros tetos "poucos centimetros" do arquivo.
ISOLATED_WALL_LENGTH_ADJUST_MAX_CM = 5.0


def _pushed_corner_point(this_p_far, this_outward_dir, other_p0, other_dir, other_thickness_ft):
    """Mesma formula de extend_wall_ends_to_junctions (secao ETAPA 1, ver
    `final_point = hit + direction * margin`): ponto onde a ponta que sai
    de `this_p_far`, na direcao `this_outward_dir`, deve terminar para
    atravessar o EIXO da parede `other` (qualquer ponto+direcao que
    representem a reta dela - o SINAL de `other_dir` nao importa para o
    resultado, so' a reta em si) e chegar na FACE OPOSTA dela (mais meia
    espessura de `other_thickness_ft`, na mesma direcao de avanco
    `this_outward_dir`). None se as retas forem paralelas (nunca deveria
    acontecer num encontro real)."""
    hit = _line_2d_intersection(this_p_far, this_outward_dir, other_p0, other_dir)
    if hit is None:
        return None
    return hit + this_outward_dir * (other_thickness_ft / 2.0)


def _corner_reference_wall(node, wall_idx, end_index):
    """Wall_idx da OUTRA parede que participa deste no' de encontro
    (L_CORNER ou T_INTERSECTION), do ponto de vista de `(wall_idx,
    end_index)` - usado so' para saber contra qual EIXO recalcular a
    PROPRIA ponta de wall_idx quando ela e' deslocada (ver
    _shift_wall_line_perpendicular). Funciona tanto para L_CORNER quanto
    para T_INTERSECTION (wall_idx como parede INCOMING, que so' desliza ao
    longo da face da parede principal - nao muda o comprimento dela, so' a
    posicao do contato) - None quando wall_idx seria a parede PRINCIPAL de
    um T (esse caso e' rejeitado antes de chegar aqui, ver
    _wall_has_third_party_midspan_contact) ou quando o no' nao e' um
    encontro real."""
    if not isinstance(node, dict):
        return None
    kind = node.get("kind")
    if kind == "L_CORNER":
        arms = node.get("arms") or []
        others = [a[0] for a in arms if a != (wall_idx, end_index)]
        if others:
            return others[0]
        if node.get("neighbor_wall_idx") is not None:
            return node["neighbor_wall_idx"]
        return None
    if kind == "T_INTERSECTION":
        if node.get("incoming_wall_idx") == wall_idx:
            return node.get("main_wall_idx")
        return None
    return None


def _wall_group_shift_targets(wall_idx, wall_end_to_node, wall_graph_nodes):
    """Para cada ponta (0/1) de `wall_idx` classificada como L_CORNER real
    (a UNICA classificacao em que deslocar `wall_idx` de fato MUDA O
    COMPRIMENTO da parede vizinha - um T_INTERSECTION em que wall_idx e' a
    parede incoming so' desliza o ponto de contato ao longo da face da
    parede principal, sem alterar o comprimento de ninguem, ver
    _corner_reference_wall), devolve a OUTRA parede que compartilha aquele
    mesmo no' - candidata a ter o proprio comprimento recalculado se
    `wall_idx` for deslocada perpendicular ao proprio eixo.

    Devolve uma lista de {"shift_end": 0|1, "node_index": int,
    "neighbor_wall_idx": int, "neighbor_end_index": 0|1}. Nunca lanca
    excecao; [] se o grafo nao estiver disponivel ou nenhuma ponta
    encostar num L_CORNER real."""
    targets = []
    if not wall_end_to_node or not wall_graph_nodes:
        return targets
    for end_index in (0, 1):
        node_index = wall_end_to_node.get((wall_idx, end_index))
        if node_index is None:
            continue
        try:
            node = wall_graph_nodes[node_index]
        except (IndexError, TypeError):
            continue
        if not isinstance(node, dict) or node.get("kind") != "L_CORNER":
            continue
        arms = node.get("arms") or []
        others = [a for a in arms if a != (wall_idx, end_index)]
        if others:
            neighbor_idx, neighbor_end_index = others[0]
        elif node.get("neighbor_wall_idx") is not None:
            neighbor_idx, neighbor_end_index = node["neighbor_wall_idx"], node["neighbor_end_index"]
        else:
            continue
        targets.append({
            "shift_end": end_index, "node_index": node_index,
            "neighbor_wall_idx": neighbor_idx, "neighbor_end_index": neighbor_end_index,
        })
    return targets


def _wall_has_third_party_midspan_contact(wall_idx, wall_graph_nodes):
    """True se alguma OUTRA parede encosta em `wall_idx` fora das duas
    pontas dele - `wall_idx` sendo a parede PRINCIPAL (`main_wall_idx`) de
    um T_INTERSECTION em que uma TERCEIRA parede termina no meio dele, ou
    participando de um X_INTERSECTION de meio de parede
    (`crossing_walls`). Deslocar `wall_idx` nesses casos quebraria o
    encontro de uma parede fora do grupo (proibido pelo escopo "so'
    vizinhos diretos" confirmado com o usuario)."""
    for node in wall_graph_nodes or []:
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "T_INTERSECTION" and node.get("main_wall_idx") == wall_idx:
            return True
        crossing = node.get("crossing_walls")
        if crossing and wall_idx in crossing:
            return True
    return False


def _wall_shift_is_topologically_safe(wall_idx, walls_to_create, wall_end_to_node, wall_graph_nodes):
    """True quando `wall_idx` pode ser deslocada perpendicular ao proprio
    eixo sem quebrar nada fora do grupo direto: nenhuma ponta travada
    (`locked_ends` - uma testa real do CAD, nunca recalculada por este
    mecanismo), nenhum contato de TERCEIROS no meio dela (ver
    _wall_has_third_party_midspan_contact), e nenhuma ponta
    STRAIGHT_CONTINUATION/AMBIGUOUS (a parede seria literalmente um
    fragmento de um trecho reto mais longo, ou o no' e' geometricamente
    ambiguo - deslocar perpendicular separaria/sobreporia esses casos, fora
    de escopo desta versao)."""
    locks = walls_to_create[wall_idx][2]
    if locks[0] or locks[1]:
        return False
    if _wall_has_third_party_midspan_contact(wall_idx, wall_graph_nodes):
        return False
    for end_index in (0, 1):
        node_index = (wall_end_to_node or {}).get((wall_idx, end_index))
        if node_index is None:
            continue
        try:
            node = wall_graph_nodes[node_index]
        except (IndexError, TypeError):
            continue
        kind = node.get("kind") if isinstance(node, dict) else None
        if kind in ("STRAIGHT_CONTINUATION", "AMBIGUOUS"):
            return False
    return True


def _shift_wall_line_perpendicular(walls_to_create, wall_idx, delta_ft,
                                   wall_end_to_node, wall_graph_nodes,
                                   min_len_ft=MIN_SEGMENT_LENGTH_FT):
    """Nova Line de `wall_idx` deslocada perpendicular ao proprio eixo por
    `delta_ft` (translacao rigida - o comprimento da PROPRIA parede nunca
    muda por causa da translacao em si). Pontas em L_CORNER ou
    T_INTERSECTION (wall_idx como incoming) sao RECALCULADAS contra o eixo
    ORIGINAL (nao deslocado) da parede vizinha, com a MESMA formula de
    extend_wall_ends_to_junctions (ver _pushed_corner_point) - atravessa o
    eixo dela e chega na face oposta. Pontas FREE_END (ou sem no'
    conhecido) so' recebem a translacao rigida, sem recalculo.

    So' chame depois de confirmar _wall_shift_is_topologically_safe - nao
    revalida isso aqui.

    Devolve a nova Line, ou None se algum encontro ficasse geometricamente
    invalido (parede colapsaria a menos de `min_len_ft`, ou retas paralelas
    onde nao deveriam ser - nunca deveria acontecer num encontro real, mas
    e' checado por seguranca)."""
    centerline, _thickness_ft, _locks = walls_to_create[wall_idx]
    raw_p0 = centerline.GetEndPoint(0)
    raw_p1 = centerline.GetEndPoint(1)
    direction = (raw_p1 - raw_p0).Normalize()
    perp = _perp_dir(direction)
    offset = XYZ(perp.X * delta_ft, perp.Y * delta_ft, 0.0)
    points = [
        XYZ(raw_p0.X + offset.X, raw_p0.Y + offset.Y, raw_p0.Z),
        XYZ(raw_p1.X + offset.X, raw_p1.Y + offset.Y, raw_p1.Z),
    ]

    for end_index in (0, 1):
        node_index = (wall_end_to_node or {}).get((wall_idx, end_index))
        if node_index is None:
            continue
        try:
            node = wall_graph_nodes[node_index]
        except (IndexError, TypeError):
            continue
        other_idx = _corner_reference_wall(node, wall_idx, end_index)
        if other_idx is None:
            continue
        other_p0, _other_p1, other_dir, _other_len, other_thickness_ft = _wall_axis_and_length(
            walls_to_create, other_idx
        )
        this_p_far = points[1 - end_index]
        this_outward_dir = direction if end_index == 1 else direction.Negate()
        new_point = _pushed_corner_point(this_p_far, this_outward_dir, other_p0, other_dir, other_thickness_ft)
        if new_point is None:
            return None
        new_len_ft = (new_point - this_p_far).DotProduct(this_outward_dir)
        if new_len_ft < min_len_ft:
            return None
        points[end_index] = new_point

    return Line.CreateBound(points[0], points[1])


def _extend_wall_line_axial(walls_to_create, wall_idx, delta_ft, side,
                            min_len_ft=MIN_SEGMENT_LENGTH_FT):
    """Nova Line de `wall_idx` com a ponta `side` (0 ou 1) movida ao longo
    do PROPRIO eixo por `delta_ft` (positivo = alonga, negativo = encurta) -
    a ponta OPOSTA nunca e' tocada. `side` tem que ser uma ponta FREE_END
    (ver _axis_free_end_sides): como ela nao encosta em nada, mover so' ela
    nao afeta nenhum encontro L/T/X vizinho nem cria "dente".

    Devolve a nova Line, ou None se o resultado colapsaria a menos de
    `min_len_ft`."""
    centerline, _thickness_ft, _locks = walls_to_create[wall_idx]
    p0 = centerline.GetEndPoint(0)
    p1 = centerline.GetEndPoint(1)
    direction = (p1 - p0).Normalize()
    new_len_ft = centerline.Length + delta_ft
    if new_len_ft < min_len_ft:
        return None
    if side == 0:
        new_p0 = XYZ(p0.X - direction.X * delta_ft, p0.Y - direction.Y * delta_ft, p0.Z)
        return Line.CreateBound(new_p0, p1)
    new_p1 = XYZ(p1.X + direction.X * delta_ft, p1.Y + direction.Y * delta_ft, p1.Z)
    return Line.CreateBound(p0, new_p1)


def _recompute_neighbor_line_after_shift(walls_to_create, neighbor_idx, neighbor_end_index,
                                         w_new_p0, w_direction, w_thickness_ft,
                                         min_len_ft=MIN_SEGMENT_LENGTH_FT):
    """Nova Line do vizinho depois que a parede W (que forma este encontro
    L_CORNER) foi deslocada perpendicular ao proprio eixo - so' a ponta
    `neighbor_end_index` muda (a ponta OPOSTA do vizinho nunca e' tocada,
    mesma garantia de _build_axis_opening_plan/apply_axis_opening_fix para
    o resto do arquivo). `w_new_p0`/`w_direction` representam a NOVA reta
    de W (qualquer ponto dela serve, e' tratada como reta infinita);
    `w_thickness_ft` e' a espessura de W (nao muda com a translacao).

    Devolve (new_line, delta_len_ft) - delta_len_ft > 0 = vizinho cresceu,
    < 0 = encolheu (a excecao AUTORIZADA a regra #1 desta ETAPA - ver
    cabecalho). (None, 0.0) se o resultado fosse geometricamente invalido
    (parede colapsaria a menos de `min_len_ft`, ou retas paralelas)."""
    n_p0, n_p1, _n_dir, n_len_ft, _n_th = _wall_axis_and_length(walls_to_create, neighbor_idx)
    n_p_end = n_p0 if neighbor_end_index == 0 else n_p1
    n_p_far = n_p1 if neighbor_end_index == 0 else n_p0
    n_outward_dir = (n_p_end - n_p_far).Normalize()
    new_point = _pushed_corner_point(n_p_far, n_outward_dir, w_new_p0, w_direction, w_thickness_ft)
    if new_point is None:
        return None, 0.0
    new_len_ft = (new_point - n_p_far).DotProduct(n_outward_dir)
    if new_len_ft < min_len_ft:
        return None, 0.0
    new_line = (
        Line.CreateBound(new_point, n_p_far) if neighbor_end_index == 0
        else Line.CreateBound(n_p_far, new_point)
    )
    return new_line, new_len_ft - n_len_ft


def _candidate_walls_to_shift_for(wall_idx, base_walls, wall_end_to_node, wall_graph_nodes):
    """Paredes candidatas a SEREM DESLOCADAS para tentar consertar
    `wall_idx` (que esta' falhando a modulacao): as VIZINHAS dela em
    encontros L_CORNER reais - deslocar UMA DELAS perpendicular ao proprio
    eixo e' o que muda o COMPRIMENTO de `wall_idx` (deslocar a propria
    `wall_idx` so' mudaria o comprimento das VIZINHAS dela, nunca o dela
    mesma - e' uma translacao rigida, ver _wall_group_shift_targets).

    DELIBERADAMENTE so' 1 salto (sem BFS/propagacao em cadeia) - regra de
    escopo JA' CONFIRMADA com o usuario (2026-08-25, ver cabecalho da
    ETAPA 3C): "so' vizinhos DIRETOS ... sem propagacao em cadeia". Avaliado
    de novo nesta sessao (ver FASE 3 do plano em
    C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md) para o
    exemplo de encontro em U/H do usuario (duas verticais conectadas por
    uma horizontal compartilhada): a parede horizontal JA' e' vizinha
    DIRETA de CADA vertical nesse caso classico - o ganho real nao estava
    na profundidade da busca, e sim em COMPARAR candidatos (ver
    find_wall_group_shift_fixes/_group_shift_trial_score, que agora
    prefere um deslocamento que corrige VARIAS paredes da lista de falhas
    de uma vez so'). Estender para 2+ saltos reverteria a regra ja'
    confirmada com o usuario - NAO fazer isso sem reconfirmar."""
    candidates = []
    for target in _wall_group_shift_targets(wall_idx, wall_end_to_node, wall_graph_nodes):
        n_idx = target["neighbor_wall_idx"]
        if n_idx in candidates:
            continue
        if _wall_shift_is_topologically_safe(n_idx, base_walls, wall_end_to_node, wall_graph_nodes):
            candidates.append(n_idx)
    return candidates


def _wall_ok_map(a_run):
    """{wall_idx: bool} - True quando a parede fecha a modulacao nesta
    resolucao (`validation['ok']` e sem `non_modular`). Fatorado de
    _group_shift_trial_improves para ser reaproveitado pelo score (ver
    _group_shift_trial_score) sem duplicar a mesma leitura."""
    return dict(
        (entry["wall_idx"], entry["validation"]["ok"] and not entry["non_modular"])
        for entry in a_run["per_wall"]
    )


def _wall_node_neighbors(wall_idx, wall_graph_nodes, wall_end_to_node):
    """{wall_idx dos vizinhos} - toda parede que compartilha um NO' (ponta
    L/T/X ou cruzamento de meio-de-parede) com `wall_idx`, no MESMO grafo
    que _candidate_walls_to_shift_for ja usa para achar candidatos a
    deslocar. Usado pelo RESOLVE PARCIAL da ETAPA 3C (ver
    _expand_dirty_wall_idxs/process_walls_one_by_one, `dirty_wall_idxs`) -
    NAO confundir com _wall_group_shift_targets (que so' devolve o
    vizinho de encontros L_CORNER, relevante para ESCOLHER quem deslocar;
    aqui precisamos de QUALQUER encontro, inclusive T/X, porque a pergunta
    e' outra: "quem mais pode ter sua propria modulacao afetada por esta
    parede ter mudado de geometria"."""
    neighbors = set()
    for end_index in (0, 1):
        node_id = wall_end_to_node.get((wall_idx, end_index))
        if node_id is None:
            continue
        node = wall_graph_nodes[node_id]
        for w, _e in (node.get("arms") or []):
            if w != wall_idx:
                neighbors.add(w)
    for node in wall_graph_nodes:
        crossing_walls = node.get("crossing_walls")
        if crossing_walls and wall_idx in crossing_walls:
            neighbors.add(crossing_walls[0] if crossing_walls[1] == wall_idx else crossing_walls[1])
    return neighbors


def _expand_dirty_wall_idxs(seed_idxs, wall_graph_nodes, wall_end_to_node):
    """Fecho de 1 salto (ver _wall_node_neighbors) a partir de `seed_idxs` -
    o conjunto de paredes cuja modulacao PODE ter sido afetada por uma
    mudanca de geometria nas paredes de `seed_idxs`, usado como
    `dirty_wall_idxs` do RESOLVE PARCIAL (process_walls_one_by_one) dentro
    de find_wall_group_shift_fixes. `seed_idxs` ja' inclui a parede
    deslocada E suas vizinhas de encontro (`member_lines.keys()` - as
    UNICAS paredes cuja LINHA de verdade mudou nesta tentativa) - este
    fecho de mais 1 salto cobre quem NAO mudou de geometria mas pode ter
    sua propria modulacao/validacao afetada por quem mudou (ex.: um
    encontro T onde so' o braco perpendicular se moveu)."""
    dirty = set(seed_idxs)
    for wall_idx in list(seed_idxs):
        dirty.update(_wall_node_neighbors(wall_idx, wall_graph_nodes, wall_end_to_node))
    return dirty


def _group_shift_trial_improves(run, trial_run, changed_wall_idxs):
    """True quando a tentativa de deslocamento de grupo: (a) faz TODAS as
    paredes de `changed_wall_idxs` passarem a fechar (validation['ok'] e
    sem non_modular) na re-solucao completa da planta (`trial_run`), e (b)
    NENHUMA parede que estava OK em `run` (a resolucao original, ANTES do
    deslocamento) passa a falhar em `trial_run` - nunca troca um problema
    por outro."""
    before = _wall_ok_map(run)
    after = _wall_ok_map(trial_run)
    for wall_idx in changed_wall_idxs:
        if not after.get(wall_idx, False):
            return False
    for wall_idx, was_ok in before.items():
        if was_ok and not after.get(wall_idx, False):
            return False
    return True


def _group_shift_trial_score(run, trial_run, member_lines, delta_cm, still_failing_idxs):
    """Score de UM candidato JA' APROVADO por _group_shift_trial_improves -
    ver FASE 3 do plano em C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-
    petal.md ("escolher automaticamente a melhor solucao").

    `trial_run` ja' re-resolve a planta INTEIRA (e' o mesmo `process_walls_
    one_by_one` que _group_shift_trial_improves usa para o gate de
    aprovacao/regressao) - ou seja, o efeito deste candidato sobre TODAS as
    outras paredes que ainda estavam falhando (`still_failing_idxs`, a
    lista ORIGINAL de failing_idxs de find_wall_group_shift_fixes) JA' esta'
    calculado; contar quantas delas passam a fechar aqui e'
    ESSENCIALMENTE DE GRACA (nenhuma chamada extra de verify()) - e' assim
    que um deslocamento de grupo que resolve DUAS paredes conectadas de
    uma vez (ex.: a parede horizontal compartilhada de um encontro em U/H,
    ver exemplo do usuario) fica visivel para o solver PREFERIR em vez de
    resolver as duas separadamente.

    Devolve uma tupla ordenavel (menor = melhor):
    `(-paredes_recem_corrigidas, deslocamento_cm, elementos_alterados)` -
    prioriza NESTA ordem: (1) mais paredes da lista de falhas corrigidas de
    uma vez so', (2) menor deslocamento, (3) menos elementos alterados.
    Conflito/regressao continua sendo um GATE obrigatorio, verificado
    ANTES de chamar esta funcao (_group_shift_trial_improves) - nunca um
    fator de score: uma solucao "melhor pontuada" nunca pode vencer se
    piorar alguma coisa."""
    after = _wall_ok_map(trial_run)
    before = _wall_ok_map(run)
    newly_fixed = sum(
        1 for wall_idx in still_failing_idxs
        if not before.get(wall_idx, False) and after.get(wall_idx, False)
    )
    return (-newly_fixed, abs(delta_cm), len(member_lines))


def _build_group_shift_plan(shifted_idx, delta_cm, member_lines, ft_to_cm):
    """Monta o dict de plano devolvido por find_wall_group_shift_fixes a
    partir de um candidato ja' aprovado por _group_shift_trial_improves.
    `member_lines`: {wall_idx: nova Line}, com `shifted_idx` incluido."""
    members = []
    for m_idx, m_line in member_lines.items():
        role = "shifted" if m_idx == shifted_idx else "neighbor"
        members.append({
            "wall_idx": m_idx, "role": role, "new_centerline": m_line,
            "new_length_cm": m_line.GetEndPoint(0).DistanceTo(m_line.GetEndPoint(1)) * ft_to_cm,
        })
    return {
        "kind": "group_shift", "feasible": True, "reason": None,
        "shifted_wall_idx": shifted_idx, "shift_delta_cm": delta_cm,
        "max_shift_cm": abs(delta_cm),
        "members": members,
    }


def _build_isolated_extend_plan(wall_idx, delta_cm, new_line, ft_to_cm):
    """Monta o dict de plano para o ajuste de comprimento de uma parede
    ISOLADA (ver ISOLATED_WALL_LENGTH_ADJUST_MAX_CM) - MESMO formato de
    _build_group_shift_plan, para reaproveitar apply_wall_group_shift sem
    nenhuma alteracao. O membro tem role SEMPRE "neighbor" (edita so' o
    pilar real da ponta que mudou) - NUNCA "shifted", que faria
    apply_wall_group_shift tratar isto como uma TRANSLACAO RIGIDA (comprimento
    igual, so' a posicao muda), errado aqui: o comprimento da propria parede
    e' o que MUDA de verdade."""
    return {
        "kind": "wall_length_adjust", "feasible": True, "reason": None,
        "shifted_wall_idx": wall_idx, "shift_delta_cm": delta_cm,
        "max_shift_cm": abs(delta_cm),
        "members": [{
            "wall_idx": wall_idx, "role": "neighbor", "new_centerline": new_line,
            "new_length_cm": new_line.GetEndPoint(0).DistanceTo(new_line.GetEndPoint(1)) * ft_to_cm,
        }],
    }


def find_wall_group_shift_fixes(run, walls_to_create, openings_per_wall,
                                wall_graph_nodes, wall_end_to_node, catalog, plan_hook,
                                allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                                max_shift_cm=WALL_GROUP_SHIFT_MAX_CM,
                                verify_budget=WALL_GROUP_SHIFT_VERIFY_BUDGET,
                                isolated_extend_max_cm=ISOLATED_WALL_LENGTH_ADJUST_MAX_CM,
                                per_wall_budget=WALL_GROUP_SHIFT_PER_WALL_BUDGET,
                                progress_cb=None, should_cancel_cb=None, should_pause_cb=None):
    """Roda DEPOIS de `run = process_walls_one_by_one(...)` ja' ter
    tentado o ajuste normal de abertura em cada parede (via `plan_hook`,
    o MESMO passado para `run` - reaproveitado aqui para que os ajustes de
    abertura de OUTRAS paredes continuem disponiveis nas re-solucoes de
    tentativa). Para as paredes que AINDA falham (sem validation['ok'] ou
    com non_modular) e que NAO foram resolvidas por um ajuste de abertura,
    tenta deslocar uma parede VIZINHA delas (ver
    _candidate_walls_to_shift_for) perpendicular ao proprio eixo, alguns
    cm, e RE-VERIFICA rodando process_walls_one_by_one NA PLANTA INTEIRA
    sobre a geometria alterada (grafo reconstruido do zero - ver cabecalho
    da ETAPA 3C).

    Quando o deslocamento de grupo nao resolve e a parede tem ao menos UMA
    ponta FREE_END, tenta em vez disso ALONGAR OU ENCURTAR a propria parede
    ao longo do proprio eixo, movendo SO' essa ponta livre (ver
    _extend_wall_line_axial/ISOLATED_WALL_LENGTH_ADJUST_MAX_CM) - pedido
    explicito do usuario (2026-08-25). ENCURTAR e' sempre tentado antes de
    ALONGAR. Nao cria "dente" porque a ponta livre nao encosta em nada e a
    ponta conectada nunca e' movida. MESMA verificacao rigorosa (re-solve
    da planta inteira via process_walls_one_by_one + _group_shift_trial_improves).

    Os deltas de comprimento (aqui e no deslocamento de grupo) vem de
    _wall_length_snap_targets_cm e sao FRACIONARIOS: com o passo inteiro
    antigo, uma parede de comprimento fracionario - o caso comum vindo de
    CAD - nunca alcancava um comprimento valido.

    So' aceita um deslocamento quando: (a) toda parede do grupo (a
    deslocada + vizinhas cujo comprimento mudou) passa a fechar; (b)
    nenhuma parede que antes fechava passa a falhar (_group_shift_trial_improves).
    Prioriza sempre o MENOR |delta| (ordem +1,-1,+2,-2,...cm) e o pre-filtro
    aritmetico barato `wall_length_closes_with_blocks_cm` antes de gastar
    orcamento de verificacao com o re-solve caro da planta inteira.

    Devolve {wall_idx: group_plan} - uma entrada por parede do GRUPO
    INTEIRO que mudou (nao so' a que estava reprovada), so' com sucesso
    VERIFICADO.

    `progress_cb(tentativa, total_tentativas, wall_idx, tipo)`, se
    fornecido, e' chamado a CADA tentativa de re-solve da planta inteira
    (ate' `verify_budget` vezes - 120 por padrao) - existe porque cada
    tentativa roda process_walls_one_by_one sobre TODAS as paredes so'
    para verificar UM candidato de ajuste, e sem nenhum feedback esse laco
    e' exatamente o tipo de trabalho pesado e silencioso que faz o script
    parecer travado (ver PERFORMANCE em main()) mesmo sendo um numero
    FINITO e limitado de tentativas. `progress_cb` tambem e' chamado com 1
    argumento (mensagem de status pronta) nos dois pontos abaixo - ver
    `_dispatch_progress_event`, que e' a UNICA forma correta de consumir
    este callback (o descarte silencioso de chamadas de 1/4 argumentos foi
    a causa real de um travamento reportado em producao - ver FASE 1 do
    plano em C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md).

    `should_cancel_cb()`, se fornecido, e' checado nos MESMOS pontos onde
    `budget["left"]` ja' e' checado (a cada tentativa) - devolver True
    interrompe a busca de grupo/ponta-livre PARA A PAREDE ATUAL e para as
    seguintes, mas preserva qualquer plano JA' verificado em `results` (o
    cancelamento nunca desfaz um plano ja' aceito, so' para de procurar
    mais)."""
    base_walls = run["walls_after"]
    base_openings = run["openings_after"]
    # RESOLVE PARCIAL (ver docstring de process_walls_one_by_one,
    # "dirty_wall_idxs") - indexado uma UNICA vez aqui, reusado por TODAS as
    # tentativas de TODAS as paredes falhando (a topologia base nao muda
    # entre tentativas, so' a geometria de algumas paredes). Flag de
    # seguranca: ETAPA_3C_PARTIAL_RESOLVE_ENABLED=False volta ao re-solve
    # completo de sempre, sem tocar em mais nada, se algum caso real expuser
    # uma lacuna no fecho de 1 salto (_expand_dirty_wall_idxs).
    base_per_wall_by_idx = dict((e["wall_idx"], e) for e in run["per_wall"])
    base_candidates = run["candidates"]

    failing_idxs = []
    for entry in run["per_wall"]:
        wall_idx = entry["wall_idx"]
        validation = entry["validation"]
        if validation["ok"] and not entry["non_modular"]:
            continue
        if entry["adjusted"] and entry["plan"] is not None:
            continue  # ja' resolvido por um ajuste de abertura - nao precisa de grupo
        failing_idxs.append(wall_idx)

    if not failing_idxs:
        return {}

    if progress_cb is not None:
        progress_cb(
            "TENTAR CORRIGIR (ETAPA 3C): {} parede(s) ainda sem solucao apos o solver "
            "principal - procurando deslocamento de grupo/ajuste de ponta livre "
            "(orcamento de {} verificacoes)...".format(len(failing_idxs), verify_budget)
        )

    ft_to_cm = 100.0 / FEET_PER_METER
    budget = {"left": verify_budget}
    results = {}

    for _fi, wall_idx in enumerate(failing_idxs):
        if wall_idx in results:
            continue  # ja' resolvido como vizinho de uma parede anterior
        if should_pause_cb is not None:
            while should_pause_cb():
                _pump_ui_events_if_needed()
        if should_cancel_cb is not None and should_cancel_cb():
            if progress_cb is not None:
                progress_cb(
                    "CANCELADO pelo usuario durante a ETAPA 3C - {} parede(s) ainda "
                    "sem solucao, mantendo o que ja foi corrigido ate' aqui."
                    .format(len(failing_idxs) - len(results))
                )
            break
        if progress_cb is not None:
            progress_cb(
                "TENTAR CORRIGIR (ETAPA 3C): parede {} ({}/{})...".format(
                    wall_idx, _fi + 1, len(failing_idxs))
            )
        if budget["left"] <= 0:
            break
        candidates = _candidate_walls_to_shift_for(wall_idx, base_walls, wall_end_to_node, wall_graph_nodes)
        found_plan = None
        # FASE 3 (score de solucoes, ver _group_shift_trial_score):
        # `best_score`/`found_plan` guardam o MELHOR candidato ja' visto,
        # nao mais o PRIMEIRO - continua explorando os demais candidatos/
        # deltas dentro do MESMO orcamento (group_wall_budget/budget) de
        # sempre, nunca gastando MAIS verificacoes do que antes por
        # parede, so' redistribuindo o orcamento de "parar cedo" para
        # "comparar antes de decidir". Isso e' o que permite um
        # deslocamento que resolve VARIAS paredes conectadas de uma vez
        # (ex.: a parede compartilhada de um encontro em U/H) ser
        # preferido a uma correcao isolada - ver docstring de
        # _group_shift_trial_score.
        best_score = None

        # Deslocar a vizinha em `d` muda o COMPRIMENTO desta parede em ~|d|,
        # entao os candidatos vem dos ALVOS de comprimento DELA - fracionarios
        # (ver _wall_length_snap_targets_cm: com passo inteiro, uma parede de
        # comprimento fracionario nunca alcanca um comprimento valido). O
        # SINAL do deslocamento perpendicular que produz o alongamento
        # desejado depende da orientacao do encontro, entao os dois sao
        # tentados; o pre-filtro barato `wall_length_closes_with_blocks_cm`
        # sobre o comprimento recalculado do vizinho descarta o sinal errado
        # antes de gastar orcamento de verificacao.
        signed_deltas_cm = []
        for _target_cm, delta_cm in _wall_length_snap_targets_cm(
                base_walls[wall_idx][0].Length * ft_to_cm, max_shift_cm):
            signed_deltas_cm.append(delta_cm)
            signed_deltas_cm.append(-delta_cm)

        group_wall_budget = per_wall_budget
        for shifted_idx in candidates:
            targets = _wall_group_shift_targets(shifted_idx, wall_end_to_node, wall_graph_nodes)
            if not targets:
                continue
            for delta_cm in signed_deltas_cm:
                if budget["left"] <= 0 or group_wall_budget <= 0:
                    break
                if should_pause_cb is not None:
                    while should_pause_cb():
                        _pump_ui_events_if_needed()
                if should_cancel_cb is not None and should_cancel_cb():
                    budget["left"] = 0
                    break
                delta_ft = delta_cm / ft_to_cm
                new_shifted_line = _shift_wall_line_perpendicular(
                    base_walls, shifted_idx, delta_ft, wall_end_to_node, wall_graph_nodes
                )
                if new_shifted_line is None:
                    continue
                w_new_p0 = new_shifted_line.GetEndPoint(0)
                w_direction = (new_shifted_line.GetEndPoint(1) - w_new_p0).Normalize()
                w_thickness_ft = base_walls[shifted_idx][1]

                member_lines = {shifted_idx: new_shifted_line}
                plausible = True
                for target in targets:
                    n_idx = target["neighbor_wall_idx"]
                    n_end = target["neighbor_end_index"]
                    new_n_line, _delta_len_ft = _recompute_neighbor_line_after_shift(
                        base_walls, n_idx, n_end, w_new_p0, w_direction, w_thickness_ft
                    )
                    if new_n_line is None:
                        plausible = False
                        break
                    new_len_cm = new_n_line.GetEndPoint(0).DistanceTo(new_n_line.GetEndPoint(1)) * ft_to_cm
                    if not wall_length_closes_with_blocks_cm(new_len_cm):
                        plausible = False
                        break
                    member_lines[n_idx] = new_n_line
                if not plausible or budget["left"] <= 0:
                    continue

                budget["left"] -= 1
                group_wall_budget -= 1
                if progress_cb is not None:
                    progress_cb(verify_budget - budget["left"], verify_budget, wall_idx, "deslocamento de grupo")
                trial_walls = list(base_walls)
                for m_idx, m_line in member_lines.items():
                    _old_line, old_thickness_ft, old_locks = trial_walls[m_idx]
                    trial_walls[m_idx] = (m_line, old_thickness_ft, old_locks)
                trial_openings = _copy_openings_per_wall(base_openings)

                trial_walls_ext, trial_junction_map = extend_wall_ends_to_junctions(
                    trial_walls, JUNCTION_FACE_SEARCH_FT
                )
                trial_nodes, trial_end_to_node = build_wall_graph(trial_walls_ext, trial_junction_map)
                partial_kwargs = {}
                if ETAPA_3C_PARTIAL_RESOLVE_ENABLED:
                    partial_kwargs = {
                        "dirty_wall_idxs": _expand_dirty_wall_idxs(
                            member_lines.keys(), trial_nodes, trial_end_to_node
                        ),
                        "baseline_per_wall": base_per_wall_by_idx,
                        "baseline_candidates": base_candidates,
                    }
                trial_run = process_walls_one_by_one(
                    trial_walls_ext, trial_nodes, trial_end_to_node, trial_openings,
                    catalog, allow_compensators=allow_compensators, plan_hook=plan_hook,
                    **partial_kwargs
                )

                if not _group_shift_trial_improves(run, trial_run, member_lines.keys()):
                    continue

                score = _group_shift_trial_score(
                    run, trial_run, member_lines, delta_cm, failing_idxs
                )
                if best_score is None or score < best_score:
                    best_score = score
                    found_plan = _build_group_shift_plan(shifted_idx, delta_cm, member_lines, ft_to_cm)
                    # `-score[0]` (paredes recem-corrigidas) no maximo
                    # possivel para este candidato ja' e' o melhor caso
                    # (todas as demais falhas resolvidas junto) - nenhum
                    # outro candidato pode pontuar melhor no criterio
                    # primario, entao parar de gastar orcamento aqui e'
                    # seguro (mesmo efeito pratico do "break" antigo no
                    # caso comum de 1 parede so').
                    if score[0] == -len(failing_idxs):
                        break
            if (budget["left"] <= 0 or group_wall_budget <= 0
                    or (best_score is not None and best_score[0] == -len(failing_idxs))):
                break

        # Nenhuma parede vizinha candidata (sem conexao/amarracao relevante -
        # AJUSTE DE COMPRIMENTO NA PONTA LIVRE - fallback quando o
        # deslocamento de grupo nao resolveu. Basta UMA ponta FREE_END: ela
        # nao encosta em nada, entao mover essa ponta ao longo do proprio
        # eixo NUNCA cria "dente" (a ponta CONECTADA jamais e' tocada aqui -
        # e' essa a invariante que sustenta a regra do usuario). Encurtar e'
        # sempre tentado ANTES de alongar (ordem de _wall_length_snap_targets_cm).
        if found_plan is None and budget["left"] > 0:
            free_sides = _axis_free_end_sides(wall_idx, wall_end_to_node, wall_graph_nodes)
            if free_sides:
                current_len_cm = base_walls[wall_idx][0].Length * ft_to_cm
                wall_budget = per_wall_budget
                for _target_cm, delta_cm in _wall_length_snap_targets_cm(
                        current_len_cm, isolated_extend_max_cm):
                    if budget["left"] <= 0 or wall_budget <= 0:
                        break
                    if should_pause_cb is not None:
                        while should_pause_cb():
                            _pump_ui_events_if_needed()
                    if should_cancel_cb is not None and should_cancel_cb():
                        budget["left"] = 0
                        break
                    delta_ft = delta_cm / ft_to_cm
                    new_line = None
                    for side in free_sides:
                        candidate_line = _extend_wall_line_axial(base_walls, wall_idx, delta_ft, side)
                        if candidate_line is None:
                            continue
                        new_line = candidate_line
                        break
                    if new_line is None:
                        continue

                    budget["left"] -= 1
                    wall_budget -= 1
                    if progress_cb is not None:
                        progress_cb(
                            verify_budget - budget["left"], verify_budget, wall_idx,
                            "ajuste de comprimento na ponta livre"
                        )
                    trial_walls = list(base_walls)
                    _old_line, old_thickness_ft, old_locks = trial_walls[wall_idx]
                    trial_walls[wall_idx] = (new_line, old_thickness_ft, old_locks)
                    trial_openings = _copy_openings_per_wall(base_openings)

                    trial_walls_ext, trial_junction_map = extend_wall_ends_to_junctions(
                        trial_walls, JUNCTION_FACE_SEARCH_FT
                    )
                    trial_nodes, trial_end_to_node = build_wall_graph(trial_walls_ext, trial_junction_map)
                    partial_kwargs = {}
                    if ETAPA_3C_PARTIAL_RESOLVE_ENABLED:
                        partial_kwargs = {
                            "dirty_wall_idxs": _expand_dirty_wall_idxs(
                                [wall_idx], trial_nodes, trial_end_to_node
                            ),
                            "baseline_per_wall": base_per_wall_by_idx,
                            "baseline_candidates": base_candidates,
                        }
                    trial_run = process_walls_one_by_one(
                        trial_walls_ext, trial_nodes, trial_end_to_node, trial_openings,
                        catalog, allow_compensators=allow_compensators, plan_hook=plan_hook,
                        **partial_kwargs
                    )
                    if not _group_shift_trial_improves(run, trial_run, [wall_idx]):
                        continue
                    found_plan = _build_isolated_extend_plan(wall_idx, delta_cm, new_line, ft_to_cm)
                    break

        if found_plan is not None:
            for member in found_plan["members"]:
                results[member["wall_idx"]] = found_plan
            if progress_cb is not None:
                # Ledger da tentativa vencedora (pedido do usuario, ver
                # FASE 3 do plano - "Wall 1025 / Tentativa N: ... ->
                # resolveu"). `best_score` so' existe no ramo de
                # deslocamento de grupo (None no ramo de ponta livre
                # isolada, que nao compara candidatos).
                extra_walls = len(found_plan["members"]) - 1
                score_note = ""
                if best_score is not None:
                    fixed_together = -best_score[0]
                    if fixed_together > 1:
                        score_note = " ({} parede(s) da lista de falhas corrigidas junto)".format(
                            fixed_together
                        )
                progress_cb(
                    "CONCLUIDO (ETAPA 3C) - parede {}: {} ({:+.1f}cm, {} parede(s) do "
                    "grupo alterada(s)){}.".format(
                        wall_idx, found_plan["kind"], found_plan["shift_delta_cm"],
                        1 + extra_walls, score_note
                    )
                )
        elif progress_cb is not None:
            # Pedido explicito do usuario: nunca deixar uma parede/grupo
            # "sumir" em silencio quando o orcamento de tentativas se
            # esgota sem solucao verificada - o desvio para a proxima
            # parede ja acontecia (results[wall_idx] simplesmente nao e'
            # preenchido), so' faltava deixar isso visivel no log.
            progress_cb(
                "FALHOU (ETAPA 3C) - parede {}: nenhum deslocamento de grupo/ajuste de "
                "ponta livre verificado dentro do orcamento disponivel - requer revisao "
                "manual, seguindo para a proxima parede.".format(wall_idx)
            )
    return results

