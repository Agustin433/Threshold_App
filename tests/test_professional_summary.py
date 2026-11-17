"""PR J: resumen ejecutivo del PDF profe (2 paginas + indice + anexo).

Casos: Ignacio (dos evaluaciones que cruzan de era, con sRPE, raw y
bienestar) y Habib (una evaluacion con la IMTP sin subida, sin sRPE ni
bienestar recientes).
"""

from __future__ import annotations

import re
import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from modules import professional_summary as psum
from modules import report_generator as rg
from modules.app_clock import frozen_app_now
from modules.jump_analysis import PATTERN_LIBRARY, _apply_pattern_claim_guards, _prepare_jump_df
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_NO_STRAPS, ERA_VALKYRIA_STRAPS

NOW = datetime(2026, 11, 16, 12, 0)
TODAY = pd.Timestamp(NOW).normalize()


def _take(name: str, date: str, device: str, *, flight_ms: float, dj_cm: float, tc_ms: float, imtp_n: float,
          bw: float = 80.0, **extra) -> dict:
    height = round(9.81 * (flight_ms / 1000) ** 2 / 8 * 100, 2)
    return {
        "Athlete": name, "Date": date, "Source": "platform", "Device": device, "BW_kg": bw,
        "CMJ_cm": height, "CMJ_flight_ms": flight_ms, "DJ_cm": dj_cm, "DJ_tc_ms": tc_ms,
        "DJ_drop_height_cm": 30.0, "IMTP_N": imtp_n, **extra,
    }


def _group(prefix: str = "Par") -> tuple[list[dict], list[str]]:
    takes, names = [], []
    for index in range(9):
        name = f"{prefix} {index:02d}"
        names.append(name)
        takes.append(
            _take(name, "2026-10-10", ERA_INVOLUTION_STRAPS, flight_ms=520.0 + 8 * index, dj_cm=26.0 + index,
                  tc_ms=230.0 - 4 * index, imtp_n=3000.0 + 60 * index)
        )
    return takes, names


def _profiles(names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Athlete": name, "Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Recreativo"} for name in names]
    )


def _ignacio_state() -> dict[str, object]:
    takes, names = _group()
    takes += [
        _take("Ignacio De La Vega", "2026-05-20", ERA_VALKYRIA_STRAPS, flight_ms=570.0, dj_cm=33.0, tc_ms=206.0,
              imtp_n=3235.0, bw=86.9),
        _take("Ignacio De La Vega", "2026-10-08", ERA_INVOLUTION_STRAPS, flight_ms=614.0, dj_cm=36.0, tc_ms=178.0,
              imtp_n=3491.0, bw=87.5),
    ]
    names.append("Ignacio De La Vega")
    weeks = pd.date_range("2026-09-28", "2026-11-09", freq="7D")
    rpe = [{"Athlete": "Ignacio De La Vega", "Date": (w + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), "RPE": 7,
            "Duration_min": 60, "sRPE": 420.0} for w in weeks[:2]]
    raw = [{"Athlete": "Ignacio De La Vega", "Fecha_sesion": (w + pd.Timedelta(days=d)).strftime("%Y-%m-%d"),
            "Exercise Name": "Sentadilla", "Reps": 5, "Result": 100.0}
           for w in weeks[:5] for d in (0, 2)]
    days = pd.date_range("2026-07-01", "2026-11-12", freq="4D")
    wellness = [{"Athlete": "Ignacio De La Vega", "Date": day.strftime("%Y-%m-%d"), "Sueno_hs": 7.5 + (day.day % 3) * 0.3,
                 "Estres": 4, "Dolor": 2, "Wellness_Score": 21.0 + (day.day % 4)} for day in days]
    return {
        "jump_df": pd.DataFrame(takes), "athlete_profile_df": _profiles(names),
        "rpe_df": pd.DataFrame(rpe), "raw_df": pd.DataFrame(raw), "wellness_df": pd.DataFrame(wellness),
        "completion_df": None, "maxes_df": None, "rep_load_df": None, "acwr_dict": {}, "mono_dict": {},
    }


