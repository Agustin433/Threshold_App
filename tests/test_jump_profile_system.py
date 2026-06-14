from __future__ import annotations

import unittest
import unicodedata

import pandas as pd

from charts.dashboard_charts import (
    chart_composite_profile_radar,
    chart_jump_metric_trend,
    chart_quadrant_exploratory,
    chart_quadrant_rsi_sj,
    chart_radar,
    find_latest_valid_radar_row,
)
from modules.jump_analysis import (
    PATTERN_LIBRARY,
    NEUROMUSCULAR_PATTERN_FIELDS,
    _prepare_jump_df,
    _records_to_jump_df,
    build_dashboard_neuromuscular_payload,
    build_neuromuscular_profile_result,
    build_composite_profile_metric_table,
    build_composite_profile_metric_rows,
    build_composite_profile_snapshot,
    build_profile_radar_row,
    build_jump_baseline_display_table,
    build_jump_delta_display_table,
    build_jump_feedback_lines,
    build_jump_flag_rows,
    build_jump_metric_table,
    build_jump_temporal_context,
    choose_secondary_quadrant_x_spec,
    classify_neuromuscular_quadrant,
    compute_baseline_delta,
    compute_swc_delta,
    resolve_zscore,
    select_primary_profile_row,
)
from modules.report_generator import _build_pdf_neuromuscular_profile_payload


def _normalized_label(value: object) -> str:
    return unicodedata.normalize("NFD", str(value)).encode("ascii", "ignore").decode("ascii").lower()


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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 30,
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
                    "DJ_drop_height_cm": 24,
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
                    "DJ_drop_height_cm": 25,
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
                    "DJ_drop_height_cm": 26.94,
                    "DJ_cm": 28,
                    "DJ_tc_ms": 200,
                    "IMTP_N": 3100,
                    "BW_kg": 80,
                },
            ]
        )
    )


def _synthetic_profile_row(**overrides) -> pd.Series:
    base = {
        "Date": "2026-05-01",
        "SJ_cm": 32.0,
        "CMJ_cm": 34.0,
        "DJ_cm": 26.0,
        "DJ_RSI": 1.40,
        "DJ_tc_ms": 220.0,
        "IMTP_relPF": 38.0,
        "IMTP_N": 3000.0,
        "EUR": 1.062,
        "SJ_Z": 0.10,
        "CMJ_Z": 0.15,
        "DJ_height_Z": 0.05,
        "DJ_RSI_Z": 0.10,
        "TC_inv_Z": 0.05,
        "IMTP_relPF_Z": 0.20,
    }
    base.update(overrides)
    return pd.Series(base)


