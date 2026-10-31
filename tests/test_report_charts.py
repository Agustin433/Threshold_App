"""Graficos compartidos dashboard/PDF (charts.report_charts).

- Una funcion por grafico; el dashboard y el PDF llaman a la misma.
- Modo "print": tamano fijo de ancho completo, fuente >= 11 pt impresa,
  leyenda abajo en su propio margen, sin hover.
- Carga: la cronica se corta en semanas sin datos (no se interpola); ACWR
  solo EWMA, con "no calculable".
- Wellness: banda individual media +/- 1 DE de los 28 dias previos (sin banda
  con < 10 registros); sueno/estres/dolor en paneles propios.
- Cada reporte embebe exactamente sus graficos (verificado sobre el PDF).
"""

from __future__ import annotations

import re
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from pypdf import PdfReader

from charts import report_charts as rc
from modules import report_generator
from modules.app_clock import frozen_app_now
from tests.test_reports_yellow_coverage import ATHLETE, NOW, full_charts_state
from tests.test_weekly_acwr_context import _chart_theme

THEME = _chart_theme()


def _weekly(weeks: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Athlete": "Ana",
            "week_start": pd.to_datetime(weeks),
            "weekly_sRPE": values,
            "weekly_sRPE_model": values,
            "sessions_done": [4 if value else 0 for value in values],
            "sessions_missing": [0] * len(values),
        }
    )


def _acwr_daily(start: str, days: int, status: str = "ok") -> pd.DataFrame:
    dates = pd.date_range(start, periods=days)
    return pd.DataFrame(
        {
            "Date": dates,
            "EWMA_Cronica": np.linspace(100, 120, days),
            "ACWR_EWMA": np.linspace(0.9, 1.1, days),
            "ACWR_Estado": status,
        }
    )


class PrintModeTest(unittest.TestCase):
    def test_print_font_is_at_least_11pt_once_printed(self):
        self.assertGreaterEqual(rc.PRINT_FONT_PX * rc.PT_PER_PX, 11.0)

    def test_print_layout(self):
        figure = rc.load_chart(
            _weekly(["2026-09-07", "2026-09-14", "2026-09-21"], [800, 900, 850]),
            _acwr_daily("2026-09-07", 21), "Ana", theme=THEME, mode="print",
        )
        layout = figure.layout
        self.assertEqual(layout.width, rc.PRINT_CANVAS_WIDTH_PX)
        self.assertEqual(layout.height, rc.print_height_px(100.0))
        self.assertGreaterEqual(layout.font.size, rc.PRINT_FONT_PX)
        self.assertIs(layout.hovermode, False)
        self.assertEqual(layout.legend.orientation, "h")
        self.assertEqual(layout.legend.yref, "container")
        self.assertEqual(layout.legend.yanchor, "bottom")
        # La leyenda vive en el margen inferior (no encima de los ejes).
        self.assertGreaterEqual(layout.margin.b, 2 * rc.PRINT_FONT_PX)
        for axis in (layout.xaxis, layout.yaxis, layout.yaxis2):
            self.assertGreaterEqual(axis.tickfont.size, rc.PRINT_FONT_PX)
        self.assertTrue(all(trace.hoverinfo == "skip" for trace in figure.data))

    def test_screen_mode_keeps_hover(self):
        figure = rc.load_chart(_weekly(["2026-09-07", "2026-09-14"], [800, 900]), None, "Ana", theme=THEME)
        self.assertIsNone(figure.layout.width)
        self.assertNotEqual(figure.layout.hovermode, False)


class LoadChartTest(unittest.TestCase):
    def test_chronic_line_breaks_in_weeks_without_data(self):
        weekly = _weekly(["2026-09-07", "2026-09-14", "2026-09-28"], [800, 900, 850])  # sin 21/09
        frame = rc.weekly_load_frame(weekly, _acwr_daily("2026-09-07", 28))
        gap = frame[frame["week_start"] == pd.Timestamp("2026-09-21")].iloc[0]
        self.assertFalse(bool(gap["has_data"]))
        self.assertTrue(np.isnan(gap["chronic_weekly"]))
        self.assertTrue(np.isnan(gap["acwr_ewma"]))
        figure = rc.load_chart(weekly, _acwr_daily("2026-09-07", 28), "Ana", theme=THEME)
        chronic = next(trace for trace in figure.data if trace.name == rc.CHRONIC_LABEL)
        self.assertIs(chronic.connectgaps, False)

    def test_chronic_not_drawn_while_history_is_short(self):
        frame = rc.weekly_load_frame(
            _weekly(["2026-09-07", "2026-09-14"], [800, 900]), _acwr_daily("2026-09-07", 14, status="historial_insuficiente")
        )
        self.assertTrue(frame["chronic_weekly"].isna().all())

    def test_acwr_is_ewma_only_and_marks_not_calculable(self):
        acwr = _acwr_daily("2026-09-07", 14)
        acwr.loc[acwr["Date"] >= "2026-09-14", "ACWR_Estado"] = "registro_incompleto"
        figure = rc.load_chart(_weekly(["2026-09-07", "2026-09-14"], [800, 300]), acwr, "Ana", theme=THEME)
        names = [trace.name for trace in figure.data]
        self.assertIn(rc.ACWR_EWMA_LABEL, names)
        self.assertIn(rc.NOT_CALCULABLE_LABEL, names)
        self.assertFalse(any("rolling" in str(name).lower() for name in names))

    def test_athlete_variant_has_no_acwr(self):
        figure = rc.load_chart(_weekly(["2026-09-07", "2026-09-14"], [800, 900]), _acwr_daily("2026-09-07", 14), "Ana",
                               theme=THEME, show_acwr=False)
        names = [trace.name for trace in figure.data]
        self.assertNotIn(rc.ACWR_EWMA_LABEL, names)
        self.assertIn(rc.CHRONIC_LABEL, names)

    def test_partial_week_shows_estimated_hatched_and_n_of_N(self):
        weekly = _weekly(["2026-09-07", "2026-09-14"], [800, 270])
        weekly.loc[1, ["weekly_sRPE_model", "sessions_missing"]] = [1000, 3]
        figure = rc.load_chart(weekly, None, "Ana", theme=THEME, show_acwr=False)
        estimated = next(trace for trace in figure.data if trace.name == rc.ESTIMATED_LABEL)
        self.assertEqual(estimated.marker.pattern.shape, "/")
        self.assertIn("1/4", list(estimated.text))

    def test_sessions_per_week_counts_sessions_not_ua(self):
        ledger = pd.DatetimeIndex(pd.to_datetime(["2026-09-07", "2026-09-08", "2026-09-15"]))
        figure = rc.sessions_per_week_chart(ledger, [pd.Timestamp("2026-09-10")], "Ana", theme=THEME,
                                            reference_date="2026-09-16")
        bar = figure.data[0]
        self.assertEqual(list(bar.y), [3, 1])
        self.assertNotIn("UA", figure.layout.yaxis.title.text or "")


