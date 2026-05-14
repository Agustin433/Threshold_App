from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from modules.force_time_analysis import (
    get_asymmetry_summary,
    get_force_time_points,
    get_rfd_points,
    interpret_hamstring_force_time,
    interpret_imtp_force_time,
    summarize_force_time_test,
)

ANALYSIS_PATH = Path(__file__).resolve().parents[1] / "modules" / "force_time_analysis.py"
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "pages" / "02_jump_evaluation.py"
REPORT_PATH = Path(__file__).resolve().parents[1] / "modules" / "report_force_time.py"


def _storage_row(**overrides) -> dict[str, object]:
    base = {
        "IMTP_N": 3385,
        "IMTP_avg_N": 2993,
        "IMTP_force_L_N": 1731,
        "IMTP_force_R_N": 1653,
        "IMTP_asym_pct": 4.5,
        "IMTP_pretension": 1109,
        "IMTP_time_max_s": 2.63,
        "IMTP_time_pull_s": 3.0,
        "IMTP_force_50_N": 1172,
        "IMTP_force_100_N": 1364,
        "IMTP_force_150_N": 1620,
        "IMTP_force_200_N": 1957,
        "IMTP_force_250_N": 2232,
        "IMTP_rfd_50_N_s": 1260,
        "IMTP_rfd_100_N_s": 2558,
        "IMTP_rfd_150_N_s": 3411,
        "IMTP_rfd_250_N_s": 4493,
    }
    base.update(overrides)
    return base


def _normalized_metrics(**overrides) -> dict[str, object]:
    metrics = {
        "force_max_n": 3385,
        "force_avg_n": 2993,
        "force_left_max_n": 1731,
        "force_right_max_n": 1653,
        "asymmetry_pct": 4.5,
        "pre_tension_n": 1109,
        "time_to_peak_s": 2.63,
        "time_pull_s": 3.0,
        "force_50_n": 1172,
        "force_100_n": 1364,
        "force_150_n": 1620,
        "force_200_n": 1957,
        "force_250_n": 2232,
        "rfd_50_n_s": 1260,
        "rfd_100_n_s": 2558,
        "rfd_150_n_s": 3411,
        "rfd_250_n_s": 4493,
    }
    metrics.update(overrides)
    return metrics


def _hamstring_storage_row(**overrides) -> dict[str, object]:
    base = {
        "ISO_HAM_N": 1280,
        "ISO_HAM_avg_N": 1115,
        "ISO_HAM_force_L_N": 670,
        "ISO_HAM_force_R_N": 610,
        "ISO_HAM_asym_pct": 9.4,
        "ISO_HAM_pretension": 180,
        "ISO_HAM_time_max_s": 1.84,
        "ISO_HAM_time_pull_s": 2.20,
        "ISO_HAM_force_50_N": 290,
        "ISO_HAM_force_100_N": 455,
        "ISO_HAM_force_150_N": 620,
        "ISO_HAM_force_200_N": 785,
        "ISO_HAM_force_250_N": 930,
        "ISO_HAM_rfd_50_N_s": 1280,
        "ISO_HAM_rfd_100_N_s": 2240,
        "ISO_HAM_rfd_150_N_s": 2960,
        "ISO_HAM_rfd_250_N_s": 3720,
    }
    base.update(overrides)
    return base


