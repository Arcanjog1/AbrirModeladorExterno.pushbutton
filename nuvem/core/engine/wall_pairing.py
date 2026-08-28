# -*- coding: utf-8 -*-
"""Pareamento de linhas em paredes, linhas de fechamento (testas) e grafo de
encontros (L/T/X) - EXTRAIDO verbatim de core/wall_modeling.py (linhas
~820-2170 na versao de origem): find_wall_pairs, scan_possible_missed_bonecas,
classify_unused_line_reason, extend_wall_ends_to_junctions e seus helpers de
grafo (_wall_node_arms e familia), build_wall_graph, build_plan_bounds,
deduplicate_walls, build_no_pairs_message, scan_candidate_thicknesses_cm e
compute_detection_tolerance_ft - alem das funcoes de linha de fechamento
(find_cap_positions/clip_centerline_to_caps e seus helpers privados) das
quais find_wall_pairs depende.

Nenhuma formula mudou, so' o arquivo onde moram (mesma tecnica ja' usada em
core/engine/geometry.py). `wall_modeling.py` importa tudo daqui via
`from core.engine.wall_pairing import *` no lugar onde este bloco estava.

Modulo PURO quanto a UI/Revit-document: nao abre Transaction, nao le' `doc`,
nao chama forms.* - so' usa os tipos geometricos XYZ/Line (reais no Revit,
ou o shim leve usado pelos testes/pelo visualizador externo) e as funcoes
puras de core/engine/geometry.py e core/engine/tolerances.py. `ask_wall_thicknesses`
(que PERGUNTA a espessura ao usuario via forms.SelectFromList) NAO foi movida
para ca' de proposito - ela e' UI, nao pareamento; ficou em wall_modeling.py,
que continua podendo chamar `scan_candidate_thicknesses_cm` (aqui) para
montar as opcoes.
"""

from core.engine.tolerances import (  # noqa: F401
    FEET_PER_METER, MIN_WALL_THICKNESS_FT, MAX_WALL_THICKNESS_FT,
    MIN_WALL_SEGMENT_OVERLAP_RATIO, MIN_WALL_SEGMENT_ABS_FLOOR_FT,
    DUPLICATE_AXIS_TOLERANCE_FT, WALL_THICKNESS_MATCH_TOLERANCE_FT,
    WALL_DETECTION_TOLERANCE_FT, CENTERLINE_MAX_EXTENSION_FT,
    OPENING_ASSOC_TOLERANCE_FT, MIN_SEGMENT_LENGTH_FT, MIN_SEGMENT_HEIGHT_FT,
    AXIS_OFFSET_WARNING_FT, OPENING_WIDTH_CLAMP_WARNING_FT,
    CAP_MIN_COVERAGE_RATIO, CAP_MAX_COVERAGE_RATIO, CAP_MAX_AXIAL_COMPONENT,
    CAP_MAX_CENTER_OFFSET_RATIO, CAP_SEARCH_MARGIN_FT,
    CAP_ENDPOINT_TOUCH_TOLERANCE_FT, CAP_OPENING_SLACK_FT,
    MIN_WALL_THICKNESS_M, MAX_WALL_THICKNESS_M,
)
from core.engine.geometry import *  # noqa: F401,F403
from Autodesk.Revit.DB import XYZ, Line

# `__all__` inclui os nomes com underscore de proposito - `import *` os
# ignoraria por padrao, e varias funcoes "privadas" daqui (`_line_2d_intersection`
# etc.) sao chamadas por nome solto de FORA deste arquivo, dentro de
# wall_modeling.py (mesmo motivo/padrao de core/engine/geometry.py).
__all__ = [
    "_closest_target_thickness_ft", "_cap_falls_inside_opening",
    "_cap_touches_wall_face", "find_cap_positions", "clip_centerline_to_caps",
    "find_wall_pairs", "scan_possible_missed_bonecas", "_fmt_line_cm",
    "classify_unused_line_reason", "_line_2d_intersection",
    "extend_wall_ends_to_junctions", "_wall_node_arms",
    "_wall_end_geometric_anchor", "_wall_end_junction_anchor",
    "_cluster_wall_arms", "_classify_point_along_wall",
    "_find_wall_touching_point", "_classify_wall_node",
    "_find_wall_midspan_crossings", "build_wall_graph", "build_plan_bounds",
    "deduplicate_walls", "build_no_pairs_message",
    "scan_candidate_thicknesses_cm", "compute_detection_tolerance_ft",
    "WALL_GRAPH_NODE_SNAP_TOLERANCE_M", "WALL_GRAPH_NODE_SNAP_TOLERANCE_FT",
    "WALL_GRAPH_PERPENDICULAR_TOLERANCE", "WALL_GRAPH_COLLINEAR_TOLERANCE",
    # ---- associacao abertura -> parede (extraido junto com a "arquitetura
    # do modelador externo", 2026-08-26 - ver build_capture_payload em
    # ModulacaoAutomatica/.../core/capture_export.py, que serializa as
    # aberturas que este bloco depois reassocia as paredes reconstruidas) ----
    "_project_opening_raw", "_project_opening_on_line", "_merge_opening_matches",
    "find_openings_on_line", "assign_openings_to_walls", "build_wall_segments",
]


def _closest_target_thickness_ft(dist_ft, target_thicknesses_ft, tolerance_ft):
    """Devolve, dentre `target_thicknesses_ft`, o valor mais proximo de
    `dist_ft` desde que a diferenca fique dentro de `tolerance_ft`. Devolve
    None se nenhuma espessura escolhida pelo usuario for compativel - nesse
    caso o par NAO representa nenhuma das paredes que o usuario pediu para
    modelar e deve ser descartado."""
    best, best_diff = None, None
    for t in target_thicknesses_ft:
        diff = abs(dist_ft - t)
        if diff <= tolerance_ft and (best_diff is None or diff < best_diff):
            best, best_diff = t, diff
    return best


def _cap_falls_inside_opening(p0_flat, direction, t_cap, thickness_ft, openings):
    """Verifica se a linha transversal em `t_cap` cai dentro do vao de
    alguma abertura (porta/janela) desta parede.

    Nesse caso a linha NAO e' o fim da parede - e' a JAMBA do vao desenhada
    no CAD. A parede continua fisicamente ali, apenas com um trecho
    recortado em altura (verga acima e/ou peitoril abaixo), entao usar essa
    linha como limite cortaria a parede exatamente onde ela precisa
    continuar. E' a excecao pedida: portas/janelas podem existir so' como
    familia de Mobiliario no Revit, e o desenho do CAD ao redor delas nao
    define o fim da parede."""
    max_perp_dist_ft = thickness_ft / 2.0 + OPENING_ASSOC_TOLERANCE_FT
    for op in openings:
        center = op["center_xy"]
        t_center = (center - p0_flat).DotProduct(direction)
        proj_point = p0_flat + direction * t_center
        if center.DistanceTo(proj_point) > max_perp_dist_ft:
            continue  # abertura nao pertence a esta parede
        half_width_ft = op["width_ft"] / 2.0 + CAP_OPENING_SLACK_FT
        if (t_center - half_width_ft) <= t_cap <= (t_center + half_width_ft):
            return True
    return False


def _cap_touches_wall_face(a, b, candidate_lines, direction, tolerance_ft):
    """Verifica se a linha transversal candidata a testa (pontas `a`/`b`,
    ja achatadas em Z=0) TOCA a ponta de alguma linha do mesmo Layer que
    corre ao longo do eixo desta parede (uma face). E' assim que uma testa
    real fecha o fim fisico de uma parede no CAD: as duas linhas de face
    terminam exatamente onde a testa comeca/acaba.

    Uma linha transversal solta no meio do desenho (ruido/erro de CAD),
    sem tocar nenhuma face, NAO e' um fim de parede real - mesmo que, por
    coincidencia, tenha a largura e a centralizacao certas (ver
    CAP_ENDPOINT_TOUCH_TOLERANCE_M)."""
    for other in candidate_lines:
        oa_raw, ob_raw = other.GetEndPoint(0), other.GetEndPoint(1)
        oa = XYZ(oa_raw.X, oa_raw.Y, 0.0)
        ob = XYZ(ob_raw.X, ob_raw.Y, 0.0)
        seg = ob - oa
        seg_length = seg.GetLength()
        if seg_length < 1e-9:
            continue
        seg_dir = seg.Normalize()
        if abs(seg_dir.DotProduct(direction)) <= CAP_MAX_AXIAL_COMPONENT:
            continue  # e' transversal, nao uma face
        if (oa.DistanceTo(a) <= tolerance_ft or oa.DistanceTo(b) <= tolerance_ft or
                ob.DistanceTo(a) <= tolerance_ft or ob.DistanceTo(b) <= tolerance_ft):
            return True
    return False


def find_cap_positions(centerline, thickness_ft, candidate_lines, openings):
    """Procura, entre `candidate_lines` (todas as linhas do MESMO Layer),
    as linhas TRANSVERSAIS que fecham as duas faces desta parede - a
    "testa" da parede - e devolve a posicao longitudinal de cada uma ao
    longo do eixo (em pes, medida a partir da ponta 0 do eixo), junto com o
    comprimento do eixo.

    Uma linha e' aceita como fechamento quando, simultaneamente:
      - nao corre ao longo da parede (componente axial pequena - ver
        CAP_MAX_AXIAL_COMPONENT), ou seja, e' realmente transversal;
      - o quanto ela cobre PERPENDICULARMENTE bate com a espessura da
        parede (entre CAP_MIN_COVERAGE_RATIO e CAP_MAX_COVERAGE_RATIO dessa
        espessura) - e' isso que distingue uma testa, que vai de uma face
        a' outra, de uma parede perpendicular que atravessa e segue adiante;
      - fica centrada sobre o eixo desta parede (CAP_MAX_CENTER_OFFSET_RATIO),
        para nao capturar a testa de uma parede vizinha que passa perto;
      - cai dentro do alcance do eixo (com a folga CAP_SEARCH_MARGIN_FT);
      - TOCA a ponta de uma linha de face real (ver _cap_touches_wall_face)
        - senao e' ruido de CAD flutuando no meio do desenho, nao um fim de
        parede de verdade, mesmo que meca e centralize certo;
      - e NAO esta dentro do vao de uma abertura (ver
        _cap_falls_inside_opening) - ali a linha e' jamba, nao fim de parede.

    Todo o calculo e' feito em planta (Z achatado) e por projecao vetorial,
    entao funciona igual para qualquer orientacao de parede.
    """
    p0_raw = centerline.GetEndPoint(0)
    p1_raw = centerline.GetEndPoint(1)
    p0 = XYZ(p0_raw.X, p0_raw.Y, 0.0)
    p1 = XYZ(p1_raw.X, p1_raw.Y, 0.0)
    axis_length_ft = p0.DistanceTo(p1)
    if axis_length_ft < 1e-9:
        return [], 0.0

    direction = (p1 - p0).Normalize()
    perp = XYZ(-direction.Y, direction.X, 0.0)
    half_thickness_ft = thickness_ft / 2.0

    positions = []
    for line in candidate_lines:
        a_raw, b_raw = line.GetEndPoint(0), line.GetEndPoint(1)
        a = XYZ(a_raw.X, a_raw.Y, 0.0)
        b = XYZ(b_raw.X, b_raw.Y, 0.0)
        seg = b - a
        seg_length = seg.GetLength()
        if seg_length < 1e-9:
            continue

        seg_dir = seg.Normalize()
        if abs(seg_dir.DotProduct(direction)) > CAP_MAX_AXIAL_COMPONENT:
            continue  # corre ao longo da parede - e' face, nao testa

        s_a = (a - p0).DotProduct(perp)
        s_b = (b - p0).DotProduct(perp)
        perp_span_ft = abs(s_a - s_b)
        if perp_span_ft < thickness_ft * CAP_MIN_COVERAGE_RATIO:
            continue  # curta demais para ligar as duas faces
        if perp_span_ft > thickness_ft * CAP_MAX_COVERAGE_RATIO:
            continue  # longa demais - e' parede perpendicular atravessando, nao testa

        if abs((s_a + s_b) / 2.0) > half_thickness_ft * CAP_MAX_CENTER_OFFSET_RATIO:
            continue  # nao esta centrada nesta parede

        t_a = (a - p0).DotProduct(direction)
        t_b = (b - p0).DotProduct(direction)
        t_cap = (t_a + t_b) / 2.0
        if t_cap < -CAP_SEARCH_MARGIN_FT or t_cap > axis_length_ft + CAP_SEARCH_MARGIN_FT:
            continue  # fora do alcance desta parede

        if _cap_falls_inside_opening(p0, direction, t_cap, thickness_ft, openings):
            continue  # jamba de porta/janela - a parede continua ali

        if not _cap_touches_wall_face(a, b, candidate_lines, direction, CAP_ENDPOINT_TOUCH_TOLERANCE_FT):
            continue  # ruido de CAD flutuando no meio do desenho - nao toca nenhuma face

        positions.append(t_cap)

    return positions, axis_length_ft


