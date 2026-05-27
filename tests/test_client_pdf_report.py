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
from modules.report_generator import generate_visual_report_pdf


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


if __name__ == "__main__":
    unittest.main()
