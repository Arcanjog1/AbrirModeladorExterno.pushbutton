# -*- coding: utf-8 -*-
"""Servidor local minimo (so' biblioteca padrao do Python) que expoe o
pipeline DXF -> paredes -> preview de modulacao para o visualizador 3D em
viewer/index.html.

Sem framework web (Flask/FastAPI) de proposito: este e' um utilitario
local de uso pessoal, sem necessidade de rodar em producao/multiplos
usuarios - `http.server` da biblioteca padrao e' suficiente e nao exige
instalar mais nada alem do `ezdxf` (ja necessario para o dxf_reader).

Uso:
    py server.py [porta]
    (abre em http://localhost:8765 por padrao)

Rotas:
    GET  /                         -> viewer/index.html
    GET  /viewer/<arquivo>          -> arquivos estaticos do visualizador
    GET  /api/layers?path=...       -> {"layers": {"A-WALL": 42, ...}}
    POST /api/load                  -> body JSON:
        {"path": "C:/.../planta.dxf", "layers": ["A-WALL"],
         "unit_scale_to_cm": null}
        devolve {"walls": [...com "modulation"...], "warnings": [...]}
    POST /api/pick-dwg              -> sem corpo. Abre o dialogo nativo do
        Windows (Explorer) para escolher um .dwg. Devolve
        {"path": "C:/.../planta.dwg"} ou {"path": null} se cancelado.
    POST /api/convert-dwg           -> body {"path": "C:/.../planta.dwg"}.
        Aciona o ODA File Converter instalado no computador e devolve
        {"dxf_path": "C:/.../planta.dxf"}.
    POST /api/analyze-layers        -> body {"path": "...", "expected_layers":
        ["A-WALL"]} (expected_layers opcional). Devolve {"layers": [...]}
        com confianca de cada layer "parecer parede" (geometria + nome).
    POST /api/entities              -> body {"path": "...", "unit_scale_to_cm": null,
        "layers": ["A-WALL"]} (layers opcional). Devolve TODAS as
        entidades lineares do DXF (nao so' as da(s) layer(s) de parede) -
        usado para a planta baixa de referencia no visualizador 3D e o
        inspetor de camadas. Se `layers` for informado, cada entidade
        ganha um "wall_id" (aproximado - ver associate_entities_with_walls
        em wall_pairing.py) indicando a parede final a que ela parece
        pertencer.
    POST /api/edit-wall             -> edita início/fim de uma Wall contínua
        da captura Revit e recalcula blocos/encontros dependentes.
    POST /api/move-opening          -> move uma abertura hospedada ao longo
        da Wall e reaplica a mesma modulação física.
    POST /api/resize-opening        -> altera a largura de uma abertura
        hospedada, preservando-a inteiramente dentro da Wall.
    POST /api/edit-opening          -> edita posição, largura, altura e
        peitoril de uma abertura em uma única operação atômica.
    POST /api/duplicate-opening     -> duplica uma abertura no mesmo host e
        recalcula somente a componente de Walls afetada.
    POST /api/delete-opening        -> remove uma abertura e recalcula sua
        componente de Walls.
    POST /api/calculate-modulation  -> calcula alternativas manuais para
        uma Wall ou uma lista de Walls, usando catálogo/regras do projeto.
"""

import json
import hashlib
import os
import sys
import threading
import time
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dxf_reader import read_dxf_segments, list_layers_with_counts
from wall_pairing import pair_walls_from_segments, associate_entities_with_walls
from wall_capture import (
    walls_from_capture, enrich_openings_for_view,
    openings_for_capture_view,
    solve_capture_block_candidates, adjust_capture_opening, adjust_capture_openings,
    edit_capture_wall, move_capture_opening, resize_capture_opening,
    edit_capture_opening, duplicate_capture_opening, delete_capture_opening,
    dependency_context_wall_ids, warm_dependency_graph,
)
from modulation_preview import preview_walls
from file_dialog import pick_dwg_file, pick_json_file, DialogError
from oda_converter import convert_dwg_to_dxf, OdaNotFoundError, OdaConversionError
from layer_matcher import analyze_layers
from wall_validation import validate_walls
from modulation_calculator import (
    calculate_capture_solutions, calculate_project_solutions, calculate_wall_solutions,
)
from editor_session import EditorSession
from incremental_pipeline import (
    dependency_graph, filter_incremental_payload, geometry_hash,
    merge_scoped_candidates, merge_scoped_statuses, modulation_hash,
    normalize_scoped_candidates, scope_capture, candidate_wall_ids,
    opening_wall_ids, raw_wall_ids,
)

VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
_LOAD_CACHE = OrderedDict()
_SEGMENT_CACHE = OrderedDict()
_CAPTURE_MODELS = OrderedDict()
_CAPTURE_SOLUTIONS = OrderedDict()
_EDITOR_SESSIONS = OrderedDict()
_CACHE_LIMIT = 4

_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}
_VIEWER_BUILD_FILES = ("index.html", "editor-shell.css", "editor-shell.js")


class PreviewSuperseded(Exception):
    """Interrompe silenciosamente uma prévia substituída por intenção nova."""


def _viewer_build_id():
    """Identifica exatamente os arquivos visuais servidos por este processo."""
    digest = hashlib.sha256()
    for filename in _VIEWER_BUILD_FILES:
        digest.update(filename.encode("utf-8"))
        with open(os.path.join(VIEWER_DIR, filename), "rb") as source:
            digest.update(source.read())
    return digest.hexdigest()[:16]


