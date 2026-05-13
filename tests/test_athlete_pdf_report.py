from __future__ import annotations

from datetime import datetime as real_datetime
import re
import unittest
from unittest.mock import patch

import pandas as pd

import modules.report_generator as report_generator
from modules.report_generator import (
    _athlete_load_status_lines,
    _athlete_metric_explanation_rows,
    generate_visual_report_pdf,
)
from modules.report_force_time import build_force_time_report_payload


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _pdf_text(pdf: bytes) -> str:
    return pdf.decode("latin-1", errors="ignore").lower()


class FixedAthleteReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


def _athlete_report_state() -> dict[str, object]:
    return {
        "rpe_df": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-28", "sRPE": 320},
                {"Athlete": "Ana Lopez", "Date": "2026-04-30", "sRPE": 340},
                {"Athlete": "Ana Lopez", "Date": "2026-05-04", "sRPE": 300},
                {"Athlete": "Ana Lopez", "Date": "2026-05-05", "sRPE": 300},
            ]
        ),
        "wellness_df": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-28", "Sueno_hs": 7.2, "Estres": 3, "Dolor": 2, "Wellness_Score": 8.0},
                {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Sueno_hs": 7.0, "Estres": 4, "Dolor": 2, "Wellness_Score": 7.8},
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "Sueno_hs": 6.8, "Estres": 4, "Dolor": 3, "Wellness_Score": 7.2},
                {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 6.6, "Estres": 5, "Dolor": 3, "Wellness_Score": 6.8},
            ]
        ),
        "completion_df": pd.DataFrame(
            [{"Athlete": "Ana Lopez", "Date": "2026-04-30", "Assigned": 10, "Completed": 9, "Pct": 90}]
        ),
        "jump_df": pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "CMJ_cm": 32,
                    "SJ_cm": 29,
                    "DJ_cm": 25,
                    "DJ_tc_ms": 230,
                    "DRI": 1.4,
                    "IMTP_N": 1800,
                    "EUR": 1.1,
                    "NM_Profile": "Reactivo",
                }
            ]
        ),
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {
            "Ana Lopez": pd.DataFrame(
                [
                    {"Date": "2026-04-28", "sRPE_diario": 320, "ACWR_EWMA": 1.05, "Zona": "Optimo"},
                    {"Date": "2026-04-30", "sRPE_diario": 340, "ACWR_EWMA": 1.10, "Zona": "Optimo"},
                    {"Date": "2026-05-04", "sRPE_diario": 300, "ACWR_EWMA": 0.95, "Zona": "Optimo"},
                    {"Date": "2026-05-05", "sRPE_diario": 300, "ACWR_EWMA": 0.98, "Zona": "Optimo"},
                ]
            )
        },
        "mono_dict": {
            "Ana Lopez": pd.DataFrame([{"Semana": "2026-04-27", "Carga_Semanal": 660, "Monotonia": 1.3, "Strain": 858}])
        },
    }


def _athlete_report_state_with_force_time() -> dict[str, object]:
    state = _athlete_report_state()
    state["jump_df"] = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Date": "2026-04-01",
                "CMJ_cm": 32,
                "SJ_cm": 29,
                "DJ_cm": 25,
                "DJ_tc_ms": 230,
                "DRI": 1.4,
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
                "EUR": 1.1,
                "NM_Profile": "Reactivo",
            }
        ]
    )
    return state


class AthletePdfReportTest(unittest.TestCase):
    def test_athlete_pdf_stays_compact_at_four_pages_or_less(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 4)

    def test_athlete_pdf_survives_missing_evaluations_load_and_wellness(self):
        state = {
            "completion_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-05-01", "Assigned": 4, "Completed": 3, "Pct": 75}]),
            "rpe_df": None,
            "wellness_df": None,
            "jump_df": None,
            "raw_df": None,
            "maxes_df": None,
            "rep_load_df": None,
            "acwr_dict": {},
            "mono_dict": {},
        }

        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(state, "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 4)

    def test_athlete_load_copy_marks_partial_week_without_closed_week_comparison(self):
        row = pd.Series({"ACWR EWMA": 0.98, "Zona": "Optimo", "Monotonia": 1.3})
        internal_load = {
            "analysis_scope": "current_week_partial",
            "current_week_total": 780,
            "current_week_sessions": 2,
            "weekly_change_pct": -52.0,
        }

        joined = " ".join(_athlete_load_status_lines(row, internal_load))

        self.assertIn("Semana en curso / datos parciales", joined)
        self.assertIn("No compararlo todavía", joined)
        self.assertNotIn("-52.0%", joined)

    def test_athlete_metric_definitions_translate_technical_terms(self):
        row = pd.Series({"ACWR EWMA": 1.1, "DRI": 1.4, "IMTP N": 1800, "EUR (ratio)": 1.1, "Monotonia": 1.3})

        definitions = dict(_athlete_metric_explanation_rows(row))

        self.assertIn("relación entre carga reciente y carga habitual", definitions["ACWR EWMA"])
        self.assertIn("Drop Jump", definitions["DRI"])
        self.assertIn("salto con contramovimiento", definitions["EUR"])


    def test_athlete_pdf_with_imtp_force_time_generates_optional_block_without_forbidden_language(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            with patch.object(report_generator, "draw_force_time_test_block", wraps=report_generator.draw_force_time_test_block) as mocked_draw:
                pdf = generate_visual_report_pdf(_athlete_report_state_with_force_time(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        self.assertEqual(mocked_draw.call_count, 1)

    def test_athlete_pdf_without_imtp_force_time_skips_optional_block(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            with patch.object(report_generator, "draw_force_time_test_block", wraps=report_generator.draw_force_time_test_block) as mocked_draw:
                pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        self.assertEqual(mocked_draw.call_count, 0)

    def test_force_time_payload_for_athlete_stays_descriptive(self):
        payload = build_force_time_report_payload(
            _athlete_report_state_with_force_time()["jump_df"].iloc[0],
            report_type="athlete",
        )
        combined = " ".join(str(value) for value in payload["interpretation"].values()).lower()

        self.assertTrue(payload["has_valid_force_time"])
        self.assertIn("rfd", combined)
        self.assertIn("cautela", combined)
        self.assertNotIn("curva cruda", combined)
        self.assertNotIn("raw curve", combined)
        self.assertNotIn("riesgo de lesi", combined)
        self.assertNotIn("diagn", combined)
        self.assertNotIn("rfd 200", combined)


if __name__ == "__main__":
    unittest.main()
