"""PR F: cuadrante Fuerza vs Explosividad del gimnasio (IMTP vs CMJ por vuelo)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from charts.quadrant_charts import AGE_COLORS, chart_strength_quadrant
from modules import report_generator as rg
from modules import strength_quadrant as sq
from modules.app_clock import frozen_app_now
from modules.athlete_profile import Sexo
from modules.jump_analysis import _prepare_jump_df
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_STRAPS

TODAY = pd.Timestamp("2026-11-06")
THEME = rg._build_report_chart_theme()
NO_GOALS = pd.DataFrame(columns=sq.GOALS_COLUMNS)


def _flight_ms(height_cm: float) -> float:
    return 1000.0 * (8 * height_cm / 100.0 / 9.81) ** 0.5


def _take(name: str, date: str, device: str, *, cmj: float | None = None, imtp_rel: float | None = None, bw: float = 80.0) -> dict:
    row: dict[str, object] = {"Athlete": name, "Date": date, "Device": device, "Source": "platform", "BW_kg": bw}
    if cmj is not None:
        row.update({"CMJ_cm": cmj, "CMJ_flight_ms": _flight_ms(cmj)})
    if imtp_rel is not None:
        row["IMTP_N"] = imtp_rel * bw * 1.0
    return row


def _profiles(*rows: tuple[str, str, str | None]) -> pd.DataFrame:
    return pd.DataFrame([{"Athlete": name, "Sexo": sexo, "Fecha_nacimiento": birth} for name, sexo, birth in rows])


def _map(takes: list[dict], profiles: pd.DataFrame, goals: pd.DataFrame = NO_GOALS) -> sq.QuadrantMap:
    prepared = _prepare_jump_df(pd.DataFrame(takes), profile_df=profiles)
    return sq.build_quadrant_map(prepared, profiles, today=TODAY, goal_history=goals)


def _team() -> tuple[list[dict], pd.DataFrame]:
    takes = [
        _take("Ana", "2026-10-20", ERA_INVOLUTION_STRAPS, cmj=33.0, imtp_rel=36.0),
        _take("Bea", "2026-10-21", ERA_INVOLUTION_STRAPS, cmj=27.0, imtp_rel=30.0),
        _take("Carlos", "2026-10-22", ERA_INVOLUTION_STRAPS, cmj=44.0, imtp_rel=50.0),
        _take("Diego", "2026-10-23", ERA_INVOLUTION_STRAPS, cmj=36.0, imtp_rel=46.0),
        _take("Ezequiel", "2026-10-24", ERA_INVOLUTION_STRAPS, cmj=42.0, imtp_rel=40.0),
    ]
    profiles = _profiles(
        ("Ana", "Femenino", "1990-01-01"),
        ("Bea", "Femenino", None),
        ("Carlos", "Masculino", "2010-05-05"),
        ("Diego", "Masculino", "1980-01-01"),
        ("Ezequiel", "Masculino", "2000-01-01"),
    )
    return takes, profiles


class GoalTests(unittest.TestCase):
    def test_percent_of_goal_by_sex(self):
        takes, profiles = _team()
        placements = {p.athlete: p for p in _map(takes, profiles).placements}
        # CMJ: varones 40 cm, mujeres 30 cm.
        self.assertAlmostEqual(placements["Carlos"].pct_cmj, 110.0, places=0)
        self.assertAlmostEqual(placements["Ana"].pct_cmj, 110.0, places=0)
        # IMTP provisoria = mediana de la era vigente por sexo.
        self.assertAlmostEqual(placements["Diego"].pct_imtp, 100.0, places=0)  # mediana varones = 46
        self.assertAlmostEqual(placements["Ana"].pct_imtp, 36.0 / 33.0 * 100, places=0)  # mediana mujeres = 33

    def test_provisional_goal_is_labelled_and_undefined_without_data(self):
        takes, profiles = _team()
        quadrant_map = _map(takes, profiles)
        imtp_men = quadrant_map.goals[(Sexo.MASCULINO, sq.METRIC_IMTP)]
        self.assertEqual(imtp_men.source, sq.GOAL_SOURCE_PROVISIONAL)
        self.assertIn("provisoria", " ".join(quadrant_map.legend_lines))
        # Mujeres sin IMTP en la era vigente: meta sin definir y no se ubican.
        old_women = [_take("Ana", "2026-05-20", ERA_VALKYRIA_STRAPS, cmj=33.0, imtp_rel=36.0)]
        women_map = _map(old_women, _profiles(("Ana", "Femenino", None)))
        self.assertFalse(women_map.goals[(Sexo.FEMENINO, sq.METRIC_IMTP)].defined)
        self.assertEqual(women_map.unplaced, [("Ana", "meta de IMTP mujeres sin definir")])

    def test_configured_goal_wins_and_keeps_history(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            sq.save_goal("Masculino", sq.METRIC_IMTP, 40.0, changed_at="2026-11-01T10:00:00", store_dir=tmp, remote=False)
            sq.save_goal("M", sq.METRIC_IMTP, 50.0, changed_at="2026-11-02T10:00:00", store_dir=tmp, remote=False)
            history = pd.read_csv(tmp / sq.GOALS_FILENAME)
            self.assertEqual(len(history), 2)  # nunca pisa: queda el historial con fecha
            takes, profiles = _team()
            quadrant_map = _map(takes, profiles, goals=history)
            goal = quadrant_map.goals[(Sexo.MASCULINO, sq.METRIC_IMTP)]
            self.assertEqual(goal.value, 50.0)
            self.assertEqual(goal.source, sq.GOAL_SOURCE_CONFIGURED)
            self.assertIn("desde 02/11/2026", " ".join(quadrant_map.legend_lines))
            carlos = next(p for p in quadrant_map.placements if p.athlete == "Carlos")
            self.assertAlmostEqual(carlos.pct_imtp, 100.0, places=0)
            with self.assertRaises(ValueError):
                sq.save_goal("no_especificado", sq.METRIC_CMJ, 40.0, store_dir=tmp, remote=False)
            with self.assertRaises(ValueError):
                sq.save_goal("F", sq.METRIC_CMJ, 0, store_dir=tmp, remote=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_remote_save_is_off_without_supabase(self):
        from modules.remote_store import save_remote_quadrant_goal

        result = save_remote_quadrant_goal({"Sexo": "M", "Metrica": sq.METRIC_CMJ, "Meta": 40.0,
                                            "Fecha_cambio": "2026-11-06T10:00:00"}, row_key="x")
        self.assertFalse(result["enabled"])


class QuadrantTests(unittest.TestCase):
    def test_borders(self):
        self.assertEqual(sq.quadrant_of(100.0, 100.0), sq.QUADRANT_COMPLETE)
        self.assertEqual(sq.quadrant_of(100.0, 99.9), sq.QUADRANT_STRONG)
        self.assertEqual(sq.quadrant_of(99.9, 100.0), sq.QUADRANT_EXPLOSIVE)
        self.assertEqual(sq.quadrant_of(99.9, 99.9), sq.QUADRANT_BASE)

    def test_what_to_work(self):
        self.assertIn("Fuerza primero", sq.WHAT_TO_WORK[sq.QUADRANT_BASE])
        self.assertIn("Fuerza máxima", sq.WHAT_TO_WORK[sq.QUADRANT_EXPLOSIVE])
        self.assertIn("pliometría", sq.WHAT_TO_WORK[sq.QUADRANT_STRONG])
        self.assertIn("transferir al deporte", sq.WHAT_TO_WORK[sq.QUADRANT_COMPLETE])

    def test_age_groups(self):
        self.assertEqual(sq.age_group("2010-05-05", TODAY), "<18")
        self.assertEqual(sq.age_group("2000-01-01", TODAY), "18-29")
        self.assertEqual(sq.age_group("1990-01-01", TODAY), "30-44")
        self.assertEqual(sq.age_group("1980-01-01", TODAY), "45+")
        self.assertEqual(sq.age_group(None, TODAY), sq.AGE_UNKNOWN)

    def test_without_sex_listed_apart(self):
        takes, profiles = _team()
        takes.append(_take("Giffon", "2026-05-22", ERA_VALKYRIA_STRAPS, cmj=36.7, imtp_rel=40.0))
        quadrant_map = _map(takes, profiles)
        self.assertIn(("Giffon", "sin sexo en el perfil (no hay meta)"), quadrant_map.unplaced)
        self.assertNotIn("Giffon", [p.athlete for p in quadrant_map.placements])


class NoticeTests(unittest.TestCase):
    def test_previous_protocol_and_stale(self):
        takes, profiles = _team()
        takes.append(_take("Giffon", "2026-05-22", ERA_VALKYRIA_STRAPS, cmj=36.7, imtp_rel=40.0))
        profiles = pd.concat([profiles, _profiles(("Giffon", "Masculino", None))], ignore_index=True)
        giffon = next(p for p in _map(takes, profiles).placements if p.athlete == "Giffon")
        self.assertTrue(giffon.previous_protocol)
        self.assertTrue(giffon.stale)
        self.assertEqual(giffon.note(), "Evaluación 22/05/2026 · protocolo anterior · más de 12 semanas")
        self.assertIn("el IMTP suele dar más bajo (~30%); posición orientativa", giffon.note(professional=True))

    def test_recent_current_era_has_no_notice(self):
        takes, profiles = _team()
        carlos = next(p for p in _map(takes, profiles).placements if p.athlete == "Carlos")
        self.assertIsNone(carlos.note())

    def test_route_and_dotted_arrow_when_crossing_protocols(self):
        takes, profiles = _team()
        takes.insert(0, _take("Carlos", "2026-05-20", ERA_VALKYRIA_STRAPS, cmj=38.0, imtp_rel=36.0))
        quadrant_map = _map(takes, profiles)
        carlos = next(p for p in quadrant_map.placements if p.athlete == "Carlos")
        self.assertEqual(len(carlos.history), 1)
        self.assertTrue(carlos.crosses_protocol)
        figure = chart_strength_quadrant(quadrant_map, theme=THEME)
        routes = [trace for trace in figure.data if trace.name == "tu recorrido"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].line.dash, "dot")


class ChartTests(unittest.TestCase):
    def test_professional_view_names_everyone(self):
        takes, profiles = _team()
        figure = chart_strength_quadrant(_map(takes, profiles), theme=THEME)
        labels = [t for trace in figure.data if trace.mode == "markers+text" for t in trace.text]
        self.assertEqual(sorted(labels), ["Ana", "Bea", "Carlos", "Diego", "Ezequiel"])

    def test_athlete_view_is_anonymous_except_the_athlete(self):
        takes, profiles = _team()
        figure = chart_strength_quadrant(_map(takes, profiles), theme=THEME, highlight="Diego", anonymous=True)
        labels = [t for trace in figure.data if trace.mode == "markers+text" for t in trace.text if t]
        self.assertEqual(labels, ["Diego"])
        self.assertFalse(any(trace.showlegend for trace in figure.data if trace.mode == "markers+text"))

    def test_unknown_age_is_gray(self):
        takes, profiles = _team()
        figure = chart_strength_quadrant(_map(takes, profiles), theme=THEME)
        unknown = next(trace for trace in figure.data if trace.name == sq.AGE_UNKNOWN)
        self.assertEqual(list(unknown.text), ["Bea"])
        self.assertEqual(AGE_COLORS[sq.AGE_UNKNOWN], "#9A9A9A")

    def test_goals_in_chart_legend(self):
        takes, profiles = _team()
        figure = chart_strength_quadrant(_map(takes, profiles), theme=THEME)
        texts = " ".join(str(annotation.text) for annotation in figure.layout.annotations)
        self.assertIn("CMJ por vuelo: varones 40.0 cm · mujeres 30.0 cm", texts)


class PdfTests(unittest.TestCase):
    def _state(self) -> dict[str, object]:
        takes, profiles = _team()
        return {
            "jump_df": pd.DataFrame(takes),
            "athlete_profile_df": profiles,
            "quadrant_goal_history_df": NO_GOALS,
            "rpe_df": None, "wellness_df": None, "completion_df": None, "raw_df": None,
            "maxes_df": None, "rep_load_df": None, "acwr_dict": {}, "mono_dict": {},
        }

    def test_athlete_pdf_shows_quadrant_without_other_names(self):
        with frozen_app_now(datetime(2026, 11, 6, 12, 0)):
            pdf = rg.generate_visual_report_pdf(self._state(), "Diego", "atleta")
            payload = rg.build_individual_report_payload(self._state(), "Diego", "atleta")
        text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Tu lugar en el mapa del gimnasio", text)
        self.assertIn("Hoy estás en Fuerte - falta explosividad", text)  # CMJ 36/40 = 90%, IMTP 100%
        for other in ("Ana", "Bea", "Carlos", "Ezequiel"):
            self.assertNotIn(other, text)
        self.assertEqual(payload["strength_summary"]["quadrant"], sq.QUADRANT_STRONG)

    def test_athlete_without_sex_has_no_section(self):
        state = self._state()
        state["jump_df"] = pd.concat(
            [state["jump_df"], pd.DataFrame([_take("Giffon", "2026-05-22", ERA_VALKYRIA_STRAPS, cmj=36.7, imtp_rel=40.0)])],
            ignore_index=True,
        )
        with frozen_app_now(datetime(2026, 11, 6, 12, 0)):
            payload = rg.build_individual_report_payload(state, "Giffon", "atleta")
        self.assertIsNone(payload["strength_summary"])


class DashboardTeamMapTest(unittest.TestCase):
    """Vista Team: mapa con nombres, tabla y editor de metas, sin errores."""

    def test_team_view_renders_map_and_goal_editor(self):
        import importlib
        import os
        import uuid

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "app.py"
        tmp_root = Path(__file__).resolve().parent / f".tmp_quadrant_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True)
        original = os.environ.get("THRESHOLD_STORE_DIR")
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        try:
            takes, profiles = _team()
            pd.DataFrame(takes).to_csv(store_dir / "evaluations_history.csv", index=False)
            profiles.to_csv(store_dir / "athlete_profiles.csv", index=False)
            import local_store

            importlib.reload(local_store)
            at = AppTest.from_file(str(app_path), default_timeout=120)
            at.run()
            self.assertFalse(at.exception, at.exception)
            nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
            nav.set_value("Team").run()
            self.assertFalse(at.exception, at.exception)
            markdown = " ".join(str(item.value) for item in at.markdown)
            self.assertIn("Mapa del gimnasio: Fuerza vs Explosividad", markdown)
            self.assertTrue(any(button.label == "Guardar metas" for button in at.button))
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
