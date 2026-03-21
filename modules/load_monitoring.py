# modules/load_monitoring.py

import pandas as pd
import numpy as np
from config import ACWR_ZONES, MONOTONY_HIGH


def calculate_acwr_classic(
    df: pd.DataFrame,
    athlete: str,
    acute_window: int = 7,
    chronic_window: int = 28
) -> pd.DataFrame:
    """
    ACWR Clásico (rolling ratio).
    
    Acuta  = media rolling de 7 días
    Crónica = media rolling de 28 días
    ACWR = Aguda / Crónica
    
    Referencia: Gabbett 2016, BJSM
    Zona óptima: 0.8 – 1.3
    Zona riesgo: > 1.5
    
    ADVERTENCIA (honestidad brutal): el ACWR clásico tiene limitaciones
    matemáticas documentadas (Lolli et al. 2017, Windt & Gabbett 2019).
    En períodos de baja carga crónica, el ratio se infla artificialmente.
    El EWMA (ver función de abajo) es más robusto para uso operativo.
    """
    a_df = df[df["Athlete"] == athlete].copy()
    a_df = a_df.set_index("Date").sort_index()

    # Resample diario (rellena días sin sesión con 0)
    daily = a_df["sRPE"].resample("D").sum().fillna(0)

    result = pd.DataFrame({"Date": daily.index, "sRPE_diario": daily.values})
    result["Aguda_7d"]  = result["sRPE_diario"].rolling(acute_window,  min_periods=1).mean()
    result["Cronica_28d"] = result["sRPE_diario"].rolling(chronic_window, min_periods=1).mean()

    # Evitar división por cero
    result["ACWR"] = np.where(
        result["Cronica_28d"] > 0,
        result["Aguda_7d"] / result["Cronica_28d"],
        0
    )

    result["Zona_ACWR"] = result["ACWR"].apply(classify_acwr_zone)
    result["Athlete"] = athlete
    return result


def calculate_acwr_ewma(
    df: pd.DataFrame,
    athlete: str,
    lambda_acute: float = 0.28,    # ≈ 7 días de half-life
    lambda_chronic: float = 0.07   # ≈ 28 días de half-life
) -> pd.DataFrame:
    """
    ACWR con EWMA (Exponentially Weighted Moving Average).
    
    Más sensible a cambios recientes. Recomendado operativamente.
    λ_aguda  ≈ 2/(7+1)  = 0.25  o 0.28 (convención)
    λ_crónica ≈ 2/(28+1) = 0.069
    
    Referencia: Williams et al. 2017, IJSPP
    Hulin et al. 2016 — EWMA vs rolling average en rugby union
    """
    a_df = df[df["Athlete"] == athlete].copy()
    a_df = a_df.set_index("Date").sort_index()
    daily = a_df["sRPE"].resample("D").sum().fillna(0)

    result = pd.DataFrame({"Date": daily.index, "sRPE_diario": daily.values})

    # EWMA
    result["EWMA_Aguda"]   = result["sRPE_diario"].ewm(alpha=lambda_acute,  adjust=False).mean()
    result["EWMA_Cronica"] = result["sRPE_diario"].ewm(alpha=lambda_chronic, adjust=False).mean()

    result["ACWR_EWMA"] = np.where(
        result["EWMA_Cronica"] > 0,
        result["EWMA_Aguda"] / result["EWMA_Cronica"],
        0
    )

    result["Zona_ACWR"] = result["ACWR_EWMA"].apply(classify_acwr_zone)
    result["Athlete"] = athlete
    return result


def classify_acwr_zone(acwr: float) -> str:
    """Clasifica zona de riesgo según ACWR."""
    if acwr == 0:
        return "Sin carga"
    for zone, (low, high) in ACWR_ZONES.items():
        if low <= acwr < high:
            return zone.replace("_", " ").title()
    return "Alto Riesgo"


def calculate_monotony_and_strain(
    df: pd.DataFrame,
    athlete: str
) -> pd.DataFrame:
    """
    Monotonía y Strain — Foster 2001.
    
    Monotonía = media(sRPE semana) / SD(sRPE semana)
    Strain     = carga_total_semana × monotonía
    
    Monotonía > 2.0 → señal de alarma (Foster 2001)
    Strain alto + Monotonía alta = riesgo de sobreentrenamiento
    
    Interpretación práctica:
    - Alta monotonía = poca variabilidad en la carga → no hay ondulación
    - Combinar con wellness score para decisión final
    """
    a_df = df[df["Athlete"] == athlete].copy()
    a_df = a_df.set_index("Date").sort_index()
    daily = a_df["sRPE"].resample("D").sum().fillna(0)

    # Agrupar por semana
    weekly = daily.resample("W").agg(["sum", "mean", "std"]).reset_index()
    weekly.columns = ["Semana", "Carga_Total", "Media_sRPE", "SD_sRPE"]

    weekly["SD_sRPE"] = weekly["SD_sRPE"].fillna(0.001)  # evitar /0
    weekly["Monotonia"] = weekly["Media_sRPE"] / weekly["SD_sRPE"]
    weekly["Strain"] = weekly["Carga_Total"] * weekly["Monotonia"]
    weekly["Alerta_Monotonia"] = weekly["Monotonia"] > MONOTONY_HIGH
    weekly["Athlete"] = athlete

    return weekly


def get_team_load_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resumen de carga para todo el equipo en la última semana.
    Útil para el dashboard grupal.
    """
    athletes = df["Athlete"].unique()
    summaries = []

    for athlete in athletes:
        a_df = df[df["Athlete"] == athlete].copy()
        if a_df.empty:
            continue

        last_7  = a_df.tail(7)["sRPE"].sum()
        last_28 = a_df.tail(28)["sRPE"].mean()

        acwr = last_7 / 7 / last_28 if last_28 > 0 else 0

        summaries.append({
            "Athlete":     athlete,
            "Carga_7d":   round(last_7, 0),
            "Media_28d":  round(last_28, 1),
            "ACWR":       round(acwr, 2),
            "Zona":       classify_acwr_zone(acwr),
        })

    return pd.DataFrame(summaries)