"""Cobertura de sRPE: cuanto de la carga interna se registro (PR S).

Con cobertura baja, ACWR, monotonia y strain describen el REGISTRO, no la
carga (Foster et al. 2001, J Strength Cond Res 15:109; Bourdon et al. 2017,
IJSPP 12:S2-161). Este modulo es la unica definicion de cobertura de la app,
el dashboard y los PDF:

    cobertura = sesiones completadas con RPE / sesiones completadas

* "sesion completada" = dia con series registradas en Raw Workouts
  (TeamBuildr), por fecha de sesion (la completada, no la asignada);
* "con RPE" = ese mismo dia tiene sRPE > 0;
* ventana movil de 28 dias que termina en la fecha de referencia, o semana
  calendario (lunes a domingo).

Nada se borra: la cobertura solo condiciona que se MUESTRA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

COVERAGE_WINDOW_DAYS = 28
COVERAGE_MIN = 0.70
# Semanas consecutivas con cobertura >= 70% para que la cronica (28 dias) sea
# una carga y no un arrastre del periodo sin registro.
FORMATION_WEEKS = 4

REGISTER_RPE_TEXT = "Registrá tu RPE: te faltan {n} sesiones"
REGISTER_RPE_TEXT_ONE = "Registrá tu RPE: te falta 1 sesión"
FORMATION_TEXT = "carga crónica en formación (estable desde ~{date})"
NO_SESSIONS_TEXT = "sin sesiones registradas en 28 días"


def _dates(values: Iterable[object] | None) -> pd.DatetimeIndex:
    if values is None:
        return pd.DatetimeIndex([])
    series = pd.to_datetime(pd.Series(list(values)), errors="coerce").dropna()
    if series.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(series.dt.normalize().unique()).sort_values()


def missing_for_target(sessions: int, logged: int, target: float = COVERAGE_MIN) -> int:
    """Sesiones sin RPE que faltan registrar para llegar al umbral."""
    if sessions <= 0:
        return 0
    needed = math.ceil(target * sessions - 1e-9)
    return max(0, needed - logged)


def register_rpe_text(missing: int) -> str:
    return REGISTER_RPE_TEXT_ONE if int(missing) == 1 else REGISTER_RPE_TEXT.format(n=int(missing))


def week_start(date: object) -> pd.Timestamp:
    day = pd.Timestamp(date).normalize()
    return day - pd.Timedelta(days=day.weekday())


@dataclass(frozen=True)
class WeekCoverage:
    week_start: pd.Timestamp
    sessions: int
    logged: int

    @property
    def coverage(self) -> float | None:
        return self.logged / self.sessions if self.sessions else None

    @property
    def meets(self) -> bool:
        return self.coverage is not None and self.coverage >= COVERAGE_MIN - 1e-9


@dataclass(frozen=True)
class RpeCoverage:
    reference_date: pd.Timestamp
    sessions: int
    logged: int
    streak_weeks: int = 0
    stable_from: pd.Timestamp | None = None

    @property
    def coverage(self) -> float | None:
        return self.logged / self.sessions if self.sessions else None

    @property
    def pct(self) -> float | None:
        return None if self.coverage is None else 100.0 * self.coverage

    @property
    def meets(self) -> bool:
        """Cobertura de 28 dias >= 70%: el ACWR describe carga."""
        return self.coverage is not None and self.coverage >= COVERAGE_MIN - 1e-9

    @property
    def missing(self) -> int:
        return missing_for_target(self.sessions, self.logged)

    @property
    def forming(self) -> bool:
        """Supero el 70% pero con menos de 4 semanas seguidas >= 70%."""
        return self.meets and self.streak_weeks < FORMATION_WEEKS

    @property
    def register_text(self) -> str:
        if not self.sessions:
            return NO_SESSIONS_TEXT
        return register_rpe_text(self.missing)

    @property
    def formation_text(self) -> str:
        if not self.forming or self.stable_from is None:
            return ""
        return FORMATION_TEXT.format(date=f"{self.stable_from:%d/%m}")

    def as_dict(self) -> dict[str, object]:
        return {
            "rpe_sessions_28d": self.sessions,
            "rpe_logged_28d": self.logged,
            "rpe_coverage_28d": self.coverage,
            "rpe_missing_for_70": self.missing,
            "rpe_coverage_ok": self.meets,
            "rpe_coverage_forming": self.forming,
            "rpe_stable_from": self.stable_from,
        }


def count_in_window(session_dates, logged_dates, start, end) -> tuple[int, int]:
    """(sesiones completadas, de esas con RPE) entre start y end inclusive."""
    sessions = _dates(session_dates)
    logged = set(_dates(logged_dates))
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    in_window = sessions[(sessions >= start) & (sessions <= end)]
    return int(len(in_window)), int(sum(1 for day in in_window if day in logged))


def weekly_coverage(session_dates, logged_dates, *, until: object | None = None) -> list[WeekCoverage]:
    """Cobertura por semana calendario (lunes a domingo), en orden."""
    sessions = _dates(session_dates)
    if until is not None:
        sessions = sessions[sessions <= pd.Timestamp(until).normalize()]
    if not len(sessions):
        return []
    logged = set(_dates(logged_dates))
    frame = pd.DataFrame({"day": sessions})
    frame["week"] = frame["day"].map(week_start)
    frame["logged"] = frame["day"].map(lambda day: day in logged)
    grouped = frame.groupby("week")["logged"].agg(["size", "sum"])
    return [WeekCoverage(pd.Timestamp(week), int(row["size"]), int(row["sum"])) for week, row in grouped.iterrows()]


def coverage_for_week(session_dates, logged_dates, week: object) -> WeekCoverage:
    start = week_start(week)
    sessions, logged = count_in_window(session_dates, logged_dates, start, start + pd.Timedelta(days=6))
    return WeekCoverage(start, sessions, logged)


def formation_by_week(weeks: Iterable[WeekCoverage]) -> dict[pd.Timestamp, tuple[int, pd.Timestamp | None]]:
    """Racha de semanas seguidas con cobertura >= 70% que termina en cada semana.

    Una semana sin sesiones (descanso) no figura: ni corta ni suma. Devuelve
    {semana: (racha, inicio de la racha o None)}.
    """
    result: dict[pd.Timestamp, tuple[int, pd.Timestamp | None]] = {}
    streak, start = 0, None
    for item in sorted(weeks, key=lambda week: week.week_start):
        if item.sessions <= 0:
            continue
        if item.meets:
            streak += 1
            start = item.week_start if streak == 1 else start
        else:
            streak, start = 0, None
        result[item.week_start] = (streak, start)
    return result


def stable_from_date(reference_date: object, streak_start: pd.Timestamp | None) -> pd.Timestamp:
    """Fecha en que la cronica tendria 4 semanas de registro >= 70%."""
    start = streak_start if streak_start is not None else week_start(reference_date) + pd.Timedelta(days=7)
    return pd.Timestamp(start) + pd.Timedelta(days=FORMATION_WEEKS * 7)


def streak_at(formation: dict[pd.Timestamp, tuple[int, pd.Timestamp | None]], reference_date: object) -> tuple[int, pd.Timestamp]:
    current = week_start(reference_date)
    previous = [week for week in formation if week <= current]
    streak, start = formation[max(previous)] if previous else (0, None)
    return streak, stable_from_date(reference_date, start)


def rpe_coverage(session_dates, logged_dates, reference_date: object) -> RpeCoverage:
    """Cobertura de los 28 dias que terminan en `reference_date`, con la racha semanal."""
    reference = pd.Timestamp(reference_date).normalize()
    start = reference - pd.Timedelta(days=COVERAGE_WINDOW_DAYS - 1)
    sessions, logged = count_in_window(session_dates, logged_dates, start, reference)
    formation = formation_by_week(weekly_coverage(session_dates, logged_dates, until=reference))
    streak, stable_from = streak_at(formation, reference)
    return RpeCoverage(reference, sessions, logged, streak, stable_from)


def rolling_coverage_counts(calendar: pd.DatetimeIndex, session_dates, logged_dates) -> tuple[np.ndarray, np.ndarray]:
    """(sesiones, con RPE) de los 28 dias que terminan en cada dia de `calendar`.

    Vectorizado con la misma definicion que `rpe_coverage` (lo verifican los
    tests): lo usa `calc_acwr` para el gate diario del ACWR.
    """
    sessions = _dates(session_dates)
    logged_set = set(_dates(logged_dates))
    with_rpe = pd.DatetimeIndex([day for day in sessions if day in logged_set])
    days = pd.DatetimeIndex(calendar).normalize()
    starts = days - pd.Timedelta(days=COVERAGE_WINDOW_DAYS - 1)
    session_values = sessions.values
    rpe_values = with_rpe.values
    total = np.searchsorted(session_values, days.values, side="right") - np.searchsorted(
        session_values, starts.values, side="left"
    )
    logged = np.searchsorted(rpe_values, days.values, side="right") - np.searchsorted(
        rpe_values, starts.values, side="left"
    )
    return total.astype(int), logged.astype(int)


# ── Desde los DataFrames de la app ────────────────────────────────────────
def session_dates_by_athlete(raw_df: pd.DataFrame | None) -> dict[str, pd.DatetimeIndex]:
    from modules.load_monitoring import training_dates_by_athlete

    return training_dates_by_athlete(raw_df)


def logged_dates_by_athlete(rpe_df: pd.DataFrame | None, value_col: str = "sRPE") -> dict[str, pd.DatetimeIndex]:
    """Fechas con sRPE > 0 por atleta (clave de cruce sin tildes)."""
    from modules.load_monitoring import athlete_match_key

    if rpe_df is None or rpe_df.empty or not {"Athlete", "Date"}.issubset(rpe_df.columns):
        return {}
    frame = pd.DataFrame({
        "key": rpe_df["Athlete"].map(athlete_match_key),
        "Date": pd.to_datetime(rpe_df["Date"], errors="coerce").dt.normalize(),
    })
    if value_col in rpe_df.columns:
        frame = frame[pd.to_numeric(rpe_df[value_col], errors="coerce").gt(0).to_numpy()]
    frame = frame.dropna()
    frame = frame[frame["key"] != ""]
    return {key: pd.DatetimeIndex(group["Date"].unique()).sort_values() for key, group in frame.groupby("key")}


def coverage_by_athlete(
    raw_df: pd.DataFrame | None,
    rpe_df: pd.DataFrame | None,
    reference_date: object,
) -> dict[str, RpeCoverage]:
    """Cobertura de 28 dias de cada atleta con sesiones en Raw Workouts.

    Clave = `athlete_match_key` (sin tildes ni mayusculas). Es LA cobertura
    que muestran el KPI de registro, Equipo, el PDF profe y el PDF atleta.
    """
    sessions_by_key = session_dates_by_athlete(raw_df)
    rpe_by_key = logged_dates_by_athlete(rpe_df)
    return {key: rpe_coverage(sessions, rpe_by_key.get(key), reference_date) for key, sessions in sessions_by_key.items()}


def athlete_rpe_coverage(
    athlete: object,
    *,
    raw_df: pd.DataFrame | None,
    rpe_df: pd.DataFrame | None,
    reference_date: object,
) -> RpeCoverage | None:
    """Cobertura de un atleta; None si no tiene sesiones en Raw Workouts."""
    from modules.load_monitoring import athlete_match_key

    return coverage_by_athlete(raw_df, rpe_df, reference_date).get(athlete_match_key(athlete))


def coverage_from_acwr_frame(acwr_df: pd.DataFrame | None, reference_date: object | None = None) -> RpeCoverage | None:
    """Cobertura leida del frame de `calc_acwr` (las mismas cuentas que su gate).

    Las cuentas de 28 dias salen de las columnas que `calc_acwr` arma con el
    registro completo de sesiones; la racha semanal, de los dias del frame.
    """
    needed = {"Date", "Sesion_completada", "Sesiones_completadas_28d", "Sesiones_con_RPE_28d"}
    if acwr_df is None or acwr_df.empty or not needed.issubset(acwr_df.columns):
        return None
    frame = acwr_df.copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["Date"]).sort_values("Date")
    reference = pd.Timestamp(reference_date).normalize() if reference_date is not None else frame["Date"].max()
    scoped = frame[frame["Date"] <= reference]
    if scoped.empty:
        return None
    completed = scoped["Sesion_completada"].fillna(False).astype(bool)
    with_rpe = completed & pd.to_numeric(scoped["sRPE_diario"], errors="coerce").fillna(0).gt(0)
    streak_source = rpe_coverage(scoped.loc[completed, "Date"], scoped.loc[with_rpe, "Date"], reference)
    if scoped["Date"].iloc[-1] == reference:
        last = scoped.iloc[-1]
        sessions, logged = int(last["Sesiones_completadas_28d"]), int(last["Sesiones_con_RPE_28d"])
    else:
        sessions, logged = streak_source.sessions, streak_source.logged
    return RpeCoverage(reference, sessions, logged, streak_source.streak_weeks, streak_source.stable_from)


def team_registration_table(
    *,
    raw_df: pd.DataFrame | None,
    rpe_df: pd.DataFrame | None,
    wellness_df: pd.DataFrame | None,
    reference_date: object,
    athletes: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, float | None]:
    """KPI de registro: % RPE y % bienestar (28 dias) por atleta, de menor a mayor.

    Denominador = sesiones completadas en Raw Workouts. Bienestar = sesiones
    con un registro de bienestar el mismo dia. Devuelve (tabla, % RPE del
    equipo = suma con RPE / suma de sesiones).
    """
    from modules.load_monitoring import athlete_match_key

    columns = ["Atleta", "Sesiones (28 d)", "RPE %", "Bienestar %", "Te faltan"]
    sessions_by_key = session_dates_by_athlete(raw_df)
    if not sessions_by_key:
        return pd.DataFrame(columns=columns), None
    wellness_by_key = logged_dates_by_athlete(wellness_df, value_col="__all__")
    names: dict[str, str] = {}
    raw_athlete_col = "Athlete" if raw_df is not None and "Athlete" in raw_df.columns else "Name"
    if raw_df is not None and raw_athlete_col in raw_df.columns:
        for name in raw_df[raw_athlete_col].dropna().astype(str):
            names.setdefault(athlete_match_key(name), " ".join(name.split()))
    allowed = {athlete_match_key(name) for name in athletes} if athletes is not None else None
    reference = pd.Timestamp(reference_date).normalize()
    start = reference - pd.Timedelta(days=COVERAGE_WINDOW_DAYS - 1)
    coverages = coverage_by_athlete(raw_df, rpe_df, reference)
    rows = []
    total_sessions = total_logged = 0
    for key, sessions in sessions_by_key.items():
        if allowed is not None and key not in allowed:
            continue
        coverage = coverages[key]
        if not coverage.sessions:
            continue
        _, wellness_logged = count_in_window(sessions, wellness_by_key.get(key), start, reference)
        total_sessions += coverage.sessions
        total_logged += coverage.logged
        rows.append({
            "Atleta": names.get(key, key),
            "Sesiones (28 d)": coverage.sessions,
            "RPE %": round(100.0 * coverage.coverage, 0),
            "Bienestar %": round(100.0 * wellness_logged / coverage.sessions, 0),
            "Te faltan": coverage.missing,
        })
    table = pd.DataFrame(rows, columns=columns)
    if not table.empty:
        table = table.sort_values(["RPE %", "Bienestar %", "Atleta"], kind="mergesort").reset_index(drop=True)
    team_pct = 100.0 * total_logged / total_sessions if total_sessions else None
    return table, team_pct


WEEK_COVERAGE_COLUMNS = [
    "week_start",
    "rpe_sessions_week",
    "rpe_logged_week",
    "rpe_coverage_week",
    "rpe_coverage_28d",
    "rpe_missing_for_70",
    "rpe_coverage_forming",
    "rpe_stable_from",
]


def acwr_frame_week_coverage(acwr_df: pd.DataFrame | None) -> pd.DataFrame:
    """Cobertura por semana calendario desde un frame de `calc_acwr`.

    Semana (lunes) -> sesiones completadas, con RPE, cobertura de la semana,
    cobertura de 28 dias al ultimo dia de la semana, sesiones que faltan para
    el 70% y si la cronica esta "en formacion". Misma definicion que
    `rpe_coverage` (lo verifican los tests).
    """
    needed = {"Date", "Sesion_completada", "Sesiones_completadas_28d", "Sesiones_con_RPE_28d", "sRPE_diario"}
    if acwr_df is None or acwr_df.empty or not needed.issubset(acwr_df.columns):
        return pd.DataFrame(columns=WEEK_COVERAGE_COLUMNS)
    frame = acwr_df[list(needed)].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["Date"]).sort_values("Date")
    frame["done"] = frame["Sesion_completada"].fillna(False).astype(bool)
    frame["with_rpe"] = frame["done"] & pd.to_numeric(frame["sRPE_diario"], errors="coerce").fillna(0).gt(0)
    frame["week_start"] = frame["Date"] - pd.to_timedelta(frame["Date"].dt.weekday, unit="D")
    grouped = frame.groupby("week_start").agg(
        rpe_sessions_week=("done", "sum"),
        rpe_logged_week=("with_rpe", "sum"),
        sessions_28=("Sesiones_completadas_28d", "last"),
        logged_28=("Sesiones_con_RPE_28d", "last"),
        last_day=("Date", "last"),
    )
    weeks = [
        WeekCoverage(pd.Timestamp(week), int(row.rpe_sessions_week), int(row.rpe_logged_week))
        for week, row in grouped.iterrows()
    ]
    formation = formation_by_week(weeks)
    rows = []
    for week, row in grouped.iterrows():
        sessions_28, logged_28 = int(row.sessions_28), int(row.logged_28)
        coverage = RpeCoverage(pd.Timestamp(row.last_day), sessions_28, logged_28, *streak_at(formation, row.last_day))
        rows.append({
            "week_start": pd.Timestamp(week),
            "rpe_sessions_week": int(row.rpe_sessions_week),
            "rpe_logged_week": int(row.rpe_logged_week),
            "rpe_coverage_week": (row.rpe_logged_week / row.rpe_sessions_week) if row.rpe_sessions_week else np.nan,
            "rpe_coverage_28d": coverage.coverage if coverage.coverage is not None else np.nan,
            "rpe_missing_for_70": coverage.missing,
            "rpe_coverage_forming": coverage.forming,
            "rpe_stable_from": coverage.stable_from if coverage.forming else pd.NaT,
        })
    return pd.DataFrame(rows, columns=WEEK_COVERAGE_COLUMNS)


def week_monotony_allowed(sessions_week: object, logged_week: object) -> bool | None:
    """Cobertura de la semana >= 70%; None si no hay registro de sesiones."""
    sessions = pd.to_numeric(pd.Series([sessions_week]), errors="coerce").iloc[0]
    logged = pd.to_numeric(pd.Series([logged_week]), errors="coerce").iloc[0]
    if pd.isna(sessions) or sessions <= 0:
        return None
    return bool((0 if pd.isna(logged) else logged) / sessions >= COVERAGE_MIN - 1e-9)


# ── Textos compartidos (app, dashboard y PDF) ─────────────────────────────
def _number(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(numeric) else float(numeric)


def formation_text_for(forming: object, stable_from: object) -> str:
    if forming is None or (isinstance(forming, float) and math.isnan(forming)) or not bool(forming):
        return ""
    stamp = pd.to_datetime(stable_from, errors="coerce")
    if pd.isna(stamp):
        return ""
    return FORMATION_TEXT.format(date=f"{stamp:%d/%m}")


def acwr_display_text(value: object, reason: object = "", *, forming: object = False, stable_from: object = None) -> str:
    """ACWR visible ("1.12", "1.12 · carga crónica en formación (...)") u oculto (motivo)."""
    number = _number(value)
    if number is not None:
        legend = formation_text_for(forming, stable_from)
        return f"{number:.2f}" + (f" · {legend}" if legend else "")
    text = str(reason or "").strip()
    return text if text and text.lower() != "nan" else "-"


def week_gate_text(coverage_week: object, missing_28d: object) -> str:
    """Motivo de una monotonia/strain ocultos por cobertura semanal < 70%."""
    missing = _number(missing_28d)
    if missing is not None and missing > 0:
        return register_rpe_text(int(missing))
    coverage = _number(coverage_week)
    if coverage is not None:
        return f"RPE en {100 * coverage:.0f}% de las sesiones de la semana (mínimo 70%)"
    return "-"
