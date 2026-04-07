from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_dir = Path(tmp_dir) / "store"
            os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
            import local_store as local_store_module

            local_store_module = importlib.reload(local_store_module)
            local_store_module.LEGACY_STORE_DIR = Path(tmp_dir) / "legacy-default"
            yield local_store_module, Path(tmp_dir)
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        import local_store as local_store_module

        importlib.reload(local_store_module)


class Phase2HistoryTest(unittest.TestCase):
    def test_overwrite_dataset_replaces_existing_history(self):
        with isolated_store() as (local_store, _tmp_root):
            initial_df = pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Pct": 90},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-02", "Pct": 75},
                ]
            )
            local_store.save_dataset("completion_df", initial_df)

            replacement_df = pd.DataFrame(
                [{"Athlete": "Ana Lopez", "Date": "2026-04-03", "Pct": 95}]
            )
            overwritten = local_store.overwrite_dataset("completion_df", replacement_df)
            loaded = local_store.read_full_dataset("completion_df")

            self.assertEqual(len(overwritten), 1)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded["Date"].iloc[0].strftime("%Y-%m-%d"), "2026-04-03")
            self.assertEqual(loaded["Athlete"].iloc[0], "Ana Lopez")

    def test_team_report_figures_include_completion_or_quadrants(self):
        from modules.report_generator import collect_report_plotly_figures

        state = {
            "completion_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Pct": 90},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-01", "Pct": 75},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-03", "Pct": 100},
                ]
            ),
            "jump_df": pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 32.5, "SJ_cm": 29.2, "DRI": 0.62, "IMTP_N": 1820},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-01", "CMJ_cm": 35.1, "SJ_cm": 30.4, "DRI": 0.69, "IMTP_N": 1950},
                ]
            ),
            "rpe_df": None,
            "wellness_df": None,
            "rep_load_df": None,
            "raw_df": None,
            "maxes_df": None,
            "acwr_dict": {},
            "mono_dict": {},
        }

        figures = collect_report_plotly_figures(state, report_athlete="Todos", report_audience="profe")
        slugs = {figure["slug"] for figure in figures}

        self.assertTrue({"completion_team", "quadrant_cmj_imtp"} & slugs)


if __name__ == "__main__":
    unittest.main()
