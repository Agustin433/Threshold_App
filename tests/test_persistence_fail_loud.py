"""Bloque "fallar fuerte": la app no puede decir que guardo si Supabase no confirmo.

Casos: key anon ignorada, chequeo de esquema contra la base (400 de
PostgREST), guardados parciales con conteo de filas, respuestas vacias,
banners persistentes y su cableado en app.py.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from modules import persistence_guard, remote_store
from modules.data_loader import EVALUATION_DB_COLUMN_MAP
from modules.remote_store import (
    RemoteSaveError,
    SupabaseHTTPError,
    check_remote_schema,
    save_remote_dataset,
    save_remote_evaluations,
    supabase_dataset_store_enabled,
    supabase_evaluations_enabled,
    supabase_key_role,
)

APP_PY_PATH = Path(__file__).resolve().parent.parent / "app.py"
TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_fail_loud"

SUPABASE_ENV_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "THRESHOLD_SUPABASE_URL",
    "THRESHOLD_SUPABASE_KEY",
)


@contextmanager
def patched_env(updates: dict[str, str | None]):
    full = {key: None for key in SUPABASE_ENV_KEYS}
    full.update(updates)
    original = {key: os.environ.get(key) for key in full}
    try:
        for key, value in full.items():
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


SERVICE_ENV = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}


def _jwt(role: str) -> str:
    def enc(payload: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'HS256'})}.{enc({'role': role})}.firma"


def _http_400(column: str) -> SupabaseHTTPError:
    body = json.dumps({"code": "42703", "message": f"column evaluations.{column} does not exist"})
    return SupabaseHTTPError(400, "Bad Request", body)


def _evaluations_frame(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Athlete": f"Atleta {i}", "Date": pd.Timestamp("2026-10-20"), "Source": "platform", "CMJ_cm": 30.0 + i}
            for i in range(n)
        ]
    )


class SupabaseConfigTest(unittest.TestCase):
    def test_anon_key_is_not_a_fallback(self):
        with patched_env({"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "anon"}):
            self.assertFalse(supabase_evaluations_enabled())
            self.assertFalse(supabase_dataset_store_enabled())

    def test_service_role_key_enables_persistence(self):
        with patched_env(SERVICE_ENV):
            self.assertTrue(supabase_evaluations_enabled())
            self.assertTrue(supabase_dataset_store_enabled())

    def test_key_role_detection(self):
        self.assertEqual(supabase_key_role(_jwt("anon")), "anon")
        self.assertEqual(supabase_key_role(_jwt("service_role")), "service_role")
        self.assertEqual(supabase_key_role("sb_publishable_abc"), "anon")
        self.assertEqual(supabase_key_role("sb_secret_abc"), "service_role")
        self.assertIsNone(supabase_key_role("cualquier-cosa"))


class RemoteSchemaCheckTest(unittest.TestCase):
    def test_ok_when_all_columns_exist(self):
        calls = []

        def fake_request(method, table, query=None, **kwargs):
            calls.append((method, table, dict(query or {})))
            return []

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            result = check_remote_schema()

        self.assertTrue(result["ok"])
        eval_call = next(call for call in calls if call[1] == "evaluations")
        self.assertEqual(eval_call[0], "GET")
        self.assertEqual(eval_call[2]["limit"], 0)
        self.assertEqual(
            set(eval_call[2]["select"].split(",")), set(EVALUATION_DB_COLUMN_MAP.values())
        )

    def test_400_names_every_missing_column(self):
        missing = {"cmj_landing_asym_pct", "dj_rsi"}

        def fake_request(method, table, query=None, **kwargs):
            selected = set((query or {}).get("select", "").split(","))
            hit = sorted(selected & missing)
            if table == "evaluations" and hit:
                raise _http_400(hit[0])
            return []

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            result = check_remote_schema()

        self.assertFalse(result["ok"])
        evaluations = next(item for item in result["tables"] if item["table"] == "evaluations")
        self.assertEqual(sorted(evaluations["missing"]), sorted(missing))
        messages = persistence_guard.persistence_banner_messages(
            persistence_enabled=True, schema=result, save_failures=None, pending_evaluations=0
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("cmj_landing_asym_pct", messages[0])
        self.assertIn("dj_rsi", messages[0])

    def test_non_400_error_is_reported_not_swallowed(self):
        def fake_request(method, table, query=None, **kwargs):
            raise SupabaseHTTPError(401, "Unauthorized", '{"message":"Invalid API key"}')

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            result = check_remote_schema()

        self.assertFalse(result["ok"])
        messages = persistence_guard.persistence_banner_messages(
            persistence_enabled=True, schema=result, save_failures=None, pending_evaluations=0
        )
        self.assertTrue(any("Invalid API key" in message for message in messages))

    def test_anon_key_configured_as_service_key_is_flagged(self):
        with patched_env({"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": _jwt("anon")}), patch.object(
            remote_store, "_supabase_request", return_value=[]
        ):
            result = check_remote_schema()
        self.assertFalse(result["ok"])
        self.assertEqual(result["key_role"], "anon")

    def test_check_is_cached_per_session(self):
        state: dict = {}
        calls = []

        def checker():
            calls.append(1)
            return {"enabled": True, "ok": True, "key_role": None, "tables": []}

        persistence_guard.get_remote_schema_check(state, checker)
        persistence_guard.get_remote_schema_check(state, checker)
        self.assertEqual(len(calls), 1)
        persistence_guard.get_remote_schema_check(state, checker, force=True)
        self.assertEqual(len(calls), 2)

    def test_checker_exception_becomes_error_not_crash(self):
        state: dict = {}

        def checker():
            raise RuntimeError("sin red")

        result = persistence_guard.get_remote_schema_check(state, checker)
        self.assertFalse(result["ok"])
        self.assertIn("sin red", result["tables"][0]["detail"])


class RemoteSaveFailuresTest(unittest.TestCase):
    def test_evaluations_400_reports_unsaved_rows(self):
        posted = []

        def fake_request(method, table, query=None, payload=None, **kwargs):
            if method == "PATCH":
                return []
            posted.append(payload)
            if len(posted) == 2:
                raise _http_400("cmj_cm")
            return [payload]

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            with self.assertRaises(RemoteSaveError) as ctx:
                save_remote_evaluations(_evaluations_frame(3))

        exc = ctx.exception
        self.assertEqual((exc.saved, exc.total, exc.failed), (1, 3, 2))
        self.assertIn("2 de 3", str(exc))
        self.assertIn("42703", str(exc))
        message = persistence_guard.describe_remote_save_failure("Evaluaciones individuales", exc)
        self.assertIn("NO guardo 2 de 3", message)

    def test_evaluations_empty_insert_response_is_not_success(self):
        def fake_request(method, table, query=None, payload=None, **kwargs):
            return []

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            with self.assertRaises(RemoteSaveError) as ctx:
                save_remote_evaluations(_evaluations_frame(1))
        self.assertEqual(ctx.exception.saved, 0)

    def test_evaluations_success_counts_only_confirmed_rows(self):
        def fake_request(method, table, query=None, payload=None, **kwargs):
            if method == "PATCH":
                return [payload] if payload["athlete"] == "Atleta 0" else []
            return [payload]

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            stats = save_remote_evaluations(_evaluations_frame(2))
        self.assertEqual((stats["updated"], stats["inserted"]), (1, 1))

    def test_dataset_400_on_second_chunk_reports_unsaved_rows(self):
        df = pd.DataFrame(
            {"Athlete": [f"A{i}" for i in range(600)], "Date": ["2026-10-20"] * 600, "sRPE": [300.0] * 600}
        )
        chunks = []

        def fake_request(method, table, query=None, payload=None, **kwargs):
            chunks.append(len(payload))
            if len(chunks) == 2:
                raise SupabaseHTTPError(400, "Bad Request", '{"code":"PGRST204"}')
            return payload

        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", side_effect=fake_request):
            with self.assertRaises(RemoteSaveError) as ctx:
                save_remote_dataset("rpe_df", df)

        exc = ctx.exception
        self.assertEqual(chunks, [500, 100])
        self.assertEqual((exc.saved, exc.total, exc.failed), (500, 600, 100))
        self.assertIn("100 de 600", str(exc))

    def test_dataset_empty_response_is_not_success(self):
        df = pd.DataFrame({"Athlete": ["A"], "Date": ["2026-10-20"], "sRPE": [300.0]})
        with patched_env(SERVICE_ENV), patch.object(remote_store, "_supabase_request", return_value=[]):
            with self.assertRaises(RemoteSaveError):
                save_remote_dataset("rpe_df", df)


class BannerMessagesTest(unittest.TestCase):
    def test_no_persistence_banner(self):
        messages = persistence_guard.persistence_banner_messages(
            persistence_enabled=False, schema=None, save_failures=None, pending_evaluations=0
        )
        self.assertEqual(messages, [persistence_guard.NO_PERSISTENCE_MESSAGE])
        self.assertTrue(messages[0].startswith("Modo sin persistencia: nada se guarda"))

    def test_pending_queue_banner(self):
        messages = persistence_guard.persistence_banner_messages(
            persistence_enabled=True,
            schema={"enabled": True, "ok": True, "tables": []},
            save_failures=None,
            pending_evaluations=3,
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("Tenés 3 evaluación(es) SIN GUARDAR", messages[0])

    def test_save_failures_persist_until_cleared(self):
        state: dict = {}
        persistence_guard.record_remote_save_failure(
            "rpe_df", "RPE", RemoteSaveError(saved=0, total=5, detail="400"), state=state
        )
        messages = persistence_guard.persistence_banner_messages(
            persistence_enabled=True,
            schema={"enabled": True, "ok": True, "tables": []},
            save_failures=state[persistence_guard.SAVE_FAILURES_STATE_KEY],
            pending_evaluations=0,
        )
        self.assertTrue(any("NO guardo 5 de 5" in message for message in messages))
        persistence_guard.clear_remote_save_failure("rpe_df", state=state)
        self.assertEqual(state[persistence_guard.SAVE_FAILURES_STATE_KEY], {})


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = TEST_TMP_ROOT / f"store_{uuid.uuid4().hex[:8]}"
    try:
        (tmp_root / "store").mkdir(parents=True, exist_ok=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(tmp_root / "store")
        yield
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        shutil.rmtree(tmp_root, ignore_errors=True)
        if TEST_TMP_ROOT.exists() and not any(TEST_TMP_ROOT.iterdir()):
            TEST_TMP_ROOT.rmdir()


def _error_texts(at) -> list[str]:
    return [element.value for element in at.error]


class AppBannerWiringTest(unittest.TestCase):
    """Corre app.py real con AppTest para verificar que los banners se pintan."""

    def _run_app(self, session: dict | None = None):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(APP_PY_PATH), default_timeout=120)
        for key, value in (session or {}).items():
            at.session_state[key] = value
        at.run()
        self.assertFalse(at.exception, f"app.py lanzo: {at.exception}")
        return at

    def test_without_secrets_shows_no_persistence_banner(self):
        with isolated_store(), patched_env({}):
            at = self._run_app()
        self.assertTrue(
            any(text.startswith("Modo sin persistencia: nada se guarda") for text in _error_texts(at)),
            _error_texts(at),
        )

    def test_pending_queue_shows_unsaved_banner(self):
        record = {"Athlete": "Ana Lopez", "Date": pd.Timestamp("2026-10-20"), "test_type": "CMJ", "CMJ_cm": 31.0}
        with isolated_store(), patched_env({}):
            at = self._run_app({"eval_records": [record]})
        self.assertTrue(
            any("Tenés 1 evaluación(es) SIN GUARDAR" in text for text in _error_texts(at)),
            _error_texts(at),
        )

    def test_schema_400_shows_missing_column_banner(self):
        def fake_request(method, table, query=None, **kwargs):
            selected = (query or {}).get("select", "")
            if table == "evaluations" and (query or {}).get("limit") == 0 and "dj_rsi" in selected.split(","):
                raise _http_400("dj_rsi")
            return []

        with isolated_store(), patched_env(SERVICE_ENV), patch.object(
            remote_store, "_supabase_request", side_effect=fake_request
        ):
            at = self._run_app()
        texts = _error_texts(at)
        self.assertTrue(any("dj_rsi" in text and "desfasado" in text for text in texts), texts)
        self.assertFalse(any(text.startswith("Modo sin persistencia") for text in texts))


if __name__ == "__main__":
    unittest.main()
