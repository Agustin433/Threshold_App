"""PR G: "Como venis aguantando" (bienestar y carga en 6 semanas, atleta/cliente).

Casos reales (fechas y cantidades de los datos al 05/11/2026; puntajes
sinteticos con la misma estructura):
- Ignacio De La Vega: 42 registros, 9 en las 6 semanas y ninguno en la ultima
  semana completa -> antes no se mostraba nada; ahora grafico completo.
- Tomas De La Vega: 7 registros, 2 en la ventana al 05/11 (proximo paso) y 3
  en la ventana al 23/10 (puntos sin banda).
- Agustin Giffon: 49 registros, 15 en la ventana, con sRPE: grafico con
  barras y conserva la tabla de la ultima semana y las frases de carga.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from charts.athlete_charts import FEW_RECORDS_LEGEND, chart_tolerance
from modules import athlete_report as ar
from modules import report_generator as rg
from modules.app_clock import frozen_app_now

TODAY = pd.Timestamp("2026-11-05")
NOW = datetime(2026, 11, 5, 12, 0)
THEME = rg._build_report_chart_theme()

IGNACIO_WINDOW_DATES = ["2026-09-29", "2026-10-01", "2026-10-06", "2026-10-07", "2026-10-09",
                        "2026-10-14", "2026-10-15", "2026-10-21", "2026-10-23"]
TOMAS_DATES = ["2026-08-21", "2026-08-25", "2026-09-01", "2026-09-03", "2026-09-11", "2026-10-15", "2026-10-22"]


def _wellness(athlete: str, dates: list[str], scores: list[float] | None = None, **components) -> pd.DataFrame:
    scores = scores if scores is not None else [21.0 + (i % 3) - 1 for i in range(len(dates))]
    rows = []
    for index, (date, score) in enumerate(zip(dates, scores)):
        row = {"Athlete": athlete, "Date": date, "Wellness_Score": score, "Sueno_hs": 7.5, "Estres": 5, "Dolor": 4}
        for column, values in components.items():
            row[column] = values[index]
        rows.append(row)
    return pd.DataFrame(rows)


def _ignacio_wellness() -> pd.DataFrame:
    # 33 registros previos (2-3 por semana desde mayo) + 9 en la ventana = 42.
    prior = pd.date_range("2026-05-27", "2026-09-20", periods=33).strftime("%Y-%m-%d").tolist()
    return _wellness("Ignacio De La Vega", prior + IGNACIO_WINDOW_DATES)


def _giffon_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    prior = pd.date_range("2026-06-01", "2026-09-20", periods=34).strftime("%Y-%m-%d").tolist()
    window = pd.date_range("2026-09-25", "2026-10-30", periods=15).strftime("%Y-%m-%d").tolist()
    scores = [15.5 + (i % 3) - 1 for i in range(34)] + [16.0 + (i % 3) - 1 for i in range(15)]
    wellness = _wellness("Agustin Giffon", prior + window, scores)
    rpe = pd.DataFrame(
        [
            {"Athlete": "Agustin Giffon", "Date": day.strftime("%Y-%m-%d"), "RPE": 6, "Duration_min": 57, "sRPE": 342}
            for day in pd.date_range("2026-09-28", "2026-10-28", freq="2D")
        ]
    )
    return wellness, rpe


class ReadingRuleTests(unittest.TestCase):
    def test_ignacio_42_records_gets_full_chart(self):
        wellness = _ignacio_wellness()
        self.assertEqual(len(wellness), 42)
        # Regla vieja: 0 registros en la ultima semana completa -> nada.
        last_week = wellness[pd.to_datetime(wellness["Date"]).between("2026-10-26", "2026-11-01")]
        self.assertTrue(last_week.empty)
        reading = ar.tolerance_reading(wellness, None, "Ignacio De La Vega", today=TODAY)
        self.assertEqual(reading["mode"], ar.TOLERANCE_MODE_FULL)
        self.assertEqual(reading["n_records"], 9)
        self.assertTrue(reading["points"]["band_mean"].notna().all())
        self.assertEqual(reading["sentences"][0], ar.TOLERANCE_SENTENCES["within"])

    def test_tomas_depends_on_window(self):
        wellness = _wellness("Tomas De La Vega", TOMAS_DATES, [20, 19, 21, 18, 20, 23, 17])
        # Al 05/11: 15/10 y 22/10 -> < 3, solo proximo paso.
        self.assertIsNone(ar.tolerance_reading(wellness, None, "Tomas De La Vega", today=TODAY))
        # Al 22/10 (su ultimo dato): 11/09, 15/10 y 22/10 -> puntos sin banda.
        reading = ar.tolerance_reading(wellness, None, "Tomas De La Vega", today="2026-10-22")
        self.assertEqual(reading["mode"], ar.TOLERANCE_MODE_POINTS)
        self.assertTrue(reading["few_records"])
        self.assertTrue(reading["points"]["band_mean"].isna().all())

    def test_six_or_more_full_three_to_five_points(self):
        dates = pd.date_range("2026-10-01", periods=6, freq="5D").strftime("%Y-%m-%d").tolist()
        full = ar.tolerance_reading(_wellness("A", dates), None, "A", today=TODAY)
        self.assertEqual(full["mode"], ar.TOLERANCE_MODE_FULL)
        points = ar.tolerance_reading(_wellness("A", dates[:5]), None, "A", today=TODAY)
        self.assertEqual(points["mode"], ar.TOLERANCE_MODE_POINTS)
        self.assertIsNone(ar.tolerance_reading(_wellness("A", dates[:2]), None, "A", today=TODAY))

    def test_sentences_follow_the_data(self):
        prior = pd.date_range("2026-08-01", "2026-09-23", periods=20).strftime("%Y-%m-%d").tolist()
        window = pd.date_range("2026-09-26", "2026-11-04", periods=8).strftime("%Y-%m-%d").tolist()
        base = [22.0 + (i % 3) - 1 for i in range(20)]
        below = ar.tolerance_reading(_wellness("A", prior + window, base + [16.0] * 8), None, "A", today=TODAY)
        self.assertEqual(below["signal"], "below")
        self.assertEqual(below["sentences"][0], ar.TOLERANCE_SENTENCES["below"])
        above = ar.tolerance_reading(_wellness("A", prior + window, base + [27.0] * 8), None, "A", today=TODAY)
        self.assertEqual(above["sentences"][0], ar.TOLERANCE_SENTENCES["above"])

    def test_within_but_low_range_is_said(self):
        wellness, _ = _giffon_frames()
        reading = ar.tolerance_reading(wellness, None, "Agustin Giffon", today=TODAY)
        self.assertEqual(reading["signal"], "within")
        self.assertEqual(reading["sentences"][0], ar.TOLERANCE_WITHIN_LOW_SENTENCE)

    def test_only_the_component_that_moved_most(self):
        prior = pd.date_range("2026-08-01", "2026-09-23", periods=10).strftime("%Y-%m-%d").tolist()
        window = pd.date_range("2026-09-26", "2026-11-04", periods=6).strftime("%Y-%m-%d").tolist()
        n_prior, n_window = len(prior), len(window)
        wellness = _wellness(
            "A",
            prior + window,
            [20.0] * (n_prior + n_window),
            Sueno_hs=[7.0 + 0.2 * (i % 2) for i in range(n_prior)] + [5.5] * n_window,
            Estres=[5 + (i % 2) for i in range(n_prior)] + [6] * n_window,
            Dolor=[4 + (i % 2) for i in range(n_prior)] + [4] * n_window,
        )
        sentences = ar.tolerance_reading(wellness, None, "A", today=TODAY)["sentences"]
        highlights = [s for s in sentences if s.startswith("Lo que más se movió")]
        self.assertEqual(len(highlights), 1)
        self.assertIn("el sueño", highlights[0])
        self.assertIn("peor", highlights[0])

    def test_weekly_load_only_complete_weeks_in_window(self):
        wellness, rpe = _giffon_frames()
        reading = ar.tolerance_reading(wellness, rpe, "Agustin Giffon", today=TODAY)
        weeks = reading["weekly_load"]["week_start"]
        self.assertTrue((weeks >= reading["window_start"]).all())
        self.assertGreater(len(weeks), 0)


class ChartTests(unittest.TestCase):
    def test_with_srpe_bars_and_band(self):
        wellness, rpe = _giffon_frames()
        figure = chart_tolerance(ar.tolerance_reading(wellness, rpe, "Agustin Giffon", today=TODAY), theme=THEME, mode="print")
        types = [trace.type for trace in figure.data]
        self.assertIn("bar", types)
        self.assertTrue(any(trace.fill == "tonexty" for trace in figure.data if trace.type == "scatter"))

    def test_without_srpe_no_empty_bars(self):
        figure = chart_tolerance(ar.tolerance_reading(_ignacio_wellness(), None, "Ignacio De La Vega", today=TODAY), theme=THEME)
        self.assertNotIn("bar", [trace.type for trace in figure.data])
        self.assertIsNone(getattr(figure.layout, "yaxis2", None) and figure.layout.yaxis2.title.text)

    def test_few_records_points_without_band(self):
        wellness = _wellness("Tomas De La Vega", TOMAS_DATES, [20, 19, 21, 18, 20, 23, 17])
        figure = chart_tolerance(ar.tolerance_reading(wellness, None, "Tomas De La Vega", today="2026-10-22"), theme=THEME)
        scatters = [trace for trace in figure.data if trace.type == "scatter"]
        self.assertEqual(len(scatters), 1)
        self.assertEqual(scatters[0].mode, "markers")
        self.assertIn(FEW_RECORDS_LEGEND, scatters[0].name)

    def test_none_without_reading(self):
        self.assertIsNone(chart_tolerance(None, theme=THEME))


def _state(athlete: str, wellness: pd.DataFrame, rpe: pd.DataFrame | None = None) -> dict[str, object]:
    # Dos evaluaciones: asi "Proximos pasos" (maximo 2) no se llena con la
    # primera comparacion y el paso de bienestar se puede ver.
    return {
        "jump_df": pd.DataFrame(
            [
                {"Athlete": athlete, "Date": date, "Source": "platform", "BW_kg": 77.0, "CMJ_cm": cmj, "CMJ_flight_ms": ms}
                for date, cmj, ms in (("2026-05-22", 38.0, 547), ("2026-10-21", 44.0, 599))
            ]
        ),
        "rpe_df": rpe,
        "wellness_df": wellness,
        "completion_df": None,
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {},
        "mono_dict": {},
    }


def _pdf_text(state: dict[str, object], athlete: str, audience: str = "atleta") -> str:
    with frozen_app_now(NOW):
        pdf = rg.generate_visual_report_pdf(state, athlete, audience)
    return " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


class ReportTests(unittest.TestCase):
    def test_ignacio_pdf_shows_section_and_no_wellness_step(self):
        state = _state("Ignacio De La Vega", _ignacio_wellness())
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(state, "Ignacio De La Vega", "atleta")
        self.assertIsNone(payload["wellness"])  # la regla vieja no mostraba nada
        self.assertIsNotNone(payload["tolerance"])
        self.assertFalse(any("cuestionario de bienestar" in step for step in payload["next_steps"]))
        text = _pdf_text(state, "Ignacio De La Vega")
        self.assertIn("Cómo venís aguantando", text)
        self.assertIn("Venís dentro de tu rango habitual", text)

    def test_tomas_without_enough_records_only_next_step(self):
        state = _state("Tomas De La Vega", _wellness("Tomas De La Vega", TOMAS_DATES))
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(state, "Tomas De La Vega", "atleta")
        self.assertIsNone(payload["tolerance"])
        self.assertTrue(any("cuestionario de bienestar" in step for step in payload["next_steps"]))
        self.assertNotIn("Cómo venís aguantando", _pdf_text(state, "Tomas De La Vega"))

    def test_giffon_single_window_without_last_week_table(self):
        wellness, rpe = _giffon_frames()
        # PR H: aunque la ultima semana completa tenga >= 3 dias, la tabla de
        # esa semana ya no va en el PDF atleta (una sola ventana de 6 semanas).
        extra = _wellness("Agustin Giffon", ["2026-10-20", "2026-10-22", "2026-10-23"], [13.0, 14.0, 14.0])
        state = _state("Agustin Giffon", pd.concat([wellness, extra], ignore_index=True), rpe)
        text = _pdf_text(state, "Agustin Giffon")
        self.assertIn("Cómo venís aguantando", text)
        self.assertNotIn("Días con registro", text)
        self.assertNotIn("Carga reciente", text)

    def test_client_pdf_gets_the_section(self):
        state = _state("Ignacio De La Vega", _ignacio_wellness())
        self.assertIn("Cómo venís aguantando", _pdf_text(state, "Ignacio De La Vega", "cliente"))

    def test_band_uses_history_before_the_window(self):
        # Con solo la ventana (6 semanas) en wellness_df y la historia en
        # wellness_history_df, la banda igual se calcula.
        full = _ignacio_wellness()
        recent = full[pd.to_datetime(full["Date"]) > TODAY - pd.Timedelta(days=42)]
        state = _state("Ignacio De La Vega", recent)
        state["wellness_history_df"] = full
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(state, "Ignacio De La Vega", "atleta")
        self.assertTrue(payload["tolerance"]["points"]["band_mean"].notna().any())


class DashboardToleranceTest(unittest.TestCase):
    def test_athlete_view_shows_section(self):
        import importlib
        import os
        import shutil
        import uuid
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "app.py"
        tmp_root = Path(__file__).resolve().parent / f".tmp_tolerance_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True)
        original = os.environ.get("THRESHOLD_STORE_DIR")
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        try:
            today = pd.Timestamp.today().normalize()
            dates = [(today - pd.Timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(80, 0, -3)]
            _wellness("Ignacio De La Vega", dates).to_csv(store_dir / "wellness_history.csv", index=False)
            pd.DataFrame(
                [{"Athlete": "Ignacio De La Vega", "Date": dates[-1], "Source": "platform", "BW_kg": 80.0,
                  "CMJ_cm": 46.0, "CMJ_flight_ms": 614}]
            ).to_csv(store_dir / "evaluations_history.csv", index=False)
            import local_store

            importlib.reload(local_store)
            at = AppTest.from_file(str(app_path), default_timeout=120)
            at.run()
            self.assertFalse(at.exception, at.exception)
            nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
            nav.set_value("Profile").run()
            self.assertFalse(at.exception, at.exception)
            markdown = " ".join(str(item.value) for item in at.markdown)
            self.assertIn("Cómo venís aguantando", markdown)
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
