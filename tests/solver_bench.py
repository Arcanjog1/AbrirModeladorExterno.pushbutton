# -*- coding: utf-8 -*-
"""Banco de medicao e ASSINATURA do Solver 18 (Etapa 4, "Lancar Blocos").

Existe por causa do travamento real relatado em producao (2026-08-27, planta
de 306 eixos: o solver ficava ~55 minutos parado em 99%, janela do Revit em
"Nao esta respondendo"). A causa era `validate_same_course_collision`
comparando TODAS as pecas contra todas depois da ultima parede - 95% do tempo
total no profiler - mais tres varreduras "lista inteira por parede". Ver os
comentarios de `_collision_candidate_pairs` / `_placed_index_near_wall` em
core/engine/wall_stepper.py.

Este arquivo serve a DOIS propositos, e o segundo e' o mais importante:

1. MEDIR (`bench`) - quanto tempo o solver leva numa planta sintetica de
   tamanho controlado, para provar que uma mudanca acelerou (ou nao) e que o
   escalonamento continua LINEAR, nao quadratico. Um solver que dobra de
   tempo quando a planta dobra esta' saudavel; um que quadruplica voltou a
   ter um laco todos-contra-todos em algum lugar.

2. PROVAR QUE NADA MUDOU (`fingerprint`) - toda otimizacao aqui e' de ACESSO
   AOS DADOS, nunca de regra de modulacao. A assinatura abaixo captura o que
   o solver DECIDE (posicao, codigo, rotacao, espelhamento e variante de cada
   peca, mais colisoes, validacoes, auditoria de amarracao e vaos de porta) e
   reduz tudo a um sha256. Se o sha256 nao muda, nenhuma peca mudou de lugar,
   de tipo ou de orientacao - e' a unica forma barata de mexer num solver de
   17 mil linhas sem depender de inspecao visual no Revit.

   VALOR DE REFERENCIA (cenarios padrao, apos a otimizacao de 2026-08-27):

       9413aad03627387d3a3ca548ab6705ee76bf36bf027ca2debb54f6dc5b28e88d

   Esse numero SO' vale para os `SCENARIOS` definidos aqui. Mudar a grade, as
   aberturas ou o numero de fiadas muda a assinatura sem que nada esteja
   errado - por isso os cenarios estao versionados junto, e nao devem ser
   alterados sem trocar tambem o valor de referencia acima (e dizer por que).

Roda FORA do Revit, com os dubles de tests/revit_stubs.py (geometria XYZ/Line
de verdade). Uso:

    python tests/solver_bench.py                # mede os tamanhos padrao
    python tests/solver_bench.py --bench 12 12  # mede uma grade especifica
    python tests/solver_bench.py --profile 8 8  # perfil por funcao (cProfile)
    python tests/solver_bench.py --fingerprint  # imprime o sha256 e compara
    python tests/solver_bench.py --phases 12 12 # tempo do laco x etapa final
"""

import cProfile
import hashlib
import io
import json
import os
import pstats
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import load_script  # noqa: E402

m = load_script.load()

F = m.FEET_PER_METER

# Assinatura esperada dos SCENARIOS abaixo - ver o docstring do modulo.
REFERENCE_FINGERPRINT = "9413aad03627387d3a3ca548ab6705ee76bf36bf027ca2debb54f6dc5b28e88d"

# Pe-direito tipico do projeto: 3,00m / 20cm por fiada = 15 fiadas fisicas.
NUM_COURSES = 15


def ft(cm):
    return cm / 100.0 * F


def seg(x0, y0, x1, y1):
    return m.Line.CreateBound(m.XYZ(ft(x0), ft(y0), 0.0), m.XYZ(ft(x1), ft(y1), 0.0))


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


# Mesmas medidas de celula da familia real do projeto - identico ao CATALOG de
# tests/test_script.py (duplicado aqui de proposito: aquele arquivo e' uma
# suite de casos com ~4400 linhas, importa-lo so' pelo catalogo arrastaria a
# execucao de todos os testes junto).
CATALOG = {
    "B39": _block("B39", 39, [_cell(-9.9, 15.7), _cell(9.9, 15.8)]),
    "B34": _block("B34", 34, [_cell(-10.2, 10.7), _cell(7.4, 15.7)]),
    "B54": _block("B54", 54, [_cell(-19.5, 15.8), _cell(0.0, 12.5), _cell(19.5, 15.8)]),
    "B19": _block("B19", 19, [_cell(0.0, 15.7)]),
    "C09": _block("C09", 9, []),
    "C04": _block("C04", 4, []),
}


