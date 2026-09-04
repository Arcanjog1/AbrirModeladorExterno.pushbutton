import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer"


class EditorShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (VIEWER / "index.html").read_text(encoding="utf-8")
        cls.css = (VIEWER / "editor-shell.css").read_text(encoding="utf-8")
        cls.javascript = (VIEWER / "editor-shell.js").read_text(encoding="utf-8")
        cls.inline_javascript = "\n".join(re.findall(r"<script>([\s\S]*?)</script>", cls.html))
        cls.server = (ROOT / "server.py").read_text(encoding="utf-8")
        cls.launcher = (ROOT.parent / "external_modelador.py").read_text(encoding="utf-8")

    def test_html_ids_are_unique(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        duplicates = sorted(item for item in set(ids) if ids.count(item) > 1)
        self.assertEqual([], duplicates)

    def test_compact_bim_shell_has_the_primary_surfaces(self):
        required_ids = {
            "app-bar",
            "top-toolbar",
            "navigation-toolbar",
            "view-cube",
            "status-bar",
            "selection-panel",
            "wall-inspector",
            "section-panel",
            "diagnostics-panel",
            "element-search",
            "command-palette",
            "toast-stack",
        }
        found_ids = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertTrue(required_ids.issubset(found_ids))

    def test_theme_tokens_and_responsive_breakpoints_are_declared(self):
        for token in ("#111318", "#181b22", "#20242d", "#3b82f6", ':root[data-theme="light"]'):
            self.assertIn(token, self.css)
        for breakpoint in ("max-width: 1320px", "max-width: 900px", "min-width: 2500px"):
            self.assertIn(breakpoint, self.css)
        self.assertNotIn("linear-gradient", self.css)

    def test_editor_shortcuts_and_contextual_feedback_are_wired(self):
        for feature in (
            "editor:selection-changed",
            "openOverlay('element-search')",
            "openOverlay('command-palette')",
            "showPreviewFeedback",
            "rebuildDiagnosticMarkers",
            "updateHover",
            "showToast",
        ):
            self.assertIn(feature, self.javascript)
        self.assertIn("key === 'f'", self.javascript)
        self.assertIn("key === 'k' || key === 'p'", self.javascript)

    def test_wall_and_section_workflows_are_exposed(self):
        for control in (
            "wall-previous",
            "wall-next",
            "wall-front",
            "wall-side",
            "btn-course-labels",
            "wall-diagnostic",
            "section-live-axis",
            "section-live-slider",
            "section-through-selection",
        ):
            self.assertIn(f'id="{control}"', self.html)

    def test_direct_drag_is_the_primary_edit_flow(self):
        for feature in (
            "interactiveEditAt",
            "directEditSession",
            "startInteractivePointer",
            "interactionPointForSession",
            "editorUpdateDirectPreview",
            "pointercancel",
        ):
            self.assertIn(feature, self.inline_javascript)
        self.assertIn('id="drag-value-badge"', self.html)
        self.assertIn('value="project"', self.html)
        self.assertIn("event.shiftKey", self.inline_javascript)

    def test_contextual_gizmos_and_immediate_feedback_are_wired(self):
        for feature in (
            "editorPickDirectHandle",
            "directManipulationPreviewGroup",
            "requestAnimationFrame(renderDirectPreview)",
            "resize-start",
            "resize-end",
            "mode: 'sill'",
        ):
            self.assertIn(feature, self.javascript)
        self.assertIn("controls.enabled = false", self.inline_javascript)
        self.assertIn("controls.enabled = true", self.inline_javascript)
        self.assertIn("AbortController", self.inline_javascript)

    def test_section_plane_is_pickable_draggable_and_undoable(self):
        for feature in (
            "sectionDragHandle",
            "sectionHitAt",
            "applyPendingSectionDrag",
            "pushSectionHistory",
            "undoSection",
            "redoSection",
            "PlaneGeometry",
            "ArrowHelper",
        ):
            self.assertIn(feature, self.javascript)
        self.assertIn("editorSectionDragging", self.javascript)

    def test_application_bar_actions_are_real_and_wired(self):
        actions = (
            "btn-app-import",
            "btn-app-revit",
            "btn-app-save",
            "btn-app-export",
            "btn-app-send-revit",
            "btn-app-settings",
            "btn-app-help",
        )
        for control in actions + ("processing-indicator",):
            self.assertIn(f'id="{control}"', self.html)
        for control in actions:
            self.assertIn(f"byId('{control}').addEventListener", self.javascript)
        self.assertIn("modulador:apply-to-revit", self.javascript)
        self.assertIn("downloadExport", self.javascript)

    def test_import_drawer_is_progressive_and_preserves_legacy_controls(self):
        self.assertEqual(4, len(re.findall(r'data-import-step="[1-4]"', self.html)))
        self.assertEqual(4, len(re.findall(r'data-import-progress="[1-4]"', self.html)))
        for section in ("import", "calculator", "visibility", "history"):
            self.assertIn(f'data-workspace-section="{section}"', self.html)
        for legacy_control in ("btn-pick-dwg", "btn-pick-json", "unit-scale", "wall-layers", "btn-load"):
            self.assertEqual(1, len(re.findall(fr'id="{legacy_control}"', self.html)))
        self.assertIn("openWorkspaceSection", self.javascript)
        self.assertIn("setImportStep", self.javascript)

    def test_visibility_and_diagnostic_docks_are_interactive(self):
        for control in ("btn-visibility-popover", "visibility-popover", "quick-display-mode"):
            self.assertIn(f'id="{control}"', self.html)
        for tab in ("problems", "element", "performance", "history", "log", "dependencies", "commands"):
            self.assertIn(f'data-diagnostic-tab="{tab}"', self.html)
        for feature in ("filterDiagnosticProblems", "rebuildDiagnosticDock", "data-diagnostic-action", "diagnosticSuggestion"):
            self.assertIn(feature, self.javascript)

    def test_shortcuts_and_multiple_selection_match_the_bim_workflow(self):
        for shortcut in ("s:", "o:", "p:", "z:", "f:", "m:", "r:", "c:", "i:", "h:"):
            self.assertIn(shortcut, self.javascript)
        self.assertIn("i: isolateSelected", self.javascript)
        self.assertIn("h: hideSelected", self.javascript)
        for feature in ("multiSelectionGroup", "handleSelectionChanged", "renderMultiSelectionPanel", "event.ctrlKey || event.metaKey"):
            self.assertIn(feature, self.javascript)
        self.assertIn("event.key === 'Delete'", self.javascript)

    def test_incremental_scene_and_performance_instrumentation_are_visible(self):
        self.assertIn('id="status-performance"', self.html)
        self.assertIn('id="diagnostics-performance"', self.html)
        for feature in (
            "incremental_patch", "mergeAffectedItems", "scene_update",
            "editor:drag-state", "beginFpsMeasurement", "geometry_hash",
        ):
            self.assertIn(feature, self.html + self.javascript + self.server)

    def test_reviewed_geometry_proposals_are_available_without_silent_apply(self):
        for control in (
            "btn-proposals", "btn-generate-proposals", "btn-generate-project-proposals",
            "btn-discard-proposal", "diagnostics-proposals",
        ):
            self.assertIn(f'id="{control}"', self.html)
        for feature in (
            "/api/proposals", "/api/preview-proposal", "/api/apply-proposal",
            "generateProposals", "previewProposal", "applyProposal", "discardProposalPreview",
            "requires_manual_review", "proposal-card",
        ):
            self.assertIn(feature, self.html + self.css + self.javascript + self.server)

    def test_section_can_invert_its_visible_side(self):
        self.assertIn('id="section-invert"', self.html)
        self.assertIn("sectionInverted", self.javascript)
        self.assertIn("normal.negate()", self.javascript)
        self.assertIn("pushSectionHistory(before, sectionSnapshot())", self.javascript)

    def test_camera_extents_include_model_height(self):
        self.assertIn(
            "Math.max(maxX - minX, maxY - minY, maxHeight, 200)",
            self.inline_javascript,
        )
        self.assertIn("camera.lookAt(controls.target)", self.inline_javascript)

    def test_revit_launch_rejects_stale_servers_and_browser_assets(self):
        for feature in (
            "_viewer_build_id",
            "_versioned_viewer_index",
            'parsed.path == "/api/health"',
            "no-store, no-cache, must-revalidate",
        ):
            self.assertIn(feature, self.server)
        for feature in (
            "_visualizer_build_id",
            "_server_build_for_port",
            "_compatible_server_port",
            "&build={}",
        ):
            self.assertIn(feature, self.launcher)


if __name__ == "__main__":
    unittest.main()
