"""Reporte profesional: cobertura de sRPE en rojo y semana con sesiones sin sRPE.

- Cobertura "Rojo" (sRPE < 60% de las sesiones): ninguna frase de estabilidad
  ni tolerancia ("Carga estable... compatible con tolerancia"); en su lugar
  "No evaluable: cobertura insuficiente". Los avisos de datos faltantes
  (ACWR no calculable, monotonia no calculable) se mantienen.
- sRPE semanal con sesiones sin reporte: el total se muestra como parcial,
  "1441 UA (parcial: 3 de N sesiones)", en la misma casilla.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import pandas as pd

import local_store
from modules import report_generator
from modules.data_quality import SRPE_COVERAGE_RED_PCT

DAYS = pd.date_range("2026-08-03", "2026-10-04", freq="D")
TRAINED = [day for day in DAYS if day.weekday() in (0, 1, 3, 4)]
TODAY = pd.Timestamp("2026-10-06")
INTERPRETIVE_PHRASES = ("estable", "compatible", "tolerable", "luce alta", "homogénea", "subdosificada", "en ascenso")


def _state(logged_dates) -> dict:
    rpe_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in logged_dates])
    raw_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Assigned Date": day, "Exercise": "Squat"} for day in TRAINED])
    acwr_dict, mono_dict = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
    state = {"rpe_df": rpe_df, "raw_df": raw_df, "acwr_dict": acwr_dict, "mono_dict": mono_dict}
    state["weekly_summaries"] = local_store.build_weekly_summaries(
        rpe_df, None, raw_df, acwr_dict=acwr_dict, today=TODAY
    )
    return state


def _load_payload(state: dict) -> tuple[dict, dict]:
    with patch.object(report_generator, "_professional_report_today", return_value=TODAY):
        internal = report_generator._build_professional_internal_load_context(state, "Ana Lopez")
        payload = report_generator._build_professional_load_tolerance_payload(state, "Ana Lopez", internal)
    return internal, payload


class CoverageRedTest(unittest.TestCase):
    def test_threshold_is_sixty_percent(self):
        self.assertEqual(SRPE_COVERAGE_RED_PCT, 60.0)

    def test_full_coverage_keeps_interpretive_reading(self):
        _, payload = _load_payload(_state(TRAINED))
        self.assertFalse(payload["coverage_red"])
        self.assertNotIn(report_generator.LOAD_NOT_EVALUABLE_TEXT, payload["risk_line"])

    def test_red_coverage_replaces_stability_and_tolerance_phrases(self):
        state = _state(TRAINED)
        with patch.object(
            report_generator, "_srpe_coverage_red", return_value=(True, "sRPE en 40% de las sesiones")
        ):
            _, payload = _load_payload(state)

        self.assertTrue(payload["coverage_red"])
        self.assertEqual(
            payload["risk_line"], "No evaluable: cobertura insuficiente (sRPE en 40% de las sesiones)."
        )
        for phrase in INTERPRETIVE_PHRASES:
            self.assertNotIn(phrase, payload["risk_line"].lower())

    def test_missing_data_warnings_win_over_coverage_text(self):
        # Con sesiones sin sRPE el ACWR ya avisa "no calculable": se mantiene.
        _, payload = _load_payload(_state(TRAINED[::4]))
        self.assertTrue(payload["coverage_red"])
        self.assertIn("no calculable", payload["risk_line"].lower())
        for phrase in INTERPRETIVE_PHRASES:
            self.assertNotIn(phrase, payload["risk_line"].lower())

    def test_real_low_coverage_is_detected(self):
        red, detail = report_generator._srpe_coverage_red(_state(TRAINED[::4]), "Ana Lopez")
        self.assertTrue(red)
        self.assertRegex(detail, r"^sRPE en \d+% de las (sesiones|días)$")

    def test_wellness_compatibility_does_not_claim_tolerance(self):
        wellness = {
            "state": "available",
            "analysis_week_label": "28/09/2026 - 04/10/2026",
            "last_week_summary": {"score_mean": 20.0, "score_n": 4, "sleep_mean": 7.5, "stress_mean": 2.0, "pain_mean": 1.0},
            "scales": {"sleep": "h", "stress": "/5", "pain": "/5"},
        }
        internal = {"state": "available", "weekly_change_pct": 2.0}
        args = (_state(TRAINED), "Ana Lopez", {"state": "available"}, internal, wellness)

        with patch.object(report_generator, "_srpe_coverage_red", return_value=(False, "")):
            ok = report_generator._build_professional_wellness_availability_payload(*args)
        self.assertIn("compatible con tolerancia", ok["compatibility"])

        with patch.object(
            report_generator, "_srpe_coverage_red", return_value=(True, "sRPE en 40% de las sesiones")
        ):
            red = report_generator._build_professional_wellness_availability_payload(*args)
        self.assertTrue(red["compatibility"].startswith(report_generator.LOAD_NOT_EVALUABLE_TEXT))
        self.assertNotIn("estable", red["compatibility"].lower())
        self.assertNotIn("tolerancia", red["compatibility"].lower())


class PartialWeeklySrpeTest(unittest.TestCase):
    def test_weekly_srpe_shows_partial_sessions(self):
        internal, payload = _load_payload(_state(TRAINED[::4]))
        done = internal["analysis_week_sessions_done"]
        missing = internal["analysis_week_sessions_missing"]
        self.assertGreater(missing, 0)

        rows = dict(payload["rows"])
        match = re.fullmatch(r"(\d+) UA \(parcial: (\d+) de (\d+) sesiones\)", rows["sRPE semanal"])
        self.assertIsNotNone(match, rows["sRPE semanal"])
        self.assertEqual(int(match.group(2)), int(done - missing))
        self.assertEqual(int(match.group(3)), int(done))

    def test_complete_week_has_no_partial_suffix(self):
        _, payload = _load_payload(_state(TRAINED))
        rows = dict(payload["rows"])
        self.assertRegex(rows["sRPE semanal"], r"^\d+ UA$")


if __name__ == "__main__":
    unittest.main()
