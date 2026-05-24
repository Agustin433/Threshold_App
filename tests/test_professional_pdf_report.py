from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime as real_datetime
from io import BytesIO
import re
import unicodedata
import unittest
from unittest.mock import patch

import pandas as pd
from pypdf import PdfReader

import modules.report_generator as report_generator
from modules.jump_analysis import (
    build_composite_profile_metric_table,
    build_composite_profile_snapshot,
)
from modules.report_generator import (
    PDF_MISSING_TEXT,
    PROFESSIONAL_NO_EVALUATION_TEXT,
    _build_professional_action_plan_payload,
    _build_professional_change_payload,
    _build_professional_composite_profile_payload,
    _build_professional_exposure_payload,
    _build_professional_evolution_sections,
    _build_professional_integrated_interpretation,
    _build_professional_internal_load_context,
    _build_professional_load_tolerance_payload,
    _build_professional_metric_cards,
    _build_professional_next_steps,
    _build_professional_quadrant_sections,
    _build_professional_report_overview,
    _build_professional_training_context,
    _build_professional_wellness_availability_payload,
    _quality_detail_text,
    _professional_assessment_date_count,
    _professional_join_labels,
    _professional_metric_display_groups,
    _professional_short_assessment_interval_warning,
    _professional_quadrants_ready,
    _professional_wellness_context,
    _repair_mojibake_text,
    generate_visual_report_pdf,
    safe_value,
)
from modules.report_force_time import build_force_time_report_payload


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _pdf_text(pdf: bytes) -> str:
    return pdf.decode("latin-1", errors="ignore").lower()


def _pdf_extracted_text_pages(pdf: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf))
    return [(page.extract_text() or "") for page in reader.pages]


def _normalized_pdf_pages(pdf: bytes) -> list[str]:
    return [_normalized_story_text(page) for page in _pdf_extracted_text_pages(pdf)]


def _normalized_story_text(text: str) -> str:
    repaired = report_generator._repair_mojibake_text(text)
    return unicodedata.normalize("NFD", repaired).encode("ascii", "ignore").decode("ascii").lower()


def _story_plain_text(flowable: object) -> list[str]:
    if flowable is None:
        return []
    if isinstance(flowable, (list, tuple)):
        lines: list[str] = []
        for item in flowable:
            lines.extend(_story_plain_text(item))
        return lines
    if hasattr(flowable, "getPlainText"):
        try:
            return [str(flowable.getPlainText())]
        except Exception:
            return []
    if hasattr(flowable, "_cellvalues"):
        lines = []
        for row in getattr(flowable, "_cellvalues", []) or []:
            lines.extend(_story_plain_text(row))
        return lines
    return []


def _rendered_pdf_and_story_text(
    state: dict[str, object],
    athlete: str,
    audience: str = "profe",
    now_cls: type[real_datetime] | None = None,
) -> tuple[bytes, str]:
    from reportlab.platypus import SimpleDocTemplate

    captured: dict[str, object] = {}
    original_build = SimpleDocTemplate.build

    def capture_build(self, flowables, *args, **kwargs):
        captured["story"] = list(flowables)
        return original_build(self, flowables, *args, **kwargs)

    active_now_cls = now_cls or FixedProfessionalReportDate
    with patch.object(report_generator, "datetime", active_now_cls):
        with patch.object(SimpleDocTemplate, "build", capture_build):
            pdf = generate_visual_report_pdf(state, athlete, audience)

    assert pdf is not None
    text = _normalized_story_text(" ".join(_story_plain_text(captured.get("story", []))))
    return pdf, text


def _rendered_story_text(state: dict[str, object], athlete: str, audience: str = "profe") -> str:
    return _rendered_pdf_and_story_text(state, athlete, audience)[1]


def _rendered_pdf_and_raw_story_text(
    state: dict[str, object],
    athlete: str,
    audience: str = "profe",
    now_cls: type[real_datetime] | None = None,
) -> tuple[bytes, str]:
    from reportlab.platypus import SimpleDocTemplate

    captured: dict[str, object] = {}
    original_build = SimpleDocTemplate.build

    def capture_build(self, flowables, *args, **kwargs):
        captured["story"] = list(flowables)
        return original_build(self, flowables, *args, **kwargs)

    active_now_cls = now_cls or FixedProfessionalReportDate
    with patch.object(report_generator, "datetime", active_now_cls):
        with patch.object(SimpleDocTemplate, "build", capture_build):
            pdf = generate_visual_report_pdf(state, athlete, audience)

    assert pdf is not None
    raw_text = " ".join(_story_plain_text(captured.get("story", [])))
    return pdf, raw_text


