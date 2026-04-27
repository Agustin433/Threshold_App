from __future__ import annotations

import unittest

import pandas as pd

from charts.load_charts import chart_acwr
from modules.load_monitoring import calc_monotony_strain


def _chart_theme() -> dict:
    colors = {
        "navy": "#0D3C5E",
        "steel": "#708C9F",
        "blue": "#4A9FD4",
        "green": "#6F8F78",
        "yellow": "#C4A464",
        "orange": "#C88759",
        "red": "#B56B73",
        "muted": "#5E6A74",
        "bg": "#F5F4F0",
        "card": "#FEFEFE",
        "white": "#221F20",
        "gray": "#4B5560",
        "border": "#D8DEE4",
    }
    return {
        "colors": colors,
        "layout": dict(
            template="plotly_white",
            paper_bgcolor=colors["bg"],
            plot_bgcolor=colors["card"],
            font=dict(family="Barlow, sans-serif", color=colors["white"], size=11),
            margin=dict(l=44, r=32, t=68, b=48),
        ),
        "grid": "rgba(34, 31, 32, 0.08)",
        "grid_soft": "rgba(34, 31, 32, 0.05)",
        "reference_line": "rgba(34, 31, 32, 0.18)",
        "legend": dict(
            orientation="h",
            y=-0.18,
            bgcolor="rgba(254, 254, 254, 0.92)",
            bordercolor=colors["border"],
            borderwidth=1,
            font=dict(size=9, color=colors["gray"]),
        ),
    }


class LoadMonitoringEWMATest(unittest.TestCase):
    def test_chart_acwr_renders_only_ewma_trace(self):
        acwr_df = pd.DataFrame(
            [
                {"Date": "2026-04-01", "sRPE_diario": 320, "ACWR_EWMA": 1.05, "ACWR_Classic": 1.18},
                {"Date": "2026-04-02", "sRPE_diario": 410, "ACWR_EWMA": 1.12, "ACWR_Classic": 1.24},
            ]
        )

        figure = chart_acwr(acwr_df, "Atleta Test", theme=_chart_theme())
        trace_names = [trace.name for trace in figure.data]

        self.assertEqual(trace_names, ["sRPE diario", "ACWR EWMA"])

    def test_monotony_strain_has_no_artificial_value_for_zero_variability(self):
        srpe_daily = pd.DataFrame(
            {
                "Date": pd.date_range("2026-04-20", periods=7, freq="D"),
                "sRPE_diario": [300] * 7,
            }
        )

        weekly = calc_monotony_strain(srpe_daily)
        row = weekly.iloc[0]

        self.assertEqual(row["Monotony_Status"], "zero_variability")
        self.assertEqual(row["Monotony_Warning"], "zero_variability")
        self.assertTrue(pd.isna(row["Monotonia"]))
        self.assertTrue(pd.isna(row["Strain"]))
        self.assertFalse(bool(row["Alerta"]))


if __name__ == "__main__":
    unittest.main()