def clip_centerline_to_caps(centerline, thickness_ft, candidate_lines, openings):
    """Encurta `centerline` para que a parede NUNCA ultrapasse as linhas de
    fechamento (testas) encontradas no mesmo Layer (ver find_cap_positions).

    So' ENCURTA, nunca estica: uma testa e' um limite fisico, entao ela
    manda sobre qualquer prolongamento que create_centerline tenha feito ao
    cobrir a uniao das duas faces. As testas antes do meio do eixo definem
    o inicio; as depois do meio definem o fim; e em cada lado vale a MAIS
    RESTRITIVA (a mais interna), garantindo que nenhuma sobra passe do
    fechamento desenhado.

    Devolve `(nova_centerline, (travado_inicio, travado_fim))`. Os dois
    booleanos marcam as pontas que foram definidas por uma testa real -
    essas pontas ficam CONGELADAS: extend_wall_ends_to_junctions nao pode
    mais estica-las para fechar encontros em T/L, senao a parede voltaria a
    ultrapassar exatamente o limite que o CAD desenhou. Devolve
    `(None, ...)` se o corte nao deixar comprimento util.
    """
    positions, axis_length_ft = find_cap_positions(
        centerline, thickness_ft, candidate_lines, openings
    )
    if not positions:
        return centerline, (False, False)

    p0_raw = centerline.GetEndPoint(0)
    p1_raw = centerline.GetEndPoint(1)
    direction = (XYZ(p1_raw.X, p1_raw.Y, 0.0) - XYZ(p0_raw.X, p0_raw.Y, 0.0)).Normalize()
    midpoint_t = axis_length_ft / 2.0

    t_lo, t_hi = 0.0, axis_length_ft
    locked_lo, locked_hi = False, False
    for t_cap in positions:
        if t_cap <= midpoint_t:
            if t_cap > t_lo:
                t_lo, locked_lo = t_cap, True
        else:
            if t_cap < t_hi:
                t_hi, locked_hi = t_cap, True

    if not (locked_lo or locked_hi):
        return centerline, (False, False)
    if (t_hi - t_lo) < MIN_SEGMENT_LENGTH_FT:
        return None, (locked_lo, locked_hi)

    # `direction` tem Z=0 e a linha e' horizontal, entao somar a partir de
    # `p0_raw` preserva a elevacao original do CAD.
    return (
        Line.CreateBound(p0_raw + direction * t_lo, p0_raw + direction * t_hi),
        (locked_lo, locked_hi)
    )


def find_wall_pairs(lines_to_process, target_thicknesses_ft, tolerance_ft,
                    cap_candidate_lines=None, openings=None, diagnostics=None):
    """Agrupa as linhas do Layer em pares paralelos validos e devolve
    (centerline, espessura_ft) para cada par.

    Um par so' e' aceito se a distancia perpendicular medida entre as duas
    linhas casar (dentro de `tolerance_ft`) com uma das espessuras que o
    usuario escolheu modelar em `target_thicknesses_ft` - QUALQUER outra
    distancia e' ignorada, mesmo que fisicamente pareca uma espessura de
    parede plausivel. Isso e' o que impede: (a) duas linhas de paredes
    diferentes, ou uma linha de parede e uma linha de esquadria/cruzamento,
    de serem interpretadas como uma unica parede com espessura errada/
    excessiva; e (b) uma linha "roubar" o pareamento correto de outra so'
    por estar geometricamente mais perto, quando essa proximidade nao
    corresponde a nenhuma espessura pedida.

    A espessura final gravada para o par e' sempre o valor EXATO escolhido
    pelo usuario (nao a distancia bruta medida) - a tolerancia serve apenas
    para a deteccao.

    Processa por RODADAS: em cada rodada, escolhe entre todos os candidatos
    validos (ainda nao usados) o par MAIS CONFIAVEL - primeiro pela MAIOR
    fracao de sobreposicao mutua (ver lines_overlap_enough/
    MIN_WALL_SEGMENT_OVERLAP_RATIO: as duas faces de uma mesma parede
    cobrem quase 100% uma da outra), so' desempatando pela MENOR distancia
    perpendicular quando a fracao de sobreposicao empata. Isso importa
    especialmente perto de cantos e aberturas, onde varias linhas de
    paredes DIFERENTES ficam a poucos cm umas das outras: escolher so' pela
    menor distancia podia "roubar" a face verdadeira de uma boneca curta
    (sobreposicao quase total, porem a poucos mm de bater com a espessura
    escolhida) em favor de um pareamento parcial/marginal com outra linha
    vizinha cuja distancia batesse por uma fracao de mm mais perto -
    deixando a boneca sem parede. O eixo (centerline) e' calculado a partir
    das duas linhas INTEIRAS - nao ha recorte, aparo ou divisao de nenhuma
    linha, e cada linha e' usada em NO MAXIMO um par (sem redistribuir
    "sobras" para outras rodadas).

    Isso significa que, em encontros em T, L, Cruz (+) ou qualquer outra
    configuracao, as paredes resultantes podem ficar sobrepostas entre si -
    isso e' intencional: a prioridade e' preservar exatamente a geometria e
    o comprimento calculados a partir do CAD, mesmo que isso gere paredes
    que se atravessam ou ocupam a mesma regiao.

    `diagnostics`, se fornecido (dict com as chaves "parallel_pairs",
    "min_dist_ft", "max_dist_ft", "offset_suspect_count" e
    "offset_suspect_max_ft" ja inicializadas pelo chamador), e' preenchido
    com estatisticas dos pares paralelos considerados (mesmo os
    descartados), para permitir diagnosticar por que nenhuma parede foi
    gerada (ex.: linhas paralelas encontradas mas em nenhuma espessura
    escolhida pelo usuario) - e tambem com a contagem/pior caso de eixos
    calculados que falharam na autoverificacao de centralizacao (ver
    _axis_offset_error_ft), para a etapa de validacao final.

    Devolve (walls_to_create, unused_lines): `unused_lines` sao as linhas do
    Layer que NAO entraram em nenhum par (nem como parceira nem como base) -
    apenas para diagnostico (contadas no resumo final). Elas NAO viram
    parede: uma linha sem parceira na espessura escolhida nao e' uma parede
    confirmada, e' descartada deliberadamente para nao desenhar parede em
    cima de linhas de hachura, cota ou qualquer outra linha do Layer que nao
    representa de fato uma parede de 14cm (ou outra espessura escolhida).
    PERFORMANCE: a versao original recalculava o "melhor par restante"
    varrendo TODOS os pares (i, j) ainda nao usados a cada rodada (um par
    aceito por rodada) - ou seja, um Layer com N linhas custava O(N^3) no
    pior caso (a varredura O(N^2) inteira repetida ate' N/2 vezes), o que
    em Layers de CAD tipicos (milhares de linhas) e' o principal motivo do
    script ficar lento logo apos a etapa de aberturas (esta funcao e'
    chamada logo em seguida, com `lines_to_process` do tamanho do Layer
    inteiro). Como o sort_key de cada par so' depende da geometria das
    DUAS linhas dele (nunca do estado de uso de outros pares), calcular
    todos os pares candidatos e' UMA UNICA vez, ordena-los uma vez e
    aceitar greedily na ordem (pulando qualquer par que ja tenha uma ponta
    usada) produz exatamente a mesma sequencia de escolhas que "recalcula
    o melhor par restante a cada rodada" - so' que em O(N^2) no total, em
    vez de O(N^3).
    """
    pending = list(lines_to_process)
    n = len(pending)
    used = [False] * n
    walls_to_create = []

    # Geometria de cada linha calculada UMA UNICA vez (ver PERFORMANCE em
    # _line_geom_cache) - sem isso, are_lines_parallel/
    # get_distance_between_parallel_lines/_line_pair_overlap_ft
    # recalculavam a direcao/comprimento/ponto medio da MESMA linha `i` do
    # zero em cada uma das O(n) comparacoes contra `j`.
    caches = [_line_geom_cache(line) for line in pending]

    # Unica passada O(n^2): reune TODOS os pares geometricamente validos
    # (ver docstring/PERFORMANCE acima) - cada par e' avaliado uma vez so',
    # nunca mais re-testado a cada rodada.
    candidates = []  # (sort_key, i, j, matched_thickness_ft) - sort_key = (-overlap_ratio, dist)
    for i in range(n):
        cache_i = caches[i]
        for j in range(i + 1, n):
            cache_j = caches[j]

            if not _are_parallel_cached(cache_i, cache_j):
                continue

            dist = _distance_between_parallel_cached(cache_i, cache_j)

            if diagnostics is not None:
                diagnostics["parallel_pairs"] += 1
                if diagnostics["min_dist_ft"] is None or dist < diagnostics["min_dist_ft"]:
                    diagnostics["min_dist_ft"] = dist
                if diagnostics["max_dist_ft"] is None or dist > diagnostics["max_dist_ft"]:
                    diagnostics["max_dist_ft"] = dist

            if not (MIN_WALL_THICKNESS_FT <= dist <= MAX_WALL_THICKNESS_FT):
                continue

            matched_thickness = _closest_target_thickness_ft(dist, target_thicknesses_ft, tolerance_ft)
            if matched_thickness is None:
                continue  # distancia nao corresponde a nenhuma espessura escolhida pelo usuario

            overlap_ft, length1, length2 = _line_pair_overlap_ft_cached(cache_i, cache_j)
            if overlap_ft < MIN_WALL_SEGMENT_ABS_FLOOR_FT:
                continue
            shorter_length = min(length1, length2)
            if shorter_length < 1e-9:
                continue
            overlap_ratio = overlap_ft / shorter_length
            if overlap_ratio < MIN_WALL_SEGMENT_OVERLAP_RATIO:
                continue  # paralelas e na espessura certa, mas nao correm lado a lado (nao e' a mesma parede)

            candidates.append(((-overlap_ratio, dist), i, j, matched_thickness))

    # Ordena uma unica vez pelo mesmo sort_key da versao original e aceita
    # greedily, pulando pares que ja tenham uma ponta usada por um par
    # anterior (mais bem colocado no ranking) - equivalente a "recalcula o
    # melhor par restante a cada rodada", ver PERFORMANCE acima.
    candidates.sort(key=lambda c: c[0])

    for _, i, j, matched_thickness in candidates:
        if used[i] or used[j]:
            continue

        centerline = create_centerline(pending[i], pending[j], CENTERLINE_MAX_EXTENSION_FT)
        if centerline:
            # Validacao final (autoverificacao geometrica, ver
            # _axis_offset_error_ft): confirma que o eixo recem-calculado
            # realmente ficou centralizado entre as duas linhas do CAD -
            # alarme precoce para o sintoma de "parede com ~0,5cm de
            # deslocamento" relatado, mesmo que a causa seja outra ainda
            # nao identificada.
            if diagnostics is not None:
                offset_error_ft = _axis_offset_error_ft(centerline, pending[i], pending[j])
                if offset_error_ft > AXIS_OFFSET_WARNING_FT:
                    diagnostics["offset_suspect_count"] += 1
                    diagnostics["offset_suspect_max_ft"] = max(
                        diagnostics["offset_suspect_max_ft"], offset_error_ft
                    )

            # Limita a parede as linhas de FECHAMENTO (testas) desenhadas no
            # mesmo Layer. Isso acontece DEPOIS de create_centerline de
            # proposito: o eixo e' calculado normalmente (cobrindo a uniao
            # das duas faces) e so' entao e' cortado onde o CAD fecha a
            # parede - assim o corte vale sobre qualquer prolongamento
            # geometrico, que e' exatamente o comportamento pedido.
            locked_ends = (False, False)
            if cap_candidate_lines:
                clipped, locked_ends = clip_centerline_to_caps(
                    centerline, matched_thickness, cap_candidate_lines, openings or []
                )
                if clipped is not None and (locked_ends[0] or locked_ends[1]):
                    if diagnostics is not None:
                        diagnostics["cap_clipped_count"] += 1
                centerline = clipped

            if centerline is not None:
                walls_to_create.append((centerline, matched_thickness, locked_ends))

        used[i] = True
        used[j] = True

    unused_lines = [pending[i] for i in range(len(pending)) if not used[i]]
    return walls_to_create, unused_lines


