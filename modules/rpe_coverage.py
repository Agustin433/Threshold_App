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

# "Te faltan N" proyectado hacia adelante: el RPE de una sesion pasada no se
# recupera (Foster 2001: se toma ~30 min despues de la sesion), asi que N son
# sesiones FUTURAS seguidas con RPE hasta llegar al 70% en 28 dias.
REGISTER_RPE_BASE = "Registrá tu RPE en cada sesión"
REGISTER_RPE_TEXT = REGISTER_RPE_BASE + ": con {n} seguidas ves tu carga (~{date})"
REGISTER_RPE_TEXT_ONE = REGISTER_RPE_BASE + ": con 1 más ves tu carga (~{date})"
PROJECTION_HORIZON_DAYS = 60
HABITUAL_MIN_TIMES = 2
FORMATION_TEXT = "carga crónica en formación (estable desde ~{date})"
NO_SESSIONS_TEXT = "sin sesiones registradas en 28 días"


_EMPTY_DAYS = np.array([], dtype="datetime64[D]")


def _days(values: Iterable[object] | None) -> np.ndarray:
    """Dias unicos y ordenados (datetime64[D]). numpy: se llama por atleta."""
    if values is None:
        return _EMPTY_DAYS
    if isinstance(values, np.ndarray) and values.dtype == "datetime64[D]":
        return np.unique(values)
    if isinstance(values, (pd.DatetimeIndex, pd.Series)):
        array = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce")).to_numpy(dtype="datetime64[D]")
    else:
        array = pd.to_datetime(pd.Series(list(values), dtype=object), errors="coerce").to_numpy(dtype="datetime64[D]")
    array = array[~np.isnat(array)]
    return np.unique(array)


def _dates(values: Iterable[object] | None) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(_days(values))


def _day(value: object) -> np.datetime64:
    return np.datetime64(pd.Timestamp(value).normalize().date(), "D")


def _week_starts(days: np.ndarray) -> np.ndarray:
    weekday = (days.view("int64") + 3) % 7  # 1970-01-01 fue jueves
    return days - weekday.astype("timedelta64[D]")


def missing_for_target(sessions: int, logged: int, target: float = COVERAGE_MIN) -> int:
    """Sesiones sin RPE que faltan registrar para llegar al umbral."""
    if sessions <= 0:
        return 0
    needed = math.ceil(target * sessions - 1e-9)
    return max(0, needed - logged)


def register_rpe_text(n_sessions: int | None, target_date: object = None) -> str:
    """Mensaje de registro con la proyeccion; sin proyeccion, solo el pedido."""
    stamp = pd.to_datetime(target_date, errors="coerce")
    if n_sessions is None or pd.isna(stamp) or int(n_sessions) <= 0:
        return REGISTER_RPE_BASE
    template = REGISTER_RPE_TEXT_ONE if int(n_sessions) == 1 else REGISTER_RPE_TEXT
    return template.format(n=int(n_sessions), date=f"{stamp:%d/%m}")


def projection_label(n_sessions: int | None, target_date: object = None) -> str:
    """Celda del KPI: "8 sesiones · ~08/12"."""
    stamp = pd.to_datetime(target_date, errors="coerce")
    if n_sessions is None or pd.isna(stamp):
        return "sin proyección"
    if int(n_sessions) <= 0:
        return "—"
    unit = "sesión" if int(n_sessions) == 1 else "sesiones"
    return f"{int(n_sessions)} {unit} · ~{stamp:%d/%m}"


def habitual_weekdays(session_dates, reference_date: object) -> set[int]:
    """Dias de la semana (0 = lunes) con sesion en los ultimos 28 dias.

    Los que aparecen >= 2 veces; si no queda ninguno, todos los que tienen
    alguna sesion. Vacio si no hubo sesiones en la ventana.
    """
    sessions = _days(session_dates)
    end = _day(reference_date)
    start = end - np.timedelta64(COVERAGE_WINDOW_DAYS - 1, "D")
    window = sessions[(sessions >= start) & (sessions <= end)]
    if not len(window):
        return set()
    weekdays = (window.view("int64") + 3) % 7
    counts = np.bincount(weekdays, minlength=7)
    habitual = {int(day) for day in np.flatnonzero(counts >= HABITUAL_MIN_TIMES)}
    return habitual or {int(day) for day in np.flatnonzero(counts > 0)}


