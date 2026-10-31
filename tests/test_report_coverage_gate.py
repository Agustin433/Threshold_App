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


def _state(logged_dates, *, with_raw: bool = True) -> dict:
    rpe_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in logged_dates])
    raw_df = (
        pd.DataFrame([{"Athlete": "Ana Lopez", "Assigned Date": day, "Exercise": "Squat"} for day in TRAINED])
        if with_raw
        else None
    )
    acwr_dict, mono_dict = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
    # Wellness todos los dias entrenados: el semaforo solo depende del sRPE.
    wellness_df = pd.DataFrame(
        [{"Athlete": "Ana Lopez", "Date": day, "Wellness_Score": 20.0} for day in TRAINED]
    )
    state = {
        "rpe_df": rpe_df,
        "raw_df": raw_df,
        "wellness_df": wellness_df,
        "acwr_dict": acwr_dict,
        "mono_dict": mono_dict,
    }
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
        self.assertTrue(payload["load_evaluable"])
        self.assertNotIn(report_generator.LOAD_NOT_EVALUABLE_TEXT, payload["risk_line"])

    def test_red_coverage_replaces_stability_and_tolerance_phrases(self):
        state = _state(TRAINED)
        with patch.object(
            report_generator, "_load_evaluability", return_value=(False, "sRPE en 40% de las sesiones")
        ):
            _, payload = _load_payload(state)

        self.assertFalse(payload["load_evaluable"])
        self.assertEqual(
            payload["risk_line"], "No evaluable: cobertura insuficiente (sRPE en 40% de las sesiones)."
        )
        for phrase in INTERPRETIVE_PHRASES:
            self.assertNotIn(phrase, payload["risk_line"].lower())

    def test_missing_data_warnings_win_over_coverage_text(self):
        # Con sesiones sin sRPE el ACWR ya avisa "no calculable": se mantiene.
        _, payload = _load_payload(_state(TRAINED[::4]))
        self.assertFalse(payload["load_evaluable"])
        self.assertIn("no calculable", payload["risk_line"].lower())
        for phrase in INTERPRETIVE_PHRASES:
            self.assertNotIn(phrase, payload["risk_line"].lower())

    def test_real_low_coverage_is_detected(self):
        with patch.object(report_generator, "_professional_report_today", return_value=TODAY):
            evaluable, detail = report_generator._load_evaluability(_state(TRAINED[::4]), "Ana Lopez")
        self.assertFalse(evaluable)
        self.assertRegex(detail, r"^cobertura roja: sRPE en \d+% de las (sesiones|días)$")

    def test_wellness_compatibility_does_not_claim_tolerance(self):
        wellness = {
            "state": "available",
            "analysis_week_label": "28/09/2026 - 04/10/2026",
            "last_week_summary": {"score_mean": 20.0, "score_n": 4, "sleep_mean": 7.5, "stress_mean": 2.0, "pain_mean": 1.0},
            "scales": {"sleep": "h", "stress": "/10", "pain": "/10"},
        }
        internal = {"state": "available", "weekly_change_pct": 2.0}
        args = (_state(TRAINED), "Ana Lopez", {"state": "available"}, internal, wellness)

        with patch.object(report_generator, "_load_evaluability", return_value=(True, "")):
            ok = report_generator._build_professional_wellness_availability_payload(*args)
        self.assertIn("compatible con tolerancia", ok["compatibility"])

        with patch.object(
            report_generator, "_load_evaluability", return_value=(False, "sRPE en 40% de las sesiones")
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

    def test_complete_week_shows_full_coverage(self):
        _, payload = _load_payload(_state(TRAINED))
        rows = dict(payload["rows"])
        self.assertRegex(rows["sRPE semanal"], r"^\d+ UA \((\d+) de \1 sesiones\)$")

    def test_without_raw_workouts_shows_sessions_with_srpe(self):
        # Sin Raw Workouts no hay N: nunca el numero solo.
        state = _state(TRAINED, with_raw=False)
        _, payload = _load_payload(state)
        rows = dict(payload["rows"])
        self.assertRegex(rows["sRPE semanal"], r"^\d+ UA \(con \d+ sesi(ón|ones) con sRPE\)$")

    def test_weekly_points_mark_partial_weeks(self):
        internal, _ = _load_payload(_state(TRAINED[::4]))
        partial = [point for point in internal["weekly_points"] if point.get("partial")]
        self.assertTrue(partial)
        for point in partial:
            self.assertLess(point["sessions_with_srpe"], point["sessions_done"])

    def test_formatter_cases(self):
        fmt = report_generator.weekly_srpe_text
        self.assertEqual(fmt(1441, 4, 3), "1441 UA (parcial: 3 de 4 sesiones)")
        self.assertEqual(fmt(270, None, 1), "270 UA (con 1 sesión con sRPE)")
        self.assertEqual(fmt(800, None, 2), "800 UA (con 2 sesiones con sRPE)")
        self.assertEqual(fmt(1200, 3, 3), "1200 UA (3 de 3 sesiones)")


if __name__ == "__main__":
    unittest.main()


class ClientLoadTrendTest(unittest.TestCase):
    """Reporte cliente: semana mas liviana/similar/mas exigente que las anteriores."""

    @staticmethod
    def _internal(values, partial_last=False, scope="last_complete_week"):
        points = [{"value": value, "partial": False} for value in values]
        points[-1]["partial"] = partial_last
        return {"analysis_scope": scope, "weekly_points": points}

    def test_lighter_similar_heavier(self):
        trend = report_generator.client_load_trend
        self.assertEqual(trend(self._internal([1000, 1000, 1000, 1000, 600])), report_generator.CLIENT_TREND_LIGHTER)
        self.assertEqual(trend(self._internal([1000, 1000, 1000, 1050])), report_generator.CLIENT_TREND_SIMILAR)
        self.assertEqual(trend(self._internal([1000, 1000, 1400])), report_generator.CLIENT_TREND_HEAVIER)

    def test_no_comparison_without_enough_complete_weeks(self):
        trend = report_generator.client_load_trend
        self.assertIsNone(trend(self._internal([1000, 600])))
        self.assertIsNone(trend(self._internal([1000, 1000, 1000, 270], partial_last=True)))
        self.assertIsNone(trend(self._internal([1000, 1000, 1000], scope="current_week_partial")))

    def test_labels_have_no_acwr_vocabulary(self):
        for text in list(report_generator.CLIENT_TREND_LABELS.values()) + list(report_generator.CLIENT_TREND_SENTENCES.values()):
            lowered = text.lower()
            for word in ("subcarga", "óptimo", "precaución", "riesgo", "acwr", "zona"):
                self.assertNotIn(word, lowered)
