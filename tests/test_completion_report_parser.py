from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd

from modules import data_loader


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _csv_bytes(text: str) -> bytes:
    return text.strip().encode("utf-8")


class CompletionReportSummaryParserTest(unittest.TestCase):
    def test_parse_completion_report_accepts_summary_csv_format(self):
        df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    athlete,assigned,completed,percent
                    Celina Amarillo,1410,515,36.52%
                    Andrea Appas,60,62,100%
                    """
                ),
                "completion_summary.csv",
            )
        )

        self.assertEqual(list(df["Athlete"]), ["Celina Amarillo", "Andrea Appas"])
        self.assertEqual(df["completion_scope"].unique().tolist(), ["uploaded_period_total"])
        self.assertEqual(df["source_type"].unique().tolist(), ["completion_report_summary"])
        self.assertTrue(df["Date"].isna().all())

    def test_parse_completion_report_drops_average_and_total_rows(self):
        df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Athlete,Assigned,Completed,Percent
                    Celina Amarillo,1410,515,36.52%
                    AVERAGE,457.24,162.23,35.48%
                    Total,1470,577,39.25%
                    """
                ),
                "completion_summary.csv",
            )
        )

        athlete_names = df["Athlete"].astype(str).str.casefold().tolist()
        self.assertEqual(athlete_names, ["celina amarillo"])
        self.assertNotIn("average", athlete_names)
        self.assertNotIn("total", athlete_names)

    def test_parse_completion_report_parses_percent_strings(self):
        df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Athlete,Assigned,Completed,Percent
                    Celina Amarillo,1410,515,36.52%
                    """
                ),
                "completion_summary.csv",
            )
        )

        self.assertAlmostEqual(float(df.loc[0, "Pct"]), 36.52, places=2)

    def test_parse_completion_report_keeps_completed_greater_than_assigned(self):
        df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Athlete,Assigned,Completed,Percent
                    Andrea Appas,60,62,
                    """
                ),
                "completion_summary.csv",
            )
        )

        self.assertEqual(int(df.loc[0, "Assigned"]), 60)
        self.assertEqual(int(df.loc[0, "Completed"]), 62)
        self.assertGreater(float(df.loc[0, "Pct"]), 100.0)

    def test_parse_completion_report_summary_does_not_create_fake_dates_or_week_start(self):
        df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Athlete,Assigned,Completed,Percent
                    Celina Amarillo,1410,515,36.52%
                    """
                ),
                "completion_summary.csv",
            )
        )

        self.assertIn("Date", df.columns)
        self.assertTrue(pd.to_datetime(df["Date"], errors="coerce").isna().all())
        self.assertNotIn("week_start", df.columns)


if __name__ == "__main__":
    unittest.main()
