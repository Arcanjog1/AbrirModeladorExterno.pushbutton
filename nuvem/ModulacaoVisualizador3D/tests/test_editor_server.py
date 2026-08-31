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


if __name__ == "__main__":
    unittest.main()