def scan_possible_missed_bonecas(unused_lines):
    """Etapa de validacao final: entre as linhas que NAO formaram par
    valido em nenhuma das espessuras escolhidas pelo usuario
    (`unused_lines`, devolvidas por find_wall_pairs), procura pares que
    MESMO ASSIM parecem, geometricamente, uma parede/boneca legitima -
    paralelas, com distancia dentro da faixa FISICA plausivel de parede
    (MIN_WALL_THICKNESS_FT a MAX_WALL_THICKNESS_FT, SEM restringir as
    espessuras escolhidas pelo usuario) e com sobreposicao suficiente
    (mesmo criterio de MIN_WALL_SEGMENT_OVERLAP_RATIO usado em
    find_wall_pairs).

    Cobre o requisito "nenhuma boneca valida foi ignorada": qualquer par
    assim encontrado e' sinal de uma parede/boneca real desenhada no CAD
    cuja espessura nao bate com nenhuma das escolhidas pelo usuario (ex.:
    o usuario esqueceu de marcar aquela espessura na lista, ou uma boneca
    tem uma espessura ligeiramente diferente da parede principal). NAO cria
    parede nenhuma automaticamente a partir disso (isso ignoraria a escolha
    deliberada do usuario sobre quais espessuras modelar) - so' reporta a
    ocorrencia no resumo final, para o usuario decidir se deve reexecutar
    incluindo essa espessura.

    Devolve uma lista de (dist_cm, overlap_cm) - uma entrada por par
    encontrado (guloso pela maior fracao de sobreposicao, mesmo
    comportamento de find_wall_pairs; cada linha entra em no maximo um
    par aqui).

    PERFORMANCE: mesma reestruturacao de find_wall_pairs (ver o
    PERFORMANCE na docstring de la') - os candidatos sao calculados numa
    unica passada O(n^2) e aceitos greedily numa lista ja ordenada, em vez
    de re-varrer os pares restantes do zero a cada par aceito. A geometria
    de cada linha tambem e' calculada uma unica vez (ver _line_geom_cache)."""
    n = len(unused_lines)
    used = [False] * n
    found = []

    caches = [_line_geom_cache(line) for line in unused_lines]

    candidates = []  # (sort_key, i, j, dist, overlap_ft)
    for i in range(n):
        cache_i = caches[i]
        for j in range(i + 1, n):
            cache_j = caches[j]

            if not _are_parallel_cached(cache_i, cache_j):
                continue
            dist = _distance_between_parallel_cached(cache_i, cache_j)
            if not (MIN_WALL_THICKNESS_FT <= dist <= MAX_WALL_THICKNESS_FT):
                continue

            overlap_ft, length1, length2 = _line_pair_overlap_ft_cached(cache_i, cache_j)
            if overlap_ft < MIN_WALL_SEGMENT_ABS_FLOOR_FT:
                continue
            shorter_length = min(length1, length2)
            if shorter_length < 1e-9:
                continue
            overlap_ratio = overlap_ft / shorter_length
            if overlap_ratio < MIN_WALL_SEGMENT_OVERLAP_RATIO:
                continue

            candidates.append(((-overlap_ratio, dist), i, j, dist, overlap_ft))

    candidates.sort(key=lambda c: c[0])

    for _, i, j, dist, overlap_ft in candidates:
        if used[i] or used[j]:
            continue
        found.append((
            round(dist / FEET_PER_METER * 100.0, 1),
            round(overlap_ft / FEET_PER_METER * 100.0, 1)
        ))
        used[i] = True
        used[j] = True

    return found


def _fmt_line_cm(line):
    """Formata uma linha como coordenadas em cm (arredondadas), para o log
    final apontar exatamente qual linha do CAD corresponde a cada parede
    ignorada - sem isso o usuario nao tem como localizar a linha na planta a
    partir do resumo."""
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)

    def cm(v):
        return round(v / FEET_PER_METER * 100.0)

    return "({:.0f}, {:.0f}) -> ({:.0f}, {:.0f})".format(cm(p0.X), cm(p0.Y), cm(p1.X), cm(p1.Y))


def classify_unused_line_reason(line, all_lines, target_thicknesses_ft, tolerance_ft):
    """Determina o motivo mais provavel pelo qual `line` (uma linha do Layer
    que NAO formou par valido em find_wall_pairs) foi ignorada - comparando-a
    com TODAS as demais linhas do mesmo Layer (nao so' as tambem sem-par),
    ja' que a melhor candidata a parceira dela pode ter sido "roubada" por
    outro par mais confiavel.

    Usado na secao "paredes ignoradas / motivo" do log final (ver
    build_ignored_walls_log e main()).

    IMPORTANTE: o "melhor" candidato e' escolhido por UM UNICO criterio de
    prioridade (matches_thickness > in_physical_range > parallel, com a
    fracao de sobreposicao so' como desempate) e a distancia/sobreposicao
    reportadas na mensagem SEMPRE vem DESSE MESMO candidato - nunca de
    campos calculados independentemente uns dos outros a partir de
    candidatos DIFERENTES (isso produzia mensagens sem sentido, ex.: uma
    distancia de "528cm" citada como "espessura fisica plausivel", vinda de
    um candidato de sobreposicao alta mas totalmente fora da faixa fisica,
    enquanto o flag "in_physical_range" vinha de outro candidato qualquer)."""
    best = None  # (rank_tuple, dist_ft, ratio, in_physical_range, matches_thickness)

    for other in all_lines:
        if other is line:
            continue
        if not are_lines_parallel(line, other):
            continue

        dist = get_distance_between_parallel_lines(line, other)
        overlap_ft, len1, len2 = _line_pair_overlap_ft(line, other)
        shorter = min(len1, len2)
        ratio = (overlap_ft / shorter) if shorter > 1e-9 else 0.0

        in_physical_range = MIN_WALL_THICKNESS_FT <= dist <= MAX_WALL_THICKNESS_FT
        matches_thickness = in_physical_range and _closest_target_thickness_ft(
            dist, target_thicknesses_ft, tolerance_ft
        ) is not None

        rank = (1 if matches_thickness else 0, 1 if in_physical_range else 0, ratio)
        if best is None or rank > best[0]:
            best = (rank, dist, ratio, in_physical_range, matches_thickness)

    if best is None:
        return "nenhuma linha paralela no Layer (hachura, cota, ou face sem par desenhado no CAD)"

    _, best_dist_ft, best_overlap_ratio, best_in_physical_range, best_matches_thickness = best
    best_dist_cm = round(best_dist_ft / FEET_PER_METER * 100.0, 1)

    if not best_in_physical_range:
        return (
            "linha(s) paralela(s) encontrada(s), mas a distancia fica fora da faixa "
            "fisica de espessura de parede ({}-{}cm)"
        ).format(round(MIN_WALL_THICKNESS_M * 100.0, 1), round(MAX_WALL_THICKNESS_M * 100.0, 1))
    if not best_matches_thickness:
        return (
            "linha(s) paralela(s) em espessura fisica plausivel ({}cm), mas fora das "
            "espessuras escolhidas pelo usuario"
        ).format(best_dist_cm)
    if best_overlap_ratio < MIN_WALL_SEGMENT_OVERLAP_RATIO:
        return (
            "linha paralela na espessura certa, mas sobreposicao insuficiente ao longo "
            "do comprimento ({}% - parece cruzamento/coincidencia, nao a mesma parede)"
        ).format(round(best_overlap_ratio * 100.0, 1))
    return (
        "candidata plausivel ({}cm de espessura, {}% de sobreposicao), mas outro par "
        "mais confiavel usou a linha parceira primeiro"
    ).format(best_dist_cm, round(best_overlap_ratio * 100.0, 1))


def _line_2d_intersection(p1, d1, p2, d2):
    """Ponto de intersecao das retas (p1, d1) e (p2, d2) no plano XY
    (ignora Z - assume que ambas estao no mesmo plano/nivel). Devolve None
    se forem paralelas."""
    denom = d1.X * d2.Y - d1.Y * d2.X
    if abs(denom) < 1e-9:
        return None
    dx = p2.X - p1.X
    dy = p2.Y - p1.Y
    t = (dx * d2.Y - dy * d2.X) / denom
    return p1 + d1 * t


