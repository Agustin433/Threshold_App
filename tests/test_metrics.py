import math
import unittest

import pandas as pd

from modules.metrics import calculate_completion_rate, calculate_monotony


class CompletionRateTests(unittest.TestCase):
    def test_weighted_completion_beats_simple_percentage_mean(self):
        df = pd.DataFrame(
            [
                {"Assigned": 1, "Completed": 1, "Pct": 100},
                {"Assigned": 99, "Completed": 0, "Pct": 0},
            ]
        )

        result = calculate_completion_rate(df)

        self.assertEqual(result.method, "weighted")
        self.assertAlmostEqual(result.value, 1.0, places=3)

    def test_percentage_fallback_keeps_0_to_100_scale(self):
        result = calculate_completion_rate(pd.DataFrame([{"Pct": 80}, {"Pct": 100}]))

        self.assertEqual(result.method, "fallback_pct")
        self.assertAlmostEqual(result.value, 90.0, places=3)

    def test_percentage_fallback_normalizes_0_to_1_scale(self):
        result = calculate_completion_rate(pd.DataFrame([{"CompletionPct": 0.5}, {"CompletionPct": 1.0}]))

        self.assertEqual(result.method, "fallback_pct")
        self.assertAlmostEqual(result.value, 75.0, places=3)

    def test_invalid_assigned_can_fallback_to_percentage(self):
        result = calculate_completion_rate(pd.DataFrame([{"Assigned": 0, "Completed": 0, "Pct": 0.5}]))

        self.assertEqual(result.method, "fallback_pct")
        self.assertEqual(result.warning, "invalid_assigned")
        self.assertAlmostEqual(result.value, 50.0, places=3)

    def test_missing_values_do_not_break_weighted_completion(self):
        df = pd.DataFrame(
            [
                {"Assigned": 10, "Completed": 5},
                {"Assigned": None, "Completed": 10},
                {"Assigned": 0, "Completed": 0},
            ]
        )

        result = calculate_completion_rate(df)

        self.assertEqual(result.method, "weighted")
        self.assertEqual(result.warning, "rows_ignored")
        self.assertAlmostEqual(result.value, 50.0, places=3)


class MonotonyTests(unittest.TestCase):
    def test_standard_monotony_uses_mean_over_population_sd(self):
        result = calculate_monotony([100, 200, 300])

        self.assertEqual(result.method, "standard")
        self.assertAlmostEqual(result.value, 200 / math.sqrt(20000 / 3), places=3)

    def test_zero_variability_with_positive_load_is_flagged_high(self):
        result = calculate_monotony([100, 100, 100])

        self.assertEqual(result.method, "zero_variability")
        self.assertEqual(result.warning, "zero_variability")
        self.assertEqual(result.value, 99.0)

    def test_less_than_three_valid_days_is_insufficient(self):
        result = calculate_monotony([100, 200])

        self.assertEqual(result.method, "insufficient_data")
        self.assertIsNone(result.value)

    def test_no_valid_load_returns_zero(self):
        result = calculate_monotony([0, 0, 0])

        self.assertEqual(result.method, "no_load")
        self.assertEqual(result.value, 0.0)


if __name__ == "__main__":
    unittest.main()
