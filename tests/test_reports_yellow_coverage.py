"""Los tres reportes PDF con cobertura AMARILLA y 1 sesión con sRPE en la semana.

Caso real de producción (Cande Falzone, 30/10/2026): cobertura amarilla, la
semana analizada con 1 sesión reportada y ACWR/monotonía/strain no
calculables. El PDF decía "Carga estable + wellness estables: compatible con
tolerancia" y "270 UA" sin decir que era parcial.

Se verifica en el texto real de los PDF profesional, atleta y cliente:
- ninguna frase de estabilidad/tolerancia/zona útil de la carga;
- "No evaluable: cobertura insuficiente";
- el sRPE semanal con "(parcial: 1 de 4 sesiones)";
- dolor y estrés en /10.
"""

from __future__ import annotations

import re
import unicodedata
import unittest
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

import local_store
from modules import report_generator
from modules.app_clock import frozen_app_now

ATHLETE = "Cande Prueba"
NOW = pd.Timestamp("2026-10-29 12:00")  # jueves: ultima semana completa 19/10-25/10
WEEKS = pd.date_range("2026-09-14", "2026-10-19", freq="W-MON")
TRAINING_WEEKDAYS = (0, 1, 3, 4)
ANALYSIS_WEEK = pd.Timestamp("2026-10-19")

# Frases que afirman estabilidad, tolerancia o zona util de la CARGA.
FORBIDDEN = (
    "compatible con tolerancia",
    "compatible con control de carga",
    "parece estable y compatible",
    "zona util",
    "zona operativa util",
    "carga estable",
    "con zona no evaluable",
)


# Semana en curso (26/10): entrena lunes y martes, reporta el lunes. Cierra la
# semana 19/10 como "ultima semana completa".
CURRENT_WEEK_TRAINED = [pd.Timestamp("2026-10-26"), pd.Timestamp("2026-10-27")]
CURRENT_WEEK_REPORTED = [pd.Timestamp("2026-10-26")]


def _trained_days() -> list[pd.Timestamp]:
    return [week + pd.Timedelta(days=offset) for week in WEEKS for offset in TRAINING_WEEKDAYS] + CURRENT_WEEK_TRAINED


def _reported_days() -> list[pd.Timestamp]:
    """3 de 4 sesiones por semana; la semana analizada solo 1 de 4."""
    reported: list[pd.Timestamp] = []
    for week in WEEKS:
        days = [week + pd.Timedelta(days=offset) for offset in TRAINING_WEEKDAYS]
        reported.extend(days[:1] if week == ANALYSIS_WEEK else days[:3])
    return reported + CURRENT_WEEK_REPORTED


def yellow_coverage_state() -> dict:
    reported = _reported_days()
    rpe_df = pd.DataFrame(
        [{"Athlete": ATHLETE, "Date": day, "RPE": 6, "Duration_min": 45, "sRPE": 270.0} for day in reported]
    )
    raw_df = pd.DataFrame(
        [
            {
                "Athlete": ATHLETE,
                "Assigned Date": day,
                "Completed Date": day,
                "Exercise Name": name,
                "Set Number": 1,
                "Result": 80,
                "Reps": 5,
                "Tags": tag,
            }
            for day in _trained_days()
            for name, tag in (("Back Squat", "Dominante de Rodilla"), ("Barbell Bench Press", "Empuje Horizontal"))
        ]
    )
    wellness_df = pd.DataFrame(
        [
            {"Athlete": ATHLETE, "Date": day, "Sueno_hs": 7.0, "Estres": 3, "Dolor": 2, "Wellness_Score": 22.0}
            for day in reported
        ]
    )
    acwr_dict, mono_dict = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
    weekly = local_store.build_weekly_summaries(
        rpe_df, wellness_df, raw_df, acwr_dict=acwr_dict, today=NOW.normalize()
    )
    return {
        "rpe_df": rpe_df,
        "raw_df": raw_df,
        "wellness_df": wellness_df,
        "acwr_dict": acwr_dict,
        "mono_dict": mono_dict,
        "weekly_summaries": weekly,
        "athletes_list": [ATHLETE],
    }


