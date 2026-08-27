# -*- coding: utf-8 -*-
"""Pareia segmentos de reta (de `dxf_reader.py`) em paredes, usando a MESMA
orquestracao real de pareamento/junções de `core/wall_modeling.py` (via
`engine_bridge` -> `core.engine.wall_pairing`, extraído para lá
especificamente para este visualizador poder consumi-la) - não mais uma
reimplementação simplificada própria.

Isso substitui a versão anterior (pareamento guloso simples, sem
religamento de fragmentos nem extensão até junções L/T/X, documentada como
"reimplementação simplificada" - ver ARQUITETURA_INTERATIVA.md no
motor principal). O fluxo agora é: segmentos em cm -> `Line`s (via
`engine_bridge.make_line`) -> `find_wall_pairs` (pareamento real) ->
`extend_wall_ends_to_junctions` (fecha encontros L/T) ->
`deduplicate_walls` -> de volta para dicts em cm, no MESMO formato já
consumido por `modulation_preview.py`/`server.py`/`viewer/index.html`.

Aberturas: passadas como lista vazia de propósito (decisão do usuário,
2026-08-26) - um DWG/DXF isolado não carrega essa informação (no motor
real ela vem de família já colocada no Revit); ver README.md."""

import math

from engine_bridge import (
    make_line, point_to_cm,
    scan_candidate_thicknesses_cm, compute_detection_tolerance_ft,
    find_wall_pairs, extend_wall_ends_to_junctions, deduplicate_walls,
    scan_possible_missed_bonecas, build_wall_graph,
    assign_openings_to_walls, build_wall_segments,
    MIN_WALL_THICKNESS_FT, MAX_WALL_THICKNESS_FT, JUNCTION_FACE_SEARCH_FT,
    FEET_PER_METER, XYZ,
)

# Tolerancia (cm) alem da meia-espessura da parede para considerar que uma
# entidade bruta do DXF "pertence" a ela - so' usado pela aproximacao de
# rastreamento entidade->parede (ver associate_entities_with_walls), nao
# pelo pareamento real (esse usa as tolerancias do motor via engine_bridge).
ENTITY_WALL_PERP_SLACK_CM = 5.0
ENTITY_WALL_MIN_OVERLAP_RATIO = 0.3

CM_TO_FT = FEET_PER_METER / 100.0
FT_TO_CM = 100.0 / FEET_PER_METER

# Usadas so' se scan_candidate_thicknesses_cm nao encontrar NENHUM par
# plausivel no layer (ex.: layer com poucas linhas) - espessuras comuns de
# alvenaria estrutural, so' para nao deixar o pareamento sem nenhuma
# espessura-alvo para tentar.
DEFAULT_THICKNESS_CANDIDATES_CM = (9.0, 14.0, 19.0, 24.0, 29.0)


def _new_diagnostics():
    return {
        "parallel_pairs": 0, "min_dist_ft": None, "max_dist_ft": None,
        "offset_suspect_count": 0, "offset_suspect_max_ft": 0.0,
        "cap_clipped_count": 0,
    }


