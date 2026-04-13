from __future__ import annotations

import os
import shutil
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from modules.jump_analysis import _prepare_jump_df
from modules.load_monitoring import calc_acwr, calc_monotony_strain

RECENT_WEEKS = 6
RECENT_DAYS = RECENT_WEEKS * 7
MONOTONY_HIGH = 2.0

APP_ROOT = Path(__file__).resolve().parent
STORE_DIR_ENV_VAR = "THRESHOLD_STORE_DIR"
LEGACY_STORE_DIR = APP_ROOT / "data" / "store"


def _resolve_store_dir() -> Path:
    configured = os.environ.get(STORE_DIR_ENV_VAR, "").strip()
    if not configured:
        return APP_ROOT / ".local" / "store"
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = APP_ROOT / candidate
    return candidate.resolve()


STORE_DIR = _resolve_store_dir()
ATHLETE_REGISTRY_PATH = STORE_DIR / "athletes.csv"

DATASET_SPECS: dict[str, dict[str, object]] = {
    "rpe_df": {
        "filename": "rpe_history.csv",
        "date_col": "Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Date"],
    },
    "wellness_df": {
        "filename": "wellness_history.csv",
        "date_col": "Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Date"],
    },
    "completion_df": {
        "filename": "completion_history.csv",
        "date_col": "Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Date"],
    },
    "rep_load_df": {
        "filename": "rep_load_history.csv",
        "date_col": "Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Date", "Exercise"],
    },
    "raw_df": {
        "filename": "raw_workouts_history.csv",
        "date_col": "Assigned Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Assigned Date", "Exercise Name", "Set Number"],
    },
    "maxes_df": {
        "filename": "maxes_history.csv",
        "date_col": "Added Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Added Date", "Exercise Name"],
    },
    "jump_df": {
        "filename": "evaluations_history.csv",
        "date_col": "Date",
        "athlete_col": "Athlete",
        "dedupe_cols": ["Athlete", "Date"],
    },
}

DATASET_LABELS: dict[str, str] = {
    "rpe_df": "RPE + Tiempo",
    "wellness_df": "Wellness",
    "completion_df": "Completion",
    "rep_load_df": "Rep/Load",
    "raw_df": "Raw Workouts",
    "maxes_df": "Maxes",
    "jump_df": "Evaluaciones",
}

ACWR_ZONES = (
    (0.00, 0.80, "Subcarga", "#4A9FD4"),
    (0.80, 1.30, "Optimo", "#4FC97E"),
    (1.30, 1.50, "Precaucion", "#E8C84A"),
    (1.50, 9.99, "Alto riesgo", "#D94F4F"),
)


def _ensure_store_dir() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_store()


def _dataset_path(state_key: str) -> Path:
    spec = DATASET_SPECS[state_key]
    return STORE_DIR / str(spec["filename"])


def _legacy_dataset_path(state_key: str) -> Path:
    spec = DATASET_SPECS[state_key]
    return LEGACY_STORE_DIR / str(spec["filename"])


def _migrate_legacy_store() -> None:
    if STORE_DIR == LEGACY_STORE_DIR or not LEGACY_STORE_DIR.exists():
        return

    copy_pairs = [(LEGACY_STORE_DIR / "athletes.csv", ATHLETE_REGISTRY_PATH)]
    copy_pairs.extend((_legacy_dataset_path(state_key), _dataset_path(state_key)) for state_key in DATASET_SPECS)

    for source, target in copy_pairs:
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _empty_dataset_columns(state_key: str, columns: list[str] | None = None) -> list[str]:
    if columns:
        unique_columns: list[str] = []
        for column in columns:
            if column and column not in unique_columns:
                unique_columns.append(str(column))
        if unique_columns:
            return unique_columns

    spec = DATASET_SPECS[state_key]
    fallback_columns: list[str] = []
    athlete_col = spec.get("athlete_col")
    date_col = spec.get("date_col")
    dedupe_cols = spec.get("dedupe_cols") or []

    for column in [athlete_col, date_col, *dedupe_cols]:
        if column and column not in fallback_columns:
            fallback_columns.append(str(column))

    return fallback_columns or ["_empty"]


def _persist_empty_dataset(state_key: str, columns: list[str] | None = None) -> pd.DataFrame:
    empty_df = pd.DataFrame(columns=_empty_dataset_columns(state_key, columns))
    empty_df.to_csv(_dataset_path(state_key), index=False)
    return empty_df


