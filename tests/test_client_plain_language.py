"""Reporte cliente en lenguaje llano y motivos reales (PDF real de produccion, 31/10).

- El cliente nunca ve "ACWR" ni "zona" (antes: "sostener carga actual con
  acwr ewma 0.94 en zona optimo" en lectura breve, foco y cierre).
- Constancia > 100% se muestra con tope 100% y "completo todo lo asignado".
- Profesional: el motivo de la confianza baja es el real; nunca "cobertura
  parcial" si la cobertura es verde.
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

ATHLETE = "Exequiel Prueba"
NOW = pd.Timestamp("2026-10-29 12:00")
WEEKS = pd.date_range("2026-08-03", "2026-10-26", freq="W-MON")
TRAINED = [week + pd.Timedelta(days=offset) for week in WEEKS for offset in (0, 1, 3, 4)]
TRAINED = [day for day in TRAINED if day <= pd.Timestamp("2026-10-27")]


def green_state(*, completion_pct: float | None = None) -> dict:
    """Cobertura verde (sRPE y wellness todos los dias), sin evaluaciones fisicas."""
    rpe = pd.DataFrame([{"Athlete": ATHLETE, "Date": day, "RPE": 6, "Duration_min": 70, "sRPE": 420.0} for day in TRAINED])
    raw = pd.DataFrame(
        [
            {"Athlete": ATHLETE, "Assigned Date": day, "Completed Date": day, "Exercise Name": "Back Squat",
             "Set Number": 1, "Result": 80, "Reps": 5, "Tags": "Dominante de Rodilla"}
            for day in TRAINED
        ]
    )
    wellness = pd.DataFrame(
        [{"Athlete": ATHLETE, "Date": day, "Sueno_hs": 7.5, "Estres": 3, "Dolor": 1, "Wellness_Score": 23.5} for day in TRAINED]
    )
    acwr, mono = local_store.build_load_models(rpe, weeks=None, raw_df=raw)
    state = {
        "rpe_df": rpe,
        "raw_df": raw,
        "wellness_df": wellness,
        "acwr_dict": acwr,
        "mono_dict": mono,
        "weekly_summaries": local_store.build_weekly_summaries(rpe, wellness, raw, acwr_dict=acwr, today=NOW.normalize()),
        "athletes_list": [ATHLETE],
    }
    if completion_pct is not None:
        # 38 de 35 asignados = 108.6% (completo mas de lo asignado).
        assigned = 35
        completed = round(assigned * completion_pct / 100)
        state["completion_df"] = pd.DataFrame(
            [{"Athlete": ATHLETE, "Date": "2026-10-27", "Assigned": assigned, "Completed": completed}]
        )
    return state


def pdf_text(pdf: bytes) -> str:
    text = " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    text = report_generator._repair_mojibake_text(text)
    text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(text.split())


class ClientPlainLanguageTest(unittest.TestCase):
    def test_client_pdf_never_mentions_acwr_or_zones(self):
        state = green_state()
        with frozen_app_now(NOW):
            evaluable, detail = report_generator._load_evaluability(state, ATHLETE)
            self.assertTrue(evaluable, detail)  # el caso es el de produccion: carga evaluable
            zone = report_generator._latest_acwr_row(state, ATHLETE)["Zona"]
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, "cliente")
        self.assertTrue(str(zone))
        text = pdf_text(pdf)
        self.assertNotIn("acwr", text)
        self.assertNotIn("zona", text)
        self.assertIn("similar a las anteriores", text)


class CompletionCapTest(unittest.TestCase):
    def test_formatter_caps_at_100(self):
        fmt = report_generator.completion_display_text
        self.assertEqual(fmt(108.6), "100% (completó todo lo asignado)")
        self.assertEqual(fmt(100.0), "100.0%")
        self.assertEqual(fmt(83.3), "83.3%")
        self.assertEqual(fmt(None, fallback="Todavía no registrado"), "Todavía no registrado")

    def test_client_pdf_shows_capped_completion(self):
        state = green_state(completion_pct=108.6)
        with frozen_app_now(NOW):
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, "cliente")
        text = pdf_text(pdf)
        self.assertIn("100% (completo todo lo asignado)", text)
        self.assertIsNone(re.search(r"10[1-9]\.\d%|1[1-9]\d\.\d%", text), text[:300])


class ConfidenceReasonTest(unittest.TestCase):
    def test_green_coverage_never_blames_partial_coverage(self):
        state = green_state()
        with frozen_app_now(NOW):
            color, _ = report_generator._athlete_coverage_light(state, ATHLETE)
            self.assertEqual(color, "verde")
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, "profe")
        text = pdf_text(pdf)
        self.assertIn("nivel de confianza baja", text)
        self.assertIn("sin evaluaciones fisicas", text)
        self.assertNotIn("cobertura parcial", text)

    def test_reasons_list_coverage_only_when_not_green(self):
        reasons = report_generator._professional_confidence_reasons
        with frozen_app_now(NOW):
            green = reasons(green_state(), ATHLETE, "missing", {"state": "available"}, {"state": "available"})
        self.assertEqual(green, ["sin evaluaciones físicas"])


if __name__ == "__main__":
    unittest.main()