def build_grid_lines(nx, ny, step_cm=350.0):
    """Eixos de uma planta em grade `nx` x `ny` comodos - (nx+1)*ny eixos
    horizontais mais (ny+1)*nx verticais. Grade e' o pior caso realista para
    o solver: maximiza encontros L/T/X (cada cruzamento e' um no') e mantem
    as paredes proximas o suficiente para o teste de colisao entre vizinhas
    ter trabalho de verdade."""
    lines = []
    for j in range(ny + 1):
        for i in range(nx):
            lines.append(seg(i * step_cm, j * step_cm, (i + 1) * step_cm, j * step_cm))
    for i in range(nx + 1):
        for j in range(ny):
            lines.append(seg(i * step_cm, j * step_cm, i * step_cm, (j + 1) * step_cm))
    return lines


def make_plan(nx, ny, opening_every=3):
    """Planta completa pronta para o solver: (nodes, walls, end_to_node,
    openings_per_wall).

    As aberturas alternam de proposito entre PORTA (peitoril 0 - ativa em
    todas as fiadas), JANELA (peitoril 90cm - so' ativa na faixa vertical do
    vao, o que FORCA o agrupamento em bandas de
    `_group_course_indices_by_opening_band`) e NENHUMA. Sem esse mix o
    benchmark rodaria uma banda so' e nao exercitaria o caminho real."""
    walls = [(line, ft(14.0), (False, False)) for line in build_grid_lines(nx, ny)]
    walls, junction_map = m.extend_wall_ends_to_junctions(walls, m.JUNCTION_FACE_SEARCH_FT)
    nodes, end_to_node = m.build_wall_graph(walls, junction_map)
    openings = []
    for idx in range(len(walls)):
        if idx % opening_every == 0:
            openings.append([(ft(120.0), ft(200.0), ft(0.0), ft(210.0))])    # porta
        elif idx % opening_every == 1:
            openings.append([(ft(100.0), ft(220.0), ft(90.0), ft(200.0))])   # janela
        else:
            openings.append([])
    return nodes, walls, end_to_node, openings


def solve(nx, ny, num_courses=NUM_COURSES):
    nodes, walls, end_to_node, openings = make_plan(nx, ny)
    result = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings, CATALOG, ft(0.0), num_courses,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
    )
    return result, walls


# ------------------------------------------------------------- assinatura
# Cenarios da assinatura de referencia - NAO alterar sem trocar tambem
# REFERENCE_FINGERPRINT (ver docstring do modulo).
SCENARIOS = [(2, 2), (3, 2), (3, 3)]


def _scenario_signature(result):
    """Tudo que o solver DECIDE, em forma comparavel. Coordenadas arredondadas
    em 9 casas: absorve so' o ruido de ponto flutuante da conversao pes<->cm,
    muito abaixo de qualquer diferenca fisica (1e-9 ft ~ 3e-8 cm)."""
    candidates = result["candidates"]
    return {
        "n_cand": len(candidates),
        "collisions": [list(pair) for pair in result["collisions"]],
        "non_modular": len(result["non_modular"]),
        "jamb_exceptions": len(result["jamb_exceptions"]),
        "alignment_conflicts": len(result.get("alignment_conflicts") or []),
        "intersection_failures": len(result["intersection_failures"]),
        "door_void": [
            (v["wall_idx"], v["opening_index"], round(v["overlap_cm"], 6))
            for v in result.get("door_void_violations") or []
        ],
        "validations": [
            (v.get("ok"), sorted(v.get("checks", {}).items()))
            for v in result.get("validations") or []
        ],
        "bond_audits": sorted(
            (k, v["ok"], tuple(v["problems"]), round(v["penalty"], 6))
            for k, v in (result.get("wall_bond_audits") or {}).items()
        ),
        "pieces": [
            (
                c.get("wall_idx"), c.get("course"), c.get("logical_code"),
                round(c["origin_world"].X, 9), round(c["origin_world"].Y, 9),
                round(c["origin_world"].Z, 9),
                round(c["x_dir"].X, 9), round(c["x_dir"].Y, 9),
                c.get("mirrored"), c.get("rotation_deg"), c.get("course_variant"),
                c.get("placement_reason"),
            )
            for c in candidates
        ],
        "course_candidates": sorted(
            (ci, len(cs)) for ci, cs in (result.get("course_candidates") or {}).items()
        ),
    }


def fingerprint(scenarios=None):
    """(sha256, dados) dos `scenarios` - ver o docstring do modulo."""
    data = {}
    for nx, ny in (scenarios or SCENARIOS):
        result, _walls = solve(nx, ny)
        data["grid_{}x{}".format(nx, ny)] = _scenario_signature(result)
    blob = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), data


