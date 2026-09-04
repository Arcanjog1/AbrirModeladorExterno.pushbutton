# -*- coding: utf-8 -*-
"""Entrada por Walls reais do Revit para o visualizador externo.

O fluxo CAD continua usando `wall_pairing.py`. Este modulo cobre o novo
fluxo em que o usuario seleciona Walls ja existentes no Revit: cada Wall
capturada vira a geometria base, as aberturas sao associadas a ela e a
validacao/preview reaproveita as regras importadas por `engine_bridge`.
"""

import copy
import math
from collections import OrderedDict

from engine_bridge import (
    FEET_PER_METER, JUNCTION_FACE_SEARCH_FT, BLOCK_JOINT_CM,
    XYZ, make_line, point_to_cm,
    build_wall_graph, extend_wall_ends_to_junctions, merge_connected_collinear_walls,
    assign_openings_to_walls,
    build_wall_segments, solve_building_blocks,
)


CM_TO_FT = FEET_PER_METER / 100.0
FT_TO_CM = 100.0 / FEET_PER_METER

FIRST_COURSE_Z_OFFSET_CM = 1.0
OPENING_COURSE_BAND_TOLERANCE_CM = 0.5
MIN_EDITABLE_WALL_LENGTH_CM = 1.0
MIN_EDITABLE_WALL_THICKNESS_CM = 1.0
MIN_EDITABLE_WALL_HEIGHT_CM = 1.0
MIN_EDITABLE_OPENING_WIDTH_CM = 1.0
MIN_EDITABLE_OPENING_HEIGHT_CM = 1.0
_DEPENDENCY_GRAPH_CACHE = OrderedDict()
_DEPENDENCY_GRAPH_CACHE_LIMIT = 8


def _xy_point(value, field_name):
    """Normaliza um ponto editado na interface e rejeita geometria invalida."""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("{} deve conter coordenadas X e Y".format(field_name))
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(component) for component in point):
        raise ValueError("{} contem uma coordenada invalida".format(field_name))
    return point


