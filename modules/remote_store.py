"""Shared Supabase config and request helpers for persistence flows."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

from modules.data_loader import SUPABASE_EVALUATIONS_TABLE

SUPABASE_DATASETS_TABLE = "dataset_rows"
REMOTE_DATASET_KEYS = ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df"]


def _get_secret_or_env(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def _supabase_dataset_store_config() -> tuple[str | None, str | None, str]:
    url = _get_secret_or_env("SUPABASE_URL") or _get_secret_or_env("THRESHOLD_SUPABASE_URL")
    key = (
        _get_secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
        or _get_secret_or_env("SUPABASE_KEY")
        or _get_secret_or_env("SUPABASE_ANON_KEY")
        or _get_secret_or_env("THRESHOLD_SUPABASE_KEY")
    )
    table = _get_secret_or_env("SUPABASE_DATASETS_TABLE") or SUPABASE_DATASETS_TABLE
    return url, key, table


def _supabase_evaluations_config() -> tuple[str | None, str | None, str]:
    url = _get_secret_or_env("SUPABASE_URL") or _get_secret_or_env("THRESHOLD_SUPABASE_URL")
    key = (
        _get_secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
        or _get_secret_or_env("SUPABASE_KEY")
        or _get_secret_or_env("SUPABASE_ANON_KEY")
        or _get_secret_or_env("THRESHOLD_SUPABASE_KEY")
    )
    table = _get_secret_or_env("SUPABASE_EVALUATIONS_TABLE") or SUPABASE_EVALUATIONS_TABLE
    return url, key, table


def supabase_dataset_store_enabled() -> bool:
    url, key, table = _supabase_dataset_store_config()
    return bool(url and key and table)


def supabase_evaluations_enabled() -> bool:
    url, key, table = _supabase_evaluations_config()
    return bool(url and key and table)


def _supabase_request(
    method: str,
    table: str,
    query: dict | None = None,
    payload: list[dict] | dict | None = None,
    prefer: str | None = None,
    *,
    evaluations: bool = False,
):
    url, key, _ = _supabase_evaluations_config() if evaluations else _supabase_dataset_store_config()
    if not url or not key:
        raise RuntimeError("Supabase no configurado")

    endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
    if query:
        qs = urllib.parse.urlencode(query, doseq=True, safe="*,():")
        endpoint = f"{endpoint}?{qs}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar a Supabase: {exc.reason}") from exc
