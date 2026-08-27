# -*- coding: utf-8 -*-
"""Geometria pura (linhas/paralelismo/distancias/eixo central) extraida
verbatim de `core/wall_modeling.py` - primeira fatia da extracao fisica do
motor de regras para `core/engine/` (ver ARQUITETURA_INTERATIVA.md,
"Por que a extracao fisica do motor nao foi feita" - esta e' a
continuacao mecanica, funcao por funcao, prometida la').

Nenhuma formula mudou. `wall_modeling.py` importa tudo daqui (`from
core.engine.geometry import *`, SEM fallback - ver o ponto onde o import
acontece: e' agora uma dependencia obrigatoria, nao mais opcional como as
constantes de tolerancia) para que todos os call-sites existentes (por
nome solto, dentro do mesmo modulo) continuem funcionando sem nenhuma
alteracao.

`__all__` inclui os nomes com underscore de proposito - `import *` os
ignoraria por padrao, e varias funcoes "privadas" daqui (`_line_geom_cache`
etc.) sao chamadas por nome solto de FORA deste arquivo, dentro de
`wall_modeling.py`.

Modulo PURO: as unicas dependencias de "Revit" aqui sao os TIPOS `XYZ`/
`Line` (usados so' para construir/ler pontos e curvas - nunca `doc`/
`uidoc`, nunca uma consulta ao documento) - por isso e' seguro e testado
sem nenhum Revit de verdade (ver tests/revit_stubs.py).
"""

from Autodesk.Revit.DB import XYZ, Line

from core.engine.tolerances import (
    MIN_WALL_SEGMENT_OVERLAP_RATIO, MIN_WALL_SEGMENT_ABS_FLOOR_FT,
    OPENING_BRIDGE_TOLERANCE_FT,
)

__all__ = [
    "are_lines_parallel", "get_line_midpoint", "project_point_on_line",
    "get_distance_between_parallel_lines", "_line_geom_cache",
    "_are_parallel_cached", "_distance_between_parallel_cached",
    "_line_pair_overlap_ft_cached", "_xy_deviation_ft", "_axis_offset_error_ft",
    "create_centerline", "_opening_bridges_gap", "_merge_collinear_cluster",
    "_cluster_axis", "_cluster_interval", "_clusters_bridge_via_opening",
    "_bridge_clusters_via_openings", "merge_collinear_fragments",
    "_line_pair_overlap_ft", "lines_overlap_enough",
]


def are_lines_parallel(l1, l2, tolerance=0.05):
    """Verifica se duas linhas 2D sao paralelas (produto vetorial ~ 0)."""
    dir1 = l1.Direction.Normalize()
    dir2 = l2.Direction.Normalize()
    cross = dir1.CrossProduct(dir2)
    return abs(cross.Z) < tolerance


def get_line_midpoint(line):
    """Retorna o ponto medio de uma linha."""
    return line.Evaluate(0.5, True)


def project_point_on_line(point, line):
    """Projeta um ponto 3D sobre a linha (tratada como infinita)."""
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    v = (p1 - p0).Normalize()
    w = point - p0
    proj_dist = w.DotProduct(v)
    return p0 + v * proj_dist


def get_distance_between_parallel_lines(l1, l2):
    """Mede a distancia perpendicular entre duas linhas paralelas."""
    mid_p1 = get_line_midpoint(l1)
    proj_p2 = project_point_on_line(mid_p1, l2)
    return mid_p1.DistanceTo(proj_p2)


def _line_geom_cache(line):
    """Pre-calcula (p0, direcao normalizada, comprimento, ponto medio) de
    UMA linha - para reuso nos lacos O(n^2)/O(m^2) que comparam cada linha
    contra TODAS as outras (ver PERFORMANCE em find_wall_pairs,
    scan_possible_missed_bonecas, merge_collinear_fragments e
    _bridge_clusters_via_openings).

    Sem isso, are_lines_parallel/get_distance_between_parallel_lines
    recalculavam a direcao normalizada (Direction.Normalize(), uma conta
    com raiz quadrada) e o ponto medio (Evaluate) da MESMA linha `i` do ZERO
    a cada uma das O(n) comparacoes contra `j` - repetido, sem necessidade,
    porque a linha `i` fica fixa durante toda a varredura do laco interno.
    Calcular uma vez por linha (O(n) chamadas no total, em vez de O(n^2))
    e' um dos motivos do script ficar lento em Layers de CAD grandes,
    junto com a complexidade algoritmica ja corrigida (ver os
    PERFORMANCE das funcoes citadas acima).

    O ponto medio e' reconstruido como `p0 + direcao * (comprimento / 2)`
    em vez de `line.Evaluate(0.5, True)` (usado por get_line_midpoint) -
    matematicamente identico para uma Line reta e bound (mesma formula que
    o proprio Revit aplica internamente), sem nenhuma perda de precisao
    relevante para as tolerancias (na ordem de mm a cm) usadas em todas as
    comparacoes que consomem este cache."""
    p0 = line.GetEndPoint(0)
    p1 = line.GetEndPoint(1)
    direction = (p1 - p0).Normalize()
    length = p0.DistanceTo(p1)
    midpoint = p0 + direction * (length * 0.5)
    return (p0, p1, direction, length, midpoint)


