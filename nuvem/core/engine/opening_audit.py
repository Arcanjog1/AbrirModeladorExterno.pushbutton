# -*- coding: utf-8 -*-
"""Auditoria de aberturas em alvenaria JA CONSTRUIDA (vergas/contravergas/
canaletas/blocos cortados) - extraida verbatim de `core/wall_modeling.py`,
ver REGRAS_MODULACAO_BLOCOS.md secao 10 (fonte de verdade destas regras;
qualquer mudanca de comportamento aqui deve atualizar o campo "Status" do
item correspondente la').

DIFERENTE do resto do motor (que GERA blocos a partir de paredes/CAD
novos), este modulo LE um modelo JA CONSTRUIDO em blocos e reconstroi a
geometria das aberturas a partir do proprio layout de pecas colocadas -
util tanto pra auditar um modelo existente quanto, no futuro, pra
alimentar o solver com o sistema de abertura certo (10.1) antes de gerar
uma verga nova.

`wall_modeling.py` importa tudo daqui (`from core.engine.opening_audit
import *`, SEM fallback) pela mesma razao de `core.engine.geometry`/
`core.engine.modulation_math`: dependencia obrigatoria, call-sites por
nome solto continuam funcionando sem alteracao.

Modulo 100% PURO: nenhuma dependencia do Revit - so' tuplas/numeros/
strings/dicts. Roda em qualquer Python puro."""

__all__ = [
    "OPENING_SYSTEM_1_VERGA_CONTRAVERGA", "OPENING_SYSTEM_2_CANALETA",
    "OPENING_SYSTEM_UNKNOWN", "OPENING_GAP_MIN_CM", "OPENING_GAP_MAX_CM",
    "OPENING_MIN_CONSEC_COURSES", "OPENING_RUN_EDGE_MATCH_TOLERANCE_CM",
    "OPENING_DOOR_TOUCHES_BASE_TOLERANCE_CM", "CUT_BLOCK_JAMB_JUSTIFICATION_MAX_CM",
    "_family_name_matches_keyword", "is_canaleta_family_name",
    "is_cortado_family_name", "is_verga_or_contraverga_family_name",
    "merge_axis_intervals", "gaps_between_intervals",
    "detect_wall_openings_from_courses", "nearest_opening_jamb_distance_cm",
    "is_cut_block_justified_by_opening",
]

OPENING_SYSTEM_1_VERGA_CONTRAVERGA = "SISTEMA_1_VERGA_CONTRAVERGA"
OPENING_SYSTEM_2_CANALETA = "SISTEMA_2_CANALETA"
OPENING_SYSTEM_UNKNOWN = "SISTEMA_DESCONHECIDO"

# Gaps fora desta faixa nao contam como candidato a abertura: menores que
# OPENING_GAP_MIN_CM sao junta/ruido de amarracao (ex.: o vao que alterna
# entre fiadas num encontro T real); maiores que OPENING_GAP_MAX_CM sao
# quase certamente OUTRA parede/trecho, nao um vao na MESMA parede -
# medido em TORRE EASY-LO-R00 (REGRAS_MODULACAO_BLOCOS.md secao 10):
# largura de vao real ficou concentrada em ~90/130/170cm, nunca >260cm.
OPENING_GAP_MIN_CM = 50.0
OPENING_GAP_MAX_CM = 260.0
# Altura minima (em numero de fiadas) pra um vazio persistente contar como
# abertura de verdade, nao um nozinho de amarracao de 1 fiada so'.
OPENING_MIN_CONSEC_COURSES = 4
# Tolerancia de casamento de borda (cm) entre gaps de fiadas consecutivas
# ao formar um "trecho" vertical de vazio - absorve o pequeno deslocamento
# horizontal natural do desencontro de junta entre fiadas (secao 10.6).
OPENING_RUN_EDGE_MATCH_TOLERANCE_CM = 15.0
# Um vao cuja base fica a ate' esta distancia da fiada mais baixa da
# PROPRIA linha de parede reconstruida conta como "toca o chao" (porta,
# secao 10.4) - senao e' janela (peitoril acima da base do trecho).
OPENING_DOOR_TOUCHES_BASE_TOLERANCE_CM = 25.0
# Distancia maxima (cm) entre um bloco CORTADO e a jamba de abertura mais
# proxima pra contar como "justificado por apoio de verga/contraverga"
# (secao 10.5) - medido: 65% dos cortados reais de TORRE EASY-LO-R00
# ficaram dentro dessa distancia de alguma jamba.
CUT_BLOCK_JAMB_JUSTIFICATION_MAX_CM = 60.0


def _family_name_matches_keyword(family_name, keyword):
    return keyword in (family_name or "").upper()


def is_canaleta_family_name(family_name):
    """Peca-canaleta (verga/contraverga/cinta do Sistema 2, secao 10.1/10.2)."""
    return _family_name_matches_keyword(family_name, "CANALETA")


def is_cortado_family_name(family_name):
    """Variante cortada (meia-altura ou outra reducao) de um bloco comum."""
    return _family_name_matches_keyword(family_name, "CORTADO")


def is_verga_or_contraverga_family_name(family_name):
    """Familia dedicada de verga/contraverga do Sistema 1 (secao 10.1) -
    pega tanto `VERGA JANELA` quanto `CONTRAVERGA`/`CONTRAVERGA1` (o termo
    'VERGA' aparece nos dois nomes reais medidos no projeto)."""
    return _family_name_matches_keyword(family_name, "VERGA")


