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
from modules.report_generator import _build_pdf_neuromuscular_profile_payload, generate_visual_report_pdf


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _pdf_extracted_text_pages(pdf: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf))
    return [(page.extract_text() or "") for page in reader.pages]


def _normalized_story_text(text: str) -> str:
    repaired = report_generator._repair_mojibake_text(text)
    return unicodedata.normalize("NFD", repaired).encode("ascii", "ignore").decode("ascii").lower()


def _normalized_pdf_pages(pdf: bytes) -> list[str]:
    return [_normalized_story_text(page) for page in _pdf_extracted_text_pages(pdf)]


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
        lines: list[str] = []
        for row in getattr(flowable, "_cellvalues", []) or []:
            lines.extend(_story_plain_text(row))
        return lines
    return []


def _rendered_pdf_and_story_text(
    state: dict[str, object],
    athlete: str,
) -> tuple[bytes, str]:
    from reportlab.platypus import SimpleDocTemplate

    captured: dict[str, object] = {}
    original_build = SimpleDocTemplate.build

    def capture_build(self, flowables, *args, **kwargs):
        captured["story"] = list(flowables)
        return original_build(self, flowables, *args, **kwargs)

    with patch.object(report_generator, "datetime", FixedClientReportDate):
        with patch.object(SimpleDocTemplate, "build", capture_build):
            pdf = generate_visual_report_pdf(state, athlete, "cliente")

    assert pdf is not None
    story_text = _normalized_story_text(" ".join(_story_plain_text(captured.get("story", []))))
    return pdf, story_text


def _structured_neuromuscular_stub(**overrides) -> dict[str, object]:
    base = {
        "profile_code": "A",
        "profile_label": "Patron A - Fuerza/propulsion con SSC rapido limitado",
        "confidence": "high",
        "phys": "Buena capacidad concentrica con rezago reactivo rapido.",
        "bio": "Menor expresion del SSC rapido en contactos breves.",
        "train": "Priorizar stiffness, contacto y progresion reactiva sin perder la base actual.",
        "summary_short": "Buen perfil concentrico con rezago reactivo rapido.",
        "summary_athlete": "Mensaje atleta custom.",
        "summary_client": "Mensaje cliente custom para validar la ruta estructurada.",
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


class FixedClientReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


def _client_report_state() -> dict[str, object]:
    return {
        "rpe_df": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-28", "sRPE": 320, "RPE": 6, "Duration_min": 53},
                {"Athlete": "Ana Lopez", "Date": "2026-04-30", "sRPE": 340, "RPE": 7, "Duration_min": 49},
                {"Athlete": "Ana Lopez", "Date": "2026-05-04", "sRPE": 300, "RPE": 6, "Duration_min": 50},
                {"Athlete": "Ana Lopez", "Date": "2026-05-05", "sRPE": 300, "RPE": 7, "Duration_min": 43},
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
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-23", "Assigned": 8, "Completed": 7, "Pct": 87.5},
                {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Assigned": 10, "Completed": 9, "Pct": 90.0},
                {"Athlete": "Ana Lopez", "Date": "2026-05-05", "Assigned": 6, "Completed": 5, "Pct": 83.3},
            ]
        ),
        "jump_df": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-03-15", "CMJ_cm": 30, "SJ_cm": 28, "DJ_drop_height_cm": 46.43, "DJ_cm": 24, "DJ_tc_ms": 235, "DRI": 1.30, "EUR": 1.08, "IMTP_N": 1750, "NM_Profile": "Mixto"},
                {"Athlete": "Ana Lopez", "Date": "2026-05-02", "CMJ_cm": 32, "SJ_cm": 29, "DJ_drop_height_cm": 45.37, "DJ_cm": 25, "DJ_tc_ms": 228, "DRI": 1.38, "EUR": 1.10, "IMTP_N": 1800, "NM_Profile": "Reactivo"},
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
            "Ana Lopez": pd.DataFrame(
                [{"Semana": "2026-04-27", "Carga_Semanal": 660, "Monotonia": 1.3, "Strain": 858}]
            )
        },
    }