def _are_parallel_cached(cache1, cache2, tolerance=0.05):
    """Equivalente a are_lines_parallel, usando direcoes ja calculadas por
    _line_geom_cache em vez de recalcula-las a partir da Line."""
    direction1 = cache1[2]
    direction2 = cache2[2]
    cross = direction1.CrossProduct(direction2)
    return abs(cross.Z) < tolerance


def _distance_between_parallel_cached(cache1, cache2):
    """Equivalente a get_distance_between_parallel_lines(l1, l2), usando o
    ponto medio de `l1` e a posicao/direcao de `l2` ja calculados por
    _line_geom_cache em vez de recalcula-los a partir das Line."""
    midpoint1 = cache1[4]
    p0_2, direction2 = cache2[0], cache2[2]
    w = midpoint1 - p0_2
    proj_dist = w.DotProduct(direction2)
    proj_point = p0_2 + direction2 * proj_dist
    return midpoint1.DistanceTo(proj_point)


def _line_pair_overlap_ft_cached(cache1, cache2):
    """Equivalente a _line_pair_overlap_ft(line1, line2), usando p0/p1/
    direcao/comprimento ja calculados por _line_geom_cache em vez de
    recalcula-los a partir das Line."""
    p0, _p1, direction, length1, _mid = cache1
    q0, q1, _dir2, length2, _mid2 = cache2

    t_q0 = (q0 - p0).DotProduct(direction)
    t_q1 = (q1 - p0).DotProduct(direction)
    t2_lo, t2_hi = min(t_q0, t_q1), max(t_q0, t_q1)

    overlap_lo = max(0.0, t2_lo)
    overlap_hi = min(length1, t2_hi)
    overlap_ft = max(0.0, overlap_hi - overlap_lo)
    return overlap_ft, length1, length2


def _xy_deviation_ft(curve_a, curve_b):
    """Maior distancia, medida SO' no plano XY (planta), entre as pontas
    correspondentes de duas linhas - testando as duas correspondencias
    possiveis (inicio-com-inicio e inicio-com-fim) e devolvendo a menor
    delas, porque o Revit pode devolver a curva de localizacao de uma
    parede com o sentido invertido em relacao a curva que foi passada na
    criacao.

    Ignora Z deliberadamente: a linha calculada a partir do CAD carrega a
    elevacao do proprio CAD, enquanto a curva de localizacao da parede
    criada fica na elevacao do NIVEL de insercao - comparar Z acusaria uma
    "diferenca" enorme que nao tem nada a ver com o alinhamento em planta,
    que e' o que esta sendo verificado aqui."""
    def xy(p):
        return XYZ(p.X, p.Y, 0.0)

    a0, a1 = xy(curve_a.GetEndPoint(0)), xy(curve_a.GetEndPoint(1))
    b0, b1 = xy(curve_b.GetEndPoint(0)), xy(curve_b.GetEndPoint(1))

    same_order = max(a0.DistanceTo(b0), a1.DistanceTo(b1))
    reversed_order = max(a0.DistanceTo(b1), a1.DistanceTo(b0))
    return min(same_order, reversed_order)


def _axis_offset_error_ft(centerline, l1, l2):
    """Mede o quanto `centerline` se desvia de ficar EXATAMENTE a meio
    caminho entre `l1` e `l2` - a propria definicao de "eixo central" - nas
    duas pontas do eixo.

    Em cada ponta, compara a distancia ate' `l1` com a distancia ate' `l2`:
    se o eixo esta' corretamente centralizado, as duas devem ser IGUAIS
    (ambas valem metade da espessura medida), entao a DIFERENCA entre elas
    e' zero. Usada como autoverificacao geometrica de create_centerline
    (ver find_wall_pairs, etapa de validacao final) - independe de qualquer
    comportamento do Revit (WallType, Linha de Referencia etc., que sao
    verificados separadamente em get_or_create_wall_type): mede so' se o
    ALGORITMO calculou o eixo certo a partir das duas linhas do CAD.

    Devolve o maior desvio absoluto (em pes) encontrado entre as duas
    pontas."""
    worst = 0.0
    for idx in (0, 1):
        p = centerline.GetEndPoint(idx)
        dist_to_l1 = p.DistanceTo(project_point_on_line(p, l1))
        dist_to_l2 = p.DistanceTo(project_point_on_line(p, l2))
        worst = max(worst, abs(dist_to_l1 - dist_to_l2))
    return worst


