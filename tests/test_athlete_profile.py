from __future__ import annotations

import importlib
import os
import shutil
import unittest

from modules.evaluation_sources import MIN_COHORT_SIZE
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
                    "Sexo": "F",
                    "Objetivo_primario": "Fuerza máxima",
                },
                {
                    "Athlete": "Bruno Rey",
                    "Contexto": "",
                    "Nivel": "Recreativo",
                    "Sexo": "M",
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
                    "Sexo": "F",
                    "Objetivo_primario": "Fuerza máxima",
                },
            ]
        )
        result = compute_profile_coverage(profile_df, ["Ana Lopez"])
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertEqual(result["with_complete_profile"], 1)
        self.assertTrue(result["missing_or_incomplete"].empty)


def _profile_row(athlete: str, deporte: str, nivel: str, sexo: str = "M") -> dict[str, object]:
    return {"Athlete": athlete, "Deporte": deporte, "Nivel": nivel, "Sexo": sexo}


def _jump_row(athlete: str, date: str, **extra: object) -> dict[str, object]:
    return {"Athlete": athlete, "Date": date, **extra}


class GetComparisonCohortTest(unittest.TestCase):
    """La cohorte se arma por Clase x Sexo, no por Deporte x Nivel.

    Con match exacto por deporte el mejor grupo del plantel real llegaba a 4
    atletas y ninguno alcanzaba el minimo, asi que nadie recibia z. La clave
    pasa a ser clase (deportista / poblacion general) y sexo: pierde
    especificidad de deporte y gana una muestra que existe.
    """

    def _cohort_of(self, n: int, *, nivel: str = "Competitivo", sexo: str = "M"):
        profile_df = pd.DataFrame(
            [_profile_row(f"Atleta {i}", "Handball", nivel, sexo) for i in range(n)]
        )
        jump_df = pd.DataFrame(
            [_jump_row(f"Atleta {i}", "2026-06-01", CMJ_cm=35 + i) for i in range(n)]
        )
        return get_comparison_cohort("Atleta 0", jump_df, profile_df)

    def test_clase_sexo_level_when_sample_is_sufficient(self):
        result = self._cohort_of(MIN_COHORT_SIZE)

        self.assertEqual(result["cohort_level"], "clase_sexo")
        self.assertFalse(result["is_fallback"])
        self.assertEqual(result["cohort_size"], MIN_COHORT_SIZE)
        self.assertIn("Deportistas", result["cohort_label"])
        self.assertIn("masculino", result["cohort_label"])

    def test_sport_no_longer_splits_the_cohort(self):
        """Deportes distintos al mismo nivel y sexo comparten cohorte."""
        deportes = ["Handball", "Futbol", "Rugby", "Tenis"]
        profile_df = pd.DataFrame(
            [
                _profile_row(f"Atleta {i}", deportes[i % len(deportes)], "Competitivo", "M")
                for i in range(MIN_COHORT_SIZE)
            ]
        )
        jump_df = pd.DataFrame(
            [_jump_row(f"Atleta {i}", "2026-06-01", CMJ_cm=35 + i) for i in range(MIN_COHORT_SIZE)]
        )
        result = get_comparison_cohort("Atleta 0", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "clase_sexo")
        self.assertEqual(result["cohort_size"], MIN_COHORT_SIZE)

    def test_levels_within_deportista_share_a_cohort(self):
        """Recreativo, competitivo y alto rendimiento son todos deportistas."""
        niveles = ["Recreativo", "Competitivo", "Alto rendimiento"]
        profile_df = pd.DataFrame(
            [
                _profile_row(f"Atleta {i}", "Handball", niveles[i % len(niveles)], "M")
                for i in range(MIN_COHORT_SIZE)
            ]
        )
        jump_df = pd.DataFrame(
            [_jump_row(f"Atleta {i}", "2026-06-01", CMJ_cm=35 + i) for i in range(MIN_COHORT_SIZE)]
        )
        self.assertEqual(
            get_comparison_cohort("Atleta 0", jump_df, profile_df)["cohort_size"],
            MIN_COHORT_SIZE,
        )

    def test_poblacion_general_never_mixes_with_deportistas(self):
        rows = [
            _profile_row(f"Dep {i}", "Handball", "Competitivo", "M")
            for i in range(MIN_COHORT_SIZE)
        ]
        rows.append(_profile_row("Gen 0", "", "Poblacion general", "M"))
        jump_df = pd.DataFrame(
            [_jump_row(row["Athlete"], "2026-06-01", CMJ_cm=35) for row in rows]
        )
        result = get_comparison_cohort("Gen 0", jump_df, pd.DataFrame(rows))

        self.assertEqual(result["cohort_size"], 1)
        self.assertTrue(result["is_fallback"])
        self.assertIn("Poblacion", result["cohort_label"].replace("ó", "o"))

    def test_sexes_never_share_a_cohort(self):
        rows = [
            _profile_row(f"M {i}", "Handball", "Competitivo", "M")
            for i in range(MIN_COHORT_SIZE)
        ]
        rows.append(_profile_row("F 0", "Handball", "Competitivo", "F"))
        jump_df = pd.DataFrame(
            [_jump_row(row["Athlete"], "2026-06-01", CMJ_cm=35) for row in rows]
        )
        result = get_comparison_cohort("F 0", jump_df, pd.DataFrame(rows))

        self.assertEqual(result["cohort_size"], 1)
        self.assertTrue(result["is_fallback"])
        self.assertIn("femenino", result["cohort_label"])

    def test_insufficient_sample_reports_real_size_without_enabling_z(self):
        result = self._cohort_of(MIN_COHORT_SIZE - 1)

        self.assertEqual(result["cohort_level"], "muestra_insuficiente")
        self.assertTrue(result["is_fallback"])
        self.assertEqual(result["cohort_size"], MIN_COHORT_SIZE - 1)
        self.assertIn("muestra insuficiente", result["cohort_label"].lower())

    def test_missing_sexo_leaves_the_athlete_without_cohort(self):
        result = self._cohort_of(MIN_COHORT_SIZE, sexo="no_especificado")

        self.assertEqual(result["cohort_level"], "sin_cohorte")
        self.assertEqual(result["cohort_size"], 0)
        self.assertTrue(result["cohort_df"].empty)

    def test_missing_nivel_leaves_the_athlete_without_cohort(self):
        profile_df = pd.DataFrame([_profile_row("Ana Lopez", "Handball", "", "F")])
        jump_df = pd.DataFrame([_jump_row("Ana Lopez", "2026-06-01", CMJ_cm=35)])
        result = get_comparison_cohort("Ana Lopez", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "sin_cohorte")
        self.assertIn("nivel", result["cohort_label"])

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

    def test_blank_deporte_no_longer_blocks_the_cohort(self):
        """El deporte salio de la identidad: en blanco ya no impide comparar."""
        profile_df = pd.DataFrame(
            [_profile_row(f"Atleta {i}", "", "Competitivo", "M") for i in range(MIN_COHORT_SIZE)]
        )
        jump_df = pd.DataFrame(
            [_jump_row(f"Atleta {i}", "2026-06-01", CMJ_cm=35 + i) for i in range(MIN_COHORT_SIZE)]
        )
        result = get_comparison_cohort("Atleta 0", jump_df, profile_df)

        self.assertEqual(result["cohort_level"], "clase_sexo")
        self.assertEqual(result["cohort_size"], MIN_COHORT_SIZE)

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


