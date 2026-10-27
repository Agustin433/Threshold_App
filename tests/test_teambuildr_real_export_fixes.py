"""Regresiones encontradas con los exports reales de TeamBuildr (oct/2026)."""

import io
import os
import shutil
import tempfile
import unittest

import pandas as pd

from modules.data_loader import (
    classify_exercise,
    parse_questionnaire_raw_csv,
    prepare_raw_workouts_df,
    raw_session_date_column,
)
from modules.load_monitoring import training_dates_by_athlete


class _Named(io.BytesIO):
    def __init__(self, text: str, name: str):
        super().__init__(text.encode("utf-8"))
        self.name = name


def _questionnaire(rows: list[tuple[str, int, int, str, int]]) -> _Named:
    header = '"First Name","Last Name","User ID","External ID","Response ID","Assigned Workout ID","Question","Question ID","Question Abbreviation","Result","Timestamp Complete"\n'
    lines = [
        f'"Ana","Lopez",1,"",{index},{workout},"q",{question},"x","{value}",{timestamp}'
        for index, (_, workout, question, value, timestamp) in enumerate(rows)
    ]
    return _Named(header + "\n".join(lines) + "\n", "questionnaire.csv")


# 2026-09-29 22:30 en Argentina = 2026-09-30 01:30 UTC.
LATE_EVENING_TS = int(pd.Timestamp("2026-09-30 01:30", tz="UTC").timestamp())
MORNING_TS = int(pd.Timestamp("2026-09-29 12:00", tz="UTC").timestamp())


class QuestionnaireDateAndLoadTest(unittest.TestCase):
    def test_answer_after_21h_local_stays_on_local_day(self):
        rpe_df, _ = parse_questionnaire_raw_csv(
            _questionnaire([("", 1, 103496, "7", LATE_EVENING_TS), ("", 1, 103497, "60", LATE_EVENING_TS)])
        )
        self.assertEqual(pd.Timestamp(rpe_df.iloc[0]["Date"]), pd.Timestamp("2026-09-29"))

    def test_two_sessions_same_day_add_their_load(self):
        # Antes: RPE medio (6) x duracion media (60) = 360. Real: 5x60 + 7x60 = 720.
        rpe_df, _ = parse_questionnaire_raw_csv(
            _questionnaire(
                [
                    ("", 1, 103496, "5", MORNING_TS),
                    ("", 1, 103497, "60", MORNING_TS),
                    ("", 2, 103496, "7", MORNING_TS + 3600),
                    ("", 2, 103497, "60", MORNING_TS + 3600),
                ]
            )
        )
        row = rpe_df.iloc[0]
        self.assertAlmostEqual(float(row["sRPE"]), 720.0)
        self.assertAlmostEqual(float(row["Duration_min"]), 120.0)
        self.assertAlmostEqual(float(row["RPE"]), 6.0)


class SessionDateTest(unittest.TestCase):
    def _raw(self):
        return pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Exercise Name": "Back Squat", "Assigned Date": "2026-09-26",
                 "Completed Date": "2026-09-29", "Set Number": 1, "Result": 80, "Reps": 5,
                 "Tags": "Dominante de Rodilla"},
            ]
        )

    def test_session_date_is_completed_date_and_assigned_is_untouched(self):
        prepared = prepare_raw_workouts_df(self._raw())

        self.assertEqual(raw_session_date_column(prepared), "Fecha_sesion")
        self.assertEqual(pd.Timestamp(prepared.iloc[0]["Session Date"]), pd.Timestamp("2026-09-29"))
        # Assigned Date es clave de dedupe del historial: no se reescribe.
        self.assertEqual(pd.Timestamp(prepared.iloc[0]["Assigned Date"]), pd.Timestamp("2026-09-26"))

    def test_training_ledger_uses_completed_day(self):
        ledger = training_dates_by_athlete(prepare_raw_workouts_df(self._raw()))
        self.assertEqual(list(next(iter(ledger.values()))), [pd.Timestamp("2026-09-29")])

    def test_without_completed_date_falls_back_to_assigned(self):
        raw = self._raw().drop(columns=["Completed Date"])
        prepared = prepare_raw_workouts_df(raw)
        self.assertEqual(pd.Timestamp(prepared.iloc[0]["Session Date"]), pd.Timestamp("2026-09-26"))


