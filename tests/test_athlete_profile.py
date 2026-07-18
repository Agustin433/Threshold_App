from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from modules.athlete_profile import (
    OBJETIVO_OPTIONS,
    get_comparison_cohort,
    parse_secondary_objectives,
    secondary_objective_options,
    serialize_secondary_objectives,
    suggest_objective_from_text,
    validate_profile_fields,
)
from modules.data_quality import compute_profile_coverage

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_athlete_profile"


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = None
    try:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_root = TEST_TMP_ROOT / f"profile_{uuid.uuid4().hex[:8]}"
        tmp_root.mkdir(parents=True, exist_ok=True)
        store_dir = tmp_root / "store"
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        import local_store as local_store_module

        local_store_module = importlib.reload(local_store_module)
        local_store_module.LEGACY_STORE_DIR = tmp_root / "legacy-default"
        yield local_store_module, tmp_root
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        if TEST_TMP_ROOT.exists() and not any(TEST_TMP_ROOT.iterdir()):
            TEST_TMP_ROOT.rmdir()
        import local_store as local_store_module

        importlib.reload(local_store_module)


class UpsertAthleteProfileTest(unittest.TestCase):
    def test_upsert_creates_new_profile(self):
        with isolated_store() as (local_store, _tmp_root):
            merged = local_store.upsert_athlete_profile(
                {
                    "Athlete": "ana lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                    "Peso_kg": 60.0,
                }
            )

            self.assertEqual(len(merged), 1)
            self.assertEqual(merged["Athlete"].iloc[0], "Ana Lopez")
            self.assertEqual(merged["Contexto"].iloc[0], "Club")
            self.assertEqual(merged["Peso_kg"].iloc[0], 60.0)

            reloaded = local_store.read_full_dataset("athlete_profile_df")
            self.assertEqual(len(reloaded), 1)

    def test_upsert_edits_same_athlete_without_duplicating_and_clears_fields(self):
        with isolated_store() as (local_store, _tmp_root):
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                    "Peso_kg": 60.0,
                    "Deporte": "Handball",
                }
            )

            # Segunda edicion del mismo atleta: cambia Contexto y borra Deporte/Peso.
            merged = local_store.upsert_athlete_profile(
                {
                    "Athlete": "ana lopez",
                    "Contexto": "Gimnasio",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Hipertrofia",
                    "Peso_kg": None,
                    "Deporte": None,
                }
            )

            self.assertEqual(len(merged), 1, "no debe duplicar la fila del mismo atleta")
            row = merged.iloc[0]
            self.assertEqual(row["Contexto"], "Gimnasio")
            self.assertEqual(row["Objetivo_primario"], "Hipertrofia")
            self.assertTrue(pd.isna(row["Peso_kg"]), "el campo borrado no debe conservar el valor viejo")
            self.assertTrue(pd.isna(row["Deporte"]), "el campo borrado no debe conservar el valor viejo")

    def test_upsert_requires_athlete_name(self):
        with isolated_store() as (local_store, _tmp_root):
            with self.assertRaises(ValueError):
                local_store.upsert_athlete_profile({"Contexto": "Club"})

    def test_load_recent_state_keeps_old_profiles_outside_six_week_window(self):
        with isolated_store() as (local_store, _tmp_root):
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                }
            )
            # Simula un perfil desactualizado hace mas de 6 semanas escribiendo el CSV directo.
            profile_path = local_store.STORE_DIR / "athlete_profiles.csv"
            old_df = pd.read_csv(profile_path)
            old_df["Fecha_actualizacion"] = "2020-01-01"
            old_df.to_csv(profile_path, index=False)

            state = local_store.load_recent_state(weeks=6)
            self.assertIsNotNone(state.get("athlete_profile_df"))
            self.assertEqual(len(state["athlete_profile_df"]), 1)


class ValidateProfileFieldsTest(unittest.TestCase):
    def test_valid_profile_has_no_errors(self):
        errors = validate_profile_fields(
            {
                "Athlete": "Ana Lopez",
                "Contexto": "Club",
                "Nivel": "Competitivo",
                "Objetivo_primario": "Fuerza máxima",
            }
        )
        self.assertEqual(errors, [])

    def test_missing_required_fields_are_reported(self):
        errors = validate_profile_fields({"Athlete": "", "Contexto": "", "Nivel": "", "Objetivo_primario": ""})
        self.assertEqual(len(errors), 4)

    def test_missing_objetivo_primario_only(self):
        errors = validate_profile_fields(
            {"Athlete": "Ana Lopez", "Contexto": "Club", "Nivel": "Competitivo", "Objetivo_primario": None}
        )
        self.assertEqual(errors, ["Objetivo primario es obligatorio."])