class ForceTimeAnalysisTest(unittest.TestCase):
    def test_summarize_force_time_test_reads_flat_imtp_storage_fields(self):
        summary = summarize_force_time_test(_storage_row())

        self.assertEqual(summary["peak_force_n"], 3385)
        self.assertEqual(summary["avg_force_n"], 2993)
        self.assertEqual(summary["force_100_n"], 1364)
        self.assertEqual(summary["rfd_100_n_s"], 2558)
        self.assertNotIn("rfd_200_n_s", summary)

    def test_summarize_force_time_test_reads_normalized_metrics_nested_and_direct(self):
        nested_summary = summarize_force_time_test({"metrics": _normalized_metrics(), "test_id": "imtp"})
        direct_summary = summarize_force_time_test(_normalized_metrics(), test_id="imtp")

        for summary in (nested_summary, direct_summary):
            with self.subTest(summary=summary):
                self.assertEqual(summary["peak_force_n"], 3385)
                self.assertEqual(summary["force_100_n"], 1364)
                self.assertEqual(summary["rfd_100_n_s"], 2558)
                self.assertEqual(summary["display_name"], "IMTP")

    def test_summarize_force_time_test_reads_iso_push_hamstring_storage_fields(self):
        summary = summarize_force_time_test(_hamstring_storage_row(), test_id="iso_push_hamstring")

        self.assertEqual(summary["display_name"], "ISO Push Hip-Hamstring Bilateral")
        self.assertEqual(summary["peak_force_n"], 1280)
        self.assertEqual(summary["avg_force_n"], 1115)
        self.assertEqual(summary["force_100_n"], 455)
        self.assertEqual(summary["rfd_100_n_s"], 2240)
        self.assertEqual(summary["stronger_side"], "left")
        self.assertEqual(summary["weaker_side"], "right")
        self.assertEqual(summary["side_difference_n"], 60)
        self.assertAlmostEqual(summary["force_100_pct_peak"], 455 / 1280 * 100, places=4)
        self.assertAlmostEqual(summary["force_200_pct_peak"], 785 / 1280 * 100, places=4)
        self.assertAlmostEqual(summary["force_250_pct_peak"], 930 / 1280 * 100, places=4)
        self.assertNotIn("rfd_200_n_s", summary)

    def test_summarize_force_time_test_uses_legacy_rfd_aliases_only_as_fallback(self):
        legacy_fallback = summarize_force_time_test(
            _storage_row(
                IMTP_rfd_50_N_s=None,
                IMTP_rfd_100_N_s=None,
                IMTP_rfd_150_N_s=None,
                IMTP_rfd_250_N_s=None,
                RFD_50=1200,
                RFD_100=2400,
                RFD_150=3200,
                RFD_250=4100,
            )
        )
        canonical_priority = summarize_force_time_test(
            _storage_row(
                IMTP_rfd_100_N_s=2558,
                RFD_100=2400,
            )
        )

        self.assertEqual(legacy_fallback["rfd_50_n_s"], 1200)
        self.assertEqual(legacy_fallback["rfd_100_n_s"], 2400)
        self.assertEqual(legacy_fallback["rfd_150_n_s"], 3200)
        self.assertEqual(legacy_fallback["rfd_250_n_s"], 4100)
        self.assertEqual(canonical_priority["rfd_100_n_s"], 2558)
        self.assertNotIn("rfd_200_n_s", legacy_fallback)

    def test_asymmetry_direction_prefers_left_when_left_is_higher(self):
        summary = summarize_force_time_test(_storage_row())

        self.assertEqual(summary["stronger_side"], "left")
        self.assertEqual(summary["weaker_side"], "right")
        self.assertEqual(summary["side_difference_n"], 78)

    def test_equal_sides_clear_direction_and_keep_zero_difference(self):
        summary = summarize_force_time_test(
            _storage_row(
                IMTP_force_L_N=1000,
                IMTP_force_R_N=1000,
                IMTP_asym_pct=0,
            )
        )

        self.assertEqual(summary["side_difference_n"], 0)
        self.assertIsNone(summary["stronger_side"])
        self.assertIsNone(summary["weaker_side"])

    def test_missing_side_values_clear_directional_summary(self):
        summary = summarize_force_time_test(
            _storage_row(
                IMTP_force_L_N=None,
                IMTP_force_R_N=1653,
                IMTP_asym_pct=None,
            )
        )

        self.assertIsNone(summary["stronger_side"])
        self.assertIsNone(summary["weaker_side"])
        self.assertIsNone(summary["side_difference_n"])
        self.assertFalse(summary["has_valid_asymmetry"])

    def test_percentage_of_peak_uses_peak_force_safely(self):
        summary = summarize_force_time_test(_storage_row())

        self.assertAlmostEqual(summary["force_100_pct_peak"], 1364 / 3385 * 100, places=4)
        self.assertAlmostEqual(summary["force_200_pct_peak"], 1957 / 3385 * 100, places=4)
        self.assertAlmostEqual(summary["force_250_pct_peak"], 2232 / 3385 * 100, places=4)

    def test_missing_or_zero_peak_returns_none_for_percentage_fields(self):
        missing_peak = summarize_force_time_test(_storage_row(IMTP_N=None))
        zero_peak = summarize_force_time_test(_storage_row(IMTP_N=0))

        for summary in (missing_peak, zero_peak):
            with self.subTest(summary=summary):
                self.assertIsNone(summary["force_100_pct_peak"])
                self.assertIsNone(summary["force_200_pct_peak"])
                self.assertIsNone(summary["force_250_pct_peak"])

    def test_get_force_time_points_returns_exact_export_order(self):
        summary = summarize_force_time_test(_storage_row())

        points = get_force_time_points(summary)

        self.assertEqual(
            [(point["label"], point["time_ms"]) for point in points],
            [("50 ms", 50), ("100 ms", 100), ("150 ms", 150), ("200 ms", 200), ("250 ms", 250), ("Peak", None)],
        )

    def test_get_rfd_points_returns_exact_export_order_without_rfd_200(self):
        summary = summarize_force_time_test(_storage_row())

        points = get_rfd_points(summary)

        self.assertEqual(
            [(point["label"], point["time_ms"]) for point in points],
            [("RFD 50", 50), ("RFD 100", 100), ("RFD 150", 150), ("RFD 250", 250)],
        )
        self.assertTrue(all(point["time_ms"] != 200 for point in points))

    def test_missing_rfd_values_remain_missing_without_creating_fake_points(self):
        summary = summarize_force_time_test(
            _storage_row(
                IMTP_rfd_50_N_s=None,
                IMTP_rfd_100_N_s=None,
                IMTP_rfd_150_N_s=3411,
                IMTP_rfd_250_N_s=None,
            )
        )
        values_by_label = {point["label"]: point["value_n_s"] for point in get_rfd_points(summary)}

        self.assertIsNone(values_by_label["RFD 50"])
        self.assertIsNone(values_by_label["RFD 100"])
        self.assertEqual(values_by_label["RFD 150"], 3411)
        self.assertIsNone(values_by_label["RFD 250"])
        self.assertEqual(set(values_by_label), {"RFD 50", "RFD 100", "RFD 150", "RFD 250"})

    def test_get_asymmetry_summary_changes_interpretation_by_band(self):
        missing = get_asymmetry_summary({"left_force_n": None, "right_force_n": None, "absolute_asymmetry_pct": None})
        low = get_asymmetry_summary({"left_force_n": 1000, "right_force_n": 950, "absolute_asymmetry_pct": 4.9})
        moderate = get_asymmetry_summary({"left_force_n": 1000, "right_force_n": 870, "absolute_asymmetry_pct": 12.0})
        relevant = get_asymmetry_summary({"left_force_n": 1000, "right_force_n": 760, "absolute_asymmetry_pct": 24.0})

        self.assertEqual(missing["interpretation"], "Sin datos suficientes para interpretar asimetria.")
        self.assertEqual(low["interpretation"], "Diferencia lateral baja/contextual.")
        self.assertEqual(moderate["interpretation"], "Diferencia lateral moderada. Revisar tendencia y contexto.")
        self.assertEqual(
            relevant["interpretation"],
            "Diferencia lateral relevante. Revisar junto con dolor, historial, fatiga y carga reciente.",
        )

    def test_interpret_imtp_force_time_is_descriptive_and_cautious(self):
        summary = summarize_force_time_test(pd.Series(_storage_row()))

        interpretation = interpret_imtp_force_time(summary)
        combined = " ".join(str(value) for value in interpretation.values()).lower()

        self.assertIn("rfd", combined)
        self.assertIn("cautela", combined)
        self.assertNotIn("rojo", combined)
        self.assertNotIn("verde", combined)
        self.assertNotIn("raw curve", combined)
        self.assertNotIn("curva cruda", combined)
        self.assertNotIn("iso push", combined)
        self.assertEqual(interpretation["basis"], "valid")

    def test_interpret_hamstring_force_time_is_contextual_and_non_diagnostic(self):
        summary = summarize_force_time_test(pd.Series(_hamstring_storage_row()), test_id="iso_push_hamstring")

        interpretation = interpret_hamstring_force_time(summary)
        combined = " ".join(str(value) for value in interpretation.values()).lower()

        self.assertEqual(interpretation["basis"], "valid")
        self.assertIn("cadena posterior", combined)
        self.assertIn("flexores de rodilla", combined)
        self.assertIn("rfd", combined)
        self.assertIn("cautela", combined)
        self.assertIn("contextual", combined)
        self.assertNotIn("riesgo de lesi", combined)
        self.assertNotIn("lesion probable", combined)
        self.assertNotIn("diagn", combined)
        self.assertNotIn("raw curve", combined)
        self.assertNotIn("curva cruda", combined)

    def test_force_time_product_copy_stays_safe_across_analysis_dashboard_and_report_helpers(self):
        combined = " ".join(
            path.read_text(encoding="utf-8").lower()
            for path in (ANALYSIS_PATH, DASHBOARD_PATH, REPORT_PATH)
        )

        self.assertIn("perfil force-time por puntos", combined)
        self.assertIn("valores exportados", combined)
        self.assertIn("cautela", combined)
        self.assertIn("contextual", combined)
        self.assertIn("no tomar decisiones fuertes", combined)
        for forbidden_phrase in (
            "curva cruda",
            "raw curve",
            "riesgo de lesión alto",
            "riesgo de lesion alto",
            "lesión probable",
            "lesion probable",
            "diagnóstico",
            "diagnostico",
            "rfd 200",
            "imtp_rfd_200_n_s",
        ):
            with self.subTest(forbidden_phrase=forbidden_phrase):
                self.assertNotIn(forbidden_phrase, combined)


if __name__ == "__main__":
    unittest.main()
