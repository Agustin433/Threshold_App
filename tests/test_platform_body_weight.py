"""Reglas 6 y 7: peso de plataforma invalido y peso de una evaluacion cercana.

Casos reales de `evaluations` (Supabase, noviembre 2026):
- Santiago Gray 07/05: Involution exporto bw_kg = 0, impulso relativo del CMJ
  -0.20, CMJ exportado 43.43 cm contra 50.1 cm por tiempo de vuelo (639 ms).
- Nicolas Lorenzo 28/09: bw_kg = 0, impulso relativo -0.18, CMJ 48.05 cm
  contra 42.1 cm por tiempo de vuelo (586 ms).
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules.evaluation_rules import (
    BW_IMPUTED_COLUMN,
    BW_IMPUTED_FROM_COLUMN,
    PLATFORM_BW_FLAG_COLUMN,
    assess_platform_body_weight,
    imputed_body_weight_label,
    platform_body_weight_upload_warning,
)
from modules.jump_analysis import _prepare_jump_df, build_jump_flag_rows


def _gray_row(**overrides):
    row = {
        "Athlete": "Santiago Gray",
        "Date": "2026-05-07",
        "Source": "platform",
        "BW_kg": 0.0,
        "CMJ_cm": 43.43,
        "CMJ_flight_ms": 639.0,
        "CMJ_takeoff_velocity_m_s": 2.92,
        "CMJ_peak_power_W": 4659.0,
        "CMJ_rel_impulse": -0.2,
        "CMJ_contraction_ms": 636.0,
        "CMJ_propulsive_PF_N": 1962.0,
        "CMJ_asym_pct": -2.927,
        "SJ_cm": 41.0,
        "SJ_flight_ms": 575.0,
        "SJ_peak_power_W": 4300.0,
        "DJ_cm": 35.0,
        "DJ_tc_ms": 164.0,
        "DJ_drop_height_cm": 30.0,
        "IMTP_N": 2705.0,
    }
    row.update(overrides)
    return row


class PlatformBodyWeightRuleTests(unittest.TestCase):
    def test_zero_weight_flags_cmj_and_sj(self):
        result = assess_platform_body_weight(_gray_row())
        self.assertEqual(result["tests"], ["CMJ", "SJ"])
        self.assertIn("Involution exportó peso corporal 0 kg", result["detail"])
        self.assertIn("CMJ exportado 43.4 cm", result["detail"])
        self.assertIn("por tiempo de vuelo 50.1 cm", result["detail"])

    def test_negative_impulse_flags_even_with_valid_weight(self):
        result = assess_platform_body_weight(_gray_row(BW_kg=60.0))
        self.assertEqual(result["tests"], ["CMJ"])
        self.assertIn("impulso relativo del CMJ negativo", result["detail"])

    def test_valid_weight_and_positive_impulse_is_clean(self):
        result = assess_platform_body_weight(_gray_row(BW_kg=60.0, CMJ_rel_impulse=0.49))
        self.assertEqual(result["tests"], [])
        self.assertIsNone(result["detail"])

    def test_manual_platform_entry_without_kinetics_is_not_flagged(self):
        row = {"Athlete": "X", "Date": "2026-05-07", "Source": "platform", "CMJ_cm": 40.0}
        self.assertEqual(assess_platform_body_weight(row)["tests"], [])

    def test_nonplatform_source_is_never_flagged(self):
        row = _gray_row(Source="nonplatform")
        self.assertEqual(assess_platform_body_weight(row)["tests"], [])

    def test_prepared_frame_discards_weight_dependent_metrics_only(self):
        prepared = _prepare_jump_df(pd.DataFrame([_gray_row()]))
        row = prepared.iloc[0]
        self.assertEqual(row[PLATFORM_BW_FLAG_COLUMN], "CMJ,SJ")
        for column in ("CMJ_cm", "CMJ_takeoff_velocity_m_s", "CMJ_peak_power_W", "CMJ_rel_impulse",
                       "CMJ_contraction_ms", "SJ_cm", "SJ_peak_power_W", "EUR", "Jump_Momentum"):
            if column in prepared.columns:
                self.assertTrue(pd.isna(row[column]), column)
        # No dependen del peso: se conservan.
        self.assertAlmostEqual(row["CMJ_flight_ms"], 639.0)
        self.assertAlmostEqual(row["CMJ_propulsive_PF_N"], 1962.0)
        self.assertAlmostEqual(row["CMJ_asym_pct"], -2.927)
        self.assertAlmostEqual(row["DJ_cm"], 35.0)
        self.assertAlmostEqual(row["IMTP_N"], 2705.0)

    def test_flag_survives_re_prepare_and_null_weight_after_migration(self):
        once = _prepare_jump_df(pd.DataFrame([_gray_row()]))
        twice = _prepare_jump_df(once)
        self.assertEqual(twice.iloc[0][PLATFORM_BW_FLAG_COLUMN], "CMJ,SJ")
        migrated = _prepare_jump_df(pd.DataFrame([_gray_row(BW_kg=None)]))
        self.assertEqual(migrated.iloc[0][PLATFORM_BW_FLAG_COLUMN], "CMJ,SJ")
        self.assertTrue(pd.isna(migrated.iloc[0]["CMJ_cm"]))

    def test_flag_row_is_red_and_names_involution(self):
        prepared = _prepare_jump_df(pd.DataFrame([_gray_row()]))
        texts = [flag for flag in build_jump_flag_rows(prepared.iloc[0]) if "Peso de plataforma" in flag["text"]]
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0]["level"], "red")
        self.assertIn("Involution", texts[0]["text"])

    def test_upload_warning_only_for_cmj_sj(self):
        self.assertIsNotNone(platform_body_weight_upload_warning(_gray_row(), test_type="CMJ", source="platform"))
        self.assertIsNone(platform_body_weight_upload_warning(_gray_row(), test_type="IMTP", source="platform"))
        self.assertIsNone(platform_body_weight_upload_warning(_gray_row(), test_type="CMJ", source="nonplatform"))


class NearbyBodyWeightTests(unittest.TestCase):
    def _frame(self, gap_days: int):
        measured_date = pd.Timestamp("2026-05-07") - pd.Timedelta(days=gap_days)
        return pd.DataFrame([
            {"Athlete": "Ana", "Date": measured_date, "Source": "platform", "BW_kg": 60.0, "CMJ_cm": 30.0},
            {"Athlete": "Ana", "Date": "2026-05-07", "Source": "platform", "BW_kg": 0.0, "IMTP_N": 1800.0},
            {"Athlete": "Otra", "Date": "2026-05-07", "Source": "platform", "BW_kg": 70.0, "IMTP_N": 2000.0},
        ])

    def test_uses_weight_within_14_days_for_app_relatives(self):
        prepared = _prepare_jump_df(self._frame(10))
        row = prepared[(prepared["Athlete"] == "Ana") & (prepared["Date"] == "2026-05-07")].iloc[0]
        self.assertTrue(pd.isna(row["BW_kg"]))  # el peso medido sigue vacio
        self.assertAlmostEqual(row[BW_IMPUTED_COLUMN], 60.0)
        self.assertEqual(row[BW_IMPUTED_FROM_COLUMN], "27/04/2026")
        self.assertAlmostEqual(row["IMTP_relPF"], 30.0)
        self.assertIn("27/04/2026", imputed_body_weight_label(row))
        levels = [f["level"] for f in build_jump_flag_rows(row) if "Peso tomado" in f["text"]]
        self.assertEqual(levels, ["yellow"])

    def test_no_weight_beyond_14_days_or_from_other_athletes(self):
        prepared = _prepare_jump_df(self._frame(20))
        row = prepared[(prepared["Athlete"] == "Ana") & (prepared["Date"] == "2026-05-07")].iloc[0]
        self.assertTrue(pd.isna(row[BW_IMPUTED_COLUMN]))
        self.assertTrue(pd.isna(row["IMTP_relPF"]))

    def test_imputed_weight_never_persisted(self):
        from modules.data_loader import EVALUATION_PERSIST_COLUMNS

        self.assertNotIn(BW_IMPUTED_COLUMN, EVALUATION_PERSIST_COLUMNS)
        self.assertNotIn(BW_IMPUTED_FROM_COLUMN, EVALUATION_PERSIST_COLUMNS)

    def test_imputed_weight_does_not_rescue_platform_cmj(self):
        frame = pd.DataFrame([
            {"Athlete": "Santiago Gray", "Date": "2026-05-01", "Source": "platform", "BW_kg": 60.0},
            _gray_row(),
        ])
        prepared = _prepare_jump_df(frame)
        row = prepared[prepared["Date"] == "2026-05-07"].iloc[0]
        self.assertAlmostEqual(row[BW_IMPUTED_COLUMN], 60.0)
        self.assertTrue(pd.isna(row["CMJ_cm"]))
        self.assertTrue(pd.isna(row["Jump_Momentum"]) if "Jump_Momentum" in prepared.columns else True)
        self.assertAlmostEqual(row["IMTP_relPF"], round(2705.0 / 60.0, 2))


if __name__ == "__main__":
    unittest.main()
