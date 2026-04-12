from __future__ import annotations

import unittest

import pandas as pd

from modules.data_quality import compute_data_quality_report


class DataQualityReportTest(unittest.TestCase):
    def test_dataset_summary_marks_loaded_partial_and_empty(self):
        report = compute_data_quality_report(
            rpe_df=pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-10", "sRPE": 420},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-11", "sRPE": 390},
                ]
            ),
            wellness_df=pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-03-20", "Wellness_Score": 18},
                ]
            ),
            completion_df=None,
            raw_df=pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Assigned Date": "2026-04-09",
                        "stimulus_category": "strength_loaded",
                        "Category": "Dominante de Rodilla",
                        "Result": 80,
                        "Reps": 5,
                        "is_untagged": False,
                        "is_invalid": False,
                    }
                ]
            ),
            maxes_df=pd.DataFrame(),
            jump_df=pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-03-01", "CMJ_cm": 35},
                ]
            ),
            athletes_list=["Ana Lopez"],
            window_days=42,
            reference_date="2026-04-12",
        )

        dataset_summary = report["dataset_summary"].set_index("Dataset")
        self.assertEqual(dataset_summary.loc["RPE + Tiempo", "Estado"], "✅ cargado")
        self.assertEqual(dataset_summary.loc["Wellness", "Estado"], "⚠️ parcial")
        self.assertEqual(dataset_summary.loc["Completion", "Estado"], "❌ vacio")
        self.assertEqual(dataset_summary.loc["Maxes", "Estado"], "❌ vacio")
        self.assertEqual(dataset_summary.loc["Evaluaciones", "Estado"], "⚠️ parcial")
        self.assertEqual(dataset_summary.loc["Raw Workouts", "Filas"], 1)
        self.assertEqual(dataset_summary.loc["RPE + Tiempo", "Dias con dato"], 2)

    def test_athlete_summary_and_alerts_cover_expected_cases(self):
        rpe_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-03", "sRPE": 320},
                {"Athlete": "Ana Lopez", "Date": "2026-04-04", "sRPE": 300},
                {"Athlete": "Ana Lopez", "Date": "2026-04-05", "sRPE": 310},
                {"Athlete": "Ana Lopez", "Date": "2026-04-06", "sRPE": 330},
                {"Athlete": "Ana Lopez", "Date": "2026-04-07", "sRPE": 340},
                {"Athlete": "Ana Lopez", "Date": "2026-04-08", "sRPE": 350},
                {"Athlete": "Ana Lopez", "Date": "2026-04-09", "sRPE": 360},
                {"Athlete": "Ana Lopez", "Date": "2026-04-10", "sRPE": 370},
                {"Athlete": "Bruno Rey", "Date": "2026-04-05", "sRPE": 280},
                {"Athlete": "Bruno Rey", "Date": "2026-04-06", "sRPE": 290},
                {"Athlete": "Bruno Rey", "Date": "2026-04-07", "sRPE": 295},
                {"Athlete": "Bruno Rey", "Date": "2026-04-08", "sRPE": 305},
                {"Athlete": "Bruno Rey", "Date": "2026-04-09", "sRPE": 315},
                {"Athlete": "Bruno Rey", "Date": "2026-04-10", "sRPE": 325},
            ]
        )
        wellness_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-03", "Wellness_Score": 18},
                {"Athlete": "Ana Lopez", "Date": "2026-04-04", "Wellness_Score": 19},
                {"Athlete": "Ana Lopez", "Date": "2026-04-06", "Wellness_Score": 18},
                {"Athlete": "Ana Lopez", "Date": "2026-04-07", "Wellness_Score": 20},
                {"Athlete": "Ana Lopez", "Date": "2026-04-08", "Wellness_Score": 17},
                {"Athlete": "Ana Lopez", "Date": "2026-04-09", "Wellness_Score": 18},
                {"Athlete": "Bruno Rey", "Date": "2026-04-12", "Wellness_Score": 14},
            ]
        )
        raw_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-10",
                    "Exercise": "Back Squat",
                    "stimulus_category": "strength_loaded",
                    "Category": "Dominante de Rodilla",
                    "Result": 80,
                    "Reps": 5,
                    "is_untagged": False,
                    "is_invalid": False,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-10",
                    "Exercise": "Unknown Drill",
                    "stimulus_category": "untagged",
                    "Category": "Unknown Drill",
                    "Result": 15,
                    "Reps": 10,
                    "is_untagged": True,
                    "is_invalid": False,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-11",
                    "Exercise": "Dirty Tag",
                    "stimulus_category": "invalid",
                    "Category": "ju",
                    "Result": 20,
                    "Reps": 8,
                    "is_untagged": False,
                    "is_invalid": True,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-11",
                    "Exercise": "Unknown Jump",
                    "stimulus_category": "untagged",
                    "Category": "Unknown Jump",
                    "Result": 10,
                    "Reps": 4,
                    "is_untagged": True,
                    "is_invalid": False,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-11",
                    "Exercise": "Bench Press",
                    "stimulus_category": "strength_loaded",
                    "Category": "Empuje Horizontal",
                    "Result": 0,
                    "Reps": 6,
                    "is_untagged": False,
                    "is_invalid": False,
                },
                {
                    "Athlete": "Ana Lopez",
                    "Assigned Date": "2026-04-12",
                    "Exercise": "Push Press",
                    "stimulus_category": "strength_loaded",
                    "Category": "Empuje Vertical",
                    "Result": 40,
                    "Reps": 0,
                    "is_untagged": False,
                    "is_invalid": False,
                },
            ]
        )

        report = compute_data_quality_report(
            rpe_df=rpe_df,
            wellness_df=wellness_df,
            completion_df=None,
            raw_df=raw_df,
            maxes_df=None,
            jump_df=pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-03-01", "CMJ_cm": 35}]),
            athletes_list=["Ana Lopez", "Bruno Rey", "Carla Diaz"],
            window_days=10,
            reference_date="2026-04-12",
        )

        athlete_summary = report["athlete_summary"].set_index("Atleta")
        alerts = report["alerts"]

        self.assertEqual(athlete_summary.loc["Ana Lopez", "Semaforo"], "🟢 Verde")
        self.assertEqual(athlete_summary.loc["Bruno Rey", "Semaforo"], "🔴 Rojo")
        self.assertEqual(athlete_summary.loc["Carla Diaz", "Semaforo"], "🔴 Rojo")
        self.assertEqual(float(athlete_summary.loc["Ana Lopez", "% cobertura sRPE"]), 80.0)
        self.assertEqual(float(athlete_summary.loc["Ana Lopez", "% cobertura Wellness"]), 75.0)

        self.assertTrue(any("Carla Diaz - sin sRPE registrado en los ultimos 7 dias" in alert for alert in alerts))
        self.assertTrue(any("Bruno Rey - wellness incompleto respecto a sesiones registradas" in alert for alert in alerts))
        self.assertTrue(any("Raw workouts - 33%" in alert for alert in alerts))
        self.assertTrue(any('Raw workouts - 1 fila(s) con tag invalido ("ju")' in alert for alert in alerts))
        self.assertTrue(any("Raw workouts - 1 fila(s) con Result = 0 en strength_loaded" in alert for alert in alerts))
        self.assertTrue(any("Raw workouts - 1 fila(s) con Reps = 0" in alert for alert in alerts))
        self.assertTrue(any("Evaluaciones - ultimo test hace 42 dias" in alert for alert in alerts))

    def test_alerts_detect_dataset_gap_longer_than_seven_days(self):
        report = compute_data_quality_report(
            rpe_df=pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "sRPE": 320},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-12", "sRPE": 350},
                ]
            ),
            wellness_df=None,
            completion_df=None,
            raw_df=None,
            maxes_df=None,
            jump_df=None,
            athletes_list=["Ana Lopez"],
            window_days=14,
            reference_date="2026-04-12",
        )

        self.assertTrue(any("RPE + Tiempo - hueco de 10 dias" in alert for alert in report["alerts"]))


if __name__ == "__main__":
    unittest.main()
