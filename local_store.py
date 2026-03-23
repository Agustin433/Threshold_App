from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RECENT_WEEKS = 6
RECENT_DAYS = RECENT_WEEKS * 7
MONOTONY_HIGH = 2.0

STORE_DIR = Path(__file__).resolve().parent / "data" / "store"
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
        "athlete_col": None,
        "dedupe_cols": ["Date"],
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
        "dedupe_cols": None,
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

ACWR_ZONES = (
    (0.00, 0.80, "Subcarga", "#4A9FD4"),
    (0.80, 1.30, "Optimo", "#4FC97E"),
    (1.30, 1.50, "Precaucion", "#E8C84A"),
    (1.50, 9.99, "Alto riesgo", "#D94F4F"),
)


def _ensure_store_dir() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def _dataset_path(state_key: str) -> Path:
    spec = DATASET_SPECS[state_key]
    return STORE_DIR / str(spec["filename"])


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
    path = _dataset_path(state_key)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    return _sort_frame(_normalize_frame(df, DATASET_SPECS[state_key]), DATASET_SPECS[state_key])


def save_dataset(state_key: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return read_full_dataset(state_key)

    _ensure_store_dir()
    merged = merge_dataset(read_full_dataset(state_key), df, state_key)
    merged.to_csv(_dataset_path(state_key), index=False)
    return merged


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


def _classify_acwr(value: float) -> str:
    if pd.isna(value):
        return "Sin datos"
    for lower, upper, label, _ in ACWR_ZONES:
        if lower <= value < upper:
            return label
    return "Alto riesgo"


def _acwr_color(value: float) -> str:
    if pd.isna(value):
        return "#5A6A7A"
    for lower, upper, _, color in ACWR_ZONES:
        if lower <= value < upper:
            return color
    return "#D94F4F"


def calc_acwr(srpe_series: pd.Series, dates: pd.DatetimeIndex, method: str = "ewma") -> pd.DataFrame:
    daily = pd.Series(srpe_series.values, index=dates).sort_index()
    daily = daily.resample("D").sum().fillna(0)

    result = pd.DataFrame({"Date": daily.index, "sRPE_diario": daily.values})
    result["Aguda_7d"] = result["sRPE_diario"].rolling(7, min_periods=1).mean()
    result["Cronica_28d"] = result["sRPE_diario"].rolling(28, min_periods=1).mean()
    result["ACWR_Classic"] = np.where(
        result["Cronica_28d"] > 0,
        result["Aguda_7d"] / result["Cronica_28d"],
        0,
    )
    result["EWMA_Aguda"] = result["sRPE_diario"].ewm(alpha=0.28, adjust=False).mean()
    result["EWMA_Cronica"] = result["sRPE_diario"].ewm(alpha=0.07, adjust=False).mean()
    result["ACWR_EWMA"] = np.where(
        result["EWMA_Cronica"] > 0,
        result["EWMA_Aguda"] / result["EWMA_Cronica"],
        0,
    )
    result["ACWR"] = result["ACWR_EWMA"] if method == "ewma" else result["ACWR_Classic"]
    result["Zona"] = result["ACWR"].apply(_classify_acwr)
    result["Zona_Color"] = result["ACWR"].apply(_acwr_color)
    return result


def calc_monotony_strain(srpe_daily: pd.DataFrame) -> pd.DataFrame:
    weekly = srpe_daily.set_index("Date")["sRPE_diario"].resample("W").agg(["sum", "mean", "std"]).reset_index()
    weekly.columns = ["Semana", "Carga_Total", "Media", "SD"]
    weekly["SD"] = weekly["SD"].fillna(0.001)
    weekly["Monotonia"] = weekly["Media"] / weekly["SD"]
    weekly["Strain"] = weekly["Carga_Total"] * weekly["Monotonia"]
    weekly["Alerta"] = weekly["Monotonia"] > MONOTONY_HIGH
    return weekly


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
