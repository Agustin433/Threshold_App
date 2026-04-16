from __future__ import annotations

import unittest

import pandas as pd

import local_store
from charts.load_charts import (
    chart_weekly_external,
    chart_weekly_load,
    chart_weekly_strain,
    chart_weekly_wellness,
)


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
        "monotony_high": 2.0,
    }


class WeeklySummariesTest(unittest.TestCase):
    def test_build_weekly_summaries_aggregates_internal_wellness_and_external_load(self):
        rpe_df = pd.DataFrame(
            [
                {"Date": "2026-04-06", "Athlete": "Juan Perez", "RPE": 6, "Duration_min": 50, "sRPE": 300},
                {"Date": "2026-04-08", "Athlete": "Juan Perez", "RPE": 8, "Duration_min": 50, "sRPE": 400},
                {"Date": "2026-04-14", "Athlete": "Juan Perez", "RPE": 7, "Duration_min": 50, "sRPE": 350},
            ]
        )
        wellness_df = pd.DataFrame(
            [
                {"Date": "2026-04-06", "Athlete": "Juan Perez", "Sueno_hs": 8, "Estres": 2, "Dolor": 1, "Wellness_Score": 11},
                {"Date": "2026-04-08", "Athlete": "Juan Perez", "Sueno_hs": 7, "Estres": 3, "Dolor": 2, "Wellness_Score": 12},
                {"Date": "2026-04-14", "Athlete": "Juan Perez", "Sueno_hs": 8, "Estres": 2, "Dolor": 2, "Wellness_Score": 12},
            ]
        )
        raw_df = pd.DataFrame(
            [
                {
                    "Assigned Date": "2026-04-06",
                    "Athlete": "Juan Perez",
                    "Exercise": "Back Squat",
                    "Exercise Name": "Back Squat",
                    "Tags": "Dominante de Rodilla",
                    "Result": 80,
                    "Reps": 5,
                    "Sets": 4,
                },
                {
                    "Assigned Date": "2026-04-08",
                    "Athlete": "Juan Perez",
                    "Exercise": "Box Jump",
                    "Exercise Name": "Box Jump",
                    "Tags": "Jump_Plyo",
                    "Result": None,
                    "Reps": 20,
                    "Sets": 5,
                },
                {
                    "Assigned Date": "2026-04-09",
                    "Athlete": "Juan Perez",
                    "Exercise": "Hang Clean",
                    "Exercise Name": "Hang Clean",
                    "Tags": "DLO",
                    "Result": 60,
                    "Reps": 3,
                    "Sets": 3,
                },
                {
                    "Assigned Date": "2026-04-10",
                    "Athlete": "Juan Perez",
                    "Exercise": "10m + COD 90 + 5m",
                    "Exercise Name": "10m + COD 90 + 5m",
                    "Tags": "",
                    "Result": 10,
                    "Reps": 4,
                    "Sets": 1,
                },
                {
                    "Assigned Date": "2026-04-15",
                    "Athlete": "Juan Perez",
                    "Exercise": "Dead Bug",
                    "Exercise Name": "Dead Bug",
                    "Tags": "Core",
                    "Result": None,
                    "Reps": 12,
                    "Sets": 3,
                },
            ]
        )

        acwr_dict, _ = local_store.build_load_models(rpe_df)
        summaries = local_store.build_weekly_summaries(
            rpe_df,
            wellness_df,
            raw_df,
            acwr_dict=acwr_dict,
        )

        weekly_load = summaries["weekly_load"]
        weekly_wellness = summaries["weekly_wellness"]
        weekly_external = summaries["weekly_external"]
        weekly_team = summaries["weekly_team"]

        self.assertEqual(list(weekly_load.columns), local_store.WEEKLY_LOAD_COLUMNS)
        self.assertEqual(list(weekly_wellness.columns), local_store.WEEKLY_WELLNESS_COLUMNS)
        self.assertEqual(list(weekly_external.columns), local_store.WEEKLY_EXTERNAL_COLUMNS)
        self.assertEqual(list(weekly_team.columns), local_store.WEEKLY_TEAM_COLUMNS)

        week_one = pd.Timestamp("2026-04-06")
        load_row = weekly_load.loc[weekly_load["week_start"] == week_one].iloc[0]
        expected_acwr = (
            acwr_dict["Juan Perez"]
            .assign(week_start=lambda df: pd.to_datetime(df["Date"]) - pd.to_timedelta(pd.to_datetime(df["Date"]).dt.weekday, unit="D"))
            .query("week_start == @week_one")
            .sort_values("Date")
            .iloc[-1]["ACWR_EWMA"]
        )
        self.assertEqual(load_row["Athlete"], "Juan Perez")
        self.assertEqual(load_row["sessions_count"], 2)
        self.assertAlmostEqual(float(load_row["weekly_sRPE"]), 700.0, places=3)
        self.assertAlmostEqual(float(load_row["sRPE_mean_session"]), 350.0, places=3)
        self.assertAlmostEqual(float(load_row["ACWR_EWMA_last"]), float(expected_acwr), places=6)

        wellness_row = weekly_wellness.loc[weekly_wellness["week_start"] == week_one].iloc[0]
        self.assertEqual(wellness_row["wellness_days"], 2)
        self.assertAlmostEqual(float(wellness_row["Wellness_mean"]), 11.5, places=3)
        self.assertAlmostEqual(float(wellness_row["wellness_compliance"]), 1.0, places=3)

        external_row = weekly_external.loc[weekly_external["week_start"] == week_one].iloc[0]
        self.assertAlmostEqual(float(external_row["strength_kg"]), 400.0, places=3)
        self.assertAlmostEqual(float(external_row["plyo_contacts"]), 20.0, places=3)
        self.assertAlmostEqual(float(external_row["olympic_exposures"]), 3.0, places=3)
        self.assertAlmostEqual(float(external_row["sprint_exposures"]), 4.0, places=3)
        self.assertAlmostEqual(float(external_row["sprint_distance_m"]), 40.0, places=3)
        self.assertEqual(float(external_row["iso_exposures"]), 0.0)

        team_row = weekly_team.loc[weekly_team["week_start"] == week_one].iloc[0]
        self.assertEqual(int(team_row["athletes_active"]), 1)
        self.assertAlmostEqual(float(team_row["team_sRPE_sum"]), 700.0, places=3)
        self.assertAlmostEqual(float(team_row["team_wellness_mean"]), 11.5, places=3)

    def test_build_weekly_summaries_returns_stable_empty_frames(self):
        summaries = local_store.build_weekly_summaries(None, None, None)

        self.assertEqual(list(summaries["weekly_load"].columns), local_store.WEEKLY_LOAD_COLUMNS)
        self.assertEqual(list(summaries["weekly_wellness"].columns), local_store.WEEKLY_WELLNESS_COLUMNS)
        self.assertEqual(list(summaries["weekly_external"].columns), local_store.WEEKLY_EXTERNAL_COLUMNS)
        self.assertEqual(list(summaries["weekly_team"].columns), local_store.WEEKLY_TEAM_COLUMNS)

    def test_weekly_charts_render_from_summary_frames(self):
        weekly_load = pd.DataFrame(
            [
                {
                    "Athlete": "Juan Perez",
                    "week_start": pd.Timestamp("2026-04-06"),
                    "weekly_sRPE": 700,
                    "sessions_count": 2,
                    "sRPE_mean_session": 350,
                    "monotony": 1.5,
                    "strain": 1050,
                    "ACWR_EWMA_last": 1.08,
                }
            ]
        )
        weekly_wellness = pd.DataFrame(
            [
                {
                    "Athlete": "Juan Perez",
                    "week_start": pd.Timestamp("2026-04-06"),
                    "Sueno_mean": 7.5,
                    "Estres_mean": 2.5,
                    "Dolor_mean": 1.5,
                    "Wellness_mean": 11.5,
                    "wellness_days": 2,
                    "wellness_compliance": 1.0,
                }
            ]
        )
        weekly_external = pd.DataFrame(
            [
                {
                    "Athlete": "Juan Perez",
                    "week_start": pd.Timestamp("2026-04-06"),
                    "strength_kg": 400,
                    "plyo_contacts": 20,
                    "landing_contacts": 0,
                    "iso_exposures": 0,
                    "core_exposures": 0,
                    "mobility_exposures": 0,
                    "olympic_exposures": 3,
                    "sprint_exposures": 4,
                    "sprint_distance_m": 40,
                }
            ]
        )

        load_figure = chart_weekly_load(weekly_load, "Juan Perez", theme=_chart_theme())
        strain_figure = chart_weekly_strain(weekly_load, "Juan Perez", theme=_chart_theme())
        wellness_figure = chart_weekly_wellness(weekly_wellness, "Juan Perez", theme=_chart_theme())
        external_figure = chart_weekly_external(weekly_external, "Juan Perez", theme=_chart_theme())

        self.assertEqual([trace.name for trace in load_figure.data], ["sRPE semanal", "Monotonia"])
        self.assertEqual([trace.name for trace in strain_figure.data], ["Strain"])
        self.assertEqual(
            [trace.name for trace in wellness_figure.data],
            ["Sueno medio", "Estres medio", "Dolor medio"],
        )
        self.assertIn("Strength kg", [trace.name for trace in external_figure.data])
        self.assertIn("Sprint distance (m)", [trace.name for trace in external_figure.data])


if __name__ == "__main__":
    unittest.main()
