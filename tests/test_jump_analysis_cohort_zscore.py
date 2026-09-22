from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules.jump_analysis import calc_zscores
from modules.zscore_sources import ZSource


def _profile_row(athlete: str, deporte: str, nivel: str) -> dict[str, object]:
    return {"Athlete": athlete, "Deporte": deporte, "Nivel": nivel}


def _build_two_cohort_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    # Each athlete has a single evaluation, so the personal/temporal internal
    # z-score (`_group_internal_z`, min_count=2) never has enough history and
    # the result is fully determined by the population fallback under test.
    jump_df = pd.DataFrame(
        [
            {"Athlete": "Ana Lopez", "Date": "2026-06-01", "SJ_cm": 30, "CMJ_cm": 40},
            {"Athlete": "Bruno Rey", "Date": "2026-06-01", "SJ_cm": 32, "CMJ_cm": 41},
            {"Athlete": "Caro Diaz", "Date": "2026-06-01", "SJ_cm": 34, "CMJ_cm": 42},
            {"Athlete": "Dario Sosa", "Date": "2026-06-01", "SJ_cm": 20, "CMJ_cm": 35},
            {"Athlete": "Emi Paz", "Date": "2026-06-01", "SJ_cm": 22, "CMJ_cm": 36},
            {"Athlete": "Flor Vega", "Date": "2026-06-01", "SJ_cm": 24, "CMJ_cm": 37},
        ]
    )
    profile_df = pd.DataFrame(
        [
            _profile_row("Ana Lopez", "Handball", "Competitivo"),
            _profile_row("Bruno Rey", "Handball", "Competitivo"),
            _profile_row("Caro Diaz", "Handball", "Competitivo"),
            _profile_row("Dario Sosa", "Futbol", "Recreativo"),
            _profile_row("Emi Paz", "Futbol", "Recreativo"),
            _profile_row("Flor Vega", "Futbol", "Recreativo"),
        ]
    )
    return jump_df, profile_df


def _expected_z(values: list[float], target: float) -> float:
    arr = np.array(values, dtype=float)
    return round(float((target - arr.mean()) / arr.std(ddof=0)), 2)


def build_valid_cohort_frames() -> tuple[pd.DataFrame, pd.DataFrame, list[float]]:
    """Cohorte que si habilita un z: mismo deporte, nivel y sexo, sobre el minimo.

    Los fixtures chicos de este modulo existen para probar que el gate NIEGA
    el z. Cuando hace falta lo contrario (verificar que `profile_df` se
    propaga hasta los graficos, por ejemplo) hay que partir de una poblacion
    admisible, porque si no el z es NaN por diseno y el test no distingue
    entre "gate correcto" y "profile_df perdido en el camino".
    """
    from modules.athlete_profile import Sexo
    from modules.zscore_sources import MIN_COHORT_SIZE

    heights = [30.0 + idx for idx in range(MIN_COHORT_SIZE)]
    jump_rows, profile_rows = [], []
    for idx, height in enumerate(heights):
        name = f"Cohorte {idx}"
        jump_rows.append(
            {"Athlete": name, "Date": "2026-06-01", "SJ_cm": height, "CMJ_cm": height + 8.0}
        )
        profile_rows.append(
            {"Athlete": name, "Deporte": "Handball", "Nivel": "Competitivo", "Sexo": Sexo.FEMENINO}
        )
    return pd.DataFrame(jump_rows), pd.DataFrame(profile_rows), heights


class CalcZscoresCohortTest(unittest.TestCase):
    """Cohorte como unica poblacion admisible para un z poblacional.

    Este fixture arma cohortes de 3 atletas y sin sexo cargado. Bajo el gate
    vigente eso no alcanza para ningun z: ni literatura (no hay sexo, no hay
    tabla) ni cohorte (3 < minimo). Los tests que antes verificaban el
    fallback al dataset entero ahora verifican que ese fallback no exista.
    """

    def test_small_cohort_never_produces_a_cohort_z(self):
        jump_df, profile_df = _build_two_cohort_frames()
        result = calc_zscores(jump_df.copy(), profile_df=profile_df)

        self.assertNotIn(str(ZSource.COHORT_Z), set(result["SJ_Z_source"]))
        self.assertTrue(result["SJ_Z"].isna().all())

    def test_without_profile_df_there_is_no_population_at_all(self):
        jump_df, _profile_df = _build_two_cohort_frames()
        result = calc_zscores(jump_df.copy())

        self.assertEqual(set(result["SJ_Z_source"]), {str(ZSource.REFERENCE_BAND)})
        self.assertTrue(result["SJ_Z"].isna().all())

    def test_metric_without_applicable_population_gets_no_z(self):
        """Los perfiles del fixture no traen sexo: no hay tabla que elegir."""
        jump_df, profile_df = _build_two_cohort_frames()
        with_profile = calc_zscores(jump_df.copy(), profile_df=profile_df)

        self.assertNotIn(str(ZSource.LITERATURE_Z), set(with_profile["CMJ_Z_source"]))

    def test_cohort_above_minimum_does_produce_a_cohort_z(self):
        """Control: el camino de cohorte sigue vivo cuando la muestra alcanza."""
        from modules.athlete_profile import Sexo
        from modules.zscore_sources import MIN_COHORT_SIZE

        rows, profiles = [], []
        for idx in range(MIN_COHORT_SIZE):
            name = f"Atleta {idx}"
            rows.append({"Athlete": name, "Date": "2026-06-01", "SJ_cm": 30 + idx})
            profiles.append(
                {"Athlete": name, "Deporte": "Handball", "Nivel": "Competitivo", "Sexo": Sexo.FEMENINO}
            )

        result = calc_zscores(pd.DataFrame(rows), profile_df=pd.DataFrame(profiles))
        self.assertEqual(set(result["SJ_Z_source"]), {str(ZSource.COHORT_Z)})
        self.assertTrue(result["SJ_Z"].notna().all())


if __name__ == "__main__":
    unittest.main()
