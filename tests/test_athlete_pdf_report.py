from __future__ import annotations

from datetime import datetime as real_datetime
from io import BytesIO
import re
import unicodedata
import unittest
from unittest.mock import patch

import pandas as pd
from pypdf import PdfReader

import modules.report_generator as report_generator
from modules.report_generator import (
    _athlete_profile_interpretation,
    _athlete_load_status_lines,
    _athlete_metric_explanation_rows,
    _build_pdf_neuromuscular_profile_payload,
    generate_visual_report_pdf,
)
from modules.report_force_time import build_force_time_report_payload


def _pdf_page_count(pdf: bytes) -> int:
    return len(PdfReader(BytesIO(pdf)).pages)


def _pdf_extracted_text_pages(pdf: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf))
    return [(page.extract_text() or "") for page in reader.pages]


def _normalized_story_text(text: str) -> str:
    repaired = report_generator._repair_mojibake_text(text)
    return unicodedata.normalize("NFD", repaired).encode("ascii", "ignore").decode("ascii").lower()


def _normalized_pdf_pages(pdf: bytes) -> list[str]:
    return [_normalized_story_text(page) for page in _pdf_extracted_text_pages(pdf)]


def _collapsed_normalized_pdf_text(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(_normalized_pdf_pages(pdf))).strip()


def _structured_neuromuscular_stub(**overrides) -> dict[str, object]:
    base = {
        "profile_code": "A",
        "profile_label": "Patron A - Fuerza/propulsion con SSC rapido limitado",
        "confidence": "high",
        "phys": "Buena capacidad concentrica con rezago reactivo rapido.",
        "bio": "Menor expresion del SSC rapido en contactos breves.",
        "train": "Priorizar stiffness, contacto y progresion reactiva sin perder la base actual.",
        "summary_short": "Buen perfil concentrico con rezago reactivo rapido.",
        "summary_athlete": "Mensaje atleta custom para validar la ruta estructurada.",
        "summary_client": "Mensaje cliente custom.",
        "summary_professional": "Mensaje profesional custom.",
        "metrics": {
            "SJ_cm": {
                "label": "SJ",
                "value": 32.0,
                "unit": "cm",
                "z_score": 0.80,
                "direction": "higher_is_better",
                "semaphore": "Amarillo",
                "value_col": "SJ_cm",
                "z_col": "SJ_Z",
                "source_date": "-",
                "available": True,
            },
            "DJ_RSI": {
                "label": "DJ RSI",
                "value": 1.10,
                "unit": "m/s",
                "z_score": -0.80,
                "direction": "higher_is_better",
                "semaphore": "Naranja",
                "value_col": "DJ_RSI",
                "z_col": "DJ_RSI_Z",
                "source_date": "-",
                "available": True,
            },
        },
        "flags": [],
        "evidence": ["SJ_Z alto", "DJ_RSI_Z bajo"],
        "kpi_to_track": ["DJ_RSI", "DJ_tc_ms", "DRI"],
    }
    base.update(overrides)
    return base


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
                    "DJ_drop_height_cm": 47.65,
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
                "DJ_drop_height_cm": 47.65,
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


def _athlete_partial_report_state() -> dict[str, object]:
    return {
        "completion_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-05-01", "Assigned": 4, "Completed": 3, "Pct": 75.0}]),
        "rpe_df": None,
        "wellness_df": None,
        "jump_df": None,
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {},
        "mono_dict": {},
    }


def _athlete_low_wellness_report_state() -> dict[str, object]:
    state = _athlete_report_state()
    state["wellness_df"] = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "Sueno_hs": 5.8, "Estres": 8, "Dolor": 7, "Wellness_Score": 2.3},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Sueno_hs": 5.9, "Estres": 8, "Dolor": 6, "Wellness_Score": 2.4},
            {"Athlete": "Ana Lopez", "Date": "2026-05-01", "Sueno_hs": 5.7, "Estres": 9, "Dolor": 7, "Wellness_Score": 2.2},
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 5.6, "Estres": 9, "Dolor": 8, "Wellness_Score": 2.1},
        ]
    )
    return state


def _athlete_pattern_e_report_state() -> dict[str, object]:
    state = _athlete_report_state()
    state["jump_df"] = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Date": "2026-05-01",
                "CMJ_cm": 29.0,
                "SJ_cm": 31.0,
                "DJ_drop_height_cm": 30.0,
                "DJ_cm": 24.0,
                "DJ_RSI": 1.10,
                "DJ_tc_ms": 220.0,
                "IMTP_N": 1800.0,
                "EUR": 0.95,
            }
        ]
    )
    return state


