"""Shared load monitoring calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

ACWR_ZONES = (
    (0.00, 0.80, "Subcarga", "#4A9FD4"),
    (0.80, 1.30, "Optimo", "#4FC97E"),
    (1.30, 1.50, "Precaucion", "#E8C84A"),
    (1.50, 9.99, "Alto riesgo", "#D94F4F"),
)
MONOTONY_HIGH = 2.0


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
    """Classic 7:28 ACWR and EWMA ACWR over a daily resampled series."""
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
    """Weekly monotony and strain according to Foster."""
    weekly = srpe_daily.set_index("Date")["sRPE_diario"].resample("W").agg(["sum", "mean", "std"]).reset_index()
    weekly.columns = ["Semana", "Carga_Total", "Media", "SD"]
    weekly["SD"] = weekly["SD"].fillna(0.001)
    weekly["Monotonia"] = weekly["Media"] / weekly["SD"]
    weekly["Strain"] = weekly["Carga_Total"] * weekly["Monotonia"]
    weekly["Alerta"] = weekly["Monotonia"] > MONOTONY_HIGH
    return weekly