def _client_partial_report_state() -> dict[str, object]:
    return {
        "completion_df": pd.DataFrame(
            [{"Athlete": "Ana Lopez", "Date": "2026-05-01", "Assigned": 4, "Completed": 3, "Pct": 75.0}]
        ),
        "rpe_df": None,
        "wellness_df": None,
        "jump_df": None,
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {},
        "mono_dict": {},
    }


def _client_partial_low_wellness_report_state() -> dict[str, object]:
    state = _client_partial_report_state()
    state["wellness_df"] = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-05-03", "Sueno_hs": 5.8, "Estres": 8, "Dolor": 7, "Wellness_Score": 2.2},
            {"Athlete": "Ana Lopez", "Date": "2026-05-05", "Sueno_hs": 5.6, "Estres": 9, "Dolor": 8, "Wellness_Score": 2.0},
        ]
    )
    return state


def _client_pattern_e_report_state() -> dict[str, object]:
    state = _client_report_state()
    state["jump_df"] = pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Date": "2026-05-02",
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


def _client_attention_recovery_report_state() -> dict[str, object]:
    state = _client_report_state()
    state["wellness_df"] = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-04-28", "Sueno_hs": 7.0, "Estres": 8, "Dolor": 7, "Wellness_Score": 2.8},
            {"Athlete": "Ana Lopez", "Date": "2026-04-30", "Sueno_hs": 7.1, "Estres": 8, "Dolor": 7, "Wellness_Score": 2.7},
            {"Athlete": "Ana Lopez", "Date": "2026-05-01", "Sueno_hs": 6.9, "Estres": 9, "Dolor": 8, "Wellness_Score": 2.6},
            {"Athlete": "Ana Lopez", "Date": "2026-05-04", "Sueno_hs": 7.0, "Estres": 8, "Dolor": 7, "Wellness_Score": 2.7},
        ]
    )
    return state


def _client_precaution_load_report_state() -> dict[str, object]:
    state = _client_report_state()
    state["acwr_dict"] = {
        "Ana Lopez": pd.DataFrame(
            [
                {"Date": "2026-04-28", "sRPE_diario": 320, "ACWR_EWMA": 1.18, "Zona": "Optimo"},
                {"Date": "2026-04-30", "sRPE_diario": 340, "ACWR_EWMA": 1.24, "Zona": "Optimo"},
                {"Date": "2026-05-04", "sRPE_diario": 300, "ACWR_EWMA": 1.36, "Zona": "Precaucion"},
                {"Date": "2026-05-05", "sRPE_diario": 300, "ACWR_EWMA": 1.39, "Zona": "Precaucion"},
            ]
        )
    }
    return state


