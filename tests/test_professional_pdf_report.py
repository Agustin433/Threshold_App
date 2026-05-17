from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime as real_datetime
import re
import unittest
from unittest.mock import patch

import pandas as pd

import modules.report_generator as report_generator
from modules.report_generator import (
    PDF_MISSING_TEXT,
    PROFESSIONAL_NO_EVALUATION_TEXT,
    _build_professional_evolution_sections,
    _build_professional_integrated_interpretation,
    _build_professional_internal_load_context,
    _build_professional_metric_cards,
    _build_professional_next_steps,
    _build_professional_quadrant_sections,
    _build_professional_report_overview,
    _build_professional_training_context,
    _professional_assessment_date_count,
    _professional_metric_display_groups,
    _professional_short_assessment_interval_warning,
    _professional_quadrants_ready,
    _professional_wellness_context,
    generate_visual_report_pdf,
    safe_value,
)
from modules.report_force_time import build_force_time_report_payload


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _pdf_text(pdf: bytes) -> str:
    return pdf.decode("latin-1", errors="ignore").lower()


class FixedProfessionalReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


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
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "RPE": 6, "Duration_min": 53, "sRPE": 320},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "RPE": 7, "Duration_min": 49, "sRPE": 340},
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "RPE": 6, "Duration_min": 50, "sRPE": 300},
            {"Athlete": "Ana Lopez", "Date": "2026-05-05", "RPE": 7, "Duration_min": 43, "sRPE": 300},
        ]
    )
    wellness_df = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "Sueno_hs": 7.2, "Estres": 3, "Dolor": 2, "Wellness_Score": 8.0},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Sueno_hs": 7.0, "Estres": 4, "Dolor": 2, "Wellness_Score": 7.8},
            {"Athlete": "Ana Lopez", "Date": "2026-05-01", "Sueno_hs": 6.8, "Estres": 4, "Dolor": 3, "Wellness_Score": 7.2},
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 6.7, "Estres": 5, "Dolor": 3, "Wellness_Score": 7.0},
            {"Athlete": "Ana Lopez", "Date": "2026-05-05", "Sueno_hs": 6.6, "Estres": 5, "Dolor": 4, "Wellness_Score": 6.8},
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