def extend_wall_ends_to_junctions(walls_to_create, search_range_ft):
    """Fecha encontros em T/L entre paredes, ESTICANDO a ponta de uma parede
    ate' a FACE OPOSTA da parede perpendicular com a qual ela se encontra -
    nao apenas ate' o EIXO dessa parede vizinha.

    Devolve (novo_walls_to_create, junction_map). `junction_map` e' um
    dict {(wall_idx, end_index): {"neighbor_idx", "point", "hit_t_on_neighbor",
    "neighbor_length_ft"}} - UM registro por ponta que foi de fato esticada
    aqui, guardando com QUAL parede vizinha ela se encontrou e ONDE ao
    longo do eixo dela (`hit_t_on_neighbor`, em pe' desde o inicio da
    vizinha) isso aconteceu. E' a mesma informacao que esta funcao ja'
    calculava internamente (a variavel `hit`) e descartava depois de usar
    so' para a geometria - captura-la aqui e' o que permite ao
    build_wall_graph (logo abaixo) montar o grafo L/T/X sem refazer esta
    busca geometrica do zero (reuso pedido explicitamente na especificacao
    de modulacao por blocos, em vez de uma segunda implementacao paralela
    que podia divergir desta).

    Parar exatamente no eixo da parede perpendicular deixa uma fresta aberta
    do tamanho de metade da espessura dela (o encontro nao fecha
    completamente, e' visivel um vao). Esticar so' ate' ali (como a versao
    anterior desta funcao fazia) e' insuficiente: e' preciso atravessar toda
    a espessura da parede perpendicular para o encontro ficar fechado, com
    uma pequena sobreposicao geometrica entre as duas - exatamente como uma
    parede real construida encontra outra.

    Para cada ponta de cada parede, procura a parede perpendicular mais
    proxima cujo EIXO cruze o prolongamento dessa ponta dentro de
    `search_range_ft` (busca simetrica: tanto faz se a ponta ja passou um
    pouco do eixo ou ainda esta um pouco antes dele - so' importa estar
    perto o bastante para ser um encontro real, nao uma parede que apenas
    passa longe dali). O novo ponto final e' o eixo da parede vizinha,
    empurrado mais para frente por METADE da espessura DELA - ou seja, a
    face oposta, do lado de onde esta parede esta chegando.

    So' ESTICA (nunca encurta) - se a ponta ja alcanca ou ultrapassa essa
    face oposta, nada muda.
    """
    lines = [pair[0] for pair in walls_to_create]
    thicknesses = [pair[1] for pair in walls_to_create]
    locks = [pair[2] for pair in walls_to_create]
    n = len(lines)
    junction_map = {}

    for idx in range(n):
        line = lines[idx]
        for end_index in (0, 1):
            # Ponta definida por uma linha de FECHAMENTO real do CAD (ver
            # clip_centerline_to_caps): e' um limite fisico da parede, entao
            # NAO pode ser esticada para fechar um encontro em T/L - isso
            # faria a parede ultrapassar exatamente o ponto onde o desenho
            # diz que ela acaba. Fechar a fresta nesse encontro, se houver,
            # e' responsabilidade da parede que CHEGA ali, nao desta.
            if locks[idx][end_index]:
                continue

            p_end = line.GetEndPoint(end_index)
            p_far = line.GetEndPoint(1 - end_index)
            direction = (p_end - p_far).Normalize()

            best_final_point = None
            best_final_t = None
            best_neighbor_idx = None
            best_hit_s = None
            best_neighbor_len = None
            for k in range(n):
                if k == idx:
                    continue
                other = lines[k]
                if are_lines_parallel(line, other):
                    continue  # paralelas nao formam encontro em T/L aqui

                o_p0 = other.GetEndPoint(0)
                o_p1 = other.GetEndPoint(1)
                o_dir = (o_p1 - o_p0).Normalize()

                hit = _line_2d_intersection(p_end, direction, o_p0, o_dir)
                if hit is None:
                    continue

                t = (hit - p_end).DotProduct(direction)
                if abs(t) > search_range_ft:
                    continue  # eixo da outra parede longe demais desta ponta - nao e' este encontro

                # O ponto de encontro precisa cair dentro do trecho real da
                # OUTRA parede (com folga de meia-espessura dela em cada
                # lado, ja que o encontro pode acontecer perto da propria
                # ponta dela) - senao nao ha nada ali para se conectar.
                other_thickness_ft = thicknesses[k]
                o_len = o_p0.DistanceTo(o_p1)
                s = (hit - o_p0).DotProduct(o_dir)
                margin = other_thickness_ft / 2.0
                if s < -margin or s > o_len + margin:
                    continue

                # Ponto final: atravessa o eixo da parede vizinha e chega na
                # face OPOSTA dela (mais meia-espessura dela na mesma
                # direcao de avanco desta ponta).
                final_point = hit + direction * margin
                final_t = (final_point - p_end).DotProduct(direction)
                if final_t <= 1e-6:
                    continue  # face oposta fica atras (ou exatamente) da ponta atual - nada a esticar

                if best_final_t is None or final_t < best_final_t:
                    best_final_t = final_t
                    best_final_point = final_point
                    best_neighbor_idx = k
                    best_hit_s = s
                    best_neighbor_len = o_len

            if best_final_point is not None:
                if end_index == 0:
                    line = Line.CreateBound(best_final_point, p_far)
                else:
                    line = Line.CreateBound(p_far, best_final_point)
                lines[idx] = line
                junction_map[(idx, end_index)] = {
                    "neighbor_idx": best_neighbor_idx,
                    "point": best_final_point,
                    "hit_t_on_neighbor": best_hit_s,
                    "neighbor_length_ft": best_neighbor_len,
                }

    return [(lines[i], thicknesses[i], locks[i]) for i in range(n)], junction_map


# ==========================================
# ETAPA 2 - GRAFO DE PAREDES E CLASSIFICACAO DE NOS (WallNode)
#
# Classifica cada ENCONTRO entre paredes (nao cada parede isolada) em
# FREE_END / STRAIGHT_CONTINUATION / L_CORNER / T_INTERSECTION /
# X_INTERSECTION / AMBIGUOUS - base para o solver de blocos da Etapa 4
# decidir onde entram B34 (L), B54 (T/X) e onde e' so' preenchimento comum.
#
# Reusa DELIBERADAMENTE o calculo que extend_wall_ends_to_junctions ja' fez
# (ver `junction_map`, devolvido por ela) em vez de reimplementar a busca
# geometrica - evita duas fontes de verdade que podiam divergir sobre "que
# paredes se encontram aqui".
#
# NAO DEPENDE do sentido em que cada parede foi desenhada no CAD (A->B ou
# B->A): cada ponta e' tratada pelo seu proprio end_index (0 ou 1), nunca
# pela identidade global "inicio/fim" da parede - a mesma dupla de paredes
# produz o mesmo no' nao importa qual delas foi desenhada em qual sentido.
# ==========================================

WALL_GRAPH_NODE_SNAP_TOLERANCE_M = 0.05
WALL_GRAPH_NODE_SNAP_TOLERANCE_FT = WALL_GRAPH_NODE_SNAP_TOLERANCE_M * FEET_PER_METER

# Mesma ordem de grandeza de RECTANGLE_PERPENDICULAR_TOLERANCE/
# are_lines_parallel (produto escalar de vetores UNITARIOS, nao angulo em
# graus) - definida aqui de novo (em vez de importar a de mais adiante no
# arquivo) para esta secao ficar autocontida.
WALL_GRAPH_PERPENDICULAR_TOLERANCE = 0.05
WALL_GRAPH_COLLINEAR_TOLERANCE = 0.05


def _wall_node_arms(walls_to_create, junction_map=None):
    """Uma entrada por PONTA de parede (2 por parede): {"wall_idx",
    "end_index", "point" (XYZ, Z=0), "anchor" (XYZ, Z=0), "outward_dir"
    (XYZ unitario, Z=0, apontando do no' PARA DENTRO da propria parede - ou
    seja, em direcao a' outra ponta dela)}. `outward_dir` e' o que permite
    comparar angulos entre pontas de paredes DIFERENTES que se encontram no
    mesmo no', independente de qual extremidade (0 ou 1) cada uma usa.

    `anchor` e' o PONTO FISICO DO ENCONTRO, e e' ele (nao `point`) que
    agrupa as pontas em nos - ver _cluster_wall_arms. A distincao existe
    porque extend_wall_ends_to_junctions (que roda ANTES desta funcao no
    fluxo do main) PUXA cada ponta ate' a face oposta da parede vizinha
    para fechar o encontro: num canto em L de duas paredes de 14cm, a ponta
    de uma fica em (-7, 0) e a da outra em (0, -7) - 9,9cm de distancia,
    MUITO alem da tolerancia de agrupamento (5cm). Agrupando por `point`,
    o MESMO canto virava DOIS nos L_CORNER independentes (cada um citando o
    outro como vizinho), o solver da Etapa 4 resolvia o canto DUAS vezes e
    as pecas duplicadas colidiam; uma cruz (4 pontas) nem chegava a ser
    reconhecida como X - virava quatro L_CORNER soltos. Ancorando na
    INTERSECAO DOS DOIS EIXOS (o canto de verdade, (0,0) no exemplo), as
    pontas voltam a cair no mesmo lugar e cada encontro fisico volta a ser
    um unico no'.

    Pontas sem vizinha conhecida (ponta livre, ou travada por testa e
    portanto ausente de `junction_map`) ancoram no proprio ponto."""
    junction_map = junction_map or {}
    arms = []
    for wall_idx, (centerline, _thickness_ft, _locks) in enumerate(walls_to_create):
        p0 = centerline.GetEndPoint(0)
        p1 = centerline.GetEndPoint(1)
        for end_index, (p_end, p_far) in enumerate(((p0, p1), (p1, p0))):
            point = XYZ(p_end.X, p_end.Y, 0.0)
            far = XYZ(p_far.X, p_far.Y, 0.0)
            vec = far - point
            length = vec.GetLength()
            if length < 1e-9:
                continue
            direction = vec.Normalize()
            arms.append({
                "wall_idx": wall_idx,
                "end_index": end_index,
                "point": point,
                "anchor": _wall_end_junction_anchor(
                    walls_to_create, wall_idx, end_index, point, direction, junction_map
                ),
                "outward_dir": direction,
            })
    return arms


