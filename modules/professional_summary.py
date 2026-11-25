"""Resumen ejecutivo del PDF profe (2 paginas): datos puros, sin reportlab.

Pagina 1 "Resumen - Evaluacion": cambios vs evaluacion anterior (solo
comparables), alertas de calidad del dato. Pagina 2 "Resumen - Carga y
bienestar": sRPE semanal de 8 semanas con ACWR de contexto, sesiones
completadas por semana (desde raw) y bienestar con banda personal.

Todo sale de las mismas funciones que usan el reporte atleta y el dashboard
(`compute_evaluation_changes`, `tolerance_reading`, `weekly_srpe`,
`completed_sessions`, el modelo ACWR de `build_load_models`), asi que el
resumen no puede contradecir al anexo.
"""

from __future__ import annotations

import pandas as pd

from modules import athlete_report as ar
from modules.evaluation_rules import (
    IMTP_NO_RISE_FLAG,
    IMTP_QUALITY_FLAG_COLUMN,
    jump_height_flagged_tests,
)
from modules.jump_analysis import NO_IMPULSE_COMPARISON_SIGNAL
from modules.measurement_eras import CURRENT_ERA, ERA_CHANGE_SIGNAL, era_label

SUMMARY_LOAD_WEEKS = 8
SUMMARY_WELLNESS_DAYS = SUMMARY_LOAD_WEEKS * 7
STALE_EVALUATION_WEEKS = 12

# Variables de la tabla de cambios del resumen (las del anexo, sin derivadas
# que repiten la misma informacion).
SUMMARY_CHANGE_VARIABLES: tuple[str, ...] = (
    "CMJ_cm",
    "CMJ_ft_cm",
    "SJ_cm",
    "SJ_ft_cm",
    "DJ_cm",
    "DJ_RSI",
    "DJ_tc_ms",
    "IMTP_N",
    "IMTP_relPF",
    "EUR",
    "DSI",
)
RELEVANT_SIGNALS = {"mejora relevante": "↑ supera umbral", "caida relevante": "↓ supera umbral"}
NO_CHANGE_SIGNAL = "sin cambio relevante"
NO_COMPARABLE_ERA_TEXT = "no comparable (cruza era)"
NO_CHANGE_TEXT = "dentro del umbral"
UNUSUAL_TEXT = " · verificar"
CROSS_ERA_TEXT = " · ⚠ cruza era"


def _number(value: object) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def _fmt(value: float | None, variable: str) -> str:
    if value is None:
        return "-"
    digits = 0 if variable in {"IMTP_N", "DJ_tc_ms"} else 2 if variable in {"DJ_RSI", "EUR", "DSI"} else 1
    return f"{value:.{digits}f}"


def _fmt_date(value: object) -> str:
    stamp = pd.to_datetime(value, errors="coerce")
    return "-" if pd.isna(stamp) else f"{stamp:%d/%m/%Y}"


def summary_change_rows(delta_df: pd.DataFrame | None) -> list[dict[str, str]]:
    """Filas de "Cambios vs evaluacion anterior" del resumen.

    Variables con valor anterior. PR L: las que cruzan de era se comparan
    igual y llevan "⚠ cruza era" (el cartel bajo la tabla dice que se
    compara). Sin dato anterior o sin comparacion por impulso no entran (la
    segunda va a las alertas).
    """
    if delta_df is None or delta_df.empty:
        return []
    rows: list[dict[str, str]] = []
    for variable in SUMMARY_CHANGE_VARIABLES:
        match = delta_df[delta_df["Variable"] == variable]
        if match.empty:
            continue
        row = match.iloc[0]
        current = _number(row.get("Valor_actual"))
        previous = _number(row.get("Valor_anterior"))
        signal = str(row.get("Signal") or "")
        if current is None:
            continue
        label = str(row.get("Label") or variable)
        cross_era = str(row.get("Cross_era")) == "True"
        if signal == ERA_CHANGE_SIGNAL:
            rows.append(
                {
                    "Variable": label,
                    "Anterior": "-",
                    "Actual": _fmt(current, variable),
                    "Cambio": "-",
                    "Umbral": "-",
                    "Lectura": NO_COMPARABLE_ERA_TEXT,
                }
            )
            continue
        if previous is None:
            continue
        delta = _number(row.get("Delta_abs"))
        delta_pct = _number(row.get("Delta_pct"))
        threshold = _number(row.get("Threshold_abs"))
        reading = RELEVANT_SIGNALS.get(signal, NO_CHANGE_TEXT if signal == NO_CHANGE_SIGNAL else signal)
        if bool(row.get("Unusual")):
            reading += UNUSUAL_TEXT
        if cross_era:
            reading += CROSS_ERA_TEXT
        delta_text = "-" if delta is None else f"{delta:+.{2 if variable in {'DJ_RSI', 'EUR', 'DSI'} else 1}f}"
        if delta_pct is not None:
            delta_text += f" ({delta_pct:+.0f}%)"
        rows.append(
            {
                "Variable": label,
                "Anterior": f"{_fmt(previous, variable)} ({_fmt_date(row.get('Fecha_anterior'))[:5]})",
                "Actual": _fmt(current, variable),
                "Cambio": delta_text,
                "Umbral": "-" if threshold is None else f"±{_fmt(threshold, variable)}",
                "Lectura": reading,
            }
        )
    return rows


