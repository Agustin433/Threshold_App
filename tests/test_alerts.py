from __future__ import annotations

import unittest

import pandas as pd

from modules.alerts import (
    alert_feed_to_dataframe,
    build_alert_feed,
    dedupe_alerts,
    select_executive_alerts,
)


class ProductAlertsTest(unittest.TestCase):
    def _feed(self) -> list[dict[str, object]]:
        reference_date = pd.Timestamp("2026-04-26")
        quality_report = {
            "alerts": [
                "Raw workouts - 2 fila(s) con Result = 0 en strength_loaded",
                "Carga un archivo para continuar",
            ]
        }
        weekly_summaries = {
            "weekly_load": pd.DataFrame(
                [
                    {
                        "Athlete": "Ana",
                        "week_start": pd.Timestamp("2026-04-20"),
                        "is_current_week": True,
                        "ACWR_EWMA_last": 1.62,
                        "monotony": 1.7,
                    }
                ]
            )
        }
        completion_df = pd.DataFrame(
            [
                {"Athlete": "Ana", "Date": "2026-04-21", "Pct": 65},
                {"Athlete": "Luis", "Date": "2026-04-21", "Pct": 96},
            ]
        )
        jump_df = pd.DataFrame(
            [
                {"Athlete": "Ana", "Date": "2026-01-20", "CMJ_cm": 30.0},
            ]
        )

        return build_alert_feed(
            quality_report=quality_report,
            weekly_summaries=weekly_summaries,
            completion_df=completion_df,
            jump_df=jump_df,
            athletes_list=["Ana", "Luis"],
            reference_date=reference_date,
            week_start=pd.Timestamp("2026-04-20"),
            scope="team",
            surface="test",
        )

    def test_feed_covers_p11_v1_categories(self):
        feed = self._feed()
        categories = {alert["category"] for alert in feed}

        self.assertIn("data_quality", categories)
        self.assertIn("load_risk", categories)
        self.assertIn("adherence", categories)
        self.assertIn("evaluations", categories)

    def test_severity_priority_and_order_are_stable(self):
        feed = self._feed()
        priorities = [int(alert["priority"]) for alert in feed]

        self.assertEqual(priorities, sorted(priorities, reverse=True))
        self.assertEqual(feed[0]["category"], "load_risk")
        self.assertEqual(feed[0]["severity"], "danger")
        self.assertGreaterEqual(int(feed[0]["priority"]), 90)

    def test_local_ui_messages_are_not_product_alerts(self):
        feed = self._feed()
        messages = " ".join(str(alert["message"]) for alert in feed)

        self.assertNotIn("Carga un archivo", messages)
        self.assertFalse(any(str(alert["title"]).lower().startswith("zona optima") for alert in feed))

    def test_dedupe_keeps_one_alert_per_key(self):
        feed = self._feed()
        duplicated = dedupe_alerts([feed[0], feed[0]])

        self.assertEqual(len(duplicated), 1)
        self.assertEqual(duplicated[0]["key"], feed[0]["key"])

    def test_executive_and_operational_consumers_share_feed(self):
        feed = self._feed()
        executive = select_executive_alerts(feed, limit=3)
        detail_df = alert_feed_to_dataframe(feed)

        self.assertLessEqual(len(executive), 3)
        self.assertFalse(detail_df.empty)
        self.assertIn("Categoria", detail_df.columns)
        self.assertIn("Accion", detail_df.columns)

    def test_adherence_alert_uses_weighted_completion_when_available(self):
        feed = build_alert_feed(
            quality_report={"alerts": []},
            weekly_summaries={"weekly_load": pd.DataFrame()},
            completion_df=pd.DataFrame(
                [
                    {"Athlete": "Ana", "Date": "2026-04-21", "Assigned": 1, "Completed": 1, "Pct": 100},
                    {"Athlete": "Ana", "Date": "2026-04-22", "Assigned": 99, "Completed": 0, "Pct": 0},
                ]
            ),
            jump_df=None,
            athletes_list=["Ana"],
            reference_date=pd.Timestamp("2026-04-26"),
            week_start=pd.Timestamp("2026-04-20"),
            scope="team",
            surface="test",
        )

        adherence_alert = next(alert for alert in feed if alert["category"] == "adherence")

        self.assertEqual(adherence_alert["meta"]["calculation_method"], "weighted")
        self.assertAlmostEqual(adherence_alert["meta"]["completion_pct"], 1.0, places=3)

    def test_load_alert_surfaces_zero_variability_monotony(self):
        feed = build_alert_feed(
            quality_report={"alerts": []},
            weekly_summaries={
                "weekly_load": pd.DataFrame(
                    [
                        {
                            "Athlete": "Ana",
                            "week_start": pd.Timestamp("2026-04-20"),
                            "is_current_week": True,
                            "ACWR_EWMA_last": 1.0,
                            "monotony": 99.0,
                            "monotony_status": "zero_variability",
                        }
                    ]
                )
            },
            completion_df=None,
            jump_df=None,
            athletes_list=["Ana"],
            reference_date=pd.Timestamp("2026-04-26"),
            week_start=pd.Timestamp("2026-04-20"),
            scope="team",
            surface="test",
        )

        load_alert = next(alert for alert in feed if alert["category"] == "load_risk")

        self.assertIn("sin variabilidad", load_alert["message"])
        self.assertEqual(load_alert["meta"]["monotony_status"], "zero_variability")


if __name__ == "__main__":
    unittest.main()
