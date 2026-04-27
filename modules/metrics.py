"""Canonical metric calculations shared across product surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd


ASSIGNED_COLUMN_ALIASES: tuple[str, ...] = (
    "Assigned",
    "Asignado",
    "Total_Assigned",
    "Assigned_Count",
)
COMPLETED_COLUMN_ALIASES: tuple[str, ...] = (
    "Completed",
    "Completado",
    "Total_Completed",
    "Completed_Count",
)
PERCENT_COLUMN_ALIASES: tuple[str, ...] = (
    "Pct",
    "Percent",
    "Percentage",
    "Completion",
    "CompletionPct",
    "Completion_Pct",
    "Completion Rate",
    "Completion_Rate",
)


@dataclass(frozen=True)
class CompletionRateResult:
    value: float | None
    method: str
    warning: str | None = None
    assigned_total: float | None = None
    completed_total: float | None = None
    rows_used: int = 0
    rows_ignored: int = 0


@dataclass(frozen=True)
class MonotonyResult:
    value: float | None
    method: str
    warning: str | None = None
    mean_load: float | None = None
    sd_load: float | None = None
    total_load: float | None = None
    valid_days: int = 0


def _first_existing(columns: Iterable[str], aliases: Sequence[str]) -> str | None:
    lookup = {str(column).strip().lower(): column for column in columns}
    for alias in aliases:
        found = lookup.get(alias.strip().lower())
        if found is not None:
            return str(found)
    return None


def _to_numeric_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "--": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_percentage_series(series: pd.Series) -> pd.Series:
    values = _to_numeric_series(series)
    valid = values.dropna()
    if not valid.empty and float(valid.max()) <= 1.5:
        values = values * 100.0
    return values


def calculate_completion_rate(df: pd.DataFrame | None) -> CompletionRateResult:
    """Return completion in 0-100 scale, preferring weighted Completed/Assigned."""
    if df is None or df.empty:
        return CompletionRateResult(None, "insufficient_data", "empty")

    assigned_col = _first_existing(df.columns, ASSIGNED_COLUMN_ALIASES)
    completed_col = _first_existing(df.columns, COMPLETED_COLUMN_ALIASES)
    pct_col = _first_existing(df.columns, PERCENT_COLUMN_ALIASES)

    if assigned_col and completed_col:
        assigned = _to_numeric_series(df[assigned_col])
        completed = _to_numeric_series(df[completed_col])
        valid = assigned.gt(0) & completed.notna()
        assigned_total = float(assigned[valid].sum())
        completed_total = float(completed[valid].sum())
        rows_ignored = int((~valid).sum())
        if assigned_total > 0:
            warning = "rows_ignored" if rows_ignored else None
            return CompletionRateResult(
                value=(completed_total / assigned_total) * 100.0,
                method="weighted",
                warning=warning,
                assigned_total=assigned_total,
                completed_total=completed_total,
                rows_used=int(valid.sum()),
                rows_ignored=rows_ignored,
            )
        if pct_col:
            fallback = _completion_from_percentage(df[pct_col], warning="invalid_assigned")
            if fallback.value is not None:
                return fallback
        return CompletionRateResult(
            None,
            "invalid_assigned",
            "assigned_total_zero",
            assigned_total=assigned_total,
            completed_total=completed_total,
            rows_used=0,
            rows_ignored=len(df),
        )

    if pct_col:
        return _completion_from_percentage(df[pct_col])

    return CompletionRateResult(None, "insufficient_data", "missing_completion_columns")


def _completion_from_percentage(series: pd.Series, warning: str | None = None) -> CompletionRateResult:
    values = normalize_percentage_series(series).dropna()
    if values.empty:
        return CompletionRateResult(None, "insufficient_data", warning or "missing_percentage")
    rows_ignored = int(len(series) - len(values))
    return CompletionRateResult(
        value=float(values.mean()),
        method="fallback_pct",
        warning=warning or ("rows_ignored" if rows_ignored else None),
        rows_used=int(len(values)),
        rows_ignored=rows_ignored,
    )


def summarize_completion_by_group(
    df: pd.DataFrame | None,
    group_columns: str | Sequence[str],
    *,
    value_column: str = "Pct",
) -> pd.DataFrame:
    """Aggregate completion with the canonical weighted rule for each group."""
    if df is None or df.empty:
        columns = [group_columns] if isinstance(group_columns, str) else list(group_columns)
        return pd.DataFrame(columns=[*columns, value_column, "Calculation_Method", "Completion_Warning"])

    columns = [group_columns] if isinstance(group_columns, str) else list(group_columns)
    missing = [column for column in columns if column not in df.columns]
    if missing:
        return pd.DataFrame(columns=[*columns, value_column, "Calculation_Method", "Completion_Warning"])

    rows: list[dict[str, object]] = []
    grouped = df.groupby(columns, dropna=False, sort=False)
    for key, group in grouped:
        result = calculate_completion_rate(group)
        if result.value is None:
            continue
        key_values = key if isinstance(key, tuple) else (key,)
        row = {column: value for column, value in zip(columns, key_values)}
        row.update(
            {
                value_column: result.value,
                "Calculation_Method": result.method,
                "Completion_Warning": result.warning,
                "Rows_Used": result.rows_used,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def calculate_monotony(
    daily_loads: Iterable[float] | pd.Series,
    *,
    min_valid_days: int = 3,
    zero_variability_value: float = 99.0,
) -> MonotonyResult:
    """Calculate Foster monotony from daily loads with explicit edge-case flags."""
    values = pd.to_numeric(pd.Series(daily_loads), errors="coerce").dropna()
    valid_days = int(len(values))
    if valid_days < min_valid_days:
        return MonotonyResult(None, "insufficient_data", "less_than_min_days", valid_days=valid_days)

    mean_load = float(values.mean())
    total_load = float(values.sum())
    if mean_load <= 0 or total_load <= 0:
        return MonotonyResult(
            0.0,
            "no_load",
            None,
            mean_load=mean_load,
            sd_load=0.0,
            total_load=total_load,
            valid_days=valid_days,
        )

    sd_load = float(values.std(ddof=0))
    if sd_load <= 0:
        return MonotonyResult(
            zero_variability_value,
            "zero_variability",
            "zero_variability",
            mean_load=mean_load,
            sd_load=sd_load,
            total_load=total_load,
            valid_days=valid_days,
        )

    return MonotonyResult(
        mean_load / sd_load,
        "standard",
        None,
        mean_load=mean_load,
        sd_load=sd_load,
        total_load=total_load,
        valid_days=valid_days,
    )