def _versioned_viewer_index():
    """Devolve o HTML com URLs únicas para impedir assets antigos do browser."""
    with open(os.path.join(VIEWER_DIR, "index.html"), "rb") as source:
        html = source.read().decode("utf-8")
    version = _viewer_build_id()
    for filename in ("editor-shell.css", "editor-shell.js"):
        asset = "/viewer/{}".format(filename)
        html = html.replace(asset, "{}?v={}".format(asset, version))
    return html.encode("utf-8")


def _file_cache_key(path, *options):
    stat = os.stat(path)
    return (os.path.abspath(path), stat.st_mtime_ns, stat.st_size) + tuple(options)


def _remember(cache, key, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)


def _read_dxf_segments_cached(path, layers=None, unit_scale_to_cm=None):
    layer_key = tuple(sorted(layer.lower() for layer in (layers or [])))
    key = _file_cache_key(path, layer_key, unit_scale_to_cm)
    cached = _SEGMENT_CACHE.get(key)
    if cached is None:
        cached = read_dxf_segments(path, layers=layers, unit_scale_to_cm=unit_scale_to_cm)
        _remember(_SEGMENT_CACHE, key, cached)
    else:
        _SEGMENT_CACHE.move_to_end(key)
    return [dict(segment) for segment in cached]


def _store_capture_model(cache_key, capture, candidates=None, diagnostics=None):
    model_id = hashlib.sha1(repr(cache_key).encode("utf-8")).hexdigest()[:16]
    _remember(_CAPTURE_MODELS, model_id, capture)
    if candidates is not None and diagnostics is not None:
        _remember(_CAPTURE_SOLUTIONS, model_id, {
            "candidates": candidates,
            "diagnostics": diagnostics,
        })
    # A sessão é deliberadamente separada dos caches legados: ela contém o
    # histórico e a geração atual do editor, enquanto os caches continuam
    # atendendo o carregamento de arquivos sem editar o modelo.
    _remember(_EDITOR_SESSIONS, model_id, EditorSession(capture, candidates, diagnostics))
    if capture.get("walls"):
        worker = threading.Thread(target=warm_dependency_graph, args=(capture,))
        worker.daemon = True
        worker.start()
    return model_id


def _session_payload_metadata(payload, session, request_revision=None):
    """Anexa estado de concorrência/histórico sem expor snapshots internos."""
    if session is None:
        return payload
    payload["revision"] = session.revision
    if request_revision is not None:
        payload["request_revision"] = request_revision
    payload["history"] = session.history_summary()
    return payload


def _append_block_warnings(warnings, block_diagnostics):
    if block_diagnostics.get("status") == "error":
        warnings.append("Solver de blocos: {}".format(block_diagnostics.get("reason")))
    if block_diagnostics.get("invalid_b34_count"):
        warnings.append("Bloco B34 encontrado fora de amarracao; a solucao foi reprovada.")
    if block_diagnostics.get("lintel_missing_count"):
        warnings.append(
            "{} abertura(s) sem modulacao valida acima da verga.".format(
                block_diagnostics["lintel_missing_count"]
            )
        )
    if block_diagnostics.get("blocks_below_reference_count"):
        warnings.append("Ha blocos abaixo da cota de referencia da planta.")
    if block_diagnostics.get("error_candidate_count"):
        warnings.append(
            "{} bloco(s) de parede reprovada foram mantidos em vermelho para revisao."
            .format(block_diagnostics["error_candidate_count"])
        )


def _capture_view_payload(capture, candidates=None, block_diagnostics=None):
    segments = [dict(segment) for segment in (capture.get("segments") or [])]
    openings = openings_for_capture_view(capture)
    walls, wall_diagnostics = walls_from_capture(capture)
    if candidates is None or block_diagnostics is None:
        candidates, block_diagnostics = solve_capture_block_candidates(capture)
    walls_with_preview = preview_walls(walls)
    statuses_by_source_id = {}
    for status in (block_diagnostics.get("wall_statuses") or []):
        for source_id in status.get("source_wall_ids") or []:
            statuses_by_source_id[str(source_id)] = status
    for wall in walls_with_preview:
        source_ids = wall.get("source_wall_ids") or [wall.get("element_id"), wall.get("id")]
        statuses = [statuses_by_source_id.get(str(source_id)) for source_id in source_ids]
        statuses = [status for status in statuses if status is not None]
        if statuses:
            wall["modulation_status"] = next(
                (status for status in statuses if not status.get("ok")), statuses[0]
            )
        elif block_diagnostics.get("status") == "ok":
            wall["modulation_status"] = {
                "ok": False,
                "code": "NOT_PROCESSED",
                "reason": "o solver nao devolveu diagnostico para esta parede",
            }
    associate_entities_with_walls(segments, walls)
    openings_for_view = enrich_openings_for_view(walls, openings)
    validation = validate_walls(walls, wall_diagnostics)
    warnings = []
    if wall_diagnostics.get("skipped_walls"):
        warnings.append(
            "{} Wall(s) da captura foram ignoradas por falta de eixo valido.".format(
                wall_diagnostics["skipped_walls"]
            )
        )
    _append_block_warnings(warnings, block_diagnostics)
    return {
        "is_capture": True,
        "source_mode": "revit_walls",
        "walls": walls_with_preview,
        "entities": segments,
        "openings": openings_for_view,
        "block_candidates": candidates,
        "block_diagnostics": block_diagnostics,
        "catalog": capture.get("catalog") or {},
        "setup": capture.get("setup") or {},
        "level": capture.get("level", ""),
        "source": capture.get("source", ""),
        "wall_height_cm": (capture.get("wall_height_m") or 2.8) * 100.0,
        "warnings": warnings,
        "diagnostics": wall_diagnostics,
        "validation": validation,
    }


