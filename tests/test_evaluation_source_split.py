"""Aislamiento entre evaluaciones de plataforma y de no-plataforma.

Una plataforma de fuerza estima la altura por impulso-momento; MyJump2 y las
alfombras la derivan del tiempo de vuelo. El sesgo entre metodos no es
constante, asi que mezclarlos produce senales falsas de cambio. Estos tests
fijan los cuatro puntos donde el cruce ocurriria si nadie lo impide:
persistencia, z-scores, baselines y benchmarks externos.
"""

from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from modules.evaluation_sources import (
    DEFAULT_SOURCE,
    SOURCE_NONPLATFORM,
    SOURCE_PLATFORM,
    flight_time_to_height_cm,
    normalize_source,
)
from modules.jump_analysis import (
    _prepare_jump_df,
    _records_to_jump_df,
    available_sources,
    compute_baseline_delta,
    compute_swc_delta,
    filter_by_source,
)

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_source_split"


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = None
    try:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_root = TEST_TMP_ROOT / f"store_{uuid.uuid4().hex[:8]}"
        tmp_root.mkdir(parents=True, exist_ok=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(tmp_root / "store")
        import local_store as local_store_module

        local_store_module = importlib.reload(local_store_module)
        local_store_module.LEGACY_STORE_DIR = tmp_root / "legacy-default"
        yield local_store_module
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


def _cmj_record(athlete: str, date: str, height_cm: float, source: str) -> dict[str, object]:
    return {
        "test_type": "CMJ",
        "Athlete": athlete,
        "Date": pd.Timestamp(date),
        "CMJ_cm": height_cm,
        "Source": source,
    }


def _sj_record(athlete: str, date: str, height_cm: float, source: str) -> dict[str, object]:
    """SJ no tiene benchmark externo: aisla el z interno/poblacional."""
    return {
        "test_type": "SJ",
        "Athlete": athlete,
        "Date": pd.Timestamp(date),
        "SJ_cm": height_cm,
        "Source": source,
    }


class SourceNormalizationTest(unittest.TestCase):
    def test_blank_and_unknown_values_fall_back_to_platform(self):
        # Todo el historial anterior a esta columna vino de la plataforma.
        for value in ("", None, float("nan"), "desconocido", "nan"):
            self.assertEqual(normalize_source(value), SOURCE_PLATFORM)

    def test_known_device_aliases_resolve_to_their_partition(self):
        for value in ("myjump2", "Alfombra", "contact_mat", "No-Plataforma"):
            self.assertEqual(normalize_source(value), SOURCE_NONPLATFORM)
        for value in ("involution", "forceplate", "Plataforma"):
            self.assertEqual(normalize_source(value), SOURCE_PLATFORM)

    def test_flight_time_converts_with_the_standard_formula(self):
        # h = g*t^2/8 -> 500 ms ~ 30.66 cm
        self.assertAlmostEqual(flight_time_to_height_cm(500), 30.66, places=1)
        for invalid in (0, -100, None, "abc"):
            self.assertIsNone(flight_time_to_height_cm(invalid))


class SameDayCollisionTest(unittest.TestCase):
    def test_two_devices_on_the_same_day_stay_as_separate_rows(self):
        df = _records_to_jump_df(
            [
                _cmj_record("Ana Lopez", "2026-05-01", 40.0, SOURCE_PLATFORM),
                _cmj_record("Ana Lopez", "2026-05-01", 44.5, SOURCE_NONPLATFORM),
            ]
        )
        self.assertEqual(len(df), 2)
        self.assertEqual(
            sorted(df["CMJ_cm"].tolist()),
            [40.0, 44.5],
            "una medicion piso a la otra en vez de convivir",
        )

    def test_same_device_same_day_still_consolidates_into_one_row(self):
        # La fusion por bateria sigue viva: CMJ y SJ del mismo test son una fila.
        df = _records_to_jump_df(
            [
                _cmj_record("Ana Lopez", "2026-05-01", 40.0, SOURCE_PLATFORM),
                {
                    "test_type": "SJ",
                    "Athlete": "Ana Lopez",
                    "Date": pd.Timestamp("2026-05-01"),
                    "SJ_cm": 34.0,
                    "Source": SOURCE_PLATFORM,
                },
            ]
        )
        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(float(df.iloc[0]["EUR"]), 40.0 / 34.0, places=3)

    def test_store_round_trip_keeps_both_sources(self):
        with isolated_store() as local_store:
            incoming = _records_to_jump_df(
                [
                    _cmj_record("Ana Lopez", "2026-05-01", 40.0, SOURCE_PLATFORM),
                    _cmj_record("Ana Lopez", "2026-05-01", 44.5, SOURCE_NONPLATFORM),
                ]
            )
            local_store.save_dataset("jump_df", incoming)
            stored = local_store.read_full_dataset("jump_df")

            self.assertEqual(len(stored), 2)
            self.assertEqual(
                set(stored["Source"].map(normalize_source)),
                {SOURCE_PLATFORM, SOURCE_NONPLATFORM},
            )

    def test_legacy_rows_without_source_are_read_as_platform(self):
        with isolated_store() as local_store:
            local_store._ensure_store_dir()
            legacy = pd.DataFrame(
                [{"Athlete": "Ana Lopez", "Date": pd.Timestamp("2026-05-01"), "CMJ_cm": 40.0}]
            )
            legacy.to_csv(local_store._dataset_path("jump_df"), index=False)

            stored = local_store.read_full_dataset("jump_df")
            self.assertEqual(list(stored["Source"].map(normalize_source)), [SOURCE_PLATFORM])


class ZScorePartitionTest(unittest.TestCase):
    def test_within_athlete_z_does_not_mix_devices(self):
        # El atleta progresa igual en cada dispositivo, pero la alfombra lee
        # sistematicamente mas alto. Se usa SJ_cm porque no tiene benchmark
        # externo: asi el resultado depende solo del z intra-atleta, que es lo
        # que este test controla.
        records = []
        for day, height in enumerate([30.0, 30.5, 31.0], start=1):
            records.append(_sj_record("Ana Lopez", f"2026-05-0{day}", height, SOURCE_PLATFORM))
        for day, height in enumerate([38.0, 38.5, 39.0], start=4):
            records.append(_sj_record("Ana Lopez", f"2026-05-0{day}", height, SOURCE_NONPLATFORM))

        df = _records_to_jump_df(records)
        platform_z = filter_by_source(df, SOURCE_PLATFORM).sort_values("Date")["SJ_Z"]
        nonplatform_z = filter_by_source(df, SOURCE_NONPLATFORM).sort_values("Date")["SJ_Z"]

        # Cada fuente recorre el mismo rango relativo, asi que sus z deben
        # coincidir. Pooled, el escalon de 8 cm domina y los dos grupos
        # quedarian separados en extremos opuestos.
        np.testing.assert_allclose(
            platform_z.to_numpy(dtype=float),
            nonplatform_z.to_numpy(dtype=float),
            atol=1e-6,
        )
        np.testing.assert_allclose(
            platform_z.to_numpy(dtype=float), [-1.22, 0.0, 1.22], atol=0.01
        )

    def test_cohort_z_is_computed_per_source(self):
        """La cohorte, cuando es valida, sigue separada por fuente.

        Antes este test usaba el fallback poblacional del dataset entero, que
        se cerro: una poblacion que mezcla deportes, niveles y sexos no
        habilita un z. Ahora se arma una cohorte real (mismo deporte, nivel y
        sexo, por encima del minimo) para cada fuente y se verifica que los z
        de una no contaminen a los de la otra.
        """
        from modules.athlete_profile import Sexo
        from modules.jump_analysis import calc_zscores
        from modules.zscore_sources import MIN_COHORT_SIZE

        n = MIN_COHORT_SIZE
        rows, profiles = [], []
        for idx in range(n):
            for tag, base, source in (("Plat", 30.0, SOURCE_PLATFORM), ("Mat", 50.0, SOURCE_NONPLATFORM)):
                name = f"{tag} {idx}"
                rows.append(
                    {
                        "Athlete": name,
                        "Date": pd.Timestamp("2026-05-01"),
                        "SJ_cm": base + idx,
                        "Source": source,
                    }
                )
                profiles.append(
                    {"Athlete": name, "Deporte": "Handball", "Nivel": "Competitivo", "Sexo": Sexo.MASCULINO}
                )

        result = calc_zscores(pd.DataFrame(rows), profile_df=pd.DataFrame(profiles))
        platform_z = filter_by_source(result, SOURCE_PLATFORM)["SJ_Z"].to_numpy(dtype=float)
        nonplatform_z = filter_by_source(result, SOURCE_NONPLATFORM)["SJ_Z"].to_numpy(dtype=float)

        # Ambos grupos recorren el mismo rango relativo: si se calcularan
        # juntos, el escalon de 20 cm los separaria en extremos opuestos.
        np.testing.assert_allclose(sorted(platform_z), sorted(nonplatform_z), atol=1e-6)
        self.assertGreater(float(np.nanmax(platform_z)), 1.0)


class SourceStillPartitionsWithoutExternalBenchmarkTest(unittest.TestCase):
    """El benchmark sintetico se elimino; la particion por fuente sigue viva.

    Antes esta clase verificaba que las filas de plataforma usaran el benchmark
    externo y las de tiempo de vuelo no. Ese benchmark ya no existe: su desvio
    era `excellent - mean`, un proxy inflado. Lo que se conserva es la regla de
    fondo, que ninguna fila herede una referencia que no le corresponde.
    """

    def test_no_metric_resolves_to_a_borrowed_literature_sd(self):
        from modules.zscore_sources import ZSource

        records = [
            _cmj_record("Plat A", "2026-05-01", 38.0, SOURCE_PLATFORM),
            _cmj_record("Mat A", "2026-05-01", 38.0, SOURCE_NONPLATFORM),
        ]
        df = _records_to_jump_df(records)
        # Sin perfil no hay poblacion: nadie puede llegar a z de literatura.
        self.assertNotIn(str(ZSource.LITERATURE_Z), set(df["CMJ_Z_source"]))

    def test_sources_keep_their_own_rows(self):
        records = [
            _cmj_record("Ana Lopez", "2026-05-01", 40.0, SOURCE_PLATFORM),
            _cmj_record("Ana Lopez", "2026-05-01", 46.0, SOURCE_NONPLATFORM),
        ]
        df = _records_to_jump_df(records)
        self.assertEqual(len(df), 2)
        self.assertEqual(sorted(df["CMJ_cm"].tolist()), [40.0, 46.0])


class TemporalPartitionTest(unittest.TestCase):
    def _mixed_history(self) -> pd.DataFrame:
        rows = [
            {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 40.0, "Source": SOURCE_PLATFORM},
            {"Athlete": "Ana Lopez", "Date": "2026-04-08", "CMJ_cm": 40.2, "Source": SOURCE_PLATFORM},
            {"Athlete": "Ana Lopez", "Date": "2026-04-15", "CMJ_cm": 40.1, "Source": SOURCE_PLATFORM},
            {"Athlete": "Ana Lopez", "Date": "2026-04-22", "CMJ_cm": 48.0, "Source": SOURCE_NONPLATFORM},
            {"Athlete": "Ana Lopez", "Date": "2026-04-29", "CMJ_cm": 48.4, "Source": SOURCE_NONPLATFORM},
        ]
        return _prepare_jump_df(pd.DataFrame(rows))

    def test_swc_compares_against_the_same_device(self):
        history = self._mixed_history()
        delta = compute_swc_delta(history, "2026-04-29", variables=["CMJ_cm"])
        row = delta[delta["Variable"] == "CMJ_cm"].iloc[0]

        # El anterior debe ser la toma de alfombra del 22/04 (48.0), no la de
        # plataforma del 15/04 (40.1), que daria un salto ficticio de +8.3 cm.
        self.assertAlmostEqual(float(row["Valor_anterior"]), 48.0, places=3)
        self.assertAlmostEqual(float(row["Delta_abs"]), 0.4, places=3)

    def test_baseline_never_mixes_devices(self):
        history = self._mixed_history()
        baseline = compute_baseline_delta(history, "2026-04-29", variables=["CMJ_cm"])
        row = baseline[baseline["Variable"] == "CMJ_cm"].iloc[0]

        # Solo hay 2 tomas de alfombra, por debajo de las 3 que exige el
        # baseline. Es correcto declararlo insuficiente en vez de completarlo
        # con mediciones de plataforma.
        self.assertEqual(int(row["N_valid"]), 2)
        self.assertEqual(row["Signal"], "baseline insuficiente")

    def test_explicit_source_argument_overrides_the_current_row(self):
        history = self._mixed_history()
        baseline = compute_baseline_delta(
            history, "2026-04-29", variables=["CMJ_cm"], source=SOURCE_PLATFORM
        )
        row = baseline[baseline["Variable"] == "CMJ_cm"].iloc[0]
        self.assertEqual(int(row["N_valid"]), 3)


class FrameHelpersTest(unittest.TestCase):
    def test_available_sources_follows_canonical_order(self):
        df = _records_to_jump_df(
            [
                _cmj_record("Mat A", "2026-05-01", 44.0, SOURCE_NONPLATFORM),
                _cmj_record("Plat A", "2026-05-01", 40.0, SOURCE_PLATFORM),
            ]
        )
        self.assertEqual(available_sources(df), [SOURCE_PLATFORM, SOURCE_NONPLATFORM])

    def test_filter_by_source_treats_a_frame_without_column_as_platform(self):
        legacy = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 40.0}])
        self.assertEqual(len(filter_by_source(legacy, SOURCE_PLATFORM)), 1)
        self.assertEqual(len(filter_by_source(legacy, SOURCE_NONPLATFORM)), 0)
        self.assertEqual(len(filter_by_source(legacy, None)), 1)

    def test_source_column_survives_numeric_coercion(self):
        # `_prepare_jump_df` convierte a numerico todo lo que no este excluido:
        # si Source no estuviera protegido, quedaria NaN y el aislamiento
        # entero se caeria en silencio.
        prepared = _prepare_jump_df(
            pd.DataFrame(
                [{"Athlete": "Ana Lopez", "Date": "2026-05-01", "CMJ_cm": 40.0, "Source": SOURCE_NONPLATFORM}]
            )
        )
        self.assertEqual(prepared.iloc[0]["Source"], SOURCE_NONPLATFORM)


if __name__ == "__main__":
    unittest.main()
