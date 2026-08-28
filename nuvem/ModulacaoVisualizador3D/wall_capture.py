# -*- coding: utf-8 -*-
"""Entrada por Walls reais do Revit para o visualizador externo.

O fluxo CAD continua usando `wall_pairing.py`. Este modulo cobre o novo
fluxo em que o usuario seleciona Walls ja existentes no Revit: cada Wall
capturada vira a geometria base, as aberturas sao associadas a ela e a
validacao/preview reaproveita as regras importadas por `engine_bridge`.
"""

import copy
import math

from engine_bridge import (
    FEET_PER_METER, JUNCTION_FACE_SEARCH_FT, BLOCK_JOINT_CM,
    XYZ, make_line, point_to_cm,
    build_wall_graph, extend_wall_ends_to_junctions, assign_openings_to_walls,
    build_wall_segments, solve_building_blocks,
)


CM_TO_FT = FEET_PER_METER / 100.0
FT_TO_CM = 100.0 / FEET_PER_METER

FIRST_COURSE_Z_OFFSET_CM = 1.0
OPENING_COURSE_BAND_TOLERANCE_CM = 0.5


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
    graph_tuples, junctions_by_index, nodes, end_to_node = _graph_for_tuples(tuples)
    openings_per_wall = _assign_openings_to_raw_walls(
        graph_tuples, raw_by_tuple, _opening_objects(openings_json)
    )
    return graph_tuples, raw_by_tuple, openings_per_wall, junctions_by_index, nodes, end_to_node, skipped


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
        wall_indices_by_id.setdefault(_wall_id(raw, idx + 1), []).append(idx)
        element_id = str(raw.get("element_id") or "")
        if element_id:
            wall_indices_by_id.setdefault(element_id, []).append(idx)

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

            for seg_idx, (sub_line, seg_height_ft, seg_base_offset_ft, seg_origin) in enumerate(segments_on_wall):
                p0 = sub_line.GetEndPoint(0)
                p1 = sub_line.GetEndPoint(1)
                segment_id = (
                    "{}_{:02d}".format(wall_id, seg_idx + 1)
                    if len(segments_on_wall) > 1 else wall_id
                )
                walls.append({
                    "id": segment_id,
                    "element_id": str(raw.get("element_id") or wall_id),
                    "wall_group_id": wall_id,
                    "source": "revit_wall",
                    "start": point_to_cm(p0),
                    "end": point_to_cm(p1),
                    "thickness_cm": round(thickness_ft * FT_TO_CM, 2),
                    "length_cm": round(p0.DistanceTo(p1) * FT_TO_CM, 2),
                    "height_cm": round(seg_height_ft * FT_TO_CM, 2),
                    "base_z_cm": round((base_z_abs_ft + seg_base_offset_ft) * FT_TO_CM, 2),
                    "level": raw.get("level") or capture.get("level", ""),
                    "level_elevation_cm": raw.get("level_elevation_cm"),
                    "base_offset_cm": raw.get("base_offset_cm"),
                    "layer": raw.get("layer") or "Walls Revit",
                    "single_line": False,
                    "origin": "abertura" if seg_origin == "abertura" else "revit_wall",
                    "junctions": junctions_by_index.get(idx, [None, None]) if seg_origin == "cad" else [None, None],
                    "openings_count": len(openings_on_line),
                })

    diagnostics = {
        "source_mode": "revit_walls",
        "revit_walls_received": len(raw_walls),
        "revit_walls_used": graph_wall_count,
        "revit_wall_segments_used": len(walls),
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


def solve_capture_block_candidates(capture):
    """Resolve fiadas fisicas por nivel e serializa a geometria real."""
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
    counters = {"non_modular_count": 0, "collision_count": 0, "jamb_exception_count": 0}

    for group_key, group_raw_walls, group_openings in _capture_wall_groups(capture):
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
                    candidate_id = "{}:{}:{}:{}".format(group_key[0], wall_id or "node", course_index, len(result))
                    result.append({
                        "id": candidate_id,
                        "logical_code": code,
                        "type_name": entry.get("type_name") or code,
                        "course": course_letter,
                        "course_index": course_index,
                        "wall_idx": wall_idx,
                        "wall_id": wall_id,
                        "secondary_wall_idx": secondary_idx,
                        "origin_cm": [origin.X * FT_TO_CM, origin.Y * FT_TO_CM],
                        "z_cm": z_cm,
                        "level": group_key[0],
                        "x_dir": [x_dir.X, x_dir.Y],
                        "y_dir": [y_dir.X, y_dir.Y],
                        "length_cm": float(cand.get("length_cm") or entry.get("length_cm") or 0.0),
                        "width_cm": float(cand.get("width_cm") or entry.get("width_cm") or 0.0),
                        "height_cm": block_height_cm,
                        "cells_local_cm": entry.get("cells_local_cm") or [],
                        "color_rgb": entry.get("color_rgb"),
                        "placement_reason": cand.get("placement_reason"),
                    })
        level_runs.append({"level": group_key[0], "base_z_cm": base_z_cm, "bands": len(bands), "courses": num_courses})

    diagnostics = {
        "status": "ok",
        "candidate_count": len(result),
        "non_modular_count": counters["non_modular_count"],
        "collision_count": counters["collision_count"],
        "jamb_exception_count": counters["jamb_exception_count"],
        "skipped_walls": skipped,
        "levels": level_runs,
        "course_step_cm": course_step_cm,
        "first_course_offset_cm": FIRST_COURSE_Z_OFFSET_CM,
    }
    return result, diagnostics


def _solution_quality(diagnostics):
    """Menor e melhor; colisao nunca pode ser compensada por mais pecas."""
    return (
        int(diagnostics.get("collision_count") or 0),
        int(diagnostics.get("non_modular_count") or 0),
        int(diagnostics.get("jamb_exception_count") or 0),
        -int(diagnostics.get("candidate_count") or 0),
    )


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
    baseline_quality = _solution_quality(baseline_diagnostics)
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
        quality = _solution_quality(trial_diagnostics)
        if quality >= baseline_quality:
            continue
        if best is None or quality < best[0]:
            best = (quality, trial, trial_candidates, trial_diagnostics, candidate_delta)
            if automatic and quality[:3] == (0, 0, 0):
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