def _habib_state() -> dict[str, object]:
    takes, names = _group()
    takes.append(
        _take("Fernando Habib", "2026-10-23", ERA_INVOLUTION_STRAPS, flight_ms=498.0, dj_cm=20.9, tc_ms=203.0,
              imtp_n=3883.0, bw=90.2, IMTP_quality_flag="curva_sin_subida")
    )
    names.append("Fernando Habib")
    return {
        "jump_df": pd.DataFrame(takes), "athlete_profile_df": _profiles(names),
        "rpe_df": None, "raw_df": None, "wellness_df": None,
        "completion_df": None, "maxes_df": None, "rep_load_df": None, "acwr_dict": {}, "mono_dict": {},
    }


def _render(state: dict[str, object], athlete: str) -> tuple[list[str], dict[str, int]]:
    with frozen_app_now(NOW):
        pdf = rg.generate_visual_report_pdf(dict(state), athlete, "profe")
    pages = [" ".join((page.extract_text() or "").split()) for page in PdfReader(BytesIO(pdf)).pages]
    return pages, dict(rg.LAST_PROFESSIONAL_INDEX)


class SummaryLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = {
            "Ignacio De La Vega": _render(_ignacio_state(), "Ignacio De La Vega"),
            "Fernando Habib": _render(_habib_state(), "Fernando Habib"),
        }

    def test_two_summary_pages_then_index_then_annex(self):
        for athlete, (pages, index) in self.rendered.items():
            with self.subTest(athlete=athlete):
                self.assertIn("RESUMEN - EVALUACIÓN", pages[0])
                self.assertIn(athlete, pages[0])
                self.assertIn("RESUMEN - CARGA Y BIENESTAR", pages[1])
                self.assertIn("Índice", pages[2])
                self.assertEqual(index[rg.SUMMARY_EVALUATION_TITLE], 1)
                self.assertEqual(index[rg.SUMMARY_LOAD_TITLE], 2)
                self.assertEqual(index["Resumen ejecutivo profesional"], 4)
                self.assertIn("REPORTE PROFESIONAL", pages[3])

    def test_index_page_numbers_point_to_their_sections(self):
        for athlete, (pages, index) in self.rendered.items():
            with self.subTest(athlete=athlete):
                for title, page in index.items():
                    self.assertRegex(pages[2], re.escape(title) + r" \.*\s*" + str(page) + r"\b")
                    if title.startswith("Resumen - "):
                        continue
                    self.assertIn(title, pages[page - 1], f"{title} no esta en la pagina {page}")

    def test_ignacio_page_one_has_changes_map_and_radar(self):
        page = self.rendered["Ignacio De La Vega"][0][0]
        self.assertIn("Involution con straps", page)
        self.assertIn("(!) cruza era", page)
        self.assertNotIn("■", page)
        self.assertIn("leer como orientativo", page)
        self.assertIn("supera umbral", page)
        self.assertIn("Cuadrante:", page)
        self.assertIn("z (intervalo), n", page)

    def test_alert_line_only_when_it_applies(self):
        self.assertIn("Calidad del dato", self.rendered["Fernando Habib"][0][0])
        self.assertIn("Toma IMTP inválida", self.rendered["Fernando Habib"][0][0])
        self.assertNotIn("Calidad del dato", self.rendered["Ignacio De La Vega"][0][0])

    def test_habib_first_evaluation_and_no_recent_load(self):
        pages = self.rendered["Fernando Habib"][0]
        self.assertIn("Primera evaluación (23/10/2026)", pages[0])
        self.assertIn("Sin registros de bienestar cargados.", pages[1])

    def test_ignacio_load_page(self):
        page = self.rendered["Ignacio De La Vega"][0][1]
        self.assertIn("Sesiones completadas (registro de TeamBuildr): 10 en 8 semanas.", page)
        self.assertIn("Semanas con sesiones completadas y sin RPE", page)
        self.assertIn("Variable que más se movió", page)
        self.assertIn("Foco del bloque:", page)


