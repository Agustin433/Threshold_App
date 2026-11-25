"""PR S: carga interna condicionada por la cobertura de sRPE.

cobertura = sesiones completadas (Raw Workouts, fecha de sesion) con sRPE /
sesiones completadas, en 28 dias o por semana calendario. ACWR con >= 70% en
28 dias; monotonia/strain con >= 70% en la semana y >= 4 sesiones. Debajo:
"Registra tu RPE en cada sesion: con N seguidas ves tu carga (~dd/mm)", con N
proyectado hacia adelante (el RPE pasado no se recupera).
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
    count_in_window,
    habitual_weekdays,
    projection_label,
    sessions_to_target,
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


def _oracle(sessions, logged, reference):
    """Simulacion dia a dia independiente de sessions_to_target (la del enunciado)."""
    reference = pd.Timestamp(reference).normalize()

    def meets(all_sessions, all_logged, day):
        total, with_rpe = count_in_window(all_sessions, all_logged, day - pd.Timedelta(days=27), day)
        return total > 0 and with_rpe / total >= 0.7 - 1e-9

    sessions = [pd.Timestamp(d) for d in sessions if pd.Timestamp(d) <= reference]
    logged = [pd.Timestamp(d) for d in logged]
    if meets(sessions, logged, reference):
        return 0, reference
    recent = [d for d in sessions if d > reference - pd.Timedelta(days=28)]
    counts = pd.Series([d.weekday() for d in recent]).value_counts()
    habitual = {int(w) for w, c in counts.items() if c >= 2} or {int(w) for w in counts.index}
    if not habitual:
        return None, None
    future = []
    for offset in range(1, 61):
        day = reference + pd.Timedelta(days=offset)
        if day.weekday() in habitual:
            future.append(day)
        if future and meets(sessions + future, logged + future, day):
            return len(future), day
    return None, None


def _plan(weekdays, per_window_logged, *, front_loaded, reference=TODAY, weeks=8):
    """Sesiones en `weekdays` durante `weeks` semanas; en los ultimos 28 dias,
    `per_window_logged` con RPE, repartidas o todas al principio."""
    days = [d for d in pd.date_range(reference - pd.Timedelta(weeks=weeks), reference) if d.weekday() in weekdays]
    window = [d for d in days if d > reference - pd.Timedelta(days=28)]
    if front_loaded:
        logged = window[:per_window_logged]
    else:
        step = len(window) / per_window_logged
        logged = [window[int(i * step)] for i in range(per_window_logged)]
    return days, logged


class SessionsToTargetTest(unittest.TestCase):
    """"Te faltan N" hacia adelante: sesiones futuras seguidas con RPE hasta el 70%."""

    CASES = {
        # nombre: (dias habituales, con RPE en la ventana, al principio)
        "3/sem repartido (5/12 = 42%)": ((0, 2, 4), 5, False),
        "3/sem al principio (5/12 = 42%)": ((0, 2, 4), 5, True),
        "4/sem repartido (7/16 = 44%)": ((0, 1, 3, 4), 7, False),
        "4/sem al principio (7/16 = 44%)": ((0, 1, 3, 4), 7, True),
    }

    def test_four_cases_match_the_day_by_day_simulation(self):
        results = {}
        for name, (weekdays, logged_count, front) in self.CASES.items():
            sessions, logged = _plan(weekdays, logged_count, front_loaded=front)
            with self.subTest(case=name):
                coverage = rpe_coverage(sessions, logged, TODAY)
                self.assertAlmostEqual(coverage.coverage, logged_count / (12 if len(weekdays) == 3 else 16))
                expected = _oracle(sessions, logged, TODAY)
                self.assertIsNotNone(expected[0])
                self.assertEqual(sessions_to_target(sessions, logged, TODAY), expected)
                n, date = expected
                self.assertEqual(
                    coverage.register_text,
                    f"Registrá tu RPE en cada sesión: con {n} seguidas ves tu carga (~{date:%d/%m})",
                )
                self.assertEqual(projection_label(n, date), f"{n} sesiones · ~{date:%d/%m}")
                results[name] = n
        # Con el RPE al principio de la ventana, esas sesiones salen antes: hace
        # falta al menos lo mismo que con el RPE repartido.
        self.assertGreaterEqual(results["3/sem al principio (5/12 = 42%)"], results["3/sem repartido (5/12 = 42%)"])
        self.assertGreaterEqual(results["4/sem al principio (7/16 = 44%)"], results["4/sem repartido (7/16 = 44%)"])

    def test_without_habitual_days_there_is_no_projection(self):
        # Ultima sesion hace 40 dias: nada en los ultimos 28.
        sessions = [TODAY - pd.Timedelta(days=40), TODAY - pd.Timedelta(days=45)]
        self.assertEqual(habitual_weekdays(sessions, TODAY), set())
        self.assertEqual(sessions_to_target(sessions, [], TODAY), (None, None))
        coverage = rpe_coverage(sessions, [], TODAY)
        self.assertEqual(coverage.register_text, "Registrá tu RPE en cada sesión")
        self.assertEqual(projection_label(None, None), "sin proyección")

    def test_single_weekday_falls_back_to_any_session_day(self):
        sessions = [TODAY - pd.Timedelta(days=d) for d in (2, 10)]  # viernes y jueves, una vez cada uno
        self.assertEqual(habitual_weekdays(sessions, TODAY), {3, 4})

    def test_already_meets_has_no_message(self):
        n, date = sessions_to_target(SESSIONS, ATHLETES["Cien Total"], TODAY)
        self.assertEqual(n, 0)
        coverage = rpe_coverage(SESSIONS, ATHLETES["Cien Total"], TODAY)
        self.assertEqual(coverage.register_text, "")

    def test_singular_text(self):
        from modules.rpe_coverage import register_rpe_text

        self.assertEqual(register_rpe_text(1, "2026-12-08"), "Registrá tu RPE en cada sesión: con 1 más ves tu carga (~08/12)")


class AcwrDateAndStreakTest(unittest.TestCase):
    def test_acwr_from_an_earlier_day_shows_its_date(self):
        self.assertEqual(acwr_display_text(1.123, "", value_date="2026-11-20", reference_date="2026-11-22"),
                         "ACWR al 20/11: 1.12")
        self.assertEqual(acwr_display_text(1.123, "", value_date="2026-11-22", reference_date="2026-11-22"), "1.12")

    def test_monday_of_fourth_week_still_forming(self):
        monday = pd.Timestamp("2026-11-23")
        sessions = [d for d in pd.date_range(monday - pd.Timedelta(weeks=3), monday) if d.weekday() in (0, 2, 4)]
        # 3 semanas completas al 100% y el lunes de la 4.a con 1/1.
        coverage = rpe_coverage(sessions, sessions, monday)
        self.assertTrue(coverage.meets)
        self.assertEqual(coverage.streak_weeks, 3)
        self.assertTrue(coverage.forming)
        self.assertEqual(coverage.stable_from, pd.Timestamp("2026-11-30"))
        # El domingo de esa 4.a semana ya cuenta: deja de estar en formacion.
        sunday = monday + pd.Timedelta(days=6)
        full = [d for d in pd.date_range(monday - pd.Timedelta(weeks=3), sunday) if d.weekday() in (0, 2, 4)]
        self.assertFalse(rpe_coverage(full, full, sunday).forming)


class CoverageDefinitionTest(unittest.TestCase):
    def test_four_cases(self):
        expected = {  # (sesiones, con RPE, cumple)
            "Cien Total": (20, 20, True),
            "Setenta Justo": (20, 14, True),
            "Cincuenta Media": (20, 10, False),
            "Cero Registro": (20, 0, False),
        }
        for athlete, (sessions, logged, meets) in expected.items():
            with self.subTest(athlete=athlete):
                coverage = rpe_coverage(SESSIONS, ATHLETES[athlete], TODAY)
                self.assertEqual((coverage.sessions, coverage.logged), (sessions, logged))
                self.assertEqual(coverage.meets, meets)
                n, date = _oracle(SESSIONS, ATHLETES[athlete], TODAY)
                self.assertEqual((coverage.to_target, coverage.target_date), (n, date))
                if meets:
                    self.assertEqual(coverage.register_text, "")

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
                    self.assertEqual(acwr_unavailable_reason(last), "Registrá tu RPE en cada sesión")

    def test_zero_percent_gets_the_register_message(self):
        last = latest_training_day_row(_acwr("Cero Registro")).iloc[0]
        self.assertTrue(pd.isna(last["ACWR_EWMA"]))
        self.assertEqual(acwr_unavailable_reason(last), "Registrá tu RPE en cada sesión")

    def test_chronic_in_formation_legend(self):
        frame = _acwr("Recien Formada")
        last = latest_training_day_row(frame).iloc[0]
        self.assertTrue(pd.notna(last["ACWR_EWMA"]))
        coverage = coverage_from_acwr_frame(frame, last["Date"])
        self.assertTrue(coverage.meets)
        # Ultimo dia entrenado: viernes 20/11. La semana del 16/11 no termino:
        # no suma a la racha (solo la del 09/11).
        self.assertEqual(coverage.streak_weeks, 1)
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
        self.assertNotIn("rpe_missing_for_70", weeks.columns)


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
        n, date = _oracle(SESSIONS, [], TODAY)
        self.assertEqual(table.iloc[0]["Para ver su carga"], f"{n} sesiones · ~{date:%d/%m}")
        self.assertEqual(table[table["Atleta"] == "Cien Total"].iloc[0]["Para ver su carga"], "—")
        cien = table[table["Atleta"] == "Cien Total"].iloc[0]
        self.assertEqual(cien["Bienestar %"], 50)

    def test_professional_pdf_row_and_gate(self):
        from modules.app_clock import frozen_app_now

        with frozen_app_now(TODAY + pd.Timedelta(hours=12)):
            low = dict(rg._build_professional_load_tolerance_payload(self.state, "Cincuenta Media", {})["rows"])
        n, date = _oracle(SESSIONS, ATHLETES["Cincuenta Media"], TODAY)
        self.assertIn(f"Registrá tu RPE en cada sesión: con {n} seguidas ves tu carga (~{date:%d/%m})", low["ACWR EWMA"])
        self.assertEqual(low["RPE registrado (28 d)"].split(" de ")[0], "50%")
        high = dict(rg._build_professional_load_tolerance_payload(self.state, "Cien Total", {})["rows"])
        # Ultima sesion el viernes 20/11, PDF del domingo 22/11: el valor lleva su fecha.
        self.assertRegex(high["ACWR EWMA"], r"^ACWR al 20/11: \d\.\d\d$")


class AthleteNextStepsTest(unittest.TestCase):
    def test_low_coverage_adds_the_rpe_step_with_count(self):
        steps = ar.next_steps(
            has_evaluation=True, has_comparison=False, evaluation_stale=False,
            load_available=True, wellness_available=False, audience="atleta",
            rpe_step="Registrá tu RPE en cada sesión: con 6 seguidas ves tu carga (~08/12)",
        )
        self.assertLessEqual(len(steps), NEXT_STEPS_MAX)
        self.assertIn("Registrá tu RPE en cada sesión: con 6 seguidas ves tu carga (~08/12).", steps)

    def test_high_coverage_keeps_previous_steps(self):
        steps = ar.next_steps(
            has_evaluation=True, has_comparison=True, evaluation_stale=False,
            load_available=True, wellness_available=True, audience="atleta", rpe_step=None,
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
