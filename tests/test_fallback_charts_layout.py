"""Graficos de respaldo del PDF (sin kaleido): layout verificable.

Defectos del PDF real (oct/2026):
- wellness: la linea se dibujaba fuera del recuadro, sobre el titulo de la
  pagina (eje Y fijo 1-5 con un score 0-30, sin recorte);
- sRPE: el titulo pisaba el valor y la leyenda, y el eje Y no tenia escala.

El test es geometrico: recorre las formas del Drawing y verifica que la
linea/barras queden dentro del area del grafico, que ningun texto se pise con
otro y que el eje Y tenga marcas. Opcionalmente guarda PNGs para revision
visual (THRESHOLD_CHART_PNG_DIR).
"""

from __future__ import annotations

import os
import unittest
from itertools import combinations

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

from modules.report_generator import (
    FALLBACK_TITLE_BAND,
    _pdf_theme_threshold,
    build_fallback_weekly_ema_chart,
    build_fallback_wellness_chart,
)

PALETTE = _pdf_theme_threshold(colors, variant="professional")
SHAPES = {"Drawing": Drawing, "Rect": Rect, "Line": Line, "PolyLine": PolyLine, "Circle": Circle, "String": String}

# Wellness real en escala 0-30 (el PDF real tenia 7.7 y valores >20).
WELLNESS_POINTS = [
    {"label": "13/10", "score": 22.0},
    {"label": "14/10", "score": 7.7},
    {"label": "15/10", "score": 25.5},
    {"label": "16/10", "score": 18.0},
    {"label": "17/10", "score": 29.0},
]
# sRPE semanal: la ultima semana es la mas alta (su etiqueta de valor es la
# que chocaba con el titulo y la leyenda).
SRPE_POINTS = [
    {"label": "01/09", "value": 820.0, "ema": 820.0},
    {"label": "08/09", "value": 960.0, "ema": 860.0},
    {"label": "15/09", "value": 1010.0, "ema": 903.0},
    {"label": "22/09", "value": 1180.0, "ema": 982.0},
    {"label": "29/09", "value": 1441.0, "ema": 1113.0},
]


def _string_box(item: String) -> tuple[float, float, float, float]:
    width = stringWidth(item.text, item.fontName, item.fontSize)
    anchor = getattr(item, "textAnchor", "start")
    x0 = item.x - width if anchor == "end" else item.x - width / 2 if anchor == "middle" else item.x
    return (x0, item.y - item.fontSize * 0.25, x0 + width, item.y + item.fontSize * 0.8)


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _plot_top(drawing: Drawing) -> float:
    return drawing.height - FALLBACK_TITLE_BAND


def _check_layout(test: unittest.TestCase, drawing: Drawing, *, title: str) -> None:
    test.assertIsNotNone(drawing)
    top = _plot_top(drawing)
    strings = [item for item in drawing.contents if isinstance(item, String)]

    # 1) Linea y puntos dentro del area (nunca en la franja del titulo).
    for item in drawing.contents:
        if isinstance(item, PolyLine):
            ys = item.points[1::2]
            xs = item.points[0::2]
            test.assertTrue(all(0 <= y <= top for y in ys), f"{title}: linea fuera del area: {ys}")
            test.assertTrue(all(0 <= x <= drawing.width for x in xs), f"{title}: linea fuera en X")
        if isinstance(item, Circle):
            test.assertLessEqual(item.cy, top)
        is_data_bar = isinstance(item, Rect) and item.width < drawing.width and item.y < top - 10
        if is_data_bar:
            test.assertLessEqual(item.y + item.height, top + 0.01, f"{title}: barra invade el titulo")

    # 2) Ningun texto se pisa con otro.
    boxes = [(item.text, _string_box(item)) for item in strings]
    for (text_a, box_a), (text_b, box_b) in combinations(boxes, 2):
        test.assertFalse(_overlap(box_a, box_b), f"{title}: '{text_a}' se superpone con '{text_b}'")

    # 3) El titulo queda en la franja superior y ningun valor entra en ella.
    title_items = [item for item in strings if item.text == title]
    test.assertEqual(len(title_items), 1)
    test.assertGreaterEqual(title_items[0].y, top)

    # 4) Eje Y con escala: al menos 3 marcas numericas a la izquierda del area.
    tick_labels = [item for item in strings if getattr(item, "textAnchor", "") == "end" and item.text.replace(".", "").isdigit()]
    test.assertGreaterEqual(len(tick_labels), 3, f"{title}: eje Y sin escala")

    out_dir = os.environ.get("THRESHOLD_CHART_PNG_DIR")
    if out_dir:
        # PDF del grafico para revision visual (pdftoppm -png lo convierte).
        from reportlab.graphics import renderPDF

        renderPDF.drawToFile(drawing, os.path.join(out_dir, f"{title.split()[0].lower()}.pdf"))


