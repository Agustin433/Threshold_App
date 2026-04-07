from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_history"


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = None
    try:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_root = TEST_TMP_ROOT / f"history_{uuid.uuid4().hex[:8]}"
        tmp_root.mkdir(parents=True, exist_ok=True)
        store_dir = tmp_root / "store"
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        import local_store as local_store_module

        local_store_module = importlib.reload(local_store_module)
        local_store_module.LEGACY_STORE_DIR = tmp_root / "legacy-default"
        yield local_store_module, tmp_root
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        if TEST_TMP_ROOT.exists() and not any(TEST_TMP_ROOT.iterdir()):
            TEST_TMP_ROOT.rmdir()
        import local_store as local_store_module

        importlib.reload(local_store_module)


class Phase2HistoryTest(unittest.TestCase):
    def test_create_history_backup_writes_timestamped_csv(self):
        with isolated_store() as (_local_store, _tmp_root):
            import modules.history_manager as history_manager_module

            history_manager_module = importlib.reload(history_manager_module)
            source_df = pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Pct": 90},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-02", "Pct": 75},
                ]
            )

            backup_info = history_manager_module.create_history_backup(
                "completion_df",
                source_df,
                source="local",
                action="clear_local_dataset",
            )

            backup_path = Path(backup_info["path"])
            restored_df = pd.read_csv(backup_path)

            self.assertTrue(backup_path.exists())
            self.assertIn("completion_df", backup_path.name)
            self.assertIn("local", backup_path.name)
            self.assertIn("clear_local_dataset", backup_path.name)
            self.assertEqual(len(restored_df), 2)

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

    def test_overwrite_dataset_to_empty_does_not_restore_from_legacy_copy(self):
        with isolated_store() as (local_store, _tmp_root):
            legacy_path = local_store.LEGACY_STORE_DIR / "completion_history.csv"
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Pct": 90},
                    {"Athlete": "Bruno Rey", "Date": "2026-04-02", "Pct": 75},
                ]
            ).to_csv(legacy_path, index=False)

            migrated = local_store.read_full_dataset("completion_df")
            self.assertEqual(len(migrated), 2)

            emptied = local_store.overwrite_dataset("completion_df", pd.DataFrame())
            reloaded = local_store.read_full_dataset("completion_df")

            self.assertTrue(emptied.empty)
            self.assertTrue(reloaded.empty)
            self.assertTrue((local_store.STORE_DIR / "completion_history.csv").exists())

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