def normalize_athlete_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = " ".join(str(value).strip().split())
    return text.title()


def collect_athlete_names(*frames: pd.DataFrame | None) -> list[str]:
    names: set[str] = set()
    for frame in frames:
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        for value in frame["Athlete"].dropna().tolist():
            normalized = normalize_athlete_name(value)
            if normalized:
                names.add(normalized)
    return sorted(names)


def load_athlete_registry() -> list[str]:
    _ensure_store_dir()
    if not ATHLETE_REGISTRY_PATH.exists():
        return []
    df = pd.read_csv(ATHLETE_REGISTRY_PATH)
    if df.empty:
        return []
    source_col = "Athlete" if "Athlete" in df.columns else df.columns[0]
    names = {
        normalize_athlete_name(value)
        for value in df[source_col].dropna().tolist()
        if normalize_athlete_name(value)
    }
    return sorted(names)


def persist_athlete_names(names: list[str]) -> list[str]:
    normalized = {
        normalize_athlete_name(name)
        for name in names
        if normalize_athlete_name(name)
    }
    merged = sorted(set(load_athlete_registry()) | normalized)
    _ensure_store_dir()
    pd.DataFrame({"Athlete": merged}).to_csv(ATHLETE_REGISTRY_PATH, index=False)
    return merged