def pair_walls_from_segments(segments, target_thicknesses_cm=None, openings_json=None, wall_height_cm=280.0, include_unused_lines=True):
    """Recebe a saida de `dxf_reader.read_dxf_segments` (ou captura JSON) e devolve
    `(walls, diagnostics)`:

    `walls`: lista de dicts
        {"id": "W001_1", "wall_group_id": "W001", "start": (x_cm, y_cm), "end": (x_cm, y_cm),
         "thickness_cm": float, "length_cm": float, "height_cm": float, "base_z_cm": float,
         "origin": "cad"|"abertura", "layer": str, "single_line": bool, "junctions": [kind_inicio, kind_fim]}
    """
    scale = CM_TO_FT
    openings_objects = []
    if openings_json:
        for op in openings_json:
            cx, cy = op.get("center_cm", [0.0, 0.0])
            w_cm = op.get("width_cm", 80.0)
            sill_cm = op.get("sill_cm", 0.0)
            head_cm = op.get("head_cm", 220.0)
            openings_objects.append({
                "element_id": str(op.get("element_id", "")),
                "center_xy": XYZ(cx * scale, cy * scale, 0.0),
                "width_ft": w_cm * scale,
                "sill_z_abs": sill_cm * scale,
                "head_z_abs": head_cm * scale,
                "center_source": op.get("center_source", "geometria"),
            })

    by_layer = {}
    for seg in segments:
        by_layer.setdefault(seg["layer"], []).append(seg)

    walls = []
    wall_seq = 0
    possible_bonecas = []
    duplicates_removed_total = 0
    layer_stats = {}

    for layer, layer_segments in by_layer.items():
        lines = [make_line(s["start"], s["end"]) for s in layer_segments]

        # REQUISITO 5: Apenas as espessuras selecionadas sao modeladas.
        if target_thicknesses_cm:
            target_thicknesses_ft = sorted(set(t * CM_TO_FT for t in target_thicknesses_cm))
        else:
            candidates_cm = scan_candidate_thicknesses_cm(lines)
            source_cm = candidates_cm.keys() if candidates_cm else DEFAULT_THICKNESS_CANDIDATES_CM
            target_thicknesses_ft = sorted(set(cm * CM_TO_FT for cm in source_cm))

        tolerance_ft = compute_detection_tolerance_ft(target_thicknesses_ft)

        diagnostics = _new_diagnostics()
        walls_to_create, unused_lines = find_wall_pairs(
            lines, target_thicknesses_ft, tolerance_ft,
            cap_candidate_lines=lines, openings=openings_objects, diagnostics=diagnostics,
        )
        walls_to_create, removed_count = deduplicate_walls(walls_to_create)
        duplicates_removed_total += removed_count
        walls_to_create, junction_map = extend_wall_ends_to_junctions(
            walls_to_create, JUNCTION_FACE_SEARCH_FT
        )

        nodes, end_to_node = build_wall_graph(walls_to_create, junction_map)

        # Associa aberturas exclusivamente as paredes criadas
        openings_per_wall = assign_openings_to_walls(walls_to_create, openings_objects)
        wall_height_ft = (wall_height_cm or 280.0) * CM_TO_FT
        base_z_abs = 0.0

        for idx, (line, thickness_ft, _locked_ends) in enumerate(walls_to_create):
            wall_seq += 1
            junctions = []
            for end_index in (0, 1):
                node_idx = end_to_node.get((idx, end_index))
                junctions.append(nodes[node_idx]["kind"] if node_idx is not None else None)

            openings_on_line = openings_per_wall[idx] if idx < len(openings_per_wall) else []
            segments_on_wall = build_wall_segments(line, base_z_abs, wall_height_ft, openings_on_line)

            for seg_idx, (sub_line, seg_height_ft, seg_base_offset_ft, seg_origin) in enumerate(segments_on_wall):
                sp0 = sub_line.GetEndPoint(0)
                sp1 = sub_line.GetEndPoint(1)
                seg_len_cm = sp0.DistanceTo(sp1) * FT_TO_CM
                seg_height_cm = seg_height_ft * FT_TO_CM
                seg_base_z_cm = seg_base_offset_ft * FT_TO_CM

                seg_id = "W{:03d}_{:d}".format(wall_seq, seg_idx + 1) if len(segments_on_wall) > 1 else "W{:03d}".format(wall_seq)
                seg_junctions = [
                    junctions[0] if seg_idx == 0 and seg_origin == "cad" else None,
                    junctions[1] if seg_idx == len(segments_on_wall) - 1 and seg_origin == "cad" else None,
                ]

                walls.append({
                    "id": seg_id,
                    "wall_group_id": "W{:03d}".format(wall_seq),
                    "start": point_to_cm(sp0),
                    "end": point_to_cm(sp1),
                    "thickness_cm": round(thickness_ft * FT_TO_CM, 2),
                    "length_cm": round(seg_len_cm, 2),
                    "height_cm": round(seg_height_cm, 2),
                    "base_z_cm": round(seg_base_z_cm, 2),
                    "origin": seg_origin,
                    "layer": layer,
                    "single_line": False,
                    "junctions": seg_junctions,
                })

        if include_unused_lines:
            for line in unused_lines:
                wall_seq += 1
                p0 = line.GetEndPoint(0)
                p1 = line.GetEndPoint(1)
                walls.append({
                    "id": "W{:03d}".format(wall_seq),
                    "wall_group_id": "W{:03d}".format(wall_seq),
                    "start": point_to_cm(p0),
                    "end": point_to_cm(p1),
                    "thickness_cm": MIN_WALL_THICKNESS_FT * FT_TO_CM,
                    "length_cm": p0.DistanceTo(p1) * FT_TO_CM,
                    "height_cm": round(wall_height_cm, 2),
                    "base_z_cm": 0.0,
                    "origin": "cad",
                    "layer": layer,
                    "single_line": True,
                    "junctions": [None, None],
                })

        possible_bonecas.extend(scan_possible_missed_bonecas(unused_lines))
        layer_stats[layer] = {
            "parallel_pairs": diagnostics["parallel_pairs"],
            "walls_formed": len(walls_to_create),
            "unused_lines": len(unused_lines),
            "duplicates_removed": removed_count,
            "target_thicknesses_cm": sorted(round(t * FT_TO_CM, 1) for t in target_thicknesses_ft),
        }

    diagnostics_out = {
        "possible_bonecas": possible_bonecas,
        "duplicates_removed": duplicates_removed_total,
        "layers": layer_stats,
    }
    return walls, diagnostics_out


