"""PR D: ajustes post PR C (radar y textos).

Casos reales (valores sinteticos con la misma estructura):
- Ignacio / Tomas / Holgado: CMJ por impulso sin cohorte en la era Involution
  -> eje "CMJ (vuelo)" contra la cohorte de vuelo de todas las eras.
- Lopez Muñoz (1 eje), Palazzo y Gray (2 ejes sin vuelo): tabla, no radar.
- Giffon: ultima IMTP en valkyria_straps (22/05/2026) -> protocolo anterior;
  PDF atleta en 2 paginas.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from charts.dashboard_charts import RADAR_FEW_AXES_TEXT, chart_composite_profile_radar, chart_radar
from charts.load_charts import chart_estimated_strength
from modules import athlete_report as ar
from modules import report_generator as rg
from modules.app_clock import frozen_app_now
from modules.jump_analysis import (
    RADAR_CMJ_FLIGHT_AXIS,
    _prepare_jump_df,
    build_composite_profile_metric_rows,
    build_composite_profile_snapshot,
    build_profile_radar_row,
    radar_axis_values,
    radar_fallback_rows,
    radar_is_drawable,
)
from modules.measurement_eras import ALL_ERAS, CURRENT_ERA, ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_STRAPS
from modules.reference_engine import format_z_with_interval, parse_reference, z_interval

THEME = rg._build_report_chart_theme()


def _profile(name: str) -> dict:
    return {"Athlete": name, "Sexo": "Masculino", "Deporte": "Rugby", "Nivel": "Recreativo"}


def _flight_ms(height_cm: float) -> float:
    # h = g t^2 / 8 -> t = sqrt(8 h / g)
    return 1000.0 * (8 * height_cm / 100.0 / 9.81) ** 0.5


def _take(name: str, date: str, device: str, *, cmj: float | None = None, dj: float | None = None,
          imtp: float | None = None, tc: float = 200.0) -> dict:
    row: dict[str, object] = {"Athlete": name, "Date": date, "Source": "platform", "Device": device, "BW_kg": 80.0}
    if cmj is not None:
        row.update({"CMJ_cm": cmj, "CMJ_flight_ms": _flight_ms(cmj)})
    if dj is not None:
        row.update({"DJ_cm": dj, "DJ_tc_ms": tc, "DJ_drop_height_cm": 30.0})
    if imtp is not None:
        row["IMTP_N"] = imtp
    return row


def _valkyria_team(n: int = 10, *, with_cmj: bool = True, with_dj: bool = True, with_imtp: bool = False):
    takes, profiles = [], []
    for index in range(n):
        name = f"V {index:02d}"
        takes.append(
            _take(
                name, "2026-06-10", ERA_VALKYRIA_STRAPS,
                cmj=(34.0 + index) if with_cmj else None,
                dj=(26.0 + index) if with_dj else None,
                imtp=(2600.0 + 60 * index) if with_imtp else None,
                tc=230.0 - 2 * index,
            )
        )
        profiles.append(_profile(name))
    return takes, profiles


def _radar_row(takes: list[dict], profiles: list[dict], athlete: str) -> pd.Series:
    prepared = _prepare_jump_df(pd.DataFrame(takes), profile_df=pd.DataFrame(profiles))
    return build_profile_radar_row(prepared[prepared["Athlete"] == athlete])


# ── 1. CMJ por tiempo de vuelo ────────────────────────────────────────────
class CmjFlightAxisTests(unittest.TestCase):
    def test_ignacio_gets_cmj_flight_axis_against_all_eras(self):
        takes, profiles = _valkyria_team()
        takes.append(_take("Ignacio De La Vega", "2026-10-08", ERA_INVOLUTION_STRAPS, cmj=46.2, dj=38.0, tc=190.0))
        profiles.append(_profile("Ignacio De La Vega"))
        row = _radar_row(takes, profiles, "Ignacio De La Vega")
        payload = radar_axis_values(row)
        labels = [axis[0] for axis in payload["axes"]]
        self.assertIn(RADAR_CMJ_FLIGHT_AXIS[0], labels)
        self.assertNotIn("CMJ", labels)  # impulso: sin cohorte en Involution
        info = parse_reference(row.get("CMJ_ft_Z_reference_source"))
        self.assertEqual(info["era"], ALL_ERAS)
        self.assertEqual(info["size"], 11)  # una toma por atleta, ambas eras
        self.assertIn("Ignacio De La Vega", info["athletes"])

    def test_impulse_cmj_stays_when_comparable(self):
        takes, profiles = _valkyria_team()
        row = _radar_row(takes, profiles, "V 05")
        labels = [axis[0] for axis in radar_axis_values(row)["axes"]]
        self.assertIn("CMJ", labels)
        self.assertNotIn(RADAR_CMJ_FLIGHT_AXIS[0], labels)

    def test_flight_cohort_uses_one_take_per_athlete(self):
        takes, profiles = _valkyria_team()
        for day, height in (("2026-07-01", 50.0), ("2026-08-01", 51.0), ("2026-09-01", 52.0)):
            takes.append(_take("V 00", day, ERA_VALKYRIA_STRAPS, cmj=height))
        prepared = _prepare_jump_df(pd.DataFrame(takes), profile_df=pd.DataFrame(profiles))
        latest = prepared[prepared["Athlete"] == "V 03"].iloc[-1]
        self.assertEqual(int(latest["CMJ_ft_Z_cohort_n"]), 10)

    def test_composite_profile_reads_cmj_by_flight_when_impulse_has_no_reference(self):
        takes, profiles = _valkyria_team()
        takes.append(_take("Tomas De La Vega", "2026-10-21", ERA_INVOLUTION_STRAPS, cmj=44.0, dj=34.0))
        profiles.append(_profile("Tomas De La Vega"))
        row = _radar_row(takes, profiles, "Tomas De La Vega")
        cmj_row = next(r for r in build_composite_profile_metric_rows(row) if r["value_col"] == "CMJ_ft_cm")
        self.assertEqual(cmj_row["Variable"], "CMJ (vuelo)")


# ── 2. Menos de 3 ejes: tabla ─────────────────────────────────────────────
class FewAxesTableTests(unittest.TestCase):
    def test_lopez_munoz_one_axis_is_a_table(self):
        takes, profiles = _valkyria_team(with_cmj=False, with_dj=False, with_imtp=True)
        takes.append(_take("Agustin Lopez Muñoz", "2026-05-07", ERA_VALKYRIA_STRAPS, imtp=3000.0))
        profiles.append(_profile("Agustin Lopez Muñoz"))
        row = _radar_row(takes, profiles, "Agustin Lopez Muñoz")
        self.assertEqual(len(radar_axis_values(row)["axes"]), 1)
        self.assertFalse(radar_is_drawable(row))
        rows = radar_fallback_rows(row)
        self.assertEqual([r["Variable"] for r in rows], ["IMTP relPF"])
        self.assertIn("n=11", rows[0]["Comparación"])
        self.assertIn("atletas", rows[0]["Referencia"])
        for figure in (chart_radar(row, "Agustin Lopez Muñoz", None, theme=THEME),
                       chart_composite_profile_radar(row, "Agustin Lopez Muñoz", theme=THEME)):
            self.assertEqual(len(figure.data), 0)
            self.assertEqual(figure.layout.annotations[0].text, RADAR_FEW_AXES_TEXT)

    def test_palazzo_and_gray_two_axes_are_a_table(self):
        takes, profiles = _valkyria_team(with_cmj=False)
        for name, dj in (("Carlos Palazzo", 36.0), ("Santiago Gray", 33.0)):
            takes.append(_take(name, "2026-06-10", ERA_VALKYRIA_STRAPS, dj=dj, tc=205.0))
            profiles.append(_profile(name))
        for name in ("Carlos Palazzo", "Santiago Gray"):
            with self.subTest(athlete=name):
                row = _radar_row(takes, profiles, name)
                # DJ height, DJ RSI y tiempo de contacto: forzamos 2 ejes sacando el tc.
                row = row.copy()
                row["TC_inv_Z"] = None
                row["TC_inv_Z_source"] = ""
                payload = radar_axis_values(row)
                self.assertEqual(len(payload["axes"]), 2)
                self.assertFalse(payload["drawable"])
                self.assertEqual(len(radar_fallback_rows(row)), 2)

    def test_three_axes_draw_a_radar(self):
        takes, profiles = _valkyria_team()
        row = _radar_row(takes, profiles, "V 04")
        self.assertTrue(radar_is_drawable(row))
        self.assertGreater(len(chart_radar(row, "V 04", None, theme=THEME).data), 0)


# ── 3. z con intervalo por incertidumbre del SD ───────────────────────────
class ZIntervalTests(unittest.TestCase):
    def test_example_from_spec(self):
        self.assertEqual(format_z_with_interval(1.0, 9), "+1.0 (0.8 a 1.3), n=9")

    def test_interval_formula(self):
        low, high = z_interval(1.0, 9)
        k = 1 / (2 * 8) ** 0.5
        self.assertAlmostEqual(low, 1 / (1 + k))
        self.assertAlmostEqual(high, 1 / (1 - k))
        low, high = z_interval(-1.39, 9)
        self.assertLess(low, -1.39)
        self.assertGreater(high, -1.39)

    def test_interval_narrows_with_n(self):
        width_small = z_interval(1.0, 9)[1] - z_interval(1.0, 9)[0]
        width_large = z_interval(1.0, 66)[1] - z_interval(1.0, 66)[0]
        self.assertLess(width_large, width_small)

    def test_no_interval_without_n(self):
        self.assertEqual(format_z_with_interval(0.5, None), "+0.5")
        self.assertEqual(format_z_with_interval(None, 9), "—")

    def test_professional_metric_table_shows_interval(self):
        takes, profiles = _valkyria_team()
        state = {"jump_df": pd.DataFrame(takes), "athlete_profile_df": pd.DataFrame(profiles)}
        payload = rg._build_professional_composite_profile_payload(state, "V 09")
        z_texts = [text for text in payload["metric_table"]["Z-score"].tolist() if text not in {"—", "-"}]
        self.assertTrue(z_texts)
        self.assertTrue(all(" a " in text and "n=10" in text for text in z_texts), z_texts)

    def test_professional_feedback_text_gets_interval(self):
        takes, profiles = _valkyria_team()
        state = {"jump_df": pd.DataFrame(takes), "athlete_profile_df": pd.DataFrame(profiles)}
        payload = rg._build_professional_composite_profile_payload(state, "V 09")
        high = str(payload["feedback"].get("high") or "")
        converted = rg._professional_text_with_z_intervals(high, payload)
        self.assertIn("n=10", converted)
        # El texto base (que lee el PDF atleta) no cambia.
        self.assertNotIn("n=10", high)


# ── 4. Foco IMTP segun la era de la ultima IMTP ───────────────────────────
class ImtpFocusEraTests(unittest.TestCase):
    def _detailed(self, device: str, date: str) -> str:
        row = pd.Series(
            {
                "Athlete": "Agustin Giffon", "Date": pd.Timestamp(date), "Device": device, "Source": "platform",
                "IMTP_N": 3084.0, "IMTP_relPF": 40.1, "DJ_cm": 30.0, "DJ_tc_ms": 222.0, "DJ_RSI": 1.35,
            }
        )
        payload = rg._build_pdf_neuromuscular_profile_payload(row)
        return str(payload["training_priority_detailed"])

    def test_giffon_previous_protocol(self):
        text = self._detailed(ERA_VALKYRIA_STRAPS, "2026-05-22")
        self.assertIn("Tu última medición de IMTP es con el protocolo anterior", text)
        self.assertNotIn("protocolo actual", text)

    def test_current_era_says_current_protocol(self):
        self.assertEqual(CURRENT_ERA, ERA_INVOLUTION_STRAPS)
        text = self._detailed(ERA_INVOLUTION_STRAPS, "2026-10-08")
        self.assertIn("con el protocolo actual", text)

    def test_composite_snapshot_keeps_era_of_last_imtp(self):
        # Ultima evaluacion sin IMTP (Involution); la IMTP es de Valkyria.
        rows = [
            _take("Agustin Giffon", "2026-05-22", ERA_VALKYRIA_STRAPS, dj=30.0, imtp=3084.0),
            _take("Agustin Giffon", "2026-10-15", ERA_INVOLUTION_STRAPS, cmj=36.7),
        ]
        prepared = _prepare_jump_df(pd.DataFrame(rows))
        snapshot, _ = build_composite_profile_snapshot(prepared)
        self.assertEqual(snapshot["IMTP__era"], ERA_VALKYRIA_STRAPS)
        payload = rg._build_pdf_neuromuscular_profile_payload(snapshot)
        self.assertEqual(payload["imtp_era"], ERA_VALKYRIA_STRAPS)
        self.assertIn("protocolo anterior", str(payload["training_priority_detailed"]))


# ── 5. Una variable por prueba en "Lo que más se destaca" ─────────────────
class StrengthsOnePerTestTests(unittest.TestCase):
    def test_dj_rsi_and_dj_are_the_same_test(self):
        self.assertEqual(ar.top_strengths("DJ RSI (+1.42), DJ (+1.35), Tiempo de contacto (+0.73)"), "DJ RSI")

    def test_one_per_test_highest_z_first(self):
        text = "CMJ (vuelo) (+1.07), DJ (+1.35), DRI (+1.42), IMTP (+0.9), SJ (+0.6)"
        self.assertEqual(ar.top_strengths(text), "DRI, CMJ (vuelo)")

    def test_test_map(self):
        cases = {
            "CMJ": "CMJ", "CMJ (vuelo)": "CMJ", "SJ": "SJ", "DJ": "DJ", "DJ RSI": "DJ", "DRI": "DJ",
            "Tiempo de contacto": "DJ", "IMTP": "IMTP", "IMTP relPF": "IMTP",
        }
        for name, test in cases.items():
            with self.subTest(name=name):
                self.assertEqual(ar.strength_test_of(name), test)


# ── 6. Grafico de fuerza y PDF de Giffon en 2 paginas ─────────────────────
def _giffon_state() -> dict[str, object]:
    athlete = "Agustin Giffon"
    rpe_rows, wellness_rows, raw_rows = [], [], []
    for week in range(8):
        monday = pd.Timestamp("2026-09-07") + pd.Timedelta(weeks=week)
        for offset in (0, 2, 4):
            day = monday + pd.Timedelta(days=offset)
            rpe_rows.append({"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "RPE": 6, "Duration_min": 60, "sRPE": 360})
            wellness_rows.append(
                {"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "Sueno_hs": 6.0, "Estres": 6, "Dolor": 6, "Wellness_Score": 14.0}
            )
            for exercise, load in (("Barbell Back Squat", 90), ("Barbell Bench Press", 70), ("Barbell Deadlift", 110)):
                raw_rows.append(
                    {"Athlete": athlete, "Fecha_sesion": day.strftime("%Y-%m-%d"), "Date": day.strftime("%Y-%m-%d"),
                     "Exercise": exercise, "Exercise Name": exercise, "Result": load + week, "Reps": 5}
                )
    import local_store as ls
    from modules.data_loader import prepare_raw_workouts_df

    rpe_df, wellness_df, raw_df = pd.DataFrame(rpe_rows), pd.DataFrame(wellness_rows), pd.DataFrame(raw_rows)
    prepared = prepare_raw_workouts_df(raw_df)
    acwr, mono = ls.build_load_models(rpe_df, weeks=None, raw_df=prepared)
    return {
        "jump_df": pd.DataFrame(
            [_take(athlete, "2026-05-22", ERA_VALKYRIA_STRAPS, cmj=36.7, dj=30.0, imtp=3084.0, tc=222.0)]
        ),
        "rpe_df": rpe_df,
        "wellness_df": wellness_df,
        "completion_df": pd.DataFrame([{"Athlete": athlete, "Assigned": 40, "Completed": 30, "Pct": 75.0}]),
        "raw_df": raw_df,
        "prepared_raw_df": prepared,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": acwr,
        "mono_dict": mono,
        "weekly_summaries": ls.build_weekly_summaries(
            rpe_df, wellness_df, raw_df, acwr_dict=acwr, prepared_raw_df=prepared
        ),
    }


class StrengthChartAndLayoutTests(unittest.TestCase):
    def test_y_axis_title_is_short_and_window_goes_in_title(self):
        daily = pd.DataFrame(
            [{"Date": pd.Timestamp("2026-10-01"), "Lift": "Peso muerto", "e1RM_kg": 120.0},
             {"Date": pd.Timestamp("2026-10-15"), "Lift": "Peso muerto", "e1RM_kg": 125.0}]
        )
        figure = chart_estimated_strength(daily, theme=THEME, mode="print")
        self.assertEqual(figure.layout.yaxis.title.text, "kg")
        self.assertIn("mejor de 14 días", figure.layout.title.text)

    def test_giffon_pdf_layout_is_compact(self):
        # PR E: el conteo exacto de paginas depende de las fuentes del entorno
        # (fallaba en CI con 3). Se verifica un rango y la regla de llenado,
        # que se mide en la misma compaginacion que arma el PDF.
        with frozen_app_now(datetime(2026, 11, 5, 12, 0)):
            pdf = rg.generate_visual_report_pdf(_giffon_state(), "Agustin Giffon", "atleta")
        pages = [page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages]
        joined = " ".join(pages)
        # Las mismas secciones que el PDF real: fuerza, carga y bienestar
        # (PR G: juntas en "Como venis aguantando") y cierre.
        self.assertIn("Tu fuerza", joined)
        self.assertIn("Cómo venís aguantando", joined)
        self.assertIn("bienestar", joined)
        self.assertIn("Diccionario", joined)
        self.assertGreaterEqual(len(pages), 1)
        self.assertLessEqual(len(pages), 3)
        fill = rg.LAST_INDIVIDUAL_LAYOUT["page_fill"]
        self.assertEqual(len(fill), len(pages))
        self.assertTrue(all(value >= rg.INDIVIDUAL_MIN_PAGE_FILL for value in fill[:-1]), fill)
        # El diccionario nunca queda solo en una pagina.
        for page in pages:
            if "Diccionario" in page:
                self.assertIn("Próximos pasos", page)


if __name__ == "__main__":
    unittest.main()