def _combined_neuromuscular_text(result: dict[str, object]) -> str:
    fields = (
        "profile_label",
        "phys",
        "bio",
        "train",
        "summary_short",
        "summary_athlete",
        "summary_client",
        "summary_professional",
        "profile_source_note",
    )
    return " ".join(str(result.get(field) or "") for field in fields).lower()


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
        self.assertEqual(athlete_a["EUR_Profile"], "Reactivo")
        self.assertEqual(athlete_b["EUR_Profile"], "Base de Fuerza")
        self.assertEqual(athlete_c["EUR_Profile"], "Reactivo")

    def test_feedback_and_flags_follow_official_rules(self):
        jump_df = _sample_jump_df()
        athlete_b = jump_df[jump_df["Athlete"] == "Atleta B"].iloc[0]

        flags = build_jump_flag_rows(athlete_b)
        texts = [item["text"] for item in flags]
        self.assertTrue(any("EUR bajo" in text or "contramovimiento" in text for text in texts))
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
            ["SJ", "CMJ", "DJ height", "DJ RSI", "Tiempo de contacto", "IMTP relPF"],
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
        self.assertEqual(source_dates["Tiempo de contacto"], "22/04/2026")
        self.assertEqual(source_dates["EUR"], "15/04/2026")
        self.assertEqual(source_dates["IMTP"], "22/04/2026")

    def test_composite_profile_chart_uses_requested_axis_order(self):
        jump_df = _composite_profile_source_df()
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Compuesto", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "Tiempo de contacto", "EUR", "IMTP"])

        metric_table = build_composite_profile_metric_table(composite_row)
        self.assertEqual(
            metric_table["Variable"].tolist(),
            ["SJ", "CMJ", "DJ", "DRI", "Tiempo de contacto", "EUR", "IMTP"],
        )
        self.assertEqual(
            metric_table.columns.tolist(),
            ["Variable", "Valor", "Z-score", "Origen / referencia"],
        )
        self.assertEqual(
            metric_table.loc[metric_table["Variable"] == "SJ", "Origen / referencia"].iloc[0],
            "15/04/2026",
        )

    def test_composite_profile_metric_table_shows_zscores_when_history_is_sufficient(self):
        jump_df = _composite_profile_source_df()
        composite_row, _ = build_composite_profile_snapshot(jump_df)
        metric_table = build_composite_profile_metric_table(composite_row)
        zscores = dict(zip(metric_table["Variable"], metric_table["Z-score"]))

        self.assertNotEqual(zscores["SJ"], "—")
        self.assertNotEqual(zscores["CMJ"], "—")
        self.assertNotEqual(zscores["DJ"], "—")
        self.assertNotEqual(zscores["DRI"], "—")
        self.assertNotEqual(zscores["Tiempo de contacto"], "—")
        self.assertNotEqual(zscores["EUR"], "—")
        self.assertNotEqual(zscores["IMTP"], "—")

    def test_composite_profile_uses_zscore_aliases_shared_by_dashboard_and_quadrants(self):
        jump_df = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta Alias",
                    "Date": "2026-05-01",
                    "SJ_cm": 31,
                    "CMJ_cm": 35,
                    "DJ_drop_height_cm": 30,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    "DRI": 1.29,
                    "DJ_RSI": 1.29,
                    "EUR": 1.129,
                    "IMTP_relPF": 39.5,
                    "SJ_Z": -0.20,
                    "CMJ_Z": 0.30,
                    "DJ_height_Z": 0.10,
                    "DRI_Z": 0.35,
                    "DJ_RSI_Z": 0.45,
                    "DJtc_Z": 0.80,
                    "EUR_Z": 0.25,
                    "IMTP_Z": 0.60,
                }
            ]
        )

        composite_row, _ = build_composite_profile_snapshot(jump_df)
        metric_table = build_composite_profile_metric_table(composite_row)
        rows = build_composite_profile_metric_rows(composite_row)
        zscores = dict(zip(metric_table["Variable"], metric_table["Z-score"]))

        self.assertEqual(zscores["DRI"], 0.35)
        self.assertEqual(zscores["Tiempo de contacto"], 0.80)
        self.assertNotEqual(zscores["IMTP"], "—")
        self.assertEqual(composite_row["DRI_Z"], 0.35)
        self.assertFalse(pd.isna(composite_row["DJ_RSI_Z"]))
        self.assertNotEqual(composite_row["DRI_Z"], composite_row["DJ_RSI_Z"])
        self.assertEqual(composite_row["TC_inv_Z"], composite_row["DJtc_Z"])
        self.assertEqual(composite_row["IMTP_relPF_Z"], composite_row["IMTP_Z"])
        self.assertEqual(
            next(row for row in rows if row["Variable"] == "Tiempo de contacto")["Direccion"],
            "lower_is_better_inverted_z",
        )

        figure = chart_composite_profile_radar(composite_row, "Atleta Alias", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        radial_values = list(figure.data[-1].r)[:-1]
        self.assertEqual(axis_order[4], "Tiempo de contacto")
        self.assertEqual(radial_values[4], 0.80)

    def test_contact_time_composite_zscore_keeps_lower_is_better_semantics(self):
        jump_df = pd.DataFrame(
            [
                    {"Athlete": "Atleta TC", "Date": "2026-04-01", "DJ_drop_height_cm": 30.0, "DJ_cm": 24.0, "DJ_tc_ms": 260.0},
                    {"Athlete": "Atleta TC", "Date": "2026-04-08", "DJ_drop_height_cm": 30.0, "DJ_cm": 24.0, "DJ_tc_ms": 250.0},
                    {"Athlete": "Atleta TC", "Date": "2026-04-15", "DJ_drop_height_cm": 30.0, "DJ_cm": 24.0, "DJ_tc_ms": 240.0},
                    {"Athlete": "Atleta TC", "Date": "2026-04-22", "DJ_drop_height_cm": 30.0, "DJ_cm": 24.0, "DJ_tc_ms": 220.0},
            ]
        )

        composite_row, _ = build_composite_profile_snapshot(jump_df)
        rows = build_composite_profile_metric_rows(composite_row)
        contact_row = next(row for row in rows if row["Variable"] == "Tiempo de contacto")

        self.assertEqual(contact_row["Direccion"], "lower_is_better_inverted_z")
        self.assertGreater(float(contact_row["Z-score"]), 0)

    def test_composite_profile_chart_renders_without_imtp(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-01", "CMJ_cm": 34, "SJ_cm": 30, "DJ_drop_height_cm": 30, "DJ_cm": 26, "DJ_tc_ms": 220},
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-08", "CMJ_cm": 35, "SJ_cm": 31, "DJ_drop_height_cm": 30, "DJ_cm": 27, "DJ_tc_ms": 210},
                    {"Athlete": "Atleta Sin IMTP", "Date": "2026-04-15", "CMJ_cm": 36, "SJ_cm": 32, "DJ_drop_height_cm": 30, "DJ_cm": 28, "DJ_tc_ms": 205},
                ]
            )
        )
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Sin IMTP", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        radial_values = list(figure.data[-1].r)[:-1]
        radar_center = figure.layout.polar.radialaxis.range[0]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "Tiempo de contacto", "EUR", "IMTP"])
        self.assertEqual(radial_values[-1], radar_center)

    def test_composite_profile_chart_keeps_missing_internal_axis_fixed_at_center(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-01", "SJ_cm": 30, "DJ_drop_height_cm": 30, "DJ_cm": 24, "DJ_tc_ms": 220, "IMTP_N": 2800, "BW_kg": 78},
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-08", "SJ_cm": 31, "DJ_drop_height_cm": 30, "DJ_cm": 25, "DJ_tc_ms": 210, "IMTP_N": 2850, "BW_kg": 78},
                    {"Athlete": "Atleta Parcial", "Date": "2026-04-15", "SJ_cm": 32, "DJ_drop_height_cm": 30, "DJ_cm": 26, "DJ_tc_ms": 205, "IMTP_N": 2900, "BW_kg": 78},
                ]
            )
        )
        composite_row, _ = build_composite_profile_snapshot(jump_df)

        figure = chart_composite_profile_radar(composite_row, "Atleta Parcial", theme=_chart_theme())
        axis_order = list(figure.data[-1].theta)[:-1]
        radial_values = list(figure.data[-1].r)[:-1]
        radar_center = figure.layout.polar.radialaxis.range[0]

        self.assertEqual(axis_order, ["SJ", "CMJ", "DJ", "DRI", "Tiempo de contacto", "EUR", "IMTP"])
        self.assertEqual(radial_values[1], radar_center)

        metric_table = build_composite_profile_metric_table(composite_row)
        cmj_row = metric_table[metric_table["Variable"] == "CMJ"].iloc[0]
        self.assertEqual(cmj_row["Valor"], "-")
        self.assertEqual(cmj_row["Z-score"], "—")
        self.assertEqual(cmj_row["Origen / referencia"], "-")

    def test_composite_profile_metric_table_keeps_internal_zscores_missing_when_history_is_insufficient(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Z",
                        "Date": "2026-04-10",
                        "CMJ_cm": 35,
                        "SJ_cm": 31,
                        "DJ_drop_height_cm": 30,
                        "DJ_cm": 27,
                        "DJ_tc_ms": 210,
                        "IMTP_N": 3000,
                        "BW_kg": 80,
                    }
                ]
            )
        )

        composite_row, _ = build_composite_profile_snapshot(jump_df)
        metric_table = build_composite_profile_metric_table(composite_row)
        zscores = dict(zip(metric_table["Variable"], metric_table["Z-score"]))

        self.assertEqual(zscores["SJ"], "\u2014")
        self.assertNotEqual(zscores["CMJ"], "\u2014")
        self.assertEqual(zscores["DJ"], "\u2014")
        self.assertEqual(zscores["DRI"], "\u2014")
        self.assertEqual(zscores["Tiempo de contacto"], "\u2014")
        self.assertEqual(zscores["EUR"], "\u2014")
        self.assertNotEqual(zscores["IMTP"], "\u2014")

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

    def test_rsi_quadrant_uses_dj_rsi_even_when_dri_is_missing(self):
        jump_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "SJ_Z": 0.8, "DJ_RSI_Z": 0.6, "DJ_RSI": 1.55},
                {"Athlete": "Bruno Rey", "Date": "2026-05-01", "SJ_Z": -0.2, "DJ_RSI_Z": -0.4, "DJ_RSI": 1.20},
            ]
        )

        rsi_figure = chart_quadrant_rsi_sj(jump_df, theme=_chart_theme())
        dri_figure = chart_quadrant_exploratory(jump_df, theme=_chart_theme())

        self.assertIn("DJ RSI", str(rsi_figure.layout.title.text))
        self.assertGreater(len(rsi_figure.data), 0)
        self.assertIn("No hay suficientes datos de DRI", str(dri_figure.layout.annotations[0].text))

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

    def test_profile_radar_row_does_not_fabricate_relpf_from_previous_body_weight(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Radar",
                        "Date": "2026-04-01",
                        "CMJ_cm": 34,
                        "SJ_cm": 30,
                        "DJ_cm": 26,
                        "DJ_tc_ms": 220,
                        "IMTP_N": 3000,
                        "BW_kg": 80,
                    },
                    {
                        "Athlete": "Atleta Radar",
                        "Date": "2026-04-10",
                        "CMJ_cm": 36,
                        "SJ_cm": 31,
                        "DJ_cm": 27,
                        "DJ_tc_ms": 210,
                        "IMTP_N": 3200,
                        "BW_kg": 0,
                    },
                ]
            )
        )

        radar_row = build_profile_radar_row(jump_df[jump_df["Athlete"] == "Atleta Radar"])
        figure = chart_radar(radar_row, "Atleta Radar", None, theme=_chart_theme())

        self.assertIsNotNone(radar_row)
        self.assertFalse(bool(radar_row.get("Profile_Composed", False)))
        self.assertTrue(pd.isna(radar_row.get("IMTP_relPF")))
        self.assertEqual(
            list(figure.data[-1].theta)[:-1],
            ["SJ", "CMJ", "DJ height", "DJ RSI"],
        )

    def test_records_to_jump_df_keeps_positive_body_weight_when_zero_arrives_later_same_day(self):
        jump_df = _records_to_jump_df(
            [
                {
                    "Athlete": "Atleta Radar",
                    "Date": "2026-04-10",
                    "test_type": "CMJ",
                    "CMJ_cm": 36,
                    "SJ_cm": 31,
                    "DJ_cm": 27,
                    "DJ_tc_ms": 210,
                    "BW_kg": 88,
                },
                {
                    "Athlete": "Atleta Radar",
                    "Date": "2026-04-10",
                    "test_type": "IMTP",
                    "IMTP_N": 4191,
                    "BW_kg": 0,
                },
            ]
        )

        self.assertEqual(len(jump_df), 1)
        self.assertAlmostEqual(float(jump_df.iloc[0]["BW_kg"]), 88.0, places=2)
        self.assertAlmostEqual(float(jump_df.iloc[0]["IMTP_relPF"]), 47.62, places=2)

    def test_prepare_jump_df_does_not_reuse_previous_body_weight_for_new_imtp_only_day(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Historico",
                        "Date": "2026-04-01",
                        "CMJ_cm": 41.3,
                        "SJ_cm": 29.1,
                        "DJ_cm": 37.3,
                        "DJ_tc_ms": 189,
                        "BW_kg": 88,
                        "IMTP_N": 3902,
                    },
                    {
                        "Athlete": "Atleta Historico",
                        "Date": "2026-05-07",
                        "IMTP_N": 4191,
                        "BW_kg": 0,
                    },
                ]
            )
        )

        latest_row = jump_df.sort_values("Date").iloc[-1]
        composite_row, source_table = build_composite_profile_snapshot(jump_df)
        metric_table = build_composite_profile_metric_table(composite_row)
        imtp_row = metric_table[metric_table["Variable"] == "IMTP"].iloc[0]

        self.assertAlmostEqual(float(latest_row["BW_kg"]), 0.0, places=2)
        self.assertTrue(pd.isna(latest_row.get("IMTP_relPF")))
        self.assertTrue(pd.isna(composite_row.get("IMTP_relPF")))
        self.assertEqual(dict(zip(source_table["Variable"], source_table["Fecha origen"]))["IMTP"], "07/05/2026")
        self.assertEqual(imtp_row["Valor"], "4191 N")

    def test_composite_profile_uses_raw_imtp_when_body_weight_is_unavailable(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Nuevo",
                        "Date": "2026-05-07",
                        "CMJ_cm": 50.0,
                        "SJ_cm": 40.0,
                        "DJ_cm": 44.7,
                        "DJ_tc_ms": 226,
                        "BW_kg": 0,
                        "IMTP_N": 3385,
                    }
                ]
            )
        )

        composite_row, source_table = build_composite_profile_snapshot(jump_df)
        metric_table = build_composite_profile_metric_table(composite_row)
        metric_rows = build_composite_profile_metric_rows(composite_row)
        imtp_row = metric_table[metric_table["Variable"] == "IMTP"].iloc[0]
        imtp_metric = next(row for row in metric_rows if row["Variable"] == "IMTP")

        self.assertTrue(pd.isna(composite_row.get("IMTP_relPF")))
        self.assertEqual(imtp_row["Valor"], "3385 N")
        self.assertAlmostEqual(float(imtp_row["Z-score"]), 0.21, places=2)
        self.assertEqual(dict(zip(source_table["Variable"], source_table["Fecha origen"]))["IMTP"], "07/05/2026")
        self.assertEqual(imtp_metric["value_col"], "IMTP_N")
        self.assertEqual(imtp_metric["z_col"], "IMTP_N_Z")

    def test_prepare_jump_df_normalizes_legacy_imtp_rfd_aliases_when_new_missing(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Legacy",
                        "Date": "2026-04-10",
                        "IMTP_N": 3800,
                        "BW_kg": 80,
                        "RFD_50": 1200,
                        "RFD_100": 2400,
                        "RFD_150": 3200,
                        "RFD_250": 4100,
                    }
                ]
            )
        )

        self.assertEqual(len(jump_df), 1)
        self.assertEqual(float(jump_df.iloc[0]["IMTP_rfd_50_N_s"]), 1200.0)
        self.assertEqual(float(jump_df.iloc[0]["IMTP_rfd_100_N_s"]), 2400.0)
        self.assertEqual(float(jump_df.iloc[0]["IMTP_rfd_150_N_s"]), 3200.0)
        self.assertEqual(float(jump_df.iloc[0]["IMTP_rfd_250_N_s"]), 4100.0)

    def test_prepare_jump_df_preserves_new_imtp_rfd_values_over_legacy_aliases(self):
        jump_df = _prepare_jump_df(
            pd.DataFrame(
                [
                    {
                        "Athlete": "Atleta Canonico",
                        "Date": "2026-04-10",
                        "IMTP_N": 3800,
                        "BW_kg": 80,
                        "RFD_100": 2400,
                        "IMTP_rfd_100_N_s": 2558,
                    }
                ]
            )
        )

        self.assertEqual(len(jump_df), 1)
        self.assertEqual(float(jump_df.iloc[0]["IMTP_rfd_100_N_s"]), 2558.0)

    def test_extra_imtp_force_time_columns_are_additive_for_profile_radar_and_quadrants(self):
        base_input = pd.DataFrame(
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
            ]
        )
        enriched_input = base_input.copy()
        for column, value in {
            "IMTP_avg_N": 2993,
            "IMTP_force_L_N": 1731,
            "IMTP_force_R_N": 1653,
            "IMTP_asym_pct": 4.5,
            "IMTP_pretension": 1109,
            "IMTP_time_max_s": 2.63,
            "IMTP_time_pull_s": 3.0,
            "IMTP_force_50_N": 1172,
            "IMTP_force_100_N": 1364,
            "IMTP_force_150_N": 1620,
            "IMTP_force_200_N": 1957,
            "IMTP_force_250_N": 2232,
            "IMTP_rfd_50_N_s": 1260,
            "IMTP_rfd_100_N_s": 2558,
            "IMTP_rfd_150_N_s": 3411,
            "IMTP_rfd_250_N_s": 4493,
        }.items():
            enriched_input[column] = value

        base_df = _prepare_jump_df(base_input)
        enriched_df = _prepare_jump_df(enriched_input)

        for column in (
            "EUR",
            "DJ_RSI",
            "DRI",
            "IMTP_relPF",
            "Jump_Momentum",
            "DSI",
            "SJ_Z",
            "CMJ_Z",
            "DJ_height_Z",
            "TC_inv_Z",
            "EUR_Z",
            "IMTP_relPF_Z",
            "IMTP_Z",
            "NM_Profile",
            "EUR_Profile",
        ):
            with self.subTest(column=column):
                pd.testing.assert_series_equal(base_df[column], enriched_df[column], check_names=False)

        base_radar = chart_radar(base_df.iloc[0], "Atleta A", None, theme=_chart_theme())
        enriched_radar = chart_radar(enriched_df.iloc[0], "Atleta A", None, theme=_chart_theme())

        self.assertEqual(list(base_radar.data[-1].theta), list(enriched_radar.data[-1].theta))
        self.assertEqual(choose_secondary_quadrant_x_spec(base_df), choose_secondary_quadrant_x_spec(enriched_df))
        self.assertNotIn("IMTP_rfd_200_N_s", enriched_df.columns)

    def test_iso_push_hamstring_columns_do_not_change_profile_radar_or_composite(self):
        base_input = pd.DataFrame(
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
            ]
        )
        enriched_input = base_input.copy()
        for column, value in {
            "ISO_HAM_N": 1280,
            "ISO_HAM_avg_N": 1115,
            "ISO_HAM_force_L_N": 670,
            "ISO_HAM_force_R_N": 610,
            "ISO_HAM_asym_pct": 9.4,
            "ISO_HAM_pretension": 180,
            "ISO_HAM_time_max_s": 1.84,
            "ISO_HAM_time_pull_s": 2.20,
            "ISO_HAM_force_50_N": 290,
            "ISO_HAM_force_100_N": 455,
            "ISO_HAM_force_150_N": 620,
            "ISO_HAM_force_200_N": 785,
            "ISO_HAM_force_250_N": 930,
            "ISO_HAM_rfd_50_N_s": 1280,
            "ISO_HAM_rfd_100_N_s": 2240,
            "ISO_HAM_rfd_150_N_s": 2960,
            "ISO_HAM_rfd_250_N_s": 3720,
        }.items():
            enriched_input[column] = value

        base_df = _prepare_jump_df(base_input)
        enriched_df = _prepare_jump_df(enriched_input)

        for column in ("EUR", "DJ_RSI", "DRI", "IMTP_relPF", "Jump_Momentum", "DSI", "IMTP_Z", "NM_Profile", "EUR_Profile"):
            with self.subTest(column=column):
                pd.testing.assert_series_equal(base_df[column], enriched_df[column], check_names=False)

        base_radar = chart_radar(base_df.iloc[0], "Atleta A", None, theme=_chart_theme())
        enriched_radar = chart_radar(enriched_df.iloc[0], "Atleta A", None, theme=_chart_theme())
        composite_row, _ = build_composite_profile_snapshot(enriched_df)
        metric_table = build_composite_profile_metric_table(composite_row)

        self.assertEqual(list(base_radar.data[-1].theta), list(enriched_radar.data[-1].theta))
        self.assertEqual(choose_secondary_quadrant_x_spec(base_df), choose_secondary_quadrant_x_spec(enriched_df))
        self.assertEqual(metric_table["Variable"].tolist(), ["SJ", "CMJ", "DJ", "DRI", "Tiempo de contacto", "EUR", "IMTP"])
        self.assertNotIn("ISO_HAM_rfd_200_N_s", enriched_df.columns)

    def test_primary_profile_row_ignores_newer_iso_only_row(self):
        jump_df = pd.DataFrame(
            [
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-01",
                    "CMJ_cm": 38,
                    "SJ_cm": 32,
                    "DJ_cm": 28,
                    "DJ_tc_ms": 220,
                    "IMTP_N": 2800,
                    "BW_kg": 78,
                },
                {
                    "Athlete": "Atleta ISO",
                    "Date": "2026-04-10",
                    "ISO_HAM_N": 1280,
                    "ISO_HAM_avg_N": 1115,
                    "ISO_HAM_force_L_N": 670,
                    "ISO_HAM_force_R_N": 610,
                    "ISO_HAM_asym_pct": 9.4,
                    "ISO_HAM_time_max_s": 1.84,
                    "ISO_HAM_force_100_N": 455,
                    "ISO_HAM_force_200_N": 785,
                    "ISO_HAM_force_250_N": 930,
                    "ISO_HAM_rfd_50_N_s": 1280,
                    "ISO_HAM_rfd_100_N_s": 2240,
                    "ISO_HAM_rfd_150_N_s": 2960,
                    "ISO_HAM_rfd_250_N_s": 3720,
                },
            ]
        )

        primary_row = select_primary_profile_row(jump_df, selected_date="2026-04-10")
        radar_row = build_profile_radar_row(jump_df[jump_df["Athlete"] == "Atleta ISO"])
        composite_row, _ = build_composite_profile_snapshot(jump_df[jump_df["Athlete"] == "Atleta ISO"])

        self.assertIsNotNone(primary_row)
        self.assertEqual(pd.Timestamp(primary_row["Date"]).strftime("%Y-%m-%d"), "2026-04-01")
        self.assertIsNotNone(radar_row)
        self.assertAlmostEqual(float(radar_row["CMJ_cm"]), 38.0, places=3)
        self.assertAlmostEqual(float(composite_row["IMTP_relPF"]), 35.9, places=1)
        self.assertNotIn("ISO_HAM_rfd_200_N_s", composite_row.index)

    def test_prepare_jump_df_merges_same_day_iso_rows_additively_without_changing_profile_metrics(self):
        primary_row = {
            "Athlete": "Atleta Merge",
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
        }
        iso_row = {
            "Athlete": "Atleta Merge",
            "Date": "2026-04-01",
            "ISO_HAM_N": 1280,
            "ISO_HAM_avg_N": 1115,
            "ISO_HAM_force_L_N": 670,
            "ISO_HAM_force_R_N": 610,
            "ISO_HAM_asym_pct": 9.4,
            "ISO_HAM_time_max_s": 1.84,
            "ISO_HAM_force_100_N": 455,
            "ISO_HAM_force_200_N": 785,
            "ISO_HAM_force_250_N": 930,
            "ISO_HAM_rfd_50_N_s": 1280,
            "ISO_HAM_rfd_100_N_s": 2240,
            "ISO_HAM_rfd_150_N_s": 2960,
            "ISO_HAM_rfd_250_N_s": 3720,
        }

        base_df = _prepare_jump_df(pd.DataFrame([primary_row]))
        merged_df = _prepare_jump_df(pd.DataFrame([primary_row, iso_row]))

        self.assertEqual(len(merged_df), 1)
        self.assertEqual(float(merged_df.iloc[0]["ISO_HAM_force_100_N"]), 455.0)
        self.assertEqual(float(merged_df.iloc[0]["ISO_HAM_rfd_250_N_s"]), 3720.0)
        self.assertNotIn("ISO_HAM_rfd_200_N_s", merged_df.columns)

        for column in ("EUR", "DJ_RSI", "DRI", "IMTP_relPF", "Jump_Momentum", "DSI", "IMTP_Z", "NM_Profile", "EUR_Profile"):
            with self.subTest(column=column):
                pd.testing.assert_series_equal(base_df[column], merged_df[column], check_names=False)

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
        self.assertTrue(any("caida relevante en" in line and "Tiempo de contacto" in line for line in temporal_lines))
        self.assertIn("↑ mejora relevante", display_df["Senal"].tolist())
        self.assertIn("↓ caida relevante", display_df["Senal"].tolist())

    def test_compute_baseline_delta_requires_three_valid_measurements(self):
        jump_df = _temporal_jump_df()

        second_baseline = compute_baseline_delta(jump_df, "2026-04-08")
        cmj_second = second_baseline[second_baseline["Variable"] == "CMJ_cm"].iloc[0]

        self.assertEqual(cmj_second["Signal"], "baseline insuficiente")
        self.assertEqual(int(cmj_second["N_valid"]), 2)
        self.assertTrue(pd.isna(cmj_second["Baseline_value"]))

    def test_compute_baseline_delta_uses_first_three_values_per_variable(self):
        jump_df = _temporal_jump_df()

        fourth_baseline = compute_baseline_delta(jump_df, "2026-04-22")
        cmj_fourth = fourth_baseline[fourth_baseline["Variable"] == "CMJ_cm"].iloc[0]

        self.assertAlmostEqual(float(cmj_fourth["Baseline_value"]), 31.0, places=2)
        self.assertAlmostEqual(float(cmj_fourth["Delta_abs"]), 3.0, places=2)
        self.assertAlmostEqual(float(cmj_fourth["Delta_pct"]), 9.68, places=2)
        self.assertEqual(cmj_fourth["Baseline_method"], "Promedio primeras 3 mediciones validas")
        self.assertEqual(cmj_fourth["Signal"], "mejora vs baseline")

    def test_compute_baseline_delta_inverts_signal_for_lower_is_better_variables(self):
        jump_df = _temporal_jump_df()

        fourth_baseline = compute_baseline_delta(jump_df, "2026-04-22")
        dj_tc_baseline = fourth_baseline[fourth_baseline["Variable"] == "DJ_tc_ms"].iloc[0]

        self.assertFalse(bool(dj_tc_baseline["Higher_is_better"]))
        self.assertAlmostEqual(float(dj_tc_baseline["Baseline_value"]), (220 + 210 + 205) / 3, places=2)
        self.assertGreater(float(dj_tc_baseline["Delta_abs"]), 0)
        self.assertEqual(dj_tc_baseline["Signal"], "caida vs baseline")

    def test_baseline_display_table_reports_insufficient_baseline(self):
        jump_df = _temporal_jump_df()

        second_baseline = compute_baseline_delta(jump_df, "2026-04-08")
        display_df = build_jump_baseline_display_table(second_baseline)

        self.assertIn("baseline insuficiente", display_df["Senal"].tolist())
        self.assertTrue(any("N=2/3" in str(value) for value in display_df["Metodo"].tolist()))

    def test_neuromuscular_profile_result_imports_and_handles_empty_row(self):
        result = build_neuromuscular_profile_result(pd.Series(dtype=object))

        self.assertIsInstance(result, dict)
        self.assertEqual(result["profile_code"], "UNCLASSIFIED")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["profile_source"], "unknown")
        self.assertEqual(result["profile_source_label"], "Fuente no determinada")
        self.assertIn("missing_imtp", result["flags"])
        self.assertIn("missing_dj", result["flags"])
        self.assertIn("insufficient_pattern_evidence", result["flags"])
        self.assertEqual(result["metrics"]["SJ_cm"]["label"], "SJ")

    def test_neuromuscular_profile_result_marks_latest_valid_row_when_date_exists(self):
        row = _synthetic_profile_row(Date="2026-05-10")

        result = build_neuromuscular_profile_result(row)

        self.assertEqual(result["profile_source"], "latest_valid_row")
        self.assertEqual(result["profile_source_label"], "Ultima evaluacion valida")
        self.assertEqual(result["profile_source_dates"]["SJ_cm"], "2026-05-10")
        self.assertFalse(result["profile_source_is_composite"])

    def test_neuromuscular_profile_result_marks_composite_snapshot_and_keeps_dates(self):
        jump_df = _composite_profile_source_df()
        snapshot_row, _ = build_composite_profile_snapshot(jump_df)

        assert snapshot_row is not None
        result = build_neuromuscular_profile_result(snapshot_row)

        self.assertEqual(result["profile_source"], "composite_snapshot")
        self.assertEqual(result["profile_source_label"], "Perfil compuesto")
        self.assertTrue(result["profile_source_is_composite"])
        self.assertIn("SJ_cm", result["profile_source_dates"])
        self.assertIn("DJ_RSI", result["profile_source_dates"])
        self.assertEqual(result["profile_source_dates"]["SJ_cm"], "2026-04-15")
        self.assertEqual(result["profile_code"], build_neuromuscular_profile_result(snapshot_row)["profile_code"])

    def test_resolve_zscore_prefers_canonical_contact_time_field(self):
        row = pd.Series({"TC_inv_Z": 0.55, "DJtc_Z": -0.10})

        self.assertEqual(resolve_zscore(row, "TC_inv_Z"), 0.55)

    def test_resolve_zscore_falls_back_to_contact_time_alias(self):
        row = pd.Series({"DJtc_Z": 0.80})

        self.assertEqual(resolve_zscore(row, "TC_inv_Z"), 0.80)

    def test_resolve_zscore_prefers_canonical_imtp_relpf_field(self):
        row = pd.Series({"IMTP_relPF_Z": 0.42, "IMTP_Z": -0.20})

        self.assertEqual(resolve_zscore(row, "IMTP_relPF_Z"), 0.42)

    def test_resolve_zscore_falls_back_to_imtp_legacy_alias(self):
        row = pd.Series({"IMTP_Z": 0.60})

        self.assertEqual(resolve_zscore(row, "IMTP_relPF_Z"), 0.60)

    def test_resolve_zscore_keeps_dj_height_and_dj_rsi_separate(self):
        row = pd.Series({"DJ_height_Z": -0.40, "DJ_RSI_Z": 0.75})

        self.assertEqual(resolve_zscore(row, "DJ_height_Z"), -0.40)
        self.assertEqual(resolve_zscore(row, "DJ_RSI_Z"), 0.75)

    def test_resolve_zscore_keeps_mrsi_separate_from_dj_rsi(self):
        row = pd.Series({"mRSI_Z": 0.33, "DJ_RSI_Z": -0.66})

        self.assertEqual(resolve_zscore(row, "mRSI_Z"), 0.33)
        self.assertEqual(resolve_zscore(row, "DJ_RSI_Z"), -0.66)

    def test_dashboard_payload_matches_pdf_payload_on_empty_row(self):
        dashboard_payload = build_dashboard_neuromuscular_payload(pd.Series(dtype=object))
        pdf_payload = _build_pdf_neuromuscular_profile_payload(pd.Series(dtype=object))

        self.assertEqual(dashboard_payload["source"], "core")
        self.assertEqual(dashboard_payload["profile_code"], pdf_payload["profile_code"])
        self.assertEqual(_normalized_label(dashboard_payload["profile_label"]), _normalized_label(pdf_payload["profile_label"]))
        self.assertEqual(dashboard_payload["profile_source"], pdf_payload["profile_source"])
        self.assertEqual(set(dashboard_payload["flags"]), set(pdf_payload["flags"]))
        self.assertIn("missing_imtp", dashboard_payload["flags"])
        self.assertIn("missing_dj", dashboard_payload["flags"])
        self.assertTrue(dashboard_payload["feedback_lines"])
        self.assertTrue(dashboard_payload["flag_rows"])

    def test_dashboard_payload_matches_pdf_profile_code_and_label(self):
        row = _synthetic_profile_row(SJ_Z=0.80, DJ_RSI_Z=-0.80)

        dashboard_payload = build_dashboard_neuromuscular_payload(row)
        pdf_payload = _build_pdf_neuromuscular_profile_payload(row)

        self.assertEqual(dashboard_payload["profile_code"], pdf_payload["profile_code"])
        self.assertEqual(_normalized_label(dashboard_payload["profile_label"]), _normalized_label(pdf_payload["profile_label"]))
        self.assertEqual(dashboard_payload["confidence"], pdf_payload["confidence"])
        self.assertEqual(dashboard_payload["profile_source"], pdf_payload["profile_source"])
        self.assertEqual(set(dashboard_payload["flags"]), set(pdf_payload["flags"]))
        self.assertIn("Patron A", dashboard_payload["profile_metric_value"])

    def test_dashboard_payload_handles_missing_imtp_without_keyerror(self):
        row = _synthetic_profile_row(IMTP_relPF=None, IMTP_N=None, IMTP_relPF_Z=None)

        dashboard_payload = build_dashboard_neuromuscular_payload(row)
        pdf_payload = _build_pdf_neuromuscular_profile_payload(row)

        self.assertEqual(dashboard_payload["profile_code"], pdf_payload["profile_code"])
        self.assertEqual(set(dashboard_payload["flags"]), set(pdf_payload["flags"]))
        self.assertIn("missing_imtp", dashboard_payload["flags"])
        self.assertTrue(any("IMTP" in item["text"] for item in dashboard_payload["flag_rows"]))

    def test_dashboard_payload_handles_missing_dj_without_keyerror(self):
        row = _synthetic_profile_row(DJ_cm=None, DJ_RSI=None, DJ_tc_ms=None, DJ_RSI_Z=None, DJ_height_Z=None)

        dashboard_payload = build_dashboard_neuromuscular_payload(row)
        pdf_payload = _build_pdf_neuromuscular_profile_payload(row)

        self.assertEqual(dashboard_payload["profile_code"], pdf_payload["profile_code"])
        self.assertEqual(set(dashboard_payload["flags"]), set(pdf_payload["flags"]))
        self.assertIn("missing_dj", dashboard_payload["flags"])
        self.assertTrue(any("DJ" in item["text"] for item in dashboard_payload["flag_rows"]))

    def test_dashboard_payload_keeps_pattern_e_alert_consistent_with_pdf(self):
        row = _synthetic_profile_row(
            EUR=0.95,
            CMJ_cm=29.0,
            SJ_cm=31.0,
            SJ_Z=0.10,
            DJ_RSI_Z=0.15,
            IMTP_relPF_Z=0.20,
        )

        dashboard_payload = build_dashboard_neuromuscular_payload(row)
        pdf_payload = _build_pdf_neuromuscular_profile_payload(row)

        self.assertEqual(dashboard_payload["profile_code"], "E")
        self.assertEqual(dashboard_payload["profile_code"], pdf_payload["profile_code"])
        self.assertEqual(_normalized_label(dashboard_payload["profile_label"]), _normalized_label(pdf_payload["profile_label"]))
        self.assertIn("cmj_lower_than_sj", dashboard_payload["flags"])
        self.assertTrue(any("CMJ < SJ" in item["text"] for item in dashboard_payload["flag_rows"]))
        self.assertTrue(any("Patron E" in line for line in dashboard_payload["feedback_lines"]))

    def test_dashboard_and_pdf_payloads_resolve_same_canonical_zscores(self):
        row = pd.Series(
            {
                "SJ_cm": 31.0,
                "CMJ_cm": 35.0,
                "DJ_cm": 25.0,
                "DJ_RSI": 1.29,
                "DJ_tc_ms": 210.0,
                "IMTP_relPF": 39.5,
                "SJ_Z": -0.20,
                "CMJ_Z": 0.30,
                "DJ_Z": 0.10,
                "DJ_RSI_Z": 0.45,
                "DJtc_Z": 0.80,
                "IMTP_Z": 0.60,
                "EUR": 1.129,
                "EUR_Z": 0.25,
                "DRI": 1.29,
                "DRI_Z": 0.35,
            }
        )

        dashboard_payload = build_dashboard_neuromuscular_payload(row)
        pdf_payload = _build_pdf_neuromuscular_profile_payload(row)

        self.assertEqual(
            dashboard_payload["metrics"]["DJ_tc_ms"]["z_score"],
            pdf_payload["metrics"]["DJ_tc_ms"]["z_score"],
        )
        self.assertEqual(
            dashboard_payload["metrics"]["IMTP_relPF"]["z_score"],
            pdf_payload["metrics"]["IMTP_relPF"]["z_score"],
        )

    def test_radar_and_composite_survive_legacy_alias_only_zscores(self):
        row = pd.Series(
            {
                "Athlete": "Atleta Legacy",
                "Date": "2026-05-01",
                "SJ_cm": 31.0,
                "CMJ_cm": 35.0,
                "DJ_cm": 25.0,
                "DJ_tc_ms": 210.0,
                "DJ_RSI": 1.29,
                "IMTP_relPF": 39.5,
                "SJ_Z": -0.20,
                "CMJ_Z": 0.30,
                "DJ_Z": 0.10,
                "DJ_RSI_Z": 0.45,
                "DJtc_Z": 0.80,
                "IMTP_Z": 0.60,
                "EUR": 1.129,
                "EUR_Z": 0.25,
                "DRI": 1.29,
                "DRI_Z": 0.35,
            }
        )

        metric_rows = build_composite_profile_metric_rows(row)
        metric_table = build_composite_profile_metric_table(row).set_index("Variable")
        radar = chart_radar(row, "Atleta Legacy", None, theme=_chart_theme())

        self.assertEqual(metric_table.loc["Tiempo de contacto", "Z-score"], 0.80)
        self.assertEqual(metric_table.loc["IMTP", "Z-score"], 0.60)
        self.assertEqual(next(item for item in metric_rows if item["Variable"] == "DJ")["Z-score"], 0.10)
        self.assertIn("Tiempo de contacto", list(radar.data[-1].theta))

    def test_radar_and_composite_survive_canonical_only_zscores(self):
        row = _synthetic_profile_row(DJ_height_Z=0.10, TC_inv_Z=0.80, IMTP_relPF_Z=0.60)

        metric_table = build_composite_profile_metric_table(row).set_index("Variable")
        radar = chart_radar(row, "Atleta Canonico", None, theme=_chart_theme())

        self.assertEqual(metric_table.loc["Tiempo de contacto", "Z-score"], 0.80)
        self.assertEqual(metric_table.loc["IMTP", "Z-score"], 0.60)
        self.assertIn("DJ height", list(radar.data[-1].theta))

    def test_all_pattern_payloads_keep_consistent_structured_keys(self):
        for pattern_code in ("A", "B", "C", "D", "E"):
            payload = PATTERN_LIBRARY[pattern_code]
            with self.subTest(pattern=pattern_code):
                for key in NEUROMUSCULAR_PATTERN_FIELDS:
                    self.assertIn(key, payload)
                    self.assertTrue(payload[key])

    def test_pattern_e_keeps_phys_bio_and_train(self):
        payload = PATTERN_LIBRARY["E"]

        self.assertTrue(payload["phys"])
        self.assertTrue(payload["bio"])
        self.assertTrue(payload["train"])

        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(EUR=0.95, CMJ_cm=29.0, SJ_cm=31.0)
        )
        self.assertEqual(result["profile_code"], "E")
        self.assertTrue(result["phys"])
        self.assertTrue(result["bio"])
        self.assertTrue(result["train"])

    def test_neuromuscular_profile_result_adds_missing_imtp_and_missing_dj_flags(self):
        result = build_neuromuscular_profile_result(
            pd.Series({"SJ_cm": 30.0, "CMJ_cm": 32.0, "EUR": 1.067})
        )

        self.assertIn("missing_imtp", result["flags"])
        self.assertIn("missing_dj", result["flags"])
        self.assertEqual(result["confidence"], "low")

    def test_neuromuscular_profile_result_detects_pattern_a(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(SJ_Z=0.80, DJ_RSI_Z=-0.80)
        )

        self.assertEqual(result["profile_code"], "A")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("SJ_Z alto", result["evidence"])
        self.assertIn("DJ_RSI_Z bajo", result["evidence"])

    def test_neuromuscular_profile_result_detects_pattern_b(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(SJ_Z=-0.80, DJ_RSI_Z=0.80)
        )

        self.assertEqual(result["profile_code"], "B")
        self.assertEqual(result["confidence"], "high")

    def test_neuromuscular_profile_result_detects_pattern_c(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(IMTP_relPF_Z=-0.80, CMJ_Z=0.00)
        )

        self.assertEqual(result["profile_code"], "C")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("IMTP_relPF_Z bajo", result["evidence"])

    def test_neuromuscular_profile_result_detects_pattern_d(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                SJ_Z=-0.80,
                CMJ_Z=-0.70,
                DJ_height_Z=-0.90,
                DJ_RSI_Z=-0.85,
                TC_inv_Z=-0.65,
                IMTP_relPF_Z=-0.75,
                EUR=1.02,
            )
        )

        self.assertEqual(result["profile_code"], "D")
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(any("todos los z-scores renderizables" in item for item in result["evidence"]))

    def test_pattern_d_with_partial_battery_requires_explicit_caution(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                SJ_Z=-0.80,
                CMJ_Z=-0.70,
                DJ_cm=None,
                DJ_RSI=None,
                DJ_tc_ms=None,
                DJ_height_Z=None,
                DJ_RSI_Z=None,
                TC_inv_Z=None,
                IMTP_relPF=None,
                IMTP_N=None,
                IMTP_relPF_Z=None,
            )
        )

        self.assertEqual(result["profile_code"], "D")
        self.assertNotEqual(result["confidence"], "high")
        self.assertTrue({"missing_imtp", "missing_dj"}.issubset(set(result["flags"])))
        self.assertTrue(
            any(token in _combined_neuromuscular_text(result) for token in ("variables disponibles", "datos disponibles", "bateria parcial", "interpretacion limitada")),
            result,
        )

    def test_neuromuscular_profile_result_detects_pattern_e(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                EUR=0.95,
                CMJ_cm=29.0,
                SJ_cm=31.0,
                SJ_Z=0.10,
                DJ_RSI_Z=0.10,
                IMTP_relPF_Z=0.20,
            )
        )

        self.assertEqual(result["profile_code"], "E")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("cmj_lower_than_sj", result["flags"])
        self.assertIn("EUR bajo", result["evidence"])

    def test_pattern_a_without_imtp_avoids_force_ceiling_claims(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                SJ_Z=0.80,
                DJ_RSI_Z=-0.80,
                IMTP_relPF=None,
                IMTP_N=None,
                IMTP_relPF_Z=None,
            )
        )

        self.assertEqual(result["profile_code"], "A")
        combined = _combined_neuromuscular_text(result)
        for forbidden in ("techo de fuerza", "fuerza maxima", "fuerza máxima", "isometrica", "isométrica"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_pattern_b_without_imtp_avoids_force_limit_claims(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                SJ_Z=-0.80,
                DJ_RSI_Z=0.80,
                IMTP_relPF=None,
                IMTP_N=None,
                IMTP_relPF_Z=None,
            )
        )

        self.assertEqual(result["profile_code"], "B")
        combined = _combined_neuromuscular_text(result)
        for forbidden in ("techo de fuerza", "fuerza maxima limitada", "fuerza máxima limitada", "techo de fuerza bajo"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_pattern_c_without_dsi_does_not_project_dsi_conclusions(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                IMTP_relPF_Z=-0.80,
                CMJ_Z=0.00,
                DSI=None,
            )
        )

        self.assertEqual(result["profile_code"], "C")
        combined = _combined_neuromuscular_text(result)
        for forbidden in ("dsi probablemente elevado", "dsi elevado", "probablemente elevado"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)

    def test_composite_snapshot_requires_lower_confidence_or_visible_caution(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                Profile_Composed=True,
                Date=None,
                SJ_Z=0.80,
                DJ_RSI_Z=-0.80,
                SJ_cm__source_date="01/05/2026",
                CMJ_cm__source_date="15/05/2026",
                DJ_cm__source_date="22/05/2026",
                DJ_RSI__source_date="22/05/2026",
                DJ_tc_ms__source_date="22/05/2026",
                IMTP_relPF__source_date="10/04/2026",
                EUR__source_date="15/05/2026",
            )
        )

        self.assertEqual(result["profile_source"], "composite_snapshot")
        self.assertTrue(result["profile_source_is_composite"])
        self.assertTrue(result["profile_source_note"])
        self.assertNotEqual(result["confidence"], "high")

    def test_pattern_match_near_threshold_requires_caution(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                SJ_Z=0.51,
                DJ_RSI_Z=-0.51,
            )
        )

        self.assertEqual(result["profile_code"], "A")
        self.assertNotEqual(result["confidence"], "high")
        self.assertTrue(
            any(flag in result["flags"] for flag in ("weak_pattern_evidence", "near_threshold", "insufficient_pattern_evidence"))
            or any(token in _combined_neuromuscular_text(result) for token in ("cerca del umbral", "evidencia debil", "interpretacion limitada")),
            result,
        )

    def test_jump_flag_rows_keep_contextual_language_for_eur_dsi_and_mrsi(self):
        green_flags = build_jump_flag_rows(
            _synthetic_profile_row(
                EUR=1.12,
                DSI=1.02,
                mRSI=0.72,
                TTT_s=0.55,
            )
        )
        red_flags = build_jump_flag_rows(
            _synthetic_profile_row(
                EUR=0.95,
                DSI=0.70,
                mRSI=0.30,
                TTT_s=0.55,
            )
        )

        green_text = " ".join(item["text"] for item in green_flags).lower()
        red_text = " ".join(item["text"] for item in red_flags).lower()

        for forbidden_text, source_text in (
            ("ssc eficiente", green_text),
            ("fuerza explosiva", green_text),
            ("ssc deficiente", red_text),
            (" bueno ", f" {green_text} {red_text} "),
            (" malo ", f" {green_text} {red_text} "),
        ):
            with self.subTest(forbidden_text=forbidden_text):
                self.assertNotIn(forbidden_text, source_text)

    def test_pattern_e_combined_with_another_pattern_preserves_caution(self):
        result = build_neuromuscular_profile_result(
            _synthetic_profile_row(
                EUR=0.95,
                CMJ_cm=29.0,
                SJ_cm=31.0,
                SJ_Z=0.80,
                DJ_RSI_Z=-0.80,
            )
        )

        self.assertIn("E", result["profile_code"].split("+"))
        self.assertIn("cmj_lower_than_sj", result["flags"])
        self.assertIn("EUR bajo", result["evidence"])
        self.assertIn("cmj por debajo de sj", _combined_neuromuscular_text(result))

    def test_neuromuscular_profile_result_keeps_legacy_eur_profile_separate_from_main_profile(self):
        row = _synthetic_profile_row(
            EUR=1.12,
            SJ_Z=0.80,
            DJ_RSI_Z=-0.80,
            NM_Profile="Reactivo",
            EUR_Profile="Reactivo",
        )

        result = build_neuromuscular_profile_result(row)

        self.assertEqual(result["profile_code"], "A")
        self.assertIn("Fuerza/propulsion", result["profile_label"])
        self.assertEqual(result["eur_profile"], "Reactivo")
        self.assertEqual(result["nm_profile_legacy"], "Reactivo")

    def test_dashboard_payload_uses_structured_profile_not_legacy_nm_profile(self):
        row = _synthetic_profile_row(
            EUR=1.12,
            SJ_Z=0.80,
            DJ_RSI_Z=-0.80,
            NM_Profile="Reactivo",
            EUR_Profile="Reactivo",
        )

        payload = build_dashboard_neuromuscular_payload(row)

        self.assertEqual(payload["profile_code"], "A")
        self.assertEqual(payload["profile_metric_value"], "Patron A")
        self.assertEqual(payload["eur_profile"], "Reactivo")
        self.assertEqual(payload["nm_profile_legacy"], "Reactivo")
        self.assertNotEqual(payload["profile_metric_value"], payload["nm_profile_legacy"])

    def test_classify_neuromuscular_quadrant_uses_shared_neutral_band(self):
        cases = [
            ((0.10, 0.10), ("mid", "mid", "mid_mid")),
            ((0.50, 0.50), ("high", "high", "high_high")),
            ((-0.50, 0.50), ("low", "high", "low_high")),
            ((0.50, -0.50), ("high", "low", "high_low")),
            ((-0.50, -0.50), ("low", "low", "low_low")),
        ]

        for (x_value, y_value), expected in cases:
            with self.subTest(x_value=x_value, y_value=y_value):
                result = classify_neuromuscular_quadrant(x_value, y_value)
                self.assertEqual((result["x_zone"], result["y_zone"], result["quadrant_code"]), expected)
                self.assertEqual(result["neutral_band"], 0.35)

    def test_classify_neuromuscular_quadrant_handles_missing_values(self):
        result = classify_neuromuscular_quadrant(None, 0.10)

        self.assertEqual(result["quadrant_code"], "missing")
        self.assertEqual(result["x_zone"], "missing")
        self.assertEqual(result["y_zone"], "mid")

    def test_dashboard_quadrant_chart_uses_transition_band_for_mid_values(self):
        jump_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-05-01", "SJ_Z": 0.10, "DJ_RSI_Z": 0.10, "DJ_RSI": 1.40},
                {"Athlete": "Bruno Rey", "Date": "2026-05-01", "SJ_Z": 0.20, "DJ_RSI_Z": 0.15, "DJ_RSI": 1.35},
            ]
        )

        figure = chart_quadrant_rsi_sj(jump_df, theme=_chart_theme())
        trace_names = {str(trace.name) for trace in figure.data}

        self.assertIn("Zona media / transicion", trace_names)

if __name__ == "__main__":
    unittest.main()
