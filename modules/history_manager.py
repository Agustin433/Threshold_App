"""Helpers for UI-driven history review, trimming and remote sync."""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import streamlit as st

from local_store import (
    DATASET_LABELS,
    DATASET_SPECS,
    RECENT_WEEKS,
    STORE_DIR,
    build_load_models,
    load_recent_state,
    overwrite_dataset,
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


# Runtime now uses the shared remote serializers from modules.remote_store.
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
