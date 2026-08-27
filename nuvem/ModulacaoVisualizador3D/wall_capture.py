# -*- coding: utf-8 -*-
"""Entrada por Walls reais do Revit para o visualizador externo.

O fluxo CAD continua usando `wall_pairing.py`. Este modulo cobre o novo
fluxo em que o usuario seleciona Walls ja existentes no Revit: cada Wall
capturada vira a geometria base, as aberturas sao associadas a ela e a
validacao/preview reaproveita as regras importadas por `engine_bridge`.
"""

import math

from engine_bridge import (
    FEET_PER_METER, JUNCTION_FACE_SEARCH_FT, XYZ, make_line, point_to_cm,
    build_wall_graph, extend_wall_ends_to_junctions, assign_openings_to_walls,
    build_wall_segments, solve_building_blocks, nearest_wall_lengths_cm,
)


CM_TO_FT = FEET_PER_METER / 100.0
FT_TO_CM = 100.0 / FEET_PER_METER

ENDPOINT_CLUSTER_TOLERANCE_CM = 2.0


def _capture_graph(capture):
    raw_walls = capture.get("walls") or []
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
    openings_per_wall = assign_openings_to_walls(graph_tuples, _opening_objects(capture.get("openings")))
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
        })
    return openings


def _wall_id(raw, seq):
    return str(raw.get("id") or raw.get("element_id") or "W{:03d}".format(seq))


def _wall_tuple(raw):
    start = raw.get("start_cm") or raw.get("start")
    end = raw.get("end_cm") or raw.get("end")
    if not start or not end:
        return None
    thickness_cm = float(raw.get("thickness_cm") or raw.get("width_cm") or 14.0)
    return make_line(start, end), thickness_cm * CM_TO_FT, (False, False)


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
    graph_tuples, raw_by_tuple, openings_per_wall, junctions_by_index, _nodes, _end_to_node, skipped = _capture_graph(capture)

    walls = []
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
                "layer": raw.get("layer") or "Walls Revit",
                "single_line": False,
                "origin": "abertura" if seg_origin == "abertura" else "revit_wall",
                "junctions": junctions_by_index.get(idx, [None, None]) if seg_origin == "cad" else [None, None],
                "openings_count": len(openings_on_line),
            })

    diagnostics = {
        "source_mode": "revit_walls",
        "revit_walls_received": len(raw_walls),
        "revit_walls_used": len(graph_tuples),
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
            "is_special_bond": bool(entry.get("is_special_bond")),
            "is_compensator": bool(entry.get("is_compensator")),
            "color_rgb": entry.get("color_rgb"),
        }
    return catalog


def solve_capture_block_candidates(capture):
    """Runs the imported block solver and serializes its candidates for 3D."""
    catalog = _catalog_from_json(capture.get("catalog"))
    if not catalog or not capture.get("walls"):
        return [], {"status": "skipped", "reason": "sem catalogo ou sem Walls Revit"}

    graph_tuples, _raw_by_tuple, openings_per_wall, _junctions_by_index, nodes, end_to_node, skipped = _capture_graph(capture)
    if not graph_tuples:
        return [], {"status": "skipped", "reason": "sem paredes validas"}

    try:
        run = solve_building_blocks(
            nodes, graph_tuples, end_to_node, openings_per_wall, catalog,
            base_z_abs=0.0, variants_per_course=1,
        )
    except Exception as exc:
        return [], {"status": "error", "reason": str(exc)}

    result = []
    for cand in run.get("candidates") or []:
        code = cand.get("logical_code")
        entry = catalog.get(code) or {}
        origin = cand.get("origin_world")
        x_dir = cand.get("x_dir")
        y_dir = cand.get("y_dir")
        if origin is None or x_dir is None or y_dir is None:
            continue
        result.append({
            "logical_code": code,
            "course": cand.get("course"),
            "wall_idx": cand.get("wall_idx"),
            "secondary_wall_idx": cand.get("secondary_wall_idx"),
            "origin_cm": [origin.X * FT_TO_CM, origin.Y * FT_TO_CM],
            "x_dir": [x_dir.X, x_dir.Y],
            "y_dir": [y_dir.X, y_dir.Y],
            "length_cm": float(cand.get("length_cm") or entry.get("length_cm") or 0.0),
            "width_cm": float(cand.get("width_cm") or entry.get("width_cm") or 0.0),
            "height_cm": float(entry.get("height_cm") or 19.0),
            "color_rgb": entry.get("color_rgb"),
            "placement_reason": cand.get("placement_reason"),
        })
    diagnostics = {
        "status": "ok",
        "candidate_count": len(result),
        "non_modular_count": len(run.get("non_modular") or []),
        "collision_count": len(run.get("collisions") or []),
        "jamb_exception_count": len(run.get("jamb_exceptions") or []),
        "skipped_walls": skipped,
    }
    return result, diagnostics


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

        for wall in walls or []:
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


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cluster_endpoints(walls, tolerance_cm=ENDPOINT_CLUSTER_TOLERANCE_CM):
    nodes = []
    wall_ends = {}
    for wall in walls:
        for end_name in ("start", "end"):
            point = wall[end_name]
            node_idx = None
            for i, node in enumerate(nodes):
                if _distance(point, node["point"]) <= tolerance_cm:
                    node_idx = i
                    break
            if node_idx is None:
                node_idx = len(nodes)
                nodes.append({"point": list(point), "members": []})
            nodes[node_idx]["members"].append((wall["id"], end_name))
            wall_ends[(wall["id"], end_name)] = node_idx
    return nodes, wall_ends


