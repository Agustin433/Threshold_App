"""PR #50: RSI-mod real del CMJ (CMJ_mRSI) y el "RSI" de Valkyria fuera de la literatura.

El "RSI" que exporta Valkyria (CMJ_RSI, 1.15-1.74 en datos reales) no es el
RSI-mod de la literatura (altura / tiempo hasta el despegue, ~0.4-0.6).
CMJ_mRSI = altura por impulso-momento (CMJ_cm, m) / CMJ_contraction_ms (s),
solo en tomas validas de la era involution_straps (mismo metodo de altura que
McMahon, Ripley y Radovic).

Tomas Involution: valores reales (vuelo, contraccion y CMJ exportados).
Tomas Valkyria: el RSI exportado es real; altura y contraccion son
ilustrativas, porque en esa era el RSI-mod no se calcula nunca.
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

# Tomas reales de Involution: (atleta, fecha, vuelo ms, contraccion ms, CMJ cm, RSI-mod)
INVOLUTION_CASES = (
    ("Habib", "2026-10-23", 499.0, 578.0, 30.44, 0.53),
    ("Ignacio", "2026-10-08", 614.0, 583.0, 46.04, 0.79),
    ("Holgado", "2026-10-22", 648.0, 520.0, 51.32, 0.99),
)
# Tomas Valkyria con straps: (atleta, fecha, RSI exportado por Valkyria, contraccion ms, CMJ cm)
VALKYRIA_CASES = (
    ("Ignacio", "2026-05-20", 1.73, 550.0, 39.0),
    ("Ladetto", "2026-05-18", 1.15, 800.0, 33.0),
)
FUTBOLISTA = {"Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Alto rendimiento"}


def _row(athlete, date, contraction, cmj, **extra):
    return {"Athlete": athlete, "Date": date, "Source": "platform", "BW_kg": 75.0,
            "CMJ_contraction_ms": contraction, "CMJ_cm": cmj, "CMJ_takeoff_velocity_m_s": 2.5, **extra}


class CmjMrsiTest(unittest.TestCase):
    def test_real_involution_cases(self):
        for athlete, date, _, contraction, cmj, expected in INVOLUTION_CASES:
            with self.subTest(athlete=athlete, date=date):
                self.assertEqual(round(cmj_mrsi(cmj, contraction), 2), expected)

    def test_uses_impulse_height_not_flight_height(self):
        # Ignacio 08/10: por vuelo serian 46.23 cm; la altura usada es la de
        # impulso-momento (46.04 cm), el metodo de los estudios.
        frame = pd.DataFrame([_row("Ignacio", "2026-10-08", 583.0, 46.04, CMJ_flight_ms=614.0)])
        self.assertAlmostEqual(add_cmj_mrsi(frame)[CMJ_MRSI_COLUMN].iloc[0], 0.4604 / 0.583, places=3)

    def test_needs_both_values(self):
        self.assertIsNone(cmj_mrsi(None, 600))
        self.assertIsNone(cmj_mrsi(30.0, None))
        self.assertIsNone(cmj_mrsi(30.0, 0))
        self.assertIsNone(cmj_mrsi(0, 600))

    def test_only_valid_involution_platform_takes(self):
        frame = pd.DataFrame([
            _row("Habib", "2026-10-23", 578.0, 30.44),
            {**_row("Habib", "2026-10-23", 578.0, 30.44), "Source": "nonplatform"},
            _row("Habib", "2026-10-23", 578.0, 30.44, **{PLATFORM_BW_FLAG_COLUMN: "CMJ"}),
            _row("Habib", "2026-10-23", None, 30.44),
            _row("Ladetto", "2026-05-18", 800.0, 33.0),
            _row("Ladetto", "2026-10-23", 800.0, 33.0, Device="valkyria_straps"),
        ])
        values = add_cmj_mrsi(frame)[CMJ_MRSI_COLUMN].tolist()
        self.assertEqual(round(values[0], 2), 0.53)
        self.assertTrue(all(pd.isna(value) for value in values[1:]))

    def test_prepared_frame_real_cases_and_valkyria_dash(self):
        rows = [_row(a, d, c, h, CMJ_flight_ms=f) for a, d, f, c, h, _ in INVOLUTION_CASES]
        rows += [_row(a, d, c, h, CMJ_RSI=rsi) for a, d, rsi, c, h in VALKYRIA_CASES]
        # Toma Involution sin peso valido: fuera.
        rows.append({**rows[0], "Date": "2026-10-30", "BW_kg": 0.0})
        prepared = _prepare_jump_df(pd.DataFrame(rows))
        by_key = {(r["Athlete"], str(pd.Timestamp(r["Date"]).date())): r for _, r in prepared.iterrows()}
        for athlete, date, _, _, _, expected in INVOLUTION_CASES:
            with self.subTest(athlete=athlete, date=date):
                self.assertEqual(round(float(by_key[(athlete, date)][CMJ_MRSI_COLUMN]), 2), expected)
        self.assertTrue(pd.isna(by_key[("Habib", "2026-10-30")][CMJ_MRSI_COLUMN]))
        for athlete, date, rsi, _, _ in VALKYRIA_CASES:
            with self.subTest(athlete=athlete, date=date):
                row = by_key[(athlete, date)]
                self.assertTrue(pd.isna(row[CMJ_MRSI_COLUMN]))
                self.assertAlmostEqual(float(row["CMJ_RSI"]), rsi)
                comparison = study_comparison("CMJ_mRSI", row[CMJ_MRSI_COLUMN], profile=FUTBOLISTA,
                                              source="platform", era=ERA_VALKYRIA_STRAPS)
                self.assertEqual(comparison.text, STUDY_EMPTY)

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
