"""Raw Workouts: Fecha_sesion (dia en que se hizo la serie) para todo calculo temporal.

Dato real (oct/2026): 7.599 de 82.791 series se completaron ANTES de la fecha
asignada, hasta 29 dias antes. Fecha_sesion = Completed Date valida, si no
Fecha_ref. La clave (dedupe_cols / row_key) sigue usando Fecha_ref.
"""

from __future__ import annotations

import io
import unittest

import pandas as pd

from local_store import DATASET_SPECS, _build_weekly_external_summary, merge_dataset
from modules.data_loader import (
    RAW_FECHA_REF_COL,
    RAW_SESSION_DATE_COL,
    parse_raw_workouts,
    prepare_raw_workouts_df,
    raw_session_date_column,
)
from modules.remote_store import dataset_df_to_remote_records

HEADER = "Athlete,Assigned Date,Completed Date,WorkoutId,Exercise Name,Set Number,Result,Reps,Tags"
ROWS = [
    # asignada el lunes 12/10, completada 10 dias antes (semana anterior)
    "Ana Lopez,2026-10-12,2026-10-02,101,Sentadilla,1,100,5,Dominante de Rodilla",
    # sin Completed Date: usa Fecha_ref (Assigned Date)
    "Ana Lopez,2026-10-12,,102,Peso Muerto,1,120,3,Dominante de Rodilla",
    # Completed Date "0": tampoco es fecha
    "Ana Lopez,2026-10-12,0,103,Remo,1,60,10,Dominante de Rodilla",
]


class _Named(io.BytesIO):
    def __init__(self, text: str):
        super().__init__(text.encode("utf-8"))
        self.name = "raw.csv"


def _raw(rows=ROWS) -> pd.DataFrame:
    return parse_raw_workouts(_Named(HEADER + "\n" + "\n".join(rows) + "\n"))


class FechaSesionTest(unittest.TestCase):
    def setUp(self):
        self.raw = _raw().set_index("Exercise Name")

    def test_completed_date_wins_and_falls_back_to_fecha_ref(self):
        self.assertEqual(raw_session_date_column(self.raw), RAW_SESSION_DATE_COL)
        self.assertEqual(self.raw.loc["Sentadilla", RAW_SESSION_DATE_COL], pd.Timestamp("2026-10-02"))
        self.assertEqual(self.raw.loc["Peso Muerto", RAW_SESSION_DATE_COL], pd.Timestamp("2026-10-12"))
        self.assertEqual(self.raw.loc["Remo", RAW_SESSION_DATE_COL], pd.Timestamp("2026-10-12"))

    def test_date_column_is_the_session_date_and_key_date_is_untouched(self):
        squat = self.raw.loc["Sentadilla"]
        self.assertEqual(squat["Date"], pd.Timestamp("2026-10-02"))
        self.assertEqual(squat[RAW_FECHA_REF_COL], pd.Timestamp("2026-10-12"))
        self.assertEqual(squat["Assigned Date"], pd.Timestamp("2026-10-12"))

    def test_dedupe_cols_and_row_key_do_not_use_session_date(self):
        self.assertEqual(
            DATASET_SPECS["raw_df"]["dedupe_cols"],
            ["Athlete", RAW_FECHA_REF_COL, "WorkoutId", "Exercise Name", "Set Number"],
        )
        self.assertEqual(DATASET_SPECS["raw_df"]["date_col"], RAW_SESSION_DATE_COL)
        # Cambiar la Completed Date no cambia la clave de la fila.
        moved = _raw([ROWS[0].replace("2026-10-02", "2026-10-05")])
        original = _raw([ROWS[0]])
        key_original = dataset_df_to_remote_records("raw_df", original)[0]["row_key"]
        key_moved = dataset_df_to_remote_records("raw_df", moved)[0]["row_key"]
        self.assertEqual(key_original, key_moved)

    def test_event_date_is_the_session_date(self):
        records = {r["payload"]["Exercise Name"]: r for r in dataset_df_to_remote_records("raw_df", _raw())}
        self.assertEqual(records["Sentadilla"]["event_date"], "2026-10-02")
        self.assertEqual(records["Peso Muerto"]["event_date"], "2026-10-12")

    def test_event_date_is_derived_when_frame_lacks_it(self):
        bare = pd.DataFrame(
            [{"Athlete": "Ana Lopez", "Assigned Date": "2026-10-12", "Completed Date": "2026-10-02",
              "WorkoutId": 1, "Exercise Name": "Sentadilla", "Set Number": 1}]
        )
        self.assertEqual(dataset_df_to_remote_records("raw_df", bare)[0]["event_date"], "2026-10-02")

    def test_weekly_volume_goes_to_the_week_it_was_done(self):
        weekly = _build_weekly_external_summary(None, prepared_raw_df=prepare_raw_workouts_df(_raw()))
        weeks = {pd.Timestamp(w): row for w, row in weekly.set_index("week_start").iterrows()}
        # Sentadilla (100 kg x 5 = 500) se hizo la semana del 28/09; las otras dos, la del 12/10.
        self.assertIn(pd.Timestamp("2026-09-28"), weeks)
        self.assertIn(pd.Timestamp("2026-10-12"), weeks)
        week_cols = [c for c in weekly.columns if "kg" in c.lower() or "volume" in c.lower()]
        self.assertTrue(week_cols, list(weekly.columns))
        first = weeks[pd.Timestamp("2026-09-28")]
        self.assertAlmostEqual(float(first[week_cols[0]]), 500.0)

    def test_stored_history_with_legacy_session_date_is_recomputed(self):
        stored = _raw().reset_index().drop(columns=[RAW_SESSION_DATE_COL, RAW_FECHA_REF_COL])
        stored["Session Date"] = stored["Assigned Date"]  # regla vieja / dato viejo
        stored.attrs = {}
        merged = merge_dataset(stored, pd.DataFrame(), "raw_df").set_index("Exercise Name")
        self.assertNotIn("Session Date", merged.columns)
        self.assertEqual(merged.loc["Sentadilla", RAW_SESSION_DATE_COL], pd.Timestamp("2026-10-02"))
        self.assertEqual(len(merged), 3)


class WeeklyDecisionScriptTest(unittest.TestCase):
    def test_pattern_weeks_use_session_date(self):
        import importlib.util
        from pathlib import Path

        script = Path(__file__).resolve().parent.parent / "scripts" / "weekly_decision_report.py"
        spec = importlib.util.spec_from_file_location("weekly_decision_report", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = script.read_text(encoding="utf-8")
        self.assertIn("ensure_raw_fecha_sesion(raw_df.copy())", source)
        self.assertNotIn('df["week"] = df["Assigned Date"]', source)
        self.assertTrue(callable(module.build_pattern_zscores))


if __name__ == "__main__":
    unittest.main()
