"""PR A: validez y coherencia de numeros antes del PR de reportes.

1. Altura por impulso vs tiempo de vuelo (CMJ/SJ), con las tomas reales.
2. Umbral de cambio = max(TE, SWC) en todas las variables.
3. Una sola fuente de z-score en el PDF profe (tabla, cuadrantes y radar).
4. Adherencia: sin completion fechado no se muestra el tile.
"""

from __future__ import annotations

import math
import re
import unicodedata
import unittest
from datetime import datetime as real_datetime
from io import BytesIO

import numpy as np
import pandas as pd
from pypdf import PdfReader

import modules.report_generator as rg
from modules.app_clock import frozen_app_now
from modules.evaluation_rules import (
    INSTRUMENT_TYPICAL_ERROR_PCT,
    JUMP_HEIGHT_FLAG_COLUMN,
    PLATFORM_BW_FLAG_COLUMN,
    flight_time_height_cm,
    is_jump_height_inconsistent,
    jump_height_consistency_label,
    jump_height_consistency_rows,
    resolve_change_threshold,
)
from modules.jump_analysis import (
    NO_IMPULSE_COMPARISON_SIGNAL,
    _prepare_jump_df,
    build_jump_delta_display_table,
    compare_flight_time_height,
    compute_swc_delta,
    build_composite_profile_snapshot,
    build_jump_flag_rows,
    build_profile_radar_row,
    resolve_zscore,
)
from modules.remote_store import jump_df_to_db_records

# ── Tomas reales (Supabase, 04/11/2026): altura informada y tiempo de vuelo ──
# (atleta, fecha, test, altura informada cm, tiempo de vuelo ms)
REAL_INCONSISTENT = [
    ("Agustin Giffon", "2026-05-22", "CMJ", 58.0, 547),
    ("Agustin Giffon", "2026-05-22", "SJ", 46.02, 507),
    ("Exequiel Heredia Garcia", "2026-05-16", "CMJ", 50.0, 561),
    ("Exequiel Heredia Garcia", "2026-05-16", "SJ", 42.9, 537),
    ("Carlos Palazzo", "2026-01-29", "CMJ", 46.18, 537),
    ("Carlos Palazzo", "2026-01-29", "SJ", 29.06, 429),
    ("Mariano Burgos", "2025-12-19", "CMJ", 44.4, 540),
    ("Mariano Burgos", "2025-12-19", "SJ", 39.25, 518),
    ("Pablo Holgado", "2026-02-02", "SJ", 52.0, 520),
]
# Tomas de oct-2026 (pesaje corregido): altura e impulso cierran con el vuelo.
REAL_CONSISTENT_OCT_2026 = [
    ("Ignacio De La Vega", "2026-10-08", "CMJ", 46.04, 614),
    ("Ignacio De La Vega", "2026-10-08", "SJ", 43.55, 596),
    ("Nicolas Angelilli", "2026-10-19", "CMJ", 33.97, 528),
    ("Tomas De La Vega", "2026-10-21", "CMJ", 43.62, 599),
    ("Pablo Holgado", "2026-10-22", "CMJ", 51.32, 648),
    ("Fernando Habib", "2026-10-23", "CMJ", 30.44, 499),
    ("Agustin Esterman", "2026-10-30", "CMJ", 52.65, 657),
]


def _platform_rows(cases: list[tuple[str, str, str, float, int]]) -> pd.DataFrame:
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for athlete, date, test, height, flight_ms in cases:
        row = rows.setdefault(
            (athlete, date),
            {"Athlete": athlete, "Date": date, "Source": "platform", "BW_kg": 75.0},
        )
        row[f"{test}_cm"] = height
        row[f"{test}_flight_ms"] = flight_ms
        # Marcador de cinematica de plataforma (regla 6): con peso valido no
        # descarta nada, pero confirma que la toma es de plataforma.
        row[f"{test}_takeoff_velocity_m_s"] = math.sqrt(2 * 9.81 * height / 100)
    return pd.DataFrame(rows.values())