def _perp_distance_and_overlap_ratio(wall_p0, wall_p1, seg_p0, seg_p1):
    """Distancia perpendicular MEDIA de `seg_p0`/`seg_p1` ate' a RETA que
    passa por `wall_p0`/`wall_p1`, e a fracao do comprimento do eixo da
    parede coberta pela projecao do segmento sobre ele. So' geometria 2D
    simples (sem depender do motor/engine_bridge) - usado apenas pela
    aproximacao de rastreamento entidade->parede, nao pelo pareamento real."""
    ax, ay = wall_p1[0] - wall_p0[0], wall_p1[1] - wall_p0[1]
    wall_length = math.hypot(ax, ay)
    if wall_length < 1e-9:
        return None, 0.0
    ux, uy = ax / wall_length, ay / wall_length

    def project(pt):
        dx, dy = pt[0] - wall_p0[0], pt[1] - wall_p0[1]
        t = dx * ux + dy * uy
        perp = abs(dx * uy - dy * ux)
        return t, perp

    t0, perp0 = project(seg_p0)
    t1, perp1 = project(seg_p1)
    perp_dist_cm = (perp0 + perp1) / 2.0

    lo, hi = max(0.0, min(t0, t1)), min(wall_length, max(t0, t1))
    overlap_cm = max(0.0, hi - lo)
    overlap_ratio = overlap_cm / wall_length
    return perp_dist_cm, overlap_ratio


def associate_entities_with_walls(entities, walls):
    """Marca `entity["wall_id"]` (ou None) em cada dict de `entities` -
    aproximacao geometrica de qual parede FINAL cada entidade bruta do DXF
    ajudou a formar (mesma layer, aproximadamente colinear com o eixo da
    parede, dentro de meia-espessura + folga, com sobreposicao real ao
    longo do comprimento). NAO e' um rastreamento exato do motor (ver
    limitacao no README) - so' para o inspetor de entidade do visualizador
    ter uma referencia util em vez de nenhuma.

    Modifica `entities` in-place e tambem devolve a lista, por conveniencia."""
    walls_by_layer = {}
    for wall in walls:
        walls_by_layer.setdefault(wall["layer"], []).append(wall)

    for entity in entities:
        entity["wall_id"] = None
        candidates = walls_by_layer.get(entity["layer"])
        if not candidates:
            continue
        best_ratio = 0.0
        for wall in candidates:
            perp_dist_cm, overlap_ratio = _perp_distance_and_overlap_ratio(
                wall["start"], wall["end"], entity["start"], entity["end"]
            )
            if perp_dist_cm is None:
                continue
            if perp_dist_cm > wall["thickness_cm"] / 2.0 + ENTITY_WALL_PERP_SLACK_CM:
                continue
            if overlap_ratio < ENTITY_WALL_MIN_OVERLAP_RATIO:
                continue
            if overlap_ratio > best_ratio:
                best_ratio = overlap_ratio
                entity["wall_id"] = wall["id"]

    return entities
