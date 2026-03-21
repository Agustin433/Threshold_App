# modules/jump_analysis.py

import pandas as pd
import numpy as np
from scipy import stats
from config import EUR_REFERENCE, DRI_REFERENCE


def calculate_eur(df: pd.DataFrame) -> pd.DataFrame:
    """
    EUR = Elasticity Utilization Ratio
    Formula: (CMJ_cm - SJ_cm) / SJ_cm × 100
    
    Referencia: Bosco et al. 1982; Balsalobre-Fernández 2019
    Interpreta el uso del ciclo estiramiento-acortamiento (SSC/CEA).
    
    EUR > 20%  → atleta reactivo, domina el SSC rápido
    EUR < 10%  → predominio fuerza concéntrica, CEA ineficiente
    EUR negativo → SJ > CMJ → señal de fatiga neuromuscular severa o
                  fallo técnico (requiere re-test)
    """
    if "CMJ_cm" not in df.columns or "SJ_cm" not in df.columns:
        return df

    df["EUR"] = ((df["CMJ_cm"] - df["SJ_cm"]) / df["SJ_cm"]) * 100

    # Clasificación cualitativa
    def classify_eur(val):
        if pd.isna(val):
            return "Sin datos"
        if val < 0:
            return "⚠️ Negativo - re-test"
        for label, (low, high) in EUR_REFERENCE.items():
            if low <= val < high:
                return label.replace("_", " ").title()
        return "Muy Alto"

    df["EUR_Categoria"] = df["EUR"].apply(classify_eur)
    return df


def calculate_dri(df: pd.DataFrame) -> pd.DataFrame:
    """
    DRI = Dynamic Reactive Index (equivalente al RSI)
    Formula: DJ_height_m / contact_time_s
    
    Convierte DJ_cm → m y DJ_tc_ms → s antes de calcular.
    
    Referencia: Young 1995; Flanagan & Comyns 2008
    RSI/DRI > 2.0 → atleta reactivo de élite
    RSI/DRI 1.5-2.0 → bueno
    RSI/DRI < 0.9  → bajo, priorizar stiffness y CEA corto
    
    NOTA: algunos autores usan la fórmula de tiempo de vuelo derivado
    en lugar de altura directa. Aquí usamos altura medida directa
    (My Jump Lab).
    """
    if "DJ_cm" not in df.columns or "DJ_tc_ms" not in df.columns:
        return df

    # Conversión de unidades
    df["DJ_m"] = df["DJ_cm"] / 100
    df["DJ_tc_s"] = df["DJ_tc_ms"] / 1000

    # DRI
    df["DRI"] = df["DJ_m"] / df["DJ_tc_s"]

    def classify_dri(val):
        if pd.isna(val):
            return "Sin datos"
        for label, (low, high) in DRI_REFERENCE.items():
            if low <= val < high:
                return label.replace("_", " ").title()
        return "Excelente"

    df["DRI_Categoria"] = df["DRI"].apply(classify_dri)
    return df


def calculate_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula Z-scores grupales para:
    - CMJ_cm   (altura CMJ)
    - DJ_tc_ms (tiempo de contacto DJ — INVERTIDO: menor TC = mejor)
    - EUR      (ratio de elasticidad)
    - DRI      (índice reactivo dinámico)
    
    Z = (x - μ) / σ
    
    IMPORTANTE: DJ_tc_ms se invierte (×-1) para el radar porque
    menor tiempo de contacto = mejor capacidad reactiva.
    El radar mostrará 'DJ_Reactividad_Z' donde valores positivos
    indican mejor rendimiento.
    
    Referencia: Hopkins 2000 — Individual Response to Training
    """
    z_vars = {
        "CMJ_cm":   False,   # False = no invertir
        "DJ_tc_ms": True,    # True  = invertir (menor es mejor)
        "EUR":      False,
        "DRI":      False,
        "SJ_cm":    False,
        "IMTP_N":   False,
    }

    for col, invert in z_vars.items():
        if col in df.columns:
            z_col = f"{col.replace('_cm','').replace('_ms','').replace('_N','')}_Z"
            if col == "DJ_tc_ms":
                z_col = "DJ_Reactividad_Z"

            values = df[col].dropna()
            if len(values) > 1:
                mu = values.mean()
                sigma = values.std()
                if sigma > 0:
                    z = (df[col] - mu) / sigma
                    df[z_col] = -z if invert else z
                else:
                    df[z_col] = 0.0
            else:
                df[z_col] = 0.0

    return df


def calculate_bilateral_deficit(df: pd.DataFrame) -> pd.DataFrame:
    """
    Asimetría bilateral estimada desde EUR.
    
    No reemplaza a la plataforma de fuerza, pero es un proxy útil.
    EUR bajo + DRI bajo = déficit en el CEA rápido → trabajar DJ, pliometría
    EUR alto + DRI bajo = buen SSC lento pero falla en el rápido
    """
    if "EUR" not in df.columns or "DRI" not in df.columns:
        return df

    # Índice compuesto de perfil neuromuscular
    df["NM_Profile"] = np.where(
        (df["EUR"] >= 20) & (df["DRI"] >= 1.5), "Reactivo-Elástico",
        np.where(
            (df["EUR"] >= 20) & (df["DRI"] < 1.5), "Elástico-Lento",
            np.where(
                (df["EUR"] < 20) & (df["DRI"] >= 1.5), "Reactivo-Rígido",
                "Fuerza-Concéntrica"
            )
        )
    )
    return df


def get_athlete_jump_summary(df: pd.DataFrame, athlete: str) -> dict:
    """
    Retorna diccionario con todos los KPIs de salto para un atleta.
    Usa el registro más reciente si hay múltiples fechas.
    """
    a_df = df[df["Athlete"] == athlete].sort_values("Date")
    if a_df.empty:
        return {}

    latest = a_df.iloc[-1]
    baseline = a_df.mean(numeric_only=True)

    metrics = {}
    for col in ["CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "IMTP_N", "EUR", "DRI"]:
        if col in latest.index:
            metrics[col] = {
                "latest":   round(latest[col], 2) if not pd.isna(latest[col]) else None,
                "baseline": round(baseline[col], 2) if not pd.isna(baseline[col]) else None,
                "delta_pct": round(
                    ((latest[col] - baseline[col]) / baseline[col]) * 100, 1
                ) if baseline[col] != 0 else 0,
            }

    # Z-scores para el radar
    z_cols = [c for c in a_df.columns if c.endswith("_Z")]
    for z in z_cols:
        metrics[z] = round(float(latest[z]), 2) if z in latest.index else 0

    return metrics