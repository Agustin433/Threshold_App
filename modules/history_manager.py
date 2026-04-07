"""Helpers for UI-driven history review, trimming and remote sync."""

from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from local_store import (
    DATASET_LABELS,
    DATASET_SPECS,
    RECENT_WEEKS,
    STORE_DIR,
    build_load_models,
    load_recent_state,
    normalize_athlete_name,
    overwrite_dataset,
)
from modules.data_loader import (
    EVALUATION_DB_COLUMN_MAP,
    EVALUATION_PERSIST_COLUMNS,
)
from modules.remote_store import (
    REMOTE_DATASET_KEYS,
    _supabase_dataset_store_config,
    _supabase_evaluations_config,
    _supabase_request,
    dataset_df_to_remote_records as shared_dataset_df_to_remote_records,
    jump_df_to_db_records as shared_jump_df_to_db_records,
    load_remote_dataset as shared_load_remote_dataset,
    load_remote_evaluations_frame as shared_load_remote_evaluations_frame,
    supabase_dataset_store_enabled,
    supabase_evaluations_enabled,
)

HISTORY_BACKUP_DIRNAME = "_history_backups"


def _history_backup_dir(state_key: str):
    backup_dir = STORE_DIR / HISTORY_BACKUP_DIRNAME / state_key
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _slugify_backup_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "snapshot"


def create_history_backup(
    state_key: str,
    df: pd.DataFrame | None,
    *,
    source: str,
    action: str,
) -> dict[str, object]:
    backup_df = df.copy() if df is not None else pd.DataFrame()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_token = _slugify_backup_token(source)
    action_token = _slugify_backup_token(action)
    backup_dir = _history_backup_dir(state_key)

    backup_path = backup_dir / f"{timestamp}_{state_key}_{source_token}_{action_token}.csv"
    counter = 2
    while backup_path.exists():
        backup_path = backup_dir / f"{timestamp}_{state_key}_{source_token}_{action_token}_{counter}.csv"
        counter += 1

    backup_df.to_csv(backup_path, index=False)
    return {
        "path": str(backup_path),
        "filename": backup_path.name,
        "rows": int(len(backup_df)),
        "source": source,
        "action": action,
        "dataset": DATASET_LABELS.get(state_key, state_key),
        "state_key": state_key,
    }


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
    return __import__("hashlib").sha1(serialized.encode("utf-8")).hexdigest()


def _dataset_df_to_remote_records(state_key: str, df: pd.DataFrame) -> list[dict]:
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


def _jump_df_to_db_records(df: pd.DataFrame) -> list[dict]:
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


_dataset_df_to_remote_records = shared_dataset_df_to_remote_records
_jump_df_to_db_records = shared_jump_df_to_db_records


def _chunked(items: list[str], chunk_size: int = 100) -> list[list[str]]:
    return [items[idx: idx + chunk_size] for idx in range(0, len(items), chunk_size)]


def filter_history_frame(
    df: pd.DataFrame | None,
    *,
    athlete: str = "Todos",
    athlete_col: str | None = "Athlete",
    date_col: str | None = None,
    date_from=None,
    date_to=None,
    text_query: str = "",
) -> tuple[pd.DataFrame, pd.Series]:
    if df is None or df.empty:
        empty_index = pd.Index([], dtype=int)
        return pd.DataFrame(), pd.Series([], index=empty_index, dtype=bool)

    mask = pd.Series(True, index=df.index)

    if athlete_col and athlete_col in df.columns and athlete and athlete != "Todos":
        athlete_series = df[athlete_col].astype(str).str.strip()
        mask &= athlete_series == athlete

    if date_col and date_col in df.columns:
        parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
        if date_from:
            mask &= parsed_dates >= pd.Timestamp(date_from).normalize()
        if date_to:
            mask &= parsed_dates <= pd.Timestamp(date_to).normalize()

    query = text_query.strip().casefold()
    if query:
        text_df = df.astype(str).apply(lambda col: col.str.casefold().str.contains(query, na=False))
        mask &= text_df.any(axis=1)

    filtered = df.loc[mask].copy().reset_index(drop=True)
    return filtered, mask


def refresh_session_state_from_store(*, weeks: int = RECENT_WEEKS) -> None:
    stored_state = load_recent_state(weeks=weeks)
    for key in list(DATASET_SPECS.keys()):
        st.session_state[key] = stored_state.get(key)

    acwr_dict, mono_dict = build_load_models(st.session_state.get("rpe_df"))
    st.session_state.acwr_dict = acwr_dict or None
    st.session_state.mono_dict = mono_dict or None


