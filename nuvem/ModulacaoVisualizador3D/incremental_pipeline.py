# -*- coding: utf-8 -*-
"""Infraestrutura pura para o recálculo incremental do editor 3D.

Este módulo não contém regras físicas de modulação. Ele apenas reduz uma
captura à componente de paredes já determinada pelo grafo canônico, mescla o
resultado dessa componente com o snapshot anterior e produz chaves estáveis de
cache/diagnóstico.
"""

import copy
import hashlib
import json


def _text(value):
    return str(value or "")


def raw_wall_ids(wall):
    """IDs de origem reconhecidos para uma Wall bruta da captura."""
    values = list(wall.get("source_wall_ids") or [])
    values.extend([wall.get("id"), wall.get("element_id")])
    return set(_text(value) for value in values if _text(value))


def candidate_wall_ids(candidate):
    """IDs de Walls aos quais um candidato renderizado pertence."""
    values = [candidate.get("wall_id")]
    values.extend(candidate.get("source_wall_ids") or [])
    values.extend(candidate.get("primary_source_wall_ids") or [])
    values.extend(candidate.get("secondary_source_wall_ids") or [])
    return set(_text(value) for value in values if _text(value))


def opening_wall_ids(opening):
    values = [
        opening.get("wall_id"), opening.get("wall_group_id"),
        opening.get("host_wall_id"),
    ]
    values.extend(opening.get("source_wall_ids") or [])
    return set(_text(value) for value in values if _text(value))


def status_wall_ids(status):
    return set(_text(value) for value in (status.get("source_wall_ids") or []) if _text(value))


def scope_capture(capture, affected_wall_ids):
    """Cria uma captura somente com a componente afetada.

    Metadados de catálogo/setup são compartilhados por cópia rasa; as listas de
    Walls e aberturas são copiadas para impedir que o solver altere o snapshot
    da sessão. Aberturas sem host explícito permanecem disponíveis ao associador
    geométrico legado.
    """
    wanted = set(_text(value) for value in (affected_wall_ids or []) if _text(value))
    scoped = dict(capture)
    scoped_walls = [
        copy.deepcopy(wall) for wall in (capture.get("walls") or [])
        if raw_wall_ids(wall) & wanted
    ]
    retained_ids = set()
    for wall in scoped_walls:
        retained_ids.update(raw_wall_ids(wall))
    scoped_openings = []
    for opening in (capture.get("openings") or []):
        host_id = _text(opening.get("host_wall_id"))
        if not host_id or host_id in retained_ids:
            scoped_openings.append(copy.deepcopy(opening))
    scoped["walls"] = scoped_walls
    scoped["openings"] = scoped_openings
    # A planta de referência não participa do solver e pode ser grande.
    scoped["segments"] = []
    return scoped


def _digest(payload):
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def modulation_hash(capture):
    """Hash apenas das entradas globais capazes de alterar a solução."""
    return _digest({
        "catalog": capture.get("catalog") or {},
        "setup": capture.get("setup") or {},
        "wall_height_m": capture.get("wall_height_m"),
    })


def geometry_hash(capture, affected_wall_ids, solver_group_keys=None):
    """Hash determinístico da componente e de suas aberturas hospedadas."""
    scoped = scope_capture(capture, affected_wall_ids)
    return _digest({
        "walls": scoped.get("walls") or [],
        "openings": scoped.get("openings") or [],
        "groups": solver_group_keys or [],
        "modulation": modulation_hash(capture),
    })


def stable_candidate_id(candidate):
    """ID independente da posição do candidato na lista do solver."""
    return "inc-{}".format(_digest({
        "walls": sorted(candidate_wall_ids(candidate)),
        "course": candidate.get("course_index"),
        "band": candidate.get("band_index"),
        "code": candidate.get("logical_code") or candidate.get("code"),
        "origin": candidate.get("origin_cm") or candidate.get("center_cm"),
        "rotation": candidate.get("rotation_deg"),
        "reason": candidate.get("placement_reason"),
    }))


def normalize_scoped_candidates(candidates):
    result = []
    for candidate in candidates or []:
        normalized = dict(candidate)
        normalized["id"] = stable_candidate_id(normalized)
        result.append(normalized)
    return result


def merge_scoped_candidates(previous, changed, affected_wall_ids):
    wanted = set(_text(value) for value in (affected_wall_ids or []) if _text(value))
    kept = [candidate for candidate in (previous or []) if not (candidate_wall_ids(candidate) & wanted)]
    changed = list(changed or [])
    return kept + changed, len(previous or []) - len(kept), len(changed)


def merge_scoped_statuses(previous, changed, affected_wall_ids):
    wanted = set(_text(value) for value in (affected_wall_ids or []) if _text(value))
    kept = [status for status in (previous or []) if not (status_wall_ids(status) & wanted)]
    return kept + list(changed or [])


def filter_incremental_payload(payload, affected_wall_ids):
    """Reduz as coleções geométricas ao delta que a cena deve substituir."""
    wanted = set(_text(value) for value in (affected_wall_ids or []) if _text(value))
    filtered = dict(payload)
    filtered["walls"] = [wall for wall in (payload.get("walls") or []) if raw_wall_ids(wall) & wanted]
    filtered["openings"] = [
        opening for opening in (payload.get("openings") or [])
        if opening_wall_ids(opening) & wanted
    ]
    changed_candidates = [
        candidate for candidate in (payload.get("block_candidates") or [])
        if candidate_wall_ids(candidate) & wanted
    ]
    # Catálogo já segue no payload. Repetir a forma/cor/dimensões de cada
    # bloco torna o delta centenas de KB maior que o necessário; o viewer
    # reidrata esses campos pelo ``logical_code`` antes de desenhar.
    candidate_fields = (
        "id", "logical_code", "course_index", "wall_id", "source_wall_ids",
        "origin_cm", "z_cm", "x_dir", "y_dir", "level",
    )
    filtered["block_candidates"] = [
        dict((field, candidate[field]) for field in candidate_fields if field in candidate)
        for candidate in changed_candidates
    ]
    filtered["entities"] = []
    filtered["incremental_patch"] = True
    filtered["compact_block_candidates"] = True
    filtered["totals"] = {
        "walls": len(payload.get("walls") or []),
        "openings": len(payload.get("openings") or []),
        "block_candidates": len(payload.get("block_candidates") or []),
    }
    return filtered


def dependency_graph(action):
    """Descrição explícita do escopo invalidado para UI e diagnóstico."""
    affected = sorted(set(_text(value) for value in (action.get("affected_wall_ids") or []) if _text(value)))
    sources = sorted(set(_text(value) for value in (action.get("source_wall_ids") or []) if _text(value)))
    return {
        "changed_elements": [action.get("opening_id") or action.get("wall_id")],
        "source_wall_ids": sources,
        "affected_wall_ids": affected,
        "solver_context_wall_ids": action.get("solver_context_wall_ids") or affected,
        "solver_group_keys": action.get("solver_group_keys") or [],
        "affected_course_indices": action.get("affected_course_indices") or [],
        "invalidation": ["walls", "openings", "courses", "blocks", "junctions"],
    }