def _wall_end_geometric_anchor(walls_to_create, wall_idx, end_index, point, direction):
    """Ancoragem de ponta procurando a parede vizinha pela GEOMETRIA, para
    quando `junction_map` nao registrou nada nesta ponta (ver o fallback em
    _wall_end_junction_anchor).

    Aceita a vizinha mais PROXIMA que satisfaca as tres condicoes, todas
    necessarias para nao inventar encontro onde nao ha':
      1. nao ser paralela a esta parede;
      2. o cruzamento dos dois eixos cair a no maximo meia espessura das
         duas somada (+ tolerancia de agrupamento) da ponta - o mesmo teto
         que o caminho normal ja' usa;
      3. o cruzamento cair DENTRO do segmento da vizinha (com meia espessura
         desta de folga nas pontas dela) - senao os eixos so' se cruzariam
         num prolongamento imaginario.
    Sem vizinha que sirva, devolve o proprio ponto (ponta livre de verdade)."""
    own_curve, own_thickness, _own_locks = walls_to_create[wall_idx]
    best_point = None
    best_dist = None
    for other_idx in range(len(walls_to_create)):
        if other_idx == wall_idx:
            continue
        other_curve, other_thickness, _other_locks = walls_to_create[other_idx]
        if are_lines_parallel(own_curve, other_curve):
            continue
        o0 = other_curve.GetEndPoint(0)
        o1 = other_curve.GetEndPoint(1)
        o0_flat = XYZ(o0.X, o0.Y, 0.0)
        vec = XYZ(o1.X - o0.X, o1.Y - o0.Y, 0.0)
        other_len = vec.GetLength()
        if other_len < 1e-9:
            continue
        crossing = _line_2d_intersection(point, direction, o0_flat, vec.Normalize())
        if crossing is None:
            continue
        distance = crossing.DistanceTo(point)
        max_pull_ft = ((own_thickness + other_thickness) / 2.0
                       + WALL_GRAPH_NODE_SNAP_TOLERANCE_FT)
        if distance > max_pull_ft:
            continue
        t_other = (crossing - o0_flat).DotProduct(vec.Normalize())
        margin_ft = own_thickness / 2.0 + WALL_GRAPH_NODE_SNAP_TOLERANCE_FT
        if t_other < -margin_ft or t_other > other_len + margin_ft:
            continue
        if best_dist is None or distance < best_dist:
            best_dist = distance
            best_point = XYZ(crossing.X, crossing.Y, 0.0)
    return best_point if best_point is not None else point


def _wall_end_junction_anchor(walls_to_create, wall_idx, end_index, point, direction,
                              junction_map):
    """Ponto fisico do encontro em que a ponta (`wall_idx`, `end_index`)
    esta' - a INTERSECAO do eixo desta parede com o eixo da vizinha que
    `junction_map` (devolvido por extend_wall_ends_to_junctions) registrou
    para esta ponta. Devolve o proprio `point` quando nao ha' vizinha
    registrada, quando os eixos sao paralelos, ou quando a intersecao cai
    absurdamente longe da ponta (mais de meia espessura das duas paredes
    somada + a tolerancia de agrupamento) - nesse caso a intersecao nao
    descreve este encontro e seguir com ela agruparia coisas erradas."""
    entry = junction_map.get((wall_idx, end_index))
    if entry is None:
        # FALLBACK GEOMETRICO (2026-08-21). `junction_map` so' tem as pontas
        # que extend_wall_ends_to_junctions precisou ESTICAR. Quando o CAD ja'
        # foi desenhado com as duas paredes passando uma pela outra, nao ha'
        # nada a esticar - a ponta fica fora do mapa, ancora nela mesma, e um
        # canto em L de 14cm vira DOIS nos FREE_END a 9,9cm um do outro
        # (7,7 em cada eixo). Consequencia medida na planta real: as duas
        # paredes nao reservam nada uma para a outra, o preenchimento das
        # duas nasce por cima do cruzamento, e o resultado sao 77 das 118
        # colisoes STANDARD_FILL x STANDARD_FILL. Procurar a vizinha pela
        # GEOMETRIA fecha esse buraco sem depender do mapa.
        return _wall_end_geometric_anchor(walls_to_create, wall_idx, end_index,
                                          point, direction)
    neighbor_idx = entry.get("neighbor_idx")
    if neighbor_idx is None or not (0 <= neighbor_idx < len(walls_to_create)):
        return point
    neighbor_curve = walls_to_create[neighbor_idx][0]
    n0 = neighbor_curve.GetEndPoint(0)
    n1 = neighbor_curve.GetEndPoint(1)
    neighbor_dir = XYZ(n1.X - n0.X, n1.Y - n0.Y, 0.0)
    if neighbor_dir.GetLength() < 1e-9:
        return point
    crossing = _line_2d_intersection(
        point, direction, XYZ(n0.X, n0.Y, 0.0), neighbor_dir.Normalize()
    )
    if crossing is None:
        return point
    max_pull_ft = (
        (walls_to_create[wall_idx][1] + walls_to_create[neighbor_idx][1]) / 2.0
        + WALL_GRAPH_NODE_SNAP_TOLERANCE_FT
    )
    if crossing.DistanceTo(point) > max_pull_ft:
        return point
    return XYZ(crossing.X, crossing.Y, 0.0)


def _cluster_wall_arms(arms, tolerance_ft):
    """Agrupa `arms` (ver _wall_node_arms) cujos pontos caem a `tolerance_ft`
    um do outro - CADA GRUPO e' um NO' fisico (ponta(s) de parede que se
    encontram no mesmo lugar). Algoritmo guloso O(n^2): para ~600 pontas
    (308 paredes) e' rapido o bastante e nao vale a complexidade extra de
    um indice espacial (mesma decisao ja tomada em outras partes do
    arquivo, ver secao DESEMPENHO do prompt de especificacao)."""
    clusters = []
    used = [False] * len(arms)
    for i, arm in enumerate(arms):
        if used[i]:
            continue
        group = [arm]
        used[i] = True
        for j in range(i + 1, len(arms)):
            if used[j]:
                continue
            # Agrupa pelo ANCORA (ponto fisico do encontro), nao pela ponta
            # em si - ver _wall_node_arms para o porque.
            if arm["anchor"].DistanceTo(arms[j]["anchor"]) <= tolerance_ft:
                group.append(arms[j])
                used[j] = True
        clusters.append(group)
    return clusters


def _classify_point_along_wall(s, neighbor_len, neighbor_thickness_ft, tolerance_ft):
    """Dado que uma ponta encosta na parede `neighbor` no parametro `s`
    (pe' desde o inicio dela), devolve (kind, neighbor_end_index):
      - ("L_CORNER", 0 ou 1) se isso acontece perto de UMA DAS PONTAS de
        `neighbor` (dentro de meia-espessura dela - a vizinha "termina"
        ali tambem; `neighbor_end_index` diz QUAL das duas pontas dela,
        necessario na Etapa 3 para saber qual extremidade da vizinha
        precisa se mover junto se o eixo desta parede for esticado/
        encurtado);
      - ("T_INTERSECTION", None) se acontece no MEIO do vao dela (a
        vizinha continua reta para os dois lados - nao ha' ponta dela
        para mover, o T se fecha sozinho enquanto o encontro continuar
        dentro do vao);
      - (None, None) se `s`/`neighbor_len` nao dao para decidir."""
    if s is None or neighbor_len is None:
        return None, None
    near_start = s <= neighbor_thickness_ft / 2.0 + tolerance_ft
    near_end = s >= neighbor_len - neighbor_thickness_ft / 2.0 - tolerance_ft
    if near_start:
        return "L_CORNER", 0
    if near_end:
        return "L_CORNER", 1
    return "T_INTERSECTION", None


def _find_wall_touching_point(point, walls_to_create, exclude_idx, tolerance_ft):
    """Busca geometrica DIRETA (mesma nocao de _point_near_any_wall, usada
    em outra parte do arquivo para trechos suspeitos) por uma parede cujo
    SEGMENTO passa a `tolerance_ft` ou menos de `point`. Devolve
    (wall_idx, s, length_ft, thickness_ft) da mais proxima encontrada, ou
    None se nenhuma.

    Existe porque `junction_map` (de extend_wall_ends_to_junctions) SO'
    registra pontas que precisaram ser ESTICADAS - uma ponta TRAVADA
    (`locked_ends` - ja' encosta exatamente onde uma testa real do CAD diz
    que ela para, tipico de um T onde a parede que chega ja' e' desenhada
    parando na face da parede principal) nunca passa por ali, mas pode
    MUITO bem estar encostando no meio de outra parede - confirmado
    empiricamente: numa grade sintetica de teste, 56 pontas travadas que
    geometricamente tocavam outra parede estavam sendo classificadas como
    FREE_END so' porque a extensao nunca as tocou. Esta busca cobre esse
    caso, sem depender de extensao nenhuma ter acontecido."""
    best = None
    for idx, (line, thickness_ft, _locks) in enumerate(walls_to_create):
        if idx == exclude_idx:
            continue
        p0_raw = line.GetEndPoint(0)
        p1_raw = line.GetEndPoint(1)
        p0 = XYZ(p0_raw.X, p0_raw.Y, 0.0)
        p1 = XYZ(p1_raw.X, p1_raw.Y, 0.0)
        seg = p1 - p0
        seg_len = seg.GetLength()
        if seg_len < 1e-9:
            continue
        seg_dir = seg.Normalize()
        s = (point - p0).DotProduct(seg_dir)
        s_clamped = max(0.0, min(seg_len, s))
        closest = p0 + seg_dir * s_clamped
        distance = point.DistanceTo(closest)
        if distance > tolerance_ft:
            continue
        if best is None or distance < best[4]:
            best = (idx, s_clamped, seg_len, thickness_ft, distance)
    if best is None:
        return None
    idx, s, seg_len, thickness_ft, _distance = best
    return idx, s, seg_len, thickness_ft


