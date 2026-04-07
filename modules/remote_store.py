"""Shared Supabase config and request helpers for persistence flows."""

from __future__ import annotations

import json
import os
import hashlib
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import streamlit as st

from local_store import DATASET_SPECS, normalize_athlete_name
from modules.data_loader import EVALUATION_DB_COLUMN_MAP, EVALUATION_PERSIST_COLUMNS, SUPABASE_EVALUATIONS_TABLE
from modules.jump_analysis import _prepare_jump_df

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


def _json_safe_value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _dataset_event_date(value) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _dataset_row_signature(state_key: str, payload: dict[str, object]) -> str:
    spec = DATASET_SPECS.get(state_key, {})
    dedupe_cols = spec.get("dedupe_cols") or sorted(payload.keys())
    key_payload = {col: payload.get(col) for col in dedupe_cols if col in payload}
    if not key_payload:
        key_payload = payload
    serialized = json.dumps(key_payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def dataset_df_to_remote_records(state_key: str, df: pd.DataFrame) -> list[dict]:
    if state_key not in REMOTE_DATASET_KEYS or df is None or df.empty:
        return []

    spec = DATASET_SPECS.get(state_key, {})
    date_col = spec.get("date_col")
    athlete_col = spec.get("athlete_col")
    records: list[dict] = []

    for _, row in df.iterrows():
        payload: dict[str, object] = {}
        for col in df.columns:
            safe_value = _json_safe_value(row.get(col))
            if safe_value is not None:
                payload[col] = safe_value
        if not payload:
            continue

        if athlete_col and athlete_col in payload:
            payload[athlete_col] = normalize_athlete_name(payload[athlete_col])

        record = {
            "dataset_key": state_key,
            "row_key": _dataset_row_signature(state_key, payload),
            "payload": payload,
        }
        if athlete_col and payload.get(athlete_col):
            record["athlete"] = normalize_athlete_name(payload[athlete_col])
        if date_col:
            event_date = _dataset_event_date(payload.get(date_col))
            if event_date:
                record["event_date"] = event_date
        records.append(record)
    return records


def jump_df_to_db_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []

    records: list[dict] = []
    for _, row in df.iterrows():
        record: dict[str, object] = {}
        for app_col in EVALUATION_PERSIST_COLUMNS:
            if app_col not in row.index:
                continue
            value = row[app_col]
            if pd.isna(value):
                continue
            db_col = EVALUATION_DB_COLUMN_MAP[app_col]
            if app_col == "Date":
                record[db_col] = pd.Timestamp(value).date().isoformat()
            elif app_col == "Athlete":
                record[db_col] = normalize_athlete_name(value)
            elif isinstance(value, (np.integer, int)):
                record[db_col] = int(value)
            elif isinstance(value, (np.floating, float)):
                record[db_col] = float(value)
            else:
                record[db_col] = value
        if record.get("athlete") and record.get("date"):
            records.append(record)
    return records


def save_remote_dataset(state_key: str, df: pd.DataFrame) -> dict[str, int | bool]:
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return {"enabled": False, "upserted": 0}

    payload = dataset_df_to_remote_records(state_key, df)
    if not payload:
        return {"enabled": True, "upserted": 0}

    _, _, table = _supabase_dataset_store_config()
    rows = _supabase_request(
        "POST",
        table,
        query={"on_conflict": "dataset_key,row_key"},
        payload=payload,
        prefer="resolution=merge-duplicates,return=representation",
    ) or []
    return {"enabled": True, "upserted": len(rows) if rows else len(payload)}


def load_remote_dataset(state_key: str) -> pd.DataFrame:
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return pd.DataFrame()

    _, _, table = _supabase_dataset_store_config()
    rows = []
    offset = 0
    page_size = 1000

    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={
                "select": "payload",
                "dataset_key": f"eq.{state_key}",
                "order": "event_date.asc.nullslast,row_key.asc",
                "limit": page_size,
                "offset": offset,
            },
        ) or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    payloads = [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]
    return pd.DataFrame(payloads) if payloads else pd.DataFrame()


def save_remote_evaluations(df: pd.DataFrame) -> dict[str, int | bool]:
    if not supabase_evaluations_enabled():
        return {"enabled": False, "inserted": 0, "updated": 0, "total": 0}

    payload = jump_df_to_db_records(df)
    if not payload:
        return {"enabled": True, "inserted": 0, "updated": 0, "total": 0}

    _, _, table = _supabase_evaluations_config()
    inserted = 0
    updated = 0

    for record in payload:
        filters = {
            "select": "athlete,date",
            "athlete": f"eq.{record['athlete']}",
            "date": f"eq.{record['date']}",
        }
        updated_rows = _supabase_request(
            "PATCH",
            table,
            query=filters,
            payload=record,
            prefer="return=representation",
            evaluations=True,
        )
        if updated_rows:
            updated += len(updated_rows)
            continue

        inserted_rows = _supabase_request(
            "POST",
            table,
            payload=record,
            prefer="return=representation",
            evaluations=True,
        )
        inserted += len(inserted_rows or [record])

    return {
        "enabled": True,
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
    }


def load_remote_evaluations_frame() -> pd.DataFrame:
    if not supabase_evaluations_enabled():
        return pd.DataFrame()

    _, _, table = _supabase_evaluations_config()
    rows = []
    offset = 0
    page_size = 1000

    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={
                "select": "*",
                "order": "date.asc,athlete.asc",
                "limit": page_size,
                "offset": offset,
            },
            evaluations=True,
        ) or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if not rows:
        return pd.DataFrame()

    rename_map = {db_col: app_col for app_col, db_col in EVALUATION_DB_COLUMN_MAP.items()}
    return pd.DataFrame(rows).rename(columns=rename_map)


def load_remote_evaluations() -> pd.DataFrame:
    frame = load_remote_evaluations_frame()
    if frame.empty:
        return pd.DataFrame()

    keep_cols = [app_col for app_col in EVALUATION_DB_COLUMN_MAP if app_col in frame.columns]
    return _prepare_jump_df(frame[keep_cols])
