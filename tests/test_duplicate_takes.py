"""Regla 8 (toma duplicada con fecha distinta) y regla 5 sin pares identicos.

Casos reales de `evaluations` (noviembre 2026):
- Agustin Giffon: el mismo IMTP guardado el 22/05/2025 y el 22/05/2026
  (17 de 17 metricas identicas, cargados el 03/11 en la misma cola).
- Santiago Gray, DJ 17/12/2025 vs 07/05/2026: tomas reales distintas que
  coinciden en altura y tiempo de vuelo (2 de 8, la altura sale del vuelo).
"""

from __future__ import annotations

import unittest

import pandas as pd

from modules.evaluation_rules import (
    check_duplicate_take,
    drop_identical_consecutive_takes,
    find_duplicate_takes,
    resolve_change_threshold,
)

GIFFON_IMTP = {
    "IMTP_N": 3084.0,
    "IMTP_asym_pct": -16.39,
    "IMTP_force_L_N": 1404.0,
    "IMTP_force_R_N": 1679.0,
    "IMTP_pretension": 1118.0,
    "IMTP_rfd_100_N_s": 6237.0,
    "IMTP_time_max_s": 3.0,
    "IMTP_time_pull_s": 3.0,
}


def _imtp(date: str, **overrides):
    record = {"Athlete": "Agustin Giffon", "Date": date, "Source": "platform", **GIFFON_IMTP}
    record.update(overrides)
    record["__metric_fields"] = sorted(k for k in record if k.startswith("IMTP_"))
    return record


def _gray_dj(date: str, tc: float, rsi: float):
    record = {
        "Athlete": "Santiago Gray",
        "Date": date,
        "Source": "platform",
        "DJ_cm": 35.0,
        "DJ_flight_ms": 534.0,
        "DJ_tc_ms": tc,
        "DJ_RSI": rsi,
        "DJ_peak_force_N": 4100.0 if tc == 160 else 4321.0,
        "DJ_force_L_N": 2000.0 if tc == 160 else 2150.0,
        "DJ_force_R_N": 2100.0 if tc == 160 else 2171.0,
        "DJ_asym_pct": 4.7 if tc == 160 else 1.0,
        "DJ_drop_height_cm": 30.0,
    }
    record["__metric_fields"] = sorted(k for k in record if k.startswith("DJ_"))
    return record


class DuplicateTakeTests(unittest.TestCase):
    def test_same_imtp_with_shifted_year_is_blocked(self):
        history = pd.DataFrame([_imtp("2025-05-22")])
        message = check_duplicate_take(_imtp("2026-05-22"), history=history)
        self.assertIsNotNone(message)
        self.assertIn("posible toma duplicada con fecha distinta (22/05/2025)", message)
        self.assertIn("No se guardó", message)

    def test_duplicate_inside_the_same_queue_is_blocked(self):
        queued = _imtp("2025-05-22")
        message = check_duplicate_take(_imtp("2026-05-22"), history=None, pending=[queued])
        self.assertIn("22/05/2025", message)

    def test_same_date_is_an_overwrite_not_a_duplicate(self):
        history = pd.DataFrame([_imtp("2026-05-22")])
        self.assertIsNone(check_duplicate_take(_imtp("2026-05-22"), history=history))

    def test_other_athlete_or_source_is_not_a_duplicate(self):
        other = _imtp("2025-05-22", Athlete="Otro Atleta")
        mat = _imtp("2025-05-22", Source="nonplatform")
        self.assertIsNone(check_duplicate_take(_imtp("2026-05-22"), history=pd.DataFrame([other, mat])))

    def test_protocol_constants_do_not_count(self):
        # Solo coinciden la duracion del tiron y el tiempo al pico: no alcanza.
        different = _imtp(
            "2025-05-22",
            IMTP_N=3200.0,
            IMTP_asym_pct=-10.0,
            IMTP_force_L_N=1500.0,
            IMTP_force_R_N=1700.0,
            IMTP_pretension=1150.0,
            IMTP_rfd_100_N_s=7000.0,
        )
        result = find_duplicate_takes(
            _imtp("2026-05-22"), [different], metric_columns=_imtp("x")["__metric_fields"]
        )
        self.assertEqual(result, [])

    def test_real_gray_dj_two_of_eight_is_not_blocked(self):
        history = pd.DataFrame([_gray_dj("2025-12-17", 160.0, 2.188)])
        self.assertIsNone(check_duplicate_take(_gray_dj("2026-05-07", 164.0, 2.134), history=history))

    def test_manual_entry_with_few_metrics_is_never_blocked(self):
        manual = {"Athlete": "Ana", "Date": "2026-05-07", "Source": "platform", "CMJ_cm": 40.0,
                  "__metric_fields": ["CMJ_cm"]}
        history = pd.DataFrame([{**manual, "Date": "2026-04-01"}])
        self.assertIsNone(check_duplicate_take(manual, history=history))


class IdenticalPairsInChangeThresholdTests(unittest.TestCase):
    def test_identical_consecutive_takes_are_dropped(self):
        self.assertEqual(drop_identical_consecutive_takes([41.1, 41.1, 46.04, 46.04, 46.5]), [41.1, 46.04, 46.5])

    def test_duplicates_do_not_drive_te_to_zero(self):
        # Ignacio De La Vega antes de la limpieza: 15/05 = 20/05 y 08/10 = 31/10.
        with_duplicates = resolve_change_threshold("CMJ_cm", 46.04, [41.1, 41.1, 46.04, 46.04], swc_pct=1.5)
        clean = resolve_change_threshold("CMJ_cm", 46.04, [41.1, 46.04], swc_pct=1.5)
        self.assertEqual(with_duplicates, clean)
        self.assertEqual(with_duplicates["method"], "TE instrumento")

    def test_te_never_zero_from_a_repeated_take(self):
        result = resolve_change_threshold("IMTP_N", 3100.0, [3084.0, 3084.0, 3300.0, 3100.0], swc_pct=2.0)
        self.assertGreater(result["threshold_abs"], 0)
        self.assertIn("N=3", result["label"])


if __name__ == "__main__":
    unittest.main()