def _assert_professional_mother_structure(testcase: unittest.TestCase, text: str) -> None:
    expected_terms = [
        "perfil actual compuesto",
        "cambios vs evaluacion anterior",
        "exposicion del bloque",
        "interpretacion integrada profesional",
        "que sabemos",
        "que parece probable",
        "que no podemos afirmar",
        "decision practica",
        "mantener",
        "ajustar",
        "monitorear",
        "medir",
    ]
    for term in expected_terms:
        testcase.assertIn(term, text)


def _assert_legacy_professional_sections_absent(testcase: unittest.TestCase, text: str) -> None:
    legacy_terms = [
        "tarjetas de evaluaci",
        "paso recomendado",
    ]
    for term in legacy_terms:
        testcase.assertNotIn(term, text)


class FixedProfessionalReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


class LateProfessionalReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 19, 12, 0, tzinfo=tz)


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


def _state_with_future_empty_week() -> dict[str, object]:
    state = _weekly_state_without_evaluations()
    state["rpe_df"] = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "sRPE": 600},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "sRPE": 600},
            {"Athlete": "Ana Lopez", "Date": "2026-05-06", "sRPE": 300},
            {"Athlete": "Ana Lopez", "Date": "2026-05-09", "sRPE": 300},
        ]
    )
    state["wellness_df"] = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "Sueno_hs": 7.2, "Estres": 3, "Dolor": 2, "Wellness_Score": 8.0},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Sueno_hs": 7.0, "Estres": 4, "Dolor": 2, "Wellness_Score": 7.8},
            {"Athlete": "Ana Lopez", "Date": "2026-05-01", "Sueno_hs": 6.8, "Estres": 4, "Dolor": 3, "Wellness_Score": 7.2},
            {"Athlete": "Ana Lopez", "Date": "2026-05-06", "Sueno_hs": 6.5, "Estres": 5, "Dolor": 3, "Wellness_Score": 7.0},
            {"Athlete": "Ana Lopez", "Date": "2026-05-09", "Sueno_hs": 6.4, "Estres": 5, "Dolor": 4, "Wellness_Score": 6.7},
        ]
    )
    state["weekly_summaries"] = {
        "weekly_load": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "week_start": "2026-04-20", "weekly_sRPE": 1000, "sessions_count": 2},
                {"Athlete": "Ana Lopez", "week_start": "2026-04-27", "weekly_sRPE": 1200, "sessions_count": 2},
                {"Athlete": "Ana Lopez", "week_start": "2026-05-04", "weekly_sRPE": 600, "sessions_count": 2},
                {"Athlete": "Ana Lopez", "week_start": "2026-05-18", "weekly_sRPE": 0, "sessions_count": 0},
            ]
        ),
        "weekly_wellness": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "week_start": "2026-04-20", "Sueno_mean": 7.3, "Estres_mean": 3.5, "Dolor_mean": 2.0, "wellness_days": 3},
                {"Athlete": "Ana Lopez", "week_start": "2026-04-27", "Sueno_mean": 7.0, "Estres_mean": 3.7, "Dolor_mean": 2.3, "wellness_days": 3},
                {"Athlete": "Ana Lopez", "week_start": "2026-05-04", "Sueno_mean": 6.5, "Estres_mean": 5.0, "Dolor_mean": 3.5, "wellness_days": 2},
                {"Athlete": "Ana Lopez", "week_start": "2026-05-18", "Sueno_mean": None, "Estres_mean": None, "Dolor_mean": None, "wellness_days": 0},
            ]
        ),
        "weekly_external": pd.DataFrame(),
        "weekly_team": pd.DataFrame(),
    }
    return state


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


