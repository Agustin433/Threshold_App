"""PR E: reporte de atleta con contenido visual (dashboard + PDF).

Casos reales (valores de `tests/test_individual_report.py`): Tomas con 2
evaluaciones, Ignacio con 4, Giffon con 1.
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from charts.athlete_charts import chart_athlete_evolution, chart_group_position
from modules import athlete_report as ar
from modules import report_generator as rg
from modules.app_clock import frozen_app_now
from modules.jump_analysis import _prepare_jump_df, build_composite_profile_snapshot
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_STRAPS
from modules.reference_engine import z_interval
from tests.test_individual_report import GIFFON, IGNACIO, NOW, TOMAS, _pdf_state

THEME = rg._build_report_chart_theme()


def _history(rows: list[dict[str, object]], profiles: pd.DataFrame | None = None) -> pd.DataFrame:
    base = {"Source": "platform", "BW_kg": 80.0}
    return _prepare_jump_df(pd.DataFrame([{**base, **row} for row in rows]), profile_df=profiles)


def _flight_ms(height_cm: float) -> float:
    return 1000.0 * (8 * height_cm / 100.0 / 9.81) ** 0.5


def _team_with(athlete_rows: list[dict[str, object]], athlete: str) -> tuple[list[dict], pd.DataFrame]:
    """10 atletas de Rugby recreativo (Valkyria) + el atleta evaluado."""
    rows: list[dict[str, object]] = []
    profiles = [{"Athlete": athlete, "Sexo": "Masculino", "Deporte": "Rugby", "Nivel": "Recreativo"}]
    for index in range(10):
        name = f"V {index:02d}"
        cmj = 32.0 + index
        rows.append(
            {
                "Athlete": name, "Date": "2026-06-10", "Device": ERA_VALKYRIA_STRAPS, "Source": "platform",
                "BW_kg": 80.0, "CMJ_cm": cmj, "CMJ_flight_ms": _flight_ms(cmj),
                "DJ_cm": 24.0 + index, "DJ_tc_ms": 230.0 - 2 * index, "DJ_drop_height_cm": 30.0,
            }
        )
        profiles.append({"Athlete": name, "Sexo": "Masculino", "Deporte": "Rugby", "Nivel": "Recreativo"})
    return rows + [{"Source": "platform", "BW_kg": 80.0, **row} for row in athlete_rows], pd.DataFrame(profiles)


# ── 1. Tu evolucion ───────────────────────────────────────────────────────
class EvolutionTests(unittest.TestCase):
    def test_tomas_two_evaluations_flight_cmj_only(self):
        series = ar.evolution_series(_history(TOMAS))
        self.assertEqual([item["variable"] for item in series], ["CMJ_ft_cm"])
        cmj = series[0]
        self.assertEqual([round(v, 1) for v in cmj["values"]], [36.7, 44.0])
        self.assertEqual([f"{d:%d/%m/%Y}" for d in cmj["dates"]], ["13/11/2025", "21/10/2026"])
        # Banda = primera toma +/- max(TE, SWC); con 2 tomas gana el TE del instrumento (3%).
        low, high = cmj["band"]
        self.assertAlmostEqual((high - low) / 2, cmj["values"][0] * 0.03, places=3)
        self.assertLess(low, cmj["values"][0])
        self.assertGreater(high, cmj["values"][0])

    def test_tomas_imtp_across_eras_is_not_drawn(self):
        # 13/11/2025 (Valkyria sin straps) y 21/10/2026 (Involution): no comparables.
        self.assertNotIn("IMTP_relPF", [item["variable"] for item in ar.evolution_series(_history(TOMAS))])

    def test_imtp_drawn_with_two_takes_in_the_same_era(self):
        rows = [
            {"Athlete": "A", "Date": "2026-10-02", "Device": ERA_INVOLUTION_STRAPS, "IMTP_N": 3200.0},
            {"Athlete": "A", "Date": "2026-10-30", "Device": ERA_INVOLUTION_STRAPS, "IMTP_N": 3350.0},
        ]
        series = {item["variable"]: item for item in ar.evolution_series(_history(rows))}
        self.assertIn("IMTP_relPF", series)
        self.assertEqual(series["IMTP_relPF"]["era"], ERA_INVOLUTION_STRAPS)
        self.assertEqual(len(series["IMTP_relPF"]["values"]), 2)

    def test_ignacio_four_evaluations(self):
        series = ar.evolution_series(_history(IGNACIO))
        cmj = next(item for item in series if item["variable"] == "CMJ_ft_cm")
        self.assertEqual(len(cmj["values"]), 4)
        self.assertEqual([round(v, 1) for v in cmj["values"]][-2:], [39.8, 46.2])
        self.assertIn("N=4", str(cmj["threshold_label"]))

    def test_giffon_single_evaluation_is_not_drawn(self):
        self.assertEqual(ar.evolution_series(_history(GIFFON)), [])
        self.assertIsNone(chart_athlete_evolution([], theme=THEME))

    def test_chart_has_value_and_date_per_point_and_band(self):
        series = ar.evolution_series(_history(IGNACIO))
        figure = chart_athlete_evolution(series, theme=THEME, mode="print")
        trace = figure.data[0]
        self.assertEqual(list(trace.x), ["04/11/25", "17/12/25", "20/05/26", "08/10/26"])
        self.assertEqual(list(trace.text)[-1], "46.2")
        self.assertEqual(len(figure.layout.shapes), len(series))  # una banda por prueba


# ── 2. Tu posicion en el grupo ────────────────────────────────────────────
class GroupPositionTests(unittest.TestCase):
    def _ignacio_row(self) -> pd.Series:
        rows, profiles = _team_with([{**row, "DJ_cm": 38.0, "DJ_tc_ms": 190.0, "DJ_drop_height_cm": 30.0} for row in IGNACIO], "Ignacio De La Vega")
        prepared = _prepare_jump_df(pd.DataFrame(rows), profile_df=profiles)
        snapshot, _ = build_composite_profile_snapshot(prepared[prepared["Athlete"] == "Ignacio De La Vega"])
        return snapshot

    def test_percentile_and_band_from_z(self):
        row = self._ignacio_row()
        position = ar.group_position(row)
        bars = {bar["label"]: bar for bar in position["bars"]}
        self.assertIn("CMJ (vuelo)", bars)
        cmj = bars["CMJ (vuelo)"]
        z = float(row["CMJ_ft_Z"])
        self.assertAlmostEqual(cmj["percentile"], round(50 * (1 + math.erf(z / math.sqrt(2))), 1))
        low, high = z_interval(z, cmj["n"])
        self.assertAlmostEqual(cmj["band"][0], round(50 * (1 + math.erf(low / math.sqrt(2))), 1))
        self.assertAlmostEqual(cmj["band"][1], round(50 * (1 + math.erf(high / math.sqrt(2))), 1))
        self.assertLessEqual(cmj["band"][0], cmj["percentile"])
        self.assertGreaterEqual(cmj["band"][1], cmj["percentile"])

    def test_subtitle(self):
        position = ar.group_position(self._ignacio_row())
        self.assertRegex(
            position["subtitle"],
            r"^Comparado con \d+(–\d+)? atletas de Threshold \(mismo deporte, nivel y sexo\)\. No es una norma de rendimiento\.$",
        )

    def test_giffon_without_profile_has_no_position(self):
        snapshot, _ = build_composite_profile_snapshot(_history(GIFFON))
        self.assertIsNone(ar.group_position(snapshot))
        self.assertIsNone(chart_group_position(None, theme=THEME))

    def test_percentile_only_cohort_has_no_band(self):
        row = pd.Series(
            {"DJ_RSI_Z": None, "DJ_RSI_Z_source": "cohort_rank", "DJ_RSI_Z_percentile": 66.7, "DJ_RSI_Z_cohort_n": 6}
        )
        position = ar.group_position(row)
        self.assertEqual(position["bars"][0]["percentile"], 66.7)
        self.assertIsNone(position["bars"][0]["band"])

    def test_chart_shows_no_z(self):
        figure = chart_group_position(ar.group_position(self._ignacio_row()), theme=THEME, mode="print")
        self.assertEqual(tuple(figure.layout.xaxis.range), (0, 104))
        texts = [str(t) for trace in figure.data for t in (trace.text or [])]
        self.assertTrue(texts)
        self.assertTrue(all(0 <= float(t) <= 100 for t in texts))


# ── 3. Tus numeros hoy ────────────────────────────────────────────────────
class TilesTests(unittest.TestCase):
    def test_giffon_imtp_is_previous_protocol(self):
        tiles = {tile["variable"]: tile for tile in ar.today_tiles(_history(GIFFON))}
        self.assertEqual(set(tiles), {"CMJ_ft_cm", "DJ_RSI", "IMTP_relPF"})
        self.assertTrue(tiles["IMTP_relPF"]["value"].endswith("N/kg"))
        self.assertIn(ar.PREVIOUS_PROTOCOL_LABEL, tiles["IMTP_relPF"]["note"])

    def test_tomas_imtp_is_current_era(self):
        tiles = {tile["variable"]: tile for tile in ar.today_tiles(_history(TOMAS))}
        self.assertEqual(tiles["CMJ_ft_cm"]["value"], "44.0 cm")
        self.assertIn("Involution", tiles["IMTP_relPF"]["note"])
        self.assertNotIn(ar.PREVIOUS_PROTOCOL_LABEL, tiles["IMTP_relPF"]["note"])

    def test_client_labels_have_no_jargon(self):
        for tile in ar.today_tiles(_history(TOMAS), "cliente"):
            self.assertNotIn("IMTP", tile["label"])
            self.assertNotIn("RSI", tile["label"])


# ── 4 y 6. Compaginacion y PDF ────────────────────────────────────────────
def _pdf(state: dict[str, object], athlete: str, audience: str = "atleta") -> list[str]:
    with frozen_app_now(NOW):
        pdf = rg.generate_visual_report_pdf(state, athlete, audience)
    return [page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages]


class LayoutTests(unittest.TestCase):
    def test_rule_helper(self):
        self.assertTrue(rg._layout_is_acceptable([0.9, 0.2]))
        self.assertFalse(rg._layout_is_acceptable([0.3, 0.9]))

    def test_short_report_is_one_page(self):
        pages = _pdf(_pdf_state(GIFFON), "Agustin Giffon")
        self.assertEqual(len(pages), 1)
        self.assertIn("Diccionario", pages[0])

    def test_no_underfilled_page_except_the_last(self):
        for rows, athlete in ((TOMAS, "Tomas De La Vega"), (IGNACIO, "Ignacio De La Vega"), (GIFFON, "Agustin Giffon")):
            with self.subTest(athlete=athlete):
                pages = _pdf(_pdf_state(rows, with_wellness=True), athlete)
                fill = rg.LAST_INDIVIDUAL_LAYOUT["page_fill"]
                self.assertEqual(len(fill), len(pages))
                self.assertTrue(all(value >= rg.INDIVIDUAL_MIN_PAGE_FILL for value in fill[:-1]), fill)

    def test_tomas_pdf_has_evolution_and_tiles_but_no_imtp_newton_tile(self):
        joined = " ".join(_pdf(_pdf_state(TOMAS), "Tomas De La Vega"))
        self.assertIn("Tu evolución", joined)
        self.assertIn("Tus números hoy", joined)
        self.assertIn("N/kg", joined)
        self.assertNotIn("Lo que más se destaca", joined)
        self.assertNotIn("3638 N", joined)

    def test_position_section_in_pdf_with_cohort_and_no_z(self):
        rows, profiles = _team_with(IGNACIO, "Ignacio De La Vega")
        state = _pdf_state([r for r in rows if r["Athlete"] == "Ignacio De La Vega"])
        state["jump_df"] = pd.DataFrame(rows)
        state["athlete_profile_df"] = profiles
        joined = " ".join(_pdf(state, "Ignacio De La Vega"))
        self.assertIn("Tu posición en el grupo", joined)
        self.assertIn("No es una norma de rendimiento", joined)
        self.assertNotIn("z-score", joined.lower())
        self.assertNotIn("z =", joined.lower())

    def test_giffon_without_profile_has_no_position_section(self):
        joined = " ".join(_pdf(_pdf_state(GIFFON), "Agustin Giffon"))
        self.assertNotIn("Tu posición en el grupo", joined)
        self.assertNotIn("Tu evolución", joined)


# ── 5. Dashboard del atleta ───────────────────────────────────────────────
class DashboardVisualBlocksTest(unittest.TestCase):
    """El dashboard muestra evolucion y numeros de hoy con las mismas funciones que el PDF."""

    def test_ignacio_profile_view(self):
        import importlib
        import os
        import shutil
        import uuid
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "app.py"
        tmp_root = Path(__file__).resolve().parent / f".tmp_visual_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True)
        original = os.environ.get("THRESHOLD_STORE_DIR")
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        try:
            pd.DataFrame([{"Source": "platform", "BW_kg": 80.0, **row} for row in IGNACIO]).to_csv(
                store_dir / "evaluations_history.csv", index=False
            )
            import local_store

            importlib.reload(local_store)
            at = AppTest.from_file(str(app_path), default_timeout=120)
            at.run()
            self.assertFalse(at.exception, at.exception)
            nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
            nav.set_value("Profile").run()
            self.assertFalse(at.exception, at.exception)
            markdown = " ".join(str(item.value) for item in at.markdown)
            self.assertIn("Tu evolución", markdown)
            self.assertIn("Tus números hoy", markdown)
            metric_values = [str(metric.value) for metric in at.metric]
            self.assertIn("46.2 cm", metric_values)
            captions = " ".join(str(item.value) for item in at.caption)
            self.assertIn("Banda gris", captions)
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
