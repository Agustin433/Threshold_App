"""Raw Workouts: la fecha de ANALISIS es Completed Date (Fecha_sesion).

En el export real, 7.599 de 82.791 series (9%) se completaron antes de la
fecha asignada (mediana -1 dia, minimo -29). Fecha_ref sigue siendo la
identidad (dedupe_cols / row_key); Fecha_sesion manda en todo lo temporal.
"""

import unittest

import pandas as pd

from local_store import (
    DATASET_SPECS,
    _build_weekly_external_summary,
    _normalize_frame,
    analysis_date_col,
    filter_recent_window,
)
from modules.data_loader import (
    RAW_FECHA_REF_COL,
    RAW_FECHA_SESION_COL,
    prepare_raw_workouts_df,
    raw_session_date_column,
    summarize_completed_before_assigned,
)
from modules.history_view import completed_before_assigned_caption
from modules.remote_store import dataset_df_to_remote_records


def _row(assigned, completed, *, set_number=1, workout_id=10, result=100, reps=5):
    return {
        "Athlete": "Ana Lopez",
        "Exercise Name": "Back Squat",
        "WorkoutId": workout_id,
        "Assigned Date": assigned,
        "Completed Date": completed,
        "Set Number": set_number,
        "Result": result,
        "Reps": reps,
        "Tags": "Dominante de Rodilla",
    }


class FechaSesionTest(unittest.TestCase):
    def test_series_assigned_30_10_completed_01_10_counts_in_week_of_01_10(self):
        prepared = prepare_raw_workouts_df(pd.DataFrame([_row("2026-10-30", "2026-10-01")]))

        row = prepared.iloc[0]
        self.assertEqual(pd.Timestamp(row[RAW_FECHA_SESION_COL]), pd.Timestamp("2026-10-01"))
        self.assertEqual(pd.Timestamp(row["Date"]), pd.Timestamp("2026-10-01"))
        # La identidad no cambia.
        self.assertEqual(pd.Timestamp(row[RAW_FECHA_REF_COL]), pd.Timestamp("2026-10-30"))
        self.assertEqual(pd.Timestamp(row["Assigned Date"]), pd.Timestamp("2026-10-30"))
        self.assertEqual(raw_session_date_column(prepared), RAW_FECHA_SESION_COL)

        weekly = _build_weekly_external_summary(None, prepared_raw_df=prepared)
        self.assertEqual(len(weekly), 1)
        # 01/10/2026 es jueves: semana del lunes 28/09, no la del 26/10.
        self.assertEqual(pd.Timestamp(weekly.iloc[0]["week_start"]), pd.Timestamp("2026-09-28"))
        self.assertAlmostEqual(float(weekly.iloc[0]["strength_kg"]), 500.0)

    def test_without_valid_completed_date_falls_back_to_fecha_ref(self):
        prepared = prepare_raw_workouts_df(
            pd.DataFrame([_row("2026-10-30", ""), _row("0", "2026-10-02", set_number=2)])
        )
        self.assertEqual(
            prepared[RAW_FECHA_SESION_COL].tolist(),
            [pd.Timestamp("2026-10-30"), pd.Timestamp("2026-10-02")],
        )

    def test_dedupe_key_is_untouched(self):
        spec = DATASET_SPECS["raw_df"]
        self.assertEqual(
            spec["dedupe_cols"], ["Athlete", RAW_FECHA_REF_COL, "WorkoutId", "Exercise Name", "Set Number"]
        )
        self.assertEqual(spec["date_col"], RAW_FECHA_REF_COL)
        self.assertEqual(analysis_date_col(spec), RAW_FECHA_SESION_COL)

    def test_supabase_event_date_is_fecha_sesion_and_row_key_ignores_it(self):
        prepared = prepare_raw_workouts_df(pd.DataFrame([_row("2026-10-30", "2026-10-01")]))
        record = dataset_df_to_remote_records("raw_df", prepared)[0]
        self.assertEqual(record["event_date"], "2026-10-01")

        # Misma serie con otra Completed Date: mismo row_key (upsert, no duplica).
        moved = prepare_raw_workouts_df(pd.DataFrame([_row("2026-10-30", "2026-10-03")]))
        self.assertEqual(dataset_df_to_remote_records("raw_df", moved)[0]["row_key"], record["row_key"])

    def test_stored_history_with_old_date_is_realigned(self):
        # Historial guardado con la regla vieja: Date = Fecha_ref, sin Fecha_sesion.
        prepared = prepare_raw_workouts_df(pd.DataFrame([_row("2026-10-30", "2026-10-01")]))
        stored = prepared.drop(columns=[RAW_FECHA_SESION_COL, "Session Date"]).copy()
        stored["Date"] = stored[RAW_FECHA_REF_COL]
        stored = stored.astype({"Date": str, RAW_FECHA_REF_COL: str, "Assigned Date": str, "Completed Date": str})

        normalized = _normalize_frame(stored, DATASET_SPECS["raw_df"])
        self.assertEqual(pd.Timestamp(normalized.iloc[0][RAW_FECHA_SESION_COL]), pd.Timestamp("2026-10-01"))
        realigned = prepare_raw_workouts_df(normalized)
        self.assertEqual(pd.Timestamp(realigned.iloc[0]["Date"]), pd.Timestamp("2026-10-01"))

    def test_recent_window_uses_fecha_sesion(self):
        frame = prepare_raw_workouts_df(
            pd.DataFrame(
                [
                    _row("2026-10-30", "2026-10-01", set_number=1),
                    _row("2026-10-29", "2026-10-29", set_number=2, workout_id=11),
                ]
            )
        )
        # Ventana de 1 semana: solo la ultima semana con datos (la del 26/10).
        recent = filter_recent_window(frame, analysis_date_col(DATASET_SPECS["raw_df"]), weeks=1)
        self.assertEqual(recent["Set Number"].tolist(), [2])

    def test_completed_before_assigned_summary_and_caption(self):
        frame = pd.DataFrame(
            [
                _row("2026-10-30", "2026-10-01", set_number=1),
                _row("2026-10-10", "2026-10-09", set_number=2),
                _row("2026-10-10", "2026-10-10", set_number=3),
                _row("0", "2026-10-11", set_number=4),
            ]
        )
        stats = summarize_completed_before_assigned(frame)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["early"], 2)
        self.assertEqual(stats["min_days"], -29)
        self.assertEqual(stats["median_days"], -15.0)
        caption = completed_before_assigned_caption(frame)
        self.assertIn("2 de 4 series (50%)", caption)
        self.assertIn("minimo -29", caption)


if __name__ == "__main__":
    unittest.main()
