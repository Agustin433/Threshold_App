from __future__ import annotations

import unittest

import pandas as pd

from charts.dashboard_charts import chart_radar
from modules.jump_analysis import (
    _prepare_jump_df,
    build_jump_feedback_lines,
    build_jump_flag_rows,
    build_jump_metric_table,
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
    }


def _sample_jump_df() -> pd.DataFrame:
    return _prepare_jump_df(
        pd.DataFrame(
            [
                {
                    "Athlete": "Atleta A",
                    "Date": "2026-04-01",
                    "CMJ_cm": 38,
                    "SJ_cm": 32,
                    "DJ_cm": 28,
                    "DJ_tc_ms": 220,
                    "IMTP_N": 2800,
                    "BW_kg": 78,
                    "CMJ_propulsive_PF_N": 2600,
                    "CMJ_rel_impulse": 2.45,
                    "CMJ_contraction_ms": 520,
                },
                {
                    "Athlete": "Atleta B",
                    "Date": "2026-04-01",
                    "CMJ_cm": 30,
                    "SJ_cm": 32,
                    "DJ_cm": 25,
                    "DJ_tc_ms": 180,
                    "IMTP_N": 3200,
                    "BW_kg": 85,
                    "CMJ_propulsive_PF_N": 2500,
                    "CMJ_rel_impulse": 2.10,
                    "CMJ_contraction_ms": 650,
                },
                {
                    "Athlete": "Atleta C",
                    "Date": "2026-04-01",
                    "CMJ_cm": 45,
                    "SJ_cm": 36,
                    "DJ_cm": 35,
                    "DJ_tc_ms": 190,
                    "IMTP_N": 3800,
                    "BW_kg": 80,
                    "CMJ_propulsive_PF_N": 3300,
                    "CMJ_rel_impulse": 2.95,
                    "CMJ_contraction_ms": 430,
                },
            ]
        )
    )