class SuggestObjectiveFromTextTest(unittest.TestCase):
    def test_matches_case_insensitive_keyword(self):
        self.assertEqual(
            suggest_objective_from_text("quiere Mejorar el SPRINT para la temporada"),
            "Rendimiento deportivo específico",
        )

    def test_matches_rtp_keyword(self):
        self.assertEqual(
            suggest_objective_from_text("viene de una cirugia y quiere volver a jugar"),
            "Rehabilitación y retorno deportivo (RTP)",
        )

    def test_no_match_returns_none(self):
        self.assertIsNone(suggest_objective_from_text("le gusta entrenar los martes"))

    def test_empty_text_returns_none(self):
        self.assertIsNone(suggest_objective_from_text(""))
        self.assertIsNone(suggest_objective_from_text(None))


class SecondaryObjectivesHelpersTest(unittest.TestCase):
    def test_secondary_options_exclude_primary(self):
        options = secondary_objective_options("Fuerza máxima")
        self.assertNotIn("Fuerza máxima", options)
        self.assertEqual(len(options), len(OBJETIVO_OPTIONS) - 1)

    def test_serialize_and_parse_round_trip(self):
        values = ["Hipertrofia", "Resistencia física"]
        serialized = serialize_secondary_objectives(values)
        self.assertEqual(parse_secondary_objectives(serialized), values)

    def test_parse_blank_value_returns_empty_list(self):
        self.assertEqual(parse_secondary_objectives(None), [])
        self.assertEqual(parse_secondary_objectives(float("nan")), [])


class ComputeProfileCoverageTest(unittest.TestCase):
    def test_zero_coverage_when_no_profiles_exist(self):
        result = compute_profile_coverage(pd.DataFrame(), ["Ana Lopez", "Bruno Rey"])
        self.assertEqual(result["coverage_pct"], 0.0)
        self.assertEqual(result["total_athletes"], 2)
        self.assertEqual(result["with_complete_profile"], 0)
        self.assertEqual(len(result["missing_or_incomplete"]), 2)
        self.assertTrue((result["missing_or_incomplete"]["Tiene perfil"] == "No").all())

    def test_partial_coverage_flags_incomplete_rows(self):
        profile_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                },
                {
                    "Athlete": "Bruno Rey",
                    "Contexto": "",
                    "Nivel": "Recreativo",
                    "Objetivo_primario": "Hipertrofia",
                },
            ]
        )
        result = compute_profile_coverage(profile_df, ["Ana Lopez", "Bruno Rey", "Caro Diaz"])
        self.assertEqual(result["total_athletes"], 3)
        self.assertEqual(result["with_complete_profile"], 1)
        self.assertAlmostEqual(result["coverage_pct"], 33.3, places=1)
        missing_names = set(result["missing_or_incomplete"]["Atleta"])
        self.assertEqual(missing_names, {"Bruno Rey", "Caro Diaz"})

    def test_full_coverage_when_all_profiles_complete(self):
        profile_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                },
            ]
        )
        result = compute_profile_coverage(profile_df, ["Ana Lopez"])
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertEqual(result["with_complete_profile"], 1)
        self.assertTrue(result["missing_or_incomplete"].empty)


def _profile_row(athlete: str, deporte: str, nivel: str) -> dict[str, object]:
    return {"Athlete": athlete, "Deporte": deporte, "Nivel": nivel}


def _jump_row(athlete: str, date: str, **extra: object) -> dict[str, object]:
    return {"Athlete": athlete, "Date": date, **extra}


