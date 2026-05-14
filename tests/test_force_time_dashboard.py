from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from charts.dashboard_charts import (
    make_force_time_points_chart,
    make_left_right_force_chart,
    make_rfd_points_chart,
)
from modules.force_time_analysis import (
    get_asymmetry_summary,
    get_force_time_interpretation_lines,
    get_force_time_points,
    get_force_time_presence_report,
    get_rfd_points,
    interpret_hamstring_force_time,
    interpret_imtp_force_time,
    list_force_time_test_rows,
    select_basic_force_time_test_row,
    select_force_time_test_row,
    summarize_force_time_test,
)
from modules.page_visuals import build_page_theme


PAGE_PATH = Path(__file__).resolve().parents[1] / "pages" / "02_jump_evaluation.py"
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


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


def _hamstring_storage_row(**overrides) -> dict[str, object]:
    base = {
        "ISO_HAM_N": 1280,
        "ISO_HAM_avg_N": 1115,
        "ISO_HAM_force_L_N": 670,
        "ISO_HAM_force_R_N": 610,
        "ISO_HAM_asym_pct": 9.4,
        "ISO_HAM_pretension": 180,
        "ISO_HAM_time_max_s": 1.84,
        "ISO_HAM_time_pull_s": 2.2,
        "ISO_HAM_force_100_N": 455,
        "ISO_HAM_force_200_N": 785,
        "ISO_HAM_force_250_N": 930,
        "ISO_HAM_rfd_50_N_s": 1280,
        "ISO_HAM_rfd_100_N_s": 2240,
        "ISO_HAM_rfd_150_N_s": 2960,
        "ISO_HAM_rfd_250_N_s": 3720,
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

    def test_imtp_renders_without_iso_when_imtp_fields_exist(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-10",
                    "CMJ_cm": 35,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    **_storage_row(
                        IMTP_rfd_50_N_s=None,
                        IMTP_rfd_100_N_s=None,
                        IMTP_rfd_150_N_s=None,
                        IMTP_rfd_250_N_s=None,
                        IMTP_force_L_N=None,
                        IMTP_force_R_N=None,
                        IMTP_asym_pct=None,
                    ),
                }
            ]
        )

        imtp_row = select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10")
        iso_row = select_force_time_test_row(
            athlete_hist,
            test_id="iso_push_hamstring",
            selected_date="2026-04-10",
        )
        imtp_summary = summarize_force_time_test(imtp_row, test_id="imtp")

        self.assertIsNotNone(imtp_row)
        self.assertIsNone(iso_row)
        self.assertTrue(imtp_summary["has_valid_force_time"])
        self.assertFalse(imtp_summary["has_valid_rfd"])
        self.assertFalse(imtp_summary["has_valid_asymmetry"])

    def test_imtp_basic_row_without_force_time_points_stays_non_renderable_but_detectable(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-10",
                    "CMJ_cm": 35,
                    "SJ_cm": 31,
                    "IMTP_N": 3385,
                    "IMTP_avg_N": 2993,
                }
            ]
        )

        basic_row = select_basic_force_time_test_row(
            athlete_hist,
            test_id="imtp",
            selected_date="2026-04-10",
        )
        force_time_row = select_force_time_test_row(
            athlete_hist,
            test_id="imtp",
            selected_date="2026-04-10",
        )
        report = get_force_time_presence_report(basic_row, test_id="imtp")
        source = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIsNotNone(basic_row)
        self.assertIsNone(force_time_row)
        self.assertTrue(report["has_basic_data"])
        self.assertFalse(report["has_force_time_points"])
        self.assertFalse(report["has_valid_force_time"])
        self.assertIn("IMTP cargado, pero sin datos force-time suficientes para graficar el perfil por puntos.", source)
        self.assertIn("IMTP detectado, pero faltan los campos force-time por puntos.", source)

    def test_dashboard_stays_quiet_without_iso_push_hamstring_fields(self):
        summary = summarize_force_time_test(_storage_row(), test_id="iso_push_hamstring")
        source = PAGE_PATH.read_text(encoding="utf-8")

        self.assertFalse(summary["has_valid_force_time"])
        self.assertIn('if iso_ham_force_time_summary.get("has_valid_force_time")', source)

    def test_dashboard_detects_valid_iso_push_hamstring_data(self):
        summary = summarize_force_time_test(_hamstring_storage_row(), test_id="iso_push_hamstring")

        self.assertTrue(summary["has_valid_force_time"])
        self.assertEqual(summary["display_name"], "ISO Push Hip-Hamstring Bilateral")
        self.assertEqual(summary["peak_force_n"], 1280)
        self.assertEqual(summary["force_100_n"], 455)
        self.assertEqual(summary["force_200_n"], 785)
        self.assertEqual(summary["force_250_n"], 930)
        self.assertEqual(summary["rfd_100_n_s"], 2240)
        self.assertEqual(summary["left_force_n"], 670)
        self.assertEqual(summary["right_force_n"], 610)
        self.assertEqual(summary["absolute_asymmetry_pct"], 9.4)

    def test_dashboard_selection_finds_iso_row_even_when_primary_row_is_older(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-01",
                    "CMJ_cm": 36,
                    "SJ_cm": 32,
                    "DJ_cm": 28,
                    "DJ_tc_ms": 210,
                    "IMTP_N": 3100,
                    "BW_kg": 80,
                },
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-10",
                    **_hamstring_storage_row(),
                },
            ]
        )

        iso_row = select_force_time_test_row(
            athlete_hist,
            test_id="iso_push_hamstring",
            selected_date="2026-04-10",
        )
        summary = summarize_force_time_test(iso_row, test_id="iso_push_hamstring")

        self.assertIsNotNone(iso_row)
        self.assertEqual(pd.Timestamp(iso_row["Date"]).strftime("%Y-%m-%d"), "2026-04-10")
        self.assertTrue(summary["has_valid_force_time"])

    def test_dashboard_selection_skips_iso_block_when_no_iso_data_exists(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta Sin ISO",
                    "Date": "2026-04-01",
                    "CMJ_cm": 34,
                    "SJ_cm": 30,
                    "DJ_cm": 26,
                    "DJ_tc_ms": 220,
                    "IMTP_N": 2900,
                    "BW_kg": 79,
                }
            ]
        )

        iso_row = select_force_time_test_row(
            athlete_hist,
            test_id="iso_push_hamstring",
            selected_date="2026-04-01",
        )

        self.assertIsNone(iso_row)

    def test_iso_renders_without_imtp_when_iso_fields_exist(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-10",
                    "CMJ_cm": 36,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    "BW_kg": 80,
                    **_hamstring_storage_row(
                        ISO_HAM_rfd_50_N_s=None,
                        ISO_HAM_rfd_100_N_s=None,
                        ISO_HAM_rfd_150_N_s=None,
                        ISO_HAM_rfd_250_N_s=None,
                        ISO_HAM_force_L_N=None,
                        ISO_HAM_force_R_N=None,
                        ISO_HAM_asym_pct=None,
                    ),
                }
            ]
        )

        imtp_row = select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10")
        iso_row = select_force_time_test_row(
            athlete_hist,
            test_id="iso_push_hamstring",
            selected_date="2026-04-10",
        )
        iso_summary = summarize_force_time_test(iso_row, test_id="iso_push_hamstring")

        self.assertIsNone(imtp_row)
        self.assertIsNotNone(iso_row)
        self.assertTrue(iso_summary["has_valid_force_time"])
        self.assertFalse(iso_summary["has_valid_rfd"])
        self.assertFalse(iso_summary["has_valid_asymmetry"])

    def test_iso_block_guard_is_independent_from_imtp_guard(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-10",
                    "CMJ_cm": 36,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    **_hamstring_storage_row(),
                }
            ]
        )

        imtp_summary = summarize_force_time_test(
            select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10"),
            test_id="imtp",
        )
        iso_summary = summarize_force_time_test(
            select_force_time_test_row(athlete_hist, test_id="iso_push_hamstring", selected_date="2026-04-10"),
            test_id="iso_push_hamstring",
        )

        self.assertFalse(imtp_summary["has_valid_force_time"])
        self.assertTrue(iso_summary["has_valid_force_time"])

    def test_dashboard_selection_finds_imtp_row_even_when_primary_row_is_newer(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-01",
                    **_storage_row(),
                },
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-10",
                    "CMJ_cm": 37,
                    "SJ_cm": 33,
                    "DJ_cm": 29,
                    "DJ_tc_ms": 205,
                    "BW_kg": 80,
                },
            ]
        )

        imtp_row = select_force_time_test_row(
            athlete_hist,
            test_id="imtp",
            selected_date="2026-04-10",
        )
        summary = summarize_force_time_test(imtp_row, test_id="imtp")

        self.assertIsNotNone(imtp_row)
        self.assertEqual(pd.Timestamp(imtp_row["Date"]).strftime("%Y-%m-%d"), "2026-04-01")
        self.assertTrue(summary["has_valid_force_time"])
        self.assertEqual(summary["peak_force_n"], 3385)

    def test_imtp_force_time_lookup_keeps_older_valid_row_when_latest_row_is_basic_only(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-01",
                    **_storage_row(),
                },
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-10",
                    "IMTP_N": 3200,
                    "IMTP_avg_N": 2800,
                },
            ]
        )

        basic_row = select_basic_force_time_test_row(
            athlete_hist,
            test_id="imtp",
            selected_date="2026-04-10",
        )
        force_time_row = select_force_time_test_row(
            athlete_hist,
            test_id="imtp",
            selected_date="2026-04-10",
        )
        history = list_force_time_test_rows(athlete_hist, test_id="imtp")

        self.assertEqual(pd.Timestamp(basic_row["Date"]).strftime("%Y-%m-%d"), "2026-04-10")
        self.assertEqual(pd.Timestamp(force_time_row["Date"]).strftime("%Y-%m-%d"), "2026-04-01")
        self.assertFalse(bool(history.iloc[0]["has_valid_force_time"]))
        self.assertTrue(bool(history.iloc[1]["has_valid_force_time"]))

    def test_imtp_block_guard_is_independent_from_iso_guard(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta IMTP",
                    "Date": "2026-04-10",
                    "CMJ_cm": 35,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    **_storage_row(
                        IMTP_rfd_50_N_s=None,
                        IMTP_rfd_100_N_s=None,
                        IMTP_rfd_150_N_s=None,
                        IMTP_rfd_250_N_s=None,
                    ),
                }
            ]
        )

        imtp_summary = summarize_force_time_test(
            select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10"),
            test_id="imtp",
        )
        iso_summary = summarize_force_time_test(
            select_force_time_test_row(athlete_hist, test_id="iso_push_hamstring", selected_date="2026-04-10"),
            test_id="iso_push_hamstring",
        )

        self.assertTrue(imtp_summary["has_valid_force_time"])
        self.assertFalse(iso_summary["has_valid_force_time"])

    def test_imtp_and_iso_render_guards_behave_as_independent_siblings(self):
        scenarios = {
            "imtp_only": (
                pd.DataFrame([{"Athlete": "Atleta A", "Date": "2026-04-10", **_storage_row()}]),
                True,
                False,
            ),
            "iso_only": (
                pd.DataFrame([{"Athlete": "Atleta A", "Date": "2026-04-10", **_hamstring_storage_row()}]),
                False,
                True,
            ),
            "both_valid": (
                pd.DataFrame([{"Athlete": "Atleta A", "Date": "2026-04-10", **_storage_row(), **_hamstring_storage_row()}]),
                True,
                True,
            ),
            "neither_valid": (
                pd.DataFrame([{"Athlete": "Atleta A", "Date": "2026-04-10", "CMJ_cm": 35, "SJ_cm": 31}]),
                False,
                False,
            ),
        }

        for name, (athlete_hist, expect_imtp, expect_iso) in scenarios.items():
            with self.subTest(name=name):
                imtp_summary = summarize_force_time_test(
                    select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10"),
                    test_id="imtp",
                )
                iso_summary = summarize_force_time_test(
                    select_force_time_test_row(athlete_hist, test_id="iso_push_hamstring", selected_date="2026-04-10"),
                    test_id="iso_push_hamstring",
                )
                self.assertEqual(bool(imtp_summary["has_valid_force_time"]), expect_imtp)
                self.assertEqual(bool(iso_summary["has_valid_force_time"]), expect_iso)

    def test_force_time_row_lookup_tolerates_missing_columns_and_returns_none(self):
        athlete_hist = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta Parcial",
                    "Date": "2026-04-10",
                    "CMJ_cm": 35,
                    "SJ_cm": 31,
                }
            ]
        )

        imtp_row = select_force_time_test_row(athlete_hist, test_id="imtp", selected_date="2026-04-10")
        iso_row = select_force_time_test_row(
            athlete_hist,
            test_id="iso_push_hamstring",
            selected_date="2026-04-10",
        )

        self.assertIsNone(imtp_row)
        self.assertIsNone(iso_row)

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

    def test_chart_helpers_work_for_iso_push_hamstring_without_rfd_200(self):
        summary = summarize_force_time_test(_hamstring_storage_row(), test_id="iso_push_hamstring")

        asymmetry_chart = make_left_right_force_chart(get_asymmetry_summary(summary), theme=self.theme)
        force_chart = make_force_time_points_chart(get_force_time_points(summary), theme=self.theme)
        rfd_chart = make_rfd_points_chart(get_rfd_points(summary), theme=self.theme)

        self.assertIsNotNone(asymmetry_chart)
        self.assertIsNotNone(force_chart)
        self.assertIsNotNone(rfd_chart)
        self.assertEqual(list(force_chart.data[0].x), ["50 ms", "100 ms", "150 ms", "200 ms", "250 ms", "Peak"])
        self.assertEqual(list(rfd_chart.data[0].x), ["RFD 50", "RFD 100", "RFD 150", "RFD 250"])
        self.assertNotIn("RFD 200", [point["label"] for point in get_rfd_points(summary)])

    def test_dashboard_block_stays_guarded_when_peak_is_missing_but_partial_points_exist(self):
        summary = summarize_force_time_test(
            _storage_row(
                IMTP_N=None,
                IMTP_force_100_N=1364,
                IMTP_force_150_N=1620,
                IMTP_force_200_N=1957,
            )
        )
        source = PAGE_PATH.read_text(encoding="utf-8")

        self.assertFalse(summary["has_valid_force_time"])
        self.assertIsNotNone(make_force_time_points_chart(get_force_time_points(summary), theme=self.theme))
        self.assertIn('if imtp_force_time_summary.get("has_valid_force_time")', source)

    def test_upload_selector_exposes_iso_push_hamstring_with_expected_test_id(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn('("IMTP", "IMTP")', source)
        self.assertIn('("ISO Push Hip-Hamstring Bilateral", "iso_push_hamstring")', source)
        self.assertIn("FORCEPLATE_UPLOAD_TEST_IDS", source)

    def test_dashboard_force_time_rendering_uses_streamlit_safe_interpretation_lines(self):
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        app_source = APP_PATH.read_text(encoding="utf-8")
        interpretation = interpret_imtp_force_time(summarize_force_time_test(_storage_row()))
        lines = get_force_time_interpretation_lines(interpretation)

        self.assertTrue(lines)
        self.assertTrue(all(isinstance(line, str) for line in lines))
        self.assertIn("get_force_time_interpretation_lines", page_source)
        self.assertIn("get_force_time_interpretation_lines", app_source)

    def test_dashboard_sources_do_not_call_pdf_force_time_draw_helpers(self):
        page_source = PAGE_PATH.read_text(encoding="utf-8")
        app_source = APP_PATH.read_text(encoding="utf-8")

        self.assertNotIn("draw_force_time_test_block(", page_source)
        self.assertNotIn("draw_force_time_test_block(", app_source)
        self.assertNotIn("build_force_time_report_payload(", page_source)
        self.assertNotIn("build_force_time_report_payload(", app_source)

    def test_dashboard_copy_avoids_banned_force_time_language_for_imtp_and_iso(self):
        source = PAGE_PATH.read_text(encoding="utf-8").lower()
        app_source = APP_PATH.read_text(encoding="utf-8").lower()
        interpretation = interpret_hamstring_force_time(
            summarize_force_time_test(_hamstring_storage_row(), test_id="iso_push_hamstring")
        )
        combined = source + " " + app_source + " " + " ".join(str(value) for value in interpretation.values()).lower()

        self.assertIn("select_force_time_test_row", source)
        self.assertIn("estado de deteccion force-time", source)
        self.assertIn("filas con algun campo imtp", source)
        self.assertIn("filas con puntos force-time imtp", source)
        self.assertIn("detalle de la fila imtp candidata", source)
        self.assertIn("no se detectaron datos de imtp para este atleta.", source)
        self.assertIn("imtp detectado, pero faltan los campos force-time por puntos.", source)
        self.assertIn("imtp_avg_n", source)
        self.assertIn("imtp_force_100_n", source)
        self.assertIn("imtp_force_200_n", source)
        self.assertIn("imtp_force_250_n", source)
        self.assertIn("imtp_time_pull_s", source)
        self.assertIn("detalle force-time imtp", app_source)
        self.assertIn("fuerza isometrica complementaria - iso push hip-hamstring", app_source)
        self.assertIn("detalle force-time imtp", source)
        self.assertIn("fuerza isometrica complementaria - iso push hip-hamstring", source)
        self.assertIn("cadena posterior", combined)
        self.assertIn("flexores de rodilla", combined)
        self.assertIn("cautela", combined)
        self.assertIn("contextual", combined)
        self.assertNotIn("curva cruda", combined)
        self.assertNotIn("raw curve", combined)
        self.assertNotIn("rfd 200", combined)
        self.assertNotIn("riesgo de lesion alto", combined)
        self.assertNotIn("lesion probable", combined)
        self.assertNotIn("diagnostico", combined)


if __name__ == "__main__":
    unittest.main()