class FallbackChartLayoutTest(unittest.TestCase):
    def test_wellness_line_stays_inside_box_with_0_30_scale(self):
        drawing = build_fallback_wellness_chart(
            WELLNESS_POINTS, PALETTE, SHAPES, width_mm=174, height_mm=44, mm=mm
        )
        _check_layout(self, drawing, title="Wellness score")
        tick_texts = {item.text for item in drawing.contents if isinstance(item, String)}
        self.assertIn("30", tick_texts)
        self.assertIn("0", tick_texts)

    def test_wellness_out_of_scale_values_are_clipped(self):
        points = [{"label": "a", "score": 45.0}, {"label": "b", "score": -5.0}]
        drawing = build_fallback_wellness_chart(points, PALETTE, SHAPES, mm=mm)
        _check_layout(self, drawing, title="Wellness score")

    def test_weekly_srpe_title_value_and_legend_do_not_overlap(self):
        drawing = build_fallback_weekly_ema_chart(
            SRPE_POINTS, PALETTE, SHAPES, width_mm=174, height_mm=48, mm=mm
        )
        _check_layout(self, drawing, title="sRPE semanal + EMA 6 semanas")
        texts = {item.text for item in drawing.contents if isinstance(item, String)}
        self.assertIn("1441", texts)
        self.assertIn("sRPE semanal", texts)
        self.assertIn("EMA 6", texts)

    def test_weekly_srpe_compact_height(self):
        drawing = build_fallback_weekly_ema_chart(
            SRPE_POINTS, PALETTE, SHAPES, width_mm=174, height_mm=42, mm=mm
        )
        _check_layout(self, drawing, title="sRPE semanal + EMA 6 semanas")

    def test_partial_weeks_are_hatched_and_labelled(self):
        # Semana con 1 de 4 sesiones reportadas: barra rayada con rotulo, no
        # una barra llena que se lea como caida de carga.
        points = [dict(point) for point in SRPE_POINTS]
        points[2].update({"value": 270.0, "partial": True, "sessions_done": 4, "sessions_with_srpe": 1})
        points[-1].update({"partial": True, "sessions_done": 4, "sessions_with_srpe": 3})
        drawing = build_fallback_weekly_ema_chart(points, PALETTE, SHAPES, width_mm=174, height_mm=48, mm=mm)
        _check_layout(self, drawing, title="sRPE semanal + EMA 6 semanas")
        texts = {item.text for item in drawing.contents if isinstance(item, String)}
        self.assertIn("1/4", texts)
        self.assertIn("1441 · 3/4", texts)
        self.assertTrue(any("semana parcial" in text for text in texts))
        stripes = [
            item for item in drawing.contents
            if isinstance(item, Line) and item.y1 == item.y2 and item.strokeColor == PALETTE["orange"]
        ]
        self.assertGreater(len(stripes), 3)

    def test_not_enough_points(self):
        self.assertIsNone(build_fallback_wellness_chart(WELLNESS_POINTS[:1], PALETTE, SHAPES, mm=mm))
        self.assertIsNone(build_fallback_weekly_ema_chart(SRPE_POINTS[:1], PALETTE, SHAPES, mm=mm))


if __name__ == "__main__":
    unittest.main()
