# -*- coding: utf-8 -*-
import unittest

from incremental_pipeline import (
    candidate_wall_ids,
    dependency_graph,
    filter_incremental_payload,
    geometry_hash,
    merge_scoped_candidates,
    scope_capture,
)
from wall_capture import dependency_context_wall_ids


class IncrementalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.capture = {
            "walls": [
                {"element_id": "MAIN", "start_cm": [0, -200], "end_cm": [0, 200],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0, "level": "L1"},
                {"element_id": "IN", "start_cm": [-200, 0], "end_cm": [0, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0, "level": "L1"},
                {"element_id": "FAR", "start_cm": [800, 0], "end_cm": [1000, 0],
                 "thickness_cm": 14, "height_cm": 280, "base_z_cm": 0, "level": "L1"},
            ],
            "openings": [
                {"element_id": "P1", "host_wall_id": "MAIN", "center_cm": [0, 50],
                 "width_cm": 80, "sill_cm": 90, "head_cm": 210},
                {"element_id": "P2", "host_wall_id": "FAR", "center_cm": [900, 0],
                 "width_cm": 80, "sill_cm": 90, "head_cm": 210},
            ],
            "catalog": {"B39": {"length_cm": 39, "width_cm": 14, "height_cm": 19}},
            "setup": {"joint_cm": 1},
        }

    def test_scope_keeps_only_requested_walls_and_their_openings(self):
        scoped = scope_capture(self.capture, ["MAIN", "IN"])
        self.assertEqual({"MAIN", "IN"}, {wall["element_id"] for wall in scoped["walls"]})
        self.assertEqual(["P1"], [opening["element_id"] for opening in scoped["openings"]])

    def test_dependency_context_includes_direct_t_intersection_not_far_wall(self):
        context = dependency_context_wall_ids(self.capture, ["MAIN"])
        self.assertIn("MAIN", context)
        self.assertIn("IN", context)
        self.assertNotIn("FAR", context)

    def test_geometry_hash_changes_with_opening_but_not_unrelated_wall(self):
        first = geometry_hash(self.capture, ["MAIN"], [["L1", 0]])
        changed = dict(self.capture)
        changed["openings"] = [dict(item) for item in self.capture["openings"]]
        changed["openings"][0]["center_cm"] = [0, 60]
        self.assertNotEqual(first, geometry_hash(changed, ["MAIN"], [["L1", 0]]))
        changed["walls"] = [dict(item) for item in changed["walls"]]
        changed["walls"][2]["height_cm"] = 300
        self.assertEqual(
            geometry_hash(changed, ["MAIN"], [["L1", 0]]),
            geometry_hash({**changed, "walls": changed["walls"][:2]}, ["MAIN"], [["L1", 0]]),
        )

    def test_merge_and_payload_replace_only_affected_wall(self):
        previous = [
            {"id": "old-main", "wall_id": "MAIN"},
            {"id": "old-far", "wall_id": "FAR"},
        ]
        changed = [{"id": "new-main", "wall_id": "MAIN"}]
        merged, removed, added = merge_scoped_candidates(previous, changed, ["MAIN"])
        self.assertEqual((1, 1), (removed, added))
        self.assertEqual({"old-far", "new-main"}, {item["id"] for item in merged})
        self.assertEqual({"MAIN"}, candidate_wall_ids(changed[0]))

        payload = filter_incremental_payload({
            "walls": self.capture["walls"], "openings": self.capture["openings"],
            "block_candidates": merged, "entities": [{"id": "large-plan"}],
        }, ["MAIN"])
        self.assertTrue(payload["incremental_patch"])
        self.assertEqual([], payload["entities"])
        self.assertEqual(["new-main"], [item["id"] for item in payload["block_candidates"]])
        self.assertEqual(2, payload["totals"]["block_candidates"])

    def test_dependency_graph_exposes_affected_context_and_courses(self):
        graph = dependency_graph({
            "opening_id": "P1", "source_wall_ids": ["MAIN"],
            "affected_wall_ids": ["MAIN", "IN"],
            "solver_context_wall_ids": ["MAIN", "IN", "EDGE"],
            "affected_course_indices": [3, 4],
        })
        self.assertEqual(["P1"], graph["changed_elements"])
        self.assertEqual(["MAIN", "IN", "EDGE"], graph["solver_context_wall_ids"])
        self.assertEqual([3, 4], graph["affected_course_indices"])


if __name__ == "__main__":
    unittest.main()