def _incremental_capture_view_payload(capture, candidates, block_diagnostics,
                                      affected_wall_ids):
    """Monta apenas a geometria que a cena precisa substituir.

    A resposta inicial precisa converter todas as Walls da captura para o
    formato de visualização. Em uma edição, porém, o browser já possui essa
    cena: recriar as outras centenas de Walls só para descartá-las no filtro
    seguinte consumia a maior parte do tempo da prévia. O solver continua
    recebendo seu contexto de encontro; este helper limita *somente a camada
    de apresentação* às Walls primárias que de fato serão trocadas na cena.
    """
    affected_ids = list(affected_wall_ids or [])
    scoped_capture = scope_capture(capture, affected_ids)
    wanted = set(str(value) for value in affected_ids if str(value))
    scoped_candidates = [
        candidate for candidate in (candidates or [])
        if candidate_wall_ids(candidate) & wanted
    ]
    payload = _capture_view_payload(
        scoped_capture, scoped_candidates, block_diagnostics
    )
    payload = filter_incremental_payload(payload, affected_ids)
    # ``filter_incremental_payload`` enxerga deliberadamente só o recorte.
    # Os totais, por sua vez, devem continuar descrevendo o modelo inteiro.
    payload["totals"] = {
        "walls": len(capture.get("walls") or []),
        "openings": len(capture.get("openings") or []),
        "block_candidates": len(candidates or []),
    }
    # A validação de uma única componente não pode substituir os avisos do
    # projeto todo que o cliente já exibe. O diagnóstico do solver permanece,
    # pois ele contém os contadores globais atualizados após a mesclagem.
    for key in ("validation", "diagnostics", "warnings"):
        payload.pop(key, None)
    return payload