class AthletePdfReportTest(unittest.TestCase):
    def test_athlete_pdf_applies_threshold_visual_system_and_target_sections(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        self.assertEqual(_pdf_page_count(pdf), 6)

        extracted_pages = _normalized_pdf_pages(pdf)
        self.assertEqual(len(extracted_pages), 6)
        for index, page_text in enumerate(extracted_pages, start=1):
            self.assertIn("threshold s&c", page_text)
            self.assertIn(f"pagina {index}", page_text)

        expected_titles = [
            "reporte individual para atleta",
            "perfil neuromuscular",
            "fuerza e imtp",
            "carga reciente",
            "bienestar y adherencia",
            "fortalezas y proximos pasos",
        ]
        for page_text, title in zip(extracted_pages, expected_titles):
            self.assertIn(title, page_text)

    def test_athlete_pdf_keeps_athlete_language_and_avoids_professional_overreach(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = _collapsed_normalized_pdf_text(pdf)
        self.assertIn("que significa para vos", joined)
        self.assertIn("que vamos a priorizar", joined)
        self.assertIn("como venis tolerando el entrenamiento", joined)
        self.assertIn("proxima medicion o revision", joined)
        self.assertNotIn("sostener perfil", joined)
        self.assertNotIn("relaciones de perfil / cuadrantes", joined)
        self.assertNotIn("cuadrante", joined)
        self.assertNotIn("interpretacion integrada profesional", joined)
        self.assertNotIn("tc inv", joined)

    def test_athlete_pdf_force_time_page_keeps_simple_language_and_accents(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state_with_force_time(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        visible_text = "\n".join(_pdf_extracted_text_pages(pdf))
        normalized = _normalized_story_text(visible_text)
        collapsed = re.sub(r"\s+", " ", visible_text).strip()

        self.assertIn("Fuerza e IMTP", visible_text)
        self.assertIn("Fuerza máxima", visible_text)
        self.assertIn("Asimetría", visible_text)
        self.assertIn("posición fija", visible_text)
        self.assertIn("La RFD ayuda a ver qué tan rápido aparece la fuerza, pero la usamos con cautela cuando todavía no tenemos una referencia propia de confiabilidad.", collapsed)
        self.assertNotIn("TC inv", visible_text)
        self.assertNotIn("TE disponible", visible_text)
        self.assertNotIn("Force@100", visible_text)
        self.assertNotIn("evaluacion", visible_text)
        self.assertNotIn("adquisicion", visible_text)
        self.assertNotIn("Asimetria", visible_text)
        self.assertNotIn("produccion", visible_text)
        self.assertNotIn("isometrica", visible_text)
        self.assertNotIn("posicion", visible_text)
        self.assertNotIn("cuadrantes", normalized)

    def test_athlete_pdf_chart_fallback_copy_stays_coherent_when_render_fails(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state_with_force_time(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = _collapsed_normalized_pdf_text(pdf)

        self.assertIn("hoy no se pudo renderizar el grafico de carga, pero la lectura reciente sigue disponible", joined)
        self.assertIn("hoy no se pudo renderizar este grafico, pero la lectura de bienestar y adherencia sigue disponible", joined)
        self.assertIn("hoy no se pudo renderizar el radar, pero la lectura del perfil sigue disponible", joined)
        self.assertNotIn("faltan datos de carga interna para mostrar este grafico reciente", joined)
        self.assertNotIn("faltan datos de evaluacion para mostrar el radar neuromuscular", joined)

    def test_athlete_pdf_handles_missing_data_without_empty_pages(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_partial_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        extracted_pages = _normalized_pdf_pages(pdf)
        self.assertEqual(len(extracted_pages), 6)
        self.assertTrue(all(len(page.strip()) > 40 for page in extracted_pages))
        joined = re.sub(r"\s+", " ", " ".join(extracted_pages)).strip()
        self.assertIn("pendiente", joined)
        self.assertIn("todavia no registrado", joined)
        self.assertIn("todavia faltan registros recientes de bienestar para entender mejor como venis recuperando", joined)
        self.assertNotIn("sin datos", joined)
        self.assertNotIn("tc inv", joined)

    def test_athlete_pdf_when_wellness_is_acceptable_does_not_claim_recovery_is_low(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = _collapsed_normalized_pdf_text(pdf)
        self.assertIn("el bienestar reciente acompana, pero conviene seguir registrandolo para confirmar la tendencia", joined)
        self.assertNotIn("la recuperacion percibida viene baja y requiere seguimiento cercano", joined)

    def test_athlete_pdf_when_wellness_is_low_can_mark_close_follow_up(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_low_wellness_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = _collapsed_normalized_pdf_text(pdf)
        self.assertIn("el bienestar reciente viene bajo y conviene cruzarlo de cerca con la carga, el sueno, el estres y el dolor", joined)
        self.assertIn("la recuperacion reciente merece seguimiento cercano junto con sueno, estres y dolor", joined)

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

    def test_athlete_profile_interpretation_can_use_structured_neuromuscular_payload(self):
        focus_row = pd.Series(
            {
                "CMJ cm": 34.0,
                "DRI": 1.40,
                "IMTP N": 1800.0,
                "EUR (ratio)": 1.06,
                "Perfil NM": "Reactivo",
            }
        )
        payload = _build_pdf_neuromuscular_profile_payload(
            pd.Series(
                {
                    "SJ_cm": 32.0,
                    "CMJ_cm": 34.0,
                    "DJ_cm": 25.0,
                    "DJ_RSI": 1.10,
                    "DJ_tc_ms": 210.0,
                    "IMTP_relPF": 38.0,
                    "EUR": 1.06,
                    "SJ_Z": 0.80,
                    "CMJ_Z": 0.10,
                    "DJ_height_Z": -0.20,
                    "DJ_RSI_Z": -0.80,
                    "TC_inv_Z": 0.20,
                    "IMTP_relPF_Z": 0.30,
                }
            ),
            context={"audience": "atleta"},
        )

        reading = _athlete_profile_interpretation(focus_row, neuromuscular_profile=payload)

        self.assertEqual(payload["profile_code"], "A")
        self.assertIn("perfil actual", _normalized_story_text(reading["what"]))
        self.assertIn(_normalized_story_text(payload["summary_athlete"]), _normalized_story_text(reading["meaning"]))
        self.assertIn(_normalized_story_text(payload["training_priority_detailed"]), _normalized_story_text(reading["priority"]))

    def test_same_row_keeps_same_profile_code_for_profe_atleta_and_cliente(self):
        row = pd.Series(
            {
                "SJ_cm": 32.0,
                "CMJ_cm": 34.0,
                "DJ_cm": 25.0,
                "DJ_RSI": 1.10,
                "DJ_tc_ms": 210.0,
                "IMTP_relPF": 38.0,
                "EUR": 1.06,
                "SJ_Z": 0.80,
                "CMJ_Z": 0.10,
                "DJ_height_Z": -0.20,
                "DJ_RSI_Z": -0.80,
                "TC_inv_Z": 0.20,
                "IMTP_relPF_Z": 0.30,
            }
        )

        codes = {
            _build_pdf_neuromuscular_profile_payload(row, context={"audience": "profe"})["profile_code"],
            _build_pdf_neuromuscular_profile_payload(row, context={"audience": "atleta"})["profile_code"],
            _build_pdf_neuromuscular_profile_payload(row, context={"audience": "cliente"})["profile_code"],
        }

        self.assertEqual(codes, {"A"})

    def test_athlete_profile_payload_handles_missing_imtp_without_keyerror(self):
        focus_row = pd.Series({"CMJ cm": 32.0, "DRI": 1.20, "EUR (ratio)": 1.04, "Perfil NM": "Mixto"})
        payload = _build_pdf_neuromuscular_profile_payload(
            pd.Series({"SJ_cm": 30.0, "CMJ_cm": 32.0, "DJ_cm": 24.0, "DJ_RSI": 1.05, "DJ_tc_ms": 220.0, "EUR": 1.04}),
            context={"audience": "atleta"},
        )

        reading = _athlete_profile_interpretation(focus_row, neuromuscular_profile=payload)

        self.assertIn("missing_imtp", payload["flags"])
        self.assertTrue(reading["meaning"])
        self.assertTrue(reading["priority"])

    def test_athlete_profile_payload_handles_missing_dj_without_keyerror(self):
        focus_row = pd.Series({"CMJ cm": 32.0, "IMTP N": 1800.0, "EUR (ratio)": 1.04, "Perfil NM": "Mixto"})
        payload = _build_pdf_neuromuscular_profile_payload(
            pd.Series({"SJ_cm": 30.0, "CMJ_cm": 32.0, "IMTP_relPF": 38.0, "EUR": 1.04, "IMTP_relPF_Z": 0.10}),
            context={"audience": "atleta"},
        )

        reading = _athlete_profile_interpretation(focus_row, neuromuscular_profile=payload)

        self.assertIn("missing_dj", payload["flags"])
        self.assertTrue(reading["meaning"])
        self.assertTrue(reading["priority"])

    def test_athlete_pdf_renders_pattern_e_as_interpretative_alert(self):
        with patch.object(report_generator, "datetime", FixedAthleteReportDate):
            pdf = generate_visual_report_pdf(_athlete_pattern_e_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = _collapsed_normalized_pdf_text(pdf)
        self.assertIn("contramovimiento", joined)

    def test_athlete_pdf_uses_structured_summary_even_if_wording_changes(self):
        custom_summary = "Lectura atleta custom que cambia sin romper la estructura."
        with patch.object(
            report_generator,
            "build_neuromuscular_profile_result",
            return_value=_structured_neuromuscular_stub(summary_athlete=custom_summary),
        ):
            with patch.object(report_generator, "datetime", FixedAthleteReportDate):
                pdf = generate_visual_report_pdf(_athlete_report_state(), "Ana Lopez", "atleta")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        self.assertIn(_normalized_story_text(custom_summary), _collapsed_normalized_pdf_text(pdf))

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