def _classify_wall_node(group, junction_map, walls_to_create, tolerance_ft):
    """Classifica UM no' (grupo de pontas que se encontram no mesmo ponto -
    ver _cluster_wall_arms). Devolve um dict WallNode:
        {"point", "kind", "arms": [(wall_idx, end_index), ...],
         "main_wall_idx", "incoming_wall_idx",
         "neighbor_wall_idx", "neighbor_end_index"}
    `main_wall_idx`/`incoming_wall_idx` so' fazem sentido para
    T_INTERSECTION; `neighbor_wall_idx`/`neighbor_end_index` sao
    preenchidos para L_CORNER (as duas variantes, de uma ponta so' ou de
    duas agrupadas) - a outra parede do canto E qual extremidade DELA esta'
    neste no', necessario na Etapa 3 para mover a parede vizinha junto se o
    eixo desta for esticado/encurtado, e na Etapa 4 para o par de B34.
    Ficam `None` quando nao se aplicam.

    `kind` e' um dos: FREE_END, STRAIGHT_CONTINUATION, L_CORNER,
    T_INTERSECTION, X_INTERSECTION, AMBIGUOUS."""
    # O ponto do no' e' o ANCORA (intersecao dos eixos = o encontro fisico),
    # nao a ponta puxada por extend_wall_ends_to_junctions - ver
    # _wall_node_arms. E' esse ponto que o solver da Etapa 4 usa para
    # encostar a celula de amarracao das pecas (B34 no L, B54 no T/X), entao
    # usar a ponta puxada deslocava a peca em meia espessura de parede.
    point = group[0].get("anchor") or group[0]["point"]
    arm_ids = [(a["wall_idx"], a["end_index"]) for a in group]
    node = {
        "point": point, "arms": arm_ids,
        # Ponto PROPRIO de cada ponta (onde extend_wall_ends_to_junctions
        # deixou a extremidade dela, tipicamente na face oposta da parede
        # vizinha). E' o ponto de CONTATO das pecas assimetricas de
        # amarracao - ver _node_contact_point_for_wall.
        "arm_points": dict(
            ((a["wall_idx"], a["end_index"]), a["point"]) for a in group
        ),
        "main_wall_idx": None, "incoming_wall_idx": None,
        "neighbor_wall_idx": None, "neighbor_end_index": None,
        "crossing_walls": None,
    }

    if len(group) == 1:
        arm = group[0]
        entry = junction_map.get((arm["wall_idx"], arm["end_index"]))
        if entry is not None:
            neighbor_idx = entry["neighbor_idx"]
            s = entry["hit_t_on_neighbor"]
            neighbor_len = entry["neighbor_length_ft"]
            neighbor_thickness_ft = (
                walls_to_create[neighbor_idx][1] if neighbor_idx is not None else 0.0
            )
        else:
            # Sem registro em junction_map (tipicamente uma ponta TRAVADA,
            # que extend_wall_ends_to_junctions nunca tenta esticar - ver
            # _find_wall_touching_point acima) - procura diretamente na
            # geometria se esta ponta encosta em alguma outra parede mesmo
            # assim, antes de desistir e declarar FREE_END.
            found = _find_wall_touching_point(
                point, walls_to_create, arm["wall_idx"], tolerance_ft
            )
            if found is None:
                node["kind"] = "FREE_END"
                return node
            neighbor_idx, s, neighbor_len, neighbor_thickness_ft = found

        kind, neighbor_end_index = _classify_point_along_wall(
            s, neighbor_len, neighbor_thickness_ft, tolerance_ft
        )
        if kind is None:
            node["kind"] = "FREE_END"
        elif kind == "L_CORNER":
            node["kind"] = "L_CORNER"
            node["neighbor_wall_idx"] = neighbor_idx
            node["neighbor_end_index"] = neighbor_end_index
        else:
            node["kind"] = "T_INTERSECTION"
            node["main_wall_idx"] = neighbor_idx
            node["incoming_wall_idx"] = arm["wall_idx"]
        return node

    dirs = [a["outward_dir"] for a in group]

    if len(group) == 2:
        dot = dirs[0].DotProduct(dirs[1])
        if dot <= -1.0 + WALL_GRAPH_COLLINEAR_TOLERANCE:
            node["kind"] = "STRAIGHT_CONTINUATION"
        elif abs(dot) <= WALL_GRAPH_PERPENDICULAR_TOLERANCE:
            node["kind"] = "L_CORNER"
            # As duas pontas coincidiram no mesmo cluster - cada parede e'
            # a "vizinha" da outra (relacao simetrica, ao contrario do
            # ramo de UMA ponta so' acima). `neighbor_wall_idx`/
            # `neighbor_end_index` guardados aqui sao do ponto de vista de
            # arm_ids[0] (a Etapa 3 sempre sabe qual das duas e' "a sua"
            # ao consultar via wall_end_to_node[(wall_idx, end_index)]).
            node["neighbor_wall_idx"] = arm_ids[1][0]
            node["neighbor_end_index"] = arm_ids[1][1]
        else:
            node["kind"] = "AMBIGUOUS"
        return node

    if len(group) == 3:
        # Um T em que a parede CONTINUA tambem esta' quebrada em duas
        # paredes que terminam aqui (muito comum quando o CAD desenha cada
        # trecho separado): duas pontas colineares opostas + uma terceira
        # perpendicular a elas. Sem este ramo o no' caia em AMBIGUOUS e o
        # encontro ficava sem amarracao nenhuma.
        for third in range(3):
            a, b = [i for i in range(3) if i != third]
            if dirs[a].DotProduct(dirs[b]) > -1.0 + WALL_GRAPH_COLLINEAR_TOLERANCE:
                continue
            if abs(dirs[a].DotProduct(dirs[third])) > WALL_GRAPH_PERPENDICULAR_TOLERANCE:
                continue
            node["kind"] = "T_INTERSECTION"
            node["main_wall_idx"] = arm_ids[a][0]
            node["incoming_wall_idx"] = arm_ids[third][0]
            node["neighbor_wall_idx"] = arm_ids[b][0]
            return node
        node["kind"] = "AMBIGUOUS"
        return node

    if len(group) == 4:
        # Cruz: as 4 pontas devem formar DOIS pares colineares (cada par
        # apontando em sentidos opostos), os dois pares entre si
        # perpendiculares - a mesma nocao geometrica de "retangulo", aqui
        # aplicada a direcoes em vez de lados.
        pairs = []
        remaining = list(range(4))
        ok = True
        while remaining:
            i = remaining.pop(0)
            best_j, best_dot = None, None
            for j in remaining:
                dot = dirs[i].DotProduct(dirs[j])
                if best_dot is None or dot < best_dot:
                    best_dot = dot
                    best_j = j
            if best_j is None or best_dot > -1.0 + WALL_GRAPH_COLLINEAR_TOLERANCE:
                ok = False
                break
            pairs.append((i, best_j))
            remaining.remove(best_j)
        if ok and len(pairs) == 2:
            cross_dot = dirs[pairs[0][0]].DotProduct(dirs[pairs[1][0]])
            if abs(cross_dot) <= WALL_GRAPH_PERPENDICULAR_TOLERANCE:
                node["kind"] = "X_INTERSECTION"
                # Um representante de cada par colinear - as duas paredes
                # que a Etapa 4 (XIntersectionSolver) precisa para orientar
                # os dois B54 (ver solve_x_intersection). Como as 4 pontas
                # coincidem exatamente aqui, qualquer parede de um par serve
                # (a direcao e' a mesma dos dois lados do par).
                node["crossing_walls"] = (
                    arm_ids[pairs[0][0]][0], arm_ids[pairs[1][0]][0]
                )
                return node
        node["kind"] = "AMBIGUOUS"
        return node

    node["kind"] = "AMBIGUOUS"
    return node


def _find_wall_midspan_crossings(walls_to_create, tolerance_ft):
    """Encontra cruzamentos em X ENTRE PAREDES CONTINUAS - o caso em que
    NENHUMA das duas paredes termina no cruzamento, as duas atravessam
    inteiras (o eixo de uma corta o MEIO do vao da outra, longe das pontas
    das duas). Este e' o formato real de uma cruz neste projeto: como
    `merge_collinear_fragments`/`find_wall_pairs` ja' reconstroem cada
    parede como um trecho reto continuo a partir dos fragmentos do CAD, uma
    cruz normalmente e' representada por DUAS paredes inteiras se cortando
    no meio - nao por 4 pontas de parede se encontrando (esse e' o caso que
    _wall_node_arms/_cluster_wall_arms ja' cobrem, e que NAO detecta este
    aqui: confirmado testando uma cruz sintetica de 2 paredes continuas,
    que sem esta funcao classificava as 4 pontas distantes como FREE_END,
    perdendo o cruzamento por completo).

    Devolve lista de {"wall_a", "wall_b", "point"} - um por cruzamento
    encontrado, com `margem` suficiente das pontas de AMBAS as paredes
    (meia espessura da OUTRA parede + `tolerance_ft`) para nao se
    confundir com um encontro de ponta que build_wall_graph ja' resolveu
    pelo caminho normal."""
    crossings = []
    n = len(walls_to_create)
    for i in range(n):
        line_i, thickness_i, _locks_i = walls_to_create[i]
        p0i = line_i.GetEndPoint(0)
        p1i = line_i.GetEndPoint(1)
        flat_p0i = XYZ(p0i.X, p0i.Y, 0.0)
        dir_i = (XYZ(p1i.X, p1i.Y, 0.0) - flat_p0i)
        len_i = dir_i.GetLength()
        if len_i < 1e-9:
            continue
        dir_i = dir_i.Normalize()

        for j in range(i + 1, n):
            line_j, thickness_j, _locks_j = walls_to_create[j]
            if are_lines_parallel(line_i, line_j):
                continue
            p0j = line_j.GetEndPoint(0)
            p1j = line_j.GetEndPoint(1)
            flat_p0j = XYZ(p0j.X, p0j.Y, 0.0)
            dir_j = (XYZ(p1j.X, p1j.Y, 0.0) - flat_p0j)
            len_j = dir_j.GetLength()
            if len_j < 1e-9:
                continue
            dir_j = dir_j.Normalize()

            hit = _line_2d_intersection(flat_p0i, dir_i, flat_p0j, dir_j)
            if hit is None:
                continue

            t_i = (hit - flat_p0i).DotProduct(dir_i)
            t_j = (hit - flat_p0j).DotProduct(dir_j)
            margin_i = thickness_j / 2.0 + tolerance_ft
            margin_j = thickness_i / 2.0 + tolerance_ft
            if not (margin_i <= t_i <= len_i - margin_i):
                continue
            if not (margin_j <= t_j <= len_j - margin_j):
                continue

            crossings.append({"wall_a": i, "wall_b": j, "point": hit})
    return crossings


def build_wall_graph(walls_to_create, junction_map,
                     tolerance_ft=WALL_GRAPH_NODE_SNAP_TOLERANCE_FT):
    """Constroi o grafo de encontros entre paredes (ver cabecalho da secao
    ETAPA 2 acima). Devolve (nodes, end_to_node):
      - `nodes`: lista de WallNode (ver _classify_wall_node), incluindo os
        nos X_INTERSECTION vindos de _find_wall_midspan_crossings (esses
        tem `arms=[]` - nenhuma parede TERMINA ali - e a identidade das
        duas paredes fica em `crossing_walls`);
      - `end_to_node`: dict {(wall_idx, end_index): indice_em_nodes} - para
        as proximas etapas perguntarem rapido "em que no' esta esta ponta"
        (so' cobre nos com ponta de verdade - os X de meio-de-parede nao
        entram aqui, ja' que nao ha' end_index para eles).
    """
    arms = _wall_node_arms(walls_to_create, junction_map)
    clusters = _cluster_wall_arms(arms, tolerance_ft)

    nodes = []
    end_to_node = {}
    for group in clusters:
        node = _classify_wall_node(group, junction_map, walls_to_create, tolerance_ft)
        node_index = len(nodes)
        nodes.append(node)
        for wall_idx, end_index in node["arms"]:
            end_to_node[(wall_idx, end_index)] = node_index

    for crossing in _find_wall_midspan_crossings(walls_to_create, tolerance_ft):
        nodes.append({
            "point": crossing["point"],
            "kind": "X_INTERSECTION",
            "arms": [],
            "main_wall_idx": None,
            "incoming_wall_idx": None,
            "neighbor_wall_idx": None,
            "crossing_walls": (crossing["wall_a"], crossing["wall_b"]),
        })

    return nodes, end_to_node


def build_plan_bounds(lines, margin_ft):
    """Calcula a caixa envolvente (bounding box, plano XY) de todas as
    linhas do Layer selecionado, com uma margem extra, para servir de
    referencia na validacao final (detectar paredes criadas fora dos
    limites reais desenhados na planta)."""
    xs, ys = [], []
    for line in lines:
        for idx in (0, 1):
            p = line.GetEndPoint(idx)
            xs.append(p.X)
            ys.append(p.Y)
    return (min(xs) - margin_ft, max(xs) + margin_ft, min(ys) - margin_ft, max(ys) + margin_ft)


