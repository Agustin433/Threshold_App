from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
LOAD_PAGE_PATH = ROOT / "pages" / "01_load_monitoring.py"
TEAM_PAGE_PATH = ROOT / "pages" / "04_team_dashboard.py"


class P2P9SemanticParityStaticTest(unittest.TestCase):
    def test_load_monitoring_page_consumes_weekly_summaries(self):
        source = LOAD_PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("build_weekly_summaries(", source)
        self.assertIn("weekly_load", source)
        self.assertIn("weekly_wellness", source)
        self.assertIn("weekly_external", source)
        self.assertIn("weekly_team", source)
        self.assertIn("chart_weekly_load", source)
        self.assertIn("chart_weekly_wellness", source)
        self.assertIn("chart_weekly_external", source)

    def test_overview_distinguishes_inventory_from_quality_readiness(self):
        source = APP_PATH.read_text(encoding="utf-8")
        overview = source[source.index("# TAB: OVERVIEW"):source.index("# TAB: LOAD MONITORING")]

        self.assertIn("Fuentes cargadas", overview)
        self.assertIn("inventario local; la calidad/readiness real viene del reporte P2", overview)
        self.assertIn("Calidad/readiness", overview)
        self.assertNotIn("Readiness de fuentes", overview)

    def test_decision_panel_does_not_label_raw_execution_as_completion(self):
        source = APP_PATH.read_text(encoding="utf-8")
        start = source.index("Ranking de ejecucion registrada")
        end = source.index("Evaluaciones pendientes", start)
        ranking_block = source[start:end]

        self.assertIn("Ejecucion registrada %", ranking_block)
        self.assertIn("execution_pct", ranking_block)
        self.assertNotIn("Completion %", ranking_block)
        self.assertNotIn("completion_pct", ranking_block)

    def test_team_dashboard_prefers_weekly_summary_model(self):
        source = TEAM_PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("build_weekly_summaries(", source)
        self.assertIn("weekly_load", source)
        self.assertIn("weekly_team", source)
        self.assertIn("Estado semanal de carga del equipo", source)

    def test_app_weekly_normalizer_is_available_to_all_tabs(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertLess(
            source.index("def _normalize_weekly_frame"),
            source.index("def render_decision_panel"),
        )


if __name__ == "__main__":
    unittest.main()