def sessions_to_target(session_dates, logged_dates, reference_date: object) -> tuple[int | None, pd.Timestamp | None]:
    """Sesiones futuras seguidas con RPE hasta cobertura >= 70% en 28 dias, y la fecha.

    Simula dia a dia desde el dia siguiente a `reference_date`: cada dia
    habitual (ver `habitual_weekdays`) suma una sesion con RPE y la ventana de
    28 dias avanza (las sesiones viejas sin RPE salen). Tope: 60 dias.
    Si ya cumple: (0, reference_date). Sin dias habituales o sin llegar en el
    tope: (None, None).
    """
    reference = _day(reference_date)
    sessions = _days(session_dates)
    sessions = sessions[sessions <= reference]
    logged = sessions[np.isin(sessions, _days(logged_dates))]

    def meets(day: np.datetime64, extra: int) -> bool:
        start = day - np.timedelta64(COVERAGE_WINDOW_DAYS - 1, "D")
        total = int(np.searchsorted(sessions, day, side="right") - np.searchsorted(sessions, start, side="left"))
        with_rpe = int(np.searchsorted(logged, day, side="right") - np.searchsorted(logged, start, side="left"))
        total += extra
        with_rpe += extra
        return total > 0 and with_rpe / total >= COVERAGE_MIN - 1e-9

    if meets(reference, 0):
        return 0, pd.Timestamp(reference)
    habitual = habitual_weekdays(sessions, reference)
    if not habitual:
        return None, None
    future: list[np.datetime64] = []
    for offset in range(1, PROJECTION_HORIZON_DAYS + 1):
        day = reference + np.timedelta64(offset, "D")
        if int((day.astype("datetime64[D]").view("int64") + 3) % 7) in habitual:
            future.append(day)
        # Sesiones simuladas dentro de la ventana que termina en `day`.
        start = day - np.timedelta64(COVERAGE_WINDOW_DAYS - 1, "D")
        in_window = sum(1 for item in future if item >= start)
        if future and meets(day, in_window):
            return len(future), pd.Timestamp(day)
    return None, None


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
    # Proyeccion hacia adelante (sessions_to_target): None si no se calculo o
    # no hay dias habituales.
    to_target: int | None = None
    target_date: pd.Timestamp | None = None

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
    def forming(self) -> bool:
        """Supero el 70% pero con menos de 4 semanas seguidas >= 70%."""
        return self.meets and self.streak_weeks < FORMATION_WEEKS

    @property
    def register_text(self) -> str:
        """"" si ya cumple; si no, el pedido con la proyeccion (si la hay)."""
        if self.meets:
            return ""
        return register_rpe_text(self.to_target, self.target_date)

    @property
    def projection_label(self) -> str:
        return projection_label(self.to_target, self.target_date)

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
            "rpe_to_target": self.to_target,
            "rpe_target_date": self.target_date,
            "rpe_coverage_ok": self.meets,
            "rpe_coverage_forming": self.forming,
            "rpe_stable_from": self.stable_from,
        }


def count_in_window(session_dates, logged_dates, start, end) -> tuple[int, int]:
    """(sesiones completadas, de esas con RPE) entre start y end inclusive."""
    sessions = _days(session_dates)
    in_window = sessions[(sessions >= _day(start)) & (sessions <= _day(end))]
    logged = np.isin(in_window, _days(logged_dates))
    return int(len(in_window)), int(logged.sum())