def deduplicate_walls(walls_to_create):
    """Remove paredes DUPLICADAS da lista final: mesma espessura (dentro de
    WALL_THICKNESS_MATCH_TOLERANCE_FT), eixos praticamente colineares
    (paralelos e com deslocamento perpendicular <= DUPLICATE_AXIS_TOLERANCE_FT
    - uma tolerancia SEPARADA e mais generosa que a de merge_collinear_fragments,
    ver a nota nessa constante) e com sobreposicao real ao longo do
    comprimento. Mantem apenas a MAIS LONGA de cada grupo duplicado.

    Cobre o caso do CAD ter mais de duas linhas paralelas e proximas
    representando a MESMA parede (ex.: contorno + linha de hachura/cota
    duplicada no mesmo Layer) - sem este filtro, tanto o pareamento normal
    quanto a recuperacao de linhas sem par podiam gerar mais de uma parede
    sobreposta na mesma posicao (visivel como "fatias" de parede empilhadas
    num canto)."""
    # Mais longa primeiro, para preferir manter a parede mais completa de
    # cada grupo duplicado.
    ordered = sorted(
        walls_to_create,
        key=lambda w: -w[0].GetEndPoint(0).DistanceTo(w[0].GetEndPoint(1))
    )

    kept = []
    removed_count = 0
    for line, thickness_ft, locked_ends in ordered:
        is_duplicate = False
        for kept_line, kept_thickness, _kept_locked in kept:
            if abs(thickness_ft - kept_thickness) > WALL_THICKNESS_MATCH_TOLERANCE_FT:
                continue
            if not are_lines_parallel(line, kept_line):
                continue
            if get_distance_between_parallel_lines(line, kept_line) > DUPLICATE_AXIS_TOLERANCE_FT:
                continue
            if not lines_overlap_enough(line, kept_line):
                continue
            is_duplicate = True
            break
        if is_duplicate:
            removed_count += 1
        else:
            kept.append((line, thickness_ft, locked_ends))

    return kept, removed_count


def build_no_pairs_message(layer_name, total_lines, diagnostics, target_thicknesses_ft, tolerance_ft):
    """Monta uma mensagem explicando POR QUE nenhum par de paredes foi
    formado, com base nas estatisticas coletadas em find_wall_pairs().

    Sem isso, o alerta generico ("nenhum par valido encontrado") nao
    distingue entre: (a) nenhuma linha e' paralela a outra, (b) ha linhas
    paralelas mas a distancia entre elas fica fora da faixa aceita de
    espessura (5-35 cm) - o que costuma indicar escala/unidade do CAD
    incorreta no import/vinculo, (c) linhas duplicadas/coincidentes
    (distancia ~0), ou (d) ha linhas paralelas em espessura de parede
    plausivel mas que nao corresponde a NENHUMA das espessuras escolhidas
    pelo usuario.
    """
    msg = "Layer '{}': {} linha(s) encontrada(s).\n".format(layer_name, total_lines)

    if diagnostics["parallel_pairs"] == 0:
        msg += (
            "Nenhum par de linhas paralelas foi detectado (tolerancia de "
            "paralelismo pode estar muito rigorosa, ou as linhas do CAD nao "
            "sao realmente paralelas entre si)."
        )
        return msg

    min_cm = round(diagnostics["min_dist_ft"] / FEET_PER_METER * 100.0, 1)
    max_cm = round(diagnostics["max_dist_ft"] / FEET_PER_METER * 100.0, 1)
    min_accepted_cm = round(MIN_WALL_THICKNESS_M * 100.0, 1)
    max_accepted_cm = round(MAX_WALL_THICKNESS_M * 100.0, 1)
    chosen_cm = ", ".join(
        "{}cm".format(round(t / FEET_PER_METER * 100.0, 1)) for t in sorted(target_thicknesses_ft)
    )
    tol_cm = round(tolerance_ft / FEET_PER_METER * 100.0, 2)

    msg += (
        "Foram encontrados {} par(es) de linhas paralelas dentro da faixa "
        "fisica de parede ({}cm a {}cm), mas nenhum ficou dentro da "
        "tolerancia (+/-{}cm) de nenhuma das espessuras escolhidas ({}).\n"
        "Distancia minima medida: {}cm | maxima medida: {}cm.\n\n"
        "Causas provaveis: as espessuras escolhidas nao correspondem as "
        "paredes desse Layer, escala/unidade do CAD incorreta no "
        "import/vinculo, ou linhas duplicadas/sobrepostas (distancia ~0)."
    ).format(
        diagnostics["parallel_pairs"], min_accepted_cm, max_accepted_cm, tol_cm, chosen_cm, min_cm, max_cm
    )

    return msg


def scan_candidate_thicknesses_cm(lines):
    """Mede a distancia perpendicular entre TODOS os pares de linhas
    paralelas do Layer que caem na faixa fisica plausivel de espessura de
    parede (MIN_WALL_THICKNESS_FT a MAX_WALL_THICKNESS_FT) e com sobreposicao
    real (mesmo criterio de find_wall_pairs), e agrupa essas medidas em
    "baldes" de 0.5cm para sugerir ao usuario, com contagem de ocorrencias,
    quais espessuras de parede aparentemente existem no desenho.

    E' apenas uma sugestao para preencher a lista de selecao - o usuario
    ainda pode digitar manualmente qualquer espessura que preferir."""
    counts = {}
    n = len(lines)
    for i in range(n):
        line1 = lines[i]
        for j in range(i + 1, n):
            line2 = lines[j]
            if not are_lines_parallel(line1, line2):
                continue
            dist = get_distance_between_parallel_lines(line1, line2)
            if not (MIN_WALL_THICKNESS_FT <= dist <= MAX_WALL_THICKNESS_FT):
                continue
            if not lines_overlap_enough(line1, line2):
                continue
            cm = dist / FEET_PER_METER * 100.0
            bucket = round(cm * 2.0) / 2.0  # agrupa ao 0.5cm mais proximo
            counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def compute_detection_tolerance_ft(target_thicknesses_ft):
    """Devolve a tolerancia de deteccao a usar em find_wall_pairs.

    Normalmente e' WALL_DETECTION_TOLERANCE_FT, mas se o usuario escolheu
    duas espessuras muito proximas entre si (ex.: 14cm e 15cm), essa
    tolerancia e' reduzida automaticamente para NO MAXIMO metade da menor
    distancia entre duas espessuras escolhidas - senao as duas faixas de
    tolerancia se sobrepoem e uma parede de 14cm poderia ser confundida com
    uma de 15cm (ou vice-versa)."""
    if len(target_thicknesses_ft) < 2:
        return WALL_DETECTION_TOLERANCE_FT
    ordered = sorted(target_thicknesses_ft)
    min_gap_ft = min(b - a for a, b in zip(ordered, ordered[1:]))
    return max(0.0, min(WALL_DETECTION_TOLERANCE_FT, min_gap_ft / 2.0 - 1e-6))


# ---- associacao abertura -> parede - EXTRAIDO verbatim de
# core/wall_modeling.py (linhas ~1368-1594 na versao de origem):
# _project_opening_raw, _project_opening_on_line, _merge_opening_matches,
# find_openings_on_line, assign_openings_to_walls. Nenhuma formula mudou,
# so' o arquivo (mesmo padrao do resto deste modulo) - motivado pela
# "arquitetura do modelador externo" (2026-08-26): o modelador externo
# reconstroi walls_to_create a partir do JSON de captura
# (core/capture_export.py) e precisa desta MESMA associacao
# abertura->parede para montar openings_per_wall antes de chamar
# core.engine.wall_stepper.process_walls_one_by_one - sem isso, o
# modelador teria que reimplementar a logica de associacao (violaria o
# pedido do usuario de nao reescrever regras que ja funcionam).


def _project_opening_raw(centerline, op):
    """Como `_project_opening_on_line`, mas devolve `t_center` (posicao do
    CENTRO da abertura ao longo do eixo, a partir de `centerline.GetEndPoint(0)`)
    e `half_width_ft` SEM aplicar nenhum clamp ao comprimento do eixo -
    `_project_opening_on_line` ja recorta isso para [0, comprimento], o que
    esconde de quem chama o quanto (e para qual lado) o vao real ultrapassa
    uma das pontas do eixo. Usado pelo log final/diagnostico para reportar a
    posicao BRUTA calculada para o vao, antes de qualquer recorte.

    Achata a centerline para o plano XY (Z=0) pelo mesmo motivo de
    `_project_opening_on_line` (ver ali) - a linha do CAD costuma estar na
    elevacao absoluta do nivel/import, enquanto as aberturas sao comparadas
    com Z=0."""
    p0_raw = centerline.GetEndPoint(0)
    p1_raw = centerline.GetEndPoint(1)
    p0 = XYZ(p0_raw.X, p0_raw.Y, 0.0)
    p1 = XYZ(p1_raw.X, p1_raw.Y, 0.0)
    direction = (p1 - p0).Normalize()

    center = op["center_xy"]
    t_center = (center - p0).DotProduct(direction)
    proj_point = p0 + direction * t_center
    perp_dist = center.DistanceTo(proj_point)
    return t_center, op["width_ft"] / 2.0, perp_dist


def _project_opening_on_line(centerline, op):
    """Calcula, para UMA abertura `op` e UMA `centerline` de parede, a
    posicao horizontal (t_lo, t_hi) do vao em relacao a essa parede e a
    distancia perpendicular do centro da abertura ate' o eixo.

    A extensao horizontal (t_lo, t_hi) e' `t_center +/- largura/2`,
    calculada a partir do parametro `Largura_abertura` (ja lido em
    get_opening_instances) projetado sobre a direcao DESTA parede - nao
    depende de qual eixo local da familia corresponde a largura, porque o
    resultado e' sempre medido ao longo da parede, nao da familia.
    Deliberadamente NAO usa a bounding box 3D da instancia: ela inclui
    qualquer geometria visivel da familia (moldura, indicador de sentido de
    abertura, soleira) que costuma se estender um pouco alem do vao real, o
    que deslocava/alargava o corte mesmo com a familia posicionada
    exatamente sobre a linha do CAD.

    t_lo/t_hi sao recortados (clamp) para [0, comprimento do eixo] - ver
    `_project_opening_raw` para os valores SEM esse recorte, usados quando
    quem chama precisa saber o quanto a abertura ultrapassa uma ponta.

    So' calcula - NAO decide se a abertura "pertence" a esta parede (nem
    pela tolerancia perpendicular nem pelo trecho coberto); quem chama
    decide isso (ver assign_openings_to_walls), porque a mesma abertura
    pode precisar ser projetada em VARIAS paredes candidatas antes de se
    escolher a mais proxima.
    """
    p0_raw = centerline.GetEndPoint(0)
    p1_raw = centerline.GetEndPoint(1)
    length_ft = XYZ(p0_raw.X, p0_raw.Y, 0.0).DistanceTo(XYZ(p1_raw.X, p1_raw.Y, 0.0))

    t_center, half_width_ft, perp_dist = _project_opening_raw(centerline, op)
    t_lo = max(0.0, t_center - half_width_ft)
    t_hi = min(length_ft, t_center + half_width_ft)
    return t_lo, t_hi, perp_dist


