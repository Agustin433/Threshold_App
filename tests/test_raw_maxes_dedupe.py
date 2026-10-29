"""Raw Workouts y Raw Maxes: claves de dedupe y guardado remoto sin error 21000.

Casos del diagnostico sobre los exports reales de TeamBuildr (oct/2026):
- mismo ejercicio dos veces el mismo dia con WorkoutId distinto;
- WorkoutId reutilizado en dos fechas (la plantilla se reasigna);
- WorkoutId=0 con Assigned Date "0" (auto-registrado por el atleta);
- dos maxes el mismo dia con Max ID distinto.
Los fixtures son sinteticos con las columnas del export real.
"""

from __future__ import annotations

import io
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from charts.load_charts import daily_best_maxes
from local_store import DATASET_SPECS, merge_dataset
from modules import remote_store
from modules.data_loader import (
    DISCARDED_ROWS_ATTR,
    RAW_FECHA_REF_COL,
    describe_discarded_rows,
    parse_maxes_health,
    parse_questionnaire_raw_csv,
    parse_raw_workouts,
)
from modules.remote_store import RemoteSaveError, dataset_df_to_remote_records, save_remote_dataset

RAW_HEADER = "Athlete,Assigned Date,Completed Date,WorkoutId,Exercise Name,Set Number,Result,Reps,Tags"
RAW_ROWS = [
    # mismo ejercicio, mismo dia, WorkoutId distinto (dos bloques de la sesion)
    "Ana Lopez,2026-10-01,2026-10-01,101,Sentadilla,1,80,5,Fuerza_Rodilla_Bilateral",
    "Ana Lopez,2026-10-01,2026-10-01,102,Sentadilla,1,70,8,Fuerza_Rodilla_Bilateral",
    # WorkoutId reutilizado en dos fechas
    "Ana Lopez,2026-10-02,2026-10-02,200,Peso Muerto,1,100,3,Fuerza_Cadera_Bisagra",
    "Ana Lopez,2026-10-09,2026-10-10,200,Peso Muerto,1,105,3,Fuerza_Cadera_Bisagra",
    # auto-registrado por el atleta: WorkoutId=0, Assigned Date="0"
    "Bruno Rey,0,2026-10-03,0,Plancha,1,,1,Core_Anti_Extension",
    "Bruno Rey,0,2026-10-03,0,Plancha,2,,1,Core_Anti_Extension",
    # descartes visibles
    "Bruno Rey,0,,0,Plancha,1,,1,Core_Anti_Extension",
    ",2026-10-04,2026-10-04,300,Remo,1,50,10,Fuerza_Tiron_Horizontal",
]

MAXES_HEADER = "Athlete,Added Date,Exercise Name,Max Value,Max ID,Exercise Id"
MAXES_ROWS = [
    "Ana Lopez,2026-10-01,Sentadilla,100,9001,11",
    "Ana Lopez,2026-10-01,Sentadilla,105,9002,11",  # dos tests el mismo dia
    "Ana Lopez,2026-10-15,Sentadilla,110,9003,11",
    "Bruno Rey,2026-10-01,Sentadilla,120,9004,11",
    "Bruno Rey,fecha mal,Sentadilla,120,9005,11",
]


class _Named(io.BytesIO):
    def __init__(self, text: str, name: str):
        super().__init__(text.encode("utf-8"))
        self.name = name


def _raw_file() -> _Named:
    return _Named(RAW_HEADER + "\n" + "\n".join(RAW_ROWS) + "\n", "raw_workouts.csv")


def _maxes_file() -> _Named:
    return _Named(MAXES_HEADER + "\n" + "\n".join(MAXES_ROWS) + "\n", "maxes.csv")


SERVICE_ENV = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}