class GetComparisonCohortTest(unittest.TestCase):
    def test_deporte_nivel_level_when_sample_is_sufficient(self):
        profile_df = pd.DataFrame(
            [
                _profile_row("Ana Lopez", "Handball", "Competitivo"),
                _profile_row("Bruno Rey", "Handball", "Competitivo"),
                _profile_row("Caro Diaz", "Handball", "Competitivo"),
                _profile_row("Dario Sosa", "Handball", "Competitivo"),
                _profile_row("Emi Paz", "Futbol", "Recreativo"),
            ]
        )
        jump_df = pd.DataFrame(
            [
                _jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35),
                _jump_row("Bruno Rey", "2026-06-01", CMJ_cm=40),
                _jump_row("Caro Diaz", "2026-06-01", CMJ_cm=38),
                _jump_row("Dario Sosa", "2026-06-01", CMJ_cm=42),
                _jump_row("Emi Paz", "2026-06-01", CMJ_cm=30),
            ]
        )
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "deporte_nivel")
        self.assertFalse(result["is_fallback"])
        self.assertEqual(result["cohort_size"], 4)
        self.assertIn("Handball", result["cohort_label"])
        self.assertIn("Competitivo", result["cohort_label"])
        self.assertEqual(set(result["cohort_df"]["Athlete"]), {"Ana Lopez", "Bruno Rey", "Caro Diaz", "Dario Sosa"})

    def test_falls_back_to_nivel_when_deporte_nivel_sample_too_small(self):
        profile_df = pd.DataFrame(
            [
                _profile_row("Ana Lopez", "Handball", "Competitivo"),
                _profile_row("Bruno Rey", "Futbol", "Competitivo"),
                _profile_row("Caro Diaz", "Running", "Competitivo"),
                _profile_row("Dario Sosa", "Futbol", "Recreativo"),
            ]
        )
        jump_df = pd.DataFrame(
            [
                _jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35),
                _jump_row("Bruno Rey", "2026-06-01", CMJ_cm=40),
                _jump_row("Caro Diaz", "2026-06-01", CMJ_cm=38),
                _jump_row("Dario Sosa", "2026-06-01", CMJ_cm=32),
            ]
        )
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "nivel")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["cohort_size"], 3)
        self.assertIn("Competitivo", result["cohort_label"])
        self.assertEqual(set(result["cohort_df"]["Athlete"]), {"Ana Lopez", "Bruno Rey", "Caro Diaz"})

    def test_general_fallback_when_even_nivel_sample_is_too_small(self):
        profile_df = pd.DataFrame(
            [
                _profile_row("Ana Lopez", "Handball", "Competitivo"),
                _profile_row("Bruno Rey", "Futbol", "Competitivo"),
                _profile_row("Caro Diaz", "Running", "Recreativo"),
            ]
        )
        jump_df = pd.DataFrame(
            [
                _jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35),
                _jump_row("Bruno Rey", "2026-06-01", CMJ_cm=40),
                _jump_row("Caro Diaz", "2026-06-01", CMJ_cm=38),
            ]
        )
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "general")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["cohort_size"], 2)
        self.assertIn("Muestra insuficiente", result["cohort_label"])
        self.assertEqual(set(result["cohort_df"]["Athlete"]), {"Ana Lopez", "Bruno Rey", "Caro Diaz"})

    def test_general_fallback_when_profile_missing(self):
        profile_df = pd.DataFrame([_profile_row("Bruno Rey", "Handball", "Competitivo")])
        jump_df = pd.DataFrame(
            [
                _jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35),
                _jump_row("Bruno Rey", "2026-06-01", CMJ_cm=40),
            ]
        )
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "general")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["cohort_label"], "Comparación general — perfil incompleto")
        self.assertEqual(set(result["cohort_df"]["Athlete"]), {"Ana Lopez", "Bruno Rey"})

    def test_general_fallback_when_deporte_or_nivel_blank(self):
        profile_df = pd.DataFrame([_profile_row("Ana Lopez", "", "Competitivo")])
        jump_df = pd.DataFrame([_jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35)])
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "general")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["cohort_label"], "Comparación general — perfil incompleto")

    def test_none_or_empty_inputs_do_not_raise(self):
        self.assertEqual(get_comparison_cohort("Ana Lopez", None, None)["cohort_level"], "general")
        self.assertTrue(get_comparison_cohort("Ana Lopez", None, None)["cohort_df"].empty)
        self.assertEqual(get_comparison_cohort("Ana Lopez", pd.DataFrame(), pd.DataFrame())["cohort_level"], "general")

        jump_df = pd.DataFrame([_jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35)])
        result = get_comparison_cohort("Ana Lopez", jump_df, None)
        self.assertEqual(result["cohort_level"], "general")
        self.assertTrue(result["is_fallback"])
        self.assertTrue(result["cohort_df"].equals(jump_df))


if __name__ == "__main__":
    unittest.main()