def latest_evaluation(history: pd.DataFrame | None) -> dict[str, object] | None:
    """Fecha y protocolo (era del device) de la ultima evaluacion."""
    if history is None or history.empty or "Date" not in history.columns:
        return None
    dated = history.assign(_date=pd.to_datetime(history["Date"], errors="coerce")).dropna(subset=["_date"])
    if dated.empty:
        return None
    row = dated.sort_values("_date").iloc[-1]
    device = str(row.get("Device") or "").strip()
    return {
        "date": pd.Timestamp(row["_date"]).normalize(),
        "era": device,
        "era_label": era_label(device) if device else "protocolo sin dato",
        "row": row,
    }


def data_quality_alerts(
    history: pd.DataFrame | None,
    delta_df: pd.DataFrame | None,
    *,
    today: object,
) -> list[str]:
    """Alertas de calidad del dato. Lista vacia si no hay ninguna (no se muestra la linea).

    - IMTP con protocolo anterior (era distinta de la vigente).
    - Altura por impulso descartada (en la ultima toma o en la anterior que se compara).
    - Toma invalida (IMTP con curva sin subida).
    - Evaluacion de mas de 12 semanas.
    """
    alerts: list[str] = []
    latest = latest_evaluation(history)
    if latest is None:
        return alerts
    row = latest["row"]
    if "IMTP_N" in history.columns:
        imtp_rows = history[pd.to_numeric(history["IMTP_N"], errors="coerce").notna()].copy()
        imtp_rows["_date"] = pd.to_datetime(imtp_rows["Date"], errors="coerce")
        imtp_rows = imtp_rows.dropna(subset=["_date"]).sort_values("_date")
        if not imtp_rows.empty:
            last_imtp = imtp_rows.iloc[-1]
            device = str(last_imtp.get("Device") or "").strip()
            if device and device != CURRENT_ERA:
                alerts.append(
                    f"IMTP con protocolo anterior ({era_label(device)}, {_fmt_date(last_imtp['_date'])}): "
                    f"se compara con {era_label(CURRENT_ERA)} con aviso; suele dar ~30% menos."
                )
            if str(last_imtp.get(IMTP_QUALITY_FLAG_COLUMN) or "") == IMTP_NO_RISE_FLAG:
                alerts.append(
                    f"Toma IMTP inválida para RFD y fuerza a 50–250 ms ({_fmt_date(last_imtp['_date'])}): "
                    "curva sin subida tras el inicio. El pico se informa."
                )
    flagged = jump_height_flagged_tests(row)
    if flagged:
        alerts.append(
            f"Altura por impulso descartada en {', '.join(flagged)} ({_fmt_date(latest['date'])}): "
            "se compara por tiempo de vuelo."
        )
    if delta_df is not None and not delta_df.empty and "Signal" in delta_df.columns:
        blocked = delta_df[delta_df["Signal"] == NO_IMPULSE_COMPARISON_SIGNAL]
        blocked_labels = [str(label) for label in blocked.get("Label", pd.Series(dtype=object)).tolist() if str(label)]
        if blocked_labels and not flagged:
            alerts.append(
                f"Sin comparación por impulso en {', '.join(blocked_labels)}: la toma anterior tiene la altura "
                "por impulso descartada (ver la serie por tiempo de vuelo)."
            )
    age_days = (pd.Timestamp(today).normalize() - latest["date"]).days
    if age_days > STALE_EVALUATION_WEEKS * 7:
        alerts.append(f"Última evaluación de hace {age_days // 7} semanas (más de {STALE_EVALUATION_WEEKS}).")
    return alerts


