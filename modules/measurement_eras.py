"""Eras de medicion de la plataforma (columna `device` de evaluations).

Con los datos reales (39 evaluaciones, nov-2025 a oct-2026):

| era                  | fechas              | IMTP pico medio |
|----------------------|---------------------|-----------------|
| valkyria_sin_straps  | < 29/01/2026        | 30.4 N/kg       |
| valkyria_straps      | 29/01 - 30/09/2026  | 36.5 N/kg       |
| involution_straps    | >= 01/10/2026       | 47.5 N/kg       |

Los straps suben toda la curva del IMTP; Involution ademas detecta el pico
distinto (pico/media 1.16 -> 1.26). Las alturas por impulso estan infladas
solo con Valkyria (impulso - vuelo: +3.1 / +5.0 / -0.2 cm).

Regla: el IMTP (absoluto, relativo, RFD, F@t, media) y todo lo que sale de la
velocidad integrada (altura por impulso, potencia, RSI-mod, impulso,
momentum, EUR) solo se compara, se agrupa en cohorte y se contrasta con
literatura DENTRO de la misma era. Las alturas por tiempo de vuelo (incluido
el DJ) y las fuerzas de salto medidas directamente si se comparan entre eras:
es la misma plataforma.
"""

from __future__ import annotations

import pandas as pd

from modules.evaluation_rules import FLIGHT_TIME_HEIGHT_COLUMNS, JUMP_HEIGHT_DEPENDENT
from modules.evaluation_sources import SOURCE_PLATFORM, normalize_source

ERA_VALKYRIA_NO_STRAPS = "valkyria_sin_straps"
ERA_VALKYRIA_STRAPS = "valkyria_straps"
ERA_INVOLUTION_STRAPS = "involution_straps"

# (era, primer dia de la era), en orden.
PLATFORM_ERAS: tuple[tuple[str, pd.Timestamp], ...] = (
    (ERA_VALKYRIA_NO_STRAPS, pd.Timestamp("2000-01-01")),
    (ERA_VALKYRIA_STRAPS, pd.Timestamp("2026-01-29")),
    (ERA_INVOLUTION_STRAPS, pd.Timestamp("2026-10-01")),
)
DEFAULT_ERA = ERA_INVOLUTION_STRAPS

ERA_LABELS: dict[str, str] = {
    ERA_VALKYRIA_NO_STRAPS: "Valkyria sin straps",
    ERA_VALKYRIA_STRAPS: "Valkyria con straps",
    ERA_INVOLUTION_STRAPS: "Involution con straps",
}
ERA_OPTIONS: tuple[str, ...] = tuple(era for era, _ in reversed(PLATFORM_ERAS))

ALL_ERAS = "todas"
ALL_ERAS_LABEL = "todas las eras (misma plataforma)"

ERA_CHANGE_SIGNAL = "no comparable por era"
ERA_CHANGE_NOTE = "no comparable: cambio de software/protocolo"

# Lo que sale de la velocidad integrada: las mismas columnas que la regla 6b
# excluye cuando el peso esta mal, mas lo que deriva de ellas o del IMTP.
_VELOCITY_DERIVED = frozenset(
    column for columns in JUMP_HEIGHT_DEPENDENT.values() for column in columns
) | {"DSI", "CMJ_rel_impulse", "SJ_rel_impulse"}
_ERA_INDEPENDENT = frozenset(FLIGHT_TIME_HEIGHT_COLUMNS.values()) | {
    "DJ_cm",
    "DJ_RSI",
    "DRI",
    "DJ_tc_ms",
}


def is_era_dependent(metric: str) -> bool:
    """True si la metrica solo se compara dentro de la misma era."""
    name = str(metric)
    if name in _ERA_INDEPENDENT or name.endswith("_flight_ms") or name.endswith("_ft_cm"):
        return False
    return name.startswith("IMTP") or name in _VELOCITY_DERIVED


def era_from_date(date: object) -> str:
    when = pd.to_datetime(date, errors="coerce")
    if pd.isna(when):
        return DEFAULT_ERA
    era = PLATFORM_ERAS[0][0]
    for name, start in PLATFORM_ERAS:
        if pd.Timestamp(when).normalize() >= start:
            era = name
    return era


def resolve_era(device: object, date: object, source: object = SOURCE_PLATFORM) -> str:
    """Era de una toma: la columna device si es una era conocida; si no, la fecha.

    Fuera de plataforma (MyJump2, alfombra) la era es la propia fuente: ya
    viven en otra particion.
    """
    if normalize_source(source) != SOURCE_PLATFORM:
        return normalize_source(source)
    text = str(device or "").strip().lower()
    if text in ERA_LABELS:
        return text
    return era_from_date(date)


def era_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=object)
    devices = frame["Device"] if "Device" in frame.columns else pd.Series(None, index=frame.index)
    dates = frame["Date"] if "Date" in frame.columns else pd.Series(None, index=frame.index)
    sources = frame["Source"] if "Source" in frame.columns else pd.Series(SOURCE_PLATFORM, index=frame.index)
    return pd.Series(
        [resolve_era(d, t, s) for d, t, s in zip(devices, dates, sources)],
        index=frame.index,
        dtype=object,
    )


def metric_era(metric: str, era: str) -> str:
    """Particion de era para una metrica: la era real o 'todas'."""
    return era if is_era_dependent(metric) else ALL_ERAS


def era_label(era: object) -> str:
    text = str(era or "")
    if text == ALL_ERAS:
        return ALL_ERAS_LABEL
    return ERA_LABELS.get(text, text)