def create_centerline(l1, l2, max_extension_ft):
    """Gera a linha do eixo central entre duas linhas paralelas do CAD.

    O eixo cobre a UNIAO do alcance das duas linhas (nao apenas o alcance
    de `l1`): em cada ponta, usa a que for MAIS LONGA das duas faces
    pareadas. Isso evita que a parede nasca curta num encontro em L ou T
    so' porque, naquele ponto, uma das duas faces do CAD (interna/externa)
    foi desenhada um pouco mais curta que a outra - a face mais longa
    sempre prevalece, entao a parede chega ate' o ponto de conexao
    correto em vez de deixar um recuo/mordida no canto.

    Essa extensao, porem, e' LIMITADA a `max_extension_ft` alem do proprio
    comprimento de `l1` em cada ponta: sem esse teto, um pareamento
    equivocado (l2 pertencendo na verdade a outra parede bem mais longa que
    apenas passa perto/cruza ali) faria o eixo disparar muito alem dos
    limites reais desenhados no CAD. Um encontro T/L legitimo normalmente
    precisa de pouca extensao (da ordem da espessura da parede perpendicular
    que chega ali) - bem menor que esse teto.
    """
    p0 = l1.GetEndPoint(0)
    p1 = l1.GetEndPoint(1)
    dir1 = (p1 - p0).Normalize()

    q0, q1 = l2.GetEndPoint(0), l2.GetEndPoint(1)
    dir2_raw = (q1 - q0).Normalize()
    # l2 pode estar desenhada em qualquer sentido no CAD (nao
    # necessariamente "andando" no mesmo sentido de l1, mesmo sendo
    # paralela a ela) - alinha o sentido antes de somar/tirar a media,
    # senao os dois vetores quase se cancelariam.
    dir2 = dir2_raw if dir1.DotProduct(dir2_raw) >= 0.0 else -dir2_raw

    # Direcao do eixo: BISSETRIZ entre l1 e l2, nao simplesmente a direcao
    # de l1. are_lines_parallel tolera um pequeno desvio angular entre as
    # duas linhas (ate' uns 3 graus) - havendo esse desvio (mesmo pequeno),
    # a direcao "certa" do eixo central e' a MEDIA entre as duas, nao a de
    # uma delas sozinha. Usar so' a direcao de l1 (versao anterior) faz o
    # eixo herdar TODO o desvio angular de l1 em vez de dividi-lo ao meio,
    # deslocando lateralmente as pontas do eixo em relacao as duas linhas
    # originais (mais fora do centro nas extremidades do que no meio) - um
    # vies pequeno mas sistematico, e que tambem tornava o resultado
    # dependente da ORDEM dos argumentos (l1 vs l2), quando deveria ser
    # simetrico entre as duas faces da parede.
    bisector_vec = dir1 + dir2
    direction = bisector_vec.Normalize() if bisector_vec.GetLength() > 1e-9 else dir1

    # Ancoragem do eixo: SEMPRE em `p0` (um ponto real de l1, garantidamente
    # perto da parede de verdade) - nunca no ponto de intersecao das duas
    # retas infinitas. Uma versao anterior desta funcao ancorava no ponto de
    # intersecao quando havia desvio angular entre l1/l2, porque ali o eixo
    # fica EXATAMENTE equidistante (propriedade geometrica de bissetriz) -
    # matematicamente correto, mas numericamente perigoso na pratica: para
    # o desvio angular pequeno tipico de QUALQUER CAD real (nunca
    # perfeitamente paralelo), esse ponto de intersecao fica MUITO longe do
    # trecho real da parede (facilmente centenas de metros, para um desvio
    # de fracoes de grau) - e qualquer imprecisao residual na direcao
    # calculada fica AMPLIFICADA pela distancia ate' esse ponto distante ao
    # projetar de volta para perto da parede (pior ainda em projetos que
    # usam coordenadas de implantacao/levantamento longe da origem, comuns
    # em vinculos de CAD). Na pratica isso corrompia a geometria de
    # praticamente toda parede gerada (pontas nao alcancando cantos, vaos
    # inesperados) - regressao bem pior que o pequeno vies residual que a
    # media de amostras (abaixo) deixa para desvios angulares realistas.
    len1 = (p1 - p0).DotProduct(direction)

    # Deslocamento perpendicular de l1 para l2: MEDIA do deslocamento medido
    # em TRES pontos ao longo do eixo (inicio, meio, fim de l1, projetados
    # na direcao ja' calculada acima - a bissetriz, nao mais so' a direcao
    # de l1). Para linhas verdadeiramente paralelas essa distancia e'
    # constante ao longo do comprimento, entao a media e' exata; para um
    # desvio angular real (mesmo pequeno) ela varia um pouco ao longo do
    # comprimento - amostrar as duas pontas + o meio e tirar a media cancela
    # a maior parte desse vies, sem depender de nenhum ponto distante.
    sample_ts = (0.0, len1 * 0.5, len1)
    offset_sum = XYZ(0.0, 0.0, 0.0)
    for t in sample_ts:
        sample_pt = p0 + direction * t
        proj = project_point_on_line(sample_pt, l2)
        offset_sum += (proj - sample_pt)
    half_offset = (offset_sum / len(sample_ts)) * 0.5

    t_lo = 0.0
    t_hi = len1

    t_q0 = (q0 - p0).DotProduct(direction)
    t_q1 = (q1 - p0).DotProduct(direction)
    for t in (t_q0, t_q1):
        if t < t_lo and (t_lo - t) <= max_extension_ft:
            t_lo = t
        if t > t_hi and (t - t_hi) <= max_extension_ft:
            t_hi = t

    mid_start = p0 + direction * t_lo + half_offset
    mid_end = p0 + direction * t_hi + half_offset

    if mid_start.DistanceTo(mid_end) < 0.01:
        return None

    return Line.CreateBound(mid_start, mid_end)