def _week_start(value: pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(value).normalize()
    return value - pd.Timedelta(days=value.dayofweek)


def weekly_load_summary(
    rpe_df: pd.DataFrame | None,
    raw_df: pd.DataFrame | None,
    acwr_df: pd.DataFrame | None,
    athlete: str,
    *,
    today: object,
    weeks: int = SUMMARY_LOAD_WEEKS,
) -> pd.DataFrame:
    """Una fila por semana (lunes), las ultimas `weeks` incluida la actual.

    Columnas: week_start, srpe (suma de sRPE; NaN sin registros), acwr (ultimo
    ACWR EWMA valido de la semana; contexto, sin semaforo), sessions
    (sesiones completadas segun raw, no el % del export), in_progress.
    """
    end = pd.Timestamp(today).normalize()
    current = _week_start(end)
    starts = [current - pd.Timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)]
    window_start = starts[0]
    srpe = ar.weekly_srpe(rpe_df, athlete, start=window_start - pd.Timedelta(days=1), end=end)
    srpe_by_week = dict(zip(pd.to_datetime(srpe["week_start"]), srpe["load"])) if not srpe.empty else {}

    acwr_by_week: dict[pd.Timestamp, float] = {}
    if isinstance(acwr_df, pd.DataFrame) and not acwr_df.empty and {"Date", "ACWR_EWMA"}.issubset(acwr_df.columns):
        acwr = acwr_df[["Date", "ACWR_EWMA"]].copy()
        acwr["Date"] = pd.to_datetime(acwr["Date"], errors="coerce").dt.normalize()
        acwr["ACWR_EWMA"] = pd.to_numeric(acwr["ACWR_EWMA"], errors="coerce")
        acwr = acwr.dropna().sort_values("Date")
        acwr = acwr[(acwr["Date"] >= window_start) & (acwr["Date"] <= end)]
        for _, item in acwr.iterrows():
            acwr_by_week[_week_start(item["Date"])] = float(item["ACWR_EWMA"])

    rows = []
    for start in starts:
        week_end = min(start + pd.Timedelta(days=6), end)
        rows.append(
            {
                "week_start": start,
                "srpe": float(srpe_by_week[start]) if start in srpe_by_week else float("nan"),
                "acwr": acwr_by_week.get(start, float("nan")),
                "sessions": ar.completed_sessions(raw_df, athlete, window_start=start, window_end=week_end),
                "in_progress": bool(start == current),
            }
        )
    return pd.DataFrame(rows)


def wellness_summary(
    wellness_df: pd.DataFrame | None,
    athlete: str,
    *,
    today: object,
    days: int = SUMMARY_WELLNESS_DAYS,
) -> dict[str, object] | None:
    """Bienestar diario con banda personal (mismo calculo que el reporte atleta) y la variable que mas se movio."""
    reading = ar.tolerance_reading(wellness_df, None, athlete, today=today, window_days=days)
    if reading is None:
        return None
    rows = ar._athlete_rows(wellness_df, athlete)
    rows = rows[rows["Date"] <= pd.Timestamp(today).normalize()]
    shift = ar.wellness_component_shift(rows, pd.Timestamp(reading["window_start"]))
    if shift is None:
        moved = "Ninguna variable de bienestar (sueño, estrés, dolor) tiene historia previa suficiente para comparar."
    else:
        moved = (
            f"Variable que más se movió: {shift['name']} {shift['window_mean']:.1f}{shift['unit']} "
            f"vs {shift['prior_mean']:.1f}{shift['unit']} antes ({shift['change_sd']:+.1f} DE, {shift['direction']})."
        )
    return {**reading, "moved_line": moved, "shift": shift}


PROFESSIONAL_TOLERANCE_TEXT = {
    "within": "Bienestar dentro de su banda personal (media ± 1 DE de los 28 días previos).",
    "below": "Bienestar por debajo de su banda personal en la ventana.",
    "above": "Bienestar por encima de su banda personal en la ventana.",
    "unknown": "Pocos registros para una banda personal.",
}