class JumpHeightConsistencyTests(unittest.TestCase):
    def test_flight_height_formula(self):
        # Giffon 22/05/2026: 547 ms -> 36.7 cm (g * t^2 / 8).
        self.assertAlmostEqual(flight_time_height_cm(547), 36.69, places=2)
        self.assertIsNone(flight_time_height_cm(None))
        self.assertIsNone(flight_time_height_cm(0))

    def test_cited_real_takes_are_flagged(self):
        for athlete, date, test, height, flight_ms in REAL_INCONSISTENT:
            with self.subTest(athlete=athlete, date=date, test=test):
                self.assertTrue(is_jump_height_inconsistent(height, flight_ms))

    def test_october_2026_takes_are_not_flagged(self):
        for athlete, date, test, height, flight_ms in REAL_CONSISTENT_OCT_2026:
            with self.subTest(athlete=athlete, date=date, test=test):
                self.assertFalse(is_jump_height_inconsistent(height, flight_ms))

    def test_tolerance_is_max_of_3cm_and_8pct(self):
        # 657 ms -> 52.9 cm: 8% = 4.2 cm manda sobre 3 cm.
        self.assertFalse(is_jump_height_inconsistent(52.94 + 4.1, 657))
        self.assertTrue(is_jump_height_inconsistent(52.94 + 4.4, 657))
        # 427 ms -> 22.4 cm: 8% = 1.8 cm, manda el piso de 3 cm.
        self.assertFalse(is_jump_height_inconsistent(22.36 + 2.9, 427))
        self.assertTrue(is_jump_height_inconsistent(22.36 + 3.1, 427))

    def test_flagged_height_leaves_every_calculation(self):
        prepared = _prepare_jump_df(_platform_rows(REAL_INCONSISTENT + REAL_CONSISTENT_OCT_2026))
        giffon = prepared[prepared["Athlete"] == "Agustin Giffon"].iloc[0]
        self.assertEqual(giffon[JUMP_HEIGHT_FLAG_COLUMN], "CMJ,SJ")
        for column in ("CMJ_cm", "SJ_cm", "EUR", "Jump_Momentum", "CMJ_Z", "SJ_Z", "EUR_Z"):
            self.assertTrue(pd.isna(giffon.get(column)), column)
        self.assertAlmostEqual(float(giffon["CMJ_cm_reported"]), 58.0)
        self.assertAlmostEqual(float(giffon["CMJ_flight_height_cm"]), 36.7, places=1)

        holgado = prepared[(prepared["Athlete"] == "Pablo Holgado")].set_index("Date")
        feb = holgado.loc[pd.Timestamp("2026-02-02")]
        oct_ = holgado.loc[pd.Timestamp("2026-10-22")]
        self.assertEqual(feb[JUMP_HEIGHT_FLAG_COLUMN], "SJ")
        self.assertTrue(pd.isna(feb["SJ_cm"]))
        self.assertTrue(pd.isna(oct_[JUMP_HEIGHT_FLAG_COLUMN]))
        self.assertAlmostEqual(float(oct_["CMJ_cm"]), 51.32)

        for athlete, date, _, _, _ in REAL_CONSISTENT_OCT_2026:
            row = prepared[(prepared["Athlete"] == athlete) & (prepared["Date"] == pd.Timestamp(date))].iloc[0]
            self.assertTrue(pd.isna(row[JUMP_HEIGHT_FLAG_COLUMN]), athlete)

    def test_flag_survives_re_preparation(self):
        once = _prepare_jump_df(_platform_rows(REAL_INCONSISTENT))
        twice = _prepare_jump_df(once)
        self.assertEqual(
            sorted((r["Athlete"], r["Test"]) for r in jump_height_consistency_rows(once)),
            sorted((r["Athlete"], r["Test"]) for r in jump_height_consistency_rows(twice)),
        )
        self.assertEqual(len(jump_height_consistency_rows(twice)), len(REAL_INCONSISTENT))

    def test_not_written_back_to_supabase(self):
        prepared = _prepare_jump_df(_platform_rows(REAL_INCONSISTENT[:2]))
        records = jump_df_to_db_records(prepared)
        self.assertEqual(len(records), 1)
        self.assertNotIn("cmj_cm", records[0])
        self.assertFalse(any("reported" in key or "flight_height" in key for key in records[0]))

    def test_non_platform_source_is_not_evaluated(self):
        frame = _platform_rows(REAL_INCONSISTENT[:1])
        # MyJump2/alfombra: la altura ya sale del vuelo, no hay impulso.
        frame["Source"] = "nonplatform"
        prepared = _prepare_jump_df(frame)
        self.assertTrue(pd.isna(prepared.iloc[0][JUMP_HEIGHT_FLAG_COLUMN]))
        self.assertAlmostEqual(float(prepared.iloc[0]["CMJ_cm"]), 58.0)

    def test_invalid_body_weight_is_labelled_by_rule_6_not_twice(self):
        # Palazzo 07/05/2026: sin peso. Ya lo descarta la regla 6.
        frame = pd.DataFrame(
            [{
                "Athlete": "Carlos Palazzo", "Date": "2026-05-07", "Source": "platform", "BW_kg": None,
                "CMJ_cm": 47.61, "CMJ_flight_ms": 635, "CMJ_takeoff_velocity_m_s": 3.06,
            }]
        )
        row = _prepare_jump_df(frame).iloc[0]
        self.assertEqual(row[PLATFORM_BW_FLAG_COLUMN], "CMJ")
        self.assertTrue(pd.isna(row[JUMP_HEIGHT_FLAG_COLUMN]))

    def test_flight_height_only_in_professional_pdf_lines(self):
        prepared = _prepare_jump_df(_platform_rows(REAL_INCONSISTENT[:2]))
        row = prepared.iloc[0]
        dashboard_label = jump_height_consistency_label(row) or ""
        self.assertIn("inconsistente con tiempo de vuelo", dashboard_label)
        self.assertNotIn("36.7", dashboard_label)
        self.assertTrue(any("inconsistente" in flag["text"] for flag in build_jump_flag_rows(row)))

        lines = rg._professional_jump_height_quality_lines(prepared)
        self.assertEqual(len(lines), 2)
        self.assertIn("altura informada (impulso) 58.0 cm", lines[0])
        self.assertIn("altura por tiempo de vuelo 36.7 cm", lines[0])
        self.assertIn("22/05/2026", lines[0])


