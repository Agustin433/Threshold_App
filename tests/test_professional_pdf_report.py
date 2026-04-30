from __future__ import annotations

import re
import unittest

import pandas as pd

from modules.report_generator import (
    PDF_MISSING_TEXT,
    PROFESSIONAL_NO_EVALUATION_TEXT,
    _build_professional_evolution_sections,
    _build_professional_integrated_interpretation,
    _build_professional_internal_load_context,
    _build_professional_metric_cards,
    _build_professional_quadrant_sections,
    _build_professional_report_overview,
    _build_professional_training_context,
    _professional_assessment_date_count,
    _professional_metric_display_groups,
    _professional_quadrants_ready,
    _professional_wellness_context,
    generate_visual_report_pdf,
    safe_value,
)


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _weekly_state_without_evaluations() -> dict[str, object]:
    weeks = pd.date_range("2026-01-05", periods=18, freq="W-MON")
    weekly_load = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "week_start": week,
                "weekly_sRPE": 420 + idx * 15,
                "sessions_count": 2,
            }
            for idx, week in enumerate(weeks)
        ]
    )
    weekly_wellness = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "week_start": week,
                "Sueno_mean": 7.6 - idx * 0.02,
                "Estres_mean": 3.0 + idx * 0.03,
                "Dolor_mean": 2.0 + idx * 0.02,
                "Wellness_mean": 8.1 - idx * 0.03,
                "wellness_days": 3,
            }
            for idx, week in enumerate(weeks)
        ]
    )
    rpe_df = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "RPE": 6, "Duration_min": 50, "sRPE": 300},
            {"Athlete": "Ana Lopez", "Date": "2026-05-06", "RPE": 7, "Duration_min": 45, "sRPE": 315},
        ]
    )
    wellness_df = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 7.2, "Estres": 3, "Dolor": 2, "Wellness_Score": 8.0},
            {"Athlete": "Ana Lopez", "Date": "2026-05-05", "Sueno_hs": 7.0, "Estres": 4, "Dolor": 2, "Wellness_Score": 7.8},
            {"Athlete": "Ana Lopez", "Date": "2026-05-06", "Sueno_hs": 6.8, "Estres": 4, "Dolor": 3, "Wellness_Score": 7.2},
        ]
    )
    return {
        "completion_df": None,
        "jump_df": None,
        "rpe_df": rpe_df,
        "wellness_df": wellness_df,
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {},
        "mono_dict": {},
        "weekly_summaries": {
            "weekly_load": weekly_load,
            "weekly_wellness": weekly_wellness,
            "weekly_external": pd.DataFrame(),
            "weekly_team": pd.DataFrame(),
        },
    }


