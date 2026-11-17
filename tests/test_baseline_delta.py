"""PR K: "Cambio vs baseline" con tomas previas, misma era y umbral max(TE, SWC)."""

from __future__ import annotations

import unittest

import pandas as pd

from modules.jump_analysis import (
    _prepare_jump_df,
    build_jump_baseline_display_table,
    compute_baseline_delta,
)
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_NO_STRAPS, ERA_VALKYRIA_STRAPS


def _take(date: str, device: str, *, flight_ms: float = 560.0, dj: float = 40.0, imtp: float = 3000.0) -> dict:
    return {
        "Athlete": "A", "Date": date, "Source": "platform", "Device": device, "BW_kg": 80.0,
        "CMJ_cm": round(9.81 * (flight_ms / 1000) ** 2 / 8 * 100, 2), "CMJ_flight_ms": flight_ms,
        "DJ_cm": dj, "DJ_tc_ms": 200.0, "DJ_drop_height_cm": 30.0, "IMTP_N": imtp,
    }


def _baseline(rows: list[dict]) -> pd.DataFrame:
    history = _prepare_jump_df(pd.DataFrame(rows))
    last = pd.to_datetime(history["Date"]).max()
    return compute_baseline_delta(history, last).set_index("Variable")


IGNACIO_LIKE = [
    _take("2025-11-04", ERA_VALKYRIA_NO_STRAPS, flight_ms=540, dj=float("nan"), imtp=2500),  # sin DJ, como Ignacio
    _take("2025-12-17", ERA_VALKYRIA_NO_STRAPS, flight_ms=555, dj=41.0, imtp=2600),
    _take("2026-05-20", ERA_VALKYRIA_STRAPS, flight_ms=570, dj=42.7, imtp=3235),
    _take("2026-10-08", ERA_INVOLUTION_STRAPS, flight_ms=614, dj=40.8, imtp=3491),
]


class BaselineDeltaTests(unittest.TestCase):
    def test_imtp_baseline_crosses_eras_with_warning(self):
        # PR L: baseline con las 3 tomas previas aunque sean de otra era.
        imtp = _baseline(IGNACIO_LIKE).loc["IMTP_N"]
        self.assertAlmostEqual(float(imtp["Baseline_value"]), (2500 + 2600 + 3235) / 3, places=1)
        self.assertTrue(bool(imtp["Cross_era"]))
        self.assertIn("Valkyria sin straps → Involution con straps", imtp["Comparison_note"])
        display = build_jump_baseline_display_table(_baseline(IGNACIO_LIKE).reset_index())
        self.assertIn("⚠ compara", display.set_index("Variable").loc["IMTP", "Senal"])

    def test_baseline_never_includes_current_take(self):
        baseline = _baseline(IGNACIO_LIKE)
        flight = baseline.loc["CMJ_ft_cm"]
        self.assertEqual(pd.Timestamp(flight["Baseline_end_date"]), pd.Timestamp("2026-05-20"))
        self.assertLess(pd.Timestamp(flight["Baseline_end_date"]), pd.Timestamp(flight["Fecha_actual"]))
        # DJ: solo 2 tomas previas -> insuficiente (antes contaba la actual).
        self.assertEqual(baseline.loc["DJ_cm", "Signal"], "baseline insuficiente")
        self.assertEqual(int(baseline.loc["DJ_cm", "N_valid"]), 2)

    def test_flight_heights_cross_eras_with_threshold(self):
        flight = _baseline(IGNACIO_LIKE).loc["CMJ_ft_cm"]
        self.assertEqual(flight["Signal"], "mejora vs baseline")
        self.assertGreater(flight["Delta_abs"], flight["Threshold_abs"])

    def test_change_within_threshold_is_not_an_improvement(self):
        rows = [
            _take("2026-07-01", ERA_INVOLUTION_STRAPS, dj=40.0),
            _take("2026-08-01", ERA_INVOLUTION_STRAPS, dj=40.5),
            _take("2026-09-01", ERA_INVOLUTION_STRAPS, dj=39.6),
            _take("2026-10-08", ERA_INVOLUTION_STRAPS, dj=40.18),  # +0.15 cm vs baseline
        ]
        dj = _baseline(rows).loc["DJ_cm"]
        self.assertAlmostEqual(float(dj["Delta_abs"]), 0.15, places=2)
        self.assertEqual(dj["Signal"], "sin cambio vs baseline")

    def test_same_era_baseline_is_used_when_available(self):
        rows = [
            _take("2026-06-01", ERA_INVOLUTION_STRAPS, imtp=3000),
            _take("2026-07-01", ERA_INVOLUTION_STRAPS, imtp=3050),
            _take("2026-08-01", ERA_INVOLUTION_STRAPS, imtp=3100),
            _take("2026-10-08", ERA_INVOLUTION_STRAPS, imtp=3600),
        ]
        imtp = _baseline(rows).loc["IMTP_N"]
        self.assertAlmostEqual(float(imtp["Baseline_value"]), 3050.0)
        self.assertEqual(imtp["Signal"], "mejora vs baseline")

    def test_too_few_takes_is_insufficient(self):
        baseline = _baseline(IGNACIO_LIKE[-2:])
        self.assertEqual(baseline.loc["CMJ_ft_cm", "Signal"], "baseline insuficiente")


if __name__ == "__main__":
    unittest.main()