def _merge_opening_matches(matches):
    """Ordena e remove apenas duplicatas geometricamente equivalentes.

    A antiga uniao por sobreposicao horizontal transformava duas aberturas
    em alturas diferentes num unico vazio do menor peitoril ate a maior
    verga. A decomposicao 2D de ``build_wall_segments`` lida com retangulos
    sobrepostos sem precisar aumentar o vazio real.
    """
    ordered = sorted(matches, key=lambda m: (m[0], m[1], m[2], m[3]))
    unique = []
    for row in ordered:
        if unique and all(abs(row[i] - unique[-1][i]) <= 1e-9 for i in range(4)):
            continue
        unique.append(row)
    return unique


def find_openings_on_line(centerline, thickness_ft, openings):
    """Filtra, dentre `openings`, apenas as que estao proximas o bastante
    desta `centerline` de parede (dentro de thickness/2 + tolerancia) para
    pertencer a ela, e devolve seus intervalos horizontais/verticais em
    relacao a ela - ver `_project_opening_on_line` para o calculo de cada
    abertura e `_merge_opening_matches` para a mesclagem de sobrepostas.

    NAO e' exclusivo entre paredes (a mesma abertura pode "bater" aqui para
    mais de uma `centerline` candidata, se ambas estiverem dentro da
    tolerancia) - usada isoladamente (ex.: diagnostico/depuracao de uma
    unica parede). A geracao principal usa `assign_openings_to_walls`, que
    associa cada abertura a NO MAXIMO uma parede (a mais proxima), evitando
    que a mesma porta/janela recorte (boneca + verga) mais de uma parede
    candidata ao mesmo tempo.
    """
    max_perp_dist_ft = thickness_ft / 2.0 + OPENING_ASSOC_TOLERANCE_FT

    matches = []
    for op in openings:
        t_lo, t_hi, perp_dist = _project_opening_on_line(centerline, op)
        if perp_dist > max_perp_dist_ft:
            continue  # abertura longe demais do eixo desta parede - nao e' dela
        if t_hi - t_lo <= MIN_SEGMENT_LENGTH_FT:
            continue  # abertura fora (ou quase fora) do trecho desta parede
        matches.append((t_lo, t_hi, op["sill_z_abs"], op["head_z_abs"]))

    return _merge_opening_matches(matches)


def assign_openings_to_walls(walls_to_create, openings, diagnostics=None):
    """Associa cada abertura do projeto a NO MAXIMO UMA parede dentre
    `walls_to_create` - a de eixo MAIS PROXIMO (menor distancia
    perpendicular), entre as que ficam dentro da tolerancia de associacao
    (thickness/2 + OPENING_ASSOC_TOLERANCE_FT).

    Sem esta exclusividade, uma abertura posicionada entre duas paredes
    PARALELAS proximas o bastante uma da outra (ex.: paredes finas dos dois
    lados de um corredor estreito, ou duas paredes que compartilham quase o
    mesmo eixo) poderia cair dentro da tolerancia de AMBAS ao mesmo tempo e
    ser recortada (boneca + verga) em cada uma delas - inclusive numa
    parede a que ela fisicamente nao pertence. E' exatamente isso que faria
    a "parede acima da porta/janela" (a verga) parecer ultrapassar os
    limites do vao ou se fundir com uma parede vizinha: nao por erro no
    calculo do proprio intervalo [t_lo, t_hi] (que ja' e' exato - ver
    `_project_opening_on_line`), mas por ele acabar sendo aplicado tambem
    numa parede errada.

    `diagnostics`, se fornecido (dict com a chave "clamped_opening_count"
    ja inicializada pelo chamador), e' incrementado sempre que o intervalo
    [t_lo, t_hi] atribuido a uma abertura fica mais ESTREITO que sua
    `Largura_abertura` real por mais de OPENING_WIDTH_CLAMP_WARNING_FT -
    sinal de que a abertura esta' posicionada perto demais da ponta da
    parede reconstruida a partir do CAD (o vao "bate" no limite da propria
    parede antes de completar a largura toda), util para a etapa de
    validacao final (verga deve cobrir EXATAMENTE a largura da abertura).

    Devolve uma lista paralela a `walls_to_create`: para cada parede, a
    lista de (t_lo, t_hi, sill_z_abs, head_z_abs) das aberturas
    exclusivamente atribuidas a ela (mesmo formato que find_openings_on_line
    devolve para uma unica parede).
    """
    n = len(walls_to_create)
    raw_per_wall = [[] for _ in range(n)]

    for op in openings:
        best_wall_idx = None
        best_perp_dist = None
        best_interval = None
        for idx, (centerline, thickness_ft, _locked) in enumerate(walls_to_create):
            t_lo, t_hi, perp_dist = _project_opening_on_line(centerline, op)
            max_perp_dist_ft = thickness_ft / 2.0 + OPENING_ASSOC_TOLERANCE_FT
            if perp_dist > max_perp_dist_ft:
                continue  # abertura longe demais do eixo desta parede - nao e' dela
            if t_hi - t_lo <= MIN_SEGMENT_LENGTH_FT:
                continue  # abertura fora (ou quase fora) do trecho desta parede
            if best_perp_dist is None or perp_dist < best_perp_dist:
                best_perp_dist = perp_dist
                best_wall_idx = idx
                best_interval = (t_lo, t_hi)

        if best_wall_idx is not None:
            t_lo, t_hi = best_interval
            if diagnostics is not None:
                measured_width_ft = t_hi - t_lo
                if (op["width_ft"] - measured_width_ft) > OPENING_WIDTH_CLAMP_WARNING_FT:
                    diagnostics["clamped_opening_count"] += 1

                bbox_center = op.get("bbox_center_xy")
                if bbox_center is not None:
                    centerline_of_wall = walls_to_create[best_wall_idx][0]
                    w_p0_raw = centerline_of_wall.GetEndPoint(0)
                    w_p1_raw = centerline_of_wall.GetEndPoint(1)
                    w_p0 = XYZ(w_p0_raw.X, w_p0_raw.Y, 0.0)
                    w_dir = (XYZ(w_p1_raw.X, w_p1_raw.Y, 0.0) - w_p0).Normalize()
                    t_insertion = (op["center_xy"] - w_p0).DotProduct(w_dir)
                    t_bbox = (bbox_center - w_p0).DotProduct(w_dir)
                    center_gap_ft = abs(t_insertion - t_bbox)
                    if center_gap_ft > diagnostics["opening_center_gap_max_ft"]:
                        diagnostics["opening_center_gap_max_ft"] = center_gap_ft
                    if center_gap_ft > OPENING_WIDTH_CLAMP_WARNING_FT:
                        diagnostics["opening_off_center_count"] += 1

                diagnostics.setdefault("assignments", []).append({
                    "op": op,
                    "wall_idx": best_wall_idx,
                    "t_lo": t_lo,
                    "t_hi": t_hi,
                    "perp_dist_ft": best_perp_dist,
                })

            raw_per_wall[best_wall_idx].append((t_lo, t_hi, op["sill_z_abs"], op["head_z_abs"]))
        elif diagnostics is not None:
            diagnostics.setdefault("unassigned_openings", []).append(op)

    return [_merge_opening_matches(matches) for matches in raw_per_wall]


def build_wall_segments(centerline, base_z_abs, wall_height_ft, openings_on_line):
    """Fatia a `centerline` de uma parede em um ou mais segmentos, para que
    cada abertura em `openings_on_line` fique livre apenas na sua faixa real
    (peitoril ate verga, na largura do vao) e os vazios entre essa faixa e a
    base/topo da parede sejam preenchidos com parede normalmente.

    Devolve uma lista de (sub_line, height_ft, base_offset_ft, origin), pronta
    para ser usada em Wall.Create / modelo 3D (base_offset_ft e' relativo a `base_z_abs`,
    ou seja, ao nivel de insercao da parede). `origin` e' "cad" para um
    trecho cheio normal (determinado so' pelas linhas do AutoCAD) ou
    "abertura" para um trecho de preenchimento (verga/peitoril) cuja
    extensao horizontal foi determinada EXCLUSIVAMENTE pela abertura
    selecionada no Revit.
    Sem aberturas associadas, devolve a propria `centerline` inteira, altura
    cheia, offset 0, origem "cad".
    """
    if not openings_on_line:
        return [(centerline, wall_height_ft, 0.0, "cad")]

    p0_raw = centerline.GetEndPoint(0)
    p1_raw = centerline.GetEndPoint(1)
    p0 = XYZ(p0_raw.X, p0_raw.Y, 0.0)
    p1 = XYZ(p1_raw.X, p1_raw.Y, 0.0)
    direction = (p1 - p0).Normalize()
    length_ft = p0.DistanceTo(p1)
    top_z_abs = base_z_abs + wall_height_ft

    def make_horizontal_full_segment(t_a, t_b):
        if t_b - t_a <= MIN_SEGMENT_LENGTH_FT:
            return None
        sub_line = Line.CreateBound(p0 + direction * t_a, p0 + direction * t_b)
        return (sub_line, wall_height_ft, 0.0, "cad")

    def make_infill_segment(t_a, t_b, seg_base_z, seg_top_z):
        if t_b - t_a <= MIN_SEGMENT_LENGTH_FT:
            return None
        if seg_top_z - seg_base_z <= MIN_SEGMENT_HEIGHT_FT:
            return None
        sub_line = Line.CreateBound(p0 + direction * t_a, p0 + direction * t_b)
        return (sub_line, seg_top_z - seg_base_z, seg_base_z - base_z_abs, "abertura")

    normalized = []
    x_breaks = [0.0, length_ft]
    for t_lo, t_hi, sill_z_abs, head_z_abs in openings_on_line:
        lo = max(0.0, min(length_ft, t_lo))
        hi = max(0.0, min(length_ft, t_hi))
        sill = max(base_z_abs, min(top_z_abs, sill_z_abs))
        head = max(base_z_abs, min(top_z_abs, head_z_abs))
        if hi - lo <= MIN_SEGMENT_LENGTH_FT or head - sill <= MIN_SEGMENT_HEIGHT_FT:
            continue
        normalized.append((lo, hi, sill, head))
        x_breaks.extend((lo, hi))

    if not normalized:
        return [(centerline, wall_height_ft, 0.0, "cad")]

    x_breaks = sorted(set(round(value, 9) for value in x_breaks))
    segments = []
    for index in range(len(x_breaks) - 1):
        t_a, t_b = x_breaks[index], x_breaks[index + 1]
        if t_b - t_a <= MIN_SEGMENT_LENGTH_FT:
            continue
        mid_t = (t_a + t_b) / 2.0
        voids = sorted(
            (sill, head) for lo, hi, sill, head in normalized
            if lo - 1e-9 <= mid_t <= hi + 1e-9
        )
        merged_voids = []
        for sill, head in voids:
            if merged_voids and sill <= merged_voids[-1][1] + 1e-9:
                merged_voids[-1] = (merged_voids[-1][0], max(merged_voids[-1][1], head))
            else:
                merged_voids.append((sill, head))

        if not merged_voids:
            seg = make_horizontal_full_segment(t_a, t_b)
            if seg:
                segments.append(seg)
            continue

        cursor_z = base_z_abs
        for sill, head in merged_voids:
            seg = make_infill_segment(t_a, t_b, cursor_z, sill)
            if seg:
                segments.append(seg)
            cursor_z = max(cursor_z, head)
        seg = make_infill_segment(t_a, t_b, cursor_z, top_z_abs)
        if seg:
            segments.append(seg)

    return segments