# ── 2. Umbral de cambio ────────────────────────────────────────────────────
class ChangeThresholdTests(unittest.TestCase):
    def test_sj_with_three_takes_never_below_instrument_noise(self):
        # SJ de Ignacio De La Vega (nov-25 a may-26) antes de este PR: Hopkins
        # 0.2·SD daba 0.58 cm, por debajo del 3% del instrumento (1.22 cm).
        history = [36.83, 38.18, 40.64]
        result = resolve_change_threshold("SJ_cm", 40.64, history, swc_pct=1.5)
        sd = float(np.std(history, ddof=1))
        self.assertLess(0.2 * sd, 0.6)
        self.assertEqual(result["method"], "TE instrumento")
        self.assertAlmostEqual(result["threshold_abs"], 40.64 * 0.03)
        self.assertEqual(result["label"], "TE instrumento 3%, N=3")

    def test_threshold_is_max_of_te_and_swc_for_every_variable(self):
        histories = {
            "few": [40.0, 41.0],
            "stable": [40.0, 40.2, 40.1, 40.3],
            "noisy": [40.0, 44.0, 39.0, 45.0],
        }
        for variable, te_pct in INSTRUMENT_TYPICAL_ERROR_PCT.items():
            for name, raw in histories.items():
                with self.subTest(variable=variable, history=name):
                    values = [v * (10 if variable.startswith("IMTP_N") else 1) for v in raw]
                    previous = values[-1]
                    result = resolve_change_threshold(variable, previous, values, swc_pct=1.5)
                    te_instr = previous * te_pct / 100
                    if len(values) >= 3:
                        swc = 0.2 * float(np.std(values, ddof=1))
                        te_intra = float(np.std(np.diff(values), ddof=1) / math.sqrt(2))
                        expected = max(te_instr, te_intra, swc)
                    else:
                        expected = max(te_instr, previous * 1.5 / 100)
                    self.assertAlmostEqual(result["threshold_abs"], expected)
                    self.assertGreaterEqual(result["threshold_abs"] + 1e-12, te_instr)