def _opening_bridges_gap(p0, direction, gap_lo, gap_hi, openings, perp_tolerance_ft, width_slack_ft):
    """Verifica se existe, dentre `openings`, uma abertura REAL do projeto
    (porta/janela ja' inserida, com Largura_abertura/Altura_abertura/
    Peitoril) cujo centro projetado sobre a reta (p0, direction) caia
    dentro da quebra [gap_lo, gap_hi] entre dois fragmentos colineares, com
    distancia perpendicular plausivel (dentro de `perp_tolerance_ft`, a
    espessura maxima de parede aceita) e largura compativel com o tamanho
    da propria quebra (dentro de `width_slack_ft`, folga para jambas/
    enquadramento desenhados no CAD).

    Usada para religar fragmentos separados por um vao MAIOR que
    `gap_tolerance_ft` (ver _merge_collinear_cluster) quando esse vao e'
    genuinamente o vao de uma porta/janela - only entao, nunca para
    quebras sem nenhuma abertura real correspondente ali.

    A largura da abertura vem diretamente de `op["width_ft"]` (o parametro
    Largura_abertura, ja lido em get_opening_instances) - nao da bounding
    box 3D da instancia, que pode incluir moldura/enquadramento e outras
    geometrias que se estendem alem do vao real.

    IMPORTANTE: `op["center_xy"]` (ver get_opening_instances) fica sempre
    em Z=0, enquanto `p0` (ponto da linha do CAD) costuma estar na
    elevacao ABSOLUTA do nivel/import (Z != 0). Comparar os pontos
    originais faria XYZ.DistanceTo() somar essa diferenca de elevacao
    inteira na "distancia perpendicular", estourando sempre `perp_tolerance_ft`
    e fazendo esta funcao nunca religar nada - por isso `p0` e' achatado
    para Z=0 aqui antes de qualquer calculo de distancia (mesmo ajuste ja'
    feito em find_openings_on_line)."""
    p0_flat = XYZ(p0.X, p0.Y, 0.0)
    gap_span_ft = gap_hi - gap_lo
    for op in openings:
        center = op["center_xy"]
        t_center = (center - p0_flat).DotProduct(direction)
        if t_center < gap_lo or t_center > gap_hi:
            continue

        proj_point = p0_flat + direction * t_center
        if center.DistanceTo(proj_point) > perp_tolerance_ft:
            continue

        if abs(gap_span_ft - op["width_ft"]) > width_slack_ft:
            continue

        return True
    return False