def replace_local_history(state_key: str, df: pd.DataFrame | None) -> pd.DataFrame:
    updated_df = overwrite_dataset(state_key, df)
    refresh_session_state_from_store()
    return updated_df


def load_remote_history_frame(state_key: str) -> pd.DataFrame:
    if state_key == "jump_df":
        return shared_load_remote_evaluations_frame()
    return shared_load_remote_dataset(state_key)


def replace_remote_history(state_key: str, df: pd.DataFrame | None) -> dict[str, object]:
    if state_key == "jump_df":
        return _replace_remote_evaluations(df)
    return _replace_remote_dataset(state_key, df)


def _replace_remote_dataset(state_key: str, df: pd.DataFrame | None) -> dict[str, object]:
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return {"enabled": False, "deleted": 0, "upserted": 0, "dataset": DATASET_LABELS.get(state_key, state_key)}

    _, _, table = _supabase_dataset_store_config()
    desired_records = _dataset_df_to_remote_records(state_key, df if df is not None else pd.DataFrame())
    desired_keys = {record["row_key"] for record in desired_records}

    existing_rows = []
    offset = 0
    page_size = 1000
    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={"select": "row_key", "dataset_key": f"eq.{state_key}", "limit": page_size, "offset": offset},
        ) or []
        if not batch:
            break
        existing_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    existing_keys = {row.get("row_key") for row in existing_rows if row.get("row_key")}
    deleted = 0
    keys_to_delete = sorted(existing_keys - desired_keys)
    for chunk in _chunked(keys_to_delete):
        deleted_rows = _supabase_request(
            "DELETE",
            table,
            query={"dataset_key": f"eq.{state_key}", "row_key": f"in.({','.join(chunk)})"},
            prefer="return=representation",
        ) or []
        deleted += len(deleted_rows) if deleted_rows else len(chunk)

    upserted = 0
    if desired_records:
        upserted_rows = _supabase_request(
            "POST",
            table,
            query={"on_conflict": "dataset_key,row_key"},
            payload=desired_records,
            prefer="resolution=merge-duplicates,return=representation",
        ) or []
        upserted = len(upserted_rows) if upserted_rows else len(desired_records)

    return {"enabled": True, "deleted": deleted, "upserted": upserted, "dataset": DATASET_LABELS.get(state_key, state_key)}


def _replace_remote_evaluations(df: pd.DataFrame | None) -> dict[str, object]:
    if not supabase_evaluations_enabled():
        return {"enabled": False, "deleted": 0, "upserted": 0, "dataset": DATASET_LABELS.get("jump_df", "Evaluaciones")}

    _, _, table = _supabase_evaluations_config()
    desired_records = _jump_df_to_db_records(df if df is not None else pd.DataFrame())
    desired_keys = {(record["athlete"], record["date"]) for record in desired_records}

    existing_rows = []
    offset = 0
    page_size = 1000
    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={"select": "athlete,date", "order": "date.asc,athlete.asc", "limit": page_size, "offset": offset},
            evaluations=True,
        ) or []
        if not batch:
            break
        existing_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    deleted = 0
    existing_keys = {(row.get("athlete"), row.get("date")) for row in existing_rows if row.get("athlete") and row.get("date")}
    for athlete, event_date in sorted(existing_keys - desired_keys):
        deleted_rows = _supabase_request(
            "DELETE",
            table,
            query={"athlete": f"eq.{athlete}", "date": f"eq.{event_date}"},
            prefer="return=representation",
            evaluations=True,
        ) or []
        deleted += len(deleted_rows) if deleted_rows else 1

    upserted = 0
    for record in desired_records:
        updated_rows = _supabase_request(
            "PATCH",
            table,
            query={"athlete": f"eq.{record['athlete']}", "date": f"eq.{record['date']}"},
            payload=record,
            prefer="return=representation",
            evaluations=True,
        ) or []
        if updated_rows:
            upserted += len(updated_rows)
            continue
        inserted_rows = _supabase_request(
            "POST",
            table,
            payload=record,
            prefer="return=representation",
            evaluations=True,
        ) or []
        upserted += len(inserted_rows) if inserted_rows else 1

    return {"enabled": True, "deleted": deleted, "upserted": upserted, "dataset": DATASET_LABELS.get("jump_df", "Evaluaciones")}