class ClientPdfReportTest(unittest.TestCase):
    def test_client_pdf_applies_threshold_visual_system_and_target_sections(self):
        with patch.object(report_generator, "datetime", FixedClientReportDate):
            pdf = generate_visual_report_pdf(_client_report_state(), "Ana Lopez", "cliente")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        self.assertLessEqual(_pdf_page_count(pdf), 5)

        extracted_pages = _normalized_pdf_pages(pdf)
        self.assertEqual(len(extracted_pages), 5)
        self.assertIn("threshold s&c", extracted_pages[0])
        self.assertIn("pagina 1", extracted_pages[0])
        self.assertIn("threshold s&c", extracted_pages[-1])
        self.assertIn("pagina 5", extracted_pages[-1])
        self.assertTrue(all(page.count("threshold s&c") == 1 for page in extracted_pages))

        expected_titles = [
            "reporte de progreso",
            "estado actual y progreso",
            "carga y constancia",
            "bienestar y recuperacion",
            "proximos pasos",
        ]
        for page_text, title in zip(extracted_pages, expected_titles):
            self.assertIn(title, page_text)

    def test_client_pdf_keeps_simple_language_and_avoids_technical_terms(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_report_state(), "Ana Lopez")
        joined_pages = " ".join(_normalized_pdf_pages(pdf))

        self.assertIsNotNone(pdf)
        self.assertIn("carga actual", story_text)
        self.assertIn("estado de carga", story_text)
        self.assertIn("foco actual", story_text)
        self.assertIn("que vamos a priorizar", story_text)
        self.assertIn("que vamos a cuidar", story_text)
        self.assertIn("volver a medir", story_text)
        self.assertNotIn("como venis hoy", story_text)
        self.assertNotIn("estado actual optimo", joined_pages)
        self.assertLessEqual(story_text.count("proximo foco"), 1)
        self.assertNotIn("perfil actual compuesto", story_text)
        self.assertNotIn("z-score", story_text)
        self.assertNotIn("force-time", story_text)
        self.assertNotIn("rfd", story_text)
        self.assertNotIn("cuadrante", story_text)
        self.assertNotIn("imtp", story_text)
        self.assertNotIn("tc inv", story_text)

    def test_client_pdf_handles_missing_data_with_friendly_copy_and_without_empty_pages(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_partial_report_state(), "Ana Lopez")
        page_five = _normalized_pdf_pages(pdf)[-1]

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 5)
        extracted_pages = _normalized_pdf_pages(pdf)
        self.assertEqual(len(extracted_pages), 5)
        self.assertTrue(all(len(page.strip()) > 40 for page in extracted_pages))
        self.assertIn("pendiente de evaluacion", story_text)
        self.assertIn("todavia no registrado", story_text)
        self.assertIn("falta completar esta referencia", story_text)
        self.assertIn("falta informacion para definir con mas claridad que conviene priorizar", story_text)
        self.assertIn("falta informacion reciente para entender como venis recuperando", story_text)
        self.assertIn("programar una nueva evaluacion", page_five)
        self.assertIn("cuando completemos una nueva evaluacion", page_five)
        self.assertNotIn("completar una nueva evaluacion nos va a dar una referencia mas clara para seguir ajustando el proceso", page_five)
        self.assertNotIn("sin datos", story_text)
        self.assertNotIn("base de trabajo definida: sin datos", story_text)
        self.assertNotIn("ya contamos con informacion suficiente para seguir tu progreso con mas claridad", story_text)
        self.assertNotIn("pendiente de completar", story_text)

    def test_client_pdf_visible_text_avoids_common_mojibake_and_tc_inv(self):
        with patch.object(report_generator, "datetime", FixedClientReportDate):
            pdf = generate_visual_report_pdf(_client_report_state(), "Ana Lopez", "cliente")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        visible_text = "\n".join(_pdf_extracted_text_pages(pdf))
        self.assertNotIn("TC inv", visible_text)
        for token in ["ÃƒÆ’", "Ãƒâ€š", "EstÃƒÆ’", "fisiolÃƒÆ’", "biomecÃƒÆ’", "prÃƒÆ’", "exposiciÃƒÆ’"]:
            self.assertNotIn(token, visible_text)
        for token in ["ultimas", "util", "Proximo", "proximo", "grafico", "sueno", "estres", "recuperacion", "medicion"]:
            self.assertNotIn(token, visible_text)
        self.assertNotIn("..", visible_text)
        self.assertNotIn("cuidar la recuperaci", visible_text.lower())

    def test_client_pdf_labels_wellness_windows_and_avoids_recovery_contradictions(self):
        with patch.object(report_generator, "datetime", FixedClientReportDate):
            pdf = generate_visual_report_pdf(_client_report_state(), "Ana Lopez", "cliente")

        self.assertIsNotNone(pdf)
        assert pdf is not None
        joined = " ".join(_normalized_pdf_pages(pdf))
        self.assertIn("promedio reciente", joined)
        self.assertIn("ultimos registros visibles", joined)
        self.assertIn("el promedio reciente es aceptable, pero conviene seguir de cerca la recuperacion percibida", joined)
        self.assertNotIn("sin senales grandes de alerta", joined)

    def test_client_pdf_uses_actionable_confirmation_copy_without_old_defensive_phrase(self):
        custom_payload = _structured_neuromuscular_stub(
            profile_code=None,
            profile_label="Sin patrón dominante",
            metrics={},
            flags=["insufficient_pattern_evidence"],
            evidence=[],
            kpi_to_track=[],
            summary_short="La información disponible todavía no alcanza para cerrar un patrón estable.",
            summary_client="La información disponible todavía no alcanza para cerrar un patrón estable.",
        )

        with patch.object(report_generator, "build_neuromuscular_profile_result", return_value=custom_payload):
            pdf, story_text = _rendered_pdf_and_story_text(_client_report_state(), "Ana Lopez")

        self.assertIsNotNone(pdf)
        joined_pages = " ".join(_normalized_pdf_pages(pdf))
        self.assertIn("mantener el bloque actual y volver a medir para confirmar", joined_pages)
        self.assertNotIn("antes de cambiar demasiado el foco", joined_pages)
        self.assertNotIn("antes de cambiar demasiado el foco", story_text)

    def test_client_pdf_high_stress_and_pain_do_not_read_as_no_large_deviations(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_attention_recovery_report_state(), "Ana Lopez")
        joined_pages = " ".join(_normalized_pdf_pages(pdf))

        self.assertIsNotNone(pdf)
        self.assertIn(
            "la recuperacion viene algo cargada: estres y dolor merecen atencion antes de subir exigencia",
            joined_pages,
        )
        self.assertNotIn("sin senales grandes de alerta", joined_pages)
        self.assertNotIn("no muestran desvios grandes", joined_pages)
        self.assertNotIn("sin senales grandes de alerta", story_text)

    def test_client_pdf_precaution_load_keeps_useful_but_not_overly_positive_wording(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_precaution_load_report_state(), "Ana Lopez")
        joined_pages = " ".join(_normalized_pdf_pages(pdf))

        self.assertIsNotNone(pdf)
        self.assertIn(
            "la carga permite seguir entrenando, pero pide cuidado y mas continuidad antes de subir exigencia",
            joined_pages,
        )
        self.assertNotIn("zona util para seguir construyendo con continuidad", joined_pages)
        self.assertNotIn("zona util para seguir construyendo con continuidad", story_text)

    def test_client_pdf_handles_low_wellness_with_few_records_without_repeating_or_softening_alerts(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_partial_low_wellness_report_state(), "Ana Lopez")
        joined_pages = " ".join(_normalized_pdf_pages(pdf))

        self.assertIsNotNone(pdf)
        self.assertLessEqual(_pdf_page_count(pdf), 5)
        self.assertIn("el registro es bajo, pero los valores disponibles sugieren cuidar recuperacion, estres y dolor de cerca", joined_pages)
        self.assertIn("recuperacion, estres, dolor y constancia requieren seguimiento", joined_pages)
        self.assertIn("promedio reciente", joined_pages)
        self.assertIn("ultimos registros visibles", joined_pages)
        self.assertLessEqual(joined_pages.count("todavia hay pocos registros para sacar una conclusion firme sobre recuperacion"), 1)
        self.assertNotIn("sin senales grandes de alerta", joined_pages)
        self.assertNotIn("estado actual optimo", joined_pages)
        self.assertNotIn("tc inv", story_text)

    def test_client_payload_handles_missing_imtp_without_keyerror(self):
        payload = _build_pdf_neuromuscular_profile_payload(
            pd.Series({"SJ_cm": 30.0, "CMJ_cm": 32.0, "DJ_cm": 24.0, "DJ_RSI": 1.05, "DJ_tc_ms": 220.0, "EUR": 1.04}),
            context={"audience": "cliente"},
        )

        self.assertIn("missing_imtp", payload["flags"])
        self.assertTrue(payload["summary_client"])
        self.assertTrue(payload["training_priority_short"])

    def test_client_payload_handles_missing_dj_without_keyerror(self):
        payload = _build_pdf_neuromuscular_profile_payload(
            pd.Series({"SJ_cm": 30.0, "CMJ_cm": 32.0, "IMTP_relPF": 38.0, "EUR": 1.04, "IMTP_relPF_Z": 0.10}),
            context={"audience": "cliente"},
        )

        self.assertIn("missing_dj", payload["flags"])
        self.assertTrue(payload["summary_client"])
        self.assertTrue(payload["training_priority_short"])

    def test_client_summary_avoids_heavy_jargon_across_patterns(self):
        rows = {
            "A": pd.Series({"SJ_cm": 32.0, "CMJ_cm": 34.0, "DJ_cm": 25.0, "DJ_RSI": 1.10, "DJ_tc_ms": 210.0, "IMTP_relPF": 38.0, "EUR": 1.06, "SJ_Z": 0.80, "CMJ_Z": 0.10, "DJ_height_Z": -0.20, "DJ_RSI_Z": -0.80, "TC_inv_Z": 0.20, "IMTP_relPF_Z": 0.30}),
            "B": pd.Series({"SJ_cm": 26.0, "CMJ_cm": 29.0, "DJ_cm": 24.0, "DJ_RSI": 1.35, "DJ_tc_ms": 205.0, "EUR": 1.08, "SJ_Z": -0.80, "CMJ_Z": 0.00, "DJ_height_Z": 0.20, "DJ_RSI_Z": 0.80, "TC_inv_Z": 0.30}),
            "C": pd.Series({"SJ_cm": 30.0, "CMJ_cm": 33.0, "DJ_cm": 24.0, "DJ_RSI": 1.00, "DJ_tc_ms": 220.0, "IMTP_relPF": 30.0, "EUR": 1.10, "SJ_Z": 0.00, "CMJ_Z": 0.00, "DJ_height_Z": 0.00, "DJ_RSI_Z": 0.00, "TC_inv_Z": 0.00, "IMTP_relPF_Z": -0.80}),
            "D": pd.Series({"SJ_cm": 25.0, "CMJ_cm": 27.0, "DJ_cm": 20.0, "DJ_RSI": 0.85, "DJ_tc_ms": 260.0, "IMTP_relPF": 28.0, "EUR": 1.02, "SJ_Z": -0.80, "CMJ_Z": -0.70, "DJ_height_Z": -0.90, "DJ_RSI_Z": -0.85, "TC_inv_Z": -0.65, "IMTP_relPF_Z": -0.75}),
            "E": pd.Series({"SJ_cm": 31.0, "CMJ_cm": 29.0, "DJ_cm": 24.0, "DJ_RSI": 1.20, "DJ_tc_ms": 220.0, "IMTP_relPF": 38.0, "EUR": 0.95, "SJ_Z": 0.10, "CMJ_Z": 0.05, "DJ_height_Z": 0.00, "DJ_RSI_Z": 0.15, "TC_inv_Z": 0.05, "IMTP_relPF_Z": 0.20}),
        }

        forbidden_terms = ("ssc", "isometrica relativa", "isométrica relativa", "densidad reactiva", "stiffness", "dsi", "imtp")

        for pattern_code, row in rows.items():
            with self.subTest(pattern=pattern_code):
                payload = _build_pdf_neuromuscular_profile_payload(row, context={"audience": "cliente"})
                summary = _normalized_story_text(payload["summary_client"])
                for forbidden in forbidden_terms:
                    self.assertNotIn(forbidden, summary)

    def test_client_pdf_renders_pattern_e_as_simple_alert(self):
        pdf, story_text = _rendered_pdf_and_story_text(_client_pattern_e_report_state(), "Ana Lopez")
        joined_pages = " ".join(_normalized_pdf_pages(pdf))

        self.assertIsNotNone(pdf)
        self.assertIn("contramovimiento", joined_pages)
        self.assertNotIn("tc inv", story_text)

    def test_client_pdf_uses_structured_summary_when_wording_changes(self):
        custom_summary = "Lectura cliente custom que cambia sin romper la estructura."
        with patch.object(
            report_generator,
            "build_neuromuscular_profile_result",
            return_value=_structured_neuromuscular_stub(summary_client=custom_summary),
        ):
            pdf, story_text = _rendered_pdf_and_story_text(_client_report_state(), "Ana Lopez")

        self.assertIsNotNone(pdf)
        self.assertIn(_normalized_story_text(custom_summary), story_text)

    def test_client_focus_can_read_profile_label_from_structured_payload(self):
        custom_label = "Patron E - CMJ menor que SJ"
        with patch.object(
            report_generator,
            "build_neuromuscular_profile_result",
            return_value=_structured_neuromuscular_stub(profile_label=custom_label, profile_code="E"),
        ):
            pdf, story_text = _rendered_pdf_and_story_text(_client_report_state(), "Ana Lopez")

        self.assertIsNotNone(pdf)
        self.assertIn(_normalized_story_text(custom_label), story_text)


if __name__ == "__main__":
    unittest.main()
