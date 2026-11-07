"""PR H: coherencia del reporte atleta/cliente (casos de los PDFs reales del 06/11).

- Foco del proximo bloque desde el cuadrante del mapa del gimnasio
  (Anadon/Reinoso/Cornet en Base decian "Mantener el bloque actual"; Ignacio
  en "falta fuerza" decia "repetir IMTP"). El aviso de IMTP pasa a Proximos
  pasos. Sin ubicacion en el mapa, la logica de siempre.
- Sin "Tu referencia actual" en "Lo que lograste".
- Sin tablas de "ultima semana completa" en el PDF atleta/cliente.
- Frase neutra cuando una metrica de "Tu evolucion" baja mas que el umbral
  (Anadon: CMJ por vuelo 36.6 -> 32.6 cm).
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
from modules.jump_analysis import _prepare_jump_df
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_NO_STRAPS, ERA_VALKYRIA_STRAPS
from modules.report_messages import NEXT_STEP_IMTP_PREVIOUS_PROTOCOL, NEXT_STEP_IMTP_REPEAT, NEXT_STEP_TEXT
from modules.strength_quadrant import GOALS_COLUMNS, QUADRANT_BASE, QUADRANT_EXPLOSIVE, WHAT_TO_WORK

NOW = datetime(2026, 11, 6, 12, 0)
# Meta de IMTP de varones configurada (48.1 N/kg, la provisoria real del 06/11).
GOALS = pd.DataFrame(
    [{"Sexo": "M", "Metrica": "IMTP_relPF", "Meta": 48.1, "Fecha_cambio": "2026-11-01T10:00:00"}],
    columns=GOALS_COLUMNS,
)


def _row(name: str, date: str, device: str, *, flight_ms: float | None = None, imtp_n: float | None = None,
         bw: float = 80.0, dj: float | None = None) -> dict:
    row: dict[str, object] = {"Athlete": name, "Date": date, "Device": device, "Source": "platform", "BW_kg": bw}
    if flight_ms is not None:
        # CMJ por impulso igual al de vuelo: la toma no queda marcada.
        height = 9.81 * (flight_ms / 1000.0) ** 2 / 8 * 100
        row.update({"CMJ_cm": round(height, 2), "CMJ_flight_ms": flight_ms})
    if imtp_n is not None:
        row["IMTP_N"] = imtp_n
    if dj is not None:
        row.update({"DJ_cm": dj, "DJ_tc_ms": 210.0, "DJ_drop_height_cm": 30.0})
    return row


ANADON = [
    _row("Alejandro Anadon", "2025-12-17", ERA_VALKYRIA_NO_STRAPS, flight_ms=546, imtp_n=2019.0, bw=73.0, dj=28.0),
    _row("Alejandro Anadon", "2026-05-07", ERA_VALKYRIA_STRAPS, flight_ms=516, imtp_n=2526.0, bw=74.0, dj=28.0),
]
REINOSO = [_row("Sergio Reinoso", "2026-05-14", ERA_VALKYRIA_STRAPS, flight_ms=506, imtp_n=2380.0, dj=27.0)]
CORNET = [_row("Evaristo Cornet", "2026-05-07", ERA_VALKYRIA_STRAPS, flight_ms=476, imtp_n=2590.0, dj=25.0)]
IGNACIO = [
    _row("Ignacio De La Vega", "2026-05-20", ERA_VALKYRIA_STRAPS, flight_ms=570, imtp_n=3235.0, bw=86.9, dj=33.0),
    _row("Ignacio De La Vega", "2026-10-08", ERA_INVOLUTION_STRAPS, flight_ms=614, imtp_n=3491.0, bw=87.5, dj=36.0),
]
GIFFON = [_row("Agustin Giffon", "2026-05-22", ERA_VALKYRIA_STRAPS, flight_ms=547, imtp_n=3084.0, bw=77.0, dj=30.0)]
PROFILES = pd.DataFrame(
    [
        {"Athlete": name, "Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Recreativo", "Fecha_nacimiento": "2000-01-01"}
        for name in ("Alejandro Anadon", "Sergio Reinoso", "Evaristo Cornet", "Ignacio De La Vega")
    ]
)


def _state() -> dict[str, object]:
    return {
        "jump_df": pd.DataFrame(ANADON + REINOSO + CORNET + IGNACIO + GIFFON),
        "athlete_profile_df": PROFILES,
        "quadrant_goal_history_df": GOALS,
        "rpe_df": None, "wellness_df": None, "completion_df": None, "raw_df": None,
        "maxes_df": None, "rep_load_df": None, "acwr_dict": {}, "mono_dict": {},
    }


def _payload(athlete: str, audience: str = "atleta", state: dict[str, object] | None = None) -> dict[str, object]:
    with frozen_app_now(NOW):
        return rg.build_individual_report_payload(state or _state(), athlete, audience)


def _pdf_text(athlete: str, audience: str = "atleta", state: dict[str, object] | None = None) -> str:
    with frozen_app_now(NOW):
        pdf = rg.generate_visual_report_pdf(state or _state(), athlete, audience)
    return " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


class FocusFromQuadrantTests(unittest.TestCase):
    def test_base_athletes_get_strength_first(self):
        for athlete in ("Alejandro Anadon", "Sergio Reinoso", "Evaristo Cornet"):
            with self.subTest(athlete=athlete):
                payload = _payload(athlete)
                self.assertEqual(payload["strength_summary"]["quadrant"], QUADRANT_BASE)
                self.assertEqual(payload["focus"], WHAT_TO_WORK[QUADRANT_BASE])
                self.assertNotIn("Mantener el bloque actual", payload["focus"])

    def test_ignacio_lacking_strength_and_imtp_notice_moves_to_next_steps(self):
        payload = _payload("Ignacio De La Vega")
        self.assertEqual(payload["strength_summary"]["quadrant"], QUADRANT_EXPLOSIVE)
        self.assertEqual(payload["focus"], WHAT_TO_WORK[QUADRANT_EXPLOSIVE])
        self.assertNotIn("IMTP", payload["focus"])
        self.assertIn(NEXT_STEP_TEXT[NEXT_STEP_IMTP_REPEAT]["atleta"], payload["next_steps"])

    def test_imtp_step_by_era(self):
        flagged = {"flags": ["imtp_reference_missing"]}
        self.assertEqual(ar.imtp_next_step({**flagged, "imtp_era": ERA_INVOLUTION_STRAPS}), NEXT_STEP_IMTP_REPEAT)
        self.assertEqual(ar.imtp_next_step({**flagged, "imtp_era": ERA_VALKYRIA_STRAPS}), NEXT_STEP_IMTP_PREVIOUS_PROTOCOL)
        self.assertIsNone(ar.imtp_next_step({"flags": [], "imtp_era": ERA_VALKYRIA_STRAPS}))

    def test_client_imtp_step_has_no_jargon(self):
        for key in (NEXT_STEP_IMTP_REPEAT, NEXT_STEP_IMTP_PREVIOUS_PROTOCOL):
            self.assertNotIn("IMTP", NEXT_STEP_TEXT[key]["cliente"])

    def test_not_placed_keeps_previous_logic(self):
        # Giffon: sin sexo en el perfil -> no esta en el mapa; el foco sigue
        # siendo el de siempre (aviso de protocolo anterior).
        payload = _payload("Agustin Giffon")
        self.assertIsNone(payload["strength_summary"])
        self.assertIn("protocolo anterior", payload["focus"])


class ReferenceLineTests(unittest.TestCase):
    def test_no_reference_line(self):
        for athlete in ("Alejandro Anadon", "Agustin Giffon"):
            with self.subTest(athlete=athlete):
                self.assertNotIn("Tu referencia actual", _pdf_text(athlete))


class SingleWindowTests(unittest.TestCase):
    def _state_with_wellness(self) -> dict[str, object]:
        state = _state()
        dates = pd.date_range("2026-08-01", "2026-11-04", freq="3D")
        state["wellness_df"] = pd.DataFrame(
            [
                {"Athlete": "Alejandro Anadon", "Date": day.strftime("%Y-%m-%d"), "Sueno_hs": 6.6 if day.day % 2 else 8.0,
                 "Estres": 5, "Dolor": 3, "Wellness_Score": 20.0}
                for day in dates
            ]
        )
        return state

    def test_no_last_week_tables_in_athlete_and_client_pdf(self):
        state = self._state_with_wellness()
        for audience in ("atleta", "cliente"):
            with self.subTest(audience=audience):
                text = _pdf_text("Alejandro Anadon", audience, state)
                self.assertIn("Cómo venís aguantando", text)
                self.assertNotIn("Días con registro", text)
                self.assertNotIn("Última semana completa", text)
                self.assertNotIn("Sueño\n", text)


class EvolutionDropTests(unittest.TestCase):
    def test_anadon_flight_cmj_drop_sentence(self):
        payload = _payload("Alejandro Anadon")
        sentences = ar.evolution_drop_sentences(payload["evolution"])
        self.assertEqual(
            sentences,
            ["Tu salto CMJ (vuelo) bajó entre el 17/12/2025 y el 07/05/2026; la próxima evaluación nos dice cómo estás hoy."],
        )
        self.assertIn("la próxima evaluación nos dice cómo estás hoy", _pdf_text("Alejandro Anadon").replace("\n", " "))

    def test_no_sentence_when_it_goes_up(self):
        self.assertEqual(ar.evolution_drop_sentences(_payload("Ignacio De La Vega")["evolution"]), [])

    def test_drop_within_threshold_is_not_said(self):
        rows = [
            _row("A", "2026-09-01", ERA_INVOLUTION_STRAPS, flight_ms=600),
            _row("A", "2026-10-01", ERA_INVOLUTION_STRAPS, flight_ms=597),  # -0.5 cm < 3% TE
        ]
        series = ar.evolution_series(_prepare_jump_df(pd.DataFrame(rows)))
        self.assertEqual(ar.evolution_drop_sentences(series), [])


if __name__ == "__main__":
    unittest.main()