def _merge_collinear_cluster(cluster, gap_tolerance_ft, openings, opening_perp_tolerance_ft, opening_width_slack_ft):
    """Recebe um grupo de linhas ja confirmadas como colineares entre si e
    devolve a(s) linha(s) reconstruida(s), religando fragmentos cujo
    espaco entre um e outro seja <= `gap_tolerance_ft` (tipicamente a
    quebra deixada por outra parede cruzando esta) OU que corresponda a
    uma ABERTURA real do projeto na mesma posicao/largura (ver
    _opening_bridges_gap) - o vao de uma porta/janela costuma ser desenhado
    no CAD como uma quebra genuina na linha da parede (bem maior que
    `gap_tolerance_ft`), mas fisicamente a parede E' continua ali (so' com
    um vao recortado verticalmente, nao uma interrupcao estrutural) -
    religar esse trecho e' o que permite depois recortar exatamente a
    altura certa do vao (find_openings_on_line/build_wall_segments) e
    preservar tanto a parede acima da verga quanto qualquer "boneca" curta
    de parede entre a porta e um canto/encontro proximo, que sem isso nunca
    teriam eixo nenhum de parede passando por ali. Fragmentos separados por
    um vao maior que nao corresponde a nenhuma abertura real permanecem
    como linhas distintas - nada e' religado nesse caso."""
    # DIRECAO de referencia: a do fragmento MAIS LONGO do cluster - nao
    # simplesmente `cluster[0]` (a ordem de chegada dos fragmentos, ditada
    # so' pela ordem de travessia da geometria do CAD, e' arbitraria).
    base = max(cluster, key=lambda line: line.GetEndPoint(0).DistanceTo(line.GetEndPoint(1)))
    base_p0 = base.GetEndPoint(0)
    direction = (base.GetEndPoint(1) - base_p0).Normalize()

    # POSICAO de referencia: media dos fragmentos PONDERADA PELO COMPRIMENTO
    # de cada um - nao a posicao do fragmento mais longo. Uma versao anterior
    # ancorava a reta reconstruida exatamente sobre o fragmento mais longo,
    # o que REALOCAVA lateralmente todos os demais fragmentos do grupo ate'
    # a reta dele (ver a nota extensa em COLLINEAR_MATCH_TOLERANCE_M: com a
    # tolerancia generosa de entao, isso deslocava bonecas em ~0,5cm em
    # plantas cujas linhas nao sao perfeitamente alinhadas).
    #
    # Com a tolerancia agora apertada (2mm), todo fragmento que chega aqui
    # ja' esta' comprovadamente sobre a mesma reta, entao esta media so'
    # distribui ruido sub-milimetrico em vez de deixar um unico fragmento
    # ditar a posicao de todos. A ponderacao por comprimento faz os
    # fragmentos longos (mais confiaveis, menos sensiveis a imprecisao de
    # desenho) pesarem mais que os curtos, sem que os curtos sejam
    # simplesmente descartados.
    total_weight = 0.0
    weighted_offset_sum = XYZ(0.0, 0.0, 0.0)
    for line in cluster:
        a_pt, b_pt = line.GetEndPoint(0), line.GetEndPoint(1)
        weight = a_pt.DistanceTo(b_pt)
        if weight < 1e-12:
            continue
        mid = (a_pt + b_pt) * 0.5
        # Componente PERPENDICULAR (em relacao a `direction`) do vetor que
        # vai da reta base ate' o meio deste fragmento.
        rel = mid - base_p0
        perp = rel - direction * rel.DotProduct(direction)
        weighted_offset_sum += perp * weight
        total_weight += weight

    p0 = base_p0 + (weighted_offset_sum / total_weight if total_weight > 1e-12 else XYZ(0.0, 0.0, 0.0))

    intervals = []
    for line in cluster:
        a = (line.GetEndPoint(0) - p0).DotProduct(direction)
        b = (line.GetEndPoint(1) - p0).DotProduct(direction)
        intervals.append((min(a, b), max(a, b)))
    intervals.sort()

    merged = []
    cur_lo, cur_hi = intervals[0]
    for lo, hi in intervals[1:]:
        if lo <= cur_hi + gap_tolerance_ft or _opening_bridges_gap(
            p0, direction, cur_hi, lo, openings, opening_perp_tolerance_ft, opening_width_slack_ft
        ):
            cur_hi = max(cur_hi, hi)
        else:
            merged.append((cur_lo, cur_hi))
            cur_lo, cur_hi = lo, hi
    merged.append((cur_lo, cur_hi))

    return [
        Line.CreateBound(p0 + direction * lo, p0 + direction * hi)
        for lo, hi in merged
        if hi - lo > 1e-6
    ]


def _cluster_axis(cluster):
    """Devolve (p0, direction) de referencia para um cluster de fragmentos
    colineares - mesma convencao usada em _merge_collinear_cluster (ponto
    inicial e direcao do fragmento MAIS LONGO do cluster) - para servir de
    eixo de projecao ao TESTAR uma possivel fusao entre dois clusters
    distintos (ver _clusters_bridge_via_opening). NAO decide a posicao
    final de nenhum fragmento - isso continua sendo feito, do mesmo jeito de
    sempre, por _merge_collinear_cluster depois que os clusters candidatos a
    fusao ja tiverem sido decididos."""
    base = max(cluster, key=lambda line: line.GetEndPoint(0).DistanceTo(line.GetEndPoint(1)))
    p0 = base.GetEndPoint(0)
    direction = (base.GetEndPoint(1) - p0).Normalize()
    return p0, direction


