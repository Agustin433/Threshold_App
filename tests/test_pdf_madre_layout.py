"""PDF madre (profesional individual): ninguna imagen puede exceder la pagina.

Produccion (31/10, Streamlit Cloud): con muchas categorias de estimulo la
figura "Distribucion visual del bloque" media 1189 pt de alto dentro de una
Table de 1 celda (frame de 739 pt) -> LayoutError de reportlab, y el reporte
caia EN SILENCIO al generador legacy. Localmente no se veia porque sin kaleido
se usaba el respaldo chico. Aca se simula kaleido con un PNG del tamano real
de cada figura, que es lo que dispara el error.
"""

from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from pypdf import PdfReader

from charts.report_charts import PRINT_CANVAS_WIDTH_PX, PRINT_SCALE
from modules import report_generator
from modules.app_clock import frozen_app_now
from tests.test_reports_yellow_coverage import ATHLETE, NOW, full_charts_state

# >= 8 categorias de estimulo: 6 patrones de fuerza + pliometria, DLO,
# isometricos, core, movilidad y sprint.
MANY_CATEGORY_EXERCISES = (
    ("Back Squat", "Dominante de Rodilla"),
    ("Romanian Deadlift", "Dominante de Cadera"),
    ("Barbell Bench Press", "Empuje Horizontal"),
    ("Overhead Press", "Empuje Vertical"),
    ("Seated Row", "Traccion Horizontal"),
    ("Pull Up", "Traccion Vertical"),
    ("Box Jump", "Jump_Plyo"),
    ("Hang Clean", "DLO"),
    ("Isometric Mid-Thigh Pull", "Iso_Overcoming"),
    ("Front Plank", "Core_Plank"),
    ("Hip Mobility Flow", "Mobility MMII"),
    ("Sprint 20m", "Sprint"),
)


def many_categories_state() -> dict:
    state = full_charts_state()
    raw = state["raw_df"]
    days = sorted(pd.to_datetime(raw["Completed Date"]).unique())
    rows = [
        {
            "Athlete": ATHLETE,
            "Assigned Date": day,
            "Completed Date": day,
            "Exercise Name": name,
            "Set Number": set_number,
            "Result": 60,
            "Reps": 5,
            "Tags": tag,
        }
        for day in days
        for name, tag in MANY_CATEGORY_EXERCISES
        for set_number in (1, 2, 3)
    ]
    state["raw_df"] = pd.DataFrame(rows)
    state.pop("prepared_raw_df", None)
    return state


_RENDER_COUNT = [0]


def _real_size_png(pio_module, figure, *, width, height, scale):
    """kaleido simulado: PNG del tamano real que tendria la figura.

    Cada PNG es distinto (reportlab deduplica imagenes identicas).
    """
    from PIL import Image

    _RENDER_COUNT[0] += 1
    shade = _RENDER_COUNT[0] % 250
    buffer = BytesIO()
    Image.new("RGB", (width * scale, height * scale), (255, 255 - shade, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class MadreLayoutTest(unittest.TestCase):
    def test_many_categories_builds_madre_with_all_charts(self):
        state = many_categories_state()
        with frozen_app_now(NOW), patch.object(report_generator, "_plotly_figure_to_png_bytes", side_effect=_real_size_png):
            figures = report_generator.build_report_chart_figures(state, ATHLETE, "profe")
            self.assertEqual(sorted(figures), sorted(report_generator.REPORT_CHART_SLUGS["profe"]))
            self.assertGreaterEqual(len(figures["exposure"]), 2)  # partida por seccion
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, "profe")

        reader = PdfReader(BytesIO(pdf))
        self.assertIn("Reporte madre profesional", reader.pages[0].extract_text())
        charts = [
            image for page in reader.pages for image in page.images
            if image.image.width == PRINT_CANVAS_WIDTH_PX * PRINT_SCALE
        ]
        self.assertEqual(len(charts), report_generator.report_chart_image_count(figures))
        # Ninguna imagen supera el alto maximo (en px a escala de impresion).
        max_px = PRINT_CANVAS_WIDTH_PX * PRINT_SCALE * report_generator.PDF_CHART_MAX_HEIGHT_MM / 168.0
        self.assertTrue(all(image.image.height <= max_px + 2 for image in charts))

    def test_tall_figure_is_capped_keeping_full_width(self):
        import plotly.graph_objects as go

        figure = go.Figure(go.Bar(y=[1, 2]))
        figure.update_layout(width=PRINT_CANVAS_WIDTH_PX, height=3000)
        with patch.object(report_generator, "_plotly_figure_to_png_bytes", side_effect=_real_size_png):
            image = report_generator.render_print_chart_image(figure)
        from reportlab.lib.units import mm

        self.assertAlmostEqual(image.drawWidth, 168 * mm, places=3)
        self.assertLessEqual(image.drawHeight, report_generator.PDF_CHART_MAX_HEIGHT_MM * mm + 0.01)
        self.assertEqual(figure.layout.height, 3000)  # la figura original no se modifica


class BlockDistributionSharedAxisTest(unittest.TestCase):
    def test_all_sections_share_weekly_monday_axis_and_week_wide_bars(self):
        from charts.load_charts import WEEK_BAR_WIDTH_MS, chart_volume_by_tag_sections
        from modules.data_loader import prepare_raw_workouts_df

        prepared = prepare_raw_workouts_df(many_categories_state()["raw_df"])
        figures = chart_volume_by_tag_sections(prepared, ATHLETE, theme=report_generator._build_report_chart_theme())
        self.assertGreaterEqual(len(figures), 7)
        axes = {(tuple(map(str, fig.layout.xaxis.range)), tuple(fig.layout.xaxis.ticktext)) for fig in figures}
        self.assertEqual(len(axes), 1, axes)  # mismo eje X en todas las secciones
        start, end = (pd.Timestamp(value) for value in figures[0].layout.xaxis.range)
        self.assertEqual(start.dayofweek, 0)  # lunes
        self.assertEqual(end.dayofweek, 0)
        for fig in figures:
            for trace in fig.data:
                self.assertAlmostEqual(trace.width, WEEK_BAR_WIDTH_MS)


class NoSilentLegacyFallbackTest(unittest.TestCase):
    def test_madre_failure_raises_visible_error_not_another_report(self):
        state = full_charts_state()

        def broken_build(self, *args, **kwargs):
            raise RuntimeError("LayoutError simulado")

        from reportlab.platypus import SimpleDocTemplate

        with frozen_app_now(NOW), patch.object(SimpleDocTemplate, "build", broken_build):
            with self.assertRaises(report_generator.ReportBuildError) as ctx:
                report_generator.generate_visual_report_pdf(state, ATHLETE, "profe")
        self.assertIn(ATHLETE, str(ctx.exception))
        self.assertIn("LayoutError simulado", str(ctx.exception))

    def test_payload_failure_also_raises(self):
        state = full_charts_state()
        with frozen_app_now(NOW), patch.object(
            report_generator, "_build_professional_load_tolerance_payload", side_effect=ValueError("dato roto")
        ):
            with self.assertRaises(report_generator.ReportBuildError):
                report_generator.generate_visual_report_pdf(state, ATHLETE, "profe")


if __name__ == "__main__":
    unittest.main()
