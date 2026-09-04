# -*- coding: utf-8 -*-
"""Contrato HTTP do histórico do editor, sem abrir uma porta TCP."""

import copy
import unittest

import server
from editor_session import EditorSession


class TestEditorServer(unittest.TestCase):
    def setUp(self):
        self.model_id = "editor-history-test"
        self.capture = {
            "walls": [{
                "element_id": "W1", "start_cm": [0, 0], "end_cm": [400, 0],
                "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0,
            }],
            "openings": [{
                "element_id": "P1", "host_wall_id": "W1", "center_cm": [100, 0],
                "width_cm": 80, "sill_cm": 0, "head_cm": 210,
            }],
            "catalog": {},
        }
        self.diagnostics = {"status": "ok", "wall_statuses": []}
        self.session = EditorSession(self.capture, [], self.diagnostics)
        changed = copy.deepcopy(self.capture)
        changed["openings"][0]["center_cm"] = [200, 0]
        accepted, _revision, _state = self.session.commit(
            0, changed, [], self.diagnostics, {"history_label": "Mover abertura P1"}
        )
        self.assertTrue(accepted)
        server._EDITOR_SESSIONS[self.model_id] = self.session
        server._CAPTURE_MODELS[self.model_id] = changed
        server._CAPTURE_SOLUTIONS[self.model_id] = {"candidates": [], "diagnostics": self.diagnostics}

    def tearDown(self):
        server._EDITOR_SESSIONS.pop(self.model_id, None)
        server._CAPTURE_MODELS.pop(self.model_id, None)
        server._CAPTURE_SOLUTIONS.pop(self.model_id, None)

    def test_undo_restores_snapshot_and_advances_revision(self):
        handler = server.Handler.__new__(server.Handler)
        handler._read_json_body = lambda: {
            "model_id": self.model_id, "base_revision": 1, "revision": 44,
        }
        response = {}
        handler._send_json = lambda status, payload: response.update(status=status, payload=payload)

        handler._handle_history_move(-1)

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["payload"]["revision"], 2)
        self.assertEqual(response["payload"]["request_revision"], 44)
        self.assertTrue(response["payload"]["history"]["can_redo"])
        opening = response["payload"]["openings"][0]
        self.assertEqual(opening["center_cm"], [100, 0])

    def test_incremental_view_payload_only_builds_and_returns_changed_component(self):
        capture = copy.deepcopy(self.capture)
        capture["walls"].append({
            "element_id": "W2", "start_cm": [600, 0], "end_cm": [1000, 0],
            "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0,
        })
        capture["openings"].append({
            "element_id": "P2", "host_wall_id": "W2", "center_cm": [700, 0],
            "width_cm": 80, "sill_cm": 0, "head_cm": 210,
        })
        candidates = [
            {"id": "w1", "wall_id": "W1", "logical_code": "B39"},
            {"id": "w2", "wall_id": "W2", "logical_code": "B39"},
        ]
        payload = server._incremental_capture_view_payload(
            capture, candidates, {"status": "ok", "wall_statuses": []}, ["W1"]
        )

        self.assertTrue(payload["incremental_patch"])
        self.assertEqual(["W1"], [wall["element_id"] for wall in payload["walls"]])
        self.assertEqual(["P1"], [opening["element_id"] for opening in payload["openings"]])
        self.assertEqual(["w1"], [block["id"] for block in payload["block_candidates"]])
        self.assertEqual({"walls": 2, "openings": 2, "block_candidates": 2}, payload["totals"])
        self.assertNotIn("validation", payload)

    def test_incremental_commit_keeps_a_complete_reload_cache(self):
        capture = copy.deepcopy(self.capture)
        capture["walls"].append({
            "element_id": "W2", "start_cm": [600, 0], "end_cm": [1000, 0],
            "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0,
        })
        capture["openings"].append({
            "element_id": "P2", "host_wall_id": "W2", "center_cm": [700, 0],
            "width_cm": 80, "sill_cm": 0, "head_cm": 210,
        })
        diagnostics = {"status": "ok", "wall_statuses": []}
        before = [
            {"id": "old-w1", "wall_id": "W1", "logical_code": "B39"},
            {"id": "w2", "wall_id": "W2", "logical_code": "B39"},
        ]
        after = [
            {"id": "new-w1", "wall_id": "W1", "logical_code": "B39"},
            {"id": "w2", "wall_id": "W2", "logical_code": "B39"},
        ]
        cached = server._capture_view_payload(capture, before, diagnostics)
        delta = server._incremental_capture_view_payload(capture, after, diagnostics, ["W1"])
        merged = server._merge_incremental_cache_payload(
            cached, delta, after, diagnostics, ["W1"]
        )

        self.assertEqual({"W1", "W2"}, {wall["element_id"] for wall in merged["walls"]})
        self.assertEqual({"P1", "P2"}, {opening["element_id"] for opening in merged["openings"]})
        self.assertEqual({"new-w1", "w2"}, {item["id"] for item in merged["block_candidates"]})
        self.assertFalse(merged.get("incremental_patch"))


if __name__ == "__main__":
    unittest.main()