def _line_projection(point, start, end):
    """Parametro e ponto projetado de ``point`` no eixo ``start -> end``."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        raise ValueError("eixo da parede sem comprimento")
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    return t, (start[0] + t * dx, start[1] + t * dy)


def _point_on_line(start, end, t):
    return [
        round(start[0] + (end[0] - start[0]) * t, 6),
        round(start[1] + (end[1] - start[1]) * t, 6),
    ]


def capture_z_reference_cm(capture):
    """Cota da planta usada como Z=0 no visualizador externo."""
    bases = [
        float(raw.get("base_z_cm") or 0.0)
        for raw in (capture.get("walls") or [])
        if (raw.get("start_cm") or raw.get("start")) and (raw.get("end_cm") or raw.get("end"))
    ]
    return min(bases) if bases else 0.0


def openings_for_capture_view(capture):
    """Copia as aberturas com cotas relativas a planta baixa."""
    reference_cm = capture_z_reference_cm(capture)
    result = []
    for source in capture.get("openings") or []:
        opening = copy.deepcopy(source)
        sill = float(source.get("sill_cm") or 0.0) - reference_cm
        head = float(source.get("head_cm") or (float(source.get("sill_cm") or 0.0) + 220.0)) - reference_cm
        opening["sill_cm"] = round(sill, 3)
        opening["head_cm"] = round(max(sill, head), 3)
        opening["height_cm"] = round(max(0.0, head - sill), 3)
        if source.get("level_elevation_cm") is not None:
            opening["level_elevation_cm"] = round(
                float(source.get("level_elevation_cm")) - reference_cm, 3
            )
        result.append(opening)
    return result


def _capture_graph(capture):
    return _capture_graph_for_raw(
        capture.get("walls") or [], capture.get("openings") or []
    )


def _capture_graph_for_raw(raw_walls, openings_json):
    tuples = []
    raw_by_tuple = []
    skipped = 0
    for raw in raw_walls:
        tup = _wall_tuple(raw)
        if tup is None:
            skipped += 1
            continue
        tuples.append(tup)
        raw_by_tuple.append(raw)
    source_keys = [round(float(raw.get("height_cm") or 0.0), 3) for raw in raw_by_tuple]
    tuples, source_groups = merge_connected_collinear_walls(tuples, source_keys=source_keys)
    raw_by_tuple = [_merged_raw_wall([raw_by_tuple[i] for i in group]) for group in source_groups]
    graph_tuples, junctions_by_index, nodes, end_to_node = _graph_for_tuples(tuples)
    openings_per_wall = _assign_openings_to_raw_walls(
        graph_tuples, raw_by_tuple, _opening_objects(openings_json)
    )
    return graph_tuples, raw_by_tuple, openings_per_wall, junctions_by_index, nodes, end_to_node, skipped


def _raw_wall_ids(raw):
    source_ids = list(raw.get("source_wall_ids") or [])
    if source_ids:
        ids = []
        for value in source_ids:
            text = str(value or "")
            if text and text not in ids:
                ids.append(text)
        return ids
    ids = []
    for value in (raw.get("id"), raw.get("element_id")):
        text = str(value or "")
        if text and text not in ids:
            ids.append(text)
    return ids


def _merged_raw_wall(members):
    """Metadados de uma cadeia colinear preservando todas as Walls fonte."""
    result = dict(members[0])
    source_ids = []
    for raw in members:
        for wall_id in _raw_wall_ids(raw):
            if wall_id not in source_ids:
                source_ids.append(wall_id)
    result["source_wall_ids"] = source_ids
    result["source_wall_count"] = len(members)
    if len(members) > 1:
        result["id"] = "+".join(source_ids) if source_ids else result.get("id")
        result["element_id"] = source_ids[0] if source_ids else result.get("element_id")
    return result


def _opening_objects(openings_json):
    openings = []
    for op in openings_json or []:
        center_cm = op.get("center_cm") or [0.0, 0.0]
        openings.append({
            "element_id": str(op.get("element_id", "")),
            "center_xy": XYZ(center_cm[0] * CM_TO_FT, center_cm[1] * CM_TO_FT, 0.0),
            "width_ft": float(op.get("width_cm") or 80.0) * CM_TO_FT,
            "sill_z_abs": float(op.get("sill_cm") or 0.0) * CM_TO_FT,
            "head_z_abs": float(op.get("head_cm") or 220.0) * CM_TO_FT,
            "center_source": op.get("center_source", "geometria"),
            "host_wall_id": str(op.get("host_wall_id") or ""),
            "level": op.get("level") or "",
        })
    return openings


def _assign_openings_to_raw_walls(graph_tuples, raw_walls, openings):
    """Respeita o host exportado; capturas antigas usam a associacao real."""
    result = [[] for _ in graph_tuples]
    unhosted = []
    wall_indices_by_id = {}
    for idx, raw in enumerate(raw_walls):
        for wall_id in _raw_wall_ids(raw) or [_wall_id(raw, idx + 1)]:
            wall_indices_by_id.setdefault(wall_id, []).append(idx)

    for opening in openings:
        host_id = opening.get("host_wall_id")
        candidate_indices = wall_indices_by_id.get(host_id) if host_id else None
        for wall_idx in candidate_indices or []:
            rows = assign_openings_to_walls([graph_tuples[wall_idx]], [opening])[0]
            if rows:
                result[wall_idx].extend(rows)
                break
        if not host_id or candidate_indices is None:
            unhosted.append(opening)

    if unhosted:
        fallback = assign_openings_to_walls(graph_tuples, unhosted)
        for wall_idx, rows in enumerate(fallback):
            result[wall_idx].extend(rows)

    for rows in result:
        rows.sort(key=lambda row: row[0])
    return result


def _wall_id(raw, seq):
    return str(raw.get("id") or raw.get("element_id") or "W{:03d}".format(seq))


def _wall_tuple(raw):
    start = raw.get("start_cm") or raw.get("start")
    end = raw.get("end_cm") or raw.get("end")
    if not start or not end:
        return None
    thickness_cm = float(raw.get("thickness_cm") or raw.get("width_cm") or 14.0)
    return make_line(start, end), thickness_cm * CM_TO_FT, (False, False)


def _wall_group_key(raw, capture):
    level = raw.get("level") or capture.get("level") or ""
    base_z_cm = float(raw.get("base_z_cm") or 0.0)
    return level, round(base_z_cm, 3)


def _openings_for_group(capture, raw_walls):
    openings = capture.get("openings") or []
    wall_ids = set()
    levels = set()
    min_base = None
    max_top = None
    for seq, raw in enumerate(raw_walls):
        wall_ids.add(_wall_id(raw, seq + 1))
        wall_ids.add(str(raw.get("element_id") or ""))
        levels.add(raw.get("level") or capture.get("level") or "")
        base = float(raw.get("base_z_cm") or 0.0)
        top = base + float(raw.get("height_cm") or (capture.get("wall_height_m") or 2.8) * 100.0)
        min_base = base if min_base is None else min(min_base, base)
        max_top = top if max_top is None else max(max_top, top)

    selected = []
    for opening in openings:
        host_id = str(opening.get("host_wall_id") or "")
        if host_id:
            if host_id in wall_ids:
                selected.append(opening)
            continue
        opening_level = opening.get("level") or ""
        if opening_level and opening_level not in levels:
            continue
        sill = float(opening.get("sill_cm") or 0.0)
        head = float(opening.get("head_cm") or sill)
        if min_base is not None and max_top is not None:
            if head <= min_base or sill >= max_top:
                continue
        selected.append(opening)
    return selected


def _capture_wall_groups(capture):
    grouped = {}
    order = []
    for raw in capture.get("walls") or []:
        key = _wall_group_key(raw, capture)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(raw)
    return [
        (key, grouped[key], _openings_for_group(capture, grouped[key]))
        for key in order
    ]


def _merge_active_band_rows(rows):
    """Une somente os intervalos horizontais ativos na mesma fiada."""
    ordered = sorted(rows, key=lambda row: (row[0], row[1]))
    merged = []
    for row in ordered:
        if merged and row[0] <= merged[-1][1] + 1e-9:
            previous = merged[-1]
            merged[-1] = (
                previous[0], max(previous[1], row[1]),
                min(previous[2], row[2]), max(previous[3], row[3]),
            )
        else:
            merged.append(row)
    return merged


def _graph_for_tuples(wall_tuples):
    if not wall_tuples:
        return [], {}, [], {}
    extended, junction_map = extend_wall_ends_to_junctions(
        wall_tuples, JUNCTION_FACE_SEARCH_FT
    )
    nodes, end_to_node = build_wall_graph(extended, junction_map)
    junctions_by_index = {}
    for idx, _wall_tuple_value in enumerate(extended):
        kinds = []
        for end_index in (0, 1):
            node_idx = end_to_node.get((idx, end_index))
            kinds.append(nodes[node_idx]["kind"] if node_idx is not None else None)
        junctions_by_index[idx] = kinds
    return extended, junctions_by_index, nodes, end_to_node


def _junctions_for_tuples(wall_tuples):
    extended, junctions_by_index, _nodes, _end_to_node = _graph_for_tuples(wall_tuples)
    return extended, junctions_by_index


def walls_from_capture(capture):
    """Devolve `(walls, diagnostics)` a partir de `capture["walls"]`.

    Schema aceito por Wall:
      {"id"/"element_id", "start"/"start_cm": [x,y],
       "end"/"end_cm": [x,y], "thickness_cm"/"width_cm": 14.0,
       "height_cm": 280.0, "base_z_cm": 0.0, "level": "..."}
    """
    raw_walls = capture.get("walls") or []
    wall_height_cm = float(capture.get("wall_height_cm") or (capture.get("wall_height_m") or 2.8) * 100.0)
    walls = []
    skipped = 0
    graph_wall_count = 0
    z_reference_cm = capture_z_reference_cm(capture)
    for _key, group_raw_walls, group_openings in _capture_wall_groups(capture):
        graph_tuples, raw_by_tuple, openings_per_wall, junctions_by_index, _nodes, _end_to_node, group_skipped = _capture_graph_for_raw(
            group_raw_walls, group_openings
        )
        skipped += group_skipped
        graph_wall_count += len(graph_tuples)
        for idx, (line, thickness_ft, _locked_ends) in enumerate(graph_tuples):
            raw = raw_by_tuple[idx] if idx < len(raw_by_tuple) else {}
            wall_id = _wall_id(raw, idx + 1)
            openings_on_line = openings_per_wall[idx] if idx < len(openings_per_wall) else []
            base_z_abs_ft = float(raw.get("base_z_cm") or 0.0) * CM_TO_FT
            raw_height_cm = float(raw.get("height_cm") or wall_height_cm)
            segments_on_wall = build_wall_segments(
                line, base_z_abs_ft, raw_height_cm * CM_TO_FT, openings_on_line
            )

            cutout_segments = []
            for seg_idx, (sub_line, seg_height_ft, seg_base_offset_ft, seg_origin) in enumerate(segments_on_wall):
                p0 = sub_line.GetEndPoint(0)
                p1 = sub_line.GetEndPoint(1)
                cutout_segments.append({
                    "id": "{}_cut_{:02d}".format(wall_id, seg_idx + 1),
                    "start": point_to_cm(p0),
                    "end": point_to_cm(p1),
                    "length_cm": round(p0.DistanceTo(p1) * FT_TO_CM, 2),
                    "height_cm": round(seg_height_ft * FT_TO_CM, 2),
                    "base_z_cm": round((base_z_abs_ft + seg_base_offset_ft) * FT_TO_CM - z_reference_cm, 2),
                    "origin": "abertura" if seg_origin == "abertura" else "revit_wall",
                })

            p0 = line.GetEndPoint(0)
            p1 = line.GetEndPoint(1)
            walls.append({
                "id": wall_id,
                "element_id": str(raw.get("element_id") or wall_id),
                "wall_group_id": wall_id,
                "source_wall_ids": _raw_wall_ids(raw),
                "source_wall_count": int(raw.get("source_wall_count") or 1),
                "source": "revit_wall",
                "start": point_to_cm(p0),
                "end": point_to_cm(p1),
                "thickness_cm": round(thickness_ft * FT_TO_CM, 2),
                "length_cm": round(p0.DistanceTo(p1) * FT_TO_CM, 2),
                "height_cm": round(raw_height_cm, 2),
                "base_z_cm": round(base_z_abs_ft * FT_TO_CM - z_reference_cm, 2),
                "level": raw.get("level") or capture.get("level", ""),
                "level_elevation_cm": (
                    round(float(raw.get("level_elevation_cm")) - z_reference_cm, 2)
                    if raw.get("level_elevation_cm") is not None else None
                ),
                "base_offset_cm": raw.get("base_offset_cm"),
                "layer": raw.get("layer") or "Walls Revit",
                "single_line": False,
                "origin": "revit_wall",
                "junctions": junctions_by_index.get(idx, [None, None]),
                "openings_count": len(openings_on_line),
                "cutout_segments": cutout_segments,
            })

    diagnostics = {
        "source_mode": "revit_walls",
        "revit_walls_received": len(raw_walls),
        "revit_walls_used": graph_wall_count,
        "revit_wall_segments_used": sum(
            len(wall.get("cutout_segments") or []) for wall in walls
        ),
        "continuous_wall_count": len(walls),
        "z_reference_cm": round(z_reference_cm, 3),
        "walls_below_reference_count": sum(1 for wall in walls if wall.get("base_z_cm", 0.0) < -1e-6),
        "skipped_walls": skipped,
        "duplicates_removed": 0,
        "possible_bonecas": [],
        "layers": {"Walls Revit": {"walls_formed": len(walls), "unused_lines": skipped}},
    }
    return walls, diagnostics


def _catalog_from_json(catalog_json):
    catalog = {}
    for code, entry in (catalog_json or {}).items():
        cells = []
        for cell in entry.get("cells_local_cm") or []:
            center = cell.get("center_cm") or [0.0, 0.0]
            size = cell.get("size_cm") or [0.0, 0.0]
            cells.append({
                "center_local": (float(center[0]) * CM_TO_FT, float(center[1]) * CM_TO_FT),
                "size_local": (float(size[0]) * CM_TO_FT, float(size[1]) * CM_TO_FT),
            })
        catalog[code] = {
            "length_cm": float(entry.get("length_cm") or 0.0),
            "height_cm": float(entry.get("height_cm") or 19.0),
            "width_cm": float(entry.get("width_cm") or 14.0),
            "cells_local": cells,
            "cells_local_cm": entry.get("cells_local_cm") or [],
            "is_special_bond": bool(entry.get("is_special_bond")),
            "is_compensator": bool(entry.get("is_compensator")),
            "color_rgb": entry.get("color_rgb"),
            "type_name": entry.get("type_name") or code,
        }
    return catalog


def _wall_solver_status(entry, raw):
    """Serializa o resultado do solver em uma explicação exibível por Wall."""
    validation = entry.get("validation") or {}
    non_modular = entry.get("non_modular") or []
    alignment = entry.get("alignment_conflicts") or []
    if non_modular:
        issue = non_modular[0]
        if issue.get("conflict") == "SEM_ESPACO":
            reason = "abertura ou encontro ocupa todo o trecho livre"
        else:
            reason = (
                "trecho de {:.1f}cm nao fecha com o catalogo e as juntas atuais"
                .format(float(issue.get("current_length_cm") or 0.0))
            )
        code = "NON_MODULAR"
    elif alignment:
        reason = "as fiadas criam junta vertical coincidente; o solver nao aceitou a solucao"
        code = "ALIGNMENT_CONFLICT"
    elif not validation.get("ok", False):
        problems = validation.get("problems") or []
        reason = "; ".join(str(problem) for problem in problems) or "falha na validacao de encontros"
        code = "VALIDATION_FAILURE"
    else:
        reason = "modulada com as regras do solver"
        code = "MODULABLE"
    return {
        "wall_idx": entry.get("wall_idx"),
        "wall_id": _wall_id(raw, int(entry.get("wall_idx") or 0) + 1),
        "source_wall_ids": _raw_wall_ids(raw),
        "ok": code == "MODULABLE",
        "code": code,
        "reason": reason,
        "candidate_count": int(entry.get("candidate_count") or 0),
    }


def _merge_wall_status(statuses, candidate):
    """Conserva a pior situação de uma Wall quando ela aparece em várias faixas."""
    existing = statuses.get(candidate["wall_id"])
    if existing is None or (existing.get("ok") and not candidate.get("ok")):
        statuses[candidate["wall_id"]] = candidate


def _mark_candidates_for_failed_walls(candidates, statuses):
    """Mantém blocos reprovados visíveis, mas inequívocos no visualizador.

    Uma Wall sem solução não pode desaparecer silenciosamente. Os candidatos
    que pertencem a uma Wall reprovada continuam no payload para diagnóstico,
    recebem a cor vermelha e carregam o motivo; o renderer não precisa conhecer
    regras de modulação para decidir o que é inválido.
    """
    failed_by_source = {}
    for status in statuses.values():
        if status.get("ok"):
            continue
        for source_id in status.get("source_wall_ids") or [status.get("wall_id")]:
            if source_id is not None:
                failed_by_source[str(source_id)] = status
    for candidate in candidates:
        candidate_ids = set(str(value) for value in (candidate.get("source_wall_ids") or []) if value is not None)
        candidate_ids.update(str(value) for value in (candidate.get("secondary_source_wall_ids") or []) if value is not None)
        if candidate.get("wall_id") is not None:
            candidate_ids.add(str(candidate.get("wall_id")))
        status = next((failed_by_source[value] for value in candidate_ids if value in failed_by_source), None)
        if status is None:
            continue
        candidate["is_error"] = True
        candidate["error_code"] = status.get("code")
        candidate["error_reason"] = status.get("reason")
        candidate["color_rgb"] = [229, 57, 53]
    return sum(1 for candidate in candidates if candidate.get("is_error"))


def solve_capture_block_candidates(capture, group_keys=None):
    """Resolve fiadas físicas por nível/faixa e serializa a geometria real.

    ``group_keys`` permite recalcular somente as faixas independentes
    alteradas por uma edição interativa. Sem esse argumento o comportamento
    é idêntico ao carregamento inicial e resolve toda a captura.
    """
    catalog = _catalog_from_json(capture.get("catalog"))
    if not catalog or not capture.get("walls"):
        return [], {"status": "skipped", "reason": "sem catalogo ou sem Walls Revit"}

    result = []
    heights = sorted(set(round(float(e.get("height_cm") or 0.0), 3) for e in catalog.values() if e.get("height_cm")))
    if len(heights) != 1:
        return [], {"status": "error", "reason": "catalogo sem altura unica de bloco", "heights_cm": heights}
    block_height_cm = heights[0]
    course_step_cm = block_height_cm + BLOCK_JOINT_CM
    skipped = 0
    level_runs = []
    counters = {
        "non_modular_count": 0, "collision_count": 0, "jamb_exception_count": 0,
        "intersection_failure_count": 0, "validation_failure_count": 0,
        "door_void_violation_count": 0,
    }
    wall_statuses = {}
    z_reference_cm = capture_z_reference_cm(capture)
    requested_groups = None
    if group_keys is not None:
        requested_groups = set((str(key[0]), float(key[1])) for key in group_keys)

    for group_key, group_raw_walls, group_openings in _capture_wall_groups(capture):
        if requested_groups is not None and (str(group_key[0]), float(group_key[1])) not in requested_groups:
            continue
        graph_tuples, raw_by_tuple, openings_per_wall, _junctions_by_index, nodes, end_to_node, group_skipped = _capture_graph_for_raw(
            group_raw_walls, group_openings
        )
        skipped += group_skipped
        if not graph_tuples:
            continue
        base_z_cm = float(group_key[1])
        max_height_cm = max(float(raw.get("height_cm") or (capture.get("wall_height_m") or 2.8) * 100.0) for raw in raw_by_tuple)
        num_courses = int(math.floor(max_height_cm / course_step_cm + 1e-6))

        bands = {}
        band_order = []
        for course_index in range(num_courses):
            z_lo_cm = base_z_cm + FIRST_COURSE_Z_OFFSET_CM + course_index * course_step_cm
            z_hi_cm = z_lo_cm + block_height_cm
            filtered = []
            signature_rows = []
            for openings in openings_per_wall:
                active = _merge_active_band_rows([
                    row for row in openings
                    if min(row[3] * FT_TO_CM, z_hi_cm) - max(row[2] * FT_TO_CM, z_lo_cm)
                    > OPENING_COURSE_BAND_TOLERANCE_CM
                ])
                filtered.append(active)
                signature_rows.append(tuple((round(row[0], 4), round(row[1], 4)) for row in active))
            signature = tuple(signature_rows)
            if signature not in bands:
                bands[signature] = {"course_indices": [], "openings": filtered}
                band_order.append(signature)
            bands[signature]["course_indices"].append(course_index)

        for signature in band_order:
            band = bands[signature]
            try:
                run = solve_building_blocks(
                    nodes, graph_tuples, end_to_node, band["openings"], catalog,
                    base_z_abs=base_z_cm * CM_TO_FT, variants_per_course=1,
                )
            except Exception as exc:
                return [], {"status": "error", "reason": str(exc), "level": group_key[0]}
            counters["non_modular_count"] += len(run.get("non_modular") or [])
            counters["collision_count"] += len(run.get("collisions") or [])
            counters["jamb_exception_count"] += len(run.get("jamb_exceptions") or [])
            counters["intersection_failure_count"] += len(run.get("intersection_failures") or [])
            counters["validation_failure_count"] += sum(
                1 for validation in (run.get("validations") or []) if not validation.get("ok")
            )
            counters["door_void_violation_count"] += len(run.get("door_void_violations") or [])
            for entry in run.get("per_wall") or []:
                wall_idx = entry.get("wall_idx")
                if isinstance(wall_idx, int) and 0 <= wall_idx < len(raw_by_tuple):
                    _merge_wall_status(
                        wall_statuses, _wall_solver_status(entry, raw_by_tuple[wall_idx])
                    )

            for course_index in band["course_indices"]:
                course_letter = "A" if course_index % 2 == 0 else "B"
                z_cm = base_z_cm + FIRST_COURSE_Z_OFFSET_CM + course_index * course_step_cm
                for cand in run.get("candidates") or []:
                    if cand.get("course") != course_letter:
                        continue
                    wall_idx = cand.get("wall_idx")
                    secondary_idx = cand.get("secondary_wall_idx")
                    involved = [i for i in (wall_idx, secondary_idx) if isinstance(i, int) and i < len(raw_by_tuple)]
                    if involved and any(
                        z_cm + block_height_cm > float(raw_by_tuple[i].get("base_z_cm") or base_z_cm)
                        + float(raw_by_tuple[i].get("height_cm") or max_height_cm) + 1e-6
                        for i in involved
                    ):
                        continue
                    code = cand.get("logical_code")
                    entry = catalog.get(code) or {}
                    origin = cand.get("origin_world")
                    x_dir = cand.get("x_dir")
                    y_dir = cand.get("y_dir")
                    if origin is None or x_dir is None or y_dir is None:
                        continue
                    wall_id = _wall_id(raw_by_tuple[wall_idx], wall_idx + 1) if isinstance(wall_idx, int) and wall_idx < len(raw_by_tuple) else None
                    source_wall_ids = (
                        _raw_wall_ids(raw_by_tuple[wall_idx])
                        if isinstance(wall_idx, int) and wall_idx < len(raw_by_tuple) else []
                    )
                    secondary_source_wall_ids = (
                        _raw_wall_ids(raw_by_tuple[secondary_idx])
                        if isinstance(secondary_idx, int) and secondary_idx < len(raw_by_tuple) else []
                    )
                    candidate_id = "{}:{}:{}:{}".format(group_key[0], wall_id or "node", course_index, len(result))
                    result.append({
                        "id": candidate_id,
                        "logical_code": code,
                        "type_name": entry.get("type_name") or code,
                        "course": course_letter,
                        "course_index": course_index,
                        "wall_idx": wall_idx,
                        "wall_id": wall_id,
                        "source_wall_ids": source_wall_ids,
                        "secondary_wall_idx": secondary_idx,
                        "secondary_source_wall_ids": secondary_source_wall_ids,
                        "origin_cm": [origin.X * FT_TO_CM, origin.Y * FT_TO_CM],
                        "z_cm": z_cm - z_reference_cm,
                        "level": group_key[0],
                        "x_dir": [x_dir.X, x_dir.Y],
                        "y_dir": [y_dir.X, y_dir.Y],
                        "length_cm": float(cand.get("length_cm") or entry.get("length_cm") or 0.0),
                        "width_cm": float(cand.get("width_cm") or entry.get("width_cm") or 0.0),
                        "height_cm": block_height_cm,
                        "cells_local_cm": entry.get("cells_local_cm") or [],
                        "color_rgb": entry.get("color_rgb"),
                        "placement_reason": cand.get("placement_reason"),
                        "solver_group_key": [group_key[0], group_key[1]],
                    })
        level_runs.append({"level": group_key[0], "base_z_cm": base_z_cm, "bands": len(bands), "courses": num_courses})

    error_candidate_count = _mark_candidates_for_failed_walls(result, wall_statuses)
    compensator_codes = set(
        code for code, entry in catalog.items() if entry.get("is_compensator")
    )
    # B34 tambem e' uma peca valida de preenchimento corrente. A aceitacao
    # depende do travamento entre fiadas (auditado pelo motor canonico), e
    # nao de estar ou nao em uma quina/encontro.
    invalid_b34_count = 0
    lintel_missing_count = 0
    raw_walls_by_id = {}
    for seq, raw in enumerate(capture.get("walls") or []):
        raw_walls_by_id[_wall_id(raw, seq + 1)] = raw
        if raw.get("element_id") is not None:
            raw_walls_by_id[str(raw.get("element_id"))] = raw
    for opening in capture.get("openings") or []:
        host_id = str(opening.get("host_wall_id") or "")
        raw_wall = raw_walls_by_id.get(host_id)
        if raw_wall is None:
            continue
        wall_base_cm = float(raw_wall.get("base_z_cm") or 0.0)
        wall_top_cm = wall_base_cm + float(raw_wall.get("height_cm") or 0.0)
        head_cm = float(opening.get("head_cm") or wall_base_cm)
        if wall_top_cm - head_cm < block_height_cm - 1e-6:
            continue
        normalized_head_cm = head_cm - z_reference_cm
        has_lintel_course = any(
            (host_id in (candidate.get("source_wall_ids") or [])
             or candidate.get("wall_id") == _wall_id(raw_wall, 1))
            and candidate.get("z_cm", 0.0) + 1e-6 >= normalized_head_cm
            and candidate.get("z_cm", 0.0) + block_height_cm <= wall_top_cm - z_reference_cm + 1e-6
            for candidate in result
        )
        if not has_lintel_course:
            lintel_missing_count += 1
    diagnostics = {
        "status": "ok",
        "candidate_count": len(result),
        "non_modular_count": counters["non_modular_count"],
        "collision_count": counters["collision_count"],
        "jamb_exception_count": counters["jamb_exception_count"],
        "intersection_failure_count": counters["intersection_failure_count"],
        "validation_failure_count": counters["validation_failure_count"],
        "door_void_violation_count": counters["door_void_violation_count"],
        "invalid_b34_count": invalid_b34_count,
        "compensator_count": sum(1 for c in result if c.get("logical_code") in compensator_codes),
        "pastilha_count": sum(1 for c in result if c.get("logical_code") == "C04"),
        "error_candidate_count": error_candidate_count,
        "main_block_count": sum(1 for c in result if c.get("logical_code") == "B39"),
        "blocks_below_reference_count": sum(1 for c in result if c.get("z_cm", 0.0) < -1e-6),
        "lintel_missing_count": lintel_missing_count,
        "skipped_walls": skipped,
        "levels": level_runs,
        "course_step_cm": course_step_cm,
        "first_course_offset_cm": FIRST_COURSE_Z_OFFSET_CM,
        "z_reference_cm": round(z_reference_cm, 3),
        "wall_statuses": [wall_statuses[key] for key in sorted(wall_statuses)],
        "processed_group_keys": [[entry["level"], entry["base_z_cm"]] for entry in level_runs],
    }
    return result, diagnostics


def _solution_quality(diagnostics, candidates=None):
    """Menor e melhor; validade vem antes da economia de pecas."""
    return (
        int(diagnostics.get("collision_count") or 0),
        int(diagnostics.get("non_modular_count") or 0),
        int(diagnostics.get("intersection_failure_count") or 0),
        int(diagnostics.get("validation_failure_count") or 0),
        int(diagnostics.get("door_void_violation_count") or 0),
        int(diagnostics.get("invalid_b34_count") or 0),
        int(diagnostics.get("blocks_below_reference_count") or 0),
        int(diagnostics.get("lintel_missing_count") or 0),
        int(diagnostics.get("jamb_exception_count") or 0),
        int(diagnostics.get("compensator_count") or 0),
        int(diagnostics.get("pastilha_count") or 0),
        -int(diagnostics.get("main_block_count") or 0),
        int(diagnostics.get("candidate_count") or 0),
    )


def _find_capture_display_wall(capture, wall_id):
    """Localiza a Wall contínua mostrada pelo visualizador.

    Uma Wall mostrada pode representar várias Walls de origem colineares. A
    edição deve atuar no eixo contínuo, nunca em apenas um fragmento interno,
    para que uma ponta arrastada não abra uma fenda entre os fragmentos.
    """
    wanted = str(wall_id or "")
    for wall in walls_from_capture(capture)[0]:
        ids = {str(wall.get("id") or ""), str(wall.get("element_id") or "")}
        ids.update(str(value) for value in (wall.get("source_wall_ids") or []))
        if wanted in ids:
            return wall
    return None


def _source_ids_for_display_wall(wall):
    ids = [str(value) for value in (wall.get("source_wall_ids") or []) if str(value)]
    if not ids:
        ids = [str(wall.get("element_id") or wall.get("id") or "")]
    return set(value for value in ids if value)


def _dependency_geometry_key(capture):
    rows = []
    for raw in capture.get("walls") or []:
        start = raw.get("start_cm") or raw.get("start") or []
        end = raw.get("end_cm") or raw.get("end") or []
        rows.append((
            tuple(_raw_wall_ids(raw)), tuple(start[:2]), tuple(end[:2]),
            raw.get("thickness_cm"), raw.get("width_cm"), raw.get("height_cm"),
            raw.get("base_z_cm"), raw.get("level"),
        ))
    return tuple(rows)


def _dependency_graph_rows(capture):
    """Grafo geométrico memoizado; mover abertura não altera esta chave."""
    cache_key = _dependency_geometry_key(capture)
    cached = _DEPENDENCY_GRAPH_CACHE.get(cache_key)
    if cached is not None:
        _DEPENDENCY_GRAPH_CACHE.move_to_end(cache_key)
        return cached
    rows = []
    for _key, group_raw_walls, group_openings in _capture_wall_groups(capture):
        graph, raw_by_tuple, _openings, _junctions, nodes, _end_to_node, _skipped = _capture_graph_for_raw(
            group_raw_walls, group_openings
        )
        adjacency = dict((index, set()) for index in range(len(graph)))
        for node in nodes:
            involved = set(index for index, _end in (node.get("arms") or []))
            involved.update(node.get("crossing_walls") or [])
            for field in ("main_wall_idx", "incoming_wall_idx", "neighbor_wall_idx"):
                index = node.get(field)
                if isinstance(index, int):
                    involved.add(index)
            for index in involved:
                adjacency.setdefault(index, set()).update(involved - {index})
        rows.append((raw_by_tuple, adjacency))
    _DEPENDENCY_GRAPH_CACHE[cache_key] = rows
    _DEPENDENCY_GRAPH_CACHE.move_to_end(cache_key)
    while len(_DEPENDENCY_GRAPH_CACHE) > _DEPENDENCY_GRAPH_CACHE_LIMIT:
        _DEPENDENCY_GRAPH_CACHE.popitem(last=False)
    return rows


def _affected_wall_ids(capture, source_ids):
    """Retorna a componente de encontros afetada por uma edição.

    O solver já isola níveis/faixas de base; dentro de uma faixa, só Walls
    conectadas por um nó L/T/X (ou cruzamento) precisam ser destacadas como
    dependentes diretas. A lista é diagnóstico para a UI e também evita que
    uma alteração pareça afetar o projeto inteiro silenciosamente.
    """
    affected = set()
    for raw_by_tuple, adjacency in _dependency_graph_rows(capture):
        selected = {
            index for index, raw in enumerate(raw_by_tuple)
            if _source_ids_for_display_wall(raw) & source_ids
        }
        if not selected:
            continue
        # Um salto é o fecho seguro do resolve parcial do solver: a parede
        # alterada e quem compartilha diretamente um encontro com ela. Ir
        # transitivamente até o fim da rede transformaria qualquer edição em
        # recálculo das 125 paredes conectadas do projeto real.
        visited = set(selected)
        for index in selected:
            for neighbor in adjacency.get(index, ()):
                visited.add(neighbor)
        for index in visited:
            if index < len(raw_by_tuple):
                affected.update(_source_ids_for_display_wall(raw_by_tuple[index]))
    return sorted(affected)


def dependency_context_wall_ids(capture, affected_wall_ids):
    """Acrescenta um anel de contexto sem promovê-lo a região alterada.

    O solver canônico precisa enxergar os encontros nas pontas das Walls que
    serão recalculadas. Essas Walls de borda participam do cálculo, mas seus
    blocos não entram no delta enviado à cena.
    """
    return _affected_wall_ids(
        capture, set(str(value) for value in (affected_wall_ids or []) if str(value))
    )


def warm_dependency_graph(capture):
    """Prepara o grafo no worker de carga antes do primeiro arraste."""
    _dependency_graph_rows(capture)


def _group_keys_for_source_ids(capture, source_ids):
    """Faixas independentes do solver que contêm uma das Walls alteradas."""
    keys = []
    for key, group_raw_walls, _group_openings in _capture_wall_groups(capture):
        if any(set(_raw_wall_ids(raw)) & source_ids for raw in group_raw_walls):
            keys.append([key[0], key[1]])
    return keys


def _group_source_ids(capture, group_keys):
    requested = set((str(key[0]), float(key[1])) for key in (group_keys or []))
    ids = set()
    for key, group_raw_walls, _group_openings in _capture_wall_groups(capture):
        if (str(key[0]), float(key[1])) in requested:
            for raw in group_raw_walls:
                ids.update(_raw_wall_ids(raw))
    return sorted(ids)


def edit_capture_wall(capture, wall_id, start_cm=None, end_cm=None,
                      thickness_cm=None, height_cm=None):
    """Edita uma Wall contínua e propaga o deslocamento às suas aberturas.

    Esta é a única porta de edição geométrica do modelo externo. Ela mantém
    os fragmentos Revit que compõem o eixo na mesma razão paramétrica e move
    as aberturas hospedadas com o eixo. Em seguida o chamador roda o mesmo
    ``solve_capture_block_candidates`` da modulação inicial; não há regra de
    preview paralela para a geometria editada.
    """
    display_wall = _find_capture_display_wall(capture, wall_id)
    if display_wall is None:
        return capture, {"accepted": False, "reason": "parede nao encontrada"}

    old_start = _xy_point(display_wall.get("start"), "inicio atual")
    old_end = _xy_point(display_wall.get("end"), "fim atual")
    new_start = _xy_point(start_cm if start_cm is not None else old_start, "inicio")
    new_end = _xy_point(end_cm if end_cm is not None else old_end, "fim")
    new_length = math.hypot(new_end[0] - new_start[0], new_end[1] - new_start[1])
    if new_length < MIN_EDITABLE_WALL_LENGTH_CM:
        return capture, {
            "accepted": False,
            "reason": "a parede deve manter pelo menos {:.0f}cm de comprimento".format(
                MIN_EDITABLE_WALL_LENGTH_CM
            ),
        }

    try:
        new_thickness = (float(thickness_cm) if thickness_cm is not None
                         else float(display_wall.get("thickness_cm") or 0.0))
        new_height = (float(height_cm) if height_cm is not None
                      else float(display_wall.get("height_cm") or 0.0))
    except (TypeError, ValueError):
        return capture, {"accepted": False, "reason": "espessura ou altura da parede invalida"}
    if not math.isfinite(new_thickness) or new_thickness < MIN_EDITABLE_WALL_THICKNESS_CM:
        return capture, {
            "accepted": False,
            "reason": "a parede deve manter pelo menos {:.0f}cm de espessura".format(
                MIN_EDITABLE_WALL_THICKNESS_CM
            ),
        }
    if not math.isfinite(new_height) or new_height < MIN_EDITABLE_WALL_HEIGHT_CM:
        return capture, {
            "accepted": False,
            "reason": "a parede deve manter pelo menos {:.0f}cm de altura".format(
                MIN_EDITABLE_WALL_HEIGHT_CM
            ),
        }

    source_ids = _source_ids_for_display_wall(display_wall)
    trial = copy.deepcopy(capture)
    changed_wall_ids = []
    for raw in trial.get("walls") or []:
        raw_ids = set(_raw_wall_ids(raw))
        if not raw_ids & source_ids:
            continue
        raw_start = _xy_point(raw.get("start_cm") or raw.get("start"), "inicio da parede fonte")
        raw_end = _xy_point(raw.get("end_cm") or raw.get("end"), "fim da parede fonte")
        start_t, _unused = _line_projection(raw_start, old_start, old_end)
        end_t, _unused = _line_projection(raw_end, old_start, old_end)
        raw["start_cm"] = _point_on_line(new_start, new_end, start_t)
        raw["end_cm"] = _point_on_line(new_start, new_end, end_t)
        raw["thickness_cm"] = round(new_thickness, 6)
        raw["height_cm"] = round(new_height, 6)
        raw["top_z_cm"] = round(float(raw.get("base_z_cm") or 0.0) + new_height, 6)
        raw.pop("start", None)
        raw.pop("end", None)
        changed_wall_ids.extend(_raw_wall_ids(raw))

    # A porta/janela permanece na mesma posição relativa ao eixo. Assim,
    # mover ou redimensionar a Wall nunca deixa uma abertura órfã na posição
    # antiga; o solver recebe sempre paredes + aberturas consistentes.
    moved_opening_ids = []
    for opening in trial.get("openings") or []:
        if str(opening.get("host_wall_id") or "") not in source_ids:
            continue
        center = _xy_point(opening.get("center_cm"), "centro da abertura")
        center_t, _unused = _line_projection(center, old_start, old_end)
        opening["center_cm"] = _point_on_line(new_start, new_end, center_t)
        moved_opening_ids.append(str(opening.get("element_id") or ""))

    return trial, {
        "accepted": True,
        "wall_id": display_wall.get("id"),
        "source_wall_ids": sorted(source_ids),
        "changed_wall_ids": sorted(set(changed_wall_ids)),
        "affected_wall_ids": _affected_wall_ids(trial, source_ids),
        "moved_opening_ids": [value for value in moved_opening_ids if value],
        "old_start_cm": list(old_start),
        "old_end_cm": list(old_end),
        "start_cm": list(new_start),
        "end_cm": list(new_end),
        "length_cm": round(new_length, 3),
        "thickness_cm": round(new_thickness, 3),
        "height_cm": round(new_height, 3),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": _group_keys_for_source_ids(trial, source_ids),
        "processed_source_wall_ids": _group_source_ids(
            trial, _group_keys_for_source_ids(trial, source_ids)
        ),
    }


def move_capture_opening(capture, opening_id, center_cm):
    """Move uma abertura ao longo de sua parede, aceitando toda posição válida.

    Diferente do ajuste automático, uma edição explícita não exige melhorar a
    pontuação do solver: ela só precisa permanecer dentro da Wall hospedeira.
    O resultado pode ser não modular, mas será devolvido com o diagnóstico
    correspondente em vez de a abertura ser ignorada ou revertida em silêncio.
    """
    opening_id = str(opening_id or "")
    source_opening = next(
        (opening for opening in capture.get("openings") or []
         if str(opening.get("element_id") or "") == opening_id), None
    )
    if source_opening is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}
    axis = _opening_wall_axis(capture, source_opening)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}
    requested = _xy_point(center_cm, "centro da abertura")
    current = _xy_point(source_opening.get("center_cm"), "centro atual da abertura")
    delta_cm = ((requested[0] - current[0]) * axis["x_dir"] +
                (requested[1] - current[1]) * axis["y_dir"])
    new_t_cm = axis["opening_t_cm"] + delta_cm
    half_width_cm = float(source_opening.get("width_cm") or 0.0) / 2.0
    if new_t_cm - half_width_cm < -1e-6 or new_t_cm + half_width_cm > axis["length_cm"] + 1e-6:
        return capture, {
            "accepted": False,
            "reason": "a abertura deve permanecer inteiramente dentro da parede hospedeira",
        }
    trial = copy.deepcopy(capture)
    opening = next(item for item in trial.get("openings") or []
                   if str(item.get("element_id") or "") == opening_id)
    opening["center_cm"] = [
        round(current[0] + axis["x_dir"] * delta_cm, 6),
        round(current[1] + axis["y_dir"] * delta_cm, 6),
    ]
    return trial, {
        "accepted": True,
        "opening_id": opening_id,
        "wall_id": axis["wall_id"],
        "delta_cm": round(delta_cm, 3),
        "center_cm": opening["center_cm"],
        "affected_wall_ids": _affected_wall_ids(trial, {str(axis["wall_id"])}),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": _group_keys_for_source_ids(trial, {str(axis["wall_id"])}),
        "processed_source_wall_ids": _group_source_ids(
            trial, _group_keys_for_source_ids(trial, {str(axis["wall_id"])})
        ),
    }


def resize_capture_opening(capture, opening_id, width_cm):
    """Altera a largura de uma abertura sem deixar seu vão sair da Wall."""
    opening_id = str(opening_id or "")
    source_opening = next(
        (opening for opening in capture.get("openings") or []
         if str(opening.get("element_id") or "") == opening_id), None,
    )
    if source_opening is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}
    axis = _opening_wall_axis(capture, source_opening)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}
    try:
        requested_width_cm = float(width_cm)
    except (TypeError, ValueError):
        return capture, {"accepted": False, "reason": "largura da abertura invalida"}
    if not math.isfinite(requested_width_cm) or requested_width_cm < MIN_EDITABLE_OPENING_WIDTH_CM:
        return capture, {
            "accepted": False,
            "reason": "a abertura deve manter pelo menos {:.0f}cm de largura".format(
                MIN_EDITABLE_OPENING_WIDTH_CM
            ),
        }
    half_width_cm = requested_width_cm / 2.0
    if (axis["opening_t_cm"] - half_width_cm < -1e-6 or
            axis["opening_t_cm"] + half_width_cm > axis["length_cm"] + 1e-6):
        return capture, {
            "accepted": False,
            "reason": "a nova largura nao cabe inteiramente na parede hospedeira",
        }
    trial = copy.deepcopy(capture)
    opening = next(item for item in trial.get("openings") or []
                   if str(item.get("element_id") or "") == opening_id)
    opening["width_cm"] = round(requested_width_cm, 6)
    source_ids = {str(axis["wall_id"])}
    groups = _group_keys_for_source_ids(trial, source_ids)
    return trial, {
        "accepted": True,
        "opening_id": opening_id,
        "wall_id": axis["wall_id"],
        "width_cm": opening["width_cm"],
        "affected_wall_ids": _affected_wall_ids(trial, source_ids),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": groups,
        "processed_source_wall_ids": _group_source_ids(trial, groups),
    }


def edit_capture_opening(capture, opening_id, center_cm=None, width_cm=None,
                         height_cm=None, sill_cm=None):
    """Aplica posição e dimensões de uma abertura como uma única operação.

    Todas as etapas trabalham numa cópia e só devolvem o snapshot novo se a
    abertura continuar dentro do prisma da Wall hospedeira. O chamador executa
    o solver canônico uma única vez e registra um único item de Undo/Redo.
    """
    opening_id = str(opening_id or "")
    source = next(
        (item for item in capture.get("openings") or []
         if str(item.get("element_id") or "") == opening_id), None,
    )
    if source is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}

    trial = capture
    if center_cm is not None:
        trial, action = move_capture_opening(trial, opening_id, center_cm)
        if not action.get("accepted"):
            return capture, action
    if width_cm is not None:
        trial, action = resize_capture_opening(trial, opening_id, width_cm)
        if not action.get("accepted"):
            return capture, action
    if trial is capture:
        trial = copy.deepcopy(capture)

    opening = next(
        item for item in trial.get("openings") or []
        if str(item.get("element_id") or "") == opening_id
    )
    axis = _opening_wall_axis(trial, opening)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}

    current_sill = float(opening.get("sill_cm") or 0.0)
    current_height = float(opening.get("height_cm") or
                           (float(opening.get("head_cm") or 0.0) - current_sill))
    try:
        requested_sill = current_sill if sill_cm is None else float(sill_cm)
        requested_height = current_height if height_cm is None else float(height_cm)
    except (TypeError, ValueError):
        return capture, {"accepted": False, "reason": "altura ou peitoril da abertura invalido"}
    if not math.isfinite(requested_height) or requested_height < MIN_EDITABLE_OPENING_HEIGHT_CM:
        return capture, {
            "accepted": False,
            "reason": "a abertura deve manter pelo menos {:.0f}cm de altura".format(
                MIN_EDITABLE_OPENING_HEIGHT_CM
            ),
        }
    if not math.isfinite(requested_sill):
        return capture, {"accepted": False, "reason": "peitoril da abertura invalido"}
    requested_head = requested_sill + requested_height
    wall_base = axis["base_z_cm"]
    wall_top = wall_base + axis["height_cm"]
    if requested_sill < wall_base - 1e-6 or requested_head > wall_top + 1e-6:
        return capture, {
            "accepted": False,
            "reason": "a abertura deve permanecer inteiramente dentro da altura da parede hospedeira",
        }

    opening["sill_cm"] = round(requested_sill, 6)
    opening["height_cm"] = round(requested_height, 6)
    opening["head_cm"] = round(requested_head, 6)
    source_ids = {str(axis["wall_id"])}
    groups = _group_keys_for_source_ids(trial, source_ids)
    return trial, {
        "accepted": True,
        "opening_id": opening_id,
        "wall_id": axis["wall_id"],
        "center_cm": list(opening.get("center_cm") or []),
        "width_cm": float(opening.get("width_cm") or 0.0),
        "height_cm": opening["height_cm"],
        "sill_cm": opening["sill_cm"],
        "head_cm": opening["head_cm"],
        "affected_wall_ids": _affected_wall_ids(trial, source_ids),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": groups,
        "processed_source_wall_ids": _group_source_ids(trial, groups),
    }


def duplicate_capture_opening(capture, opening_id, delta_cm=10.0):
    """Duplica uma abertura na mesma Wall, deslocada ao longo do eixo."""
    opening_id = str(opening_id or "")
    source = next(
        (item for item in capture.get("openings") or []
         if str(item.get("element_id") or "") == opening_id), None,
    )
    if source is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}
    axis = _opening_wall_axis(capture, source)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}
    try:
        requested_delta = float(delta_cm)
    except (TypeError, ValueError):
        return capture, {"accepted": False, "reason": "deslocamento da copia invalido"}
    existing = set(str(item.get("element_id") or "") for item in capture.get("openings") or [])
    suffix = 1
    new_id = "{}__copy{}".format(opening_id, suffix)
    while new_id in existing:
        suffix += 1
        new_id = "{}__copy{}".format(opening_id, suffix)

    half_width = float(source.get("width_cm") or 0.0) / 2.0
    choices = [requested_delta, -requested_delta]
    chosen = next((delta for delta in choices
                   if axis["opening_t_cm"] + delta - half_width >= -1e-6
                   and axis["opening_t_cm"] + delta + half_width <= axis["length_cm"] + 1e-6), None)
    if chosen is None:
        return capture, {"accepted": False, "reason": "nao ha espaco na parede para duplicar a abertura"}
    trial = copy.deepcopy(capture)
    duplicated = copy.deepcopy(source)
    duplicated["element_id"] = new_id
    center = duplicated.get("center_cm") or [0.0, 0.0]
    duplicated["center_cm"] = [
        round(float(center[0]) + axis["x_dir"] * chosen, 6),
        round(float(center[1]) + axis["y_dir"] * chosen, 6),
    ]
    duplicated["editor_created"] = True
    trial.setdefault("openings", []).append(duplicated)
    source_ids = {str(axis["wall_id"])}
    groups = _group_keys_for_source_ids(trial, source_ids)
    return trial, {
        "accepted": True, "opening_id": new_id, "source_opening_id": opening_id,
        "wall_id": axis["wall_id"], "delta_cm": round(chosen, 3),
        "affected_wall_ids": _affected_wall_ids(trial, source_ids),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": groups,
        "processed_source_wall_ids": _group_source_ids(trial, groups),
    }


def delete_capture_opening(capture, opening_id):
    """Remove uma abertura do snapshot do editor e invalida somente sua Wall."""
    opening_id = str(opening_id or "")
    source = next(
        (item for item in capture.get("openings") or []
         if str(item.get("element_id") or "") == opening_id), None,
    )
    if source is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}
    axis = _opening_wall_axis(capture, source)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}
    trial = copy.deepcopy(capture)
    trial["openings"] = [
        item for item in trial.get("openings") or []
        if str(item.get("element_id") or "") != opening_id
    ]
    source_ids = {str(axis["wall_id"])}
    groups = _group_keys_for_source_ids(trial, source_ids)
    return trial, {
        "accepted": True, "opening_id": opening_id, "wall_id": axis["wall_id"],
        "affected_wall_ids": _affected_wall_ids(trial, source_ids),
        "recalculation_scope": "nivel_e_faixa_da_parede",
        "solver_group_keys": groups,
        "processed_source_wall_ids": _group_source_ids(trial, groups),
    }


def _opening_wall_axis(capture, opening):
    host_id = str(opening.get("host_wall_id") or "")
    center = opening.get("center_cm") or [0.0, 0.0]
    best = None
    for seq, wall in enumerate(capture.get("walls") or []):
        wall_id = _wall_id(wall, seq + 1)
        if host_id and host_id not in (wall_id, str(wall.get("element_id") or "")):
            continue
        start = wall.get("start_cm") or wall.get("start")
        end = wall.get("end_cm") or wall.get("end")
        if not start or not end:
            continue
        dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        if length > 1e-9:
            ux, uy = dx / length, dy / length
            t = (float(center[0]) - float(start[0])) * ux + (float(center[1]) - float(start[1])) * uy
            px = float(start[0]) + max(0.0, min(length, t)) * ux
            py = float(start[1]) + max(0.0, min(length, t)) * uy
            perpendicular = math.hypot(float(center[0]) - px, float(center[1]) - py)
            candidate = {
                "x_dir": ux, "y_dir": uy, "wall_id": wall_id,
                "length_cm": length, "opening_t_cm": t,
                "base_z_cm": float(wall.get("base_z_cm") or 0.0),
                "height_cm": float(wall.get("height_cm") or
                                   (float(capture.get("wall_height_m") or 2.8) * 100.0)),
            }
            if host_id:
                return candidate
            if best is None or perpendicular < best[0]:
                best = (perpendicular, candidate)
    return best[1] if best is not None else None


def adjust_capture_opening(capture, opening_id, delta_cm=None, automatic=False):
    """Desloca uma abertura no eixo e so aceita melhoria confirmada pelo solver."""
    opening_id = str(opening_id)
    source_opening = next(
        (opening for opening in capture.get("openings") or []
         if str(opening.get("element_id")) == opening_id),
        None,
    )
    if source_opening is None:
        return capture, {"accepted": False, "reason": "abertura nao encontrada"}, [], {}

    axis = _opening_wall_axis(capture, source_opening)
    if axis is None:
        return capture, {"accepted": False, "reason": "parede hospedeira nao identificada"}, [], {}

    baseline_candidates, baseline_diagnostics = solve_capture_block_candidates(capture)
    baseline_quality = _solution_quality(baseline_diagnostics, baseline_candidates)
    if baseline_diagnostics.get("status") != "ok":
        return capture, {"accepted": False, "reason": baseline_diagnostics.get("reason")}, baseline_candidates, baseline_diagnostics

    if automatic:
        deltas = [-1.0, 1.0, -2.0, 2.0, -3.0, 3.0, -4.0, 4.0, -5.0, 5.0]
    else:
        try:
            requested = float(delta_cm)
        except (TypeError, ValueError):
            return capture, {"accepted": False, "reason": "deslocamento manual invalido"}, baseline_candidates, baseline_diagnostics
        if abs(requested) > 5.0 + 1e-9 or abs(requested) < 1e-9:
            return capture, {"accepted": False, "reason": "o limite permitido e de +/-5cm"}, baseline_candidates, baseline_diagnostics
        deltas = [requested]

    best = None
    ux, uy = axis["x_dir"], axis["y_dir"]
    wall_id = axis["wall_id"]
    half_width_cm = float(source_opening.get("width_cm") or 0.0) / 2.0
    for candidate_delta in deltas:
        new_t_cm = axis["opening_t_cm"] + candidate_delta
        if new_t_cm - half_width_cm < -1e-6 or new_t_cm + half_width_cm > axis["length_cm"] + 1e-6:
            continue
        trial = copy.deepcopy(capture)
        trial_opening = next(
            opening for opening in trial.get("openings") or []
            if str(opening.get("element_id")) == opening_id
        )
        center = trial_opening.get("center_cm") or [0.0, 0.0]
        trial_opening["center_cm"] = [
            float(center[0]) + ux * candidate_delta,
            float(center[1]) + uy * candidate_delta,
        ]
        trial_candidates, trial_diagnostics = solve_capture_block_candidates(trial)
        if trial_diagnostics.get("status") != "ok":
            continue
        quality = _solution_quality(trial_diagnostics, trial_candidates)
        if quality >= baseline_quality:
            continue
        if best is None or quality < best[0]:
            best = (quality, trial, trial_candidates, trial_diagnostics, candidate_delta)
            if automatic and quality[:9] == (0, 0, 0, 0, 0, 0, 0, 0, 0):
                break

    if best is None:
        return capture, {
            "accepted": False,
            "reason": "nenhuma tentativa melhorou a modulacao sem criar conflitos",
            "wall_id": wall_id,
            "baseline": baseline_diagnostics,
        }, baseline_candidates, baseline_diagnostics

    _quality, adjusted_capture, candidates, diagnostics, applied_delta = best
    return adjusted_capture, {
        "accepted": True,
        "opening_id": opening_id,
        "wall_id": wall_id,
        "delta_cm": applied_delta,
        "from": baseline_diagnostics,
        "to": diagnostics,
    }, candidates, diagnostics


def adjust_capture_openings(capture):
    """Testa todas as aberturas e mantem apenas melhorias validadas."""
    current = capture
    actions = []
    for opening in capture.get("openings") or []:
        opening_id = str(opening.get("element_id") or "")
        if not opening_id:
            continue
        adjusted, action, _candidates, _diagnostics = adjust_capture_opening(
            current, opening_id, automatic=True
        )
        actions.append(action)
        if action.get("accepted"):
            current = adjusted

    candidates, diagnostics = solve_capture_block_candidates(current)
    accepted_count = sum(1 for action in actions if action.get("accepted"))
    return current, {
        "accepted": accepted_count > 0,
        "actions": actions,
        "accepted_count": accepted_count,
        "reason": None if accepted_count else "nenhuma abertura admitiu melhoria pelas regras do solver",
    }, candidates, diagnostics


def enrich_openings_for_view(walls, openings_json, tolerance_cm=10.0):
    """Adds wall orientation metadata so the viewer can draw openings on-axis.

    The Revit export gives the opening center and width, but the external
    viewer also needs the wall angle/thickness to place the translucent void
    box correctly in 3D.
    """
    enriched = []
    for op in openings_json or []:
        op_view = dict(op)
        center = op.get("center_cm") or [0.0, 0.0]
        cx, cy = float(center[0]), float(center[1])
        best = None
        host_id = str(op.get("host_wall_id") or "")
        opening_level = op.get("level") or ""

        for wall in walls or []:
            wall_ids = {
                str(wall.get("id") or ""), str(wall.get("element_id") or ""),
                str(wall.get("wall_group_id") or ""),
            }
            wall_ids.update(str(value) for value in (wall.get("source_wall_ids") or []))
            if host_id and host_id not in wall_ids:
                continue
            if not host_id and opening_level and (wall.get("level") or "") != opening_level:
                continue
            x0, y0 = wall["start"]
            x1, y1 = wall["end"]
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            ux, uy = dx / length, dy / length
            t = (cx - x0) * ux + (cy - y0) * uy
            t_clamped = max(0.0, min(length, t))
            px, py = x0 + ux * t_clamped, y0 + uy * t_clamped
            perp = math.hypot(cx - px, cy - py)
            max_perp = float(wall.get("thickness_cm") or 0.0) / 2.0 + tolerance_cm
            if perp > max_perp:
                continue
            score = (perp, 0.0 if 0.0 <= t <= length else min(abs(t), abs(t - length)))
            if best is None or score < best["score"]:
                best = {
                    "score": score,
                    "wall": wall,
                    "projected_center_cm": [round(px, 4), round(py, 4)],
                    "axis_cm": [round(ux, 8), round(uy, 8)],
                    "t_cm": round(t_clamped, 4),
                }

        if best is not None:
            wall = best["wall"]
            ux, uy = best["axis_cm"]
            op_view.update({
                "wall_id": wall.get("id"),
                "wall_group_id": wall.get("wall_group_id"),
                "center_cm": best["projected_center_cm"],
                "axis_cm": best["axis_cm"],
                "angle_rad": math.atan2(uy, ux),
                "wall_thickness_cm": wall.get("thickness_cm"),
                "t_cm": best["t_cm"],
            })
        enriched.append(op_view)
    return enriched
