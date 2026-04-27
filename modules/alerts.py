from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import unicodedata
from typing import Iterable

import pandas as pd

from modules.jump_analysis import compute_baseline_delta, compute_swc_delta
from modules.metrics import calculate_completion_rate


ALERT_CATEGORIES = ("data_quality", "load_risk", "adherence", "evaluations")
ALERT_SEVERITIES = ("danger", "warning", "info")
SEVERITY_WEIGHT = {"danger": 3, "warning": 2, "info": 1}

ACWR_WARNING = 1.30
ACWR_DANGER = 1.50
MONOTONY_WARNING = 2.00
ADHERENCE_WARNING = 90.0
ADHERENCE_DANGER = 70.0
EVALUATION_WARNING_DAYS = 30
EVALUATION_DANGER_DAYS = 60
BASELINE_MATERIAL_DROP_PCT = 5.0


@dataclass(frozen=True)
class ProductAlert:
    category: str
    severity: str
    priority: int
    title: str
    message: str
    athlete: str | None = None
    source: str = ""
    action: str = ""
    scope: str = "team"
    surface: str = "app"
    key: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["priority"] = int(self.priority)
        return payload


def _ascii_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -")


def _slug(value: object) -> str:
    text = _ascii_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "alert"


def _coerce_float(value: object) -> float | None:
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(number):
        return None
    return float(number)


def _coerce_reference_date(reference_date=None) -> pd.Timestamp:
    if reference_date is None:
        return pd.Timestamp.today().normalize()
    return pd.Timestamp(reference_date).normalize()


def _week_start_for(reference_date: pd.Timestamp) -> pd.Timestamp:
    return reference_date - pd.Timedelta(days=int(reference_date.weekday()))


def _normalize_weekly_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "week_start" in result.columns:
        result["week_start"] = pd.to_datetime(result["week_start"], errors="coerce").dt.normalize()
    if "is_current_week" in result.columns:
        result["is_current_week"] = result["is_current_week"].fillna(False).astype(bool)
    return result


def _week_slice(
    frame: pd.DataFrame | None,
    *,
    reference_date: pd.Timestamp,
    week_start=None,
) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    result = _normalize_weekly_frame(frame)
    if result.empty:
        return result, None

    if week_start is not None and "week_start" in result.columns:
        selected_week = pd.Timestamp(week_start).normalize()
        return result[result["week_start"].eq(selected_week)].copy(), selected_week

    if "is_current_week" in result.columns:
        current = result[result["is_current_week"].fillna(False)]
        if not current.empty:
            selected_week = None
            if "week_start" in current.columns and current["week_start"].notna().any():
                selected_week = pd.Timestamp(current["week_start"].dropna().max()).normalize()
            return current.copy(), selected_week

    if "week_start" in result.columns and result["week_start"].notna().any():
        selected_week = pd.Timestamp(result["week_start"].dropna().max()).normalize()
        return result[result["week_start"].eq(selected_week)].copy(), selected_week

    return result.tail(1).copy(), _week_start_for(reference_date)


def _week_label(week_start: pd.Timestamp | None, fallback: str = "semana actual") -> str:
    if week_start is None or pd.isna(week_start):
        return fallback
    week_end = pd.Timestamp(week_start).normalize() + pd.Timedelta(days=6)
    return f"semana {pd.Timestamp(week_start):%d/%m}-{week_end:%d/%m}"


def _make_alert(
    *,
    category: str,
    severity: str,
    priority: int,
    title: str,
    message: str,
    athlete: str | None = None,
    source: str = "",
    action: str = "",
    scope: str = "team",
    surface: str = "app",
    key: str | None = None,
    meta: dict[str, object] | None = None,
) -> ProductAlert:
    safe_category = category if category in ALERT_CATEGORIES else "data_quality"
    safe_severity = severity if severity in ALERT_SEVERITIES else "info"
    safe_athlete = _ascii_text(athlete) if athlete else None
    safe_title = _ascii_text(title)
    safe_message = _ascii_text(message)
    safe_action = _ascii_text(action)
    fingerprint = key or f"{safe_category}:{safe_athlete or scope}:{safe_title}:{safe_message}"
    return ProductAlert(
        category=safe_category,
        severity=safe_severity,
        priority=int(priority),
        title=safe_title,
        message=safe_message,
        athlete=safe_athlete,
        source=_ascii_text(source),
        action=safe_action,
        scope=_ascii_text(scope or "team"),
        surface=_ascii_text(surface or "app"),
        key=_slug(fingerprint),
        meta=meta or {},
    )


