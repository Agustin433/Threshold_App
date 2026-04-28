from __future__ import annotations

import unittest

import pandas as pd

from charts.load_charts import chart_weekly_acwr_context
from modules.load_monitoring import build_weekly_acwr_context


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
        "legend": dict(orientation="h"),
        "monotony_high": 2.0,
    }


class WeeklyAcwrContextTest(unittest.TestCase):
    def _weekly_load(self) -> pd.DataFrame:
        weeks = pd.date_range("2026-01-05", periods=6, freq="W-MON")
        loads = [100, 200, 300, 400, 500, 900]
        return pd.DataFrame(
            {
                "Athlete": ["Ana Gomez"] * len(weeks),
                "week_start": weeks,
                "is_current_week": [False] * 5 + [True],
                "weekly_sRPE": loads,
                "sessions_count": [1, 2, 2, 3, 3, 4],
                "monotony": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
                "strain": [100, 220, 360, 520, 700, 1350],
                "ACWR_EWMA_last": [1.0, 1.05, 1.1, 1.15, 1.2, 1.35],
            }
        )

    def test_weekly_acwr_context_uses_uncoupled_previous_four_week_chronic_load(self):
        context = build_weekly_acwr_context(self._weekly_load(), "Ana Gomez", weeks=None)

        fifth_week = context.iloc[4]
        sixth_week = context.iloc[5]

        self.assertAlmostEqual(float(fifth_week["chronic_4w"]), 250.0, places=3)
        self.assertAlmostEqual(float(fifth_week["acwr_rolling_1_4"]), 2.0, places=3)
        self.assertEqual(fifth_week["context_status"], "standard")
        self.assertAlmostEqual(float(sixth_week["chronic_4w"]), 350.0, places=3)
        self.assertAlmostEqual(float(sixth_week["acwr_rolling_1_4"]), 900 / 350, places=3)

    def test_weekly_acwr_context_flags_limited_history_and_spikes(self):
        context = build_weekly_acwr_context(self._weekly_load(), "Ana Gomez", weeks=None)

        first_week = context.iloc[0]
        second_week = context.iloc[1]
        last_week = context.iloc[-1]

        self.assertEqual(first_week["context_status"], "insufficient_history")
        self.assertTrue(pd.isna(first_week["acwr_rolling_1_4"]))
        self.assertEqual(second_week["context_status"], "limited_history")
        self.assertTrue(bool(last_week["spike_flag"]))
        self.assertAlmostEqual(float(last_week["weekly_change_pct"]), 80.0, places=3)

    def test_weekly_acwr_context_limits_visible_window(self):
        context = build_weekly_acwr_context(self._weekly_load(), "Ana Gomez", weeks=4)

        self.assertEqual(len(context), 4)
        self.assertEqual(context.iloc[0]["week_start"], pd.Timestamp("2026-01-19"))

    def test_weekly_acwr_context_chart_renders_two_panel_traces(self):
        context = build_weekly_acwr_context(self._weekly_load(), "Ana Gomez", weeks=6)

        figure = chart_weekly_acwr_context(context, "Ana Gomez", theme=_chart_theme())
        trace_names = [trace.name for trace in figure.data]

        self.assertIn("Carga semanal", trace_names)
        self.assertIn("Cronica 4 semanas previas", trace_names)
        self.assertIn("ACWR rolling 1:4", trace_names)
        self.assertIn("Media movil ACWR 4 sem", trace_names)
        self.assertIn("Spike semanal", trace_names)


if __name__ == "__main__":
    unittest.main()
