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
"""

import json
import hashlib
import os
import sys
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
    solve_capture_block_candidates, adjust_capture_opening, adjust_capture_openings,
)
from modulation_preview import preview_walls
from file_dialog import pick_dwg_file, pick_json_file, DialogError
from oda_converter import convert_dwg_to_dxf, OdaNotFoundError, OdaConversionError
from layer_matcher import analyze_layers
from wall_validation import validate_walls

VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
_LOAD_CACHE = OrderedDict()
_SEGMENT_CACHE = OrderedDict()
_CAPTURE_MODELS = OrderedDict()
_CACHE_LIMIT = 4

_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


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


def _store_capture_model(cache_key, capture):
    model_id = hashlib.sha1(repr(cache_key).encode("utf-8")).hexdigest()[:16]
    _remember(_CAPTURE_MODELS, model_id, capture)
    return model_id


def _capture_view_payload(capture, candidates=None, block_diagnostics=None):
    segments = [dict(segment) for segment in (capture.get("segments") or [])]
    openings = capture.get("openings") or []
    walls, wall_diagnostics = walls_from_capture(capture)
    if candidates is None or block_diagnostics is None:
        candidates, block_diagnostics = solve_capture_block_candidates(capture)
    walls_with_preview = preview_walls(walls)
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
    if block_diagnostics.get("status") == "error":
        warnings.append("Solver de blocos: {}".format(block_diagnostics.get("reason")))
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("[server] " + (format % args) + "\n")

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send_file(os.path.join(VIEWER_DIR, "index.html"), "text/html; charset=utf-8")

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
                openings = capture.get("openings", [])
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
                payload["model_id"] = _store_capture_model(cache_key, capture)
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
        capture = _CAPTURE_MODELS.get(model_id)
        if capture is None:
            return self._send_json(400, {"error": "Modelo nao encontrado; recarregue a captura."})

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
                    return self._send_json(200, payload)
                _remember(_CAPTURE_MODELS, model_id, adjusted)
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
