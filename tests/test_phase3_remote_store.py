from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from modules.remote_store import (
    _supabase_request,
    dataset_df_to_remote_records,
    load_remote_dataset,
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