def _professional_state_with_force_time() -> dict[str, object]:
    state = _weekly_state_without_evaluations()
    state["jump_df"] = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Date": "2026-04-01",
                "CMJ_cm": 32.0,
                "SJ_cm": 29.0,
                "DJ_cm": 24.0,
                "DJ_tc_ms": 230,
                "DRI": 1.4,
                "IMTP_N": 3300,
                "EUR": 1.10,
                "NM_Profile": "Reactivo",
            },
            {
                "Athlete": "Ana Lopez",
                "Date": "2026-05-01",
                "CMJ_cm": 33.0,
                "SJ_cm": 30.0,
                "DJ_cm": 25.0,
                "DJ_tc_ms": 225,
                "DRI": 1.5,
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
                "EUR": 1.12,
                "NM_Profile": "Reactivo",
            },
        ]
    )
    return state


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

    def test_metric_cards_keep_imtp_in_newtons_when_body_mass_is_missing(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-05-01",
                        "IMTP_N": 3385,
                    }
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        imtp_card = next(card for card in cards if card["title"] == "IMTP")

        self.assertEqual(imtp_card["value"], "3385 N")
        self.assertEqual(imtp_card["unit_label"], "N")
        self.assertNotEqual(imtp_card["unit_label"], "N/kg")

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

    def test_professional_quadrant_uses_dri_sj_instead_of_dj_rsi(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-01",
                        "CMJ_cm": 32.0,
                        "SJ_cm": 30.0,
                        "DJ_cm": 24.0,
                        "DJ_tc_ms": 220,
                        "IMTP_N": 1900,
                        "BW_kg": 70,
                    },
                    {
                        "Athlete": "Bruno Rey",
                        "Date": "2026-04-01",
                        "CMJ_cm": 36.0,
                        "SJ_cm": 28.0,
                        "DJ_cm": 21.0,
                        "DJ_tc_ms": 250,
                        "IMTP_N": 2100,
                        "BW_kg": 80,
                    },
                ]
            )
        }

        sections = _build_professional_quadrant_sections(state, "Ana Lopez")
        dri_section = sections[1]

        self.assertEqual(dri_section["title"], "Cuadrante fuerza concéntrica vs DRI")
        self.assertEqual(dri_section["x_col"], "DRI_Z")
        self.assertEqual(dri_section["x_label"], "DRI z")
        self.assertEqual(dri_section["y_label"], "SJ z")
        self.assertNotIn("DJ RSI", dri_section["title"])
        self.assertNotIn("DJ RSI", dri_section["what"])
        self.assertIsNotNone(dri_section["selected"])
        self.assertIn("SJ", dri_section["athlete_meaning"])
        self.assertIn("DRI", dri_section["athlete_meaning"])

    def test_professional_quadrant_does_not_fallback_to_rsi_when_dri_is_missing(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "SJ_Z": 0.8, "DJ_RSI_Z": 0.9},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-01", "SJ_Z": -0.2, "DJ_RSI_Z": -0.4},
                ]
            )
        }

        sections = _build_professional_quadrant_sections(state, "Ana Lopez")
        dri_section = sections[1]

        self.assertIsNone(dri_section["selected"])
        self.assertEqual(dri_section["message"], "Faltan datos para construir el cuadrante SJ vs DRI.")

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
        self.assertEqual(rows["Adherencia formal"], "Faltan datos")
        self.assertEqual(rows["Sesiones registradas"], "2")

    def test_metric_signal_treats_small_delta_inside_noise_as_yellow(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "DJ_cm": 25.0},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "DJ_cm": 24.9},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        dj_card = next(card for card in cards if card["title"] == "DJ")

        self.assertEqual(dj_card["signal"], "Amarillo")
        self.assertIn("error típico", dj_card["interpretation"])
        self.assertIn("TE de referencia", dj_card["te_caption"])

    def test_imtp_improvement_is_green_even_with_negative_reference_zscore(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "IMTP_N": 1000, "IMTP_N_Z": -1.2},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "IMTP_N": 1038, "IMTP_N_Z": -1.0},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        imtp_card = next(card for card in cards if card["title"] == "IMTP")

        self.assertEqual(imtp_card["signal"], "Verde")
        self.assertIn("Cambio favorable mayor al TE", imtp_card["interpretation"])
        self.assertNotEqual(imtp_card["signal"], "Referencia externa/grupal baja")

    def test_eur_keeps_context_note_while_using_te_semaphore(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "EUR": 1.10, "CMJ_cm": 33, "SJ_cm": 30},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "EUR": 1.18, "CMJ_cm": 34, "SJ_cm": 29},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        eur_card = next(card for card in cards if card["title"] == "EUR")

        self.assertEqual(eur_card["signal"], "Verde")
        self.assertIn("EUR debe interpretarse junto con CMJ y SJ", eur_card["interpretation"])

    def test_rsi_cards_use_index_units_not_meters_per_second(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "DJ_cm": 24.0, "DJ_tc_ms": 240},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "DJ_cm": 27.0, "DJ_tc_ms": 230},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        rsi_card = next(card for card in cards if card["title"] == "RSI")

        self.assertEqual(rsi_card["unit_label"], "Índice RSI")
        self.assertNotIn("m/s", rsi_card["value"])
        self.assertIn("unidades RSI", rsi_card["delta"])
        self.assertIn("unidades RSI", rsi_card["threshold"])
        self.assertNotIn("m/s", rsi_card["te_caption"])

    def test_eur_cards_keep_ratio_label(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "EUR": 1.10, "CMJ_cm": 33, "SJ_cm": 30},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "EUR": 1.18, "CMJ_cm": 34, "SJ_cm": 29},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        eur_card = next(card for card in cards if card["title"] == "EUR")

        self.assertEqual(eur_card["unit_label"], "Ratio")
        self.assertIn("EUR debe interpretarse junto con CMJ y SJ", eur_card["interpretation"])

    def test_contact_time_cards_keep_ms_units(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "DJ_tc_ms": 240},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "DJ_tc_ms": 232},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        contact_card = next(card for card in cards if card["title"] == "Contact Time")

        self.assertEqual(contact_card["unit_label"], "ms")
        self.assertTrue(contact_card["value"].endswith(" ms"))
        self.assertIn("ms", contact_card["threshold"])

    def test_large_individual_improvement_adds_protocol_warning(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0, "SJ_cm": 28.0},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-20", "CMJ_cm": 38.0, "SJ_cm": 32.5},
                ]
            )
        }

        cards = _build_professional_metric_cards(state, "Ana Lopez")
        cmj_card = next(card for card in cards if card["title"] == "CMJ")
        sj_card = next(card for card in cards if card["title"] == "SJ")

        self.assertIn("Mejora individual marcada", cmj_card["large_change_warning"])
        self.assertIn("calidad del dato", sj_card["large_change_warning"])

    def test_short_assessment_interval_adds_caution_warning(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-25", "CMJ_cm": 31.0},
                ]
            )
        }

        warning = _professional_short_assessment_interval_warning(state, "Ana Lopez")

        self.assertIn("Intervalo entre evaluaciones menor", warning)

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
        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _build_professional_internal_load_context({"rpe_df": None}, "Ana Lopez")

        self.assertEqual(context["state"], "missing")
        self.assertTrue(str(context["message"]).startswith("Faltan datos suficientes para analizar"))

    def test_internal_load_uses_sixteen_week_export_context(self):
        state = _weekly_state_without_evaluations()

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _build_professional_internal_load_context(state, "Ana Lopez")

        self.assertEqual(context["state"], "available")
        self.assertEqual(context["analysis_scope"], "last_complete_week")
        self.assertEqual(context["analysis_week_label"], "27/04/2026 - 03/05/2026")
        self.assertEqual(len(context["weekly_points"]), 16)
        self.assertIsNotNone(context["weekly_change_pct"])
        self.assertEqual(context["sessions_registered"], 2)
        self.assertEqual(context["days_without_data"], 5)
        self.assertAlmostEqual(context["last_week_total"], 660.0)
        self.assertAlmostEqual(context["current_week_total"], 600.0)

    def test_midweek_report_uses_last_complete_week_not_current_week(self):
        state = {
            "rpe_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-21", "sRPE": 500},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-23", "sRPE": 500},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-28", "sRPE": 600},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-30", "sRPE": 600},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-04", "sRPE": 300},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-05", "sRPE": 300},
                ]
            ),
            "weekly_summaries": {
                "weekly_load": pd.DataFrame(
                    [
                        {"Athlete": "Ana Lopez", "week_start": "2026-04-20", "weekly_sRPE": 1000, "sessions_count": 2},
                        {"Athlete": "Ana Lopez", "week_start": "2026-04-27", "weekly_sRPE": 1200, "sessions_count": 2},
                        {"Athlete": "Ana Lopez", "week_start": "2026-05-04", "weekly_sRPE": 600, "sessions_count": 2},
                    ]
                ),
                "weekly_wellness": pd.DataFrame(),
                "weekly_external": pd.DataFrame(),
                "weekly_team": pd.DataFrame(),
            },
        }

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _build_professional_internal_load_context(state, "Ana Lopez")

        self.assertEqual(context["analysis_scope"], "last_complete_week")
        self.assertEqual(context["analysis_week_label"], "27/04/2026 - 03/05/2026")
        self.assertAlmostEqual(context["last_week_total"], 1200.0)
        self.assertAlmostEqual(context["current_week_total"], 600.0)
        self.assertAlmostEqual(context["weekly_change_pct"], 20.0)

    def test_current_partial_week_is_not_compared_as_closed_week(self):
        state = {
            "rpe_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-05-04", "sRPE": 380},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-05", "sRPE": 400},
                ]
            ),
            "weekly_summaries": {
                "weekly_load": pd.DataFrame(
                    [
                        {"Athlete": "Ana Lopez", "week_start": "2026-05-04", "weekly_sRPE": 780, "sessions_count": 2},
                    ]
                ),
                "weekly_wellness": pd.DataFrame(),
                "weekly_external": pd.DataFrame(),
                "weekly_team": pd.DataFrame(),
            },
        }

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _build_professional_internal_load_context(state, "Ana Lopez")
            joined = " ".join(_build_professional_integrated_interpretation(context, {"state": "missing", "weekly_points": []}))

        self.assertEqual(context["analysis_scope"], "current_week_partial")
        self.assertIsNone(context["weekly_change_pct"])
        self.assertIn("no debe compararse", context["current_week_partial_message"])
        self.assertIn("acumulado parcial", joined)
        self.assertNotIn("disminuyó", joined)

    def test_wellness_context_exposes_last_week_and_sixteen_week_trends(self):
        state = _weekly_state_without_evaluations()

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _professional_wellness_context(state, "Ana Lopez")

        self.assertEqual(context["state"], "available")
        self.assertEqual(context["analysis_scope"], "last_complete_week")
        self.assertEqual(context["analysis_week_label"], "27/04/2026 - 03/05/2026")
        self.assertEqual(len(context["weekly_points"]), 16)
        self.assertEqual(context["last_week_summary"]["days"], 3)
        self.assertAlmostEqual(context["last_week_summary"]["sleep_mean"], 7.0, places=1)
        self.assertEqual(context["scales"]["sleep"], "h")
        self.assertEqual(context["scales"]["stress"], "/5")
        self.assertEqual(context["scales"]["pain"], "/5")
        self.assertEqual(context["scales"]["score"], "/5.0")

    def test_wellness_context_marks_single_record_as_partial_context_not_trend(self):
        state = {
            "wellness_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 5.8, "Estres": 8, "Dolor": 7, "Wellness_Score": 10},
                ]
            )
        }

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _professional_wellness_context(state, "Ana Lopez")

        self.assertEqual(context["state"], "partial")
        self.assertEqual(context["analysis_scope"], "current_week_partial")
        self.assertEqual(context["analysis_title"], "Wellness - semana en curso")
        self.assertFalse(context["trend_allowed"])
        self.assertIn("Registro parcial: 1 día con datos", context["partial_message"])

    def test_wellness_current_week_partial_is_labeled_correctly(self):
        state = {
            "wellness_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 6.8, "Estres": 6, "Dolor": 2, "Wellness_Score": 15},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-05", "Sueno_hs": 6.6, "Estres": 7, "Dolor": 3, "Wellness_Score": 14},
                ]
            )
        }

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            context = _professional_wellness_context(state, "Ana Lopez")

        self.assertEqual(context["analysis_scope"], "current_week_partial")
        self.assertEqual(context["analysis_title"], "Wellness - semana en curso")
        self.assertEqual(context["last_week_summary"]["days"], 2)
        self.assertIn("Registro parcial: 2 días con datos", context["partial_message"])

    def test_integrated_interpretation_uses_brief_wellness_partial_message(self):
        internal = {"weekly_change_pct": 12.0, "weekly_change": 80}
        wellness = {
            "state": "partial",
            "weekly_points": [],
            "last_week_summary": {"days": 1, "stress_mean": 8.0, "pain_mean": 7.0, "sleep_mean": 5.8},
            "partial_message": "Wellness parcial: solo 1 día con registro. Sueño bajo, estrés elevado y dolor elevado.",
            "scales": {"stress": "/10", "pain": "/10", "sleep": "h", "score": "escala no definida"},
        }

        joined = " ".join(_build_professional_integrated_interpretation(internal, wellness))

        self.assertIn("La lectura del wellness es limitada por baja cantidad de registros", joined)
        self.assertNotIn("Wellness parcial: solo 1 día con registro", joined)

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

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 4)

    def test_professional_pdf_with_partial_evaluations_stays_compact(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 32.0},
            ]
        )

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 7)

    def test_professional_pdf_partial_evaluations_and_partial_wellness_stays_compact(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0, "SJ_cm": 28.0},
                {"Athlete": "Ana Lopez", "Date": "2026-04-25", "CMJ_cm": 38.0, "SJ_cm": 32.0},
            ]
        )
        state["wellness_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 5.8, "Estres": 8, "Dolor": 7, "Wellness_Score": 10},
            ]
        )

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 7)

    def test_partial_next_steps_include_protocol_and_missing_metrics_guidance(self):
        steps = _build_professional_next_steps("partial")

        self.assertTrue(any("Completar métricas faltantes" in step for step in steps))
        self.assertTrue(any("entrada en calor" in step for step in steps))
        self.assertTrue(any("no reemplazan el perfil físico" in step for step in steps))

    def test_quadrant_sections_do_not_mix_missing_message_with_valid_location(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-01",
                        "CMJ_cm": 32.0,
                        "SJ_cm": 30.0,
                        "DJ_cm": 24.0,
                        "DJ_tc_ms": 220,
                        "IMTP_N": 1900,
                        "BW_kg": 70,
                        "EUR": 1.08,
                    },
                    {
                        "Athlete": "Bruno Rey",
                        "Date": "2026-04-01",
                        "CMJ_cm": 36.0,
                        "SJ_cm": 28.0,
                        "DJ_cm": 21.0,
                        "DJ_tc_ms": 250,
                        "IMTP_N": 2100,
                        "BW_kg": 80,
                        "EUR": 1.15,
                    },
                ]
            )
        }

        sections = _build_professional_quadrant_sections(state, "Ana Lopez")
        ready_sections = [section for section in sections if section["selected"] is not None]

        self.assertTrue(ready_sections)
        for section in ready_sections:
            self.assertEqual(section["message"], "")
            self.assertNotEqual(section["location"], PDF_MISSING_TEXT)
            self.assertNotIn("Faltan datos para ubicar al atleta", section["location"])

    def test_professional_narrative_avoids_double_periods(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0, "SJ_cm": 28.0},
                {"Athlete": "Ana Lopez", "Date": "2026-05-20", "CMJ_cm": 31.5, "SJ_cm": 29.0},
            ]
        )

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            cards = _build_professional_metric_cards(state, "Ana Lopez")
            training = _build_professional_training_context(state, "Ana Lopez")
            internal = _build_professional_internal_load_context(state, "Ana Lopez")
            overview = _build_professional_report_overview(state, "Ana Lopez", cards, training, internal)
            wellness = _professional_wellness_context(state, "Ana Lopez")
            lines = _build_professional_integrated_interpretation(
                internal,
                wellness,
                evaluation_state="partial",
                assessment_interval_warning=_professional_short_assessment_interval_warning(state, "Ana Lopez"),
            )

        text = " ".join([overview["reading"], overview["decision"], *lines])
        self.assertNotIn("..", text)

    def test_professional_pdf_calls_expected_section_builders(self):
        state = _professional_state_with_force_time()

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            with ExitStack() as stack:
                mocks = {
                    name: stack.enter_context(patch.object(report_generator, name, wraps=getattr(report_generator, name)))
                    for name in [
                        "_build_professional_metric_cards",
                        "_build_professional_evolution_sections",
                        "_build_professional_quadrant_sections",
                        "_build_professional_training_context",
                        "_build_professional_internal_load_context",
                        "_professional_wellness_context",
                        "_build_professional_integrated_interpretation",
                        "_build_professional_next_steps",
                    ]
                }
                pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        for name, mocked in mocks.items():
            self.assertGreaterEqual(mocked.call_count, 1, name)


    def test_professional_pdf_with_imtp_force_time_generates_contextual_block(self):
        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            with patch.object(report_generator, "draw_force_time_test_block", wraps=report_generator.draw_force_time_test_block) as mocked_draw:
                pdf = generate_visual_report_pdf(_professional_state_with_force_time(), "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertEqual(mocked_draw.call_count, 1)

    def test_professional_pdf_without_imtp_force_time_generates_without_optional_block(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 32.0, "SJ_cm": 28.0, "IMTP_N": 1900},
            ]
        )

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            with patch.object(report_generator, "draw_force_time_test_block", wraps=report_generator.draw_force_time_test_block) as mocked_draw:
                pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertEqual(mocked_draw.call_count, 0)

    def test_force_time_payload_for_professional_stays_descriptive(self):
        payload = build_force_time_report_payload(
            _professional_state_with_force_time()["jump_df"].iloc[-1],
            report_type="professional",
        )
        combined = " ".join(str(value) for value in payload["interpretation"].values()).lower()

        self.assertTrue(payload["has_valid_force_time"])
        self.assertIn("rfd", combined)
        self.assertIn("cautela", combined)
        self.assertNotIn("curva cruda", combined)
        self.assertNotIn("raw curve", combined)
        self.assertNotIn("riesgo de lesi", combined)
        self.assertNotIn("lesion probable", combined)
        self.assertNotIn("diagn", combined)
        self.assertNotIn("rfd 200", combined)


if __name__ == "__main__":
    unittest.main()