@contextmanager
def patched_env(updates: dict[str, str]):
    original = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RawWorkoutsKeyTest(unittest.TestCase):
    def setUp(self):
        self.raw = parse_raw_workouts(_raw_file())

    def test_self_registered_rows_are_imported_with_completed_date(self):
        planks = self.raw[self.raw["Exercise Name"] == "Plancha"]
        self.assertEqual(len(planks), 2)
        self.assertTrue(planks["Assigned Date"].isna().all())
        self.assertEqual(set(planks[RAW_FECHA_REF_COL]), {pd.Timestamp("2026-10-03")})
        self.assertEqual(set(planks["Date"]), {pd.Timestamp("2026-10-03")})
        self.assertEqual(set(planks["Fecha_sesion"]), {pd.Timestamp("2026-10-03")})

    def test_discarded_rows_are_counted_by_reason(self):
        discarded = self.raw.attrs[DISCARDED_ROWS_ATTR]
        self.assertEqual(sum(discarded.values()), 2)
        self.assertEqual(discarded["sin atleta"], 1)
        self.assertEqual(discarded["sin fecha valida (ni Assigned Date ni Completed Date)"], 1)
        self.assertIn("2 fila(s) descartadas", describe_discarded_rows(self.raw))
        self.assertEqual(len(self.raw), 6)

    def test_new_key_has_no_collisions_and_old_key_did(self):
        records = dataset_df_to_remote_records("raw_df", self.raw)
        self.assertEqual(len(records), 6)
        self.assertEqual(len({record["row_key"] for record in records}), 6)

        old_key = ["Athlete", "Assigned Date", "Exercise Name", "Set Number"]
        self.assertTrue(self.raw.duplicated(subset=old_key, keep=False).any())
        self.assertEqual(
            DATASET_SPECS["raw_df"]["dedupe_cols"],
            ["Athlete", RAW_FECHA_REF_COL, "WorkoutId", "Exercise Name", "Set Number"],
        )

    def test_reused_workout_id_on_two_dates_are_two_rows(self):
        deadlifts = self.raw[self.raw["WorkoutId"] == 200]
        self.assertEqual(sorted(deadlifts[RAW_FECHA_REF_COL]), [pd.Timestamp("2026-10-02"), pd.Timestamp("2026-10-09")])

    def test_local_merge_keeps_every_row(self):
        merged = merge_dataset(pd.DataFrame(), self.raw, "raw_df")
        self.assertEqual(len(merged), 6)
        self.assertEqual((merged["Exercise Name"] == "Plancha").sum(), 2)

    def test_row_key_is_stable_for_int_and_float_set_numbers(self):
        as_float = self.raw.copy()
        as_float["Set Number"] = as_float["Set Number"].astype(float)
        keys_int = [r["row_key"] for r in dataset_df_to_remote_records("raw_df", self.raw)]
        keys_float = [r["row_key"] for r in dataset_df_to_remote_records("raw_df", as_float)]
        self.assertEqual(keys_int, keys_float)

    def test_stored_history_without_fecha_ref_gets_it(self):
        stored = self.raw.drop(columns=[RAW_FECHA_REF_COL]).copy()
        stored.attrs = {}
        merged = merge_dataset(stored, pd.DataFrame(), "raw_df")
        self.assertEqual(len(merged), 6)
        self.assertTrue(merged[RAW_FECHA_REF_COL].notna().all())


class MaxesKeyTest(unittest.TestCase):
    def setUp(self):
        self.maxes = parse_maxes_health(_maxes_file())

    def test_two_maxes_same_day_are_both_kept(self):
        self.assertEqual(DATASET_SPECS["maxes_df"]["dedupe_cols"], ["Max ID"])
        same_day = self.maxes[(self.maxes["Athlete"] == "Ana Lopez") & (self.maxes["Added Date"] == "2026-10-01")]
        self.assertEqual(sorted(same_day["Max Value"]), [100, 105])
        records = dataset_df_to_remote_records("maxes_df", self.maxes)
        self.assertEqual(len({record["row_key"] for record in records}), len(records))
        merged = merge_dataset(pd.DataFrame(), self.maxes, "maxes_df")
        self.assertEqual(len(merged), 4)

    def test_invalid_date_is_counted(self):
        self.assertEqual(self.maxes.attrs[DISCARDED_ROWS_ATTR], {"fecha invalida": 1})

    def test_trend_uses_best_value_of_the_day(self):
        best = daily_best_maxes(self.maxes)
        ana = best[(best["Athlete"] == "Ana Lopez") & (best["Exercise Name"] == "Sentadilla")]
        self.assertEqual(list(ana["Max Value"]), [105, 110])


