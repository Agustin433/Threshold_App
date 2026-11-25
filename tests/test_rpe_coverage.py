"""PR S: carga interna condicionada por la cobertura de sRPE.

cobertura = sesiones completadas (Raw Workouts, fecha de sesion) con sRPE /
sesiones completadas, en 28 dias o por semana calendario. ACWR con >= 70% en
28 dias; monotonia/strain con >= 70% en la semana y >= 4 sesiones. Debajo:
"Registra tu RPE: te faltan N sesiones".
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules import athlete_report as ar
from modules import report_generator as rg
from modules.load_monitoring import (
    ACWR_STATUS_INCOMPLETE,
    acwr_unavailable_reason,
    calc_acwr,
    calc_monotony_strain,
    latest_training_day_row,
)
from modules.report_messages import NEXT_STEPS_MAX
from modules.rpe_coverage import (
    acwr_display_text,
    acwr_frame_week_coverage,
    coverage_by_athlete,
    coverage_from_acwr_frame,
    missing_for_target,
    rolling_coverage_counts,
    rpe_coverage,
    team_registration_table,
)

# Domingo: la ventana de 28 dias son 4 semanas calendario completas.
TODAY = pd.Timestamp("2026-11-22")
# 5 sesiones por semana (lunes a viernes) durante 10 semanas.
SESSIONS = pd.DatetimeIndex([
    day for day in pd.date_range(TODAY - pd.Timedelta(days=69), TODAY) if day.weekday() < 5
])
WINDOW = SESSIONS[SESSIONS > TODAY - pd.Timedelta(days=28)]  # 20 sesiones


def _logged_fraction(sessions: pd.DatetimeIndex, per_week: int) -> list[pd.Timestamp]:
    """Las primeras `per_week` sesiones de cada semana (los huecos repartidos)."""
    frame = pd.DataFrame({"day": sessions})
    frame["week"] = frame["day"] - pd.to_timedelta(frame["day"].dt.weekday, unit="D")
    return list(frame.groupby("week").head(per_week)["day"])


def _seventy_exact() -> list[pd.Timestamp]:
    # 14 de 20 en la ventana: 4,4,3,3 por semana; antes, todo registrado.
    before = list(SESSIONS[SESSIONS <= TODAY - pd.Timedelta(days=28)])
    weeks = sorted({day - pd.Timedelta(days=day.weekday()) for day in WINDOW})
    logged = []
    for week, count in zip(weeks, (3, 3, 4, 4)):
        logged += [day for day in WINDOW if week <= day < week + pd.Timedelta(days=7)][:count]
    return before + logged


ATHLETES = {
    "Cien Total": list(SESSIONS),
    "Setenta Justo": _seventy_exact(),
    "Cincuenta Media": [day for i, day in enumerate(SESSIONS) if i % 2 == 0],
    "Cero Registro": [],
    # Paso el 70% hace 2 semanas: 40% hasta entonces, 100% las 2 ultimas.
    "Recien Formada": _logged_fraction(SESSIONS[SESSIONS < TODAY - pd.Timedelta(days=13)], 2)
    + list(SESSIONS[SESSIONS >= TODAY - pd.Timedelta(days=13)]),
}


def _raw() -> pd.DataFrame:
    rows = [
        {"Athlete": athlete, "Assigned Date": day, "Completed Date": day, "Exercise Name": "Sentadilla", "Set Number": 1}
        for athlete in ATHLETES
        for day in SESSIONS
    ]
    return pd.DataFrame(rows)


def _rpe() -> pd.DataFrame:
    rows = [
        {"Athlete": athlete, "Date": day, "RPE": 6, "Duration_min": 60 + 5 * (day.dayofyear % 4), "sRPE": 6.0 * (60 + 5 * (day.dayofyear % 4))}
        for athlete, days in ATHLETES.items()
        for day in days
    ]
    return pd.DataFrame(rows)


def _wellness() -> pd.DataFrame:
    return pd.DataFrame([
        {"Athlete": "Cien Total", "Date": day, "Wellness_Score": 20.0} for day in WINDOW[::2]
    ])


def _acwr(athlete: str) -> pd.DataFrame:
    logged = pd.DatetimeIndex(ATHLETES[athlete])
    loads = [360.0 + 15 * (day.dayofyear % 4) for day in logged]
    return calc_acwr(pd.Series(loads), logged, training_dates=SESSIONS)


class CoverageDefinitionTest(unittest.TestCase):
    def test_four_cases(self):
        expected = {  # (sesiones, con RPE, cumple, faltan)
            "Cien Total": (20, 20, True, 0),
            "Setenta Justo": (20, 14, True, 0),
            "Cincuenta Media": (20, 10, False, 4),
            "Cero Registro": (20, 0, False, 14),
        }
        for athlete, (sessions, logged, meets, missing) in expected.items():
            with self.subTest(athlete=athlete):
                coverage = rpe_coverage(SESSIONS, ATHLETES[athlete], TODAY)
                self.assertEqual((coverage.sessions, coverage.logged), (sessions, logged))
                self.assertEqual(coverage.meets, meets)
                self.assertEqual(coverage.missing, missing)
        self.assertEqual(rpe_coverage(SESSIONS, ATHLETES["Cincuenta Media"], TODAY).register_text,
                         "Registrá tu RPE: te faltan 4 sesiones")
        self.assertEqual(missing_for_target(10, 6), 1)
        self.assertEqual(missing_for_target(0, 0), 0)

    def test_rolling_counts_match_the_point_function(self):
        calendar = pd.date_range(TODAY - pd.Timedelta(days=40), TODAY)
        for athlete, logged in ATHLETES.items():
            totals, with_rpe = rolling_coverage_counts(calendar, SESSIONS, logged)
            for day, total, count in list(zip(calendar, totals, with_rpe))[::5]:
                coverage = rpe_coverage(SESSIONS, logged, day)
                with self.subTest(athlete=athlete, day=day):
                    self.assertEqual((coverage.sessions, coverage.logged), (int(total), int(count)))


class AcwrGateTest(unittest.TestCase):
    def test_acwr_shown_only_from_seventy_percent(self):
        for athlete, shown in (("Cien Total", True), ("Setenta Justo", True), ("Cincuenta Media", False)):
            with self.subTest(athlete=athlete):
                last = latest_training_day_row(_acwr(athlete)).iloc[0]
                self.assertEqual(pd.notna(last["ACWR_EWMA"]), shown)
                if not shown:
                    self.assertEqual(last["ACWR_Estado"], ACWR_STATUS_INCOMPLETE)
                    self.assertEqual(acwr_unavailable_reason(last), "Registrá tu RPE: te faltan 4 sesiones")

    def test_zero_percent_gets_the_register_message(self):
        last = latest_training_day_row(_acwr("Cero Registro")).iloc[0]
        self.assertTrue(pd.isna(last["ACWR_EWMA"]))
        self.assertEqual(acwr_unavailable_reason(last), "Registrá tu RPE: te faltan 14 sesiones")

    def test_chronic_in_formation_legend(self):
        frame = _acwr("Recien Formada")
        last = latest_training_day_row(frame).iloc[0]
        self.assertTrue(pd.notna(last["ACWR_EWMA"]))
        coverage = coverage_from_acwr_frame(frame, last["Date"])
        self.assertTrue(coverage.meets)
        self.assertEqual(coverage.streak_weeks, 2)
        self.assertTrue(coverage.forming)
        # Racha desde el lunes 09/11: 4 semanas despues, 07/12.
        self.assertEqual(coverage.formation_text, "carga crónica en formación (estable desde ~07/12)")
        text = acwr_display_text(last["ACWR_EWMA"], "", forming=coverage.forming, stable_from=coverage.stable_from)
        self.assertRegex(text, r"^\d\.\d\d · carga crónica en formación \(estable desde ~07/12\)$")
        # Con 4 semanas seguidas >= 70% ya no esta en formacion.
        self.assertFalse(coverage_from_acwr_frame(_acwr("Cien Total")).forming)

    def test_weekly_summary_carries_the_same_coverage(self):
        weeks = acwr_frame_week_coverage(_acwr("Cincuenta Media"))
        last = weeks.iloc[-1]
        self.assertAlmostEqual(last["rpe_coverage_28d"], 0.5)
        self.assertEqual(last["rpe_missing_for_70"], 4)


class MonotonyGateTest(unittest.TestCase):
    def test_week_needs_seventy_percent_coverage(self):
        weekly = calc_monotony_strain(_acwr("Cincuenta Media"))
        low = weekly[pd.to_numeric(weekly["Cobertura_RPE_semana"], errors="coerce") < 0.7]
        self.assertFalse(low.empty)
        self.assertTrue(low["Monotonia"].isna().all())
        self.assertTrue(low["Strain"].isna().all())
        full = calc_monotony_strain(_acwr("Cien Total"))
        complete_weeks = full[full["Sesiones_completadas_semana"] == 5]
        self.assertTrue(complete_weeks["Monotonia"].notna().all())

    def test_week_with_three_sessions_has_no_monotony(self):
        days = pd.DatetimeIndex(["2026-11-16", "2026-11-18", "2026-11-20"])
        frame = calc_acwr(pd.Series([400.0, 450.0, 500.0]), days, training_dates=days)
        weekly = calc_monotony_strain(frame)
        week = weekly.iloc[-1]
        self.assertEqual(week["Cobertura_RPE_semana"], 1.0)
        self.assertTrue(pd.isna(week["Monotonia"]))
        self.assertTrue(pd.isna(week["Strain"]))
        self.assertEqual(week["Monotony_Status"], "few_sessions")


class SameCoverageEverywhereTest(unittest.TestCase):
    """App (KPI de Hoy y modelo de ACWR), dashboard (resumen semanal) y PDF: la misma cobertura."""

    def setUp(self):
        self.raw, self.rpe = _raw(), _rpe()
        from local_store import build_load_models, build_weekly_summaries

        self.acwr_dict, self.mono_dict = build_load_models(self.rpe, weeks=None, raw_df=self.raw)
        self.weekly = build_weekly_summaries(self.rpe, _wellness(), self.raw, acwr_dict=self.acwr_dict, today=TODAY)
        self.state = {"raw_df": self.raw, "rpe_df": self.rpe, "wellness_df": _wellness(),
                      "acwr_dict": self.acwr_dict, "mono_dict": self.mono_dict}

    def test_same_number_in_app_dashboard_and_pdf(self):
        table, team_pct = team_registration_table(
            raw_df=self.raw, rpe_df=self.rpe, wellness_df=_wellness(), reference_date=TODAY
        )
        kpi = dict(zip(table["Atleta"], table["RPE %"]))
        by_key = coverage_by_athlete(self.raw, self.rpe, TODAY)
        weekly_load = self.weekly["weekly_load"]
        for athlete in ATHLETES:
            with self.subTest(athlete=athlete):
                pdf = rg.athlete_registration_coverage(self.state, athlete, TODAY)
                self.assertEqual(round(pdf.pct), kpi[athlete])
                self.assertEqual(pdf.coverage, by_key[athlete.casefold()].coverage)
                model = self.acwr_dict.get(athlete)
                if model is not None:  # sin ningun sRPE no hay modelo de carga
                    # El modelo y el resumen semanal leen la cobertura al ultimo
                    # dia entrenado (viernes): la misma que el PDF a esa fecha.
                    last = latest_training_day_row(model).iloc[0]
                    at_last = rg.athlete_registration_coverage(self.state, athlete, last["Date"])
                    self.assertAlmostEqual(last["Cobertura_RPE_28d"], at_last.coverage)
                    week = weekly_load[(weekly_load["Athlete"] == athlete)
                                       & (pd.to_datetime(weekly_load["week_start"]) == TODAY - pd.Timedelta(days=6))]
                    self.assertAlmostEqual(float(week["rpe_coverage_28d"].iloc[0]), at_last.coverage)
        # Total del equipo = suma con RPE / suma de sesiones (100, 70, 50, 0 y 70%).
        self.assertAlmostEqual(team_pct, 100 * (20 + 14 + 10 + 0 + 14) / 100)

    def test_kpi_table_sorted_ascending_with_wellness(self):
        table, _ = team_registration_table(
            raw_df=self.raw, rpe_df=self.rpe, wellness_df=_wellness(), reference_date=TODAY
        )
        self.assertEqual(table["RPE %"].tolist(), sorted(table["RPE %"].tolist()))
        self.assertEqual(table.iloc[0]["Atleta"], "Cero Registro")
        self.assertEqual(table.iloc[0]["Te faltan"], 14)
        cien = table[table["Atleta"] == "Cien Total"].iloc[0]
        self.assertEqual(cien["Bienestar %"], 50)

    def test_professional_pdf_row_and_gate(self):
        from modules.app_clock import frozen_app_now

        with frozen_app_now(TODAY + pd.Timedelta(hours=12)):
            low = dict(rg._build_professional_load_tolerance_payload(self.state, "Cincuenta Media", {})["rows"])
        self.assertIn("Registrá tu RPE: te faltan 4 sesiones", low["ACWR EWMA"])
        self.assertEqual(low["RPE registrado (28 d)"].split(" de ")[0], "50%")
        high = dict(rg._build_professional_load_tolerance_payload(self.state, "Cien Total", {})["rows"])
        self.assertRegex(high["ACWR EWMA"], r"^\d")


class AthleteNextStepsTest(unittest.TestCase):
    def test_low_coverage_adds_the_rpe_step_with_count(self):
        steps = ar.next_steps(
            has_evaluation=True, has_comparison=False, evaluation_stale=False,
            load_available=True, wellness_available=False, audience="atleta", rpe_missing=4,
        )
        self.assertLessEqual(len(steps), NEXT_STEPS_MAX)
        self.assertIn("Registrá tu RPE al terminar cada sesión: te faltan 4 para ver tu carga.", steps)

    def test_high_coverage_keeps_previous_steps(self):
        steps = ar.next_steps(
            has_evaluation=True, has_comparison=True, evaluation_stale=False,
            load_available=True, wellness_available=True, audience="atleta", rpe_missing=None,
        )
        self.assertFalse(any("RPE" in step for step in steps))

    def test_tolerance_hides_weeks_under_seventy_percent(self):
        wellness = pd.DataFrame([
            {"Athlete": "Cincuenta Media", "Date": day, "Sueno_hs": 7, "Estres": 6, "Dolor": 6, "Wellness_Score": 19.0}
            for day in SESSIONS[-30:]
        ])
        rpe = _rpe()
        without = ar.tolerance_reading(wellness, rpe, "Cincuenta Media", today=TODAY)
        gated = ar.tolerance_reading(wellness, rpe, "Cincuenta Media", today=TODAY, raw_df=_raw())
        self.assertGreater(len(without["weekly_load"]), 0)
        self.assertEqual(len(gated["weekly_load"]), 0)
        self.assertEqual(gated["hidden_load_weeks"], len(without["weekly_load"]))


if __name__ == "__main__":
    unittest.main()
