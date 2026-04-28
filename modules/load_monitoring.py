"""Shared load monitoring calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.metrics import calculate_monotony

ACWR_ZONES = (
    (0.00, 0.80, "Subcarga", "#4A9FD4"),
    (0.80, 1.30, "Optimo", "#4FC97E"),
    (1.30, 1.50, "Precaucion", "#E8C84A"),
    (1.50, 9.99, "Alto riesgo", "#D94F4F"),
)
MONOTONY_HIGH = 2.0
ACWR_CONTEXT_DEFAULT_WEEKS = 16
ACWR_SPIKE_THRESHOLD_PCT = 50.0
ACWR_CONTEXT_COLUMNS = [
    "Athlete",
    "week_start",
    "is_current_week",
    "weekly_sRPE",
    "sessions_count",
    "chronic_4w",
    "chronic_weeks",
    "acwr_rolling_1_4",
    "acwr_rolling_ma4",
    "weekly_change_pct",
    "spike_flag",
    "context_status",
    "ACWR_EWMA_last",
    "monotony",
    "strain",
]


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


def calc_acwr(srpe_series: pd.Series, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Build the canonical ACWR EWMA daily series used across the app."""
    daily = pd.Series(srpe_series.values, index=dates).sort_index()
    daily = daily.resample("D").sum().fillna(0)

    result = pd.DataFrame({"Date": daily.index, "sRPE_diario": daily.values})
    result["Aguda_7d"] = result["sRPE_diario"].rolling(7, min_periods=1).mean()
    result["Cronica_28d"] = result["sRPE_diario"].rolling(28, min_periods=1).mean()
    # DEPRECATED: kept only as a legacy reference for historical inspection.
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

    result["ACWR"] = result["ACWR_EWMA"]
    result["Zona"] = result["ACWR"].apply(_classify_acwr)
    result["Zona_Color"] = result["ACWR"].apply(_acwr_color)
    return result


def _calendar_week_loads(series: pd.Series, week_end: pd.Timestamp) -> pd.Series:
    end = pd.Timestamp(week_end).normalize()
    start = end - pd.Timedelta(days=6)
    loads = series.copy()
    loads.index = pd.to_datetime(loads.index, errors="coerce").normalize()
    loads = loads.dropna()
    scoped = loads.loc[(loads.index >= start) & (loads.index <= end)]
    if not scoped.empty:
        scoped = scoped.groupby(scoped.index).sum()
    return scoped.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)