def full_charts_state() -> dict:
    """Caso amarillo + wellness diario (40 dias): todos los graficos de cada reporte."""
    import numpy as np

    state = yellow_coverage_state()
    days = pd.date_range("2026-09-15", "2026-10-26")
    rng = np.random.default_rng(1)
    wellness = pd.DataFrame(
        {
            "Athlete": ATHLETE,
            "Date": days,
            "Sueno_hs": rng.normal(7, 0.7, len(days)).round(1),
            "Estres": rng.integers(2, 7, len(days)),
            "Dolor": rng.integers(0, 5, len(days)),
        }
    )
    wellness["Wellness_Score"] = wellness["Sueno_hs"].clip(0, 10) + (10 - wellness["Estres"]) + (10 - wellness["Dolor"])
    state["wellness_df"] = wellness
    return state


def _pdf_text(pdf: bytes) -> str:
    pages = [(page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages]
    text = " ".join(report_generator._repair_mojibake_text(page) for page in pages)
    ascii_text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(ascii_text.split())


class WellnessChartTitleTest(unittest.TestCase):
    def test_title_matches_window(self):
        weekly = [{"label": f"S{i}", "score": 20.0} for i in range(5)]
        daily = [{"label": f"D{i}", "score": 20.0} for i in range(3)]
        points, title = report_generator.wellness_chart_points_and_title(
            {"trend_allowed": True, "weekly_points": weekly, "daily_points": daily}
        )
        self.assertEqual(len(points), 5)
        self.assertEqual(title, "Wellness semanal (promedio por semana, 5 semanas)")
        points, title = report_generator.wellness_chart_points_and_title(
            {"trend_allowed": False, "weekly_points": weekly, "daily_points": daily}
        )
        self.assertEqual(len(points), 3)
        self.assertEqual(title, "Wellness diario (semana analizada)")


class YellowCoverageReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = yellow_coverage_state()
        cls.texts: dict[str, str] = {}
        with frozen_app_now(NOW):
            evaluable, detail = report_generator._load_evaluability(cls.state, ATHLETE)
            cls.precondition = (evaluable, detail)
            cls.internal = report_generator._build_professional_internal_load_context(cls.state, ATHLETE)
            for audience in ("profe", "atleta", "cliente"):
                pdf = report_generator.generate_visual_report_pdf(cls.state, ATHLETE, audience)
                cls.texts[audience] = _pdf_text(pdf) if pdf else ""

    def test_fixture_is_yellow_with_one_session_reported(self):
        evaluable, detail = self.precondition
        self.assertFalse(evaluable)
        self.assertIn("cobertura amarilla", detail)
        self.assertEqual(self.internal["analysis_week_label"], "19/10/2026 - 25/10/2026")
        self.assertEqual(self.internal["analysis_week_sessions_with_srpe"], 1)
        self.assertEqual(self.internal["analysis_week_sessions_done"], 4)

    def test_no_stability_or_tolerance_phrases(self):
        for audience, text in self.texts.items():
            with self.subTest(audience=audience):
                self.assertTrue(text, f"no se genero el PDF {audience}")
                for phrase in FORBIDDEN:
                    self.assertNotIn(phrase, text, f"{audience}: '{phrase}'")
                self.assertNotIn("optimo", text.split("estado de")[-1][:40] if "estado de" in text else "")

    def test_not_evaluable_text_is_shown(self):
        for audience, text in self.texts.items():
            with self.subTest(audience=audience):
                self.assertIn("no evaluable: cobertura insuficiente", text)

    def test_weekly_srpe_is_partial(self):
        for audience, text in self.texts.items():
            with self.subTest(audience=audience):
                self.assertRegex(text, r"\d+ ua \(parcial: 1 de 4 sesiones\)")
                self.assertIsNone(re.search(r"\b270 ua(?! \()", text), f"{audience}: 270 UA sin cobertura")

    def test_pain_and_stress_use_ten_point_scale(self):
        for audience in ("profe", "cliente"):
            with self.subTest(audience=audience):
                text = self.texts[audience]
                self.assertNotRegex(text, r"\d/5\b")
                self.assertRegex(text, r"dolor[^/]{0,60}/10")


if __name__ == "__main__":
    unittest.main()