def weekly_coverage(session_dates, logged_dates, *, until: object | None = None) -> list[WeekCoverage]:
    """Cobertura por semana calendario (lunes a domingo), en orden."""
    sessions = _days(session_dates)
    if until is not None:
        sessions = sessions[sessions <= _day(until)]
    if not len(sessions):
        return []
    logged = np.isin(sessions, _days(logged_dates)).astype(int)
    weeks = _week_starts(sessions)
    starts = np.flatnonzero(np.r_[True, weeks[1:] != weeks[:-1]])
    sizes = np.diff(np.r_[starts, len(weeks)])
    counts = np.add.reduceat(logged, starts)
    return [
        WeekCoverage(pd.Timestamp(weeks[start]), int(size), int(count))
        for start, size, count in zip(starts, sizes, counts)
    ]


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
    if streak_start is not None:
        start = streak_start
    else:
        # Sin racha: la mas temprana posible arranca en la semana en curso si
        # todavia no termino, o en la proxima.
        current = week_start(reference_date)
        start = current if not week_finished(current, reference_date) else current + pd.Timedelta(days=7)
    return pd.Timestamp(start) + pd.Timedelta(days=FORMATION_WEEKS * 7)


def week_finished(week: object, reference_date: object) -> bool:
    """La semana (lunes) ya termino: su domingo es <= la fecha de referencia."""
    return week_start(week) + pd.Timedelta(days=6) <= pd.Timestamp(reference_date).normalize()


def streak_at(formation: dict[pd.Timestamp, tuple[int, pd.Timestamp | None]], reference_date: object) -> tuple[int, pd.Timestamp]:
    """Racha a la fecha de referencia. La semana en curso solo cuenta si ya termino:
    si no termino, no suma ni corta (un lunes con 1/1 no completa una racha)."""
    current = week_start(reference_date)
    last_counted = current if week_finished(current, reference_date) else current - pd.Timedelta(days=7)
    previous = [week for week in formation if week <= last_counted]
    streak, start = formation[max(previous)] if previous else (0, None)
    return streak, stable_from_date(reference_date, start)


def rpe_coverage(session_dates, logged_dates, reference_date: object) -> RpeCoverage:
    """Cobertura de los 28 dias que terminan en `reference_date`, con la racha semanal."""
    reference = pd.Timestamp(reference_date).normalize()
    start = reference - pd.Timedelta(days=COVERAGE_WINDOW_DAYS - 1)
    sessions, logged = count_in_window(session_dates, logged_dates, start, reference)
    formation = formation_by_week(weekly_coverage(session_dates, logged_dates, until=reference))
    streak, stable_from = streak_at(formation, reference)
    to_target, target_date = sessions_to_target(session_dates, logged_dates, reference)
    return RpeCoverage(reference, sessions, logged, streak, stable_from, to_target, target_date)


def rolling_coverage_counts(calendar: pd.DatetimeIndex, session_dates, logged_dates) -> tuple[np.ndarray, np.ndarray]:
    """(sesiones, con RPE) de los 28 dias que terminan en cada dia de `calendar`.

    Vectorizado con la misma definicion que `rpe_coverage` (lo verifican los
    tests): lo usa `calc_acwr` para el gate diario del ACWR.
    """
    sessions = _days(session_dates)
    with_rpe = sessions[np.isin(sessions, _days(logged_dates))]
    days = pd.DatetimeIndex(calendar).to_numpy(dtype="datetime64[D]")
    starts = days - np.timedelta64(COVERAGE_WINDOW_DAYS - 1, "D")
    total = np.searchsorted(sessions, days, side="right") - np.searchsorted(sessions, starts, side="left")
    logged = np.searchsorted(with_rpe, days, side="right") - np.searchsorted(with_rpe, starts, side="left")
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

    columns = ["Atleta", "Sesiones (28 d)", "RPE %", "Bienestar %", "Para ver su carga"]
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
            "Para ver su carga": coverage.projection_label,
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
    "rpe_coverage_forming",
    "rpe_stable_from",
]