class RealTagsTest(unittest.TestCase):
    def test_real_teambuildr_tags_are_mapped(self):
        cases = {
            "Core_Plank": "core_stability",
            "Core_Dead_Bug": "core_stability",
            "Core_Carry": "core_stability",
            "Ballistic MMSS": "plyo_jump",
            "Mobility MMII": "mobility_prehab",
            "Tejidos": "mobility_prehab",
            "Breathing": "mobility_prehab",
        }
        for tag, expected in cases.items():
            with self.subTest(tag=tag):
                self.assertEqual(classify_exercise(tag, "Ejercicio X"), expected)

    def test_frequent_untagged_exercises_are_classified(self):
        cases = {
            "1-Leg Glute Bridge": "strength_loaded",
            "Db/Kb 1-Arm Farmer Carry": "core_stability",
            "Banded Face Pull": "strength_loaded",
            "Half Kneeling Ankle Dorsiflexion": "mobility_prehab",
            "Rack Assisted Hip Airplane": "mobility_prehab",
            "Mb Chest Pass to Floor": "plyo_jump",
        }
        for exercise, expected in cases.items():
            with self.subTest(exercise=exercise):
                self.assertEqual(classify_exercise("", exercise), expected)


class ReplaceDatasetSpanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.previous = os.environ.get("THRESHOLD_STORE_DIR")
        os.environ["THRESHOLD_STORE_DIR"] = self.tmp
        import importlib

        import local_store

        self.store = importlib.reload(local_store)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = self.previous
        import importlib

        import local_store

        importlib.reload(local_store)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reupload_moves_answer_instead_of_duplicating_it(self):
        old = pd.DataFrame(
            [
                {"Date": "2026-09-01", "Athlete": "Ana Lopez", "RPE": 6, "Duration_min": 60, "sRPE": 360},
                # Guardada con el dia UTC (30/09) en vez del local (29/09).
                {"Date": "2026-09-30", "Athlete": "Ana Lopez", "RPE": 7, "Duration_min": 60, "sRPE": 420},
                {"Date": "2026-09-30", "Athlete": "Bruno Rey", "RPE": 5, "Duration_min": 50, "sRPE": 250},
            ]
        )
        self.store.save_dataset("rpe_df", old)
        corrected = pd.DataFrame(
            [{"Date": "2026-09-29", "Athlete": "Ana Lopez", "RPE": 7, "Duration_min": 60, "sRPE": 420}]
        )
        span = self.store.dataset_span("rpe_df", corrected)
        span = (span[0], span[1] + pd.Timedelta(days=1), span[2])
        merged = self.store.replace_dataset_span("rpe_df", corrected, span)

        ana = merged[merged["Athlete"] == "Ana Lopez"]
        self.assertEqual(sorted(pd.to_datetime(ana["Date"]).dt.strftime("%m-%d")), ["09-01", "09-29"])
        # Otro atleta y fechas fuera del rango no se tocan.
        self.assertEqual(len(merged[merged["Athlete"] == "Bruno Rey"]), 1)


if __name__ == "__main__":
    unittest.main()


class PerSetExposureTest(unittest.TestCase):
    """Segunda revision del PDF real de Mariano (14/10/2026)."""

    def test_core_and_prehab_rows_count_one_series_each(self):
        raw = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Exercise Name": "Banded Pallof Press", "Assigned Date": "2026-10-06",
                 "Set Number": n, "Reps": 10, "Tags": "Core_Anti_Rotacion"}
                for n in (1, 2, 3)
            ]
            + [
                {"Athlete": "Ana Lopez", "Exercise Name": "Short Copenhagen Plank", "Assigned Date": "2026-10-06",
                 "Set Number": n, "Reps": None, "Tags": ""}
                for n in (1, 2)
            ]
        )
        prepared = prepare_raw_workouts_df(raw)
        by_category = prepared.groupby("stimulus_category")["Exposures"].sum()

        # Antes: 30 (repeticiones) y 0 (sin reps -> "Faltan datos").
        self.assertEqual(by_category["core_stability"], 3)
        self.assertEqual(by_category["mobility_prehab"], 2)

    def test_facepull_written_together_is_horizontal_pull(self):
        raw = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Exercise Name": 'Cable Half Kneeling "Facepull"',
                 "Assigned Date": "2026-10-06", "Set Number": 1, "Result": 15, "Reps": 12, "Tags": ""},
                {"Athlete": "Ana Lopez", "Exercise Name": "Band Pull Apart",
                 "Assigned Date": "2026-10-06", "Set Number": 1, "Result": 0, "Reps": 15, "Tags": ""},
            ]
        )
        prepared = prepare_raw_workouts_df(raw)
        self.assertEqual(prepared["strength_pattern"].tolist(), ["traccion_horizontal", "traccion_horizontal"])
