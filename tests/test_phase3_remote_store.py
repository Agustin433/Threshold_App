from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from modules.remote_store import (
    _supabase_request,
    backfill_remote_evaluations_drop_height,
    dataset_df_to_remote_records,
    jump_df_to_db_records,
    load_remote_dataset,
    load_remote_evaluations,
    load_remote_evaluations_frame,
    save_remote_evaluations,
    supabase_dataset_store_enabled,
    supabase_evaluations_enabled,
)


@contextmanager
def patched_env(updates: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _MockResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Phase3RemoteStoreTest(unittest.TestCase):
    def test_enabled_checks_follow_environment(self):
        with patched_env(
            {
                "SUPABASE_URL": None,
                "SUPABASE_KEY": None,
                "SUPABASE_SERVICE_ROLE_KEY": None,
                "SUPABASE_ANON_KEY": None,
                "THRESHOLD_SUPABASE_URL": None,
                "THRESHOLD_SUPABASE_KEY": None,
            }
        ):
            self.assertFalse(supabase_dataset_store_enabled())
            self.assertFalse(supabase_evaluations_enabled())

        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            self.assertTrue(supabase_dataset_store_enabled())
            self.assertTrue(supabase_evaluations_enabled())

    def test_supabase_request_returns_decoded_json(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch("modules.remote_store.urllib.request.urlopen", return_value=_MockResponse(b'[{"ok": true}]')) as mocked:
                rows = _supabase_request("GET", "dataset_rows", query={"select": "*", "limit": 1})

        self.assertEqual(rows, [{"ok": True}])
        request = mocked.call_args.args[0]
        self.assertIn("/rest/v1/dataset_rows", request.full_url)
        self.assertIn("select=*", request.full_url)
        headers = dict(request.header_items())
        self.assertEqual(headers.get("Apikey"), "test-key")

    def test_dataset_df_to_remote_records_normalizes_keys(self):
        source_df = pd.DataFrame([{"Athlete": "ana lopez", "Date": "2026-04-01", "Pct": 95}])

        records = dataset_df_to_remote_records("completion_df", source_df)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["athlete"], "Ana Lopez")
        self.assertEqual(records[0]["event_date"], "2026-04-01")
        self.assertIn("row_key", records[0])

    def test_load_remote_dataset_uses_shared_pagination(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[[{"payload": {"Athlete": "Ana Lopez", "Date": "2026-04-01", "Pct": 95}}], []],
            ):
                df = load_remote_dataset("completion_df")

        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["Athlete"], "Ana Lopez")

    def test_load_remote_evaluations_frame_renames_columns(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[[{"athlete": "Ana Lopez", "date": "2026-04-01", "cmj_cm": 31.2}], []],
            ):
                df = load_remote_evaluations_frame()

        self.assertIn("Athlete", df.columns)
        self.assertIn("Date", df.columns)
        self.assertIn("CMJ_cm", df.columns)

    def test_jump_df_to_db_records_includes_new_imtp_force_time_columns(self):
        eval_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "IMTP_N": 3385,
                    "IMTP_avg_N": 2993,
                    "IMTP_force_L_N": 1731,
                    "IMTP_force_R_N": 1653,
                    "IMTP_asym_pct": 4.5,
                    "IMTP_pretension": 1109,
                    "IMTP_time_max_s": 2.63,
                    "IMTP_time_pull_s": 3.0,
                    "IMTP_force_50_N": 1172,
                    "IMTP_force_100_N": 1364,
                    "IMTP_force_150_N": 1620,
                    "IMTP_force_200_N": 1957,
                    "IMTP_force_250_N": 2232,
                    "IMTP_rfd_50_N_s": 1260,
                    "IMTP_rfd_100_N_s": 2558,
                    "IMTP_rfd_150_N_s": 3411,
                    "IMTP_rfd_250_N_s": 4493,
                }
            ]
        )

        records = jump_df_to_db_records(eval_df)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["athlete"], "Ana Lopez")
        self.assertEqual(record["date"], "2026-04-01")
        self.assertEqual(record["imtp_force_50_n"], 1172.0)
        self.assertEqual(record["imtp_force_200_n"], 1957.0)
        self.assertEqual(record["imtp_rfd_100_n_s"], 2558.0)
        self.assertEqual(record["imtp_time_pull_s"], 3.0)
        self.assertNotIn("rfd_100", record)
        self.assertNotIn("imtp_rfd_200_n_s", record)

    def test_jump_df_to_db_records_explicitly_clears_drop_height_for_dj_rows_without_height(self):
        eval_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "DJ_cm": 28.0,
                    "DJ_tc_ms": 200.0,
                    "DJ_RSI": 1.4,
                    "DJ_drop_height_cm": None,
                    "DRI": None,
                }
            ]
        )

        records = jump_df_to_db_records(eval_df)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["athlete"], "Ana Lopez")
        self.assertEqual(record["date"], "2026-04-01")
        self.assertEqual(record["dj_cm"], 28.0)
        self.assertEqual(record["dj_tc_ms"], 200.0)
        self.assertEqual(record["dj_rsi"], 1.4)
        self.assertIn("dj_drop_height_cm", record)
        self.assertIsNone(record["dj_drop_height_cm"])

    def test_backfill_remote_evaluations_drop_height_updates_only_missing_height_rows(self):
        remote_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "DJ_cm": 28.0,
                    "DJ_tc_ms": 200.0,
                    "DJ_RSI": 1.4,
                    "DJ_drop_height_cm": None,
                },
                {
                    "Athlete": "Bruno Diaz",
                    "Date": "2026-04-01",
                    "DJ_cm": 27.0,
                    "DJ_tc_ms": 210.0,
                    "DJ_RSI": 1.29,
                    "DJ_drop_height_cm": 40.0,
                },
            ]
        )

        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch("modules.remote_store.load_remote_evaluations_frame", return_value=remote_df):
                with patch(
                    "modules.remote_store.save_remote_evaluations",
                    return_value={"enabled": True, "inserted": 0, "updated": 1, "total": 1},
                ) as mocked_save:
                    stats = backfill_remote_evaluations_drop_height(default_drop_height_cm=30.0)

        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["updated_rows"], 1)
        self.assertEqual(stats["athletes"], 1)

        payload_df = mocked_save.call_args.args[0]
        self.assertEqual(len(payload_df), 1)
        self.assertEqual(payload_df.iloc[0]["Athlete"], "Ana Lopez")
        self.assertAlmostEqual(float(payload_df.iloc[0]["DJ_drop_height_cm"]), 30.0, places=3)

    def test_load_remote_evaluations_preserves_new_imtp_force_time_columns(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[
                    [
                        {
                            "athlete": "Ana Lopez",
                            "date": "2026-04-01",
                            "imtp_n": 3385,
                            "imtp_time_pull_s": 3.0,
                            "imtp_force_100_n": 1364,
                            "imtp_rfd_100_n_s": 2558,
                        }
                    ],
                    [],
                ],
            ):
                df = load_remote_evaluations()

        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["IMTP_N"]), 3385.0)
        self.assertEqual(float(df.iloc[0]["IMTP_time_pull_s"]), 3.0)
        self.assertEqual(float(df.iloc[0]["IMTP_force_100_N"]), 1364.0)
        self.assertEqual(float(df.iloc[0]["IMTP_rfd_100_N_s"]), 2558.0)

    def test_jump_df_to_db_records_includes_iso_hamstring_force_time_columns(self):
        eval_df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-04-01",
                    "ISO_HAM_N": 1280,
                    "ISO_HAM_avg_N": 1115,
                    "ISO_HAM_force_L_N": 670,
                    "ISO_HAM_force_R_N": 610,
                    "ISO_HAM_asym_pct": 9.4,
                    "ISO_HAM_pretension": 180,
                    "ISO_HAM_time_max_s": 1.84,
                    "ISO_HAM_time_pull_s": 2.2,
                    "ISO_HAM_force_50_N": 290,
                    "ISO_HAM_force_100_N": 455,
                    "ISO_HAM_force_150_N": 620,
                    "ISO_HAM_force_200_N": 785,
                    "ISO_HAM_force_250_N": 930,
                    "ISO_HAM_rfd_50_N_s": 1280,
                    "ISO_HAM_rfd_100_N_s": 2240,
                    "ISO_HAM_rfd_150_N_s": 2960,
                    "ISO_HAM_rfd_250_N_s": 3720,
                }
            ]
        )

        records = jump_df_to_db_records(eval_df)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["athlete"], "Ana Lopez")
        self.assertEqual(record["date"], "2026-04-01")
        self.assertEqual(record["iso_ham_force_100_n"], 455.0)
        self.assertEqual(record["iso_ham_rfd_100_n_s"], 2240.0)
        self.assertEqual(record["iso_ham_time_pull_s"], 2.2)
        self.assertNotIn("iso_ham_rfd_200_n_s", record)

    def test_load_remote_evaluations_preserves_iso_hamstring_force_time_columns(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[
                    [
                        {
                            "athlete": "Ana Lopez",
                            "date": "2026-04-01",
                            "iso_ham_n": 1280,
                            "iso_ham_time_pull_s": 2.2,
                            "iso_ham_force_100_n": 455,
                            "iso_ham_rfd_100_n_s": 2240,
                        }
                    ],
                    [],
                ],
            ):
                df = load_remote_evaluations()

        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["ISO_HAM_N"]), 1280.0)
        self.assertEqual(float(df.iloc[0]["ISO_HAM_time_pull_s"]), 2.2)
        self.assertEqual(float(df.iloc[0]["ISO_HAM_force_100_N"]), 455.0)
        self.assertEqual(float(df.iloc[0]["ISO_HAM_rfd_100_N_s"]), 2240.0)

    def test_load_remote_evaluations_uses_legacy_rfd_aliases_as_fallback(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[
                    [
                        {
                            "athlete": "Ana Lopez",
                            "date": "2026-04-01",
                            "imtp_n": 3385,
                            "rfd_100": 2400,
                        }
                    ],
                    [],
                ],
            ):
                df = load_remote_evaluations()

        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["IMTP_rfd_100_N_s"]), 2400.0)

    def test_load_remote_evaluations_older_records_without_iso_ham_columns_still_load_safely(self):
        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[
                    [
                        {
                            "athlete": "Ana Lopez",
                            "date": "2026-04-01",
                            "imtp_n": 3385,
                        }
                    ],
                    [],
                ],
            ):
                df = load_remote_evaluations()

        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["IMTP_N"]), 3385.0)
        self.assertNotIn("ISO_HAM_N", df.columns)

    def test_save_remote_evaluations_preserves_inserted_and_updated_counts(self):
        eval_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-04-01", "CMJ_cm": 31.2},
                {"Athlete": "Bruno Rey", "Date": "2026-04-02", "CMJ_cm": 33.4},
            ]
        )

        with patched_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            }
        ):
            with patch(
                "modules.remote_store._supabase_request",
                side_effect=[
                    [],
                    [{"athlete": "Ana Lopez", "date": "2026-04-01"}],
                    [{"athlete": "Bruno Rey", "date": "2026-04-02"}],
                ],
            ):
                stats = save_remote_evaluations(eval_df)

        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["total"], 2)


if __name__ == "__main__":
    unittest.main()
