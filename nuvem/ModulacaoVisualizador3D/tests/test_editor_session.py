# -*- coding: utf-8 -*-
import unittest

from editor_session import EditorSession


class TestEditorSession(unittest.TestCase):
    def test_commit_is_atomic_and_undo_redo_restore_same_solver_result(self):
        session = EditorSession({"openings": [{"x": 100}]}, [{"id": "B1"}], {"ok": True})
        revision, state = session.current()
        accepted, next_revision, _state = session.commit(
            revision, {"openings": [{"x": 200}]}, [{"id": "B2"}], {"ok": True},
            {"label": "Mover P04"},
        )
        self.assertTrue(accepted)
        self.assertEqual(next_revision, 1)
        accepted, reason, revision, previous = session.undo(next_revision)
        self.assertTrue(accepted, reason)
        self.assertEqual(previous["capture"]["openings"][0]["x"], 100)
        self.assertEqual(previous["candidates"][0]["id"], "B1")
        accepted, reason, revision, restored = session.redo(revision)
        self.assertTrue(accepted, reason)
        self.assertEqual(restored["capture"]["openings"][0]["x"], 200)
        self.assertEqual(restored["candidates"][0]["id"], "B2")

    def test_stale_commit_cannot_replace_newer_geometry(self):
        session = EditorSession({"x": 1})
        accepted, revision, _state = session.commit(0, {"x": 2}, [], {}, {"label": "primeira"})
        self.assertTrue(accepted)
        accepted, current_revision, current = session.commit(0, {"x": 3}, [], {}, {"label": "atrasada"})
        self.assertFalse(accepted)
        self.assertEqual(current_revision, revision)
        self.assertEqual(current["capture"], {"x": 2})

    def test_preview_cache_never_changes_model(self):
        session = EditorSession({"x": 1})
        calls = []
        first, cache_hit = session.preview("same", lambda: calls.append(1) or {"x": 2})
        second, cache_hit_second = session.preview("same", lambda: calls.append(2) or {"x": 3})
        self.assertFalse(cache_hit)
        self.assertTrue(cache_hit_second)
        self.assertEqual(first, second)
        self.assertEqual(calls, [1])
        _revision, current = session.current()
        self.assertEqual(current["capture"], {"x": 1})
