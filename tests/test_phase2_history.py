from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

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
    def test_ensure_prepared_raw_workouts_skips_rebuild_when_raw_version_is_unchanged(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        raw_df = pd.DataFrame(
            [
                {
                    "Assigned Date": "2026-04-01",
                    "Athlete": "Ana Lopez",
                    "Exercise": "Back Squat",
                    "Tags": "Dominante de Rodilla",
                    "Result": 80,
                    "Reps": 5,
                    "Sets": 4,
                }
            ]
        )
        prepared_df = pd.DataFrame(
            [
                {
                    "Assigned Date": pd.Timestamp("2026-04-01"),
                    "Date": pd.Timestamp("2026-04-01"),
                    "Athlete": "Ana Lopez",
                    "Exercise": "Back Squat",
                    "Category": "Dominante de Rodilla",
                    "stimulus_category": "strength_loaded",
                    "Volume_Load": 400.0,
                    "Volume_Load_legacy": 400.0,
                    "Volume_Load_kg": 400.0,
                    "Contacts": 0.0,
                    "Exposures": 4.0,
                    "Distance_m": 0.0,
                    "is_invalid": False,
                    "is_untagged": False,
                }
            ]
        )
        fake_st = SimpleNamespace(session_state={"raw_df": raw_df})

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(page_state_module, "current_raw_df_version", return_value=(("raw_df", True, 1, 10),)):
                with patch.object(page_state_module, "prepare_raw_workouts_df", return_value=prepared_df) as mocked_prepare:
                    first = page_state_module.ensure_prepared_raw_workouts(ensure_base_state=False)
                    second = page_state_module.ensure_prepared_raw_workouts(ensure_base_state=False)

        self.assertIs(first, prepared_df)
        self.assertIs(second, prepared_df)
        self.assertEqual(mocked_prepare.call_count, 1)
        self.assertEqual(fake_st.session_state["prepared_raw_df_version"], (("raw_df", True, 1, 10),))

    def test_ensure_prepared_raw_workouts_rebuilds_when_raw_version_changes(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        raw_df = pd.DataFrame(
            [
                {
                    "Assigned Date": "2026-04-01",
                    "Athlete": "Ana Lopez",
                    "Exercise": "Back Squat",
                    "Tags": "Dominante de Rodilla",
                    "Result": 80,
                    "Reps": 5,
                    "Sets": 4,
                }
            ]
        )
        prepared_v1 = pd.DataFrame([{"Athlete": "Ana Lopez", "Category": "week_1"}])
        prepared_v2 = pd.DataFrame([{"Athlete": "Ana Lopez", "Category": "week_2"}])
        fake_st = SimpleNamespace(session_state={"raw_df": raw_df})

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(
                page_state_module,
                "current_raw_df_version",
                side_effect=[(("raw_df", True, 1, 10),), (("raw_df", True, 2, 10),)],
            ):
                with patch.object(page_state_module, "prepare_raw_workouts_df", side_effect=[prepared_v1, prepared_v2]) as mocked_prepare:
                    first = page_state_module.ensure_prepared_raw_workouts(ensure_base_state=False)
                    second = page_state_module.ensure_prepared_raw_workouts(ensure_base_state=False)

        self.assertIs(first, prepared_v1)
        self.assertIs(second, prepared_v2)
        self.assertEqual(mocked_prepare.call_count, 2)
        self.assertEqual(fake_st.session_state["prepared_raw_df_version"], (("raw_df", True, 2, 10),))

    def test_report_preview_signature_changes_when_options_or_store_version_change(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        signature_a = page_state_module.build_report_preview_signature(
            report_audience="profe",
            report_athlete="Ana Lopez",
            effective_report_athlete="Ana Lopez",
            report_options={"include_technical_annex": False, "include_volume": True},
            date_window="01/04/2026 a 30/04/2026",
            store_version=(("rpe_df", True, 1, 10),),
        )
        signature_b = page_state_module.build_report_preview_signature(
            report_audience="profe",
            report_athlete="Ana Lopez",
            effective_report_athlete="Ana Lopez",
            report_options={"include_technical_annex": False, "include_volume": True},
            date_window="01/04/2026 a 30/04/2026",
            store_version=(("rpe_df", True, 1, 10),),
        )
        signature_c = page_state_module.build_report_preview_signature(
            report_audience="profe",
            report_athlete="Ana Lopez",
            effective_report_athlete="Ana Lopez",
            report_options={"include_technical_annex": True, "include_volume": True},
            date_window="01/04/2026 a 30/04/2026",
            store_version=(("rpe_df", True, 1, 10),),
        )
        signature_d = page_state_module.build_report_preview_signature(
            report_audience="profe",
            report_athlete="Ana Lopez",
            effective_report_athlete="Ana Lopez",
            report_options={"include_technical_annex": False, "include_volume": True},
            date_window="01/04/2026 a 30/04/2026",
            store_version=(("rpe_df", True, 2, 10),),
        )

        self.assertEqual(signature_a, signature_b)
        self.assertNotEqual(signature_a, signature_c)
        self.assertNotEqual(signature_a, signature_d)

    def test_report_preview_cache_reuses_payload_until_signature_changes(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(session_state={})
        payload = {"executive_df": pd.DataFrame([{"Bloque": "Semana actual"}])}
        signature_a = ("report_preview", "profe", "Ana Lopez", "Ana Lopez", "window-a", (("include_volume", True),), (("rpe_df", True, 1, 10),))
        signature_b = ("report_preview", "profe", "Ana Lopez", "Ana Lopez", "window-a", (("include_volume", True),), (("rpe_df", True, 2, 10),))

        with patch.object(page_state_module, "st", fake_st):
            self.assertTrue(page_state_module.report_preview_needs_refresh(signature=signature_a))
            page_state_module.store_report_preview(payload=payload, signature=signature_a)
            self.assertFalse(page_state_module.report_preview_needs_refresh(signature=signature_a))
            self.assertTrue(page_state_module.report_preview_needs_refresh(signature=signature_b))
            self.assertEqual(fake_st.session_state["report_preview_payload"], payload)
            self.assertEqual(fake_st.session_state["report_preview_signature"], signature_a)

    def test_performance_debug_helpers_initialize_missing_keys_safely(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state_module, "st", fake_st):
            page_state_module.reset_performance_debug_cycle()
            page_state_module.record_performance_debug_timing("ensure_load_state_s", 0.125, accumulate=False)
            page_state_module.record_performance_debug_artifact("load_state", "reutilizado")

        self.assertIn("performance_debug_timings", fake_st.session_state)
        self.assertIn("performance_debug_artifacts", fake_st.session_state)
        self.assertAlmostEqual(fake_st.session_state["performance_debug_timings"]["ensure_load_state_s"], 0.125, places=6)
        self.assertEqual(fake_st.session_state["performance_debug_artifacts"]["load_state"], "reutilizado")

    def test_ensure_load_state_skips_rebuild_when_load_version_is_unchanged(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(
            session_state={
                "rpe_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-04-01", "sRPE": 210}]),
                "wellness_df": None,
                "raw_df": None,
            }
        )
        weekly_stub = {
            "weekly_load": pd.DataFrame(),
            "weekly_wellness": pd.DataFrame(),
            "weekly_external": pd.DataFrame(),
            "weekly_team": pd.DataFrame(),
        }

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(page_state_module, "current_load_state_version", return_value=(("load", True, 1, 10),)):
                with patch.object(page_state_module, "build_load_models", return_value=({"Ana Lopez": pd.DataFrame()}, {"Ana Lopez": pd.DataFrame()})) as mocked_build_load_models:
                    with patch.object(page_state_module, "build_weekly_summaries", return_value=weekly_stub) as mocked_build_weekly_summaries:
                        page_state_module.ensure_load_state(ensure_base_state=False)
                        page_state_module.ensure_load_state(ensure_base_state=False)

        self.assertEqual(mocked_build_load_models.call_count, 1)
        self.assertEqual(mocked_build_weekly_summaries.call_count, 1)
        self.assertEqual(fake_st.session_state["load_state_version"], (("load", True, 1, 10),))

    def test_ensure_load_state_rebuilds_when_load_version_changes(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(
            session_state={
                "rpe_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-04-01", "sRPE": 210}]),
                "wellness_df": None,
                "raw_df": None,
            }
        )
        weekly_stub = {
            "weekly_load": pd.DataFrame(),
            "weekly_wellness": pd.DataFrame(),
            "weekly_external": pd.DataFrame(),
            "weekly_team": pd.DataFrame(),
        }

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(
                page_state_module,
                "current_load_state_version",
                side_effect=[(("load", True, 1, 10),), (("load", True, 2, 10),)],
            ):
                with patch.object(page_state_module, "build_load_models", return_value=({"Ana Lopez": pd.DataFrame()}, {"Ana Lopez": pd.DataFrame()})) as mocked_build_load_models:
                    with patch.object(page_state_module, "build_weekly_summaries", return_value=weekly_stub) as mocked_build_weekly_summaries:
                        page_state_module.ensure_load_state(ensure_base_state=False)
                        page_state_module.ensure_load_state(ensure_base_state=False)

        self.assertEqual(mocked_build_load_models.call_count, 2)
        self.assertEqual(mocked_build_weekly_summaries.call_count, 2)
        self.assertEqual(fake_st.session_state["load_state_version"], (("load", True, 2, 10),))

    def test_ensure_load_state_matches_direct_load_model_outputs(self):
        import modules.page_state as page_state_module

        with isolated_store() as (local_store, _tmp_root):
            page_state_module = importlib.reload(page_state_module)
            local_store.save_dataset(
                "rpe_df",
                pd.DataFrame(
                    [
                        {"Athlete": "Ana Lopez", "Date": "2026-04-01", "sRPE": 210, "RPE": 7.0, "Time": 30},
                        {"Athlete": "Ana Lopez", "Date": "2026-04-03", "sRPE": 280, "RPE": 8.0, "Time": 35},
                        {"Athlete": "Bruno Rey", "Date": "2026-04-02", "sRPE": 180, "RPE": 6.0, "Time": 30},
                    ]
                ),
            )
            local_store.save_dataset(
                "wellness_df",
                pd.DataFrame(
                    [
                        {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Sueno_hs": 7, "Estres": 2, "Dolor": 1, "Wellness_Score": 18},
                        {"Athlete": "Bruno Rey", "Date": "2026-04-02", "Sueno_hs": 6, "Estres": 3, "Dolor": 2, "Wellness_Score": 15},
                    ]
                ),
            )
            local_store.save_dataset(
                "raw_df",
                pd.DataFrame(
                    [
                        {"Athlete": "Ana Lopez", "Assigned Date": "2026-04-01", "Exercise Name": "CMJ", "Set Number": 1},
                        {"Athlete": "Bruno Rey", "Assigned Date": "2026-04-02", "Exercise Name": "Sprint", "Set Number": 1},
                    ]
                ),
            )

            recent_state = local_store.load_recent_state(weeks=local_store.RECENT_WEEKS)
            expected_acwr_dict, expected_mono_dict = local_store.build_load_models(recent_state["rpe_df"])
            expected_weekly_summaries = local_store.build_weekly_summaries(
                recent_state["rpe_df"],
                recent_state["wellness_df"],
                recent_state["raw_df"],
                acwr_dict=expected_acwr_dict or {},
            )
            fake_st = SimpleNamespace(session_state=dict(recent_state))

            with patch.object(page_state_module, "st", fake_st):
                page_state_module.ensure_load_state(ensure_base_state=False)

            self.assertEqual(sorted((fake_st.session_state.get("acwr_dict") or {}).keys()), sorted((expected_acwr_dict or {}).keys()))
            self.assertEqual(sorted((fake_st.session_state.get("mono_dict") or {}).keys()), sorted((expected_mono_dict or {}).keys()))
            for athlete, frame in (expected_acwr_dict or {}).items():
                assert_frame_equal(
                    fake_st.session_state["acwr_dict"][athlete].reset_index(drop=True),
                    frame.reset_index(drop=True),
                )
            for athlete, frame in (expected_mono_dict or {}).items():
                assert_frame_equal(
                    fake_st.session_state["mono_dict"][athlete].reset_index(drop=True),
                    frame.reset_index(drop=True),
                )
            for key in ["weekly_load", "weekly_wellness", "weekly_external", "weekly_team"]:
                assert_frame_equal(
                    fake_st.session_state["weekly_summaries"][key].reset_index(drop=True),
                    expected_weekly_summaries[key].reset_index(drop=True),
                    check_dtype=False,
                )

    def test_ensure_page_state_skips_rehydration_when_store_version_is_unchanged(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(session_state={})
        stored_state = {key: None for key in page_state_module.DATASET_SESSION_KEYS}

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(page_state_module, "current_local_store_version", return_value=(("store", True, 1, 10),)):
                with patch.object(page_state_module, "load_recent_state", return_value=stored_state) as mocked_load_recent_state:
                    page_state_module.ensure_page_state(load_models=False)
                    page_state_module.ensure_page_state(load_models=False)

        self.assertEqual(mocked_load_recent_state.call_count, 1)
        self.assertTrue(fake_st.session_state["local_store_hydrated"])
        self.assertEqual(fake_st.session_state["local_store_version"], (("store", True, 1, 10),))

    def test_ensure_page_state_rehydrates_after_store_version_changes(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(session_state={})
        stored_state = {key: None for key in page_state_module.DATASET_SESSION_KEYS}

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(
                page_state_module,
                "current_local_store_version",
                side_effect=[(("store", True, 1, 10),), (("store", True, 2, 10),)],
            ):
                with patch.object(page_state_module, "load_recent_state", return_value=stored_state) as mocked_load_recent_state:
                    page_state_module.ensure_page_state(load_models=False)
                    page_state_module.ensure_page_state(load_models=False)

        self.assertEqual(mocked_load_recent_state.call_count, 2)
        self.assertEqual(fake_st.session_state["local_store_version"], (("store", True, 2, 10),))

    def test_ensure_full_history_state_reuses_cached_snapshot_until_version_changes(self):
        import modules.page_state as page_state_module

        page_state_module = importlib.reload(page_state_module)
        fake_st = SimpleNamespace(session_state={})
        full_state = {"completion_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Pct": 90}])}

        with patch.object(page_state_module, "st", fake_st):
            with patch.object(
                page_state_module,
                "current_local_store_version",
                side_effect=[(("completion_df", True, 1, 10),), (("completion_df", True, 1, 10),), (("completion_df", True, 2, 10),)],
            ):
                with patch.object(page_state_module, "load_full_history_state", return_value=full_state) as mocked_load_full_history_state:
                    first = page_state_module.ensure_full_history_state(keys=["completion_df"])
                    second = page_state_module.ensure_full_history_state(keys=["completion_df"])
                    third = page_state_module.ensure_full_history_state(keys=["completion_df"])

        self.assertIs(first, second)
        self.assertEqual(mocked_load_full_history_state.call_count, 2)
        self.assertEqual(third["completion_df"].iloc[0]["Athlete"], "Ana Lopez")

    def test_filter_recent_window_uses_last_available_weeks_instead_of_calendar_cutoff(self):
        with isolated_store() as (local_store, _tmp_root):
            source_df = pd.DataFrame(
                [
                    {"Athlete": "Ana Lopez", "Date": "2026-01-05", "sRPE": 100},
                    {"Athlete": "Ana Lopez", "Date": "2026-01-12", "sRPE": 110},
                    {"Athlete": "Ana Lopez", "Date": "2026-01-19", "sRPE": 120},
                    {"Athlete": "Ana Lopez", "Date": "2026-01-26", "sRPE": 130},
                    {"Athlete": "Ana Lopez", "Date": "2026-02-02", "sRPE": 140},
                    {"Athlete": "Ana Lopez", "Date": "2026-02-09", "sRPE": 150},
                    {"Athlete": "Ana Lopez", "Date": "2026-04-27", "sRPE": 160},
                ]
            )

            filtered = local_store.filter_recent_window(source_df, "Date", weeks=6)
            visible_dates = pd.to_datetime(filtered["Date"]).dt.strftime("%Y-%m-%d").tolist()

            self.assertEqual(
                visible_dates,
                ["2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02", "2026-02-09", "2026-04-27"],
            )

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

    def test_repload_history_still_loads_as_legacy_dataset(self):
        with isolated_store() as (local_store, _tmp_root):
            source_df = pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-20",
                        "Exercise": "Back Squat",
                        "Load_kg": 80,
                        "Reps_Completed": 5,
                    }
                ]
            )

            local_store.save_dataset("rep_load_df", source_df)
            state = local_store.load_recent_state(weeks=6)

            self.assertIsNotNone(state["rep_load_df"])
            self.assertEqual(state["rep_load_df"].iloc[0]["Athlete"], "Ana Lopez")
            self.assertIn("legacy", local_store.DATASET_LABELS["rep_load_df"].lower())

    def test_recent_completion_state_keeps_undated_summary_rows(self):
        with isolated_store() as (local_store, _tmp_root):
            source_df = pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": pd.NaT,
                        "Assigned": 120,
                        "Completed": 90,
                        "Pct": 75.0,
                        "completion_scope": "uploaded_period_total",
                        "source_type": "completion_report_summary",
                    }
                ]
            )

            local_store.save_dataset("completion_df", source_df)
            state = local_store.load_recent_state(weeks=6)

            self.assertIsNotNone(state["completion_df"])
            self.assertEqual(len(state["completion_df"]), 1)
            self.assertTrue(pd.to_datetime(state["completion_df"]["Date"], errors="coerce").isna().all())
            self.assertEqual(state["completion_df"].iloc[0]["source_type"], "completion_report_summary")


if __name__ == "__main__":
    unittest.main()
