# -*- coding: utf-8 -*-
"""Testes de carregamento de arquivo de captura JSON do Revit no server.py."""

import json
import os
import tempfile
import unittest

import server


class TestCaptureLoad(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_json_capture_generates_walls_and_openings(self):
        capture_data = {
            "schema_version": 1,
            "source": "Projeto Teste",
            "level": "Nivel 1",
            "wall_height_m": 2.8,
            "segments": [
                {"layer": "A-PAREDE", "start": [0.0, 0.0], "end": [300.0, 0.0]},
                {"layer": "A-PAREDE", "start": [0.0, 14.0], "end": [300.0, 14.0]},
            ],
            "openings": [
                {
                    "element_id": "999",
                    "center_cm": [100.0, 7.0],
                    "width_cm": 80.0,
                    "sill_cm": 0.0,
                    "head_cm": 210.0,
                    "center_source": "geometria",
                }
            ],
            "catalog": {
                "B39": {
                    "logical_code": "B39",
                    "length_cm": 39.0,
                    "height_cm": 19.0,
                    "width_cm": 14.0,
                    "cells_local_cm": [],
                    "is_special_bond": False,
                    "is_compensator": False,
                    "color_rgb": [196, 164, 132],
                }
            },
            "setup": {
                "layer": "A-PAREDE",
                "thicknesses_cm": [14.0],
                "openings_mode": "auto",
            },
        }

        json_path = os.path.join(self.temp_dir, "teste_captura.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(capture_data, f)

        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/load"
        req_body = {"path": json_path}
        handler._read_json_body = lambda: req_body

        captured = {}

        def _fake_send_json(status, payload):
            captured["status"] = status
            captured["payload"] = payload

        handler._send_json = _fake_send_json

        handler._handle_load()

        self.assertEqual(captured.get("status"), 200)
        payload = captured.get("payload", {})
        self.assertTrue(payload.get("is_capture"))
        self.assertEqual(len(payload.get("walls", [])), 3)
        self.assertEqual(len(payload.get("openings", [])), 1)
        self.assertEqual(len(payload.get("entities", [])), 2)
        self.assertEqual(payload.get("source"), "Projeto Teste")
        self.assertEqual(payload.get("level"), "Nivel 1")
        self.assertEqual(payload.get("wall_height_cm"), 280.0)


if __name__ == "__main__":
    unittest.main()