# ------------------------------------------------------------------ bench
def bench(nx, ny, profile=False):
    nodes, walls, end_to_node, openings = make_plan(nx, ny)
    print("eixos: {} | nos: {} | fiadas: {}".format(len(walls), len(nodes), NUM_COURSES))
    profiler = cProfile.Profile() if profile else None
    if profiler:
        profiler.enable()
    started = time.time()
    result = m.solve_building_blocks_all_courses(
        nodes, walls, end_to_node, openings, CATALOG, ft(0.0), NUM_COURSES,
        variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
    )
    elapsed = time.time() - started
    if profiler:
        profiler.disable()
    print("TOTAL: {:.2f}s | bandas: {} | pecas: {} | colisoes: {}".format(
        elapsed, len(result["bands"]), len(result["candidates"]), len(result["collisions"])))
    if profiler:
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("tottime").print_stats(20)
        print(stream.getvalue())
    return elapsed


def phases(nx, ny):
    """Separa o tempo do laco parede-a-parede (que reporta progresso na tela)
    do tempo da ETAPA FINAL (que roda depois da ultima parede). Foi a etapa
    final que causou o travamento de 2026-08-27 - e' o numero a vigiar."""
    acc = {"collisions": 0.0, "door": 0.0, "orient": 0.0, "audit": 0.0, "per_wall": 0.0}
    stepper = sys.modules.get("core.engine.wall_stepper")

    def timed(fn, key, global_threshold=None):
        def inner(*args, **kwargs):
            started = time.time()
            try:
                return fn(*args, **kwargs)
            finally:
                delta = time.time() - started
                if global_threshold is not None and len(args[0]) <= global_threshold:
                    acc["per_wall"] += delta   # chamada por parede, nao a final
                else:
                    acc[key] += delta
        return inner

    originals = {
        "vscc": m.validate_same_course_collision,
        "door": m.find_door_void_violations,
        "orient": m.orient_compensator_candidates,
        "audit": m.audit_all_walls_bond_quality,
    }
    m.validate_same_course_collision = timed(originals["vscc"], "collisions", 500)
    m.find_door_void_violations = timed(originals["door"], "door")
    m.orient_compensator_candidates = timed(originals["orient"], "orient")
    m.audit_all_walls_bond_quality = timed(originals["audit"], "audit")
    if stepper is not None:
        stepper.validate_same_course_collision = m.validate_same_course_collision
        stepper.find_door_void_violations = m.find_door_void_violations
    try:
        nodes, walls, end_to_node, openings = make_plan(nx, ny)
        started = time.time()
        result = m.solve_building_blocks_all_courses(
            nodes, walls, end_to_node, openings, CATALOG, ft(0.0), NUM_COURSES,
            variants_per_course=m.PIER_LAYOUT_VARIANTS_PER_COURSE,
        )
        total = time.time() - started
    finally:
        m.validate_same_course_collision = originals["vscc"]
        m.find_door_void_violations = originals["door"]
        m.orient_compensator_candidates = originals["orient"]
        m.audit_all_walls_bond_quality = originals["audit"]
        if stepper is not None:
            stepper.validate_same_course_collision = originals["vscc"]
            stepper.find_door_void_violations = originals["door"]

    final = acc["collisions"] + acc["door"] + acc["orient"] + acc["audit"]
    print("eixos: {} | pecas: {}".format(len(walls), len(result["candidates"])))
    print("TOTAL .................. {:7.2f}s".format(total))
    print("  laco parede-a-parede   {:7.2f}s  (reporta progresso na tela)".format(total - final))
    print("  ETAPA FINAL .......... {:7.2f}s  ({:.1f}% do total)".format(
        final, 100.0 * final / total if total else 0.0))
    print("     colisoes globais... {:7.2f}s".format(acc["collisions"]))
    print("     vaos de porta ..... {:7.2f}s".format(acc["door"]))
    print("     compensadores ..... {:7.2f}s".format(acc["orient"]))
    print("     auditoria amarr.... {:7.2f}s".format(acc["audit"]))
    return total, final


# ------------------------------------------------------------------- CLI
DEFAULT_SIZES = [(3, 3), (6, 6), (8, 8), (12, 12)]


def main(argv):
    if "--fingerprint" in argv:
        digest, _data = fingerprint()
        print("sha256    : {}".format(digest))
        print("referencia: {}".format(REFERENCE_FINGERPRINT))
        if digest == REFERENCE_FINGERPRINT:
            print("OK - o solver decide exatamente as mesmas pecas de sempre.")
            return 0
        print("DIVERGIU - alguma peca mudou de posicao/tipo/orientacao. Se a")
        print("mudanca era INTENCIONAL, atualizar REFERENCE_FINGERPRINT e")
        print("explicar no commit o que mudou e por que.")
        return 1

    sizes = [(int(argv[i + 1]), int(argv[i + 2]))
             for i, a in enumerate(argv) if a in ("--bench", "--profile", "--phases")
             and i + 2 < len(argv)]

    if "--phases" in argv:
        for nx, ny in sizes or [(12, 12)]:
            phases(nx, ny)
        return 0

    profile = "--profile" in argv
    for nx, ny in sizes or DEFAULT_SIZES:
        bench(nx, ny, profile=profile)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
