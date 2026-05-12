from __future__ import annotations

import unittest
from pathlib import Path

from charts.dashboard_charts import (
    make_force_time_points_chart,
    make_left_right_force_chart,
    make_rfd_points_chart,
)
from modules.force_time_analysis import (
    get_asymmetry_summary,
    get_force_time_points,
    get_rfd_points,
    summarize_force_time_test,
)
from modules.page_visuals import build_page_theme


PAGE_PATH = Path(__file__).resolve().parents[1] / "pages" / "02_jump_evaluation.py"


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
        "IMTP_force_100_N": 1364,
        "IMTP_force_200_N": 1957,
        "IMTP_force_250_N": 2232,
        "IMTP_rfd_100_N_s": 2558,
    }
    base.update(overrides)
    return base


class ForceTimeDashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.theme = build_page_theme()

    def test_dashboard_summary_stays_safe_without_imtp_force_time_fields(self):
        summary = summarize_force_time_test({"Athlete": "Test Athlete"})

        self.assertFalse(summary["has_valid_force_time"])
        self.assertEqual(summary["basis"], "missing")
        self.assertIsNone(make_left_right_force_chart(get_asymmetry_summary(summary), theme=self.theme))
        self.assertIsNone(make_force_time_points_chart(get_force_time_points(summary), theme=self.theme))
        self.assertIsNone(make_rfd_points_chart(get_rfd_points(summary), theme=self.theme))

    def test_dashboard_detects_valid_imtp_force_time_data(self):
        summary = summarize_force_time_test(_storage_row())

        self.assertTrue(summary["has_valid_force_time"])
        self.assertEqual(summary["peak_force_n"], 3385)
        self.assertEqual(summary["force_100_n"], 1364)
        self.assertEqual(summary["force_200_n"], 1957)
        self.assertEqual(summary["force_250_n"], 2232)
        self.assertEqual(summary["rfd_100_n_s"], 2558)
        self.assertEqual(summary["left_force_n"], 1731)
        self.assertEqual(summary["right_force_n"], 1653)
        self.assertEqual(summary["absolute_asymmetry_pct"], 4.5)

    def test_left_right_chart_tolerates_missing_side_data(self):
        partial_chart = make_left_right_force_chart(
            {"left_force_n": 1731, "right_force_n": None},
            theme=self.theme,
        )

        self.assertIsNotNone(partial_chart)
        self.assertEqual(list(partial_chart.data[0].x), ["Izquierda"])

    def test_force_time_chart_tolerates_partial_points(self):
        summary = summarize_force_time_test(_storage_row(IMTP_force_200_N=None, IMTP_force_250_N=None))

        figure = make_force_time_points_chart(get_force_time_points(summary), theme=self.theme)

        self.assertIsNotNone(figure)
        self.assertEqual(list(figure.data[0].x), ["50 ms", "100 ms", "150 ms", "200 ms", "250 ms", "Peak"])

    def test_rfd_chart_tolerates_partial_values_and_never_adds_rfd_200(self):
        summary = summarize_force_time_test(_storage_row(IMTP_rfd_100_N_s=None, IMTP_rfd_150_N_s=3411))

        figure = make_rfd_points_chart(get_rfd_points(summary), theme=self.theme)

        self.assertIsNotNone(figure)
        self.assertEqual(list(figure.data[0].x), ["RFD 50", "RFD 100", "RFD 150", "RFD 250"])
        labels = [point["label"] for point in get_rfd_points(summary)]
        self.assertEqual(labels, ["RFD 50", "RFD 100", "RFD 150", "RFD 250"])
        self.assertNotIn("RFD 200", labels)

    def test_dashboard_copy_avoids_banned_force_time_language(self):
        source = PAGE_PATH.read_text(encoding="utf-8").lower()

        self.assertIn("detalle force-time imtp", source)
        self.assertIn("perfil por puntos derivado del resumen exportado", source)
        self.assertNotIn("curva cruda", source)
        self.assertNotIn("raw curve", source)
        self.assertNotIn("riesgo de lesion alto", source)
        self.assertNotIn("diagnostico", source)


if __name__ == "__main__":
    unittest.main()
