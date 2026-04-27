from __future__ import annotations

import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _report_block() -> str:
    source = APP_PATH.read_text(encoding="utf-8")
    start = source.index("# TAB: REPORTE DESCARGABLE")
    return source[start:]


class ReportTabStaticTest(unittest.TestCase):
    def test_main_report_tab_uses_modern_p10_scope_and_export_flow(self):
        report = _report_block()

        self.assertIn("build_report_executive_sheet(", report)
        self.assertIn("report_requires_individual(report_audience)", report)
        self.assertIn("resolve_report_scope(", report)
        self.assertIn("effective_report_athlete", report)
        self.assertIn("include_technical_annex=include_technical_annex", report)
        self.assertIn('st.button("Preparar exportables", disabled=effective_report_athlete is None)', report)

    def test_main_report_tab_no_longer_uses_legacy_summary_directly(self):
        report = _report_block()

        self.assertNotIn("build_executive_summary_df(", report)


if __name__ == "__main__":
    unittest.main()
