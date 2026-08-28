# -*- coding: utf-8 -*-
"""Calculadora manual de modulação, sem dependência da interface.

O solver de edifícios (``wall_stepper``) continua sendo a fonte de verdade
quando há geometria completa de Walls/encontros. Este módulo atende ao caso
manual: recebe o comprimento e as condições declaradas nas duas pontas,
transforma as amarrações em peças obrigatórias conhecidas e enumera somente
preenchimentos que fecham com as juntas do motor.

Ele não inventa uma subtração de comprimento. Um T sem o papel geométrico da
parede, por exemplo, devolve as duas interpretações permitidas (principal e
boneca), marcadas como hipótese para o usuário escolher; para uma solução
definitiva de L/T/X use a captura do projeto, que chama ``wall_stepper``.
"""

from __future__ import division

import math

from engine_bridge import BLOCK_JOINT_CM, BLOCK_OPENING_JOINT_CM


DEFAULT_BLOCK_CATALOG = {
    "B54": {"length_cm": 54.0, "is_special_bond": True},
    "B39": {"length_cm": 39.0},
    "B34": {"length_cm": 34.0, "is_special_bond": True},
    "B19": {"length_cm": 19.0},
    "C09": {"length_cm": 9.0, "is_compensator": True},
    "C04": {"length_cm": 4.0, "is_compensator": True},
}

OPEN_TIES = set((
    "", "NONE", "NENHUMA", "LIVRE", "FREE", "OPEN", "PAREDE_LIVRE", "OPENING",
))
L_TIES = set(("L", "QUINA", "CORNER", "ENCONTRO_L"))
X_TIES = set(("X", "CRUZ", "CRUZAMENTO", "X_INTERSECTION"))
T_TIES = set(("T", "ENCONTRO_T", "T_INTERSECTION"))
MAX_ENUMERATED_LAYOUTS = 5000


