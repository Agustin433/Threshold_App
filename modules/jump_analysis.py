"""Shared jump evaluation calculations and normalization."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _normalize_eur_series_to_ratio(series: pd.Series) -> pd.Series:
    """Normalize EUR values to a canonical CMJ/SJ ratio."""
    result = pd.to_numeric(series, errors="coerce")
    pct_mask = result > 5
    result.loc[pct_mask] = 1 + (result.loc[pct_mask] / 100)
    return result.round(3)


def calc_eur(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical EUR as a CMJ/SJ ratio."""
    if "EUR" in df.columns:
        # Historical files may still store EUR as percentage. Normalize first so
        # downstream z-scores and NM profile always see ratio values.
        df["EUR"] = _normalize_eur_series_to_ratio(df["EUR"])
    if "CMJ_cm" in df.columns and "SJ_cm" in df.columns:
        mask = df["CMJ_cm"].notna() & df["SJ_cm"].notna() & (df["SJ_cm"] != 0)
        df.loc[mask, "EUR"] = (df.loc[mask, "CMJ_cm"] / df.loc[mask, "SJ_cm"]).round(3)
    return df


def calc_dri(df: pd.DataFrame) -> pd.DataFrame:
    """DRI as jump height in meters divided by contact time in seconds."""
    if "DJ_cm" in df.columns and "DJ_tc_ms" in df.columns:
        df["DRI"] = (df["DJ_cm"] / 100) / (df["DJ_tc_ms"] / 1000)
    return df


def calc_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """Group z-scores used by the neuromuscular radar."""
    cols_config = {
        "CMJ_cm": ("CMJ_Z", False),
        "SJ_cm": ("SJ_Z", False),
        "DJ_tc_ms": ("DJtc_Z", True),
        "EUR": ("EUR_Z", False),
        "DRI": ("DRI_Z", False),
        "IMTP_N": ("IMTP_Z", False),
    }
    for col, (z_col, invert) in cols_config.items():
        if col not in df.columns:
            continue
        values = df[col].dropna()
        if len(values) > 1 and values.std() > 0:
            z_score = (df[col] - values.mean()) / values.std()
            df[z_col] = (-z_score if invert else z_score).round(2)
        else:
            df[z_col] = 0.0
    return df


def calc_nm_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Neuromuscular profile based on EUR ratio and DRI."""
    if "EUR" not in df.columns or "DRI" not in df.columns:
        return df
    eur_ratio = _normalize_eur_series_to_ratio(df["EUR"])
    conditions = [
        (eur_ratio >= 1.20) & (df["DRI"] >= 1.5),
        (eur_ratio >= 1.20) & (df["DRI"] < 1.5),
        (eur_ratio < 1.20) & (df["DRI"] >= 1.5),
        (eur_ratio < 1.20) & (df["DRI"] < 1.5),
    ]
    labels = [
        "Reactivo-Elastico",
        "Elastico / CEA-Lento",
        "Reactivo / Poca Base",
        "Fuerza-Concentrica",
    ]
    df["EUR"] = eur_ratio
    df["NM_Profile"] = np.select(conditions, labels, default="Sin datos")
    return df


def _prepare_jump_df(jump_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the unified evaluations table and recompute derived metrics."""
    if jump_df is None or jump_df.empty:
        return pd.DataFrame()

    result = jump_df.copy()
    if "Athlete" in result.columns:
        result["Athlete"] = result["Athlete"].astype(str).str.strip().str.title()
    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()

    numeric_cols = [col for col in result.columns if col not in {"Athlete", "Date", "NM_Profile"}]
    for col in numeric_cols:
        result[col] = pd.to_numeric(result[col], errors="coerce")

    valid_subset = [col for col in ["Athlete", "Date"] if col in result.columns]
    result = result.dropna(subset=valid_subset)
    if result.empty:
        return pd.DataFrame()

    result = result.sort_values(["Athlete", "Date"]).drop_duplicates(
        subset=["Athlete", "Date"],
        keep="last",
    )
    result = calc_eur(result)
    result = calc_dri(result)
    result = calc_zscores(result)
    result = calc_nm_profile(result)
    return result.sort_values(["Athlete", "Date"]).reset_index(drop=True)


def _records_to_jump_df(records: list[dict]) -> pd.DataFrame:
    """Consolidate individual test records into one row per athlete/date."""
    if not records:
        return pd.DataFrame()

    rows: dict[tuple[str, pd.Timestamp], dict[str, object]] = {}
    for record in records:
        athlete = str(record.get("Athlete", "")).strip().title()
        date = pd.to_datetime(record.get("Date"), errors="coerce")
        if not athlete or pd.isna(date):
            continue

        key = (athlete, date.normalize())
        row = rows.setdefault(key, {"Athlete": athlete, "Date": date.normalize()})
        for field, value in record.items():
            if (
                field in {"Athlete", "Date", "test_type"}
                or field.endswith("_reps")
                or field.startswith("__")
            ):
                continue
            if value is not None and not (isinstance(value, float) and np.isnan(value)):
                row[field] = value

    return _prepare_jump_df(pd.DataFrame(rows.values()))
