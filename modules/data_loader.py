# modules/data_loader.py

import pandas as pd
import numpy as np
import streamlit as st
from config import TB_RPE_COLUMNS

# ── Mapas de nombres de columnas por reporte ──────────────────────────
# Teambuildr cambia nombres de columnas según idioma/versión
# Este mapa normaliza todo a nombres internos consistentes

COLUMN_MAPS = {
    "rpe_time": {
        "Date": ["Date", "Fecha", "date"],
        "Athlete": ["Athlete", "Atleta", "Name", "Player"],
        "Duration": ["Duration", "Time", "Tiempo", "Duration (min)", "Minutes"],
        "RPE": ["RPE", "Session RPE", "sRPE_raw"],
        "WorkoutName": ["Workout", "WorkoutName", "Session", "Training"],
    },
    "wellness": {
        "Date": ["Date", "Fecha"],
        "Athlete": ["Athlete", "Atleta", "Name"],
        "Q1": ["Q1", "Sleep", "Sueño", "Sleep Quality"],
        "Q2": ["Q2", "Fatigue", "Fatiga"],
        "Q3": ["Q3", "Soreness", "Dolor", "Muscle Soreness"],
    },
    "rep_load": {
        "Date": ["Date", "Fecha"],
        "Athlete": ["Athlete", "Atleta"],
        "Exercise": ["Exercise", "Ejercicio", "ExerciseName"],
        "Sets": ["Sets", "Set Number", "Set"],
        "Reps": ["Reps", "Repetitions", "Rep Count"],
        "Load": ["Load", "Weight", "Carga", "Load (kg)"],
    },
    "raw_data": {
        "Date": ["Date", "Fecha", "Workout Date"],
        "Athlete": ["Athlete", "Atleta", "Athlete Name"],
        "Exercise": ["Exercise", "ExerciseName", "Exercise Name"],
        "Set": ["Set", "Set Number"],
        "Reps": ["Reps", "Repetitions", "Completed Reps"],
        "Load": ["Load", "Weight (kg)", "Load (kg)"],
        "ExternalID": ["ExternalID", "External ID", "Custom ID"],
        "Tags": ["Tags", "Tag", "Labels"],
    },
}


def normalize_columns(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    Renombra columnas del DataFrame a nombres internos estándar.
    Tolerante a variaciones de Teambuildr.
    """
    rename_dict = {}
    for standard_name, variants in col_map.items():
        for variant in variants:
            if variant in df.columns:
                rename_dict[variant] = standard_name
                break
    return df.rename(columns=rename_dict)


def clean_dates(df: pd.DataFrame, col: str = "Date") -> pd.DataFrame:
    """Parsea fechas con tolerancia a múltiples formatos."""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def clean_athlete_names(df: pd.DataFrame, col: str = "Athlete") -> pd.DataFrame:
    """Normaliza nombres: strip espacios, title case."""
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip().str.title()
    return df


@st.cache_data
def load_rpe_time(file) -> pd.DataFrame:
    """
    Carga RPE + Time de Teambuildr.
    Calcula sRPE = RPE × Duration.
    """
    df = _read_file(file)
    df = normalize_columns(df, COLUMN_MAPS["rpe_time"])
    df = clean_dates(df)
    df = clean_athlete_names(df)

    # Conversión de tipos
    df["Duration"] = pd.to_numeric(df.get("Duration", 0), errors="coerce")
    df["RPE"] = pd.to_numeric(df.get("RPE", 0), errors="coerce")

    # Calcular sRPE (Foster et al. 2001)
    df["sRPE"] = df["Duration"] * df["RPE"]

    return df.dropna(subset=["Date", "Athlete"])


@st.cache_data
def load_wellness(file) -> pd.DataFrame:
    """
    Carga wellness de 3 preguntas.
    Calcula score compuesto y Z-score longitudinal.
    """
    df = _read_file(file)
    df = normalize_columns(df, COLUMN_MAPS["wellness"])
    df = clean_dates(df)
    df = clean_athlete_names(df)

    for q in ["Q1", "Q2", "Q3"]:
        if q in df.columns:
            df[q] = pd.to_numeric(df[q], errors="coerce")

    # Score compuesto (promedio de las 3 preguntas)
    q_cols = [c for c in ["Q1", "Q2", "Q3"] if c in df.columns]
    if q_cols:
        df["Wellness_Score"] = df[q_cols].mean(axis=1)

    return df.dropna(subset=["Date", "Athlete"])


@st.cache_data
def load_rep_load(file) -> pd.DataFrame:
    """Rep/Load Report — datos de ejercicios con cargas."""
    df = _read_file(file)
    df = normalize_columns(df, COLUMN_MAPS["rep_load"])
    df = clean_dates(df)
    df = clean_athlete_names(df)

    df["Load"] = pd.to_numeric(df.get("Load", 0), errors="coerce")
    df["Reps"] = pd.to_numeric(df.get("Reps", 0), errors="coerce")
    df["Volume_Load"] = df["Load"] * df["Reps"]

    return df


@st.cache_data
def load_raw_data(file) -> pd.DataFrame:
    """New Raw Data Report — datos completos por serie/rep."""
    df = _read_file(file)
    df = normalize_columns(df, COLUMN_MAPS["raw_data"])
    df = clean_dates(df)
    df = clean_athlete_names(df)
    return df


@st.cache_data
def load_jump_evaluation(file) -> pd.DataFrame:
    """
    Carga evaluación de saltos (tu formato custom).
    Columnas esperadas: Date, Athlete, CMJ_cm, SJ_cm, DJ_cm, DJ_tc_ms, IMTP_N
    """
    df = _read_file(file)
    df = clean_dates(df)
    df = clean_athlete_names(df)

    numeric_cols = ["CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "IMTP_N"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _read_file(file) -> pd.DataFrame:
    """Lee CSV o Excel según extensión."""
    name = file.name.lower()
    if name.endswith(".csv"):
        # Intenta detectar separador automáticamente
        try:
            return pd.read_csv(file, sep=",")
        except Exception:
            file.seek(0)
            return pd.read_csv(file, sep=";")
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)
    else:
        raise ValueError(f"Formato no soportado: {file.name}")