class WellnessChartsTest(unittest.TestCase):
    def _wellness(self, days: int) -> pd.DataFrame:
        dates = pd.date_range("2026-09-01", periods=days)
        return pd.DataFrame({"Date": dates, "Wellness_Score": np.linspace(15, 25, days), "Sueno_hs": 7.0, "Estres": 3, "Dolor": 2})

    def test_band_needs_ten_previous_records(self):
        band = rc.wellness_band(self._wellness(12)["Date"], self._wellness(12)["Wellness_Score"])
        self.assertTrue(band["band_mean"].iloc[:10].isna().all())
        self.assertFalse(np.isnan(band["band_mean"].iloc[10]))
        expected = self._wellness(12)["Wellness_Score"].iloc[:10]
        self.assertAlmostEqual(band["band_mean"].iloc[10], expected.mean())
        self.assertAlmostEqual(band["band_sd"].iloc[10], expected.std(ddof=1))

    def test_band_uses_only_previous_28_days(self):
        frame = self._wellness(40)
        band = rc.wellness_band(frame["Date"], frame["Wellness_Score"])
        last = band.iloc[-1]
        prior = frame[(frame["Date"] < last["Date"]) & (frame["Date"] >= last["Date"] - pd.Timedelta(days=28))]
        self.assertAlmostEqual(last["band_mean"], prior["Wellness_Score"].mean())

    def test_score_chart_without_band_when_few_records(self):
        names = [trace.name for trace in rc.wellness_score_chart(self._wellness(8), "Ana", theme=THEME).data]
        self.assertNotIn(rc.BAND_LABEL, names)
        names = [trace.name for trace in rc.wellness_score_chart(self._wellness(30), "Ana", theme=THEME).data]
        self.assertIn(rc.BAND_LABEL, names)

    def test_components_have_their_own_axes_and_never_the_score(self):
        figure = rc.wellness_components_chart(self._wellness(14), "Ana", theme=THEME)
        axes = {trace.yaxis for trace in figure.data}
        self.assertEqual(len(axes), 3)
        self.assertFalse(any("score" in str(trace.name).lower() for trace in figure.data))
        self.assertEqual(list(figure.layout.yaxis2.range), [0, 10.0])


class DashboardUsesSameFunctionsTest(unittest.TestCase):
    def test_app_calls_shared_chart_functions(self):
        source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        self.assertIn("from charts.report_charts import", source)
        for name in ("load_chart(", "wellness_score_chart(", "wellness_components_chart("):
            self.assertIn(name, source)
        self.assertNotIn("chart_weekly_acwr_context", source)
        self.assertNotIn("ACWR rolling", source)


class ReportsEmbedExpectedChartsTest(unittest.TestCase):
    """Cada PDF embebe exactamente sus graficos (kaleido simulado con un PNG)."""

    @staticmethod
    def _fake_png(width: int, height: int) -> bytes:
        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
        return buffer.getvalue()

    def test_each_report_embeds_its_charts(self):
        requested: dict[str, list[tuple[int, int]]] = {}

        def fake_render(pio_module, figure, *, width, height, scale):
            requested.setdefault(current, []).append((width, height))
            return self._fake_png(width * scale, height * scale)

        state = full_charts_state()
        for current in ("profe", "atleta", "cliente"):
            with self.subTest(audience=current), frozen_app_now(NOW), patch.object(
                report_generator, "_plotly_figure_to_png_bytes", side_effect=fake_render
            ):
                expected = sorted(report_generator.build_report_chart_figures(state, ATHLETE, current))
                self.assertEqual(expected, sorted(report_generator.REPORT_CHART_SLUGS[current]))
                pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, current)
                widths = [int(image.image.width) for page in PdfReader(BytesIO(pdf)).pages for image in page.images]
                charts = [width for width in widths if width == rc.PRINT_CANVAS_WIDTH_PX * rc.PRINT_SCALE]
                figures = report_generator.build_report_chart_figures(state, ATHLETE, current)
                self.assertEqual(len(charts), report_generator.report_chart_image_count(figures), f"{current}: {widths}")
                self.assertTrue(all(width == rc.PRINT_CANVAS_WIDTH_PX for width, _ in requested[current]))


if __name__ == "__main__":
    unittest.main()