def merge_axis_intervals(intervals, joint_tolerance_cm=3.0):
    """Funde intervalos `(inicio_cm, fim_cm)` que se tocam ou se sobrepoem
    (folga de ate' `joint_tolerance_cm`, pra' absorver a junta normal entre
    blocos adjacentes sem fundir dois blocos que na verdade tem um vao
    real entre eles). Pura, sem dependencia do Revit - testavel offline."""
    ordered = sorted(intervals)
    merged = []
    for start, end in ordered:
        if merged and start - merged[-1][1] <= joint_tolerance_cm:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def gaps_between_intervals(merged_intervals):
    """Devolve os vazios `(inicio_cm, fim_cm)` ENTRE intervalos ja'
    fundidos (ver `merge_axis_intervals`) - nao inclui o vazio antes do
    primeiro nem depois do ultimo (essas pontas sao "fim de parede", nao
    "vao no meio da parede"). Pura, testavel offline."""
    gaps = []
    for i in range(len(merged_intervals) - 1):
        gaps.append((merged_intervals[i][1], merged_intervals[i + 1][0]))
    return gaps


def detect_wall_openings_from_courses(courses):
    """Reconstroi as aberturas (vaos) de uma linha de parede a partir do
    layout REAL de pecas ja colocadas - ver REGRAS_MODULACAO_BLOCOS.md
    secao 10 (10.1/10.4). Pura (so' tuplas/numeros), testavel offline sem
    Revit - o chamador real (`audit_existing_masonry_openings`) so' faz a
    leitura do Revit e monta `courses` nesse formato antes de chamar isto.

    `courses`: lista de `(z_cm, [(inicio_cm, fim_cm, nome_familia), ...])`,
    UMA entrada por fiada distinta da MESMA linha de parede (mesmo nivel,
    mesma orientacao, mesma coordenada perpendicular), em QUALQUER ordem
    de z (a funcao ordena).

    Devolve lista de dicts:
        {"x_range": (ini_cm, fim_cm), "width_cm": float,
         "z_range": (z_lo, z_hi), "n_courses": int,
         "tipo_provavel": "PORTA" | "JANELA"}
    "PORTA" quando o vao toca a fiada mais baixa da PROPRIA linha
    (`OPENING_DOOR_TOUCHES_BASE_TOLERANCE_CM`) - nunca espera contraverga
    nesse caso (secao 10.4). "JANELA" caso contrario."""
    ordered = sorted(courses, key=lambda c: c[0])
    if len(ordered) < OPENING_MIN_CONSEC_COURSES:
        return []
    z_values = [z for z, _ in ordered]
    body_bottom = min(z_values)

    course_gaps = {}
    for z_cm, intervals in ordered:
        merged = merge_axis_intervals([(s, e) for s, e, _fam in intervals])
        gaps = [(s, e) for s, e in gaps_between_intervals(merged)
                if OPENING_GAP_MIN_CM <= (e - s) <= OPENING_GAP_MAX_CM]
        course_gaps[z_cm] = gaps

    openings = []
    used = set()
    for i, (z_cm, _intervals) in enumerate(ordered):
        for gi, (gap_start, gap_end) in enumerate(course_gaps.get(z_cm, [])):
            signature = (z_cm, gi)
            if signature in used:
                continue
            used.add(signature)
            run_courses = [z_cm]
            run_start, run_end = gap_start, gap_end
            for z2, _iv2 in ordered[i + 1:]:
                match = None
                for gj, (gs2, ge2) in enumerate(course_gaps.get(z2, [])):
                    if (z2, gj) in used:
                        continue
                    if (abs(gs2 - run_start) <= OPENING_RUN_EDGE_MATCH_TOLERANCE_CM
                            and abs(ge2 - run_end) <= OPENING_RUN_EDGE_MATCH_TOLERANCE_CM):
                        match = (gj, gs2, ge2)
                        break
                if match is None:
                    break
                gj, gs2, ge2 = match
                used.add((z2, gj))
                run_courses.append(z2)
                run_start = min(run_start, gs2)
                run_end = max(run_end, ge2)
            if len(run_courses) >= OPENING_MIN_CONSEC_COURSES:
                z_lo, z_hi = min(run_courses), max(run_courses)
                is_door_like = (z_lo <= body_bottom + OPENING_DOOR_TOUCHES_BASE_TOLERANCE_CM)
                openings.append({
                    "x_range": (run_start, run_end),
                    "width_cm": run_end - run_start,
                    "z_range": (z_lo, z_hi),
                    "n_courses": len(run_courses),
                    "tipo_provavel": "PORTA" if is_door_like else "JANELA",
                })
    return openings


def nearest_opening_jamb_distance_cm(position_cm, openings):
    """Distancia (cm) de `position_cm` ate' a jamba (borda) de abertura
    mais proxima, dentre `openings` (formato de `detect_wall_openings_
    from_courses`). `None` se `openings` estiver vazio. Pura, testavel
    offline."""
    if not openings:
        return None
    jamb_positions = []
    for op in openings:
        jamb_positions.append(op["x_range"][0])
        jamb_positions.append(op["x_range"][1])
    return min(abs(position_cm - jamb) for jamb in jamb_positions)


def is_cut_block_justified_by_opening(position_cm, openings,
                                       max_distance_cm=CUT_BLOCK_JAMB_JUSTIFICATION_MAX_CM):
    """Regra 10.5: um bloco CORTADO perto (`max_distance_cm`) de uma jamba
    de abertura tem justificativa geometrica (apoio de verga/contraverga)
    e NAO deveria ser reportado como erro de modulacao so' por ser um
    corte. Devolve `False` (nao justificado por proximidade de abertura -
    pode ainda ser justificado por outro motivo, ex. encontro L/T/X, nao
    coberto por esta funcao) quando `openings` estiver vazio ou a
    distancia exceder o teto. Pura, testavel offline."""
    distance = nearest_opening_jamb_distance_cm(position_cm, openings)
    return distance is not None and distance <= max_distance_cm
