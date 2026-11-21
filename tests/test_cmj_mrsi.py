"""PR #50: RSI-mod real del CMJ (CMJ_mRSI) y el "RSI" de Valkyria fuera de la literatura.

El "RSI" que exporta Valkyria (CMJ_RSI, 1.15-1.74 en datos reales) no es el
RSI-mod de la literatura (altura / tiempo hasta el despegue, ~0.4-0.6).
CMJ_mRSI = altura por tiempo de vuelo (m) / CMJ_contraction_ms (s).

Los tiempos de vuelo y contraccion de los casos se reconstruyeron para dar el
RSI-mod informado de cada toma (los crudos no estan en el repo).
"""

from __future__ import annotations

import unittest

import pandas as pd

from modules.evaluation_rules import (
    CMJ_MRSI_COLUMN,
    CMJ_RSI_VALKYRIA_LABEL,
    PLATFORM_BW_FLAG_COLUMN,
    add_cmj_mrsi,
    cmj_mrsi,
)
from modules.jump_analysis import METRIC_LABELS, _prepare_jump_df
from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_STRAPS, is_era_dependent
from modules.study_references import (
    RANKING_METRICS,
    STUDY_EMPTY,
    STUDY_METRICS,
    STUDY_REFERENCES,
    closest_study,
    study_comparison,
)
from modules.zscore_sources import REFERENCE_TABLES, context_references, lookup_reference

# (atleta, fecha, RSI Valkyria exportado o None, vuelo ms, contraccion ms, RSI-mod esperado)
CASES = (
    ("Ladetto", "2026-05-18", 1.15, 500.0, 807.0, 0.38),
    ("Ignacio", "2026-05-20", 1.73, 540.0, 550.0, 0.65),
    ("Habib", "2026-10-23", None, 520.0, 626.0, 0.53),
    ("Ignacio", "2026-10-08", None, 560.0, 487.0, 0.79),
    ("Holgado", "2026-10-22", None, 600.0, 446.0, 0.99),
)
FUTBOLISTA = {"Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Alto rendimiento"}


class CmjMrsiTest(unittest.TestCase):
    def test_cited_cases(self):
        for athlete, date, _, flight, contraction, expected in CASES:
            with self.subTest(athlete=athlete, date=date):
                self.assertAlmostEqual(cmj_mrsi(flight, contraction), expected, places=2)

    def test_valkyria_rsi_is_not_rsi_mod(self):
        for athlete, date, valkyria_rsi, flight, contraction, _ in CASES:
            if valkyria_rsi is None:
                continue
            with self.subTest(athlete=athlete, date=date):
                self.assertGreater(valkyria_rsi / cmj_mrsi(flight, contraction), 2.5)

    def test_needs_both_values(self):
        self.assertIsNone(cmj_mrsi(None, 600))
        self.assertIsNone(cmj_mrsi(500, None))
        self.assertIsNone(cmj_mrsi(500, 0))
        self.assertIsNone(cmj_mrsi(0, 600))

    def test_only_valid_platform_takes(self):
        frame = pd.DataFrame([
            {"Source": "platform", "CMJ_flight_ms": 520.0, "CMJ_contraction_ms": 626.0},
            {"Source": "nonplatform", "CMJ_flight_ms": 520.0, "CMJ_contraction_ms": 626.0},
            {"Source": "platform", "CMJ_flight_ms": 520.0, "CMJ_contraction_ms": 626.0, PLATFORM_BW_FLAG_COLUMN: "CMJ"},
            {"Source": "platform", "CMJ_flight_ms": 520.0, "CMJ_contraction_ms": None},
        ])
        values = add_cmj_mrsi(frame)[CMJ_MRSI_COLUMN].tolist()
        self.assertAlmostEqual(values[0], 0.53, places=2)
        self.assertTrue(all(pd.isna(value) for value in values[1:]))

    def test_prepared_frame_computes_it_and_drops_it_without_valid_weight(self):
        rows = []
        for athlete, date, valkyria_rsi, flight, contraction, _ in CASES:
            rows.append({"Athlete": athlete, "Date": date, "Source": "platform", "BW_kg": 75.0,
                         "CMJ_flight_ms": flight, "CMJ_contraction_ms": contraction, "CMJ_RSI": valkyria_rsi,
                         "CMJ_cm": round(9.81 * (flight / 1000) ** 2 / 8 * 100, 2),
                         "CMJ_takeoff_velocity_m_s": 2.5})
        # Toma sin peso valido: la plataforma no detecta bien el inicio del movimiento.
        rows.append({**rows[2], "Date": "2026-10-30", "BW_kg": 0.0})
        prepared = _prepare_jump_df(pd.DataFrame(rows))
        by_key = {(r["Athlete"], str(pd.Timestamp(r["Date"]).date())): r for _, r in prepared.iterrows()}
        for athlete, date, _, _, _, expected in CASES:
            with self.subTest(athlete=athlete, date=date):
                self.assertAlmostEqual(by_key[(athlete, date)][CMJ_MRSI_COLUMN], expected, places=2)
        self.assertTrue(pd.isna(by_key[("Habib", "2026-10-30")][CMJ_MRSI_COLUMN]))

    def test_era_rules_for_studies(self):
        self.assertTrue(is_era_dependent("CMJ_mRSI"))
        involution = study_comparison("CMJ_mRSI", 0.53, profile=FUTBOLISTA, source="platform", era=ERA_INVOLUTION_STRAPS)
        self.assertEqual(involution.text, "91% · Ripley 2025, fútbol semi/pro · z -0.5")
        valkyria = study_comparison("CMJ_mRSI", 0.38, profile=FUTBOLISTA, source="platform", era=ERA_VALKYRIA_STRAPS)
        self.assertEqual(valkyria.text, STUDY_EMPTY)


class ValkyriaRsiNeverAgainstLiteratureTest(unittest.TestCase):
    def test_not_in_study_references_nor_literature(self):
        self.assertNotIn("CMJ_RSI", STUDY_METRICS)
        self.assertFalse(any(entry["metric"] == "CMJ_RSI" for entry in STUDY_REFERENCES))
        self.assertFalse(any(entry["metric"] == "CMJ_RSI" for entry in REFERENCE_TABLES))
        self.assertNotIn("CMJ_RSI", [value_col for _, value_col, _ in RANKING_METRICS])

    def test_lookups_return_nothing(self):
        for sexo, deporte in (("Masculino", "Fútbol"), ("Femenino", "Handball"), ("Masculino", "Rugby League")):
            with self.subTest(deporte=deporte):
                self.assertIsNone(closest_study("CMJ_RSI", deporte=deporte, sexo=sexo))
                profile = {"Sexo": sexo, "Deporte": deporte, "Nivel": "Alto rendimiento"}
                self.assertEqual(study_comparison("CMJ_RSI", 1.4, profile=profile, era=ERA_INVOLUTION_STRAPS).text,
                                 STUDY_EMPTY)
        self.assertIsNone(lookup_reference("CMJ_RSI", deporte="Rugby League", nivel="Alto rendimiento",
                                           sexo="Masculino"))
        self.assertEqual(context_references("CMJ_RSI", deporte="Rugby", sexo="Masculino"), [])

    def test_label(self):
        self.assertEqual(METRIC_LABELS["CMJ_RSI"], "RSI (definición Valkyria)")
        self.assertEqual(CMJ_RSI_VALKYRIA_LABEL, "RSI (definición Valkyria)")


if __name__ == "__main__":
    unittest.main()