def _last_record_date(frame: pd.DataFrame | None, athlete: str) -> pd.Timestamp | None:
    rows = ar._athlete_rows(frame, athlete)
    return None if rows.empty else pd.Timestamp(rows["Date"].max())


def weekly_load_lines(
    weekly: pd.DataFrame,
    rpe_df: pd.DataFrame | None,
    athlete: str,
    *,
    coverage=None,
    acwr_coverage=None,
) -> list[str]:
    """Lo que el grafico no dice solo: cobertura de RPE, semanas sin RPE, ACWR sin dato.

    `coverage` (modules.rpe_coverage.RpeCoverage, 28 dias a la fecha del
    resumen): con < 70% el ACWR, la monotonia y el strain no se muestran y se
    dice cuantas sesiones faltan registrar (PR S). `acwr_coverage`: la del
    ultimo dia entrenado, para la leyenda de cronica en formacion.
    """
    lines: list[str] = []
    if weekly is None or weekly.empty:
        return lines
    if coverage is not None and coverage.pct is not None:
        coverage_line = (
            f"RPE registrado en {coverage.pct:.0f}% de las sesiones de 28 días "
            f"({coverage.logged} de {coverage.sessions})."
        )
        if not coverage.meets:
            coverage_line += (
                f" {coverage.register_text}: con menos del 70% ACWR, monotonía y strain describen "
                "el registro, no la carga, y no se muestran."
            )
        elif acwr_coverage is not None and acwr_coverage.forming:
            coverage_line += f" ACWR con {acwr_coverage.formation_text}."
        lines.append(coverage_line)
    srpe = pd.to_numeric(weekly["srpe"], errors="coerce")
    sessions = pd.to_numeric(weekly["sessions"], errors="coerce").fillna(0).astype(int)
    total = int(sessions.sum())
    lines.append(f"Sesiones completadas (registro de TeamBuildr): {total} en {len(weekly)} semanas.")
    if srpe.isna().all():
        last = _last_record_date(rpe_df, athlete)
        tail = f" (último registro: {last:%d/%m/%Y})" if last is not None else ""
        lines.append(f"Sin sRPE en las últimas {len(weekly)} semanas{tail}: la carga interna no se puede leer.")
    else:
        missing = [f"{pd.Timestamp(w):%d/%m}" for w, s, n in zip(weekly["week_start"], srpe, sessions) if pd.isna(s) and n > 0]
        if missing:
            lines.append(f"Semanas con sesiones completadas y sin RPE: {', '.join(missing)} (la barra no refleja esa carga).")
        low_coverage = coverage is not None and coverage.pct is not None and not coverage.meets
        if pd.to_numeric(weekly["acwr"], errors="coerce").isna().all() and not low_coverage:
            lines.append("ACWR sin dato en la ventana: registro de sRPE incompleto.")
    return lines


def wellness_lines(wellness: dict[str, object]) -> list[str]:
    signal = str(wellness.get("signal") or "unknown")
    first = PROFESSIONAL_TOLERANCE_TEXT.get(signal, PROFESSIONAL_TOLERANCE_TEXT["unknown"])
    first += f" Promedio de la ventana: {float(wellness['window_mean']):.1f}/30 ({wellness['window_class']}), {wellness['n_records']} registros."
    return [first, str(wellness.get("moved_line") or "")]


def no_wellness_line(wellness_df: pd.DataFrame | None, athlete: str, *, today: object, days: int = SUMMARY_WELLNESS_DAYS) -> str:
    last = _last_record_date(wellness_df, athlete)
    weeks = days // 7
    if last is None:
        return "Sin registros de bienestar cargados."
    return f"Menos de 3 registros de bienestar en las últimas {weeks} semanas (último: {last:%d/%m/%Y})."


def cross_era_banner(delta_df: pd.DataFrame | None) -> str | None:
    """Cartel bajo la tabla de cambios: que eras se estan comparando."""
    from modules.jump_analysis import cross_era_rows

    rows = cross_era_rows(delta_df)
    if rows.empty:
        return None
    labels = ", ".join(dict.fromkeys(str(label) for label in rows["Label"].tolist()))
    # La nota del IMTP es la mas completa (trae el ~30% del protocolo anterior).
    imtp_rows = rows[rows["Variable"].astype(str).str.startswith("IMTP")]
    note = str((imtp_rows if not imtp_rows.empty else rows)["Comparison_note"].iloc[0])
    return f"⚠ {labels}: {note}."