def _is_local_ui_message(message: str) -> bool:
    lower = _ascii_text(message).lower()
    local_prefixes = (
        "no hay datos",
        "carga ",
        "carg",
        "reporte generado",
        "sin suficientes",
        "no hay suficientes",
        "zona optima",
    )
    return any(lower.startswith(prefix) for prefix in local_prefixes)


def _data_quality_alerts(
    quality_report: dict[str, object] | None,
    *,
    scope: str,
    surface: str,
) -> list[ProductAlert]:
    raw_alerts = []
    if isinstance(quality_report, dict):
        raw_alerts = quality_report.get("alerts", []) or []

    alerts: list[ProductAlert] = []
    for raw_alert in raw_alerts:
        message = _ascii_text(raw_alert)
        if not message or _is_local_ui_message(message):
            continue

        lower = message.lower()
        # P11 v1 handles evaluation staleness in the evaluation category to avoid
        # duplicating the same issue with a different wording.
        if "evaluaciones" in lower or "ultimo test" in lower:
            continue

        label = ""
        detail = message
        athlete = None
        if " - " in message:
            label, detail = [part.strip() for part in message.split(" - ", 1)]
            known_sources = {"raw workouts", "rpe + tiempo", "wellness", "completion", "maxes"}
            if label.lower() not in known_sources:
                athlete = label
                title = "Calidad de datos del atleta"
            else:
                title = f"Calidad de datos: {label}"
        else:
            title = "Calidad de datos"

        severity = "danger" if any(
            token in lower for token in ("result = 0", "reps = 0", "tag invalido")
        ) else "warning"
        priority = 82 if severity == "danger" else 72 if "hueco" in lower else 66

        alerts.append(
            _make_alert(
                category="data_quality",
                severity=severity,
                priority=priority,
                title=title,
                message=detail,
                athlete=athlete,
                source="compute_data_quality_report",
                action="Abrir Calidad de datos antes de interpretar o exportar.",
                scope=scope,
                surface=surface,
                key=f"data_quality:{label or 'general'}:{detail}",
            )
        )
    return alerts


def _load_risk_alerts(
    weekly_summaries: dict[str, pd.DataFrame] | None,
    *,
    reference_date: pd.Timestamp,
    week_start=None,
    scope: str,
    surface: str,
    athlete: str | None = None,
) -> list[ProductAlert]:
    weekly_load = weekly_summaries.get("weekly_load") if isinstance(weekly_summaries, dict) else None
    current_load, selected_week = _week_slice(weekly_load, reference_date=reference_date, week_start=week_start)
    if current_load.empty:
        return []

    if athlete and athlete != "Todos" and "Athlete" in current_load.columns:
        current_load = current_load[current_load["Athlete"].astype(str).str.strip() == str(athlete).strip()]
    if current_load.empty:
        return []

    label = _week_label(selected_week)
    alerts: list[ProductAlert] = []
    for _, row in current_load.iterrows():
        athlete_name = _ascii_text(row.get("Athlete")) or None
        acwr = _coerce_float(row.get("ACWR_EWMA_last"))
        monotony = _coerce_float(row.get("monotony"))
        monotony_status = _ascii_text(row.get("monotony_status")).strip()
        triggers: list[str] = []
        severity = "info"
        priority = 0

        if acwr is not None and acwr > ACWR_DANGER:
            severity = "danger"
            priority = max(priority, 96)
            triggers.append(f"ACWR EWMA {acwr:.2f}")
        elif acwr is not None and acwr > ACWR_WARNING:
            severity = "warning"
            priority = max(priority, 84)
            triggers.append(f"ACWR EWMA {acwr:.2f}")

        if monotony_status == "zero_variability":
            severity = "danger" if severity == "danger" else "warning"
            priority = max(priority, 88)
            triggers.append("monotonia sin variabilidad")
        elif monotony is not None and monotony > MONOTONY_WARNING:
            severity = "danger" if severity == "danger" else "warning"
            priority = max(priority, 86)
            triggers.append(f"monotonia {monotony:.2f}")

        if not triggers:
            continue

        alerts.append(
            _make_alert(
                category="load_risk",
                severity=severity,
                priority=priority,
                title="Riesgo de carga semanal",
                message=f"{', '.join(triggers)} en {label}.",
                athlete=athlete_name,
                source="weekly_summaries",
                action="Revisar Load Monitoring y ajustar carga aguda si corresponde.",
                scope=scope,
                surface=surface,
                key=f"load_risk:{athlete_name or 'team'}:{selected_week}:{','.join(triggers)}",
                meta={
                    "week_start": selected_week,
                    "acwr": acwr,
                    "monotony": monotony,
                    "monotony_status": monotony_status or None,
                },
            )
        )
    return alerts