def calc_monotony_strain(srpe_daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly monotony and strain according to Foster."""
    daily = srpe_daily.copy()
    daily["Date"] = pd.to_datetime(daily["Date"], errors="coerce").dt.normalize()
    daily["sRPE_diario"] = pd.to_numeric(daily["sRPE_diario"], errors="coerce")
    daily = daily.dropna(subset=["Date", "sRPE_diario"])
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "Semana",
                "Carga_Total",
                "Media",
                "SD",
                "Monotonia",
                "Monotony_Status",
                "Monotony_Warning",
                "Strain",
                "Alerta",
            ]
        )

    series = daily.groupby("Date")["sRPE_diario"].sum().sort_index()
    weekly = series.resample("W").agg(["sum", "mean"]).reset_index()
    weekly.columns = ["Semana", "Carga_Total", "Media"]
    calendar_loads_by_week = {week: _calendar_week_loads(series, week) for week, _ in series.resample("W")}
    weekly["Media"] = weekly["Semana"].map(lambda week: float(calendar_loads_by_week[week].mean()))
    weekly["SD"] = weekly["Semana"].map(lambda week: float(calendar_loads_by_week[week].std(ddof=0)))
    monotony_by_week = {week: calculate_monotony(loads) for week, loads in calendar_loads_by_week.items()}
    weekly["Monotonia"] = weekly["Semana"].map(lambda week: monotony_by_week[week].value)
    weekly["Monotony_Status"] = weekly["Semana"].map(lambda week: monotony_by_week[week].method)
    weekly["Monotony_Warning"] = weekly["Semana"].map(lambda week: monotony_by_week[week].warning)
    weekly["Monotonia"] = pd.to_numeric(weekly["Monotonia"], errors="coerce")
    weekly["Strain"] = np.where(
        weekly["Monotony_Status"].eq("standard"),
        weekly["Carga_Total"] * weekly["Monotonia"],
        np.nan,
    )
    weekly["Alerta"] = weekly["Monotonia"].gt(MONOTONY_HIGH).fillna(False)
    return weekly


def build_weekly_acwr_context(
    weekly_load_df: pd.DataFrame | None,
    athlete: str | None = None,
    *,
    weeks: int | None = ACWR_CONTEXT_DEFAULT_WEEKS,
    spike_threshold_pct: float = ACWR_SPIKE_THRESHOLD_PCT,
) -> pd.DataFrame:
    """Build uncoupled weekly ACWR context from canonical weekly load.

    The chronic load is the mean of the previous four weekly loads, so the
    current week never appears in its own denominator.
    """
    if weekly_load_df is None or weekly_load_df.empty:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)
    required_cols = {"Athlete", "week_start", "weekly_sRPE"}
    if not required_cols.issubset(weekly_load_df.columns):
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    source = weekly_load_df.copy()
    source["Athlete"] = source["Athlete"].astype(str).str.strip()
    source["week_start"] = pd.to_datetime(source["week_start"], errors="coerce").dt.normalize()
    source["weekly_sRPE"] = pd.to_numeric(source["weekly_sRPE"], errors="coerce")
    source = source.dropna(subset=["Athlete", "week_start", "weekly_sRPE"])
    if athlete and athlete != "Todos":
        source = source[source["Athlete"].eq(str(athlete).strip())]
    if source.empty:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    for column in ["sessions_count", "ACWR_EWMA_last", "monotony", "strain"]:
        if column in source.columns:
            source[column] = pd.to_numeric(source[column], errors="coerce")
        else:
            source[column] = np.nan
    if "is_current_week" not in source.columns:
        source["is_current_week"] = False
    source["is_current_week"] = source["is_current_week"].fillna(False).astype(bool)

    rows: list[pd.DataFrame] = []
    for athlete_name, athlete_df in source.sort_values("week_start").groupby("Athlete", sort=True):
        athlete_df = athlete_df.sort_values("week_start").reset_index(drop=True)
        load = athlete_df["weekly_sRPE"].astype(float)
        chronic = load.shift(1).rolling(4, min_periods=1).mean()
        chronic_weeks = load.shift(1).rolling(4, min_periods=1).count()
        athlete_df["chronic_4w"] = chronic
        athlete_df["chronic_weeks"] = chronic_weeks.astype("Int64")
        athlete_df["acwr_rolling_1_4"] = np.where(chronic.gt(0), load / chronic, np.nan)
        athlete_df["acwr_rolling_ma4"] = (
            pd.Series(athlete_df["acwr_rolling_1_4"])
            .rolling(4, min_periods=1)
            .mean()
            .to_numpy()
        )
        previous_load = load.shift(1)
        athlete_df["weekly_change_pct"] = np.where(
            previous_load.gt(0),
            ((load - previous_load) / previous_load) * 100.0,
            np.nan,
        )
        athlete_df["spike_flag"] = athlete_df["weekly_change_pct"].ge(spike_threshold_pct).fillna(False)
        athlete_df["context_status"] = np.select(
            [
                athlete_df["chronic_weeks"].fillna(0).eq(0),
                athlete_df["chronic_4w"].fillna(0).le(0),
                athlete_df["chronic_weeks"].fillna(0).lt(4),
            ],
            ["insufficient_history", "invalid_chronic", "limited_history"],
            default="standard",
        )
        athlete_df["Athlete"] = athlete_name
        rows.append(athlete_df)

    if not rows:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    result = pd.concat(rows, ignore_index=True, sort=False)
    result = result.sort_values(["Athlete", "week_start"]).reset_index(drop=True)
    if weeks is not None and weeks > 0:
        result = (
            result.groupby("Athlete", group_keys=False)
            .tail(int(weeks))
            .reset_index(drop=True)
        )

    for column in ACWR_CONTEXT_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan
    return result[ACWR_CONTEXT_COLUMNS]
