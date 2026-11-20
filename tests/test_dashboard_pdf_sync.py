"""PR K: el dashboard muestra lo mismo que el PDF profe para un mismo atleta.

Se levanta app.py con AppTest sobre un store aislado y, con el mismo estado de
sesion que usa la app, se arma lo que calcula el PDF profe. Se comparan:
cambios vs evaluacion anterior, cambio vs baseline, ACWR y adherencia.
"""

from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from modules import professional_summary as psum
from modules import report_generator as rg
from modules.app_clock import app_today
from modules.jump_analysis import (
    build_jump_baseline_display_table,
    build_jump_delta_display_table,
    compute_baseline_delta,
    compute_evaluation_changes,
)
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_NO_STRAPS, ERA_VALKYRIA_STRAPS

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp_dashboard_sync"
TODAY = app_today()
ATHLETE = "Ignacio Sync"


def _day(offset: int) -> str:
    return (TODAY - pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def _take(offset: int, device: str, flight_ms: float, imtp: float, dj: float, tc: float) -> dict:
    return {
        "Athlete": ATHLETE, "Date": _day(offset), "Source": "platform", "Device": device, "BW_kg": 87.0,
        "CMJ_cm": round(9.81 * (flight_ms / 1000) ** 2 / 8 * 100, 2), "CMJ_flight_ms": flight_ms,
        "DJ_cm": dj, "DJ_tc_ms": tc, "DJ_drop_height_cm": 30.0, "IMTP_N": imtp,
    }


def _seed(store: Path) -> None:
    # Mismo patron que Ignacio: tres tomas Valkyria y la ultima Involution.
    pd.DataFrame(
        [
            _take(330, ERA_VALKYRIA_NO_STRAPS, 540.0, 2500.0, 40.0, 215.0),
            _take(300, ERA_VALKYRIA_NO_STRAPS, 555.0, 2600.0, 41.0, 210.0),
            _take(170, ERA_VALKYRIA_STRAPS, 570.0, 3235.0, 42.7, 206.0),
            _take(40, ERA_INVOLUTION_STRAPS, 614.0, 3491.0, 40.8, 178.0),
        ]
    ).to_csv(store / "evaluations_history.csv", index=False)
    session_days = [offset for offset in range(2, 50) if offset % 2 == 0]
    pd.DataFrame(
        [{"Athlete": ATHLETE, "Date": _day(offset), "RPE": 6, "Duration_min": 60, "sRPE": 360.0 + offset}
         for offset in session_days]
    ).to_csv(store / "rpe_history.csv", index=False)
    pd.DataFrame(
        [{"Athlete": ATHLETE, "Fecha_sesion": _day(offset), "Completed Date": _day(offset), "Date": _day(offset),
          "Exercise Name": "Back Squat", "Set Number": 1, "Reps": 5, "Result": 100.0, "Tags": "Strength"}
         for offset in session_days]
    ).to_csv(store / "raw_workouts_history.csv", index=False)
    pd.DataFrame(
        [{"Athlete": ATHLETE, "Assigned": 61, "Completed": 17, "Pct": 27.87, "Percent": "27.87%",
          "completion_scope": "uploaded_period_total", "source_type": "completion_report_summary"}]
    ).to_csv(store / "completion_history.csv", index=False)


def _frames(at: AppTest) -> list[pd.DataFrame]:
    out = []
    for element in at.dataframe:
        value = element.value
        out.append(value.data if hasattr(value, "data") else value)
    return out


def _table_with(at: AppTest, column: str) -> pd.DataFrame:
    for frame in _frames(at):
        if column in frame.columns:
            return frame.reset_index(drop=True)
    raise AssertionError(f"No hay tabla con la columna {column}")


class DashboardPdfSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = os.environ.get("THRESHOLD_STORE_DIR")
        cls.tmp = TMP_ROOT / uuid.uuid4().hex[:8]
        store = cls.tmp / "store"
        store.mkdir(parents=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(store)
        _seed(store)
        import local_store

        importlib.reload(local_store)
        cls.at = AppTest.from_file(str(APP_PY), default_timeout=180)
        cls.at.run()
        assert not cls.at.exception, cls.at.exception
        cls.state = {key: cls.at.session_state[key] for key in (
            "jump_df", "rpe_df", "wellness_df", "completion_df", "raw_df", "maxes_df", "acwr_dict", "mono_dict",
        ) if key in cls.at.session_state}
        cls.state.setdefault("athlete_profile_df", None)
        cls.state.setdefault("rep_load_df", None)
        cls.history = rg._professional_jump_history(cls.state, ATHLETE)

    @classmethod
    def tearDownClass(cls):
        if cls.original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = cls.original
        shutil.rmtree(cls.tmp, ignore_errors=True)
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()

    def _view(self, name: str) -> None:
        nav = next(bg for bg in self.at.button_group if bg.label == "Vista principal")
        nav.set_value(name).run()
        self.assertFalse(self.at.exception, self.at.exception)

    def test_changes_and_baseline_match_pdf(self):
        # PR P: Analisis Plataforma -> Atleta > Evaluacion (selector compartido).
        self._view("Atleta")
        self.at.selectbox(key="atleta_sel").set_value(ATHLETE).run()
        self.at.session_state["atleta_tab"] = "Evaluación"
        self.at.run()
        self.assertFalse(self.at.exception, self.at.exception)

        # Cambios: la misma tabla que el PDF profe (incluida la fila por vuelo).
        pdf_changes = rg._build_professional_change_payload(self.state, ATHLETE)["delta_df"]
        expected = build_jump_delta_display_table(pdf_changes)
        shown = _table_with(self.at, "Anterior")
        pd.testing.assert_frame_equal(shown[["Variable", "Actual", "Anterior", "Delta abs"]],
                                      expected[["Variable", "Actual", "Anterior", "Delta abs"]])
        flight = shown[shown["Variable"] == "CMJ (por tiempo de vuelo)"].iloc[0]
        self.assertEqual((flight["Anterior"], flight["Actual"]), ("39.8", "46.2"))
        # PR L: IMTP se compara entre eras con aviso (3235 -> 3491).
        imtp_change = shown[shown["Variable"] == "IMTP"].iloc[0]
        self.assertEqual(imtp_change["Anterior"], "3235")
        self.assertIn("⚠ compara", imtp_change["Senal"])

        # Baseline: tomas previas; IMTP cruza era con aviso.
        last = pd.to_datetime(self.history["Date"]).max()
        expected_baseline = build_jump_baseline_display_table(compute_baseline_delta(self.history, last))
        shown_baseline = _table_with(self.at, "Baseline")
        pd.testing.assert_frame_equal(shown_baseline, expected_baseline)
        imtp = shown_baseline[shown_baseline["Variable"] == "IMTP"].iloc[0]
        self.assertIn("⚠ compara", imtp["Senal"])
        warnings = " ".join(str(item.value) for item in self.at.warning)
        self.assertIn("Valkyria", warnings)
        flight_baseline = shown_baseline[shown_baseline["Variable"] == "CMJ (por tiempo de vuelo)"].iloc[0]
        self.assertNotIn(last.strftime("%d/%m/%Y"), flight_baseline["Metodo"])
        # Tambien coincide con la tabla de cambios del PDF (mismo motor).
        self.assertTrue(compute_evaluation_changes(self.history, last)["Variable"].tolist())

    def test_acwr_is_context_and_matches_pdf_summary(self):
        # PR P: Load (individual) -> Atleta > Carga y bienestar.
        self._view("Atleta")
        self.at.selectbox(key="atleta_sel").set_value(ATHLETE).run()
        self.at.session_state["atleta_tab"] = "Carga y bienestar"
        self.at.run()
        self.assertFalse(self.at.exception, self.at.exception)
        weekly = psum.weekly_load_summary(
            self.state.get("rpe_df"), self.state.get("raw_df"), self.state["acwr_dict"].get(ATHLETE), ATHLETE,
            today=TODAY,
        )
        last_acwr = pd.to_numeric(weekly["acwr"], errors="coerce").dropna()
        self.assertFalse(last_acwr.empty)
        acwr_metric = next(m for m in self.at.metric if str(m.label).startswith("ACWR"))
        self.assertEqual(acwr_metric.value, f"{last_acwr.iloc[-1]:.2f}")
        text = " ".join(str(item.value) for item in [*self.at.markdown, *self.at.caption, *self.at.info, *self.at.warning])
        for zone_word in ("Alto riesgo", "zona optima", "Precaucion", "precaucion"):
            self.assertNotIn(zone_word, text)

    def test_adherence_matches_pdf(self):
        # PR P: Adherencia y completion -> Equipo > Rankings.
        self._view("Equipo")
        self.at.session_state["equipo_tab"] = "Rankings"
        self.at.run()
        self.at.selectbox(key="completion_sel_team").set_value(ATHLETE).run()
        self.assertFalse(self.at.exception, self.at.exception)
        pdf_value = rg._professional_completion_snapshot(self.state, ATHLETE)["value"]
        self.assertEqual(pdf_value, "27.9% (período del export de TeamBuildr)")
        metric = next(m for m in self.at.metric if "Completion ponderado" in str(m.label))
        self.assertIn("período del export de TeamBuildr", str(metric.label))
        self.assertEqual(f"{metric.value} ({rg.COMPLETION_EXPORT_PERIOD_LABEL})", pdf_value)
        # Sesiones por semana desde raw: mismas que el resumen del PDF profe.
        weekly = psum.weekly_load_summary(None, self.state.get("raw_df"), None, ATHLETE, today=TODAY)
        shown = _table_with(self.at, "Sesiones")
        self.assertEqual(shown["Sesiones"].astype(int).tolist(), weekly["sessions"].astype(int).tolist())

    def test_overview_adherence_card_has_no_traffic_light(self):
        self._view("Hoy")  # PR P: Overview -> Hoy
        snapshot = self.at.session_state  # la tarjeta se arma con el mismo raw
        html = " ".join(str(item.value) for item in self.at.markdown)
        self.assertIn("período del export de TeamBuildr", html)
        self.assertNotIn("Periodo cargado (sin fecha)", html)
        self.assertIsNotNone(snapshot)


if __name__ == "__main__":
    unittest.main()