def _normalize_completion_pct(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    max_value = values.dropna().max() if values.notna().any() else None
    if max_value is not None and pd.notna(max_value) and float(max_value) <= 1.5:
        values = values * 100.0
    return values


def _adherence_alerts(
    completion_df: pd.DataFrame | None,
    *,
    reference_date: pd.Timestamp,
    week_start=None,
    scope: str,
    surface: str,
    athlete: str | None = None,
) -> list[ProductAlert]:
    if completion_df is None or completion_df.empty or "Date" not in completion_df.columns:
        return []

    result = completion_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()
    result = result.dropna(subset=["Date"])
    if result.empty:
        return []

    selected_week = pd.Timestamp(week_start).normalize() if week_start is not None else _week_start_for(reference_date)
    week_end = selected_week + pd.Timedelta(days=6)
    if week_start is None:
        week_end = min(week_end, reference_date)
    window = result[result["Date"].between(selected_week, week_end)].copy()
    if window.empty:
        return []

    if athlete and athlete != "Todos" and "Athlete" in window.columns:
        window = window[window["Athlete"].astype(str).str.strip() == str(athlete).strip()]
    if window.empty:
        return []

    if "Athlete" in window.columns and window["Athlete"].notna().any():
        grouped = window.groupby(window["Athlete"].astype(str).str.strip(), dropna=True)
        rows = [(name, group) for name, group in grouped if name]
    else:
        rows = [(None, window)]

    alerts: list[ProductAlert] = []
    label = _week_label(selected_week)
    for athlete_name, group in rows:
        completion_result = calculate_completion_rate(group)
        completion = _coerce_float(completion_result.value)
        if completion is None or completion >= ADHERENCE_WARNING:
            continue
        severity = "danger" if completion < ADHERENCE_DANGER else "warning"
        priority = 78 if severity == "danger" else 64
        target = athlete_name or "equipo"
        alerts.append(
            _make_alert(
                category="adherence",
                severity=severity,
                priority=priority,
                title="Adherencia baja",
                message=f"Completion {completion:.1f}% en {label}; objetivo minimo {ADHERENCE_WARNING:.0f}%.",
                athlete=athlete_name,
                source="completion_df",
                action="Revisar completion y pendientes operativos.",
                scope=scope,
                surface=surface,
                key=f"adherence:{target}:{selected_week}",
                meta={
                    "week_start": selected_week,
                    "completion_pct": completion,
                    "calculation_method": completion_result.method,
                    "calculation_warning": completion_result.warning,
                },
            )
        )
    return alerts


def _evaluation_alerts(
    jump_df: pd.DataFrame | None,
    *,
    athletes_list: Iterable[str] | None,
    reference_date: pd.Timestamp,
    scope: str,
    surface: str,
    athlete: str | None = None,
) -> list[ProductAlert]:
    if jump_df is None or jump_df.empty or not {"Athlete", "Date"}.issubset(jump_df.columns):
        return []

    result = jump_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()
    result["Athlete"] = result["Athlete"].astype(str).str.strip()
    result = result.dropna(subset=["Date"])
    result = result[result["Athlete"].ne("")]
    if result.empty:
        return []

    if athlete and athlete != "Todos":
        target_athletes = [_ascii_text(athlete)]
    else:
        resolved = [_ascii_text(item) for item in (athletes_list or []) if _ascii_text(item)]
        target_athletes = sorted(set(resolved or result["Athlete"].dropna().astype(str).tolist()))

    alerts: list[ProductAlert] = []
    for athlete_name in target_athletes:
        athlete_hist = result[
            (result["Athlete"].astype(str).str.strip() == athlete_name)
            & (result["Date"] <= reference_date)
        ].sort_values("Date")

        if athlete_hist.empty:
            if athletes_list:
                alerts.append(
                    _make_alert(
                        category="evaluations",
                        severity="danger",
                        priority=88,
                        title="Evaluacion pendiente",
                        message="Sin evaluacion util registrada para el atleta en la ventana visible.",
                        athlete=athlete_name,
                        source="jump_df",
                        action="Programar evaluacion base antes de tomar decisiones fisicas.",
                        scope=scope,
                        surface=surface,
                        key=f"evaluations:missing:{athlete_name}",
                    )
                )
            continue

        last_date = pd.Timestamp(athlete_hist.iloc[-1]["Date"]).normalize()
        days_without = int((reference_date - last_date).days)
        if days_without > EVALUATION_DANGER_DAYS:
            severity = "danger"
            priority = 90
            title = "Evaluacion vencida"
        elif days_without >= EVALUATION_WARNING_DAYS:
            severity = "warning"
            priority = 70
            title = "Evaluacion pendiente"
        else:
            severity = ""
            priority = 0
            title = ""

        if severity:
            alerts.append(
                _make_alert(
                    category="evaluations",
                    severity=severity,
                    priority=priority,
                    title=title,
                    message=f"Ultima evaluacion hace {days_without} dias ({last_date:%d/%m/%Y}).",
                    athlete=athlete_name,
                    source="jump_df",
                    action="Actualizar toma si el perfil fisico orienta decisiones.",
                    scope=scope,
                    surface=surface,
                    key=f"evaluations:stale:{athlete_name}:{last_date}",
                    meta={"days_without": days_without, "last_date": last_date},
                )
            )

        try:
            delta_df = compute_swc_delta(athlete_hist, last_date)
        except Exception:
            delta_df = pd.DataFrame()
        if delta_df is not None and not delta_df.empty and "Signal" in delta_df.columns:
            declines = delta_df[delta_df["Signal"].astype(str).eq("caida relevante")]
            if not declines.empty:
                variables = ", ".join(declines["Label"].dropna().astype(str).unique().tolist()[:4])
                severity = "danger" if len(declines) >= 2 else "warning"
                alerts.append(
                    _make_alert(
                        category="evaluations",
                        severity=severity,
                        priority=86 if severity == "danger" else 76,
                        title="Caida relevante en evaluacion",
                        message=f"Caida relevante en {variables or 'variables fisicas'} vs evaluacion anterior.",
                        athlete=athlete_name,
                        source="compute_swc_delta",
                        action="Revisar Evaluaciones y contexto de carga previa.",
                        scope=scope,
                        surface=surface,
                        key=f"evaluations:swc_drop:{athlete_name}:{last_date}:{variables}",
                    )
                )

        try:
            baseline_df = compute_baseline_delta(athlete_hist, last_date)
        except Exception:
            baseline_df = pd.DataFrame()
        if baseline_df is None or baseline_df.empty or "Signal" not in baseline_df.columns:
            continue

        baseline_drops = baseline_df[baseline_df["Signal"].astype(str).eq("caida vs baseline")].copy()
        if not baseline_drops.empty:
            baseline_drops["abs_delta_pct"] = pd.to_numeric(
                baseline_drops.get("Delta_pct"),
                errors="coerce",
            ).abs()
            material = baseline_drops[
                baseline_drops["abs_delta_pct"].isna()
                | baseline_drops["abs_delta_pct"].ge(BASELINE_MATERIAL_DROP_PCT)
            ]
            if not material.empty:
                variables = ", ".join(material["Label"].dropna().astype(str).unique().tolist()[:4])
                alerts.append(
                    _make_alert(
                        category="evaluations",
                        severity="warning",
                        priority=74,
                        title="Caida vs baseline",
                        message=f"Caida material frente al baseline inicial en {variables or 'variables fisicas'}.",
                        athlete=athlete_name,
                        source="compute_baseline_delta",
                        action="Contrastar con fatiga reciente y planificar seguimiento.",
                        scope=scope,
                        surface=surface,
                        key=f"evaluations:baseline_drop:{athlete_name}:{last_date}:{variables}",
                    )
                )

        if baseline_df["Signal"].astype(str).eq("baseline insuficiente").all():
            n_valid = pd.to_numeric(baseline_df.get("N_valid"), errors="coerce").max()
            if pd.notna(n_valid) and int(n_valid) < 3:
                alerts.append(
                    _make_alert(
                        category="evaluations",
                        severity="info",
                        priority=32,
                        title="Baseline insuficiente",
                        message=f"Baseline canonico requiere 3 mediciones validas; hoy hay {int(n_valid)}.",
                        athlete=athlete_name,
                        source="compute_baseline_delta",
                        action="Completar mediciones antes de interpretar cambios finos.",
                        scope=scope,
                        surface=surface,
                        key=f"evaluations:baseline_insufficient:{athlete_name}:{last_date}",
                    )
                )

    return alerts


def _alert_from_dict(alert: ProductAlert | dict[str, object]) -> ProductAlert:
    if isinstance(alert, ProductAlert):
        return alert
    return _make_alert(
        category=str(alert.get("category", "data_quality")),
        severity=str(alert.get("severity", "info")),
        priority=int(alert.get("priority", 0)),
        title=str(alert.get("title", "")),
        message=str(alert.get("message", "")),
        athlete=alert.get("athlete") if alert.get("athlete") is not None else None,
        source=str(alert.get("source", "")),
        action=str(alert.get("action", "")),
        scope=str(alert.get("scope", "team")),
        surface=str(alert.get("surface", "app")),
        key=str(alert.get("key", "")) or None,
        meta=alert.get("meta") if isinstance(alert.get("meta"), dict) else {},
    )


def dedupe_alerts(alerts: Iterable[ProductAlert | dict[str, object]]) -> list[dict[str, object]]:
    best_by_key: dict[str, ProductAlert] = {}
    for raw_alert in alerts:
        alert = _alert_from_dict(raw_alert)
        existing = best_by_key.get(alert.key)
        if existing is None:
            best_by_key[alert.key] = alert
            continue
        if (alert.priority, SEVERITY_WEIGHT[alert.severity]) > (
            existing.priority,
            SEVERITY_WEIGHT[existing.severity],
        ):
            best_by_key[alert.key] = alert
    return [alert.to_dict() for alert in best_by_key.values()]


def sort_alerts(alerts: Iterable[ProductAlert | dict[str, object]]) -> list[dict[str, object]]:
    deduped = [_alert_from_dict(alert) for alert in dedupe_alerts(alerts)]
    ordered = sorted(
        deduped,
        key=lambda alert: (
            -int(alert.priority),
            -SEVERITY_WEIGHT.get(alert.severity, 0),
            alert.category,
            alert.athlete or "",
            alert.title,
        ),
    )
    return [alert.to_dict() for alert in ordered]


def select_executive_alerts(
    alerts: Iterable[ProductAlert | dict[str, object]],
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    if limit <= 0:
        return []
    return sort_alerts(alerts)[:limit]


def alert_feed_to_dataframe(alerts: Iterable[ProductAlert | dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for alert in sort_alerts(alerts):
        rows.append(
            {
                "Severidad": str(alert.get("severity", "")).upper(),
                "Prioridad": int(alert.get("priority", 0)),
                "Categoria": str(alert.get("category", "")),
                "Atleta": alert.get("athlete") or "Equipo",
                "Titulo": str(alert.get("title", "")),
                "Mensaje": str(alert.get("message", "")),
                "Accion": str(alert.get("action", "")),
                "Fuente": str(alert.get("source", "")),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["Severidad", "Prioridad", "Categoria", "Atleta", "Titulo", "Mensaje", "Accion", "Fuente"],
    )


def build_alert_feed(
    *,
    quality_report: dict[str, object] | None = None,
    weekly_summaries: dict[str, pd.DataFrame] | None = None,
    completion_df: pd.DataFrame | None = None,
    jump_df: pd.DataFrame | None = None,
    athletes_list: Iterable[str] | None = None,
    reference_date=None,
    week_start=None,
    scope: str = "team",
    surface: str = "app",
    athlete: str | None = None,
) -> list[dict[str, object]]:
    reference_ts = _coerce_reference_date(reference_date)
    alerts: list[ProductAlert] = []
    alerts.extend(_data_quality_alerts(quality_report, scope=scope, surface=surface))
    alerts.extend(
        _load_risk_alerts(
            weekly_summaries,
            reference_date=reference_ts,
            week_start=week_start,
            scope=scope,
            surface=surface,
            athlete=athlete,
        )
    )
    alerts.extend(
        _adherence_alerts(
            completion_df,
            reference_date=reference_ts,
            week_start=week_start,
            scope=scope,
            surface=surface,
            athlete=athlete,
        )
    )
    alerts.extend(
        _evaluation_alerts(
            jump_df,
            athletes_list=athletes_list,
            reference_date=reference_ts,
            scope=scope,
            surface=surface,
            athlete=athlete,
        )
    )
    return sort_alerts(alerts)