def _cluster_interval(cluster, p0, direction):
    """Projeta todos os pontos de `cluster` sobre o eixo (p0, direction) e
    devolve (t_min, t_max) - o intervalo ocupado pelo cluster nesse eixo."""
    ts = [
        (line.GetEndPoint(idx) - p0).DotProduct(direction)
        for line in cluster
        for idx in (0, 1)
    ]
    return min(ts), max(ts)


def _clusters_bridge_via_opening(cluster_a, cluster_b, bridge_tolerance_ft, openings,
                                  opening_perp_tolerance_ft, opening_width_slack_ft):
    """Verifica se dois clusters de fragmentos colineares DISTINTOS (cada um
    ja formado com a tolerancia apertada COLLINEAR_MATCH_TOLERANCE_FT - ver
    merge_collinear_fragments) na verdade pertencem a MESMA face de parede,
    apenas separados pelo vao de uma abertura real do projeto desenhada com
    um desalinhamento entre as jambas maior que os 2mm tolerados no
    agrupamento "cru", mas ainda dentro de `bridge_tolerance_ft` (ver
    OPENING_BRIDGE_TOLERANCE_M).

    So' devolve True quando HA uma abertura real cujo vao explica o espaco
    entre os dois clusters (ver _opening_bridges_gap) - nunca so' por
    proximidade/paralelismo, para nao reintroduzir o deslocamento lateral
    que a tolerancia apertada corrigiu em juncoes SEM nenhuma abertura no
    meio (ex.: cruzamento com outra parede)."""
    ref_a = max(cluster_a, key=lambda line: line.GetEndPoint(0).DistanceTo(line.GetEndPoint(1)))
    ref_b = max(cluster_b, key=lambda line: line.GetEndPoint(0).DistanceTo(line.GetEndPoint(1)))
    if not are_lines_parallel(ref_a, ref_b):
        return False
    if get_distance_between_parallel_lines(ref_a, ref_b) > bridge_tolerance_ft:
        return False

    p0, direction = _cluster_axis(cluster_a)
    lo_a, hi_a = _cluster_interval(cluster_a, p0, direction)
    lo_b, hi_b = _cluster_interval(cluster_b, p0, direction)

    if hi_a <= lo_b:
        gap_lo, gap_hi = hi_a, lo_b
    elif hi_b <= lo_a:
        gap_lo, gap_hi = hi_b, lo_a
    else:
        return False  # clusters se sobrepoem no eixo - nao e' um "gap" para religar

    return _opening_bridges_gap(
        p0, direction, gap_lo, gap_hi, openings, opening_perp_tolerance_ft, opening_width_slack_ft
    )


