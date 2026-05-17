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

        self.assertIn("report_requires_individual(report_audience)", report)
        self.assertIn("resolve_report_scope(", report)
        self.assertIn("effective_report_athlete", report)
        self.assertIn("include_technical_annex=include_technical_annex", report)
        self.assertIn('st.button("Actualizar preview", disabled=effective_report_athlete is None)', report)
        self.assertIn('st.button("Preparar exportables", disabled=effective_report_athlete is None)', report)

        preview_button_idx = report.index('st.button("Actualizar preview", disabled=effective_report_athlete is None)')
        preview_build_idx = report.index("build_report_executive_sheet(")
        preview_insights_idx = report.index("generate_module_insights(")
        export_button_idx = report.index('st.button("Preparar exportables", disabled=effective_report_athlete is None)')
        pdf_idx = report.index("generate_visual_report_pdf(")

        self.assertLess(preview_button_idx, preview_build_idx)
        self.assertLess(preview_button_idx, preview_insights_idx)
        self.assertLess(export_button_idx, pdf_idx)

    def test_main_report_tab_shows_lazy_preview_status_messages(self):
        report = _report_block()

        self.assertIn("La vista previa todavía no se generó", report)
        self.assertIn("Vista previa actualizada", report)
        self.assertIn("quedó desactualizada", report)
        self.assertIn("PDF generado y exportables listos para descargar", report)

    def test_main_report_tab_no_longer_uses_legacy_summary_directly(self):
        report = _report_block()

        self.assertNotIn("build_executive_summary_df(", report)


if __name__ == "__main__":
    unittest.main()
