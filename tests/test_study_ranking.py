"""PR R: columna "vs estudios" del ranking de Equipo, separada del z de gimnasio."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

import pandas as pd

from modules.measurement_eras import ERA_INVOLUTION_STRAPS, ERA_VALKYRIA_STRAPS
from modules.study_references import (
    COL_ATHLETE,
    COL_GYM_Z,
    COL_STUDIES,
    STUDY_EMPTY,
    STUDY_LEGEND,
    STUDY_REFERENCES,
    build_ranking_table,
    closest_study,
    study_comparison,
)
from modules.zscore_sources import REFERENCE_TABLES

ROOT = Path(__file__).resolve().parents[1]
APP_PY = ROOT / "app.py"
TMP_ROOT = ROOT / "tests" / ".tmp_study_ranking"

FUTBOLISTA = {"Sexo": "Masculino", "Deporte": "Fútbol", "Nivel": "Alto rendimiento"}
HANDBOLISTA = {"Sexo": "Femenino", "Deporte": "Handball", "Nivel": "Alto rendimiento"}
TENISTA = {"Sexo": "Masculino", "Deporte": "Tenis", "Nivel": "Competitivo"}


def _cmp(metric, value, profile, **kwargs):
    kwargs.setdefault("source", "platform")
    kwargs.setdefault("era", ERA_INVOLUTION_STRAPS)
    return study_comparison(metric, value, profile=profile, **kwargs)


class StudyComparisonTest(unittest.TestCase):
    def test_futbolista_against_ripley_with_z_when_population_matches(self):
        result = _cmp("CMJ_cm", 33.5, FUTBOLISTA)
        self.assertEqual(result.text, "87% · Ripley 2025, fútbol semi/pro · z -0.9")
        self.assertAlmostEqual(result.z, (33.5 - 38.5) / 5.5)
        rsi = _cmp("CMJ_RSI", 0.58, FUTBOLISTA)
        self.assertEqual(rsi.text, "100% · Ripley 2025, fútbol semi/pro · z +0.0")

    def test_futbolista_of_another_level_gets_context_without_z(self):
        result = _cmp("CMJ_cm", 33.5, {**FUTBOLISTA, "Nivel": "Competitivo"})
        self.assertEqual(result.text, "87% · Ripley 2025, fútbol semi/pro")
        self.assertIsNone(result.z)

    def test_handbolista_against_radovic(self):
        result = _cmp("CMJ_cm", 30.0, HANDBOLISTA)
        self.assertEqual(result.text, "112% · Radovic 2024, handball pro fem. · z +0.8")
        rsi = _cmp("CMJ_RSI", 0.376, {**HANDBOLISTA, "Nivel": "Recreativo"})
        self.assertEqual(rsi.text, "100% · Radovic 2024, handball pro fem.")

    def test_athlete_without_table_gets_a_dash(self):
        for profile in (TENISTA, {"Sexo": "Femenino", "Deporte": "Running", "Nivel": "Recreativo"},
                        {"Sexo": "", "Deporte": "Fútbol", "Nivel": "Alto rendimiento"}, {}):
            with self.subTest(profile=profile):
                result = _cmp("CMJ_cm", 35.0, profile)
                self.assertEqual(result.text, STUDY_EMPTY)
                self.assertIsNone(result.pct)

    def test_imtp_has_no_literature_column(self):
        for metric in ("IMTP_relPF", "IMTP_N", "SJ_cm", "DRI"):
            with self.subTest(metric=metric):
                self.assertEqual(_cmp(metric, 40.0, FUTBOLISTA).text, STUDY_EMPTY)
        self.assertFalse(any(str(entry["metric"]).startswith("IMTP") for entry in STUDY_REFERENCES))

    def test_closest_table_by_demand_group_and_sex(self):
        # Futbolista mujer: no hay futbol femenino; mismo grupo y sexo -> Radovic.
        self.assertEqual(closest_study("CMJ_cm", deporte="Fútbol", sexo="Femenino")["cite"],
                         "Radovic 2024, handball pro fem.")
        # Handball varon: grupo de equipo, varones; mayor n -> Ripley (76) sobre McMahon (66).
        self.assertEqual(closest_study("CMJ_cm", deporte="Handball", sexo="Masculino")["cite"],
                         "Ripley 2025, fútbol semi/pro")
        # Rugby: mismo deporte antes que el grupo.
        self.assertTrue(closest_study("CMJ_cm", deporte="Rugby", sexo="Masculino")["cite"].startswith("McMahon 2022"))

    def test_other_instrument_or_era_is_not_compared(self):
        self.assertEqual(_cmp("CMJ_cm", 33.5, FUTBOLISTA, source="nonplatform").text, STUDY_EMPTY)
        valkyria = _cmp("CMJ_cm", 33.5, FUTBOLISTA, era=ERA_VALKYRIA_STRAPS)
        self.assertEqual(valkyria.text, STUDY_EMPTY)
        self.assertTrue(valkyria.not_comparable)

    def test_mcmahon_values_match_the_literature_table(self):
        published = {(e["metric"], e["subgroup"]): (e["mean"], e["sd"], e["n"])
                     for e in REFERENCE_TABLES if e["metric"] in {"CMJ_cm", "CMJ_RSI"}}
        for entry in STUDY_REFERENCES:
            if entry["cite"].startswith("McMahon"):
                with self.subTest(entry=entry["cite"], metric=entry["metric"]):
                    self.assertEqual(published[(entry["metric"], entry["subgroup"])],
                                     (entry["mean"], entry["sd"], entry["n"]))


class RankingTableTest(unittest.TestCase):
    def test_sorted_only_by_gym_z_never_by_studies(self):
        latest = pd.DataFrame([
            # La handbolista tiene el % de estudio mas alto pero el z de gimnasio mas bajo.
            {"Athlete": "Hanna", "CMJ_cm": 34.0, "CMJ_Z": -1.0, "CMJ_Z_source": "cohort_z", "Source": "platform", "Date": "2026-11-01"},
            {"Athlete": "Fede", "CMJ_cm": 36.0, "CMJ_Z": 1.2, "CMJ_Z_source": "cohort_z", "Source": "platform", "Date": "2026-11-01"},
            {"Athlete": "Tomas", "CMJ_cm": 35.0, "CMJ_Z": 0.3, "CMJ_Z_source": "cohort_z", "Source": "platform", "Date": "2026-11-01"},
            # z vs literatura (no de cohorte): no es z gimnasio, va al fondo sin z.
            {"Athlete": "Luis", "CMJ_cm": 40.0, "CMJ_Z": 2.0, "CMJ_Z_source": "literature_z", "Source": "platform", "Date": "2026-11-01"},
        ])
        lookup = {"Hanna": HANDBOLISTA, "Fede": FUTBOLISTA, "Tomas": TENISTA, "Luis": FUTBOLISTA}
        table, not_comparable = build_ranking_table(latest, "CMJ_cm", "CMJ_Z", profile_lookup=lookup)
        self.assertEqual(table[COL_ATHLETE].tolist(), ["Fede", "Tomas", "Hanna", "Luis"])
        self.assertTrue(pd.isna(table.loc[3, COL_GYM_Z]))
        self.assertEqual(table[COL_STUDIES].tolist(), [
            "94% · Ripley 2025, fútbol semi/pro · z -0.5",
            STUDY_EMPTY,
            "127% · Radovic 2024, handball pro fem. · z +1.8",
            "104% · Ripley 2025, fútbol semi/pro · z +0.3",
        ])
        self.assertFalse(not_comparable)


def _titles(at) -> list[str]:
    return [str(item.value) for item in at.markdown]


class StudyRankingAppTest(unittest.TestCase):
    """Equipo > Rankings con un futbolista, una handbolista y un tenista (sin tabla)."""

    def test_rankings_tab_shows_both_columns_and_legend(self):
        from streamlit.testing.v1 import AppTest

        original = os.environ.get("THRESHOLD_STORE_DIR")
        tmp = TMP_ROOT / uuid.uuid4().hex[:8]
        store = tmp / "store"
        store.mkdir(parents=True)
        try:
            os.environ["THRESHOLD_STORE_DIR"] = str(store)
            sys.path.insert(0, str(ROOT / "scripts"))
            try:
                import benchmark_views
            finally:
                sys.path.pop(0)
            benchmark_views.seed_store(
                store, n_athletes=16, days_back=120, raw_rows=None, maxes_rows=60, flight_times=True
            )
            import local_store

            local_store = importlib.reload(local_store)
            athletes = benchmark_views._athletes()[:3]
            for athlete, profile in zip(athletes, (FUTBOLISTA, HANDBOLISTA, TENISTA)):
                local_store.upsert_athlete_profile({
                    "Athlete": athlete, "Contexto": "Club", "Objetivo_primario": "Fuerza máxima",
                    "Es_RTP": False, **profile,
                })

            at = AppTest.from_file(str(APP_PY), default_timeout=300).run()
            next(bg for bg in at.button_group if bg.label == "Vista principal").set_value("Equipo").run()
            at.session_state["equipo_tab"] = "Rankings"
            at.run()
            self.assertFalse(at.exception, at.exception)
            self.assertIn(STUDY_LEGEND, [str(item.value) for item in at.caption])
            tables = [df.value for df in at.dataframe if COL_STUDIES in list(df.value.columns)]
            self.assertEqual(len(tables), 1)
            table = tables[0]
            self.assertEqual(list(table.columns), [COL_ATHLETE, "Valor", COL_GYM_Z, COL_STUDIES])
            gym_z = pd.to_numeric(table[COL_GYM_Z], errors="coerce").dropna().tolist()
            self.assertEqual(gym_z, sorted(gym_z, reverse=True))
            studies = dict(zip(table[COL_ATHLETE], table[COL_STUDIES]))
            futbolista, handbolista, tenista = athletes
            self.assertRegex(studies[futbolista], r"^\d+% · Ripley 2025, fútbol semi/pro · z [+-]\d\.\d$")
            self.assertRegex(studies[handbolista], r"^\d+% · Radovic 2024, handball pro fem\. · z [+-]\d\.\d$")
            self.assertEqual(studies[tenista], STUDY_EMPTY)

            # IMTP: sin columna de literatura, todo "-".
            next(sb for sb in at.selectbox if sb.key == "team_study_ranking_metric").set_value(
                "IMTP relativo (N/kg)").run()
            self.assertFalse(at.exception, at.exception)
            tables = [df.value for df in at.dataframe if COL_STUDIES in list(df.value.columns)]
            self.assertEqual(set(tables[0][COL_STUDIES]), {STUDY_EMPTY})
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp, ignore_errors=True)
            if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
                TMP_ROOT.rmdir()


if __name__ == "__main__":
    unittest.main()
