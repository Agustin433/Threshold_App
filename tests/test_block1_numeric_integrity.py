"""Integridad numerica entre dashboard y reportes (bloque 1).

Estos tests fijan las tres contradicciones que hacian que la misma metrica
mostrara valores distintos segun la superficie: ACWR con constantes divergentes,
wellness en dos escalas, y ratios interpretados como si fueran cualidades.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules.load_monitoring import (
    ACWR_ACUTE_ALPHA,
    ACWR_ACUTE_DAYS,
    ACWR_CHRONIC_ALPHA,
    ACWR_CHRONIC_DAYS,
    calc_acwr,
    classify_acwr_zone,
)
from modules.jump_analysis import (
    VARIABLE_META,
    build_jump_flag_rows,
    compute_baseline_delta,
    compute_swc_delta,
)
from modules.report_generator import (
    WELLNESS_SCORE_MAX,
    _report_wellness_score_label,
    _report_wellness_score_series,
)


def _daily_load_series(values: list[float], start: str = "2026-05-01") -> tuple[pd.Series, pd.DatetimeIndex]:
    dates = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=dates), pd.DatetimeIndex(dates)


class AcwrConstantsTest(unittest.TestCase):
    def test_alphas_follow_williams_formula(self):
        # lambda = 2/(N+1). Antes eran 0.28 y 0.07, que no corresponden a
        # ninguna ventana entera.
        self.assertAlmostEqual(ACWR_ACUTE_ALPHA, 2 / (ACWR_ACUTE_DAYS + 1), places=12)
        self.assertAlmostEqual(ACWR_CHRONIC_ALPHA, 2 / (ACWR_CHRONIC_DAYS + 1), places=12)
        self.assertAlmostEqual(ACWR_ACUTE_ALPHA, 0.25, places=12)
        self.assertEqual((ACWR_ACUTE_DAYS, ACWR_CHRONIC_DAYS), (7, 28))

    def test_calc_acwr_uses_the_declared_alphas(self):
        values = [300.0, 0.0, 450.0, 500.0, 0.0, 620.0, 700.0, 0.0, 480.0, 530.0]
        series, dates = _daily_load_series(values)
        result = calc_acwr(series, dates)

        expected_acute = pd.Series(values).ewm(alpha=ACWR_ACUTE_ALPHA, adjust=False).mean()
        expected_chronic = pd.Series(values).ewm(alpha=ACWR_CHRONIC_ALPHA, adjust=False).mean()
        np.testing.assert_allclose(
            result["EWMA_Aguda"].to_numpy(dtype=float), expected_acute.to_numpy(dtype=float), atol=1e-12
        )
        np.testing.assert_allclose(
            result["EWMA_Cronica"].to_numpy(dtype=float), expected_chronic.to_numpy(dtype=float), atol=1e-12
        )


class AcwrZoneBoundaryTest(unittest.TestCase):
    def test_upper_bound_is_inclusive(self):
        # 1.30 pertenece al rango operativo. Antes el modulo canonico era la
        # unica superficie que lo clasificaba como precaucion.
        self.assertEqual(classify_acwr_zone(1.30), "Optimo")
        self.assertEqual(classify_acwr_zone(0.80), "Optimo")
        self.assertEqual(classify_acwr_zone(1.50), "Precaucion")

    def test_zone_edges(self):
        cases = {
            0.799: "Subcarga",
            1.301: "Precaucion",
            1.501: "Alto riesgo",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(classify_acwr_zone(value), expected)

    def test_missing_value_is_labelled(self):
        self.assertEqual(classify_acwr_zone(float("nan")), "Sin datos")


class AcwrDashboardReportParityTest(unittest.TestCase):
    def test_report_path_matches_canonical_calc(self):
        """El PDF ya no recalcula con constantes propias.

        Se reproduce el frame diario que arma el reporte y se verifica que
        pasarlo por `calc_acwr` da exactamente lo mismo que la serie canonica
        que alimenta al dashboard.
        """
        values = [420.0, 0.0, 610.0, 580.0, 0.0, 0.0, 700.0, 650.0, 0.0, 540.0, 800.0, 0.0]
        series, dates = _daily_load_series(values)

        dashboard = calc_acwr(series, dates)

        report_daily = pd.DataFrame({"Date": dates, "sRPE_diario": values})
        report = calc_acwr(report_daily["sRPE_diario"], pd.DatetimeIndex(report_daily["Date"]))

        np.testing.assert_allclose(
            dashboard["ACWR_EWMA"].to_numpy(dtype=float),
            report["ACWR_EWMA"].to_numpy(dtype=float),
            atol=1e-12,
        )
        self.assertEqual(
            [classify_acwr_zone(v) for v in dashboard["ACWR_EWMA"]],
            [classify_acwr_zone(v) for v in report["ACWR_EWMA"]],
        )

    def test_legacy_alphas_would_have_diverged(self):
        """Guard: confirma que el test anterior discrimina de verdad."""
        values = [420.0, 0.0, 610.0, 580.0, 0.0, 0.0, 700.0, 650.0, 0.0, 540.0, 800.0, 0.0]
        legacy = (
            pd.Series(values).ewm(alpha=0.28, adjust=False).mean()
            / pd.Series(values).ewm(alpha=0.07, adjust=False).mean()
        )
        current = (
            pd.Series(values).ewm(alpha=ACWR_ACUTE_ALPHA, adjust=False).mean()
            / pd.Series(values).ewm(alpha=ACWR_CHRONIC_ALPHA, adjust=False).mean()
        )
        self.assertGreater(float((legacy - current).abs().max()), 0.01)


class WellnessScaleTest(unittest.TestCase):
    def test_report_series_uses_the_canonical_0_30_scale(self):
        frame = pd.DataFrame(
            [
                {"Sueno_hs": 8.0, "Estres": 2.0, "Dolor": 1.0},   # 8 + 8 + 9 = 25
                {"Sueno_hs": 5.0, "Estres": 6.0, "Dolor": 5.0},   # 5 + 4 + 5 = 14
            ]
        )
        scores = _report_wellness_score_series(frame)
        np.testing.assert_allclose(scores.to_numpy(dtype=float), [25.0, 14.0], atol=1e-9)

    def test_report_series_reuses_precomputed_score(self):
        frame = pd.DataFrame([{"Sueno_hs": 8.0, "Estres": 2.0, "Dolor": 1.0, "Wellness_Score": 22.0}])
        self.assertAlmostEqual(float(_report_wellness_score_series(frame).iloc[0]), 22.0)

    def test_labels_are_expressed_on_the_same_scale(self):
        self.assertEqual(_report_wellness_score_label(25.0)["label"], "Óptimo")
        self.assertEqual(_report_wellness_score_label(19.0)["label"], "Aceptable")
        self.assertEqual(_report_wellness_score_label(13.0)["label"], "Atención")
        self.assertEqual(_report_wellness_score_label(5.0)["label"], "Crítico")

    def test_score_is_not_clipped_into_the_old_1_5_range(self):
        # En la escala vieja cualquier valor >5 se recortaba a 5.0.
        self.assertAlmostEqual(_report_wellness_score_label(25.0)["score"], 25.0)
        self.assertEqual(WELLNESS_SCORE_MAX, 30.0)


class RatioDirectionTest(unittest.TestCase):
    def _history(self, variable: str, values: list[float]) -> pd.DataFrame:
        dates = pd.date_range("2026-03-01", periods=len(values), freq="7D")
        return pd.DataFrame({"Athlete": "Ana Lopez", "Date": dates, variable: values})

    def test_eur_and_dsi_are_declared_context_dependent(self):
        for variable in ("EUR", "DSI"):
            with self.subTest(variable=variable):
                self.assertEqual(VARIABLE_META[variable].get("direction"), "context_dependent")

    def test_rising_eur_is_not_reported_as_improvement(self):
        """Un EUR que sube porque cayo el SJ no es una mejora.

        Antes, con `higher_is_better=True`, esta serie devolvia
        "mejora relevante".
        """
        history = self._history("EUR", [1.10, 1.12, 1.11, 1.45])
        delta = compute_swc_delta(history, history["Date"].iloc[-1], variables=["EUR"])
        signal = delta[delta["Variable"] == "EUR"].iloc[0]["Signal"]
        self.assertNotIn("mejora", signal)
        self.assertEqual(signal, "cambio relevante sin direccion")

    def test_falling_eur_is_not_reported_as_decline(self):
        history = self._history("EUR", [1.40, 1.42, 1.41, 1.05])
        delta = compute_swc_delta(history, history["Date"].iloc[-1], variables=["EUR"])
        signal = delta[delta["Variable"] == "EUR"].iloc[0]["Signal"]
        self.assertNotIn("caida", signal)
        self.assertEqual(signal, "cambio relevante sin direccion")

    def test_baseline_signal_is_also_directionless_for_ratios(self):
        history = self._history("EUR", [1.10, 1.12, 1.11, 1.45])
        baseline = compute_baseline_delta(history, history["Date"].iloc[-1], variables=["EUR"])
        signal = baseline[baseline["Variable"] == "EUR"].iloc[0]["Signal"]
        self.assertEqual(signal, "cambio vs baseline sin direccion")

    def test_simple_metrics_keep_their_direction(self):
        # CMJ sigue siendo higher_is_better: no se rompio el caso normal.
        history = self._history("CMJ_cm", [38.0, 38.2, 38.1, 44.0])
        delta = compute_swc_delta(history, history["Date"].iloc[-1], variables=["CMJ_cm"])
        self.assertEqual(delta[delta["Variable"] == "CMJ_cm"].iloc[0]["Signal"], "mejora relevante")

        # Tiempo de contacto sigue siendo lower_is_better.
        history_tc = self._history("DJ_tc_ms", [230.0, 228.0, 229.0, 180.0])
        delta_tc = compute_swc_delta(history_tc, history_tc["Date"].iloc[-1], variables=["DJ_tc_ms"])
        self.assertEqual(delta_tc[delta_tc["Variable"] == "DJ_tc_ms"].iloc[0]["Signal"], "mejora relevante")


class DsiFlagTest(unittest.TestCase):
    def _dsi_flag(self, dsi: float) -> dict[str, str]:
        flags = build_jump_flag_rows({"DSI": dsi})
        return next(flag for flag in flags if "DSI" in flag["text"])

    def test_dsi_is_never_painted_as_good_or_bad(self):
        for dsi in (0.45, 0.70, 0.95, 1.20):
            with self.subTest(dsi=dsi):
                self.assertEqual(self._dsi_flag(dsi)["level"], "gray")

    def test_low_dsi_recommends_ballistic_work(self):
        text = self._dsi_flag(0.45)["text"].lower()
        self.assertIn("balistico", text)
        self.assertIn("superavit de fuerza", text)

    def test_high_dsi_recommends_maximal_strength(self):
        text = self._dsi_flag(0.95)["text"].lower()
        self.assertIn("fuerza maxima", text)


if __name__ == "__main__":
    unittest.main()