def acwr_frame_week_coverage(acwr_df: pd.DataFrame | None) -> pd.DataFrame:
    """Cobertura por semana calendario desde un frame de `calc_acwr`.

    Semana (lunes) -> sesiones completadas, con RPE, cobertura de la semana,
    cobertura de 28 dias al ultimo dia de la semana y si la cronica esta "en
    formacion". La proyeccion ("con N seguidas") no va aca: es hacia adelante
    desde la fecha de referencia (`sessions_to_target`). Misma definicion que
    `rpe_coverage` (lo verifican los tests).
    """
    needed = {"Date", "Sesion_completada", "Sesiones_completadas_28d", "Sesiones_con_RPE_28d", "sRPE_diario"}
    if acwr_df is None or acwr_df.empty or not needed.issubset(acwr_df.columns):
        return pd.DataFrame(columns=WEEK_COVERAGE_COLUMNS)
    # numpy puro: se llama una vez por atleta y por resumen semanal, y el
    # groupby de pandas costaba ~20 ms por atleta.
    dates = pd.to_datetime(acwr_df["Date"], errors="coerce").dt.normalize().to_numpy(dtype="datetime64[D]")
    valid = ~np.isnat(dates)
    order = np.argsort(dates[valid], kind="stable")
    dates = dates[valid][order]
    done = acwr_df["Sesion_completada"].fillna(False).to_numpy(dtype=bool)[valid][order]
    loads = pd.to_numeric(acwr_df["sRPE_diario"], errors="coerce").fillna(0).to_numpy(dtype=float)[valid][order]
    with_rpe = done & (loads > 0)
    sessions_28 = pd.to_numeric(acwr_df["Sesiones_completadas_28d"], errors="coerce").fillna(0).to_numpy()[valid][order]
    logged_28 = pd.to_numeric(acwr_df["Sesiones_con_RPE_28d"], errors="coerce").fillna(0).to_numpy()[valid][order]
    if not len(dates):
        return pd.DataFrame(columns=WEEK_COVERAGE_COLUMNS)
    weekday = (dates.astype("datetime64[D]").view("int64") - 4) % 7  # 1970-01-01 fue jueves
    weeks = dates - weekday.astype("timedelta64[D]")
    starts = np.flatnonzero(np.r_[True, weeks[1:] != weeks[:-1]])
    ends = np.r_[starts[1:], len(weeks)] - 1
    week_sessions = np.add.reduceat(done.astype(int), starts)
    week_logged = np.add.reduceat(with_rpe.astype(int), starts)
    items = [
        WeekCoverage(pd.Timestamp(weeks[start]), int(n_sessions), int(n_logged))
        for start, n_sessions, n_logged in zip(starts, week_sessions, week_logged)
    ]
    formation = formation_by_week(items)
    rows = []
    for item, end in zip(items, ends):
        last_day = pd.Timestamp(dates[end])
        coverage = RpeCoverage(last_day, int(sessions_28[end]), int(logged_28[end]), *streak_at(formation, last_day))
        rows.append({
            "week_start": item.week_start,
            "rpe_sessions_week": item.sessions,
            "rpe_logged_week": item.logged,
            "rpe_coverage_week": item.coverage if item.coverage is not None else np.nan,
            "rpe_coverage_28d": coverage.coverage if coverage.coverage is not None else np.nan,
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


def acwr_display_text(
    value: object,
    reason: object = "",
    *,
    forming: object = False,
    stable_from: object = None,
    value_date: object = None,
    reference_date: object = None,
) -> str:
    """ACWR visible u oculto (motivo).

    "1.12", "1.12 · carga crónica en formación (...)", y si el valor es de
    antes de la fecha de referencia: "ACWR al 20/11: 1.12".
    """
    number = _number(value)
    if number is not None:
        legend = formation_text_for(forming, stable_from)
        text = f"{number:.2f}"
        shown = pd.to_datetime(value_date, errors="coerce")
        reference = pd.to_datetime(reference_date, errors="coerce")
        if pd.notna(shown) and pd.notna(reference) and shown.normalize() < reference.normalize():
            text = f"ACWR al {shown:%d/%m}: {text}"
        return text + (f" · {legend}" if legend else "")
    text = str(reason or "").strip()
    return text if text and text.lower() != "nan" else "-"


def week_gate_text(coverage_week: object, register_text: object = "") -> str:
    """Motivo de una monotonia/strain ocultos por cobertura semanal < 70%.

    `register_text`: el de la proyeccion (`RpeCoverage.register_text`); vacio
    si la cobertura de 28 dias ya cumple, y entonces se dice la de la semana.
    """
    text = str(register_text or "").strip()
    if text and text.lower() != "nan":
        return text
    coverage = _number(coverage_week)
    if coverage is not None:
        return f"RPE en {100 * coverage:.0f}% de las sesiones de la semana (mínimo 70%)"
    return "-"