class SafeUpsertTest(unittest.TestCase):
    def _records(self, n: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Athlete": [f"Atleta {i}" for i in range(n)],
                "Assigned Date": ["2026-10-01"] * n,
                "Fecha_ref": ["2026-10-01"] * n,
                "WorkoutId": list(range(1, n + 1)),
                "Exercise Name": ["Sentadilla"] * n,
                "Set Number": [1] * n,
            }
        )

    def test_duplicate_keys_are_reported_not_sent(self):
        df = self._records(3)
        df = pd.concat([df, df.iloc[[0, 0]]], ignore_index=True)  # Atleta 0 tres veces
        sent: list[list[dict]] = []

        def fake_request(method, table, query=None, payload=None, **kwargs):
            sent.append(payload)
            return payload

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            with self.assertRaises(RemoteSaveError) as ctx:
                save_remote_dataset("raw_df", df)

        exc = ctx.exception
        self.assertEqual((exc.saved, exc.total, exc.failed), (2, 5, 3))
        self.assertIn("Atleta 0 · 2026-10-01 · Sentadilla (x3)", str(exc))
        sent_keys = [record["row_key"] for chunk in sent for record in chunk]
        self.assertEqual(len(sent_keys), len(set(sent_keys)))

    def test_failed_chunk_does_not_stop_the_others(self):
        df = self._records(1200)  # 3 lotes de 500/500/200
        calls = []

        def fake_request(method, table, query=None, payload=None, **kwargs):
            calls.append(len(payload))
            if len(calls) == 2:
                raise remote_store.SupabaseHTTPError(500, "Internal Server Error", '{"code":"21000"}')
            return payload

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            with self.assertRaises(RemoteSaveError) as ctx:
                save_remote_dataset("raw_df", df)

        self.assertEqual(calls, [500, 500, 200])
        exc = ctx.exception
        self.assertEqual((exc.saved, exc.total, exc.failed), (700, 1200, 500))
        self.assertIn("1 lote(s) fallaron", str(exc))
        self.assertIn("21000", str(exc))


class QuestionnaireDiscardsTest(unittest.TestCase):
    def test_unknown_question_ids_are_counted_and_listed(self):
        ts = int(pd.Timestamp("2026-10-20 12:00", tz="UTC").timestamp())
        header = '"First Name","Last Name","User ID","External ID","Response ID","Assigned Workout ID","Question","Question ID","Question Abbreviation","Result","Timestamp Complete"'
        rows = [
            f'"Ana","Lopez",1,"",1,10,"q",103496,"x","7",{ts}',
            f'"Ana","Lopez",1,"",2,10,"q",103497,"x","60",{ts}',
            f'"Ana","Lopez",1,"",3,10,"q",999001,"x","3",{ts}',
            f'"Ana","Lopez",1,"",4,10,"q",999002,"x","4",{ts}',
            f'"Ana","Lopez",1,"",5,10,"q",999001,"x","5",{ts}',
        ]
        rpe_df, wellness_df = parse_questionnaire_raw_csv(_Named(header + "\n" + "\n".join(rows) + "\n", "q.csv"))
        discarded = rpe_df.attrs[DISCARDED_ROWS_ATTR]
        self.assertEqual(discarded, {"Question ID no reconocido (999001, 999002)": 3})
        self.assertEqual(wellness_df.attrs[DISCARDED_ROWS_ATTR], discarded)
        self.assertIn("3 fila(s) descartadas", describe_discarded_rows(rpe_df))


if __name__ == "__main__":
    unittest.main()