def _professional_state_with_force_time_and_exposure() -> dict[str, object]:
    state = _professional_state_with_force_time()
    exposure_df = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Assigned Date": "2026-04-28",
                "Exercise": "Back Squat producción",
                "stimulus_category": "strength_loaded",
                "Volume_Load_kg": 3200,
                "Contacts": 0,
                "Exposures": 1,
                "is_invalid": False,
                "is_untagged": False,
            },
            {
                "Athlete": "Ana Lopez",
                "Assigned Date": "2026-04-29",
                "Exercise": "Pliometría evaluación",
                "stimulus_category": "plyo_jump",
                "Volume_Load_kg": 0,
                "Contacts": 48,
                "Exposures": 1,
                "is_invalid": False,
                "is_untagged": False,
            },
            {
                "Athlete": "Ana Lopez",
                "Assigned Date": "2026-05-01",
                "Exercise": "Hang Power Clean contracción",
                "stimulus_category": "olympic_derivatives",
                "Volume_Load_kg": 0,
                "Contacts": 0,
                "Exposures": 1,
                "is_invalid": False,
                "is_untagged": False,
            },
        ]
    )
    state["prepared_raw_df"] = exposure_df
    state["raw_df"] = exposure_df.copy()
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

    def test_professional_pdf_without_evaluations_uses_mother_structure(self):
        state = _weekly_state_without_evaluations()

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 10)
        _assert_professional_mother_structure(self, text)
        _assert_legacy_professional_sections_absent(self, text)
        self.assertIn("faltan datos", text)

    def test_professional_pdf_with_partial_evaluations_uses_mother_structure(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 32.0},
            ]
        )

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 10)
        _assert_professional_mother_structure(self, text)
        _assert_legacy_professional_sections_absent(self, text)

    def test_professional_pdf_partial_evaluations_and_partial_wellness_uses_mother_structure(self):
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

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 10)
        _assert_professional_mother_structure(self, text)
        _assert_legacy_professional_sections_absent(self, text)

    def test_professional_pdf_missing_evolution_does_not_return_to_legacy_cards(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 32.0, "SJ_cm": 28.0, "DJ_cm": 24.0},
            ]
        )

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertIn("cambios vs evaluacion anterior", text)
        self.assertIn("faltan datos", text)
        self.assertLessEqual(_pdf_page_count(pdf), 9)
        _assert_professional_mother_structure(self, text)
        _assert_legacy_professional_sections_absent(self, text)

    def test_missing_evolution_note_stays_compact_inside_composite_page(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-05-01",
                    "SJ_cm": 31.0,
                    "CMJ_cm": 34.0,
                    "DJ_cm": 22.0,
                    "DJ_tc_ms": 210.0,
                    "DRI": 1.42,
                    "IMTP_relPF": 39.5,
                    "SJ_Z": 0.8,
                    "CMJ_Z": 0.7,
                    "DJ_height_Z": -1.0,
                    "DJ_RSI_Z": 0.2,
                    "TC_inv_Z": 0.9,
                    "IMTP_relPF_Z": 0.6,
                },
                {
                    "Athlete": "Bruno Rey",
                    "Date": "2026-05-01",
                    "SJ_cm": 29.0,
                    "CMJ_cm": 33.0,
                    "DJ_cm": 23.0,
                    "DJ_tc_ms": 225.0,
                    "DRI": 1.18,
                    "IMTP_relPF": 35.0,
                    "SJ_Z": 0.2,
                    "CMJ_Z": 0.1,
                    "DJ_height_Z": 0.1,
                    "DJ_RSI_Z": 0.0,
                    "TC_inv_Z": -0.2,
                    "IMTP_relPF_Z": 0.1,
                },
            ]
        )

        pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")
        pages = _normalized_pdf_pages(pdf)
        pages_with_change_note = [page for page in pages if "cambios vs evaluacion anterior" in page]

        self.assertLessEqual(len(pages), 9)
        self.assertEqual(len(pages_with_change_note), 1)
        self.assertIn("perfil actual compuesto", pages_with_change_note[0])
        self.assertIn("notas metodologicas", pages_with_change_note[0])
        self.assertIn("cambios vs evaluacion anterior: faltan datos", pages_with_change_note[0])
        self.assertIn("mostrar evolucion entre evaluaciones", pages_with_change_note[0])

    def test_client_and_athlete_pdfs_do_not_use_professional_mother_structure(self):
        state = _weekly_state_without_evaluations()

        for audience in ["cliente", "atleta"]:
            with self.subTest(audience=audience):
                _, text = _rendered_pdf_and_story_text(state, "Ana Lopez", audience)

                self.assertNotIn("perfil actual compuesto", text)
                self.assertNotIn("interpretacion integrada profesional", text)
                self.assertNotIn("decision practica", text)

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
        with patch.object(report_generator, "_draw_compact_professional_force_time_block", wraps=report_generator._draw_compact_professional_force_time_block) as mocked_compact:
            with patch.object(report_generator, "draw_force_time_test_block", wraps=report_generator.draw_force_time_test_block) as mocked_draw:
                pdf, text = _rendered_pdf_and_story_text(_professional_state_with_force_time(), "Ana Lopez", "profe")

        self.assertIsNotNone(pdf)
        self.assertEqual(mocked_compact.call_count, 1)
        self.assertEqual(mocked_draw.call_count, 0)
        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("detalle tecnico compacto", text)
        self.assertIn("force@50", text)
        self.assertIn("rfd exportada descriptiva", text)

    def test_professional_pdf_full_advanced_case_with_exposure_stays_within_ten_pages(self):
        state = _professional_state_with_force_time_and_exposure()

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")
        _, raw_text = _rendered_pdf_and_raw_story_text(state, "Ana Lopez", "profe")
        fixed_lower = _repair_mojibake_text(raw_text).lower()

        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("relaciones de perfil / cuadrantes", text)
        self.assertIn("isometricos y force-time avanzado", text)
        self.assertIn("carga interna y tolerancia", text)
        self.assertIn("wellness, disponibilidad y adherencia", text)
        self.assertIn("exposicion del bloque / contenido entrenado", text)
        self.assertIn("estimulos dominantes", text)
        self.assertIn("force@50", text)
        self.assertIn("interpretacion integrada profesional", text)
        self.assertIn("proximos pasos y limitaciones metodologicas", text)
        self.assertNotIn("tc inv", text)
        self.assertIn("back squat producción", fixed_lower)
        self.assertIn("pliometría evaluación", fixed_lower)
        self.assertIn("hang power clean contracción", fixed_lower)

    def test_professional_force_time_uses_single_lectura_practica_and_repairs_accents(self):
        _, normalized_text = _rendered_pdf_and_story_text(_professional_state_with_force_time(), "Ana Lopez", "profe")
        _, raw_text = _rendered_pdf_and_raw_story_text(_professional_state_with_force_time(), "Ana Lopez", "profe")
        fixed_text = report_generator._repair_mojibake_text(raw_text)
        fixed_lower = fixed_text.lower()

        self.assertEqual(normalized_text.count("lectura practica"), 1)
        self.assertIn("producción máxima", fixed_text)
        self.assertIn("fuerza isométrica", fixed_text)
        self.assertIn("posición de IMTP", fixed_text)
        self.assertEqual(fixed_lower.count("rfd exportada descriptiva"), 1)
        self.assertNotIn("produccion maxima", fixed_lower)
        self.assertNotIn("fuerza isometrica", fixed_lower)
        self.assertNotIn("posicion de imtp", fixed_lower)

    def test_exposure_does_not_promise_chart_when_chart_is_unavailable(self):
        state = _weekly_state_without_evaluations()

        _, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertNotIn("distribucion visual del bloque", text)
        self.assertNotIn("el grafico acompana la tabla", text)

    def test_professional_action_plan_order_is_maintain_adjust_monitor_measure(self):
        text = _rendered_story_text(_professional_state_with_force_time(), "Ana Lopez", "profe")
        action_section = text[text.index("proximos pasos y limitaciones metodologicas"):]

        maintain_idx = action_section.index("mantener")
        adjust_idx = action_section.index("ajustar")
        monitor_idx = action_section.index("monitorear")
        measure_idx = action_section.index("medir")

        self.assertLess(maintain_idx, adjust_idx)
        self.assertLess(adjust_idx, monitor_idx)
        self.assertLess(monitor_idx, measure_idx)

    def test_professional_pdf_footer_contains_threshold_and_page_number(self):
        pdf = generate_visual_report_pdf(_professional_state_with_force_time(), "Ana Lopez", "profe")
        extracted_pages = [_normalized_story_text(page) for page in _pdf_extracted_text_pages(pdf)]

        self.assertTrue(extracted_pages)
        self.assertIn("threshold s&c", extracted_pages[0])
        self.assertIn("pagina 1", extracted_pages[0])
        self.assertIn("threshold s&c", extracted_pages[-1])
        self.assertIn(f"pagina {len(extracted_pages)}", extracted_pages[-1])

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

    def test_professional_pdf_without_force_time_keeps_imtp_basic_without_technical_table(self):
        state = _weekly_state_without_evaluations()
        state["jump_df"] = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "CMJ_cm": 31.0,
                    "SJ_cm": 27.0,
                    "DJ_cm": 20.0,
                    "DJ_tc_ms": 212.0,
                    "DRI": 1.24,
                    "IMTP_N": 2380,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-05-01",
                    "CMJ_cm": 32.0,
                    "SJ_cm": 28.0,
                    "DJ_cm": 21.0,
                    "DJ_tc_ms": 205.0,
                    "DRI": 1.31,
                    "IMTP_N": 2450,
                },
            ]
        )

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("isometricos y force-time avanzado", text)
        self.assertIn("peak force", text)
        self.assertIn("2450 n", text)
        self.assertIn("faltan puntos suficientes del perfil de fuerza exportado", text)
        self.assertNotIn("detalle tecnico compacto", text)
        self.assertNotIn("force@50", text)

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

    def test_professional_pdf_repairs_mojibake_text(self):
        broken = "DecisiÃƒÂ³n sugerida con seÃƒÂ±ales del prÃƒÂ³ximo bloque"

        repaired = _repair_mojibake_text(broken)

        self.assertEqual(repaired, "Decisión sugerida con señales del próximo bloque")

    def test_professional_pdf_bytes_do_not_expose_common_mojibake_tokens(self):
        state = {
            "completion_df": None,
            "jump_df": None,
            "rpe_df": None,
            "wellness_df": None,
            "raw_df": None,
            "maxes_df": None,
            "rep_load_df": None,
            "acwr_dict": {},
            "mono_dict": {},
        }

        with patch.object(report_generator, "datetime", FixedProfessionalReportDate):
            pdf = generate_visual_report_pdf(state, "Ana Lopez", "profe")

        text = _pdf_text(pdf)
        for token in ["Ã", "Â", "â", "decisiÃ", "seÃ"]:
            self.assertNotIn(token.lower(), text)

    def test_professional_pdf_visible_story_repairs_dynamic_mojibake(self):
        _, raw_text = _rendered_pdf_and_raw_story_text(_professional_state_with_force_time(), "Ana Lopez", "profe")

        broken_c = chr(195)
        broken_a = chr(194)
        for token in [
            broken_c,
            broken_a,
            f"Est{broken_c}",
            f"fisiol{broken_c}",
            f"biomec{broken_c}",
            f"pr{broken_c}",
            f"exposici{broken_c}",
        ]:
            self.assertNotIn(token, raw_text)
        self.assertIn("Lectura fisiol\u00f3gica", raw_text)
        self.assertIn("Lectura biomec\u00e1nica", raw_text)
        self.assertIn("pr\u00f3ximo", raw_text)
        self.assertIn("exposici\u00f3n", raw_text)

    def test_internal_load_ignores_future_empty_week_after_report_window(self):
        state = _state_with_future_empty_week()

        with patch.object(report_generator, "datetime", LateProfessionalReportDate):
            context = _build_professional_internal_load_context(state, "Ana Lopez")

        self.assertEqual(context["analysis_scope"], "last_complete_week")
        self.assertEqual(context["analysis_week_label"], "27/04/2026 - 03/05/2026")
        self.assertNotIn("18/05/2026", context["analysis_week_label"])
        self.assertEqual(context["sessions_registered"], 2)
        self.assertAlmostEqual(context["last_week_total"], 1200.0)

    def test_wellness_uses_valid_week_and_does_not_show_zero_days_when_records_exist(self):
        state = _state_with_future_empty_week()

        with patch.object(report_generator, "datetime", LateProfessionalReportDate):
            internal = _build_professional_internal_load_context(state, "Ana Lopez")
            wellness = _professional_wellness_context(state, "Ana Lopez")
            payload = _build_professional_wellness_availability_payload(
                state,
                "Ana Lopez",
                {"state": "available"},
                internal,
                wellness,
            )

        rows = dict(payload["rows"])
        self.assertEqual(wellness["analysis_week_label"], "27/04/2026 - 03/05/2026")
        self.assertEqual(rows["DÃ­as con registro"], "3")
        self.assertNotEqual(rows["Wellness score"], PDF_MISSING_TEXT)

    def test_quality_detail_caps_wellness_coverage_over_one_hundred(self):
        detail = _quality_detail_text(pd.Series({"% cobertura sRPE": 88, "% cobertura Wellness": 105}))

        self.assertIn("Wellness 100%", detail)
        self.assertIn("registros adicionales", detail)
        self.assertNotIn("105%", detail)

    def test_load_tolerance_does_not_claim_missing_when_acwr_monotony_strain_exist(self):
        state = {
            "acwr_dict": {
                "Ana Lopez": pd.DataFrame([{"sRPE_diario": 300, "ACWR_EWMA": 0.95, "Zona": "Óptimo"}])
            },
            "mono_dict": {
                "Ana Lopez": pd.DataFrame([{"Monotonia": 1.40, "Strain": 2247}])
            },
        }
        internal = {
            "analysis_scope": "last_complete_week",
            "analysis_week_label": "27/04/2026 - 03/05/2026",
            "weekly_points": [],
        }

        payload = _build_professional_load_tolerance_payload(state, "Ana Lopez", internal)

        self.assertNotIn("Faltan datos para valorar la tolerancia", payload["risk_line"])
        self.assertIn("ACWR", payload["risk_line"])
        rows = dict(payload["rows"])
        self.assertEqual(rows["ACWR EWMA"], "0.95")
        self.assertEqual(rows["Strain"], "2247")

    def test_professional_pdf_without_load_uses_conservative_wellness_and_integrated_language(self):
        state = _professional_state_with_force_time()
        state["rpe_df"] = None
        state["weekly_summaries"]["weekly_load"] = pd.DataFrame()

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("carga interna y tolerancia", text)
        self.assertIn("faltan datos para valorar la tolerancia de carga", text)
        self.assertIn("sin carga interna reciente conviene usarlo solo como contexto parcial", text)
        self.assertNotIn("carga estable + wellness/disponibilidad relativamente estables", text)
        self.assertNotIn("acwr ewma", text)
        self.assertNotIn("zona acwr", text)
        self.assertNotIn("monotonia", text)
        self.assertNotIn("strain", text)

    def test_professional_pdf_without_wellness_uses_missing_block_and_conservative_integrated_language(self):
        state = _professional_state_with_force_time()
        state["wellness_df"] = None
        state["weekly_summaries"]["weekly_wellness"] = pd.DataFrame()

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("wellness, disponibilidad y adherencia", text)
        self.assertIn("faltan datos de wellness/disponibilidad para este periodo", text)
        self.assertIn("falta wellness/disponibilidad reciente; evitar conclusiones fuertes sobre tolerancia del bloque", text)
        self.assertNotIn("wellness/disponibilidad relativamente estables", text)
        self.assertNotIn("dias con registro", text)
        self.assertNotIn("wellness score", text)

    def test_change_payload_interprets_reactive_pattern_and_hides_tc_inv(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0, "SJ_cm": 28.0, "DJ_cm": 24.0, "DJ_RSI": 1.60, "DJ_tc_ms": 220},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 32.0, "SJ_cm": 29.0, "DJ_cm": 25.0, "DJ_RSI": 1.45, "DJ_tc_ms": 240},
                ]
            )
        }

        payload = _build_professional_change_payload(state, "Ana Lopez")
        visible_text = " ".join(
            [
                payload["display_table"].to_string(index=False),
                " ".join(payload["summary_lines"]),
            ]
        )

        self.assertIn("output vertical", visible_text)
        self.assertIn("Eficiencia reactiva", visible_text)
        self.assertIn("tiempo de contacto", visible_text.lower())
        self.assertNotIn("TC inv", visible_text)

    def test_composite_profile_hides_tc_inv_label(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 30.0, "SJ_cm": 28.0, "DJ_cm": 24.0, "DJ_tc_ms": 260, "TC_inv_Z": -1.2},
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 31.0, "SJ_cm": 29.0, "DJ_cm": 25.0, "DJ_tc_ms": 250, "TC_inv_Z": -1.0},
                ]
            )
        }

        payload = _build_professional_composite_profile_payload(state, "Ana Lopez")
        visible_text = " ".join(
            [
                payload["metric_table"].to_string(index=False),
                " ".join(str(value) for value in payload["feedback"].values()),
            ]
        )

        self.assertIn("Tiempo de contacto", visible_text)
        self.assertNotIn("TC inv", visible_text)

    def test_composite_profile_clarifies_contact_time_when_dominant(self):
        feedback = report_generator._professional_sanitize_profile_feedback({"high": "Tiempo de contacto (+1.00)"})
        visible_text = _normalized_story_text(feedback["high"])

        self.assertIn("tiempo de contacto", visible_text)
        self.assertIn("zona favorable", visible_text)
        self.assertNotIn("tc inv", visible_text)
        self.assertNotEqual(visible_text, "tiempo de contacto (+1.00)")

    def test_composite_profile_avoids_missing_readings_when_profile_variables_exist(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-05-01",
                        "SJ_cm": 31.0,
                        "CMJ_cm": 34.0,
                        "DJ_cm": 22.0,
                        "DJ_tc_ms": 210.0,
                        "DRI": 1.42,
                        "IMTP_relPF": 39.5,
                        "SJ_Z": 0.8,
                        "CMJ_Z": 0.7,
                        "DJ_height_Z": -1.0,
                        "DJ_RSI_Z": 0.2,
                        "TC_inv_Z": 0.9,
                        "IMTP_relPF_Z": 0.6,
                    }
                ]
            )
        }

        payload = _build_professional_composite_profile_payload(state, "Ana Lopez")
        feedback = payload["feedback"]
        combined = _normalized_story_text(" ".join(feedback.values()))

        self.assertNotIn("faltan datos", combined)
        self.assertIn("perfil actual", combined)
        self.assertIn("zona favorable", combined)
        self.assertIn("progresion reactiva", combined)

    def test_dj_height_lagging_translates_to_training_language(self):
        composite_payload = {
            "feedback": {
                "low": "DJ height (-1.00)",
                "next_block": "Sostener la cualidad dominante y ajustar la variable mas rezagada en el proximo bloque.",
            }
        }
        action_plan = _build_professional_action_plan_payload(
            {},
            "Ana Lopez",
            evaluation_state="available",
            composite_payload=composite_payload,
            change_payload={"declines": []},
            integrated_payload={},
        )
        integrated = report_generator._build_professional_integrated_decision_payload(
            {},
            "Ana Lopez",
            evaluation_state="available",
            assessment_interval_warning="",
            composite_payload=composite_payload,
            change_payload={"declines": []},
            load_payload={},
            wellness_payload={},
            exposure_payload={},
            training_context={},
        )
        adjust_text = _normalized_story_text(" ".join(action_plan["actions"]["Ajustar"]))
        decision_text = _normalized_story_text(" ".join(integrated["decision_practical"]))

        self.assertNotIn("mejorar dj height", adjust_text)
        self.assertIn("expresion en dj", adjust_text)
        self.assertIn("calidad de contacto", adjust_text)
        self.assertIn("expresion en dj", decision_text)
        self.assertIn("stiffness", decision_text)

    def test_professional_pdf_uses_dashboard_composite_zscore_source(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-05-01",
                        "SJ_cm": 31.0,
                        "CMJ_cm": 35.0,
                        "DJ_tc_ms": 210.0,
                        "DRI": 1.29,
                        "EUR": 1.129,
                        "IMTP_relPF": 39.5,
                        "SJ_Z": -0.20,
                        "CMJ_Z": 0.30,
                        "DJ_RSI_Z": 0.45,
                        "DJtc_Z": 0.80,
                        "EUR_Z": 0.25,
                        "IMTP_Z": 0.60,
                    }
                ]
            )
        }

        dashboard_row, _ = build_composite_profile_snapshot(state["jump_df"])
        dashboard_table = build_composite_profile_metric_table(dashboard_row).set_index("Variable")
        pdf_table = _build_professional_composite_profile_payload(state, "Ana Lopez")["metric_table"].set_index("Variable")
        dashboard_z = pd.to_numeric(dashboard_table["Z-score"], errors="coerce")
        pdf_z = pd.to_numeric(pdf_table["Z-score"], errors="coerce")

        self.assertAlmostEqual(pdf_z["DRI"], dashboard_z["DRI"])
        self.assertAlmostEqual(pdf_z["Tiempo de contacto"], dashboard_z["Tiempo de contacto"])
        self.assertFalse(pd.isna(pdf_z["IMTP"]))
        self.assertIn("Tiempo de contacto", pdf_table.index)
        self.assertNotIn("TC inv", " ".join(pdf_table.index.astype(str)))

    def test_composite_profile_handles_absent_lagging_variable_professionally(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-05-01",
                        "CMJ_cm": 31.0,
                        "SJ_cm": 29.0,
                        "DJ_cm": 25.0,
                        "DJ_tc_ms": 240,
                        "DRI": 1.45,
                        "EUR": 1.07,
                    },
                ]
            )
        }

        feedback_lines = [
            "Alto: sin variables > 0.5.",
            "Bajo: sin variables < -0.5.",
            "Fisiologico: Perfil equilibrado en todos los indices evaluados.",
            "Biomecanico: Sin deficits marcados en los tests disponibles.",
            "Proximo bloque: Continuar progresion planificada.",
        ]
        with patch.object(report_generator, "build_jump_feedback_lines", return_value=feedback_lines):
            composite = _build_professional_composite_profile_payload(state, "Ana Lopez")
        action_plan = _build_professional_action_plan_payload(
            state,
            "Ana Lopez",
            evaluation_state="partial",
            composite_payload=composite,
            change_payload={"declines": []},
            integrated_payload={},
        )
        visible_text = _normalized_story_text(
            " ".join(
                [
                    str(composite.get("summary_line", "")),
                    " ".join(str(value) for value in composite.get("feedback", {}).values()),
                    " ".join(item for items in action_plan["actions"].values() for item in items),
                ]
            )
        )

        self.assertIn("no aparece una variable claramente rezagada", visible_text)
        self.assertIn("mantener el perfil actual", visible_text)
        self.assertIn("monitorear si alguna variable empieza a separarse", visible_text)
        self.assertNotIn("sin variables < -0.5", visible_text)
        self.assertNotIn("mejorar sin variables", visible_text)

    def test_composite_profile_z_score_cells_are_explicit_when_missing(self):
        state = {
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 31.0, "SJ_cm": 29.0},
                ]
            )
        }

        payload = _build_professional_composite_profile_payload(state, "Ana Lopez")
        table = payload["metric_table"]

        self.assertIn("Z-score", table.columns)
        self.assertTrue(table["Z-score"].astype(str).str.strip().ne("").all())
        self.assertIn("\u2014", set(table["Z-score"].astype(str)))

    def test_exposure_payload_does_not_report_missing_low_stimuli_when_data_exists(self):
        state = {
            "prepared_raw_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-28",
                        "Exercise": "Back Squat",
                        "stimulus_category": "strength_loaded",
                        "Volume_Load_kg": 2400,
                        "Contacts": 0,
                        "Exposures": 1,
                        "is_invalid": False,
                        "is_untagged": False,
                    },
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-30",
                        "Exercise": "Drop Jump",
                        "stimulus_category": "plyo_jump",
                        "Volume_Load_kg": 0,
                        "Contacts": 45,
                        "Exposures": 1,
                        "is_invalid": False,
                        "is_untagged": False,
                    },
                ]
            )
        }

        payload = _build_professional_exposure_payload(state, "Ana Lopez")

        self.assertNotEqual(payload["state"], "missing")
        self.assertTrue(payload["dominant"])
        self.assertNotIn("Faltan datos", payload["summary_line"])
        self.assertNotIn("Faltan datos", _professional_join_labels(payload["low_or_absent"], fallback=""))
        self.assertNotIn("Pliometria", payload["table"].to_string(index=False))
        self.assertIn("Sesiones", payload["table"].columns)

    def test_professional_pdf_exposure_omits_missing_low_stimuli_line_when_undetermined(self):
        state = {
            "prepared_raw_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-28",
                        "Exercise": "Back Squat",
                        "stimulus_category": "strength_loaded",
                        "Volume_Load_kg": 2400,
                        "Contacts": 0,
                        "Exposures": 1,
                        "is_invalid": False,
                        "is_untagged": False,
                    },
                ]
            )
        }

        text = _rendered_story_text(state, "Ana Lopez", "profe")

        self.assertNotIn("estimulos bajos o ausentes: faltan datos", text)
        self.assertNotIn("sesione s", text)

    def test_professional_pdf_exposure_uses_relative_lowest_phrase_for_positive_dose(self):
        state = {
            "prepared_raw_df": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-28",
                        "Exercise": "Back Squat",
                        "stimulus_category": "strength_loaded",
                        "Volume_Load_kg": 2400,
                        "Contacts": 0,
                        "Exposures": 1,
                        "is_invalid": False,
                        "is_untagged": False,
                    },
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-30",
                        "Exercise": "Hang Power Clean",
                        "stimulus_category": "olympic_derivatives",
                        "Volume_Load_kg": 0,
                        "Contacts": 0,
                        "Exposures": 1,
                        "is_invalid": False,
                        "is_untagged": False,
                    },
                ]
            )
        }

        text = _rendered_story_text(state, "Ana Lopez", "profe")

        self.assertIn("menor exposicion relativa: derivados olimpicos", text)
        self.assertNotIn("estimulos bajos o ausentes", text)

    def test_professional_pdf_without_exposure_uses_compact_missing_block_and_conservative_interpretation(self):
        state = _professional_state_with_force_time()
        state["prepared_raw_df"] = pd.DataFrame()
        state["raw_df"] = None

        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe")

        self.assertLessEqual(_pdf_page_count(pdf), 10)
        self.assertIn("exposicion del bloque / contenido entrenado", text)
        self.assertIn("faltan raw workouts suficientes para resumir la exposicion del bloque", text)
        self.assertIn("no reemplazan la exposicion por estimulos", text)
        self.assertIn("falta exposicion por estimulos suficiente", text)
        self.assertNotIn("estimulos dominantes", text)
        self.assertNotIn("distribucion visual del bloque", text)
        self.assertNotIn("el grafico acompana la tabla", text)

    def test_action_plan_is_concrete_and_not_repetitive(self):
        payload = _build_professional_action_plan_payload(
            {},
            "Ana Lopez",
            evaluation_state="available",
            composite_payload={"feedback": {"low": "TC inv (-1.20)", "next_block": "Mejorar calidad de contacto/reactividad."}},
            change_payload={"declines": ["DJ RSI", "Tiempo de contacto"]},
            integrated_payload={},
        )
        actions = payload["actions"]

        self.assertTrue(any("calidad de contacto" in item for item in actions["Ajustar"]))
        self.assertTrue(any("DJ RSI" in item and "tiempo de contacto" in item for item in actions["Monitorear"]))
        self.assertTrue(any("6-8 semanas" in item for item in actions["Medir"]))
        for section_actions in actions.values():
            self.assertEqual(len(section_actions), len(set(section_actions)))


if __name__ == "__main__":
    unittest.main()
