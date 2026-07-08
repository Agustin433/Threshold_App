from __future__ import annotations

import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppNeuromuscularStaticTest(unittest.TestCase):
    def test_app_declares_shared_neuromuscular_source_of_truth(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("neuromuscular logic lives in modules.jump_analysis", source.lower())
        self.assertIn("charts.dashboard_charts", source)

    def test_app_uses_shared_neuromuscular_wrappers(self):
        source = APP_PATH.read_text(encoding="utf-8")

        for fragment in (
            "return shared_calc_eur(df)",
            "return shared_calc_dri(df)",
            "return shared_calc_zscores(df)",
            "return shared_calc_nm_profile(df)",
            "return shared_prepare_jump_df(jump_df)",
            "return shared_records_to_jump_df(records)",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_legacy_neuromuscular_chart_definitions_are_isolated(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("def _legacy_chart_radar_unused", source)
        self.assertIn("def _legacy_chart_quadrant_cmj_imtp_unused", source)
        self.assertIn("def _legacy_chart_quadrant_dri_sj_unused", source)
        self.assertIn("chart_radar = _bind_chart(shared_chart_radar)", source)
        self.assertIn("chart_quadrant_cmj_imtp = _bind_chart(shared_chart_quadrant_cmj_imtp)", source)
        self.assertIn("chart_quadrant_dri_sj = _bind_chart(shared_chart_quadrant_dri_sj)", source)
        self.assertIn("chart_quadrant_rsi_sj = _bind_chart(shared_chart_quadrant_rsi_sj)", source)

    def test_app_prefers_shared_alias_resolution_and_eur_profile_fallbacks(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn('resolve_zscore as shared_resolve_zscore', source)
        self.assertIn('shared_resolve_zscore(row, canonical_field)', source)
        self.assertIn('last_row.get("EUR_Profile") or last_row.get("NM_Profile"', source)

    def test_app_requires_drop_height_for_new_dj_uploads(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn('key="eval_dj_drop_height_choice"', source)
        self.assertIn('key="eval_dj_drop_height_custom"', source)
        self.assertIn('record["DJ_drop_height_cm"] = manual_dj_drop_height_cm', source)
        self.assertIn("la evaluaci", source)
        self.assertIn("altura de ca", source)

    def test_app_exposes_explicit_dj_history_backfill_controls(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("Mantenimiento DRI historico", source)
        self.assertIn("Aplicar backfill DJ historico (30 cm)", source)
        self.assertIn('key="btn_backfill_dj_drop_height"', source)
        self.assertIn("build_dj_drop_height_backfill_candidates", source)


if __name__ == "__main__":
    unittest.main()