def _norm_tie(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _normalise_catalog(catalog, allowed_codes=None):
    source = catalog or DEFAULT_BLOCK_CATALOG
    requested = set(str(code) for code in allowed_codes) if allowed_codes else None
    result = {}
    for raw_code, raw in source.items():
        code = str(raw.get("logical_code") or raw_code).upper()
        if requested is not None and code not in requested:
            continue
        try:
            length = float(raw.get("length_cm") or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(length) or length <= 0:
            continue
        result[code] = {
            "code": code,
            "length_cm": round(length, 4),
            "is_compensator": bool(raw.get("is_compensator")) or code in ("C09", "C04"),
            "is_special_bond": bool(raw.get("is_special_bond")) or code in ("B54", "B34"),
        }
    return result


def _tie_variants(tie, side, catalog):
    """Peças obrigatórias conhecidas para uma ponta declarada manualmente."""
    tie = _norm_tie(tie)
    if tie in OPEN_TIES:
        return [{"blocks": [], "label": "ponta livre", "assumption": None}]
    if tie in L_TIES:
        return [{"blocks": ["B34"], "label": "amarração em L", "assumption": None}]
    if tie in X_TIES:
        return [{"blocks": ["B54"], "label": "cruzamento", "assumption": None}]
    if tie in T_TIES:
        return [
            {
                "blocks": ["B54"], "label": "T — parede principal",
                "assumption": "T calculado como parede principal (B54)",
            },
            {
                "blocks": ["B34"], "label": "T — boneca",
                "assumption": "T calculado como boneca/incoming wall (B34)",
            },
        ]
    return [{
        "blocks": [], "label": "condição não resolvida",
        "assumption": "A amarração '{}' precisa de geometria do projeto; não foi tratada como reserva manual.".format(tie or "vazia"),
        "unsupported": True,
    }]


def _sequence_length(sequence, catalog):
    if not sequence:
        return 0.0
    return sum(catalog[code]["length_cm"] for code in sequence) + (len(sequence) - 1) * BLOCK_JOINT_CM


def _is_valid_sequence(sequence, left_blocks, right_blocks, catalog):
    compensator_runs = 0
    compensator_count = 0
    for index, code in enumerate(sequence):
        if catalog[code]["is_compensator"]:
            compensator_count += 1
            compensator_runs += 1
            if compensator_runs > 1:
                return False, "compensadores consecutivos"
        else:
            compensator_runs = 0
    if compensator_count > 1:
        return False, "mais de um compensador no trecho"

    # B19 só pode fechar uma ponta realmente aberta; nunca nasce no meio ou
    # encostado a uma amarração L/T/X.
    if "B19" in sequence:
        if sequence.count("B19") > 1:
            return False, "mais de um meio-bloco"
        b19_index = sequence.index("B19")
        allowed_at_start = not left_blocks and b19_index == 0
        allowed_at_end = not right_blocks and b19_index == len(sequence) - 1
        if not (allowed_at_start or allowed_at_end):
            return False, "meio-bloco fora de ponta livre"
    return True, None


def _rank_solution(sequence, left_count, right_count, catalog, priority):
    central = sequence[left_count:len(sequence) - right_count if right_count else len(sequence)]
    compensators = sum(1 for code in central if catalog[code]["is_compensator"])
    pastilhas = central.count("C04")
    half_blocks = central.count("B19")
    central_b34 = central.count("B34")
    special = sum(1 for code in central if catalog[code]["is_special_bond"])
    main_blocks = central.count("B39")
    score = 100.0
    score -= compensators * 22.0 + pastilhas * 8.0 + half_blocks * 11.0
    score -= central_b34 * 3.0 + max(0, special - central_b34) * 4.0
    score -= max(0, len(central) - main_blocks) * 0.5
    if priority == "fewest_blocks":
        score -= len(sequence) * 4.0
    elif priority == "fewest_small":
        score -= (compensators + half_blocks + central_b34) * 10.0
    elif priority == "economy":
        score -= len(sequence) * 2.5
    return max(0.0, round(score, 1)), {
        "main_blocks": main_blocks,
        "special_blocks": special,
        "compensators": compensators,
        "pastilhas": pastilhas,
        "half_blocks": half_blocks,
        "total_blocks": len(sequence),
    }


def _positions(sequence, catalog):
    position = 0.0
    result = []
    for index, code in enumerate(sequence):
        length = catalog[code]["length_cm"]
        result.append({
            "code": code, "start_cm": round(position, 3),
            "end_cm": round(position + length, 3), "length_cm": length,
        })
        position += length + (BLOCK_JOINT_CM if index < len(sequence) - 1 else 0.0)
    return result


def _enumerate_center_sequences(length_cm, left_blocks, right_blocks, catalog, max_candidates):
    """Enumera ordens de preenchimento que fecham com juntas reais."""
    fixed = list(left_blocks) + list(right_blocks)
    fixed_length = _sequence_length(fixed, catalog)
    # Um bloco central sempre toca pelo menos um bloco obrigatório quando
    # existe amarração; sem amarração, a primeira peça não tem junta antes.
    results = []
    codes = sorted(catalog, key=lambda code: (-catalog[code]["length_cm"], code))

    def visit(central, occupied):
        if len(results) >= max_candidates:
            return
        full = list(left_blocks) + central + list(right_blocks)
        total = _sequence_length(full, catalog)
        if abs(total - length_cm) <= 1e-6:
            valid, _reason = _is_valid_sequence(full, left_blocks, right_blocks, catalog)
            if valid:
                results.append(full)
            return
        if total > length_cm + 1e-6:
            return
        for code in codes:
            # Cada inserção precisa recomputar a junta correta entre os três
            # grupos; o cálculo pequeno é deliberadamente explícito para não
            # transformar junta/amarração em uma subtração escondida.
            candidate = central + [code]
            candidate_full = list(left_blocks) + candidate + list(right_blocks)
            candidate_total = _sequence_length(candidate_full, catalog)
            if candidate_total <= length_cm + 1e-6:
                visit(candidate, candidate_total)

    # Caso sem preenchimento entre duas amarrações.
    if abs(fixed_length - length_cm) <= 1e-6:
        valid, _reason = _is_valid_sequence(fixed, left_blocks, right_blocks, catalog)
        if valid:
            results.append(fixed)
    visit([], fixed_length)
    return results


def calculate_wall_solutions(request, catalog=None):
    """Calcula e classifica variações válidas para uma parede manual.

    Entrada mínima: ``length_cm``, ``left_tie`` e ``right_tie``. O catálogo
    pode ser o exportado do Revit; sem ele usa o catálogo padrão oficial.
    """
    request = request or {}
    try:
        length_cm = float(request.get("length_cm"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Informe um comprimento numérico em centímetros."}
    if not math.isfinite(length_cm) or length_cm <= 0:
        return {"ok": False, "error": "O comprimento da parede deve ser positivo."}
    blocks = _normalise_catalog(catalog or request.get("catalog"), request.get("allowed_codes"))
    if not blocks:
        return {"ok": False, "error": "Nenhum bloco utilizável foi informado no catálogo."}

    max_results = max(1, min(int(request.get("max_results") or 10), 100))
    priority = str(request.get("priority") or "balanced")
    left_options = _tie_variants(request.get("left_tie"), "left", blocks)
    right_options = _tie_variants(request.get("right_tie"), "right", blocks)
    all_solutions = []
    rejected = []
    for left in left_options:
        for right in right_options:
            required = left["blocks"] + right["blocks"]
            missing = [code for code in required if code not in blocks]
            if missing:
                rejected.append("A amarração exige {} ausente(s) no catálogo.".format(", ".join(missing)))
                continue
            if left.get("unsupported") or right.get("unsupported"):
                rejected.append(left.get("assumption") or right.get("assumption"))
                continue
            layouts = _enumerate_center_sequences(
                length_cm, left["blocks"], right["blocks"], blocks, MAX_ENUMERATED_LAYOUTS
            )
            for sequence in layouts:
                score, metrics = _rank_solution(
                    sequence, len(left["blocks"]), len(right["blocks"]), blocks, priority
                )
                assumptions = [item for item in (left.get("assumption"), right.get("assumption")) if item]
                all_solutions.append({
                    "score": score,
                    "sequence": sequence,
                    "blocks": _positions(sequence, blocks),
                    "left_tie": left["label"], "right_tie": right["label"],
                    "left_required": left["blocks"], "right_required": right["blocks"],
                    "assumptions": assumptions,
                    "metrics": metrics,
                    "occupied_length_cm": round(_sequence_length(sequence, blocks), 3),
                })
    # Uma mesma ordem pode surgir de variantes de T equivalentes. Mantém a
    # de maior score e uma explicação única.
    unique = {}
    for solution in all_solutions:
        key = (tuple(solution["sequence"]), solution["left_tie"], solution["right_tie"])
        if key not in unique or solution["score"] > unique[key]["score"]:
            unique[key] = solution
    ranked = sorted(
        unique.values(),
        key=lambda item: (-item["score"], item["metrics"]["compensators"], item["metrics"]["total_blocks"], item["sequence"]),
    )
    for index, solution in enumerate(ranked):
        solution["rank"] = index + 1
        solution["classification"] = "RECOMENDADA" if index == 0 else ("BOA" if solution["score"] >= 85 else "ACEITÁVEL")
    return {
        "ok": True,
        "length_cm": length_cm,
        "course": request.get("course") or 1,
        "joint_cm": BLOCK_JOINT_CM,
        "opening_joint_cm": BLOCK_OPENING_JOINT_CM,
        "catalog_source": "revit" if catalog or request.get("catalog") else "padrão do projeto",
        "total_found": len(ranked),
        "truncated": len(ranked) > max_results,
        "solutions": ranked[:max_results],
        "rejected_conditions": sorted(set(item for item in rejected if item)),
        "note": (
            "A calculadora usa juntas e peças obrigatórias da amarração. "
            "L/T/X com geometria real de paredes deve ser confirmado pelo solver completo do projeto."
        ),
    }


def calculate_project_solutions(request, catalog=None):
    """Modo lote: resolve cada parede independente e declara o limite global."""
    walls = list((request or {}).get("walls") or [])
    return {
        "ok": True,
        "mode": "independent_walls",
        "global_optimization": "pending_geometry_graph",
        "walls": [
            dict(calculate_wall_solutions(wall, catalog=catalog), wall_id=wall.get("id") or "P{}".format(index + 1))
            for index, wall in enumerate(walls)
        ],
        "note": "A otimização global exige o grafo geométrico L/T/X da captura Revit; este modo não finge resolver dependências que não recebeu.",
    }