class DataQualityAlertTests(unittest.TestCase):
    def _history(self, rows: list[dict]) -> pd.DataFrame:
        return _prepare_jump_df(pd.DataFrame(rows))

    def test_clean_recent_current_era_has_no_alerts(self):
        history = self._history([_take("A", "2026-10-20", ERA_INVOLUTION_STRAPS, flight_ms=550, dj_cm=30, tc_ms=200, imtp_n=3000)])
        self.assertEqual(psum.data_quality_alerts(history, None, today=TODAY), [])

    def test_previous_protocol_and_stale(self):
        history = self._history([_take("A", "2026-05-20", ERA_VALKYRIA_STRAPS, flight_ms=550, dj_cm=30, tc_ms=200, imtp_n=3000)])
        alerts = psum.data_quality_alerts(history, None, today=TODAY)
        self.assertTrue(any("protocolo anterior" in alert for alert in alerts))
        self.assertTrue(any("más de 12" in alert for alert in alerts))

    def test_invalid_take(self):
        history = self._history([_take("A", "2026-10-20", ERA_INVOLUTION_STRAPS, flight_ms=550, dj_cm=30, tc_ms=200,
                                       imtp_n=3000, IMTP_quality_flag="curva_sin_subida")])
        alerts = psum.data_quality_alerts(history, None, today=TODAY)
        self.assertEqual(len(alerts), 1)
        self.assertIn("Toma IMTP inválida", alerts[0])

    def test_impulse_height_discarded(self):
        row = _take("A", "2026-10-20", ERA_INVOLUTION_STRAPS, flight_ms=550, dj_cm=30, tc_ms=200, imtp_n=3000)
        history = self._history([row]).assign(Jump_height_flag="CMJ")
        alerts = psum.data_quality_alerts(history, None, today=TODAY)
        self.assertEqual(alerts, ["Altura por impulso descartada en CMJ (20/10/2026): se compara por tiempo de vuelo."])


class SummaryDataTests(unittest.TestCase):
    def test_change_rows_keep_comparables_and_mark_era(self):
        delta = pd.DataFrame(
            [
                {"Variable": "CMJ_ft_cm", "Label": "CMJ (por tiempo de vuelo)", "Valor_actual": 46.2, "Valor_anterior": 39.8,
                 "Fecha_anterior": "2026-05-20", "Delta_abs": 6.4, "Delta_pct": 16.0, "Threshold_abs": 1.8,
                 "Signal": "mejora relevante", "Unusual": False},
                {"Variable": "DJ_cm", "Label": "DJ", "Valor_actual": 40.8, "Valor_anterior": 42.7,
                 "Fecha_anterior": "2026-05-20", "Delta_abs": -1.9, "Delta_pct": -4.5, "Threshold_abs": 3.1,
                 "Signal": "sin cambio relevante", "Unusual": False},
                {"Variable": "IMTP_N", "Label": "IMTP", "Valor_actual": 3491.0, "Valor_anterior": None,
                 "Signal": "no comparable por era", "Unusual": False},
                {"Variable": "SJ_cm", "Label": "SJ", "Valor_actual": 43.5, "Valor_anterior": None,
                 "Signal": "sin dato anterior", "Unusual": False},
            ]
        )
        rows = {row["Variable"]: row for row in psum.summary_change_rows(delta)}
        self.assertEqual(rows["CMJ (por tiempo de vuelo)"]["Lectura"], "↑ supera umbral")
        self.assertEqual(rows["CMJ (por tiempo de vuelo)"]["Umbral"], "±1.8")
        self.assertEqual(rows["DJ"]["Lectura"], "dentro del umbral")
        self.assertEqual(rows["IMTP"]["Lectura"], "no comparable (cruza era)")
        self.assertNotIn("SJ", rows)

    def test_weekly_load_from_raw_and_srpe(self):
        state = _ignacio_state()
        weekly = psum.weekly_load_summary(state["rpe_df"], state["raw_df"], None, "Ignacio De La Vega", today=TODAY)
        self.assertEqual(len(weekly), 8)
        self.assertTrue(bool(weekly["in_progress"].iloc[-1]))
        self.assertEqual(int(weekly["sessions"].sum()), 10)
        self.assertEqual(weekly["srpe"].notna().sum(), 2)


class BatteryCautionTests(unittest.TestCase):
    def test_partial_battery_caution_once_in_professional_readings(self):
        result = dict(PATTERN_LIBRARY["D"])
        _apply_pattern_claim_guards(result, pd.Series(dtype=object), patterns=["D"], flags=["partial_battery_caution"])
        caution = "La batería actual es parcial y la interpretación queda limitada"
        self.assertIn(caution, result["phys"])
        self.assertNotIn(caution, result["bio"])


if __name__ == "__main__":
    unittest.main()
