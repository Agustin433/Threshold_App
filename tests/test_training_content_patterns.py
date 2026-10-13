import unittest

import pandas as pd

from modules.data_loader import classify_exercise, prepare_raw_workouts_df


def _raw(rows):
    return pd.DataFrame(
        [
            {
                "Athlete": "Ana Lopez",
                "Assigned Date": row[0],
                "Exercise Name": row[1],
                "Tags": row[2],
                "Result": row[3],
                "Reps": row[4],
                "Set Number": row[5],
            }
            for row in rows
        ]
    )


class ExerciseOverridesTest(unittest.TestCase):
    def test_copenhagen_is_prehab_even_if_tagged_core(self):
        self.assertEqual(classify_exercise("Core", "Short Copenhagen Plank"), "mobility_prehab")
        self.assertEqual(classify_exercise("", "Copenhagen Adduction"), "mobility_prehab")

    def test_nordic_is_prehab_even_if_tagged_ham_curl(self):
        self.assertEqual(classify_exercise("Ham_Curl", "Nordic Hamstring Curl"), "mobility_prehab")

    def test_pallof_stays_core(self):
        self.assertEqual(classify_exercise("", "Banded Pallof Press Rotation"), "core_stability")


class StrengthPatternAndSeriesTest(unittest.TestCase):
    def test_pattern_comes_from_primary_tag_before_stance(self):
        prepared = prepare_raw_workouts_df(
            _raw([("2026-09-28", "Bulgarian Split Squat", "Stance_Split|Dominante de Rodilla", 20, 8, 1)])
        )
        self.assertEqual(prepared.iloc[0]["strength_pattern"], "dominante_rodilla")

    def test_pattern_inferred_from_name_without_pattern_tag(self):
        prepared = prepare_raw_workouts_df(
            _raw(
                [
                    ("2026-09-28", "Barbell Bench Press", "", 60, 5, 1),
                    ("2026-09-28", "Weighted Bar Pull Up (Pronated Grip)", "", 10, 5, 1),
                    ("2026-09-28", "Romanian Deadlift", "", 80, 6, 1),
                    ("2026-09-28", "Standing Calf Raise", "", 40, 12, 1),
                ]
            )
        ).set_index("Exercise Name")
        self.assertEqual(prepared.loc["Barbell Bench Press", "strength_pattern"], "empuje_horizontal")
        self.assertEqual(prepared.loc["Weighted Bar Pull Up (Pronated Grip)", "strength_pattern"], "traccion_vertical")
        self.assertEqual(prepared.loc["Romanian Deadlift", "strength_pattern"], "dominante_cadera")
        self.assertEqual(prepared.loc["Standing Calf Raise", "strength_pattern"], "accesorios_mmii")

    def test_each_row_with_set_number_counts_as_one_series_including_bodyweight(self):
        prepared = prepare_raw_workouts_df(
            _raw(
                [
                    ("2026-09-28", "Back Squat", "Dominante de Rodilla", 100, 5, 1),
                    ("2026-09-28", "Back Squat", "Dominante de Rodilla", 100, 5, 2),
                    ("2026-09-28", "Push Up", "Empuje Horizontal", None, 12, 1),
                ]
            )
        )
        self.assertEqual(float(prepared["Series"].sum()), 3.0)
        self.assertEqual(float(prepared["Volume_Load_kg"].sum()), 1000.0)

    def test_aggregated_sets_column_is_used_when_rows_are_not_per_set(self):
        raw = pd.DataFrame(
            [{"Athlete": "Ana Lopez", "Assigned Date": "2026-09-28", "Exercise Name": "Back Squat",
              "Tags": "Dominante de Rodilla", "Result": 100, "Reps": 5, "Sets": 4}]
        )
        self.assertEqual(float(prepare_raw_workouts_df(raw)["Series"].sum()), 4.0)


class ExposurePayloadTest(unittest.TestCase):
    def _payload(self, rows):
        from modules.report_generator import _build_professional_exposure_payload

        return _build_professional_exposure_payload({"raw_df": _raw(rows)}, "Ana Lopez")

    def test_strength_shows_series_and_tonnage_and_pattern_breakdown(self):
        payload = self._payload(
            [
                ("2026-09-28", "Back Squat", "Dominante de Rodilla", 100, 5, 1),
                ("2026-09-28", "Back Squat", "Dominante de Rodilla", 100, 5, 2),
                ("2026-09-30", "Barbell Bench Press", "Empuje Horizontal", 60, 5, 1),
            ]
        )
        table = payload["table"].set_index("Estímulo")

        self.assertIn("3 series", table.loc["Fuerza con carga", "Dosis"])
        self.assertIn("kg x rep", table.loc["Fuerza con carga", "Dosis"])
        self.assertIn("2 series", table.loc["  · Dominante de rodilla", "Dosis"])
        self.assertIn("1 series", table.loc["  · Empuje horizontal", "Dosis"])
        self.assertIn("tren inferior 2 series", payload["summary_line"])
        self.assertIn("tren superior 1 series", payload["summary_line"])

    def test_isometric_and_core_are_separate_and_copenhagen_is_prehab(self):
        payload = self._payload(
            [
                ("2026-09-28", "Iso Hold Split Squat", "Iso_Overcoming", None, 1, 1),
                ("2026-09-29", "Banded Pallof Press Rotation", "Core", None, 10, 1),
                ("2026-09-30", "Short Copenhagen Plank", "Core", None, 1, 1),
            ]
        )
        stimuli = set(payload["table"]["Estímulo"])

        self.assertIn("Isométricos", stimuli)
        self.assertIn("Core / anti-rotación", stimuli)
        self.assertIn("Prehab y movilidad", stimuli)
        prehab = payload["table"].set_index("Estímulo").loc["Prehab y movilidad", "Ejercicios clave"]
        self.assertIn("Copenhagen", prehab)

    def test_ranking_between_stimuli_uses_sessions_only(self):
        # Pliometria: 2 sesiones con muchos contactos; fuerza: 2 sesiones.
        # Empatan en sesiones: la dosis (unidades distintas) no desempata.
        payload = self._payload(
            [
                ("2026-09-28", "Back Squat", "Dominante de Rodilla", 100, 5, 1),
                ("2026-09-30", "Back Squat", "Dominante de Rodilla", 100, 5, 1),
                ("2026-09-28", "Pogo Jumps", "Jump_Plyo", None, 100, 1),
                ("2026-09-30", "Pogo Jumps", "Jump_Plyo", None, 100, 1),
            ]
        )
        self.assertIn("por sesiones", payload["summary_line"])
        self.assertEqual(payload["low_or_absent"], [])


if __name__ == "__main__":
    unittest.main()
