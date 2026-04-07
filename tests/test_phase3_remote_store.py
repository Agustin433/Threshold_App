from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from modules.remote_store import _supabase_request, supabase_dataset_store_enabled, supabase_evaluations_enabled


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


if __name__ == "__main__":
    unittest.main()