class DeporteNormalizationTest(unittest.TestCase):
    """El campo Deporte pasa de texto libre a lista cerrada.

    El texto abierto produjo tres grafias del mismo deporte ("Futbol",
    "Futboll", "Futbo"), que fragmentaban cualquier agrupacion por deporte en
    grupos de uno o dos. La normalizacion las unifica.
    """

    def test_futbol_spellings_collapse_into_one_sport(self):
        from modules.athlete_profile import normalize_deporte

        for variant in ("Futbol", "Futboll", "Futbo", "futbol", "FUTBOL", " Fútbol "):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_deporte(variant), "Fútbol")

    def test_listed_sports_are_canonical(self):
        from modules.athlete_profile import DEPORTE_OPTIONS, normalize_deporte

        for option in DEPORTE_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(normalize_deporte(option), option)

    def test_unlisted_sport_is_preserved_not_discarded(self):
        # Un deporte cargado por la opcion "Otro" es dato valido, no un typo.
        from modules.athlete_profile import normalize_deporte

        self.assertEqual(normalize_deporte("  Padel "), "Padel")

    def test_blank_values_resolve_to_none(self):
        from modules.athlete_profile import normalize_deporte

        for value in ("", None, float("nan"), "nan", "   "):
            with self.subTest(value=value):
                self.assertIsNone(normalize_deporte(value))

    def test_otro_option_is_offered_after_the_listed_sports(self):
        from modules.athlete_profile import (
            DEPORTE_OPTIONS,
            DEPORTE_SELECT_OPTIONS,
            OTRO_DEPORTE_OPTION,
        )

        self.assertEqual(len(DEPORTE_OPTIONS), 10)
        self.assertEqual(DEPORTE_SELECT_OPTIONS[-1], OTRO_DEPORTE_OPTION)
        self.assertNotIn(OTRO_DEPORTE_OPTION, DEPORTE_OPTIONS)