class ProfessionalPdfReportTest(unittest.TestCase):
    def test_safe_value_hides_empty_values(self):
        self.assertEqual(safe_value(None), PDF_MISSING_TEXT)
        self.assertEqual(safe_value(float("nan")), PDF_MISSING_TEXT)
        self.assertEqual(safe_value(pd.NA), PDF_MISSING_TEXT)
        self.assertEqual(safe_value(""), PDF_MISSING_TEXT)
        self.assertEqual(safe_value("-"), PDF_MISSING_TEXT)
        self.assertEqual(safe_value("Sin dato"), PDF_MISSING_TEXT)
        self.assertEqual(safe_value(0), "0")

    def test_metric_cards_keep_all_requested_metrics_with_missing_fields(self):
        state = {
            "completion_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-04-20", "Pct": 0.8}]),
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-01",
                        "CMJ_cm": 32.0,
                    }
                ]
            ),
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")

        self.assertEqual([card["title"] for card in cards], ["CMJ", "SJ", "DJ", "RSI", "Contact Time", "EUR", "mRSI", "IMTP"])
        cmj_card = cards[0]
        self.assertEqual(cmj_card["delta"], PDF_MISSING_TEXT)
        self.assertEqual(cmj_card["best"], "32.0 cm")
        self.assertEqual(cards[1]["value"], PDF_MISSING_TEXT)
        self.assertEqual(cards[1]["z_score"], PDF_MISSING_TEXT)

    def test_metric_cards_can_collapse_when_no_evaluations_exist(self):
        cards = _build_professional_metric_cards({"jump_df": None}, "Ana Lopez")

        available, missing = _professional_metric_display_groups(cards)

        self.assertEqual(available, [])
        self.assertEqual(len(missing), 8)
        self.assertIn("Faltan datos de evaluación", PROFESSIONAL_NO_EVALUATION_TEXT)

    def test_professional_pdf_generates_with_missing_datasets(self):
        state = {
            "completion_df": pd.DataFrame([{"Athlete": "Solo Test", "Date": "2026-04-20", "Pct": 0.8}]),
            "jump_df": None,
            "rpe_df": None,
            "wellness_df": None,
            "raw_df": None,
            "maxes_df": None,
            "rep_load_df": None,
            "acwr_dict": {},
            "mono_dict": {},
        }

        pdf = generate_visual_report_pdf(state, "Solo Test", "profe")

        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_evolution_sections_report_missing_when_only_one_assessment_exists(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-01",
                        "CMJ_cm": 32.0,
                    }
                ]
            )
        }

        sections = _build_professional_evolution_sections(state, "Ana Lopez")

        self.assertEqual(sections[0]["state"], "missing")
        self.assertTrue(str(sections[0]["message"]).startswith("Faltan datos para mostrar"))
        self.assertEqual(_professional_assessment_date_count(state, "Ana Lopez"), 1)

    def test_quadrant_points_do_not_store_other_athlete_names_for_pdf_labels(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-01",
                        "CMJ_cm": 32.0,
                        "SJ_cm": 28.0,
                        "DJ_cm": 24.0,
                        "DJ_tc_ms": 240,
                        "IMTP_N": 1900,
                        "BW_kg": 70,
                    },
                    {
                        "Athlete": "Bruno Rey",
                        "Date": "2026-04-01",
                        "CMJ_cm": 35.0,
                        "SJ_cm": 30.0,
                        "DJ_cm": 25.0,
                        "DJ_tc_ms": 230,
                        "IMTP_N": 2100,
                        "BW_kg": 80,
                    },
                ]
            )
        }

        sections = _build_professional_quadrant_sections(state, "Ana Lopez")
        points = sections[0]["points"]

        self.assertTrue(points)
        self.assertTrue(any(point["selected"] for point in points))
        self.assertTrue(all("Athlete" not in point and "name" not in point for point in points))

    def test_quadrants_collapse_when_all_three_are_not_available(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 32.0},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-01", "CMJ_cm": 35.0},
                ]
            )
        }

        sections = _build_professional_quadrant_sections(state, "Ana Lopez")

        self.assertFalse(_professional_quadrants_ready(sections))

    def test_training_context_uses_sessions_when_adherence_is_missing(self):
        state = {
            "completion_df": None,
            "rpe_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-20", "RPE": 6, "Duration_min": 50, "sRPE": 300},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-22", "RPE": 7, "Duration_min": 40, "sRPE": 280},
                ]
            ),
            "wellness_df": None,
            "raw_df": None,
            "acwr_dict": {},
        }

        context = _build_professional_training_context(state, "Ana Lopez")
        rows = dict(context["rows"])

        self.assertEqual(context["state"], "partial")
        self.assertIn("Faltan datos. Sesiones registradas: 2.", rows["Adherencia formal"])
        self.assertEqual(rows["Sesiones registradas"], "2 sesión(es)")

    def test_report_overview_summarizes_available_sections(self):
        state = {
            "jump_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 32.0}]),
            "rpe_df": None,
            "wellness_df": None,
            "completion_df": None,
            "raw_df": None,
        }
        cards = _build_professional_metric_cards(state, "Ana Lopez")
        training = _build_professional_training_context(state, "Ana Lopez")
        internal = _build_professional_internal_load_context(state, "Ana Lopez")

        overview = _build_professional_report_overview(state, "Ana Lopez", cards, training, internal)

        self.assertEqual(overview["statuses"]["Evaluaciones físicas"], "Parcial")
        self.assertEqual(overview["statuses"]["Entrenamiento"], "Faltan datos")
        self.assertIn("Perfil físico parcial", overview["reading"])

    def test_internal_load_marks_missing_without_rpe(self):
        context = _build_professional_internal_load_context({"rpe_df": None}, "Ana Lopez")

        self.assertEqual(context["state"], "missing")
        self.assertTrue(str(context["message"]).startswith("Faltan datos de carga interna"))

    def test_internal_load_uses_sixteen_week_export_context(self):
        state = _weekly_state_without_evaluations()

        context = _build_professional_internal_load_context(state, "Ana Lopez")

        self.assertEqual(context["state"], "available")
        self.assertEqual(len(context["weekly_points"]), 16)
        self.assertIsNotNone(context["weekly_change_pct"])
        self.assertEqual(context["sessions_registered"], 2)
        self.assertEqual(context["days_without_data"], 5)

    def test_wellness_context_exposes_last_week_and_sixteen_week_trends(self):
        state = _weekly_state_without_evaluations()

        context = _professional_wellness_context(state, "Ana Lopez")

        self.assertEqual(context["state"], "available")
        self.assertEqual(len(context["weekly_points"]), 16)
        self.assertEqual(context["last_week_summary"]["days"], 3)
        self.assertAlmostEqual(context["last_week_summary"]["sleep_mean"], 7.0, places=1)
        self.assertEqual(context["scales"]["sleep"], "h")
        self.assertEqual(context["scales"]["stress"], "/5")
        self.assertEqual(context["scales"]["pain"], "/5")
        self.assertEqual(context["scales"]["score"], "escala no definida")

    def test_integrated_interpretation_only_mentions_real_weekly_changes(self):
        internal = {"weekly_change_pct": 29.3, "weekly_change": 120}
        wellness = {
            "state": "available",
            "weekly_points": [],
            "last_week_summary": {"stress_mean": 4.5, "pain_mean": 2.0, "sleep_mean": 7.0},
            "scales": {"stress": "/5", "pain": "/5", "sleep": "h", "score": "escala no definida"},
        }

        lines = _build_professional_integrated_interpretation(internal, wellness)
        joined = " ".join(lines)

        self.assertIn("+29.3%", joined)
        self.assertIn("estrés promedio fue elevado", joined)
        self.assertNotIn("wellness/readiness disminuyó", joined)

    def test_integrated_interpretation_formats_score_drop_as_points(self):
        internal = {"weekly_change_pct": 29.3, "weekly_change": 120}
        wellness = {
            "state": "available",
            "weekly_points": [{"score": 20.0}, {"score": 18.9}],
            "last_week_summary": {"stress_mean": 8.4, "pain_mean": 2.0, "sleep_mean": 7.0},
            "scales": {"stress": "/10", "pain": "/10", "sleep": "h", "score": "escala no definida"},
        }

        joined = " ".join(_build_professional_integrated_interpretation(internal, wellness))

        self.assertIn("La carga interna semanal aumentó +29.3%", joined)
        self.assertIn("wellness score disminuyó 1.1 puntos", joined)
        self.assertIn("estrés promedio fue elevado (8.4/10)", joined)
        self.assertNotIn("-1.1 respecto", joined)

    def test_professional_pdf_without_evaluations_stays_compact(self):
        state = _weekly_state_without_evaluations()

        pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 3)


if __name__ == "__main__":
    unittest.main()
