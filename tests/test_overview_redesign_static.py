from __future__ import annotations

import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _overview_block() -> str:
    source = APP_PATH.read_text(encoding="utf-8")
    start = source.index("# TAB: OVERVIEW")
    end = source.index("# TAB: LOAD MONITORING")
    return source[start:end]


class OverviewRedesignStaticTest(unittest.TestCase):
    def test_overview_is_executive_triage_landing(self):
        overview = _overview_block()

        self.assertIn("Overview Ejecutivo", overview)
        self.assertIn("Readiness de fuentes", overview)
        self.assertIn("Señales ejecutivas", overview)
        self.assertIn("Lectura integrada", overview)
        self.assertIn("Adonde ir despues", overview)

        for target in ["Panel de Decision", "Load Monitoring", "Calidad de datos", "Evaluaciones"]:
            self.assertIn(target, overview)

    def test_overview_uses_modern_summary_layers(self):
        overview = _overview_block()

        self.assertIn("_active_dataset_rows()", overview)
        self.assertIn("compute_data_quality_report(", overview)
        self.assertIn("build_weekly_summaries(", overview)
        self.assertIn("_overview_completion_snapshot(cdf)", overview)

    def test_overview_drops_legacy_duplicate_blocks(self):
        overview = _overview_block()

        legacy_fragments = [
            "Resumen rapido",
            "ultima sesion disponible por atleta",
            "Adherencia y volumen",
            "completion_sel_overview",
            "completion_overview",
            "chart_completion(",
            "Tonelaje total",
            "Reps/sesión promedio",
            'rldf["Load_kg"]',
            'rldf["Reps_Completed"]',
        ]
        for fragment in legacy_fragments:
            self.assertNotIn(fragment, overview)


if __name__ == "__main__":
    unittest.main()