def _merge_incremental_cache_payload(cached_payload, delta_payload, candidates,
                                     diagnostics, affected_wall_ids):
    """Mantém a cópia completa de recarga sem reconstruir a cena inteira.

    O cache de ``/api/load`` é usado quando o navegador é atualizado depois
    de uma edição confirmada. Ele precisa continuar completo, enquanto a
    resposta da edição pode ser compacta. Mesclamos o mesmo delta de volta ao
    snapshot em cache para não pagar a conversão integral de Walls no fim de
    cada arraste.
    """
    wanted = set(str(value) for value in (affected_wall_ids or []) if str(value))
    merged = dict(cached_payload)
    merged["walls"] = [
        wall for wall in (cached_payload.get("walls") or [])
        if not (raw_wall_ids(wall) & wanted)
    ] + list(delta_payload.get("walls") or [])
    merged["openings"] = [
        opening for opening in (cached_payload.get("openings") or [])
        if not (opening_wall_ids(opening) & wanted)
    ] + list(delta_payload.get("openings") or [])
    merged["block_candidates"] = [
        candidate for candidate in (cached_payload.get("block_candidates") or [])
        if not (candidate_wall_ids(candidate) & wanted)
    ] + [
        candidate for candidate in (candidates or [])
        if candidate_wall_ids(candidate) & wanted
    ]
    merged["block_diagnostics"] = diagnostics
    merged["totals"] = dict(delta_payload.get("totals") or {})
    merged.pop("incremental_patch", None)
    merged.pop("compact_block_candidates", None)
    return merged


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("[server] " + (format % args) + "\n")

    def _send_json(self, status, payload):
        serialization_started = time.perf_counter()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        performance = payload.get("performance_ms") if isinstance(payload, dict) else None
        if isinstance(performance, dict):
            performance["serialization"] = round(
                (time.perf_counter() - serialization_started) * 1000.0, 1
            )
            performance["response_bytes"] = len(body)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        if isinstance(performance, dict):
            self.send_header(
                "Server-Timing",
                "detect;dur={}, solver;dur={}, payload;dur={}".format(
                    performance.get("detection", 0), performance.get("solver", 0),
                    performance.get("payload", 0),
                ),
            )
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        with open(path, "rb") as f:
            body = f.read()
        self._send_bytes(body, content_type)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_bytes(_versioned_viewer_index(), "text/html; charset=utf-8")

        if parsed.path == "/api/health":
            return self._send_json(200, {
                "status": "ok",
                "build": _viewer_build_id(),
            })

        if parsed.path.startswith("/viewer/"):
            rel = parsed.path[len("/viewer/"):]
            full = os.path.normpath(os.path.join(VIEWER_DIR, rel))
            if not full.startswith(VIEWER_DIR) or not os.path.isfile(full):
                return self._send_json(404, {"error": "nao encontrado"})
            ext = os.path.splitext(full)[1]
            return self._send_file(full, _STATIC_CONTENT_TYPES.get(ext, "application/octet-stream"))

        if parsed.path == "/api/layers":
            qs = parse_qs(parsed.query)
            path = (qs.get("path") or [""])[0]
            try:
                layers = list_layers_with_counts(path)
                return self._send_json(200, {"layers": layers})
            except Exception as exc:
                return self._send_json(400, {"error": str(exc)})

        return self._send_json(404, {"error": "rota desconhecida"})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/load":
            return self._handle_load()
        if parsed.path == "/api/pick-dwg":
            return self._handle_pick_dwg()
        if parsed.path == "/api/pick-json":
            return self._handle_pick_json()
        if parsed.path == "/api/convert-dwg":
            return self._handle_convert_dwg()
        if parsed.path == "/api/analyze-layers":
            return self._handle_analyze_layers()
        if parsed.path == "/api/entities":
            return self._handle_entities()
        if parsed.path == "/api/adjust-opening":
            return self._handle_adjust_opening()
        if parsed.path == "/api/edit-wall":
            return self._handle_edit_wall()
        if parsed.path == "/api/move-opening":
            return self._handle_move_opening()
        if parsed.path == "/api/resize-opening":
            return self._handle_resize_opening()
        if parsed.path == "/api/edit-opening":
            return self._handle_edit_opening()
        if parsed.path == "/api/duplicate-opening":
            return self._handle_opening_collection_edit("duplicate")
        if parsed.path == "/api/delete-opening":
            return self._handle_opening_collection_edit("delete")
        if parsed.path == "/api/undo":
            return self._handle_history_move(-1)
        if parsed.path == "/api/redo":
            return self._handle_history_move(1)
        if parsed.path == "/api/calculate-modulation":
            return self._handle_calculate_modulation()

        return self._send_json(404, {"error": "rota desconhecida"})

    def _handle_load(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})

        path = body.get("path")
        layers = body.get("layers") or None
        unit_scale_to_cm = body.get("unit_scale_to_cm")

        if not path or not os.path.isfile(path):
            return self._send_json(400, {"error": "Arquivo nao encontrado: {!r}".format(path)})

        cache_key = _file_cache_key(
            path,
            tuple(sorted(layer.lower() for layer in (layers or []))),
            unit_scale_to_cm,
        )
        cached_payload = _LOAD_CACHE.get(cache_key)
        if cached_payload is not None:
            _LOAD_CACHE.move_to_end(cache_key)
            response = dict(cached_payload)
            response["performance_ms"] = dict(response.get("performance_ms") or {})
            response["performance_ms"].update({"total": 0.0, "cache_hit": True})
            return self._send_json(200, response)
        started_at = time.perf_counter()

        # Suporte a arquivo de captura JSON gerado pelo Revit (AbrirModeladorExterno.pushbutton)
        if path.lower().endswith(".json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    capture = json.load(f)

                segments = capture.get("segments", [])
                openings = openings_for_capture_view(capture)
                catalog = capture.get("catalog", {})
                setup = capture.get("setup", {})
                wall_height_m = capture.get("wall_height_m") or 2.8
                wall_height_cm = wall_height_m * 100.0

                warnings = []
                if capture.get("walls"):
                    walls, wall_diagnostics = walls_from_capture(capture)
                    block_candidates, block_diagnostics = solve_capture_block_candidates(capture)
                    if wall_diagnostics.get("skipped_walls"):
                        warnings.append(
                            "{} Wall(s) da captura foram ignoradas por falta de eixo valido.".format(
                                wall_diagnostics["skipped_walls"]
                            )
                        )
                else:
                    target_thicknesses = setup.get("thicknesses_cm")
                    layer = setup.get("layer")
                    req_layers = layers or ([layer] if layer else None)

                    if req_layers:
                        wall_segments = [s for s in segments if s.get("layer") in req_layers]
                    else:
                        wall_segments = segments

                    if not wall_segments:
                        warnings.append("Nenhum segmento encontrado para as camadas selecionadas na captura.")

                    walls, wall_diagnostics = pair_walls_from_segments(
                        wall_segments,
                        target_thicknesses_cm=target_thicknesses,
                        openings_json=openings,
                        wall_height_cm=wall_height_cm,
                        include_unused_lines=False,
                    )
                    block_candidates, block_diagnostics = [], {"status": "skipped", "reason": "captura por segmentos"}
                walls_with_preview = preview_walls(walls)
                _append_block_warnings(warnings, block_diagnostics)

                single_line_count = sum(1 for w in walls_with_preview if w["single_line"])
                if single_line_count:
                    warnings.append(
                        "{} parede(s) ficaram com uma unica face (nao encontrei o par "
                        "paralelo correspondente) - confira no visualizador.".format(single_line_count)
                    )
                if wall_diagnostics.get("duplicates_removed"):
                    warnings.append(
                        "{} parede(s) duplicada(s) foram removidas (mesma posicao/espessura, "
                        "provavel linha de hachura/cota repetida no CAD).".format(
                            wall_diagnostics["duplicates_removed"]
                        )
                    )

                validation = validate_walls(walls, wall_diagnostics)
                associate_entities_with_walls(segments, walls)

                openings_for_view = enrich_openings_for_view(walls, openings)

                payload = {
                    "is_capture": True,
                    "source_mode": "revit_walls" if capture.get("walls") else "segments",
                    "walls": walls_with_preview,
                    "entities": segments,
                    "openings": openings_for_view,
                    "block_candidates": block_candidates,
                    "block_diagnostics": block_diagnostics,
                    "catalog": catalog,
                    "setup": setup,
                    "level": capture.get("level", ""),
                    "source": capture.get("source", ""),
                    "wall_height_cm": wall_height_cm,
                    "warnings": warnings,
                    "diagnostics": wall_diagnostics,
                    "validation": validation,
                    "performance_ms": {
                        "total": round((time.perf_counter() - started_at) * 1000.0, 1),
                        "cache_hit": False,
                    },
                }
                payload["model_id"] = _store_capture_model(
                    cache_key, capture, block_candidates, block_diagnostics
                )
                _session_payload_metadata(payload, _EDITOR_SESSIONS.get(payload["model_id"]))
                _remember(_LOAD_CACHE, cache_key, payload)
                return self._send_json(200, payload)
            except Exception as exc:
                traceback.print_exc()
                return self._send_json(500, {"error": str(exc)})

        try:
            segments = _read_dxf_segments_cached(path, layers=layers, unit_scale_to_cm=unit_scale_to_cm)
            warnings = []
            if not segments:
                warnings.append("Nenhum segmento de reta encontrado (confira a layer escolhida).")
            walls, wall_diagnostics = pair_walls_from_segments(segments)
            walls_with_preview = preview_walls(walls)
            single_line_count = sum(1 for w in walls_with_preview if w["single_line"])
            if single_line_count:
                warnings.append(
                    "{} parede(s) ficaram com uma unica face (nao encontrei o par "
                    "paralelo correspondente) - confira no visualizador.".format(single_line_count)
                )
            if wall_diagnostics["duplicates_removed"]:
                warnings.append(
                    "{} parede(s) duplicada(s) foram removidas (mesma posicao/espessura, "
                    "provavel linha de hachura/cota repetida no CAD).".format(
                        wall_diagnostics["duplicates_removed"]
                    )
                )
            validation = validate_walls(walls, wall_diagnostics)
            payload = {
                "walls": walls_with_preview,
                "warnings": warnings,
                "diagnostics": wall_diagnostics,
                "validation": validation,
                "performance_ms": {
                    "total": round((time.perf_counter() - started_at) * 1000.0, 1),
                    "cache_hit": False,
                },
            }
            _remember(_LOAD_CACHE, cache_key, payload)
            return self._send_json(200, payload)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_adjust_opening(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})

        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        if body.get("base_revision") is not None and int(body.get("base_revision")) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        capture = state["capture"]

        started_at = time.perf_counter()
        try:
            preview_only = bool(body.get("preview"))
            if body.get("mode") == "auto" and not body.get("opening_id"):
                adjusted, action, candidates, diagnostics = adjust_capture_openings(capture)
            else:
                adjusted, action, candidates, diagnostics = adjust_capture_opening(
                    capture,
                    body.get("opening_id"),
                    delta_cm=body.get("delta_cm"),
                    automatic=body.get("mode") == "auto",
                )
            payload = _capture_view_payload(adjusted, candidates, diagnostics)
            payload["model_id"] = model_id
            payload["adjustment"] = action
            payload["preview"] = preview_only
            payload["performance_ms"] = {
                "total": round((time.perf_counter() - started_at) * 1000.0, 1),
                "cache_hit": False,
            }
            if action.get("accepted"):
                if preview_only:
                    _session_payload_metadata(payload, session, body.get("revision"))
                    return self._send_json(200, payload)
                action["history_label"] = "Ajustar abertura" if action.get("opening_id") else "Ajustar aberturas"
                accepted, revision, state = session.commit(
                    base_revision, adjusted, candidates, diagnostics, action
                )
                if not accepted:
                    return self._send_json(409, {
                        "error": "O modelo mudou durante o cálculo; ajuste descartado.",
                        "revision": revision, "history": session.history_summary(),
                    })
                _remember(_CAPTURE_MODELS, model_id, state["capture"])
                _remember(_CAPTURE_SOLUTIONS, model_id, {
                    "candidates": state["candidates"], "diagnostics": state["diagnostics"],
                })
                _session_payload_metadata(payload, session, body.get("revision"))
                for cache_key, cached_payload in list(_LOAD_CACHE.items()):
                    if cached_payload.get("model_id") == model_id:
                        cached_adjusted = dict(payload)
                        cached_adjusted["performance_ms"] = {
                            "total": payload["performance_ms"]["total"],
                            "cache_hit": False,
                        }
                        _remember(_LOAD_CACHE, cache_key, cached_adjusted)
                        break
                return self._send_json(200, payload)
            return self._send_json(409, payload)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _recalculate_capture_edit(self, model_id, capture, action, should_cancel=None):
        """Executa só a componente conectada e preserva candidatos independentes."""
        calculation_started = time.perf_counter()
        groups = action.get("solver_group_keys") or []
        affected_ids = list(action.get("affected_wall_ids") or action.get("source_wall_ids") or [])
        previous_solution = _CAPTURE_SOLUTIONS.get(model_id)
        if previous_solution is not None and groups and affected_ids:
            detection_started = time.perf_counter()
            context_ids = dependency_context_wall_ids(capture, affected_ids)
            scoped_capture = scope_capture(capture, context_ids)
            geometry_key = geometry_hash(capture, affected_ids, groups)
            modulation_key = modulation_hash(capture)
            detection_ms = (time.perf_counter() - detection_started) * 1000.0
            if should_cancel is not None and should_cancel():
                raise PreviewSuperseded()
            solver_started = time.perf_counter()
            scoped_candidates, changed_diagnostics = solve_capture_block_candidates(
                scoped_capture, group_keys=groups
            )
            solver_ms = (time.perf_counter() - solver_started) * 1000.0
            if should_cancel is not None and should_cancel():
                raise PreviewSuperseded()
            wanted = set(str(value) for value in affected_ids)
            changed_candidates = normalize_scoped_candidates([
                candidate for candidate in scoped_candidates
                if candidate_wall_ids(candidate) & wanted
            ])
            action["processed_source_wall_ids"] = sorted(wanted)
            action["solver_context_wall_ids"] = sorted(set(str(value) for value in context_ids))
            candidates, removed_count, added_count = merge_scoped_candidates(
                previous_solution.get("candidates") or [], changed_candidates, affected_ids
            )
            statuses = merge_scoped_statuses(
                (previous_solution.get("diagnostics") or {}).get("wall_statuses") or [],
                changed_diagnostics.get("wall_statuses") or [], affected_ids,
            )
            diagnostics = dict(previous_solution.get("diagnostics") or {})
            diagnostics.update({
                "status": changed_diagnostics.get("status", "ok"),
                "candidate_count": len(candidates),
                "wall_statuses": statuses,
                "processed_group_keys": changed_diagnostics.get("processed_group_keys") or groups,
                "partial_recalculation": True,
            })
            affected_courses = sorted(set(
                int(candidate.get("course_index")) for candidate in changed_candidates
                if candidate.get("course_index") is not None
            ))
            action["affected_course_indices"] = affected_courses
            action["blocks_removed"] = removed_count
            action["blocks_added"] = added_count
            action["dependency_graph"] = dependency_graph(action)
            performance = {
                "detection": round(detection_ms, 1),
                "solver": round(solver_ms, 1),
                "affected_walls": len(set(str(value) for value in affected_ids)),
                "processed_walls": len(set(str(value) for value in context_ids)),
                "context_wall_ids": sorted(set(str(value) for value in context_ids)),
                "affected_courses": len(affected_courses),
                "course_indices": affected_courses,
                "blocks_added": added_count,
                "blocks_removed": removed_count,
                "geometry_hash": geometry_key,
                "modulation_hash": modulation_key,
                "calculation": round((time.perf_counter() - calculation_started) * 1000.0, 1),
                "incremental_reuse": True,
            }
            return candidates, diagnostics, performance
        solver_started = time.perf_counter()
        candidates, diagnostics = solve_capture_block_candidates(capture)
        solver_ms = (time.perf_counter() - solver_started) * 1000.0
        return candidates, diagnostics, {
            "detection": 0.0, "solver": round(solver_ms, 1),
            "affected_walls": len(capture.get("walls") or []),
            "processed_walls": len(capture.get("walls") or []),
            "blocks_added": len(candidates), "blocks_removed": 0,
            "geometry_hash": geometry_hash(capture, affected_ids, groups),
            "modulation_hash": modulation_hash(capture),
            "calculation": round((time.perf_counter() - calculation_started) * 1000.0, 1),
        }

    def _preview_capture_edit(self, model_id, capture, action, started_at,
                              session=None, base_revision=None, request_revision=None):
        """Prévia efêmera: calcula, renderiza e nunca altera o modelo salvo."""
        cache_key = None
        preview_generation = session.begin_preview() if session is not None else None
        if session is not None:
            cache_key = "{}:{}".format(
                base_revision, geometry_hash(
                    capture, action.get("affected_wall_ids") or action.get("source_wall_ids") or [],
                    action.get("solver_group_keys") or [],
                )
            )
            try:
                solved, cache_hit = session.preview(
                    cache_key,
                    lambda: self._recalculate_capture_edit(
                        model_id, capture, action,
                        should_cancel=lambda: not session.is_preview_current(preview_generation),
                    ),
                )
            except PreviewSuperseded:
                return self._send_json(409, {
                    "cancelled": True, "reason": "preview_superseded",
                    "request_revision": request_revision,
                })
            if not session.is_preview_current(preview_generation):
                return self._send_json(409, {
                    "cancelled": True, "reason": "preview_superseded",
                    "request_revision": request_revision,
                })
            candidates, diagnostics, performance = solved
            action["processed_source_wall_ids"] = sorted(set(
                str(value) for value in (
                    action.get("affected_wall_ids") or action.get("source_wall_ids") or []
                )
            ))
            action["solver_context_wall_ids"] = performance.get("context_wall_ids") or action.get(
                "processed_source_wall_ids"
            )
            action["affected_course_indices"] = performance.get("course_indices") or []
            action["blocks_added"] = performance.get("blocks_added", 0)
            action["blocks_removed"] = performance.get("blocks_removed", 0)
            action["dependency_graph"] = dependency_graph(action)
        else:
            candidates, diagnostics, performance = self._recalculate_capture_edit(
                model_id, capture, action
            )
            cache_hit = False
        payload_started = time.perf_counter()
        payload = _incremental_capture_view_payload(
            capture, candidates, diagnostics,
            action.get("affected_wall_ids") or action.get("source_wall_ids") or [],
        )
        payload["model_id"] = model_id
        payload["edit"] = action
        payload["dependency_graph"] = action.get("dependency_graph") or dependency_graph(action)
        payload["preview"] = True
        performance = dict(performance)
        performance.update({
            "payload": round((time.perf_counter() - payload_started) * 1000.0, 1),
            "total": round((time.perf_counter() - started_at) * 1000.0, 1),
            "cache_hit": cache_hit,
            "response_candidates": len(payload.get("block_candidates") or []),
        })
        payload["performance_ms"] = performance
        _session_payload_metadata(payload, session, request_revision)
        return self._send_json(200, payload)

    def _commit_capture_edit(self, model_id, capture, action, started_at,
                             session=None, base_revision=None, request_revision=None):
        """Recalcula a mesma modulação completa usada na carga inicial.

        O motor já separa o cálculo por nível/faixa de base. O metadado de
        escopo devolvido na ação mostra quais Walls conectadas foram afetadas;
        assim a UI atualiza a região dependente sem inventar uma segunda
        regra simplificada para o arraste.
        """
        if session is not None:
            session.cancel_previews()
        candidates, diagnostics, performance = self._recalculate_capture_edit(
            model_id, capture, action
        )
        payload_started = time.perf_counter()
        payload = _incremental_capture_view_payload(
            capture, candidates, diagnostics,
            action.get("affected_wall_ids") or action.get("source_wall_ids") or [],
        )
        payload["model_id"] = model_id
        payload["edit"] = action
        payload["dependency_graph"] = action.get("dependency_graph") or dependency_graph(action)
        performance = dict(performance)
        performance.update({
            "payload": round((time.perf_counter() - payload_started) * 1000.0, 1),
            "total": round((time.perf_counter() - started_at) * 1000.0, 1),
            "cache_hit": False,
            "response_candidates": len(payload.get("block_candidates") or []),
        })
        payload["performance_ms"] = performance
        if session is not None:
            accepted, revision, state = session.commit(
                base_revision, capture, candidates, diagnostics, action
            )
            if not accepted:
                return self._send_json(409, {
                    "error": "A edição partiu de uma revisão antiga; o modelo foi atualizado por outra operação.",
                    "revision": revision,
                    "history": session.history_summary(),
                })
            capture = state["capture"]
            candidates = state["candidates"]
            diagnostics = state["diagnostics"]
        _remember(_CAPTURE_MODELS, model_id, capture)
        _remember(_CAPTURE_SOLUTIONS, model_id, {
            "candidates": candidates, "diagnostics": diagnostics,
        })
        _session_payload_metadata(payload, session, request_revision)
        for cache_key, cached_payload in list(_LOAD_CACHE.items()):
            if cached_payload.get("model_id") == model_id:
                cached_full = _merge_incremental_cache_payload(
                    cached_payload, payload, candidates, diagnostics,
                    action.get("affected_wall_ids") or action.get("source_wall_ids") or [],
                )
                cached_full["model_id"] = model_id
                cached_full["performance_ms"] = dict(performance)
                _session_payload_metadata(cached_full, session, request_revision)
                _remember(_LOAD_CACHE, cache_key, cached_full)
                break
        return self._send_json(200, payload)

    def _handle_edit_wall(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        requested_base_revision = body.get("base_revision")
        if requested_base_revision is not None and int(requested_base_revision) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        capture = state["capture"]
        started_at = time.perf_counter()
        try:
            edited, action = edit_capture_wall(
                capture, body.get("wall_id"), body.get("start_cm"), body.get("end_cm"),
                body.get("thickness_cm"), body.get("height_cm")
            )
            if not action.get("accepted"):
                return self._send_json(409, {"edit": action})
            action["history_label"] = "Editar parede {}".format(action.get("wall_id") or body.get("wall_id"))
            if body.get("preview"):
                return self._preview_capture_edit(
                    model_id, edited, action, started_at, session, base_revision, body.get("revision")
                )
            return self._commit_capture_edit(
                model_id, edited, action, started_at, session, base_revision, body.get("revision")
            )
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_move_opening(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        requested_base_revision = body.get("base_revision")
        if requested_base_revision is not None and int(requested_base_revision) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        capture = state["capture"]
        started_at = time.perf_counter()
        try:
            edited, action = move_capture_opening(
                capture, body.get("opening_id"), body.get("center_cm")
            )
            if not action.get("accepted"):
                return self._send_json(409, {"edit": action})
            action["history_label"] = "Mover abertura {}".format(action.get("opening_id") or body.get("opening_id"))
            if body.get("preview"):
                return self._preview_capture_edit(
                    model_id, edited, action, started_at, session, base_revision, body.get("revision")
                )
            return self._commit_capture_edit(
                model_id, edited, action, started_at, session, base_revision, body.get("revision")
            )
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_resize_opening(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        requested_base_revision = body.get("base_revision")
        if requested_base_revision is not None and int(requested_base_revision) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        capture = state["capture"]
        started_at = time.perf_counter()
        try:
            edited, action = resize_capture_opening(
                capture, body.get("opening_id"), body.get("width_cm")
            )
            if not action.get("accepted"):
                return self._send_json(409, {"edit": action})
            action["history_label"] = "Redimensionar abertura {}".format(action.get("opening_id") or body.get("opening_id"))
            if body.get("preview"):
                return self._preview_capture_edit(
                    model_id, edited, action, started_at, session, base_revision, body.get("revision")
                )
            return self._commit_capture_edit(
                model_id, edited, action, started_at, session, base_revision, body.get("revision")
            )
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_edit_opening(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        requested_base_revision = body.get("base_revision")
        if requested_base_revision is not None and int(requested_base_revision) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        started_at = time.perf_counter()
        try:
            edited, action = edit_capture_opening(
                state["capture"], body.get("opening_id"), body.get("center_cm"),
                body.get("width_cm"), body.get("height_cm"), body.get("sill_cm"),
            )
            if not action.get("accepted"):
                return self._send_json(409, {"edit": action})
            action["history_label"] = "Editar abertura {}".format(
                action.get("opening_id") or body.get("opening_id")
            )
            if body.get("preview"):
                return self._preview_capture_edit(
                    model_id, edited, action, started_at, session, base_revision, body.get("revision")
                )
            return self._commit_capture_edit(
                model_id, edited, action, started_at, session, base_revision, body.get("revision")
            )
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_opening_collection_edit(self, operation):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        base_revision, state = session.current()
        requested_base_revision = body.get("base_revision")
        if requested_base_revision is not None and int(requested_base_revision) != base_revision:
            return self._send_json(409, {
                "error": "O modelo mudou desde o início da edição.",
                "revision": base_revision, "history": session.history_summary(),
            })
        started_at = time.perf_counter()
        try:
            if operation == "duplicate":
                edited, action = duplicate_capture_opening(
                    state["capture"], body.get("opening_id"), body.get("delta_cm", 10.0)
                )
                label = "Duplicar abertura {}".format(body.get("opening_id"))
            else:
                edited, action = delete_capture_opening(
                    state["capture"], body.get("opening_id")
                )
                label = "Excluir abertura {}".format(body.get("opening_id"))
            if not action.get("accepted"):
                return self._send_json(409, {"edit": action})
            action["history_label"] = label
            return self._commit_capture_edit(
                model_id, edited, action, started_at, session, base_revision, body.get("revision")
            )
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_history_move(self, direction):
        """Restaura uma edição completa (geometria + resultado do solver)."""
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        model_id = str(body.get("model_id") or "")
        session = _EDITOR_SESSIONS.get(model_id)
        if session is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})
        try:
            expected = body.get("base_revision")
            accepted, reason, revision, state = (
                session.undo(expected) if direction < 0 else session.redo(expected)
            )
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "Revisao invalida."})
        if not accepted:
            status = 409 if reason == "stale" else 400
            return self._send_json(status, {
                "error": ("O modelo mudou desde o ultimo comando." if reason == "stale"
                          else "Nao ha nenhuma operacao para desfazer/refazer."),
                "revision": revision,
                "history": session.history_summary(),
            })
        payload = _capture_view_payload(state["capture"], state["candidates"], state["diagnostics"])
        payload.update({
            "model_id": model_id,
            "edit": {"history_label": "Desfazer" if direction < 0 else "Refazer"},
            "performance_ms": {"total": 0.0, "cache_hit": True},
        })
        _remember(_CAPTURE_MODELS, model_id, state["capture"])
        _remember(_CAPTURE_SOLUTIONS, model_id, {
            "candidates": state["candidates"], "diagnostics": state["diagnostics"],
        })
        _session_payload_metadata(payload, session, body.get("revision"))
        for cache_key, cached_payload in list(_LOAD_CACHE.items()):
            if cached_payload.get("model_id") == model_id:
                _remember(_LOAD_CACHE, cache_key, dict(payload))
                break
        return self._send_json(200, payload)

    def _handle_calculate_modulation(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})
        try:
            model_id = str(body.get("model_id") or "")
            model = _CAPTURE_MODELS.get(model_id) if model_id else None
            catalog = (model or {}).get("catalog") if model else body.get("catalog")
            if model is not None and body.get("solver_mode") == "model":
                result = calculate_capture_solutions(model, body.get("group_keys"))
            elif body.get("walls") is not None:
                result = calculate_project_solutions(body, catalog=catalog)
            else:
                result = calculate_wall_solutions(body, catalog=catalog)
            return self._send_json(200 if result.get("ok") else 400, result)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_analyze_layers(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})

        path = body.get("path")
        expected_layers = body.get("expected_layers") or None
        unit_scale_to_cm = body.get("unit_scale_to_cm")
        if not path or not os.path.isfile(path):
            return self._send_json(400, {"error": "Arquivo nao encontrado: {!r}".format(path)})

        if path.lower().endswith(".json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    capture = json.load(f)
                segments = capture.get("segments", [])
                setup = capture.get("setup", {})
                setup_layer = setup.get("layer")
                counts = {}
                for s in segments:
                    l = s.get("layer", "0")
                    counts[l] = counts.get(l, 0) + 1

                layers_res = []
                for l, count in counts.items():
                    is_main = (l == setup_layer)
                    layers_res.append({
                        "layer": l,
                        "status": "OK" if is_main or count > 10 else "ATENCAO",
                        "geometry_score": 1.0 if is_main else 0.8,
                        "name_score": 1.0 if is_main else 0.8,
                        "confidence": 1.0 if is_main else 0.8,
                        "entity_count": count,
                        "matched_expected": l if is_main else None,
                    })
                return self._send_json(200, {"layers": layers_res})
            except Exception as exc:
                traceback.print_exc()
                return self._send_json(400, {"error": str(exc)})

        try:
            results = analyze_layers(
                path, expected_layers=expected_layers, unit_scale_to_cm=unit_scale_to_cm
            )
            return self._send_json(200, {"layers": results})
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(400, {"error": str(exc)})

    def _handle_entities(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})

        path = body.get("path")
        unit_scale_to_cm = body.get("unit_scale_to_cm")
        layers = body.get("layers") or None
        if not path or not os.path.isfile(path):
            return self._send_json(400, {"error": "Arquivo nao encontrado: {!r}".format(path)})

        if path.lower().endswith(".json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    capture = json.load(f)
                segments = capture.get("segments", [])
                setup = capture.get("setup", {})
                target_thicknesses = setup.get("thicknesses_cm")
                layer = setup.get("layer")
                req_layers = layers or ([layer] if layer else None)
                if req_layers:
                    wall_segments = [s for s in segments if s.get("layer") in req_layers]
                else:
                    wall_segments = segments
                walls, _diagnostics = pair_walls_from_segments(
                    wall_segments, target_thicknesses_cm=target_thicknesses
                )
                associate_entities_with_walls(segments, walls)
                return self._send_json(200, {"entities": segments})
            except Exception as exc:
                traceback.print_exc()
                return self._send_json(400, {"error": str(exc)})

        try:
            segments = _read_dxf_segments_cached(path, unit_scale_to_cm=unit_scale_to_cm)
            if layers:
                selected_layers = set(layer.lower() for layer in layers)
                wall_segments = [
                    segment for segment in segments
                    if (segment.get("layer") or "").lower() in selected_layers
                ]
                walls, _diagnostics = pair_walls_from_segments(wall_segments)
                associate_entities_with_walls(segments, walls)
            return self._send_json(200, {"entities": segments})
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(400, {"error": str(exc)})

    def _handle_pick_dwg(self):
        try:
            path = pick_dwg_file()
            return self._send_json(200, {"path": path})
        except DialogError as exc:
            return self._send_json(500, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_pick_json(self):
        try:
            path = pick_json_file()
            return self._send_json(200, {"path": path})
        except DialogError as exc:
            return self._send_json(500, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})

    def _handle_convert_dwg(self):
        try:
            body = self._read_json_body()
        except Exception:
            return self._send_json(400, {"error": "JSON invalido no corpo da requisicao"})

        dwg_path = body.get("path")
        if not dwg_path or not os.path.isfile(dwg_path):
            return self._send_json(400, {"error": "Arquivo DWG nao encontrado: {!r}".format(dwg_path)})
        if os.path.splitext(dwg_path)[1].lower() != ".dwg":
            return self._send_json(400, {"error": "O arquivo selecionado nao e' um .dwg: {!r}".format(dwg_path)})

        try:
            dxf_path = convert_dwg_to_dxf(dwg_path)
            return self._send_json(200, {"dxf_path": dxf_path})
        except OdaNotFoundError as exc:
            return self._send_json(400, {"error": str(exc)})
        except OdaConversionError as exc:
            return self._send_json(500, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            return self._send_json(500, {"error": str(exc)})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Visualizador rodando em http://localhost:{}/ (Ctrl+C para parar)".format(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
