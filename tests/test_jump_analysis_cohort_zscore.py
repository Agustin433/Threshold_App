from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules.jump_analysis import EXTERNAL_BENCHMARKS, calc_zscores


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


class CalcZscoresCohortTest(unittest.TestCase):
    def test_without_profile_df_matches_whole_dataset_population(self):
        jump_df, _profile_df = _build_two_cohort_frames()
        result = calc_zscores(jump_df.copy())

        all_sj = [30, 32, 34, 20, 22, 24]
        expected_ana = _expected_z(all_sj, 30)
        actual_ana = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        self.assertAlmostEqual(actual_ana, expected_ana, places=2)

    def test_with_profile_df_scores_each_athlete_against_its_own_cohort(self):
        jump_df, profile_df = _build_two_cohort_frames()
        result = calc_zscores(jump_df.copy(), profile_df=profile_df)

        handball_sj = [30, 32, 34]
        futbol_sj = [20, 22, 24]

        expected_ana = _expected_z(handball_sj, 30)
        expected_dario = _expected_z(futbol_sj, 20)

        actual_ana = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        actual_dario = result.loc[result["Athlete"] == "Dario Sosa", "SJ_Z"].iloc[0]

        self.assertAlmostEqual(actual_ana, expected_ana, places=2)
        self.assertAlmostEqual(actual_dario, expected_dario, places=2)

        # Sanity: the cohort-scoped value must differ from the whole-dataset value.
        whole_dataset_ana = _expected_z([30, 32, 34, 20, 22, 24], 30)
        self.assertNotAlmostEqual(actual_ana, whole_dataset_ana, places=2)

    def test_external_benchmark_metric_is_unaffected_by_profile_df(self):
        jump_df, profile_df = _build_two_cohort_frames()

        without_profile = calc_zscores(jump_df.copy())
        with_profile = calc_zscores(jump_df.copy(), profile_df=profile_df)

        benchmark = EXTERNAL_BENCHMARKS["CMJ_cm"]
        expected_cmj_z = round((40 - benchmark["mean"]) / benchmark["sd"], 2)

        cmj_without = without_profile.loc[without_profile["Athlete"] == "Ana Lopez", "CMJ_Z"].iloc[0]
        cmj_with = with_profile.loc[with_profile["Athlete"] == "Ana Lopez", "CMJ_Z"].iloc[0]

        self.assertAlmostEqual(cmj_without, expected_cmj_z, places=2)
        self.assertAlmostEqual(cmj_with, expected_cmj_z, places=2)
        self.assertAlmostEqual(cmj_without, cmj_with, places=2)

    def test_empty_or_none_profile_df_falls_back_to_dataset_population(self):
        jump_df, _profile_df = _build_two_cohort_frames()

        result_none = calc_zscores(jump_df.copy(), profile_df=None)
        result_empty = calc_zscores(jump_df.copy(), profile_df=pd.DataFrame())

        all_sj = [30, 32, 34, 20, 22, 24]
        expected_ana = _expected_z(all_sj, 30)

        for result in (result_none, result_empty):
            actual = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
            self.assertAlmostEqual(actual, expected_ana, places=2)


if __name__ == "__main__":
    unittest.main()