def _bridge_clusters_via_openings(raw_clusters, bridge_tolerance_ft, openings,
                                   opening_perp_tolerance_ft, opening_width_slack_ft):
    """Funde clusters distintos quando uma abertura real do projeto religar
    o espaco entre eles - mesma regra de _clusters_bridge_via_opening,
    repetida em cascata ate' nao haver mais nenhuma fusao possivel (ver a
    docstring de merge_collinear_fragments).

    PERFORMANCE: rodar essa cascata (que reavalia TODOS os pares restantes
    do zero a cada fusao aceita) sobre os clusters do Layer inteiro de uma
    vez custa O(fusoes * clusters^2), recalculando a linha de referencia de
    cada cluster (max() sobre o cluster) a cada par comparado, em cada
    restart - em Layers de CAD com milhares de fragmentos (comuns em
    plantas reais), isso e' o principal motivo do script ficar muito lento
    logo depois da etapa de aberturas (que fornece `openings`, usado
    aqui).

    _clusters_bridge_via_opening so' pode devolver True quando as linhas de
    referencia dos dois clusters sao PARALELAS e estao a no maximo
    `bridge_tolerance_ft` uma da outra - exatamente esse mesmo teste,
    barato e feito aqui UMA UNICA vez (com as linhas de referencia ja
    calculadas de antemao, em vez de recalculadas a cada comparacao),
    particiona os clusters em grupos (Union-Find) sem NUNCA poder separar
    dois clusters que de fato pudessem se fundir - clusters de grupos
    diferentes jamais passariam nesse teste de qualquer forma, com
    QUALQUER abertura. A cascata cara (a mesma de sempre, sem nenhuma
    mudanca de comportamento) so' roda entao DENTRO de cada grupo -
    tipicamente pequeno (fragmentos que podem pertencer a mesma face de
    parede), nunca sobre o Layer inteiro."""
    n = len(raw_clusters)
    if n <= 1:
        return raw_clusters

    ref_lines = [
        max(cluster, key=lambda line: line.GetEndPoint(0).DistanceTo(line.GetEndPoint(1)))
        for cluster in raw_clusters
    ]
    # Geometria de cada linha de referencia calculada uma unica vez (ver
    # PERFORMANCE em _line_geom_cache) - o teste abaixo compara cada
    # cluster contra TODOS os outros (O(n^2)), o que sem cache recalcularia
    # a direcao/ponto medio da MESMA linha de referencia repetidas vezes.
    ref_caches = [_line_geom_cache(ref_line) for ref_line in ref_lines]

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        cache_i = ref_caches[i]
        for j in range(i + 1, n):
            cache_j = ref_caches[j]
            if (_are_parallel_cached(cache_i, cache_j) and
                    _distance_between_parallel_cached(cache_i, cache_j) <= bridge_tolerance_ft):
                union(i, j)

    groups = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(idx)

    result = []
    for member_idxs in groups.values():
        if len(member_idxs) == 1:
            result.append(raw_clusters[member_idxs[0]])
            continue

        # Cascata original, sem nenhuma alteracao de comportamento - so'
        # rodando sobre um grupo pequeno em vez do Layer inteiro.
        group_clusters = [raw_clusters[idx] for idx in member_idxs]
        merged_any = True
        while merged_any and len(group_clusters) > 1:
            merged_any = False
            for gi in range(len(group_clusters)):
                for gj in range(gi + 1, len(group_clusters)):
                    if _clusters_bridge_via_opening(
                        group_clusters[gi], group_clusters[gj], bridge_tolerance_ft,
                        openings, opening_perp_tolerance_ft, opening_width_slack_ft
                    ):
                        group_clusters[gi] = group_clusters[gi] + group_clusters[gj]
                        del group_clusters[gj]
                        merged_any = True
                        break
                if merged_any:
                    break
        result.extend(group_clusters)

    return result


def merge_collinear_fragments(lines, collinear_tolerance_ft, gap_tolerance_ft, openings,
                               opening_perp_tolerance_ft, opening_width_slack_ft,
                               opening_bridge_tolerance_ft=OPENING_BRIDGE_TOLERANCE_FT):
    """Reconstroi, a partir de fragmentos de linha colineares (mesma reta,
    testa-ponta ou levemente sobrepostos/afastados por ate
    `gap_tolerance_ft`, OU separados pelo vao real de uma abertura do
    projeto - ver _merge_collinear_cluster), o comprimento COMPLETO
    original de cada face de parede desenhada no CAD.

    CADs arquitetonicos costumam desenhar a face de uma parede QUEBRADA em
    varios segmentos exatamente nos pontos onde outra parede a cruza (T, L,
    Cruz +) OU onde ha' uma porta/janela - mesmo quando fisicamente e' uma
    unica parede continua. Sem recompor esses fragmentos numa linha unica
    antes de formar os pares, cada pedaco e' tratado isoladamente e pode
    ficar sem parceiro (a parede correspondente nunca chega a ser criada,
    dando a impressao de que ela foi "cortada" pela metade) - e, no caso
    especifico de uma porta, NENHUM eixo de parede chega a passar pelo
    vao dela, entao nem a "boneca" ao lado nem o preenchimento acima da
    verga tem onde nascer, mesmo que a logica de recorte por altura esteja
    correta.

    Feita em DUAS passadas:
      1. Agrupamento "cru", com a tolerancia APERTADA `collinear_tolerance_ft`
         (2mm) - idem ao comportamento original, preservando o alinhamento
         exato em juncoes/cruzamentos sem nenhuma abertura envolvida.
      2. Fusao adicional de clusters DISTINTOS da passada 1 quando (e so'
         quando) uma abertura real do projeto explica o espaco entre eles -
         ver _clusters_bridge_via_opening - usando a tolerancia mais
         generosa `opening_bridge_tolerance_ft`, para cobrir o desalinhamento
         de desenho tipico ao redor de portas/janelas reais (mais que 2mm,
         mas ainda claramente a MESMA face de parede).

    Esta funcao NAO recorta nada - faz o oposto: religa fragmentos que
    pertencem a mesma reta para restaurar o comprimento original antes de
    qualquer pareamento. O resultado dessas linhas reconstruidas e' o que
    alimenta find_wall_pairs, garantindo paredes de comprimento completo
    mesmo quando isso as faz atravessar/sobrepor outras paredes.
    """
    # Geometria de cada linha calculada uma unica vez (ver PERFORMANCE em
    # _line_geom_cache) - o agrupamento abaixo compara cada linha `base`
    # contra todas as `remaining`, o que sem cache recalcularia a direcao/
    # ponto medio da MESMA linha repetidas vezes.
    remaining = [(line, _line_geom_cache(line)) for line in lines]
    raw_clusters = []

    while remaining:
        base, base_cache = remaining.pop(0)
        cluster = [base]
        rest = []
        for other, other_cache in remaining:
            if (_are_parallel_cached(base_cache, other_cache) and
                    _distance_between_parallel_cached(base_cache, other_cache) <= collinear_tolerance_ft):
                cluster.append(other)
            else:
                rest.append((other, other_cache))
        remaining = rest
        raw_clusters.append(cluster)

    # Segunda passada (ver docstring): funde clusters distintos quando uma
    # abertura real religar o espaco entre eles - repete ate' nao haver mais
    # nenhuma fusao possivel, ja que fundir dois clusters pode abrir um novo
    # gap explicavel entre o resultado e um terceiro cluster vizinho. Ver
    # PERFORMANCE na docstring de _bridge_clusters_via_openings.
    raw_clusters = _bridge_clusters_via_openings(
        raw_clusters, opening_bridge_tolerance_ft, openings,
        opening_perp_tolerance_ft, opening_width_slack_ft
    )

    result = []
    for cluster in raw_clusters:
        result.extend(_merge_collinear_cluster(
            cluster, gap_tolerance_ft, openings, opening_perp_tolerance_ft, opening_width_slack_ft
        ))

    return result


