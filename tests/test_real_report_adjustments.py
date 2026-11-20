"""PR I: ajustes con los reportes reales del 16/11 (Habib, Ignacio).

- Percentil de posicion por rango medio (rank - 0.5)/N: nunca 0 ni 100.
  Ignacio, ultimo de 6 varones Involution en IMTP, decia "0" -> ~8.
- "Tu perfil" (Patron A/B/C/D) solo en el PDF profe (caso Habib, Patron D),
  con tildes en ese texto.
- Adherencia del Completion Report resumido (uploaded_period_total): sin tile
  en atleta/cliente; en profe con la leyenda del export de TeamBuildr.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from modules import athlete_report as ar
from modules import report_generator as rg
from modules.app_clock import frozen_app_now
from modules.jump_analysis import PATTERN_LIBRARY, _prepare_jump_df
from modules.measurement_eras import ERA_INVOLUTION_STRAPS
from modules.reference_engine import mid_rank_percentile
from modules.zscore_sources import ZSource

NOW = datetime(2026, 11, 16, 12, 0)


def _six_involution_men() -> pd.DataFrame:
    takes, profiles = [], []
    for index in range(6):
        name = f"M {index:02d}"
        takes.append(
            {
                "Athlete": name, "Date": "2026-10-10", "Source": "platform", "Device": ERA_INVOLUTION_STRAPS,
                "BW_kg": 80.0, "IMTP_N": 3000.0 + 40 * index,
            }
        )
        profiles.append({"Athlete": name, "Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Recreativo"})
    return _prepare_jump_df(pd.DataFrame(takes), profile_df=pd.DataFrame(profiles))


class MidRankPercentileTests(unittest.TestCase):
    def test_formula(self):
        self.assertAlmostEqual(mid_rank_percentile(0, 0, 6), 100 * 0.5 / 6)
        self.assertAlmostEqual(mid_rank_percentile(5, 0, 6), 100 * 5.5 / 6)
        # Dos empatados al fondo de 6: rango medio 1.5 -> (1.5 - 0.5) / 6.
        self.assertAlmostEqual(mid_rank_percentile(0, 1, 6), 100 * 1.0 / 6)

    def test_ignacio_last_of_six_is_about_8_not_0(self):
        prepared = _six_involution_men()
        last = prepared[prepared["Athlete"] == "M 00"].iloc[-1]
        first = prepared[prepared["Athlete"] == "M 05"].iloc[-1]
        self.assertEqual(last["IMTP_relPF_Z_source"], str(ZSource.COHORT_RANK))
        self.assertEqual(float(last["IMTP_relPF_Z_percentile"]), 8.3)
        self.assertEqual(float(first["IMTP_relPF_Z_percentile"]), 91.7)
        bar = ar.group_position(last)["bars"][0]
        self.assertEqual(bar["percentile"], 8.3)
        self.assertIsNone(bar["band"])

    def test_never_0_or_100_with_z_and_band(self):
        for z_value, expected in ((-6.0, 1.0), (6.0, 99.0)):
            with self.subTest(z=z_value):
                row = pd.Series({"IMTP_relPF_Z": z_value, "IMTP_relPF_Z_source": "cohort_z", "IMTP_relPF_Z_cohort_n": 10})
                bar = ar.group_position(row)["bars"][0]
                self.assertEqual(bar["percentile"], expected)
                self.assertGreaterEqual(min(bar["band"]), 1.0)
                self.assertLessEqual(max(bar["band"]), 99.0)


def _take(name: str, *, flight_ms: float, sj_ms: float, dj_cm: float, tc_ms: float, imtp_n: float, bw: float = 80.0) -> dict:
    return {
        "Athlete": name, "Date": "2026-10-23", "Source": "platform", "Device": ERA_INVOLUTION_STRAPS, "BW_kg": bw,
        "CMJ_cm": round(9.81 * (flight_ms / 1000) ** 2 / 8 * 100, 2), "CMJ_flight_ms": flight_ms,
        "SJ_cm": round(9.81 * (sj_ms / 1000) ** 2 / 8 * 100, 2), "SJ_flight_ms": sj_ms,
        "DJ_cm": dj_cm, "DJ_tc_ms": tc_ms, "DJ_drop_height_cm": 30.0, "IMTP_N": imtp_n,
    }


def _habib_state(completion: pd.DataFrame | None = None) -> dict[str, object]:
    # Habib: ultimo en todas las pruebas frente a 9 pares -> Patron D.
    takes = [_take("Fernando Habib", flight_ms=470.0, sj_ms=455.0, dj_cm=18.0, tc_ms=330.0, imtp_n=2300.0, bw=90.2)]
    names = ["Fernando Habib"]
    for index in range(9):
        name = f"Par {index:02d}"
        names.append(name)
        takes.append(
            _take(name, flight_ms=540.0 + 6 * index, sj_ms=520.0 + 6 * index, dj_cm=28.0 + index,
                  tc_ms=220.0 - 3 * index, imtp_n=3100.0 + 50 * index)
        )
    profiles = [{"Athlete": name, "Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Recreativo"} for name in names]
    return {
        "jump_df": pd.DataFrame(takes),
        "athlete_profile_df": pd.DataFrame(profiles),
        "completion_df": completion,
        "rpe_df": None, "wellness_df": None, "raw_df": None, "maxes_df": None, "rep_load_df": None,
        "acwr_dict": {}, "mono_dict": {},
    }


def _pdf_text(state: dict[str, object], athlete: str, audience: str) -> str:
    with frozen_app_now(NOW):
        pdf = rg.generate_visual_report_pdf(dict(state), athlete, audience)
    return " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


class ProfileSectionTests(unittest.TestCase):
    def test_habib_has_no_pattern_d_and_no_profile_section_for_athlete_or_client(self):
        # PR P: el patron D ya no se detecta (lo cubre el mapa del gimnasio, "Base").
        state = _habib_state()
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(state, "Fernando Habib", "atleta")
        self.assertNotIn("Patrón D", str((payload.get("profile") or {}).get("label")))
        for audience in ("atleta", "cliente"):
            with self.subTest(audience=audience):
                text = _pdf_text(state, "Fernando Habib", audience)
                self.assertNotIn("Tu perfil", text)
                self.assertNotIn("Patrón", text)
                self.assertNotIn("Déficit neuromuscular", text)
                self.assertNotIn("batería parcial", text)

    def test_pattern_d_text_has_accents(self):
        pattern = PATTERN_LIBRARY["D"]
        self.assertEqual(pattern["label"], "Patrón D - Déficit neuromuscular global")
        joined = " ".join(str(value) for value in pattern.values() if isinstance(value, str))
        self.assertIn("batería", joined)
        self.assertIn("interpretación", joined)
        self.assertNotIn("bateria", joined)
        self.assertNotIn("interpretacion", joined)


EXPORT_COMPLETION = pd.DataFrame(
    [
        {"Athlete": "Ignacio De La Vega", "Assigned": 61, "Completed": 17, "Pct": 27.87, "Date": pd.NaT,
         "completion_scope": "uploaded_period_total", "source_type": "completion_report_summary"},
        {"Athlete": "Fernando Habib", "Assigned": 66, "Completed": 26, "Pct": 39.39, "Date": pd.NaT,
         "completion_scope": "uploaded_period_total", "source_type": "completion_report_summary"},
    ]
)


class ExportAdherenceTests(unittest.TestCase):
    def _state(self) -> dict[str, object]:
        return _habib_state(EXPORT_COMPLETION.copy())

    def test_no_tile_for_athlete_or_client(self):
        state = self._state()
        for athlete in ("Fernando Habib", "Ignacio De La Vega"):
            for audience in ("atleta", "cliente"):
                with self.subTest(athlete=athlete, audience=audience):
                    with frozen_app_now(NOW):
                        payload = rg.build_individual_report_payload(state, athlete, audience)
                    self.assertIsNone(payload["completion_text"])
        text = _pdf_text(state, "Fernando Habib", "atleta")
        self.assertNotIn("Adherencia", text)
        self.assertNotIn("39.4%", text)
        self.assertNotIn("Constancia", _pdf_text(state, "Fernando Habib", "cliente"))

    def test_professional_value_has_export_legend(self):
        state = self._state()
        with frozen_app_now(NOW):
            ignacio = rg._professional_completion_snapshot(state, "Ignacio De La Vega")
            habib = rg._professional_completion_snapshot(state, "Fernando Habib")
        self.assertEqual(ignacio["value"], "27.9% (período del export de TeamBuildr)")
        self.assertEqual(habib["value"], "39.4% (período del export de TeamBuildr)")
        text = " ".join(_pdf_text(state, "Fernando Habib", "profe").split())
        self.assertIn("39.4% (período del export de TeamBuildr)", text)

    def test_dated_completion_keeps_the_tile(self):
        dated = pd.DataFrame(
            [{"Athlete": "Fernando Habib", "Assigned": 4, "Completed": 3, "Pct": 75.0, "Date": "2026-11-12"}]
        )
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(_habib_state(dated), "Fernando Habib", "atleta")
        self.assertEqual(payload["completion_text"], "75.0%")


if __name__ == "__main__":
    unittest.main()
