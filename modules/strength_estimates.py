"""Fuerza estimada (Epley) y mejores marcas de los levantamientos principales.

- Solo levantamientos principales con barra (MAIN_BARBELL_LIFTS, unica lista).
  Se dejan afuera los olimpicos (clean, snatch, push press, jerk): su carga la
  limita la tecnica y la velocidad, no la fuerza maxima, y Epley no aplica.
- Epley: 1RM estimado = carga * (1 + reps / 30), solo series de 1 a 10 reps
  (con mas repeticiones el error de la ecuacion crece mucho). Con 1 rep se
  toma la carga.
- Es una estimacion MINIMA: sale de series que no fueron necesariamente al
  fallo, asi que el 1RM real es igual o mayor. No es un 1RM medido.
"""

from __future__ import annotations

import pandas as pd

# Nombre del ejercicio en TeamBuildr (minusculas) -> rotulo para el reporte.
MAIN_BARBELL_LIFTS: dict[str, str] = {
    "barbell back squat": "Sentadilla trasera",
    "barbell front squat": "Sentadilla frontal",
    "front squat": "Sentadilla frontal",
    "barbell deadlift": "Peso muerto",
    "barbell bench press": "Press de banca",
    "barbell military press": "Press militar",
    "barbell hip thrust": "Hip thrust",
}

EPLEY_MIN_REPS = 1
EPLEY_MAX_REPS = 10
ESTIMATED_STRENGTH_LABEL = "estimación mínima a partir de tus series, no es un 1RM medido"


def main_lift_label(exercise: object) -> str | None:
    return MAIN_BARBELL_LIFTS.get(str(exercise or "").strip().casefold())


def epley_1rm(load_kg: object, reps: object) -> float | None:
    load = pd.to_numeric(pd.Series([load_kg]), errors="coerce").iloc[0]
    rep_count = pd.to_numeric(pd.Series([reps]), errors="coerce").iloc[0]
    if pd.isna(load) or pd.isna(rep_count) or load <= 0:
        return None
    rep_count = int(rep_count)
    if rep_count < EPLEY_MIN_REPS or rep_count > EPLEY_MAX_REPS:
        return None
    if rep_count == 1:
        return float(load)
    return float(load) * (1.0 + rep_count / 30.0)


def _session_date_column(raw_df: pd.DataFrame) -> str | None:
    for column in ("Fecha_sesion", "Completed Date", "Date", "Assigned Date"):
        if column in raw_df.columns:
            return column
    return None


def estimated_strength_by_day(raw_df: pd.DataFrame | None, athlete: str | None = None) -> pd.DataFrame:
    """Mejor 1RM estimado por dia y levantamiento principal.

    Columnas: Date, Lift, e1RM_kg, Load_kg, Reps.
    """
    columns = ["Date", "Lift", "e1RM_kg", "Load_kg", "Reps"]
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=columns)
    exercise_col = "Exercise Name" if "Exercise Name" in raw_df.columns else "Exercise"
    date_col = _session_date_column(raw_df)
    if exercise_col not in raw_df.columns or date_col is None or not {"Result", "Reps"}.issubset(raw_df.columns):
        return pd.DataFrame(columns=columns)
    data = raw_df
    if athlete is not None and "Athlete" in data.columns:
        data = data[data["Athlete"].astype(str).str.strip().str.casefold() == str(athlete).strip().casefold()]
    lifts = data[exercise_col].map(main_lift_label)
    data = data.assign(Lift=lifts)[lifts.notna()]
    if data.empty:
        return pd.DataFrame(columns=columns)
    data = data.assign(
        Date=pd.to_datetime(data[date_col], errors="coerce").dt.normalize(),
        Load_kg=pd.to_numeric(data["Result"], errors="coerce"),
        Reps=pd.to_numeric(data["Reps"], errors="coerce"),
    )
    data = data.assign(e1RM_kg=[epley_1rm(load, reps) for load, reps in zip(data["Load_kg"], data["Reps"])])
    data = data.dropna(subset=["Date", "e1RM_kg"])
    if data.empty:
        return pd.DataFrame(columns=columns)
    best = data.sort_values("e1RM_kg").groupby(["Date", "Lift"], as_index=False).tail(1)
    return best[columns].sort_values(["Lift", "Date"]).reset_index(drop=True)


def new_main_lift_bests(
    maxes_df: pd.DataFrame | None,
    athlete: str | None,
    *,
    window_start: object,
    window_end: object | None = None,
) -> list[dict[str, object]]:
    """Mejores marcas nuevas (maxes_df) en levantamientos principales.

    Una marca es nueva si el maximo registrado dentro de la ventana supera
    todo lo registrado antes de la ventana. Sin registro previo no hay
    "mejor marca": es la primera referencia.
    """
    if maxes_df is None or maxes_df.empty:
        return []
    needed = {"Exercise Name", "Max Value", "Added Date"}
    if not needed.issubset(maxes_df.columns):
        return []
    data = maxes_df
    if athlete is not None and "Athlete" in data.columns:
        data = data[data["Athlete"].astype(str).str.strip().str.casefold() == str(athlete).strip().casefold()]
    lifts = data["Exercise Name"].map(main_lift_label)
    data = data.assign(Lift=lifts)[lifts.notna()]
    if data.empty:
        return []
    data = data.assign(
        Date=pd.to_datetime(data["Added Date"], errors="coerce").dt.normalize(),
        Value=pd.to_numeric(data["Max Value"], errors="coerce"),
    ).dropna(subset=["Date", "Value"])
    start = pd.Timestamp(window_start).normalize()
    end = pd.Timestamp(window_end).normalize() if window_end is not None else data["Date"].max()
    bests: list[dict[str, object]] = []
    for lift, lift_df in data.groupby("Lift"):
        before = lift_df[lift_df["Date"] < start]
        inside = lift_df[(lift_df["Date"] >= start) & (lift_df["Date"] <= end)]
        if before.empty or inside.empty:
            continue
        previous_best = float(before["Value"].max())
        top = inside.sort_values(["Value", "Date"]).iloc[-1]
        if float(top["Value"]) > previous_best:
            bests.append(
                {
                    "Lift": lift,
                    "Value": float(top["Value"]),
                    "Previous": previous_best,
                    "Date": pd.Timestamp(top["Date"]),
                }
            )
    return sorted(bests, key=lambda item: item["Lift"])
