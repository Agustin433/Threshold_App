from __future__ import annotations

import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _function_block(name: str) -> str:
    source = APP_PATH.read_text(encoding="utf-8")
    marker = f"def {name}("
    start = source.index(marker)
    next_def = source.find("\ndef ", start + len(marker))
    if next_def == -1:
        return source[start:]
    return source[start:next_def]


class PerformanceDebugStaticTest(unittest.TestCase):
    def test_sidebar_contains_performance_debug_toggle_and_default_off(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn('st.toggle("Mostrar diagnóstico de rendimiento", key="performance_debug_enabled")', source)
        self.assertIn('if "performance_debug_enabled" not in st.session_state:', source)
        self.assertIn("st.session_state.performance_debug_enabled = False", source)

    def test_debug_panel_is_passive_and_does_not_trigger_heavy_reports(self):
        debug_panel = _function_block("_render_performance_debug_panel")

        self.assertNotIn("build_report_executive_sheet(", debug_panel)
        self.assertNotIn("generate_module_insights(", debug_panel)
        self.assertNotIn("generate_visual_report_pdf(", debug_panel)

    def test_debug_panel_reads_session_state_defensively(self):
        debug_panel = _function_block("_render_performance_debug_panel")

        self.assertIn('st.session_state.get("performance_debug_enabled", False)', debug_panel)
        self.assertIn('st.session_state.get("report_preview_signature")', debug_panel)
        self.assertIn('st.session_state.get("load_state_last_build_ts")', debug_panel)


if __name__ == "__main__":
    unittest.main()