def _unit_axis(wall):
    dx = wall["end"][0] - wall["start"][0]
    dy = wall["end"][1] - wall["start"][1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return dx / length, dy / length


def _apply_node_positions(walls, nodes, wall_ends):
    by_id = {w["id"]: dict(w) for w in walls}
    for wall in by_id.values():
        for end_name in ("start", "end"):
            node_idx = wall_ends[(wall["id"], end_name)]
            wall[end_name] = tuple(nodes[node_idx]["point"])
        wall["length_cm"] = round(_distance(wall["start"], wall["end"]), 2)
    return list(by_id.values())


def auto_adjust_walls(walls):
    """Ajusta em memoria paredes fora de modulo, movendo nos conectados.

    Esta funcao nao altera o Revit. Ela produz uma geometria corrigida para
    validacao/preview e um log de decisoes para a UI.
    """
    nodes, wall_ends = _cluster_endpoints(walls)
    adjusted_ids = set()
    actions = []

    for wall in walls:
        mod = wall.get("modulation") or {}
        if mod.get("closes"):
            continue

        current_len = float(wall["length_cm"])
        lower, upper = nearest_wall_lengths_cm(current_len)
        target = mod.get("suggested_length_cm") or lower or upper
        if lower and upper:
            target = lower if abs(lower - current_len) <= abs(upper - current_len) else upper
        if target is None:
            actions.append({"wall_id": wall["id"], "status": "manual", "reason": "sem comprimento modular proximo"})
            continue

        delta = float(target) - current_len
        if abs(delta) < 1e-6:
            continue
        axis = _unit_axis(wall)
        if axis is None:
            actions.append({"wall_id": wall["id"], "status": "manual", "reason": "eixo degenerado"})
            continue

        start_node = wall_ends[(wall["id"], "start")]
        end_node = wall_ends[(wall["id"], "end")]
        start_degree = len(nodes[start_node]["members"])
        end_degree = len(nodes[end_node]["members"])

        if end_degree <= start_degree:
            move_node = end_node
            direction = axis
        else:
            move_node = start_node
            direction = (-axis[0], -axis[1])

        nodes[move_node]["point"][0] += direction[0] * delta
        nodes[move_node]["point"][1] += direction[1] * delta
        adjusted_ids.add(wall["id"])
        for member_wall_id, _end_name in nodes[move_node]["members"]:
            adjusted_ids.add(member_wall_id)

        actions.append({
            "wall_id": wall["id"],
            "status": "adjusted",
            "from_cm": round(current_len, 2),
            "to_cm": round(float(target), 2),
            "delta_cm": round(delta, 2),
            "connected_walls_updated": sorted(adjusted_ids),
        })

    adjusted_walls = _apply_node_positions(walls, nodes, wall_ends)
    return adjusted_walls, {
        "actions": actions,
        "adjusted_wall_ids": sorted(adjusted_ids),
        "node_count": len(nodes),
    }
