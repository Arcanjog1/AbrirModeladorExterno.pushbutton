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

    def test_html_ids_are_unique(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        duplicates = sorted(item for item in set(ids) if ids.count(item) > 1)
        self.assertEqual([], duplicates)

    def test_compact_bim_shell_has_the_primary_surfaces(self):
        required_ids = {
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
        for token in ("#202124", "#292a2d", "#303134", ':root[data-theme="light"]'):
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


if __name__ == "__main__":
    unittest.main()
