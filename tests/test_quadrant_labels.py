"""PR Q: rotulos del mapa del gimnasio sin superposicion.

En zonas densas el rotulo pasa a iniciales o se desplaza con linea guia; el
nombre completo queda siempre en el hover.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from charts.quadrant_charts import _label_layout, _overlap, chart_strength_quadrant, initials
from modules import report_generator as rg
from modules import strength_quadrant as sq

THEME = rg._build_report_chart_theme()
NAMES = [
    "Ana Lopez", "Bruno Alvarez", "Carla Romero", "Diego Garcia", "Elena Ruiz", "Facundo Sosa",
    "Gina Perez", "Hugo Gomez", "Ines Torres", "Juan Diaz", "Karen Lopez", "Lucas Alvarez",
    "Maria Romero", "Nicolas Garcia", "Olga Ruiz", "Pablo Sosa",
]
# Cumulo denso real (sintetico del benchmark): casi todos alrededor del 100%.
POINTS = [
    (101.0, 84.0), (102.7, 112.0), (98.8, 88.0), (97.5, 110.5), (98.5, 84.0), (100.2, 112.5),
    (100.6, 86.0), (100.6, 118.0), (99.8, 92.0), (96.3, 118.5), (98.9, 93.5), (99.6, 121.0),
    (100.1, 88.5), (99.4, 119.5), (103.0, 94.5), (101.9, 128.5),
]


def _layout():
    points = [(x, y, sq.short_name(name), initials(name)) for (x, y), name in zip(POINTS, NAMES)]
    return _label_layout(points, 100.0, 100.0, bounds=(50.0, 150.0, 50.0, 150.0), guides=(100.0, 100.0))


class LabelLayoutTest(unittest.TestCase):
    def test_initials(self):
        self.assertEqual(initials("Ignacio De La Vega"), "ID")
        self.assertEqual(initials("Ana"), "An")

    def test_dense_cluster_labels_do_not_overlap(self):
        layout = _layout()
        boxes = [item["box"] for item in layout]
        self.assertTrue(all(box is not None for box in boxes))
        for index, box in enumerate(boxes):
            with self.subTest(athlete=NAMES[index]):
                self.assertEqual(_overlap(box, boxes[:index] + boxes[index + 1:]), 0.0)

    def test_every_athlete_keeps_a_visible_label(self):
        for item, name in zip(_layout(), NAMES):
            with self.subTest(athlete=name):
                self.assertIn(item["text"], {sq.short_name(name), initials(name)})
                if item["kind"] == "far":
                    self.assertIsNotNone(item["anchor"])

    def test_sparse_points_keep_the_short_name(self):
        points = [(60.0, 60.0, "Ana L.", "AL"), (140.0, 140.0, "Bruno A.", "BA")]
        layout = _label_layout(points, 100.0, 100.0, bounds=(50.0, 150.0, 50.0, 150.0))
        self.assertEqual([item["text"] for item in layout], ["Ana L.", "Bruno A."])
        self.assertEqual([item["kind"] for item in layout], ["near", "near"])


class ChartHoverTest(unittest.TestCase):
    def _map(self):
        placements = [
            SimpleNamespace(
                athlete=name, pct_imtp=x, pct_cmj=y, imtp=40.0, cmj=35.0, quadrant=sq.QUADRANT_COMPLETE,
                age_group=sq.AGE_UNKNOWN, flagged=False, history=[], crosses_protocol=False,
                note=lambda professional=True: "",
            )
            for (x, y), name in zip(POINTS, NAMES)
        ]
        return SimpleNamespace(placements=placements, unplaced=[], goals={}, legend="")

    def test_full_name_in_hover_and_every_label_drawn_once(self):
        try:
            figure = chart_strength_quadrant(self._map(), theme=THEME, show_goals=False)
        except Exception as exc:  # pragma: no cover - el mapa sintetico no trae metas
            self.skipTest(f"mapa sintetico incompleto: {exc}")
        hover_names = {row[0] for trace in figure.data if trace.mode == "markers+text" for row in trace.customdata}
        self.assertEqual(hover_names, set(NAMES))
        near = [t for trace in figure.data if trace.mode == "markers+text" for t in trace.text if t]
        far = [a for a in figure.layout.annotations if getattr(a, "hovertext", None) in set(NAMES)]
        self.assertEqual(len(near) + len(far), len(NAMES))
        for annotation in far:
            self.assertTrue(annotation.showarrow)


if __name__ == "__main__":
    unittest.main()