# ── 3. Una sola fuente de z en el PDF profe ───────────────────────────────
def _cohort_team() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plantel de futbol recreativo con cohorte suficiente (z de cohorte)."""
    rng = np.random.default_rng(7)
    athletes = [f"Atleta {idx:02d}" for idx in range(1, 11)]
    rows = []
    for idx, athlete in enumerate(athletes):
        for date, bump in (("2026-05-10", 0.0), ("2026-10-10", 1.5)):
            rows.append(
                {
                    "Athlete": athlete,
                    "Date": date,
                    "Source": "platform",
                    "BW_kg": 70 + idx,
                    "CMJ_cm": round(34 + idx * 1.1 + bump + rng.normal(0, 0.8), 2),
                    "SJ_cm": round(31 + idx * 0.9 + bump + rng.normal(0, 0.8), 2),
                    "DJ_cm": round(28 + idx * 0.7 + rng.normal(0, 0.8), 2),
                    "DJ_tc_ms": round(230 - idx * 4 + rng.normal(0, 5)),
                    "DJ_drop_height_cm": 30.0,
                    "IMTP_N": round(2200 + idx * 80 + rng.normal(0, 40)),
                }
            )
    profiles = pd.DataFrame(
        [{"Athlete": a, "Sexo": "Masculino", "Nivel": "Recreativo", "Deporte": "Fútbol"} for a in athletes]
    )
    return pd.DataFrame(rows), profiles


class SingleZSourceTests(unittest.TestCase):
    ATHLETE = "Atleta 04"
    METRICS = {"SJ": "SJ_Z", "CMJ": "CMJ_Z", "DRI": "DRI_Z", "EUR": "EUR_Z"}

    def setUp(self):
        jump_df, profiles = _cohort_team()
        self.state = {"jump_df": jump_df, "athlete_profile_df": profiles}

    def test_table_and_quadrant_source_rows_show_the_same_z(self):
        payload = rg._build_professional_composite_profile_payload(self.state, self.ATHLETE)
        table = payload["metric_table"].set_index("Variable")
        team = rg._professional_latest_team_jump_rows(self.state)
        quadrant_row = team[team["Athlete"] == self.ATHLETE].iloc[0]
        self.assertEqual(quadrant_row["CMJ_Z_source"], "cohort_z")
        for label, z_col in self.METRICS.items():
            with self.subTest(metric=label):
                expected = resolve_zscore(quadrant_row, z_col)
                self.assertIsNotNone(expected)
                self.assertAlmostEqual(float(table.loc[label, "Z-score"]), round(float(expected), 2))

    def test_quadrant_sections_match_table(self):
        payload = rg._build_professional_composite_profile_payload(self.state, self.ATHLETE)
        table = payload["metric_table"].set_index("Variable")
        sections = {s["meaning_type"]: s for s in rg._build_professional_quadrant_sections(self.state, self.ATHLETE)}
        dri_sj = sections["dri_sj"]["selected"]
        eur_cmj = sections["eur_cmj"]["selected"]
        self.assertAlmostEqual(dri_sj["x"], float(table.loc["DRI", "Z-score"]))
        self.assertAlmostEqual(dri_sj["y"], float(table.loc["SJ", "Z-score"]))
        self.assertAlmostEqual(eur_cmj["x"], float(table.loc["EUR", "Z-score"]))
        self.assertAlmostEqual(eur_cmj["y"], float(table.loc["CMJ", "Z-score"]))

    def test_re_preparing_athlete_history_no_longer_overwrites_cohort_z(self):
        history = rg._professional_jump_history(self.state, self.ATHLETE)
        snapshot, _ = build_composite_profile_snapshot(history)
        radar = build_profile_radar_row(history)
        latest = history.sort_values("Date").iloc[-1]
        for z_col in self.METRICS.values():
            with self.subTest(z=z_col):
                self.assertAlmostEqual(resolve_zscore(snapshot, z_col), resolve_zscore(latest, z_col))
                self.assertAlmostEqual(resolve_zscore(radar, z_col), resolve_zscore(latest, z_col))
        # El bug: re-preparar el subset crudo del atleta sin cohorte da otro z.
        raw_subset = self.state["jump_df"][self.state["jump_df"]["Athlete"] == self.ATHLETE]
        literature_snapshot, _ = build_composite_profile_snapshot(raw_subset)
        self.assertNotEqual(snapshot.get("CMJ_Z_source"), literature_snapshot.get("CMJ_Z_source"))


# ── PR A2: dependientes de v y serie por tiempo de vuelo ──────────────────
def _history(rows: list[dict[str, object]]) -> pd.DataFrame:
    base = {"Source": "platform", "BW_kg": 80.0}
    return pd.DataFrame([{**base, **row} for row in rows])


# Ignacio De La Vega (Supabase): CMJ 17/12/2025 y SJ 20/05/2026 marcados.
IDLV = [
    {"Athlete": "Ignacio De La Vega", "Date": "2025-11-04", "CMJ_cm": 35.51, "CMJ_flight_ms": 528},
    {"Athlete": "Ignacio De La Vega", "Date": "2025-12-17", "CMJ_cm": 42.54, "CMJ_flight_ms": 561},
    {"Athlete": "Ignacio De La Vega", "Date": "2026-05-20", "CMJ_cm": 41.1, "CMJ_flight_ms": 570,
     "SJ_cm": 40.64, "SJ_flight_ms": 536},
    {"Athlete": "Ignacio De La Vega", "Date": "2026-10-08", "CMJ_cm": 46.04, "CMJ_flight_ms": 614,
     "SJ_cm": 43.55, "SJ_flight_ms": 596},
]
# Tomas De La Vega: CMJ 13/11/2025 marcado (41.78 vs 36.7 por vuelo).
TDLV = [
    {"Athlete": "Tomas De La Vega", "Date": "2025-11-13", "CMJ_cm": 41.78, "CMJ_flight_ms": 547},
    {"Athlete": "Tomas De La Vega", "Date": "2026-10-21", "CMJ_cm": 43.62, "CMJ_flight_ms": 599},
]


class VelocityDependentExclusionTests(unittest.TestCase):
    def test_velocity_derived_variables_are_excluded_and_forces_kept(self):
        # Giffon 22/05/2026: CMJ 58.0 cm vs 36.7 por vuelo, v = 3.36 m/s.
        row = _history([{
            "Athlete": "Agustin Giffon", "Date": "2026-05-22", "BW_kg": 77.0,
            "CMJ_cm": 58.0, "CMJ_flight_ms": 547, "CMJ_takeoff_velocity_m_s": 3.36,
            "CMJ_rel_impulse": 3.3, "CMJ_peak_power_W": 5200.0, "CMJ_RSI": 0.85,
            "CMJ_brake_ms": 230.0, "CMJ_conc_ms": 260.0, "CMJ_braking_RFD_N_s": 5000.0,
            "CMJ_propulsive_RFD_N_s": 4000.0, "CMJ_landing_stiffness_N_m": 9000.0,
            "CMJ_propulsive_PF_N": 2300.0, "CMJ_braking_PF_L_N": 1100.0, "CMJ_landing_force_N": 3722.0,
            "CMJ_asym_pct": 4.0, "CMJ_contraction_ms": 680.0,
            "SJ_cm": 46.02, "SJ_flight_ms": 507, "SJ_takeoff_velocity_m_s": 3.0,
            "SJ_rel_impulse": 3.0, "SJ_peak_power_W": 4800.0, "SJ_RSI": 1.2, "SJ_peak_force_N": 2100.0,
            "IMTP_N": 3000.0,
        }])
        prepared = _prepare_jump_df(row).iloc[0]
        excluded = (
            "CMJ_takeoff_velocity_m_s", "CMJ_rel_impulse", "CMJ_peak_power_W", "CMJ_RSI",
            "CMJ_brake_ms", "CMJ_conc_ms", "CMJ_braking_RFD_N_s", "CMJ_propulsive_RFD_N_s",
            "CMJ_landing_stiffness_N_m", "Jump_Momentum", "CMJ_rel_impulse_Z",
            "SJ_takeoff_velocity_m_s", "SJ_rel_impulse", "SJ_peak_power_W", "SJ_RSI",
        )
        for column in excluded:
            self.assertTrue(pd.isna(prepared.get(column)), column)
        kept = {
            "CMJ_propulsive_PF_N": 2300.0, "CMJ_braking_PF_L_N": 1100.0, "CMJ_landing_force_N": 3722.0,
            "CMJ_asym_pct": 4.0, "CMJ_contraction_ms": 680.0, "CMJ_flight_ms": 547,
            "SJ_peak_force_N": 2100.0, "IMTP_N": 3000.0,
        }
        for column, value in kept.items():
            self.assertAlmostEqual(float(prepared[column]), value, msg=column)

    def test_unflagged_take_keeps_velocity_variables(self):
        row = _history([{**TDLV[1], "CMJ_takeoff_velocity_m_s": 2.93, "CMJ_peak_power_W": 4100.0}])
        prepared = _prepare_jump_df(row).iloc[0]
        self.assertAlmostEqual(float(prepared["CMJ_takeoff_velocity_m_s"]), 2.93)
        self.assertAlmostEqual(float(prepared["CMJ_peak_power_W"]), 4100.0)


class FlightTimeSeriesTests(unittest.TestCase):
    def test_series_exists_for_every_take_with_flight_time(self):
        prepared = _prepare_jump_df(_history(IDLV + TDLV))
        self.assertTrue(prepared["CMJ_ft_cm"].notna().all())
        flagged = prepared[(prepared["Athlete"] == "Tomas De La Vega")].iloc[0]
        self.assertTrue(pd.isna(flagged["CMJ_cm"]))
        self.assertAlmostEqual(float(flagged["CMJ_ft_cm"]), 36.69, places=2)

    def test_flight_series_never_enters_z_radar_or_db(self):
        prepared = _prepare_jump_df(_history(IDLV))
        self.assertFalse(any(col.startswith(("CMJ_ft", "SJ_ft")) and col.endswith("_Z") for col in prepared.columns))
        records = jump_df_to_db_records(prepared)
        self.assertFalse(any("ft_cm" in key for record in records for key in record))

    def test_idlv_cmj_20_05_to_08_10_2026(self):
        prepared = _prepare_jump_df(_history(IDLV))
        result = compare_flight_time_height(prepared, "CMJ", current_date="2026-10-08", previous_date="2026-05-20")
        self.assertAlmostEqual(result["Valor_anterior"], 39.8, places=1)
        self.assertAlmostEqual(result["Valor_actual"], 46.2, places=1)
        self.assertEqual(result["Label"], "CMJ (por tiempo de vuelo)")
        self.assertEqual(result["Signal"], "mejora relevante")
        values = prepared.sort_values("Date")["CMJ_ft_cm"].tolist()
        expected = max(
            39.84 * 0.03,
            float(np.std(np.diff(values), ddof=1) / math.sqrt(2)),
            0.2 * float(np.std(values, ddof=1)),
        )
        self.assertAlmostEqual(result["Threshold_abs"], expected, places=6)

    def test_tdlv_cmj_13_11_2025_to_21_10_2026(self):
        prepared = _prepare_jump_df(_history(TDLV))
        result = compare_flight_time_height(prepared, "CMJ")
        self.assertAlmostEqual(result["Valor_anterior"], 36.7, places=1)
        self.assertAlmostEqual(result["Valor_actual"], 44.0, places=1)
        self.assertEqual(result["Fecha_anterior"], pd.Timestamp("2025-11-13"))
        self.assertEqual(result["Threshold_label"], "TE instrumento 3%")
        self.assertEqual(result["Signal"], "mejora relevante")

    def test_flight_comparison_does_not_cross_sources(self):
        rows = _history(TDLV)
        rows.loc[0, "Source"] = "nonplatform"
        self.assertIsNone(compare_flight_time_height(_prepare_jump_df(rows), "CMJ"))


class ImpulseComparisonBlockedTests(unittest.TestCase):
    def test_impulse_row_not_compared_across_a_flagged_take(self):
        prepared = _prepare_jump_df(_history(TDLV))
        delta = compute_swc_delta(prepared, "2026-10-21").set_index("Variable")
        self.assertEqual(delta.loc["CMJ_cm", "Signal"], NO_IMPULSE_COMPARISON_SIGNAL)
        self.assertTrue(pd.isna(delta.loc["CMJ_cm", "Valor_anterior"]))

    def test_older_valid_take_is_not_used_when_the_last_one_is_flagged(self):
        # IDLV SJ: 20/05 marcado; no se compara contra nada mas viejo.
        prepared = _prepare_jump_df(_history(IDLV))
        delta = compute_swc_delta(prepared, "2026-10-08").set_index("Variable")
        self.assertEqual(delta.loc["SJ_cm", "Signal"], NO_IMPULSE_COMPARISON_SIGNAL)
        # CMJ 20/05 es consistente: la comparacion por impulso sigue.
        self.assertAlmostEqual(float(delta.loc["CMJ_cm", "Valor_anterior"]), 41.1)

    def test_professional_change_table_adds_labelled_flight_row(self):
        state = {"jump_df": _history(TDLV)}
        payload = rg._build_professional_change_payload(state, "Tomas De La Vega")
        table = payload["display_table"].set_index("Variable")
        self.assertIn("no comparable", table.loc["CMJ", "Senal"])
        flight = table.loc["CMJ (por tiempo de vuelo)"]
        self.assertEqual(flight["Anterior"], "36.7")
        self.assertEqual(flight["Actual"], "44.0")
        self.assertIn("mejora relevante", flight["Senal"])
        labels = list(payload["display_table"]["Variable"])
        self.assertEqual(labels.index("CMJ (por tiempo de vuelo)"), labels.index("CMJ") + 1)

    def test_no_flight_row_when_impulse_comparison_is_possible(self):
        state = {"jump_df": _history(IDLV)}
        labels = list(rg._build_professional_change_payload(state, "Ignacio De La Vega")["display_table"]["Variable"])
        self.assertNotIn("CMJ (por tiempo de vuelo)", labels)
        self.assertIn("SJ (por tiempo de vuelo)", labels)


# ── 4. Adherencia ──────────────────────────────────────────────────────────
class _FixedDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


def _normalized_pdf_text(pdf: bytes) -> str:
    text = " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", text)


def _adherence_state(completion_df: pd.DataFrame) -> dict[str, object]:
    return {
        "rpe_df": pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-28", "sRPE": 320},
                {"Athlete": "Ana Lopez", "Date": "2026-05-04", "sRPE": 300},
            ]
        ),
        "wellness_df": None,
        "completion_df": completion_df,
        "jump_df": pd.DataFrame(
            [{"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 32, "SJ_cm": 29, "IMTP_N": 1800}]
        ),
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
    }


# Forma real de completion_df en Supabase: totales del periodo, sin fecha.
UNDATED_COMPLETION = pd.DataFrame(
    [{
        "Athlete": "Ana Lopez", "Assigned": 387, "Completed": 300, "Percent": "77.5%", "Pct": 77.5,
        "completion_scope": "uploaded_period_total", "source_type": "completion_report_summary",
    }]
)


class AdherenceTileTests(unittest.TestCase):
    def test_undated_period_total_has_no_window_value(self):
        state = _adherence_state(UNDATED_COMPLETION)
        self.assertIsNone(rg._focus_completion_value(state, "Ana Lopez"))

    def test_athlete_pdf_hides_tile_without_dated_completion(self):
        with frozen_app_now(_FixedDate.now()):
            pdf = rg.generate_visual_report_pdf(_adherence_state(UNDATED_COMPLETION), "Ana Lopez", "atleta")
        self.assertIsNotNone(pdf)
        text = _normalized_pdf_text(pdf)
        self.assertNotIn("adherencia todavia no registrado", text)
        self.assertNotIn("77.5%", text)

    def test_athlete_pdf_shows_tile_with_dated_completion(self):
        dated = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-05-04", "Assigned": 10, "Completed": 9, "Pct": 90}])
        with frozen_app_now(_FixedDate.now()):
            pdf = rg.generate_visual_report_pdf(_adherence_state(dated), "Ana Lopez", "atleta")
        self.assertIn("90.0%", _normalized_pdf_text(pdf))


if __name__ == "__main__":
    unittest.main()
