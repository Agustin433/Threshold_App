"""PR P: reestructura de vistas (9 -> 6). Cada seccion movida aparece donde
dice la tabla "donde quedo cada cosa" y solo ahi; cada vista y cada pestana
renderiza sin excepcion con datos; lo que se saco no aparece en ningun lado.

Un solo AppTest recorre todo sobre un store sintetico chico pero completo
(16 atletas, 8 por sexo para que haya cohorte de z, CMJ por vuelo e IMTP para
el mapa, sRPE, wellness, Raw Workouts, maximos y completion).
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import unittest
import uuid
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "app.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp_view_layout"

VIEWS = ["Hoy", "Atleta", "Equipo", "No-Plataforma", "Reportes", "Datos"]
ATLETA_TABS = ["Resumen", "Evaluación", "Carga y bienestar", "Fuerza"]
EQUIPO_TABS = ["Mapa y cuadrantes", "Carga del grupo", "Rankings"]

# Tabla "donde quedo cada cosa": ubicacion nueva -> titulos de seccion movidos.
# (vista vieja entre parentesis como referencia para el PR)
WHERE = {
    ("Hoy", None): [
        "Señales ejecutivas",            # Overview
        "Alertas priorizadas",           # Overview
        "Carga semanal",                 # Decision Bloque 1
        "Variación semanal",             # Decision Bloque 2
        "Perfiles de desarrollo",        # Decision Bloque 3 (ahora mapa + reactividad)
        "Distribución de volumen",       # Decision Bloque 4
        "Asistencia",                    # Decision Bloque 5
        "Wellness + carga",              # Decision Bloque 6
        "Evaluaciones pendientes",       # Decision Bloque 8
        "Fuentes cargadas",              # Overview (al final, colapsado)
    ],
    ("Atleta", "Resumen"): [
        "Resumen del atleta",            # Profile
        "🏁 Lo que lograste",            # Profile
        "📈 Tu evolución",               # Profile
        "🔢 Tus números hoy",            # Profile
        "🔋 Cómo venís aguantando",      # Profile
        "📊 Tu posición en el grupo",    # Profile
        "🧾 Perfil",                     # Profile
        "KPIs de evaluación",            # Profile
    ],
    ("Atleta", "Evaluación"): [
        "Análisis Plataforma",           # Analisis Plataforma
        "Evaluación seleccionada",
        "Cambios vs evaluación anterior",
        "Cambio vs baseline",
        "Detalle de la evaluación seleccionada",
        "Perfil actual compuesto",
        "Lectura por variable actual",
        "Historial temporal",
    ],
    ("Atleta", "Carga y bienestar"): [
        "Carga y bienestar",             # Load (individual)
        "Tendencia de carga",
        "Monotonía y strain",
        "Wellness",
        "Carga externa por tipo de estímulo",
    ],
    ("Atleta", "Fuerza"): [
        "Máximos del atleta",            # Profile
    ],
    ("Equipo", "Mapa y cuadrantes"): [
        "Cuadrantes de rendimiento",     # Team
        "🗺️ Mapa del gimnasio: Fuerza vs Explosividad",
    ],
    ("Equipo", "Carga del grupo"): [
        "Estado de carga",               # Team
        "Resumen semanal del equipo",    # Load (grupal)
    ],
    ("Equipo", "Rankings"): [
        "Última evaluación por atleta",  # Team
        "Ranking por Z-scores",          # Team
        "Ranking por métrica",           # PR R
        "Adherencia y completion",       # Team
        "Progresión de máximos",         # Team
    ],
}
EXPANDERS = {
    ("Hoy", None): ["Fuentes cargadas"],
    ("Equipo", "Mapa y cuadrantes"): ["📊 Referencias de comparacion", "⚙️ Metas del mapa (solo profe)"],
    ("Equipo", "Carga del grupo"): ["📋 Calidad de datos"],
}
REMOVED_TEXT = [
    "Ranking de ejecucion registrada",
    "Ejecucion registrada %",
    "Cuadrante DRI (experimental)",
    "orientativos para futbol profesional masculino",
    "Adonde ir despues",
    "Necesitan trabajo de fuerza base",
    "Patrón C",
    "Patrón D",
    # PR Q: jerga interna fuera de la UI.
    "motor P11",
    "reporte P2",
    "alerta(s) P11",
    "DANGER",
    "WARNING",
    "Calidad/readiness",
    "Readiness ",
    "Diseñada para lectura técnica",
    "radar · cuadrantes · kpis individuales",
]
REMOVED_CHART_TITLES = ["Cuadrante Secundario", "Cuadrante DRI (experimental)"]

_TITLE = re.compile(r'class="(?:subsection|module)-title">([^<]+)<')
_HEADING = re.compile(r"^#{2,4} (.+)$", re.M)


def _titles(at: AppTest) -> list[str]:
    found: list[str] = []
    for element in at.markdown:
        value = str(element.value)
        found += _TITLE.findall(value) + _HEADING.findall(value)
    return found


def _text(at: AppTest) -> str:
    parts = [str(e.value) for e in [*at.markdown, *at.caption, *at.info, *at.warning, *at.success]]
    parts += [str(e.label) for e in at.expander]
    for frame in at.dataframe:
        value = frame.value
        value = value.data if hasattr(value, "data") else value
        parts.append(" ".join(map(str, value.columns)) + " " + value.to_string())
    return " ".join(parts)


def _chart_specs(at: AppTest) -> str:
    return " ".join(str(getattr(e.proto, "spec", "")) for e in at.get("plotly_chart"))


class ViewLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = os.environ.get("THRESHOLD_STORE_DIR")
        cls.tmp = TMP_ROOT / uuid.uuid4().hex[:8]
        store = cls.tmp / "store"
        store.mkdir(parents=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(store)
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import benchmark_views
        finally:
            sys.path.pop(0)
        benchmark_views.seed_store(
            store, n_athletes=16, days_back=120, raw_rows=None, maxes_rows=400, flight_times=True,
            teambuildr_lift_names=True,
        )
        import local_store

        importlib.reload(local_store)
        cls.at = AppTest.from_file(str(APP_PY), default_timeout=300)
        cls.at.run()
        cls.snapshots: dict[tuple[str, str | None], dict[str, object]] = {}
        cls.exceptions: dict[tuple[str, str | None], list[str]] = {}
        nav_options = next(bg for bg in cls.at.button_group if bg.label == "Vista principal").options
        cls.nav_options = list(nav_options)
        for view in VIEWS:
            next(bg for bg in cls.at.button_group if bg.label == "Vista principal").set_value(view).run()
            tabs: list[str | None] = [None]
            tab_key = None
            if view == "Atleta":
                tabs, tab_key = ATLETA_TABS, "atleta_tab"
            elif view == "Equipo":
                tabs, tab_key = EQUIPO_TABS, "equipo_tab"
            for tab in tabs:
                if tab_key:
                    cls.at.session_state[tab_key] = tab
                    cls.at.run()
                key = (view, tab)
                cls.exceptions[key] = [str(e.value) for e in cls.at.exception]
                cls.snapshots[key] = {
                    "titles": _titles(cls.at),
                    "expanders": [str(e.label) for e in cls.at.expander],
                    "text": _text(cls.at),
                    "charts": _chart_specs(cls.at),
                    "tab_labels": [str(t.label) for t in cls.at.tabs],
                }

    @classmethod
    def tearDownClass(cls):
        if cls.original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = cls.original
        shutil.rmtree(cls.tmp, ignore_errors=True)
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()

    def test_six_views_and_hoy_is_default(self):
        self.assertEqual(self.nav_options, VIEWS)
        at = AppTest.from_file(str(APP_PY), default_timeout=300).run()
        nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
        self.assertEqual(nav.value, "Hoy")

    def test_every_view_and_tab_renders_without_exception(self):
        for key, errors in self.exceptions.items():
            with self.subTest(location=key):
                self.assertEqual(errors, [])

    def test_tabs_are_the_specified_ones(self):
        self.assertEqual(self.snapshots[("Atleta", "Resumen")]["tab_labels"], ATLETA_TABS)
        self.assertEqual(self.snapshots[("Equipo", "Mapa y cuadrantes")]["tab_labels"], EQUIPO_TABS)

    def test_each_moved_section_is_where_the_table_says_and_only_there(self):
        for location, titles in WHERE.items():
            for title in titles:
                with self.subTest(location=location, section=title):
                    self.assertIn(title, self.snapshots[location]["titles"])
                    # No-Plataforma reutiliza el cuerpo de Analisis (sin cambios), asi
                    # que las secciones de Atleta > Evaluacion tambien estan ahi.
                    shared_with = {("No-Plataforma", None)} if location == ("Atleta", "Evaluación") else set()
                    elsewhere = [
                        other for other, snap in self.snapshots.items()
                        if other != location and other not in shared_with and title in snap["titles"]
                    ]
                    self.assertEqual(elsewhere, [], f"{title} tambien aparece en {elsewhere}")

    def test_moved_expanders(self):
        for location, labels in EXPANDERS.items():
            for label in labels:
                with self.subTest(location=location, expander=label):
                    self.assertIn(label, self.snapshots[location]["expanders"])

    def test_hoy_order_matches_spec(self):
        titles = self.snapshots[("Hoy", None)]["titles"]
        order = [titles.index(title) for title in WHERE[("Hoy", None)]]
        self.assertEqual(order, sorted(order))
        self.assertIn("Lectura integrada", self.snapshots[("Hoy", None)]["text"])

    def test_hoy_has_a_single_evaluation_source_and_no_repeated_alerts(self):
        text = self.snapshots[("Hoy", None)]["text"]
        # La lectura integrada ya no repite las alertas como lista de focos.
        self.assertNotIn("Sin bloqueos ejecutivos claros", text)

    def test_development_profiles_count_map_quadrants_and_reactivity(self):
        text = self.snapshots[("Hoy", None)]["text"]
        self.assertIn("Cuadrante del mapa", text)
        self.assertIn("Perfil de reactividad", text)
        for label in ("Patrón A", "Patrón B", "Patrón E", "Sin patron de reactividad"):
            self.assertIn(label, text)

    def test_estimated_strength_moved_to_fuerza(self):
        self.assertIn("Fuerza estimada:", self.snapshots[("Atleta", "Fuerza")]["text"])
        self.assertNotIn("Fuerza estimada:", self.snapshots[("Atleta", "Resumen")]["text"])

    def test_map_tab_keeps_rsi_sj_and_drops_secondary_and_dri(self):
        charts = self.snapshots[("Equipo", "Mapa y cuadrantes")]["charts"]
        self.assertIn("Cuadrante Principal", charts)
        for location, snap in self.snapshots.items():
            for title in REMOVED_CHART_TITLES:
                with self.subTest(location=location, chart=title):
                    self.assertNotIn(title, snap["charts"])

    def test_z_ranking_only_uses_cohort_z(self):
        # 8 atletas por sexo, mismo deporte y nivel: hay cohorte y hay heatmap.
        rankings = self.snapshots[("Equipo", "Rankings")]
        self.assertIn("Heatmap Z-scores", rankings["charts"])
        self.assertNotIn("no hay ranking por z", rankings["text"])

    def test_removed_items_do_not_appear_anywhere(self):
        for location, snap in self.snapshots.items():
            for fragment in REMOVED_TEXT:
                with self.subTest(location=location, removed=fragment):
                    self.assertNotIn(fragment, snap["text"])


class ZRankingWithoutCohortTest(unittest.TestCase):
    """Con 3 atletas por sexo no hay cohorte de 8: el ranking muestra el mensaje."""

    def test_message_when_no_metric_has_a_cohort_of_8(self):
        original = os.environ.get("THRESHOLD_STORE_DIR")
        tmp = TMP_ROOT / uuid.uuid4().hex[:8]
        store = tmp / "store"
        store.mkdir(parents=True)
        try:
            os.environ["THRESHOLD_STORE_DIR"] = str(store)
            sys.path.insert(0, str(ROOT / "scripts"))
            try:
                import benchmark_views
            finally:
                sys.path.pop(0)
            benchmark_views.seed_store(
                store, n_athletes=6, days_back=60, raw_rows=None, maxes_rows=60, flight_times=True
            )
            import local_store

            importlib.reload(local_store)
            at = AppTest.from_file(str(APP_PY), default_timeout=300).run()
            next(bg for bg in at.button_group if bg.label == "Vista principal").set_value("Equipo").run()
            at.session_state["equipo_tab"] = "Rankings"
            at.run()
            self.assertFalse(at.exception, at.exception)
            self.assertIn("Ranking por Z-scores", _titles(at))
            self.assertIn("no hay ranking por z", " ".join(str(item.value) for item in at.info))
            self.assertNotIn("Heatmap Z-scores", _chart_specs(at))
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp, ignore_errors=True)
            if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
                TMP_ROOT.rmdir()


if __name__ == "__main__":
    unittest.main()
