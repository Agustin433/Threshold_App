from __future__ import annotations

import unittest

import pandas as pd

from charts.dashboard_charts import (
    chart_composite_profile_radar,
    chart_jump_metric_trend,
    chart_radar,
    find_latest_valid_radar_row,
)
from modules.jump_analysis import (
    _prepare_jump_df,
    build_composite_profile_metric_table,
    build_composite_profile_snapshot,
    build_jump_delta_display_table,
    build_jump_feedback_lines,
    build_jump_flag_rows,
    build_jump_metric_table,
    build_jump_temporal_context,
    compute_swc_delta,
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


def _temporal_jump_df() -> pd.DataFrame:
    return _prepare_jump_df(
        pd.DataFrame(
            [
                {
                    "Athlete": "Atleta Delta",
                    "Date": "2026-04-01",
                    "CMJ_cm": 30,
                    "SJ_cm": 28,
                    "DJ_cm": 24,
                    "DJ_tc_ms": 220,
                    "IMTP_N": 2500,
                    "BW_kg": 78,
                },
                {
                    "Athlete": "Atleta Delta",
                    "Date": "2026-04-08",
                    "CMJ_cm": 31,
                    "SJ_cm": 29,
                    "DJ_cm": 25,
                    "DJ_tc_ms": 210,
                    "IMTP_N": 2550,
                    "BW_kg": 78,
                },
                {
                    "Athlete": "Atleta Delta",
                    "Date": "2026-04-15",
                    "CMJ_cm": 32,
                    "SJ_cm": 30,
                    "DJ_cm": 26,
                    "DJ_tc_ms": 205,
                    "IMTP_N": 2600,
                    "BW_kg": 78,
                },
                {
                    "Athlete": "Atleta Delta",
                    "Date": "2026-04-22",
                    "CMJ_cm": 34,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 225,
                    "IMTP_N": 2800,
                    "BW_kg": 78,
                },
            ]
        )
    )


def _composite_profile_source_df() -> pd.DataFrame:
    return _prepare_jump_df(
        pd.DataFrame(
            [
                {
                    "Athlete": "Atleta Compuesto",
                    "Date": "2026-04-01",
                    "CMJ_cm": 34,
                    "SJ_cm": 30,
                    "DJ_cm": 26,
                    "DJ_tc_ms": 220,
                    "IMTP_N": 3000,
                    "BW_kg": 80,
                },
                {
                    "Athlete": "Atleta Compuesto",
                    "Date": "2026-04-08",
                    "CMJ_cm": 36,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    "BW_kg": 80,
                },
                {
                    "Athlete": "Atleta Compuesto",
                    "Date": "2026-04-15",
                    "CMJ_cm": 35,
                    "SJ_cm": 32,
                    "BW_kg": 80,
                },
                {
                    "Athlete": "Atleta Compuesto",
                    "Date": "2026-04-22",
                    "DJ_cm": 28,
                    "DJ_tc_ms": 200,
                    "IMTP_N": 3100,
                    "BW_kg": 80,
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

    def test_composite_profile_snapshot_uses_latest_valid_value_per_metric(self):
        jump_df = _composite_profile_source_df()

        composite_row, source_table = build_composite_profile_snapshot(jump_df)

        self.assertIsNotNone(composite_row)
        self.assertAlmostEqual(float(composite_row["SJ_cm"]), 32.0, places=3)
        self.assertAlmostEqual(float(composite_row["CMJ_cm"]), 35.0, places=3)
        self.assertAlmostEqual(float(composite_row["DJ_cm"]), 28.0, places=3)
        self.assertAlmostEqual(float(composite_row["DRI"]), 1.4, places=3)
        self.assertAlmostEqual(float(composite_row["DJ_tc_ms"]), 200.0, places=3)
        self.assertAlmostEqual(float(composite_row["EUR"]), 1.094, places=3)
        self.assertAlmostEqual(float(composite_row["IMTP_relPF"]), 38.75, places=3)

        source_dates = dict(zip(source_table["Variable"], source_table["Fecha origen"]))
        self.assertEqual(source_dates["SJ"], "15/04/2026")
        self.assertEqual(source_dates["CMJ"], "15/04/2026")
        self.assertEqual(source_dates["DJ"], "22/04/2026")
        self.assertEqual(source_dates["DRI"], "22/04/2026")
        self.assertEqual(source_dates["TC"], "22/04/2026")
        self.assertEqual(source_dates["EUR"], "15/04/2026")
        self.assertEqual(source_dates["IMTP"], "22/04/2026")

    def test_composite_profile_chart_uses_requested_axis_order(self):
        jump_df = _composite_profile_source_df()
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Compuesto", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "TC", "EUR", "IMTP"])

        metric_table = build_composite_profile_metric_table(composite_row)
        self.assertEqual(
            metric_table["Variable"].tolist(),
            ["SJ", "CMJ", "DJ", "DRI", "TC", "EUR", "IMTP"],
        )
        self.assertEqual(
            metric_table.columns.tolist(),
            ["Variable", "Valor", "Z-score", "Origen / referencia"],
        )
        self.assertEqual(
            metric_table.loc[metric_table["Variable"] == "SJ", "Origen / referencia"].iloc[0],
            "15/04/2026",
        )

    def test_composite_profile_chart_renders_without_imtp(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-01", "CMJ_cm": 34, "SJ_cm": 30, "DJ_cm": 26, "DJ_tc_ms": 220},
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-08", "CMJ_cm": 35, "SJ_cm": 31, "DJ_cm": 27, "DJ_tc_ms": 210},
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-15", "CMJ_cm": 36, "SJ_cm": 32, "DJ_cm": 28, "DJ_tc_ms": 205},
                ]
            )
        )
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Sin IMTP", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        radial_values = list(figure.data[-1].r)[:-1]
        radar_center = figure.layout.polar.radialaxis.range[0]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "TC", "EUR", "IMTP"])
        self.assertEqual(radial_values[-1], radar_center)

    def test_composite_profile_chart_keeps_missing_internal_axis_fixed_at_center(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-01", "SJ_cm": 30, "DJ_cm": 24, "DJ_tc_ms": 220, "IMTP_N": 2800, "BW_kg": 78},
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-08", "SJ_cm": 31, "DJ_cm": 25, "DJ_tc_ms": 210, "IMTP_N": 2850, "BW_kg": 78},
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-15", "SJ_cm": 32, "DJ_cm": 26, "DJ_tc_ms": 205, "IMTP_N": 2900, "BW_kg": 78},
                ]
            )
        )
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Parcial", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        radial_values = list(figure.data[-1].r)[:-1]
        radar_center = figure.layout.polar.radialaxis.range[0]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "TC", "EUR", "IMTP"])
        self.assertEqual(radial_values[1], radar_center)

        metric_table = build_composite_profile_metric_table(composite_row)
        cmj_row = metric_table[metric_table["Variable"] == "CMJ"].iloc[0]
        self.assertEqual(cmj_row["Valor"], "-")
        self.assertEqual(cmj_row["Z-score"], "-")
        self.assertEqual(cmj_row["Origen / referencia"], "-")

    def test_metric_trend_chart_uses_chronological_eval_dates(self):
        jump_df = _temporal_jump_df()

        eur_figure = chart_jump_metric_trend(jump_df, "Atleta Delta", "EUR", theme=_chart_theme())
        dj_rsi_figure = chart_jump_metric_trend(jump_df, "Atleta Delta", "DJ_RSI", theme=_chart_theme())

        eur_dates = pd.to_datetime(list(eur_figure.data[0].x)).strftime("%Y-%m-%d").tolist()
        dj_rsi_dates = pd.to_datetime(list(dj_rsi_figure.data[0].x)).strftime("%Y-%m-%d").tolist()

        self.assertEqual(eur_figure.data[0].name, "EUR (ratio)")
        self.assertEqual(dj_rsi_figure.data[0].name, "DJ RSI")
        self.assertEqual(eur_dates, ["2026-04-01", "2026-04-08", "2026-04-15", "2026-04-22"])
        self.assertEqual(dj_rsi_dates, ["2026-04-01", "2026-04-08", "2026-04-15", "2026-04-22"])

    def test_radar_uses_latest_valid_row_when_last_calendar_row_has_no_renderable_axes(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Perfil",
                        "Date": "2026-04-01",
                        "CMJ_cm": 36,
                        "SJ_cm": 31,
                        "DJ_cm": 27,
                        "DJ_tc_ms": 210,
                        "IMTP_N": 3000,
                        "BW_kg": 78,
                    },
                    {
                        "Athlete": "Atleta Perfil",
                        "Date": "2026-04-10",
                        "BW_kg": 79,
                    },
                ]
            )
        )

        latest_valid = find_latest_valid_radar_row(jump_df[jump_df["Athlete"] == "Atleta Perfil"])

        self.assertIsNotNone(latest_valid)
        self.assertEqual(pd.Timestamp(latest_valid["Date"]).strftime("%Y-%m-%d"), "2026-04-01")

    def test_radar_filters_missing_axes_and_still_renders_partial_profile(self):
        partial_row = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Parcial",
                        "Date": "2026-04-10",
                        "CMJ_cm": 35.0,
                        "SJ_cm": 34.0,
                    }
                ]
            )
        ).iloc[0]

        figure = chart_radar(partial_row, "Atleta Parcial", None, theme=_chart_theme())

        self.assertTrue(len(figure.data) >= 2)
        self.assertEqual(list(figure.data[-1].theta), ["CMJ", "CMJ"])

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

    def test_compute_swc_delta_handles_first_second_and_hopkins_cases(self):
        jump_df = _temporal_jump_df()

        first_delta = compute_swc_delta(jump_df, "2026-04-01")
        second_delta = compute_swc_delta(jump_df, "2026-04-08")
        fourth_delta = compute_swc_delta(jump_df, "2026-04-22")

        self.assertTrue(first_delta["Signal"].eq("sin dato anterior").all())

        cmj_second = second_delta[second_delta["Variable"] == "CMJ_cm"].iloc[0]
        self.assertEqual(cmj_second["Threshold_method"], "Fijo")
        self.assertAlmostEqual(float(cmj_second["Threshold_abs"]), 0.45, places=2)
        self.assertEqual(cmj_second["Signal"], "mejora relevante")

        cmj_fourth = fourth_delta[fourth_delta["Variable"] == "CMJ_cm"].iloc[0]
        self.assertEqual(cmj_fourth["Threshold_method"], "Hopkins")
        self.assertEqual(cmj_fourth["Signal"], "mejora relevante")

    def test_compute_swc_delta_inverts_signal_for_lower_is_better_variables(self):
        jump_df = _temporal_jump_df()
        fourth_delta = compute_swc_delta(jump_df, "2026-04-22")
        dj_tc_delta = fourth_delta[fourth_delta["Variable"] == "DJ_tc_ms"].iloc[0]

        self.assertFalse(bool(dj_tc_delta["Higher_is_better"]))
        self.assertEqual(dj_tc_delta["Threshold_method"], "Hopkins")
        self.assertGreater(float(dj_tc_delta["Delta_abs"]), 0)
        self.assertEqual(dj_tc_delta["Signal"], "caida relevante")

    def test_temporal_context_and_display_table_use_relevant_signals(self):
        jump_df = _temporal_jump_df()
        fourth_delta = compute_swc_delta(jump_df, "2026-04-22")

        temporal_lines = build_jump_temporal_context(fourth_delta)
        display_df = build_jump_delta_display_table(fourth_delta)

        self.assertTrue(any("mejora relevante en" in line and "CMJ" in line for line in temporal_lines))
        self.assertTrue(any("caida relevante en" in line and "DJ TC" in line for line in temporal_lines))
        self.assertIn("↑ mejora relevante", display_df["Senal"].tolist())
        self.assertIn("↓ caida relevante", display_df["Senal"].tolist())


if __name__ == "__main__":
    unittest.main()