def _normalize_frame(df: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    athlete_col = spec.get("athlete_col")
    date_col = spec.get("date_col")

    if athlete_col and athlete_col in result.columns:
        result[athlete_col] = result[athlete_col].map(normalize_athlete_name)
        result[athlete_col] = result[athlete_col].replace("", np.nan)

    if date_col and date_col in result.columns:
        result[date_col] = pd.to_datetime(result[date_col], errors="coerce").dt.normalize()
        result = result.dropna(subset=[date_col])

    return result.reset_index(drop=True)


def _sort_frame(df: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    sort_cols = []
    athlete_col = spec.get("athlete_col")
    date_col = spec.get("date_col")
    if athlete_col and athlete_col in df.columns:
        sort_cols.append(athlete_col)
    if date_col and date_col in df.columns:
        sort_cols.append(date_col)
    if sort_cols:
        df = df.sort_values(sort_cols)
    return df.reset_index(drop=True)


def _collapse_duplicate_rows(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    ordered_cols = [col for col in df.columns if col != "_merge_order"]

    for _, group in df.groupby(key_cols, dropna=False, sort=False):
        group = group.sort_values("_merge_order")
        merged_row: dict[str, object] = {}
        for col in ordered_cols:
            series = group[col]
            non_null = series[series.notna()]
            merged_row[col] = non_null.iloc[-1] if not non_null.empty else series.iloc[-1]
        rows.append(merged_row)

    return pd.DataFrame(rows)


def _dedupe_dataset_frame(df: pd.DataFrame, state_key: str) -> pd.DataFrame:
    spec = DATASET_SPECS[state_key]
    df = _normalize_frame(df, spec)
    if df.empty:
        return df

    dedupe_cols = [col for col in (spec.get("dedupe_cols") or []) if col in df.columns]
    if dedupe_cols:
        df = df.copy()
        df["_merge_order"] = np.arange(len(df))
        df = _collapse_duplicate_rows(df, dedupe_cols)
    else:
        df = df.drop_duplicates().reset_index(drop=True)

    return _sort_frame(df, spec)


def merge_dataset(existing: pd.DataFrame, incoming: pd.DataFrame, state_key: str) -> pd.DataFrame:
    spec = DATASET_SPECS[state_key]
    existing = _normalize_frame(existing, spec)
    incoming = _normalize_frame(incoming, spec)

    if existing.empty:
        merged = incoming
    elif incoming.empty:
        merged = existing
    else:
        combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
        dedupe_cols = [col for col in (spec.get("dedupe_cols") or []) if col in combined.columns]

        if dedupe_cols:
            combined["_merge_order"] = np.arange(len(combined))
            merged = _collapse_duplicate_rows(combined, dedupe_cols)
        else:
            merged = combined.drop_duplicates().reset_index(drop=True)

    athlete_col = spec.get("athlete_col")
    if athlete_col and athlete_col in merged.columns:
        persist_athlete_names(merged[athlete_col].dropna().tolist())

    return _sort_frame(merged, spec)


def read_full_dataset(state_key: str) -> pd.DataFrame:
    _ensure_store_dir()
    path = _dataset_path(state_key)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    normalized = _sort_frame(_normalize_frame(df, DATASET_SPECS[state_key]), DATASET_SPECS[state_key])
    if state_key == "jump_df":
        # Re-canonicalize historical EUR values on read so legacy percentages
        # (for example 16.7) become ratio values (1.167) without rewriting the
        # stored CSV schema.
        normalized = _prepare_jump_df(normalized)
    return normalized


def save_dataset(state_key: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return read_full_dataset(state_key)

    _ensure_store_dir()
    merged = merge_dataset(read_full_dataset(state_key), df, state_key)
    merged.to_csv(_dataset_path(state_key), index=False)
    return merged


def overwrite_dataset(state_key: str, df: pd.DataFrame | None) -> pd.DataFrame:
    _ensure_store_dir()
    path = _dataset_path(state_key)

    if df is None or df.empty:
        existing_columns = read_full_dataset(state_key).columns.tolist() if path.exists() else None
        return _persist_empty_dataset(state_key, existing_columns)

    normalized = _dedupe_dataset_frame(df, state_key)
    if normalized.empty:
        return _persist_empty_dataset(state_key, df.columns.tolist())

    athlete_col = DATASET_SPECS[state_key].get("athlete_col")
    if athlete_col and athlete_col in normalized.columns:
        persist_athlete_names(normalized[athlete_col].dropna().tolist())

    normalized.to_csv(path, index=False)
    return normalized


def filter_recent_window(df: pd.DataFrame, date_col: str, weeks: int = RECENT_WEEKS) -> pd.DataFrame:
    if df is None or df.empty or date_col not in df.columns:
        return pd.DataFrame() if df is None else df

    recent_df = df.copy()
    recent_df[date_col] = pd.to_datetime(recent_df[date_col], errors="coerce").dt.normalize()
    recent_df = recent_df.dropna(subset=[date_col])
    if recent_df.empty:
        return recent_df

    max_date = recent_df[date_col].max()
    cutoff = max_date - pd.Timedelta(weeks=weeks)
    return recent_df[recent_df[date_col] >= cutoff].reset_index(drop=True)


def load_recent_dataset(state_key: str, weeks: int = RECENT_WEEKS) -> pd.DataFrame:
    spec = DATASET_SPECS[state_key]
    df = read_full_dataset(state_key)
    date_col = str(spec["date_col"])
    df = filter_recent_window(df, date_col, weeks=weeks)
    return _sort_frame(df, spec)


def load_recent_state(weeks: int = RECENT_WEEKS) -> dict[str, pd.DataFrame | None]:
    state: dict[str, pd.DataFrame | None] = {}
    for state_key in DATASET_SPECS:
        df = load_recent_dataset(state_key, weeks=weeks)
        state[state_key] = None if df.empty else df
    return state


def load_full_history_state(keys: list[str] | None = None) -> dict[str, pd.DataFrame | None]:
    selected_keys = keys or list(DATASET_SPECS.keys())
    state: dict[str, pd.DataFrame | None] = {}
    for state_key in selected_keys:
        df = read_full_dataset(state_key)
        state[state_key] = None if df.empty else df
    return state


def build_load_models(rpe_df: pd.DataFrame | None) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    if rpe_df is None or rpe_df.empty:
        return {}, {}
    if not {"Athlete", "Date", "sRPE"}.issubset(rpe_df.columns):
        return {}, {}

    source = rpe_df.copy()
    source["Athlete"] = source["Athlete"].map(normalize_athlete_name)
    source["Date"] = pd.to_datetime(source["Date"], errors="coerce").dt.normalize()
    source["sRPE"] = pd.to_numeric(source["sRPE"], errors="coerce")
    source = source.dropna(subset=["Athlete", "Date", "sRPE"])
    if source.empty:
        return {}, {}

    acwr_dict: dict[str, pd.DataFrame] = {}
    mono_dict: dict[str, pd.DataFrame] = {}

    for athlete in sorted(source["Athlete"].unique()):
        athlete_df = source[source["Athlete"] == athlete].sort_values("Date")
        acwr_df = calc_acwr(athlete_df["sRPE"], pd.DatetimeIndex(athlete_df["Date"]))
        mono_df = calc_monotony_strain(acwr_df)
        acwr_dict[athlete] = filter_recent_window(acwr_df, "Date")
        mono_dict[athlete] = filter_recent_window(mono_df, "Semana")

    return acwr_dict, mono_dict


def build_dataset_summaries(
    state: dict[str, pd.DataFrame | None],
    weeks: int = RECENT_WEEKS,
    keys: list[str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for state_key, spec in DATASET_SPECS.items():
        if keys is not None and state_key not in keys:
            continue

        df = state.get(state_key)
        if df is None or df.empty:
            continue

        date_col = str(spec["date_col"])
        athlete_col = spec.get("athlete_col")
        latest = None
        earliest = None
        if date_col in df.columns:
            dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            if not dates.empty:
                earliest = dates.min().normalize()
                latest = dates.max().normalize()

        athlete_count = None
        if athlete_col and athlete_col in df.columns:
            athlete_count = int(df[athlete_col].dropna().nunique())

        if latest is not None:
            window_start = (latest - pd.Timedelta(weeks=weeks)).normalize()
            window_label = f"{window_start:%d/%m/%Y} - {latest:%d/%m/%Y}"
            latest_label = latest.strftime("%d/%m/%Y")
            earliest_label = earliest.strftime("%d/%m/%Y") if earliest is not None else "—"
        else:
            window_label = "Sin fecha"
            latest_label = "—"
            earliest_label = "—"

        rows.append({
            "state_key": state_key,
            "Dataset": DATASET_LABELS.get(state_key, state_key),
            "Registros": int(len(df)),
            "Atletas": athlete_count,
            "Primera fecha": earliest_label,
            "Ultima fecha": latest_label,
            "Ventana activa": window_label,
        })

    return rows


def find_athlete_name_conflicts(
    names: list[str] | None = None,
    threshold: float = 0.86,
) -> list[dict[str, object]]:
    candidate_names = sorted(set(names or load_athlete_registry()))
    conflicts: list[dict[str, object]] = []

    for left, right in combinations(candidate_names, 2):
        l_norm = normalize_athlete_name(left)
        r_norm = normalize_athlete_name(right)
        if not l_norm or not r_norm or l_norm == r_norm:
            continue

        similarity = SequenceMatcher(None, l_norm.casefold(), r_norm.casefold()).ratio()
        shared_tokens = set(l_norm.casefold().split()) & set(r_norm.casefold().split())
        strong_token_overlap = len(shared_tokens) >= 2

        if similarity >= threshold or strong_token_overlap:
            conflicts.append({
                "Nombre A": l_norm,
                "Nombre B": r_norm,
                "Similaridad": round(similarity, 2),
            })

    conflicts.sort(key=lambda row: row["Similaridad"], reverse=True)
    return conflicts


def rename_athlete_in_store(old_name: str, new_name: str) -> dict[str, object]:
    old_norm = normalize_athlete_name(old_name)
    new_norm = normalize_athlete_name(new_name)

    if not old_norm or not new_norm:
        raise ValueError("Debes indicar un nombre actual y un nombre nuevo validos.")
    if old_norm == new_norm:
        raise ValueError("El nombre nuevo debe ser distinto al nombre actual.")

    _ensure_store_dir()
    changed: dict[str, int] = {}

    for state_key, spec in DATASET_SPECS.items():
        athlete_col = spec.get("athlete_col")
        if not athlete_col:
            continue

        path = _dataset_path(state_key)
        if not path.exists():
            continue

        df = read_full_dataset(state_key)
        if df.empty or athlete_col not in df.columns:
            continue

        athlete_series = df[athlete_col].map(normalize_athlete_name)
        mask = athlete_series == old_norm
        if not mask.any():
            continue

        df = df.copy()
        df.loc[mask, athlete_col] = new_norm
        df = _dedupe_dataset_frame(df, state_key)
        df.to_csv(path, index=False)
        changed[state_key] = int(mask.sum())

    registry_names = sorted((set(load_athlete_registry()) - {old_norm}) | {new_norm})
    pd.DataFrame({"Athlete": registry_names}).to_csv(ATHLETE_REGISTRY_PATH, index=False)

    return {
        "old": old_norm,
        "new": new_norm,
        "datasets": changed,
        "total": sum(changed.values()),
    }
