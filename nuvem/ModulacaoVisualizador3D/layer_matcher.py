# -*- coding: utf-8 -*-
"""Analisa os layers de um DXF e da' uma nota de confianca de cada um "parecer
parede" - combinando (a) geometria real (mesmos helpers do motor real, via
`engine_bridge`: quantas linhas do layer pareiam como duas faces de parede
dentro da faixa fisica de espessura) com (b) similaridade de nome contra o(s)
nome(s) de layer que o usuario espera (ex.: "A-WALL").

Existe porque a conversao DWG->DXF (ou o proprio CAD de origem) pode mudar
nomes de layer, e o sistema NAO deve simplesmente confiar num nome parecido
sem checar a geometria - ver README.md e o pedido do usuario (2026-08-26):
"Nao faca correspondencia apenas por similaridade de nome... nunca continue
silenciosamente com um Layer errado"."""

import re
from difflib import SequenceMatcher

from dxf_reader import read_dxf_segments
from engine_bridge import (
    are_lines_parallel, get_distance_between_parallel_lines, lines_overlap_enough,
    make_line, MIN_WALL_THICKNESS_FT, MAX_WALL_THICKNESS_FT,
)

# Confianca >= este valor -> "OK" (fecha bem como parede, ou nome bate bem
# com o esperado); abaixo disso -> "ATENCAO" (usuario precisa conferir antes
# de usar este layer).
CONFIDENCE_OK_THRESHOLD = 0.6

# Peso da geometria vs. nome na confianca combinada, quando o usuario informa
# nome(s) esperado(s) - a geometria pesa mais de proposito (pedido explicito:
# nao confiar so' no nome).
GEOMETRY_WEIGHT = 0.65
NAME_WEIGHT = 0.35


def _normalize_name(name):
    """Uppercase, sem acento/pontuacao, so' letras/numeros - para comparar
    nomes de layer que a conversao pode ter alterado (ex.: "A-WALL" vs
    "A_WALL_1" vs "AWALL")."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _name_similarity(layer_name, expected_names):
    """Maior similaridade (0..1, via difflib) entre `layer_name` e qualquer
    nome em `expected_names`. Devolve (score, melhor_nome_esperado) - ou
    (None, None) se `expected_names` estiver vazio (sem nome esperado para
    comparar, a confianca fica so' na geometria)."""
    if not expected_names:
        return None, None
    normalized_layer = _normalize_name(layer_name)
    best_score, best_name = 0.0, None
    for expected in expected_names:
        normalized_expected = _normalize_name(expected)
        if not normalized_expected:
            continue
        score = SequenceMatcher(None, normalized_layer, normalized_expected).ratio()
        if score > best_score:
            best_score, best_name = score, expected
    return best_score, best_name


def _geometry_score(segments):
    """Fracao (0..1) das linhas de `segments` que participam de pelo menos
    um par valido (paralelas, distancia na faixa fisica de espessura de
    parede, sobreposicao suficiente) - MESMOS criterios/helpers do motor
    real (nao uma heuristica separada). Um layer de paredes de verdade tem
    a MAIORIA das suas linhas em algum par assim; um layer de cotas/textos/
    hachura misturado por engano tende a ter pouquissimas."""
    if not segments:
        return 0.0
    lines = [make_line(s["start"], s["end"]) for s in segments]
    n = len(lines)
    used = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            if used[i] and used[j]:
                continue
            if not are_lines_parallel(lines[i], lines[j]):
                continue
            dist_ft = get_distance_between_parallel_lines(lines[i], lines[j])
            if not (MIN_WALL_THICKNESS_FT <= dist_ft <= MAX_WALL_THICKNESS_FT):
                continue
            if not lines_overlap_enough(lines[i], lines[j]):
                continue
            used[i] = used[j] = True
    return sum(used) / n


def analyze_layers(path, expected_layers=None, unit_scale_to_cm=None):
    """Analisa todos os layers com geometria linear (LINE/LWPOLYLINE/
    POLYLINE, blocos ja explodidos - ver dxf_reader) de `path`. Devolve uma
    lista de dicts, ordenada por confianca decrescente:
        {"layer": str, "entity_count": int, "geometry_score": float,
         "name_score": float ou None, "matched_expected": str ou None,
         "confidence": float, "status": "OK" ou "ATENCAO"}

    `unit_scale_to_cm`: mesma escala manual aceita por
    `dxf_reader.read_dxf_segments` - importa porque a nota GEOMETRICA
    depende de medir distancias em cm corretas (um DXF com o cabeçalho de
    unidade errado faz TODA parede medir fora da faixa fisica esperada,
    zerando a confianca mesmo num layer de paredes de verdade)."""
    segments = read_dxf_segments(path, unit_scale_to_cm=unit_scale_to_cm)
    by_layer = {}
    for seg in segments:
        by_layer.setdefault(seg["layer"], []).append(seg)

    results = []
    for layer, layer_segments in by_layer.items():
        geometry_score = _geometry_score(layer_segments)
        name_score, matched_expected = _name_similarity(layer, expected_layers)

        if name_score is None:
            confidence = geometry_score
        else:
            confidence = GEOMETRY_WEIGHT * geometry_score + NAME_WEIGHT * name_score

        results.append({
            "layer": layer,
            "entity_count": len(layer_segments),
            "geometry_score": round(geometry_score, 3),
            "name_score": round(name_score, 3) if name_score is not None else None,
            "matched_expected": matched_expected,
            "confidence": round(confidence, 3),
            "status": "OK" if confidence >= CONFIDENCE_OK_THRESHOLD else "ATENCAO",
        })

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results