def _line_pair_overlap_ft(line1, line2):
    """Calcula a sobreposicao (em pes), medida ao longo da direcao de
    `line1`, entre `line1` e a projecao de `line2` sobre essa mesma
    direcao.

    Devolve (overlap_ft, length1, length2): `length1`/`length2` sao os
    comprimentos originais de cada linha, usados por quem chamar para
    normalizar a sobreposicao como FRACAO da menor das duas (ver
    lines_overlap_enough e find_wall_pairs) - o que faz o criterio
    funcionar igualmente bem para uma parede de 6 metros ou para uma
    boneca de 12cm, sem depender de nenhum valor fixo em cm.
    """
    p0, p1 = line1.GetEndPoint(0), line1.GetEndPoint(1)
    direction = (p1 - p0).Normalize()
    length1 = p0.DistanceTo(p1)

    q0, q1 = line2.GetEndPoint(0), line2.GetEndPoint(1)
    length2 = q0.DistanceTo(q1)
    t_q0 = (q0 - p0).DotProduct(direction)
    t_q1 = (q1 - p0).DotProduct(direction)
    t2_lo, t2_hi = min(t_q0, t_q1), max(t_q0, t_q1)

    overlap_lo = max(0.0, t2_lo)
    overlap_hi = min(length1, t2_hi)
    overlap_ft = max(0.0, overlap_hi - overlap_lo)
    return overlap_ft, length1, length2


def lines_overlap_enough(line1, line2):
    """Confirma que duas linhas paralelas realmente correm lado a lado
    (representam a mesma parede), e nao apenas estao proximas e paralelas
    sem nenhuma relacao real entre si.

    Aceita o par quando a sobreposicao cobre pelo menos
    MIN_WALL_SEGMENT_OVERLAP_RATIO do comprimento da MENOR das duas linhas
    (ver a nota junto a essa constante para o motivo de usar uma FRACAO em
    vez de um piso fixo em cm) - um piso absoluto minusculo
    (MIN_WALL_SEGMENT_ABS_FLOOR_FT) ainda protege contra sobreposicoes
    numericamente degeneradas.

    Isso e' SOMENTE um criterio de validacao do pareamento - nao recorta,
    nao divide e nao gera "sobras" de nenhuma linha. Uma vez validado, o
    par usa as duas linhas INTEIRAS (ver create_centerline) para gerar a
    parede, preservando o comprimento completo mesmo que isso a faca se
    sobrepor a outras paredes em encontros em T, L, Cruz (+) ou qualquer
    outra configuracao. Sobreposicao entre paredes e' aceitavel e esperada;
    este script nao tenta elimina-la.
    """
    overlap_ft, length1, length2 = _line_pair_overlap_ft(line1, line2)
    if overlap_ft < MIN_WALL_SEGMENT_ABS_FLOOR_FT:
        return False
    shorter_length = min(length1, length2)
    if shorter_length < 1e-9:
        return False
    return (overlap_ft / shorter_length) >= MIN_WALL_SEGMENT_OVERLAP_RATIO