class JumpProfileSystemTest(unittest.TestCase):
    def test_prepare_jump_df_computes_new_profile_metrics(self):
        jump_df = _sample_jump_df()
        athlete_a = jump_df[jump_df["Athlete"] == "Atleta A"].iloc[0]
        athlete_b = jump_df[jump_df["Athlete"] == "Atleta B"].iloc[0]
        athlete_c = jump_df[jump_df["Athlete"] == "Atleta C"].iloc[0]

        self.assertAlmostEqual(float(athlete_a["EUR"]), 1.188, places=3)
        self.assertAlmostEqual(float(athlete_b["EUR"]), 0.938, places=3)
        self.assertAlmostEqual(float(athlete_c["EUR"]), 1.250, places=3)

        self.assertAlmostEqual(float(athlete_a["DJ_RSI"]), 1.273, places=3)
        self.assertAlmostEqual(float(athlete_c["DJ_RSI"]), 1.842, places=3)

        self.assertAlmostEqual(float(athlete_a["IMTP_relPF"]), 35.90, places=2)
        self.assertAlmostEqual(float(athlete_c["IMTP_relPF"]), 47.50, places=2)
        self.assertAlmostEqual(float(athlete_a["Jump_Momentum"]), 213.0, places=1)
        self.assertAlmostEqual(float(athlete_a["DSI"]), 0.929, places=3)
        self.assertTrue(pd.isna(athlete_a.get("mRSI")))

        self.assertEqual(athlete_a["NM_Profile"], "Reactivo")
        self.assertEqual(athlete_b["NM_Profile"], "Base de Fuerza")
        self.assertEqual(athlete_c["NM_Profile"], "Reactivo")

    def test_feedback_and_flags_follow_official_rules(self):
        jump_df = _sample_jump_df()
        athlete_b = jump_df[jump_df["Athlete"] == "Atleta B"].iloc[0]

        flags = build_jump_flag_rows(athlete_b)
        texts = [item["text"] for item in flags]
        self.assertTrue(any("SSC deficiente" in text for text in texts))
        self.assertTrue(any("requiere TTT del export" in text for text in texts))

        lines = build_jump_feedback_lines(athlete_b)
        self.assertGreaterEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("Alto:"))
        self.assertTrue(lines[1].startswith("Bajo:"))
        self.assertTrue(lines[2].startswith("Fisiologico:"))
        self.assertTrue(lines[3].startswith("Biomecanico:"))
        self.assertTrue(lines[4].startswith("Proximo bloque:"))
        self.assertTrue(any("CMJ < SJ" in line for line in lines))

    def test_feedback_handles_pattern_e_without_empty_low_text_and_table_never_shows_none(self):
        athlete_row = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta EUR",
                        "Date": "2026-04-10",
                        "CMJ_cm": 35.2,
                        "SJ_cm": 39.9,
                        "DJ_cm": 30.0,
                        "DJ_RSI": 2.28,
                    }
                ]
            )
        ).iloc[0]

        lines = build_jump_feedback_lines(athlete_row)
        self.assertIn(
            "Fisiologico: Mayor expresion en DJ RSI (+0.59); sin deficits marcados en el resto de variables.",
            lines,
        )
        self.assertNotIn("en .", " ".join(lines))
        self.assertIn(
            (
                "Biomecanico: Buena rigidez muscular funcional en SSC rapido, "
                "pero el CMJ < SJ indica que el ciclo de estiramiento no esta potenciando "
                "el salto con contramovimiento. Posible dominancia reactiva con limitacion "
                "en SSC lento."
            ),
            lines,
        )

        metric_table = build_jump_metric_table(athlete_row)
        self.assertTrue(all(value == "-" or pd.notna(value) for value in metric_table["Z"].tolist()))

    def test_radar_uses_official_axis_order(self):
        jump_df = _sample_jump_df()
        athlete_a = jump_df[jump_df["Athlete"] == "Atleta A"].iloc[0]

        figure = chart_radar(athlete_a, "Atleta A", None, theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        self.assertEqual(
            axis_order,
            ["SJ", "CMJ", "DJ height", "DJ RSI", "TC inv", "IMTP relPF"],
        )

    def test_dsi_requires_propulsive_force_without_peak_force_fallback(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Fallback",
                        "Date": "2026-04-01",
                        "CMJ_cm": 36,
                        "SJ_cm": 31,
                        "IMTP_N": 2900,
                        "BW_kg": 79,
                        "CMJ_peak_force_N": 2550,
                    }
                ]
            )
        )

        self.assertEqual(len(jump_df), 1)
        self.assertTrue(pd.isna(jump_df.iloc[0].get("DSI")))

    def test_rel_impulse_row_uses_internal_z_when_athlete_has_three_records(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Impulso",
                        "Date": "2026-04-01",
                        "CMJ_cm": 36,
                        "SJ_cm": 31,
                        "DJ_cm": 27,
                        "DJ_tc_ms": 210,
                        "IMTP_N": 3000,
                        "BW_kg": 78,
                        "CMJ_propulsive_PF_N": 2500,
                        "CMJ_rel_impulse": 2.0,
                    },
                    {
                        "Athlete": "Atleta Impulso",
                        "Date": "2026-04-08",
                        "CMJ_cm": 37,
                        "SJ_cm": 32,
                        "DJ_cm": 28,
                        "DJ_tc_ms": 205,
                        "IMTP_N": 3050,
                        "BW_kg": 78,
                        "CMJ_propulsive_PF_N": 2550,
                        "CMJ_rel_impulse": 2.5,
                    },
                    {
                        "Athlete": "Atleta Impulso",
                        "Date": "2026-04-15",
                        "CMJ_cm": 38,
                        "SJ_cm": 33,
                        "DJ_cm": 29,
                        "DJ_tc_ms": 200,
                        "IMTP_N": 3100,
                        "BW_kg": 78,
                        "CMJ_propulsive_PF_N": 2600,
                        "CMJ_rel_impulse": 3.0,
                    },
                ]
            )
        )

        latest_row = jump_df.sort_values("Date").iloc[-1]
        metric_table = build_jump_metric_table(latest_row)
        impulse_row = metric_table[metric_table["Variable"] == "Impulso Relativo Propulsivo"].iloc[0]

        self.assertAlmostEqual(float(impulse_row["Valor"]), 3.0, places=3)
        self.assertAlmostEqual(float(impulse_row["Z"]), 1.22, places=2)


if __name__ == "__main__":
    unittest.main()
