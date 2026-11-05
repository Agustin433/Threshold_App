"""Contenido de los reportes de atleta y cliente (PDF y dashboard).

Funciones puras: reciben lo que ya calculo el resto de la app (historial de
evaluaciones preparado, tabla de cambios, contexto de carga y bienestar) y
devuelven textos y valores listos para mostrar. El PDF y el dashboard leen el
mismo payload, asi que no pueden contradecirse.

Reglas:
- "Lo que lograste" usa el mismo motor que la tabla de cambios del PDF profe
  (`compute_evaluation_changes`): solo se celebra lo que supera max(TE, SWC),
  no esta excluido y no es un cambio de altura inusual (> +20%).
- Una seccion sin datos evaluables no se muestra: se convierte en un item de
  "Proximos pasos" (maximo 2, en positivo).
- Cada frase sale del mismo dato que se muestra al lado (signo del cambio
  semanal, clasificacion de bienestar).
"""

from __future__ import annotations

import math
import re

import pandas as pd

from modules.report_messages import (
    NEXT_STEP_FIRST_COMPARISON,
    NEXT_STEP_REEVALUATE,
    NEXT_STEP_RPE,
    NEXT_STEP_WELLNESS,
    next_step_lines,
)

ATHLETE = "atleta"
CLIENT = "cliente"

ACHIEVEMENT_WINDOW_DAYS = 42
WELLNESS_MIN_DAYS = 3
MAX_EVALUATION_ACHIEVEMENTS = 5
REEVALUATION_WEEKS = (6, 8)

# variable -> (rotulo atleta, rotulo cliente, unidad, decimales, mayor_es_mejor)
ACHIEVEMENT_VARIABLES: dict[str, tuple[str, str, str, int, bool]] = {
    "CMJ_cm": ("Salto CMJ", "Salto vertical", "cm", 1, True),
    "CMJ_ft_cm": ("Salto CMJ (por tiempo de vuelo)", "Salto vertical (por tiempo de vuelo)", "cm", 1, True),
    "SJ_cm": ("Salto SJ", "Salto sin impulso previo", "cm", 1, True),
    "SJ_ft_cm": ("Salto SJ (por tiempo de vuelo)", "Salto sin impulso previo (por tiempo de vuelo)", "cm", 1, True),
    "DJ_cm": ("Altura en el drop jump", "Salto después de caer del cajón", "cm", 1, True),
    "DJ_RSI": ("Reactividad (DJ RSI)", "Reactividad", "", 2, True),
    "DJ_tc_ms": ("Tiempo de contacto en el drop jump", "Tiempo de contacto con el piso", "ms", 0, False),
    "IMTP_N": ("Fuerza máxima (IMTP)", "Fuerza máxima", "N", 0, True),
    "IMTP_relPF": ("Fuerza máxima por kg de peso", "Fuerza en relación a tu peso", "N/kg", 1, True),
}

# Referencia actual: metrica preferida y su alternativa por tiempo de vuelo.
REFERENCE_METRICS: tuple[tuple[str, ...], ...] = (
    ("CMJ_cm", "CMJ_ft_cm"),
    ("DJ_RSI",),
    ("IMTP_N",),
)

# Codigos de KPI del perfil -> columnas que tienen que existir para recomendarlo.
KPI_COLUMNS: dict[str, tuple[str, ...]] = {
    "CMJ_cm": ("CMJ_cm",),
    "SJ_cm": ("SJ_cm",),
    "EUR": ("EUR",),
    "DJ_RSI": ("DJ_RSI",),
    "DJ_tc_ms": ("DJ_tc_ms",),
    "DRI": ("DRI",),
    "IMTP_relPF": ("IMTP_relPF", "IMTP_N"),
    "IMTP_N": ("IMTP_N",),
}
KPI_LABELS = {
    "CMJ_cm": "CMJ",
    "SJ_cm": "SJ",
    "EUR": "EUR",
    "DJ_RSI": "DJ RSI",
    "DJ_tc_ms": "tiempo de contacto",
    "DRI": "DRI",
    "IMTP_relPF": "IMTP",
    "IMTP_N": "IMTP",
}

UNCLASSIFIED_CODES = {"", "UNCLASSIFIED", "NONE", "NAN"}

IMTP_GROUP = ("IMTP_N", "IMTP_relPF")
MAX_HIGHLIGHTED_VARIABLES = 2

# KPI -> columna de z para ordenar "Seguir de cerca" por relevancia.
KPI_Z_COLUMNS = {
    "CMJ_cm": "CMJ_Z",
    "SJ_cm": "SJ_Z",
    "EUR": "EUR_Z",
    "DJ_RSI": "DJ_RSI_Z",
    "DJ_tc_ms": "TC_inv_Z",
    "DRI": "DRI_Z",
    "IMTP_relPF": "IMTP_relPF_Z",
    "IMTP_N": "IMTP_N_Z",
}

# Terminos del diccionario: se incluyen solo si aparecen en el reporte.
DICTIONARY_TERMS: dict[str, str] = {
    "CMJ": "salto con contramovimiento: bajás y subís en un solo gesto.",
    "SJ": "salto desde sentadilla quieta, sin contramovimiento.",
    "DJ RSI": "reactividad en el drop jump: altura del salto dividida por el tiempo de contacto.",
    "drop jump": "salto inmediato después de caer de un cajón.",
    "IMTP": "tirón isométrico: fuerza máxima contra una barra fija.",
    "RPE": "esfuerzo percibido de la sesión, de 0 a 10.",
    "UA": "unidades arbitrarias de carga: RPE por minutos de sesión.",
    "1RM": "el máximo peso que podrías levantar una vez.",
    "por tiempo de vuelo": "altura calculada con el tiempo que estuviste en el aire; se compara solo contra otra medición del mismo tipo.",
}


def _number(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _fmt_date(value: object) -> str:
    date = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(date) else pd.Timestamp(date).strftime("%d/%m/%Y")


def _fmt_value(value: float, unit: str, digits: int) -> str:
    text = f"{value:.{digits}f}"
    return f"{text} {unit}".strip()


def _audience_key(audience: str) -> str:
    return CLIENT if str(audience).strip().lower() == CLIENT else ATHLETE


def variable_label(variable: str, audience: str) -> str:
    spec = ACHIEVEMENT_VARIABLES.get(variable)
    if spec is None:
        return variable
    return spec[1] if _audience_key(audience) == CLIENT else spec[0]


# ── Lo que lograste ───────────────────────────────────────────────────────
def evaluation_achievements(changes: pd.DataFrame | None, audience: str) -> list[dict[str, object]]:
    """Mejoras de evaluacion para mostrar al atleta/cliente.

    Solo "mejora relevante" (supera max(TE, SWC)), de variables con rotulo
    para atleta, sin cambio inusual (> +20% en altura de salto).
    """
    if changes is None or changes.empty or "Signal" not in changes.columns:
        return []

    def _is_unusual(row: pd.Series) -> bool:
        return str(row.get("Unusual")) == "True"

    # IMTP absoluta y relativa son la misma toma: si una es inusual (> +25%),
    # ninguna se celebra; si se celebra, va en una sola linea.
    imtp_rows = changes[changes["Variable"].astype(str).isin(IMTP_GROUP)]
    imtp_unusual = any(_is_unusual(row) for _, row in imtp_rows.iterrows())
    relative_rows = changes[changes["Variable"].astype(str) == "IMTP_relPF"]
    relative_row = relative_rows.iloc[0] if not relative_rows.empty else None
    absolute_improved = (
        (changes["Variable"].astype(str) == "IMTP_N") & (changes["Signal"].astype(str) == "mejora relevante")
    ).any()

    items: list[dict[str, object]] = []
    for _, row in changes.iterrows():
        variable = str(row.get("Variable"))
        spec = ACHIEVEMENT_VARIABLES.get(variable)
        if spec is None or str(row.get("Signal")) != "mejora relevante":
            continue
        if _is_unusual(row):
            continue
        if variable in IMTP_GROUP and imtp_unusual:
            continue
        if variable == "IMTP_relPF" and absolute_improved:
            continue
        current = _number(row.get("Valor_actual"))
        previous = _number(row.get("Valor_anterior"))
        if current is None or previous is None:
            continue
        _, _, unit, digits, higher_is_better = spec
        delta = current - previous
        label = variable_label(variable, audience)
        sign = "+" if delta > 0 else "−"
        delta_text = _fmt_value(abs(delta), unit, digits)
        dates = f"{_fmt_date(row.get('Fecha_anterior'))} → {_fmt_date(row.get('Fecha_actual'))}"
        extra = ""
        if variable == "IMTP_N" and relative_row is not None:
            rel_now = _number(relative_row.get("Valor_actual"))
            rel_before = _number(relative_row.get("Valor_anterior"))
            if rel_now is not None and rel_before is not None:
                extra = f"; {rel_before:.1f} → {rel_now:.1f} N/kg"
        if higher_is_better:
            text = (
                f"{label}: {_fmt_value(previous, unit, digits)} → {_fmt_value(current, unit, digits)} "
                f"({sign}{delta_text}{extra}), {dates}."
            )
        else:
            text = f"{label} más corto: {_fmt_value(previous, unit, digits)} → {_fmt_value(current, unit, digits)} ({sign}{delta_text}), {dates}."
        items.append(
            {
                "kind": "evaluation",
                "variable": variable,
                "text": text,
                "delta_pct": _number(row.get("Delta_pct")) or 0.0,
            }
        )
    items.sort(key=lambda item: abs(float(item["delta_pct"])), reverse=True)
    return items[:MAX_EVALUATION_ACHIEVEMENTS]


def unusual_changes_for_professional(changes: pd.DataFrame | None) -> list[str]:
    """Cambios inusuales (solo PDF profe): se listan con la nota de verificar."""
    if changes is None or changes.empty or "Unusual" not in changes.columns:
        return []
    rows = changes[changes["Unusual"].fillna(False).astype(bool)]
    lines = []
    for _, row in rows.iterrows():
        current = _number(row.get("Valor_actual"))
        previous = _number(row.get("Valor_anterior"))
        pct = _number(row.get("Delta_pct"))
        if current is None or previous is None or pct is None:
            continue
        from modules.jump_analysis import unusual_change_note

        note = unusual_change_note(row.get("Variable")) or ""
        lines.append(f"{row.get('Label')}: {previous:.1f} → {current:.1f} (+{pct:.1f}%) — {note}".rstrip(" —"))
    return lines


def best_mark_achievements(bests: list[dict[str, object]], audience: str) -> list[dict[str, object]]:
    items = []
    for best in bests:
        text = (
            f"Nueva mejor marca en {best['Lift']}: {float(best['Value']):.1f} kg "
            f"(antes {float(best['Previous']):.1f} kg), {_fmt_date(best['Date'])}."
        )
        items.append({"kind": "best", "text": text.replace(".0 kg", " kg")})
    return items


def completed_sessions(raw_df: pd.DataFrame | None, athlete: str, *, window_start: object, window_end: object) -> int:
    if raw_df is None or raw_df.empty or "Athlete" not in raw_df.columns:
        return 0
    date_col = next(
        (column for column in ("Fecha_sesion", "Completed Date", "Date", "Assigned Date") if column in raw_df.columns),
        None,
    )
    if date_col is None:
        return 0
    data = raw_df[raw_df["Athlete"].astype(str).str.strip().str.casefold() == str(athlete).strip().casefold()]
    dates = pd.to_datetime(data[date_col], errors="coerce").dt.normalize().dropna()
    start = pd.Timestamp(window_start).normalize()
    end = pd.Timestamp(window_end).normalize()
    return int(dates[(dates >= start) & (dates <= end)].nunique())


def sessions_achievement(count: int, audience: str) -> dict[str, object] | None:
    """Solo si promedian al menos 1 sesion por semana en la ventana."""
    weeks = ACHIEVEMENT_WINDOW_DAYS // 7
    if count <= 0 or count / weeks < 1.0:
        return None
    noun = "sesión completada" if count == 1 else "sesiones completadas"
    return {"kind": "sessions", "text": f"{count} {noun} en las últimas {weeks} semanas."}


def reference_lines(history: pd.DataFrame | None, audience: str) -> list[str]:
    """'Tu referencia actual': ultimo valor valido de cada metrica clave."""
    if history is None or history.empty or "Date" not in history.columns:
        return []
    data = history.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.sort_values("Date")
    parts: list[str] = []
    for options in REFERENCE_METRICS:
        for variable in options:
            if variable not in data.columns:
                continue
            values = pd.to_numeric(data[variable], errors="coerce")
            valid = data[values.notna()]
            if valid.empty:
                continue
            row = valid.iloc[-1]
            _, _, unit, digits, _ = ACHIEVEMENT_VARIABLES[variable]
            parts.append(
                f"{variable_label(variable, audience)} {_fmt_value(float(values[valid.index[-1]]), unit, digits)} "
                f"({_fmt_date(row['Date'])})"
            )
            break
    return parts


# ── Perfil y foco ─────────────────────────────────────────────────────────
def is_classified_profile(profile: dict[str, object] | None) -> bool:
    code = str((profile or {}).get("profile_code") or "").strip().upper()
    return code not in UNCLASSIFIED_CODES


def available_kpis(kpis: object, history: pd.DataFrame | None) -> list[str]:
    """KPIs que el atleta efectivamente tiene medidos (nunca recomendar el resto)."""
    if not isinstance(kpis, (list, tuple)) or history is None or history.empty:
        return []
    labels: list[str] = []
    for kpi in kpis:
        columns = KPI_COLUMNS.get(str(kpi), (str(kpi),))
        has_value = any(
            column in history.columns and pd.to_numeric(history[column], errors="coerce").notna().any()
            for column in columns
        )
        label = KPI_LABELS.get(str(kpi), str(kpi))
        if has_value and label not in labels:
            labels.append(label)
    return labels


def _latest_value(history: pd.DataFrame, column: str) -> float | None:
    if column not in history.columns:
        return None
    values = pd.to_numeric(history.sort_values("Date")[column], errors="coerce").dropna() if "Date" in history.columns else pd.to_numeric(history[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def top_kpis(kpis: object, history: pd.DataFrame | None, limit: int = MAX_HIGHLIGHTED_VARIABLES) -> list[str]:
    """Hasta `limit` KPIs medidos, los de mayor |z| primero."""
    if not isinstance(kpis, (list, tuple)) or history is None or history.empty:
        return []
    ranked: list[tuple[float, int, str]] = []
    seen: set[str] = set()
    for order, kpi in enumerate(kpis):
        label = KPI_LABELS.get(str(kpi), str(kpi))
        if label in seen or not available_kpis([kpi], history):
            continue
        seen.add(label)
        z_value = _latest_value(history, KPI_Z_COLUMNS.get(str(kpi), ""))
        ranked.append((-(abs(z_value) if z_value is not None else -1.0), order, label))
    ranked.sort()
    return [label for _, _, label in ranked[:limit]]


_STRENGTH_ITEM = re.compile(r"([^,(]+?)\s*\(([+-]?\d+(?:\.\d+)?)\)")


def top_strengths(feedback_high: object, limit: int = MAX_HIGHLIGHTED_VARIABLES) -> str | None:
    """'SJ (+1.63), CMJ (+1.23), DJ (+1.25)' -> 'SJ, DJ' (mayor z primero)."""
    text = str(feedback_high or "").strip().rstrip(".")
    if not text:
        return None
    items = [(float(z), name.strip()) for name, z in _STRENGTH_ITEM.findall(text)]
    if not items:
        names = [part.strip() for part in text.split(",") if part.strip()]
        return ", ".join(names[:limit]) or None
    items.sort(key=lambda item: item[0], reverse=True)
    return ", ".join(name for _, name in items[:limit])


_FOLLOW_UP_SENTENCE = re.compile(r"\s*Seguir de cerca [^.]*\.?", re.IGNORECASE)


def focus_text(profile: dict[str, object] | None, history: pd.DataFrame | None, audience: str) -> str:
    """Foco del proximo bloque (aparece una sola vez en el reporte)."""
    profile = profile or {}
    base = str(profile.get("training_priority_detailed") or profile.get("training_priority_short") or "").strip()
    base = _FOLLOW_UP_SENTENCE.sub("", base).strip()
    if _audience_key(audience) == CLIENT:
        short = str(profile.get("training_priority_short") or "").strip()
        base = short or base
        return base
    # "Seguir de cerca ..." queda solo en el PDF profe.
    return base


def profile_reading(profile: dict[str, object] | None, composite: dict[str, object] | None, audience: str) -> dict[str, str | None]:
    """Etiqueta (solo si hay un patron real) y lectura en positivo."""
    profile = profile or {}
    composite = composite or {}
    label = str(profile.get("profile_label") or "").strip() if is_classified_profile(profile) else None
    summary_key = "summary_client" if _audience_key(audience) == CLIENT else "summary_athlete"
    summary = str(profile.get(summary_key) or "").strip() if label else None
    feedback = composite.get("feedback") if isinstance(composite.get("feedback"), dict) else {}
    strengths = None
    if composite.get("has_clear_strength") and feedback.get("high"):
        # Sin los z entre parentesis y solo las 2 de mayor z.
        strengths = top_strengths(feedback.get("high"))
    return {"label": label, "summary": summary or None, "strengths": strengths}


# ── Carga ─────────────────────────────────────────────────────────────────
ZONE_SENTENCES = {
    "high": "Las últimas semanas vienen más exigentes que tu promedio: priorizamos recuperar bien entre sesiones.",
    "low": "Las últimas semanas vienen más livianas que tu promedio.",
    "ok": "Las últimas semanas están en línea con tu promedio.",
}
CLIENT_TREND_HEADLINES = {
    "Más exigente que las anteriores": "Más alta que tu promedio",
    "Más liviana que las anteriores": "Más baja que tu promedio",
    "Similar a las anteriores": "Similar a tu promedio",
}
CLIENT_TREND_SENTENCES = {
    "Más exigente que las anteriores": "La última semana completa estuvo por encima de tu promedio de las semanas previas.",
    "Más liviana que las anteriores": "La última semana completa estuvo por debajo de tu promedio de las semanas previas.",
    "Similar a las anteriores": "La última semana completa estuvo en línea con tu promedio de las semanas previas.",
}


ZONE_LABELS = {
    "precaucion": "Precaución",
    "alto riesgo": "Alto riesgo",
    "subcarga": "Subcarga",
    "optimo": "Óptimo",
    "zona util": "Zona útil",
}


def zone_label(zone: object) -> str:
    text = str(zone or "").strip()
    key = text.casefold().replace("ó", "o").replace("á", "a").replace("ú", "u")
    return ZONE_LABELS.get(key, text)


def _zone_kind(zone: object) -> str | None:
    text = str(zone or "").strip().casefold()
    text = text.replace("ó", "o").replace("á", "a")
    if not text or text in {"nan", "none", "-", "—"} or "no evaluable" in text:
        return None
    if "riesgo" in text or "precaucion" in text or "alto" in text:
        return "high"
    if "subcarga" in text or "bajo" in text:
        return "low"
    return "ok"


def weekly_change_sentence(change_pct: object, week_label: str | None) -> str | None:
    pct = _number(change_pct)
    if pct is None:
        return None
    week = f" ({week_label})" if week_label else ""
    if abs(pct) < 0.05:
        return f"La última semana completa{week} tuvo la misma carga que la anterior."
    direction = "más" if pct > 0 else "menos"
    return f"La última semana completa{week} tuvo {abs(pct):.1f}% {direction} carga que la anterior."


def load_reading(
    internal_load: dict[str, object] | None,
    *,
    evaluable: bool,
    zone: object,
    acwr: object,
    client_trend: str | None,
    audience: str,
) -> dict[str, object] | None:
    """Lectura de carga o None si no es evaluable (la seccion no se muestra)."""
    if not evaluable:
        return None
    internal_load = internal_load or {}
    sentences: list[str] = []
    headline: str | None = None
    # Atleta y cliente: etiqueta descriptiva (ultima semana completa vs tu
    # promedio de las previas). La zona del ACWR ("Precaucion") queda en el
    # PDF profe: el ACWR es contexto, no semaforo (Impellizzeri et al. 2020).
    if client_trend:
        headline = CLIENT_TREND_HEADLINES.get(client_trend, client_trend)
        sentence = CLIENT_TREND_SENTENCES.get(client_trend)
        if sentence:
            sentences.append(sentence)
    blocked = bool(internal_load.get("weekly_change_blocked"))
    week_label = str(internal_load.get("analysis_week_label") or "").replace(" - ", "–") or None
    change_pct = None if blocked else internal_load.get("weekly_change_pct")
    change_sentence = weekly_change_sentence(change_pct, week_label)
    if change_sentence:
        sentences.append(change_sentence)
    rows: list[tuple[str, str]] = []
    total = _number(internal_load.get("last_week_total"))
    sessions = _number(internal_load.get("analysis_week_sessions_with_srpe"))
    if total is not None and total > 0:
        session_text = f" ({int(sessions)} sesiones con RPE)" if sessions else ""
        rows.append((f"Última semana completa{f' ({week_label})' if week_label else ''}", f"{total:.0f} UA{session_text}"))
    pct = _number(change_pct)
    if pct is not None:
        rows.append(("Cambio vs semana anterior", f"{pct:+.1f}%"))
    # El ACWR queda en el PDF profe: "Más alta/Similar/Más baja que tu
    # promedio" ya lo comunica sin convertirlo en semaforo.
    if not sentences and not rows:
        return None
    return {"headline": headline, "sentences": sentences, "rows": rows}


# ── Bienestar ─────────────────────────────────────────────────────────────
WELLNESS_SENTENCES = {
    "Óptimo": "Tu bienestar de esa semana fue muy bueno: buena base para progresar.",
    "Aceptable": "Tu bienestar de esa semana fue aceptable; seguimos de cerca sueño, estrés y dolor.",
    "Atención": "Tu bienestar de esa semana pide atención: cuidamos sueño, estrés y dolor antes de subir la exigencia.",
    "Crítico": "Tu bienestar de esa semana está bajo: priorizamos recuperarte antes de subir la exigencia.",
}


def wellness_score_class(score: float) -> str:
    """Mismos cortes que el PDF profe (escala 0-30)."""
    if score >= 24.0:
        return "Óptimo"
    if score >= 18.0:
        return "Aceptable"
    if score >= 12.0:
        return "Atención"
    return "Crítico"


def wellness_reading(wellness_context: dict[str, object] | None) -> dict[str, object] | None:
    """Un unico valor de bienestar (ultima semana completa) con su rango, o None."""
    context = wellness_context or {}
    summary = context.get("last_week_summary") if isinstance(context.get("last_week_summary"), dict) else {}
    score = _number(summary.get("score_mean"))
    days = int(_number(summary.get("score_n")) or 0)
    if score is None or days < WELLNESS_MIN_DAYS:
        return None
    label = wellness_score_class(score)
    week_label = str(context.get("analysis_week_label") or "").replace(" - ", "–")
    rows = [(f"Bienestar ({week_label})" if week_label else "Bienestar", f"{score:.1f} /30 ({label})")]
    for key, name, unit in (("sleep_mean", "Sueño", " h"), ("stress_mean", "Estrés", "/10"), ("pain_mean", "Dolor", "/10")):
        value = _number(summary.get(key))
        if value is not None:
            rows.append((name, f"{value:.1f}{unit}"))
    rows.append(("Días con registro", str(days)))
    return {
        "score": round(score, 1),
        "label": label,
        "range": week_label,
        "sentence": WELLNESS_SENTENCES[label],
        "rows": rows,
    }


# ── Proximos pasos y fechas ───────────────────────────────────────────────
def next_steps(
    *,
    has_evaluation: bool,
    has_comparison: bool,
    evaluation_stale: bool,
    load_available: bool,
    wellness_available: bool,
    audience: str,
) -> list[str]:
    keys: list[str] = []
    if has_evaluation and not has_comparison:
        keys.append(NEXT_STEP_FIRST_COMPARISON)
    elif evaluation_stale:
        keys.append(NEXT_STEP_REEVALUATE)
    if not load_available:
        keys.append(NEXT_STEP_RPE)
    if not wellness_available:
        keys.append(NEXT_STEP_WELLNESS)
    return next_step_lines(keys, audience)


def next_evaluation_line(last_evaluation: object, today: object = None) -> str | None:
    date = pd.to_datetime(last_evaluation, errors="coerce")
    if pd.isna(date):
        return None
    start = pd.Timestamp(date) + pd.Timedelta(weeks=REEVALUATION_WEEKS[0])
    end = pd.Timestamp(date) + pd.Timedelta(weeks=REEVALUATION_WEEKS[1])
    reference = pd.to_datetime(today, errors="coerce")
    if pd.notna(reference) and pd.Timestamp(reference).normalize() > end:
        return f"Ya corresponde una nueva evaluación: la última fue el {date:%d/%m/%Y}."
    return (
        f"Próxima evaluación sugerida: entre el {start:%d/%m/%Y} y el {end:%d/%m/%Y} "
        f"({REEVALUATION_WEEKS[0]}-{REEVALUATION_WEEKS[1]} semanas después de la última, {date:%d/%m/%Y})."
    )


def latest_data_date(frames: list[tuple[pd.DataFrame | None, tuple[str, ...]]], athlete: str) -> pd.Timestamp | None:
    """Ultimo dato del atleta en cualquier fuente (para "Datos hasta")."""
    latest: pd.Timestamp | None = None
    target = str(athlete).strip().casefold()
    for frame, columns in frames:
        if frame is None or frame.empty:
            continue
        data = frame
        if "Athlete" in data.columns:
            data = data[data["Athlete"].astype(str).str.strip().str.casefold() == target]
        column = next((col for col in columns if col in data.columns), None)
        if column is None or data.empty:
            continue
        dates = pd.to_datetime(data[column], errors="coerce").dropna()
        if dates.empty:
            continue
        candidate = pd.Timestamp(dates.max()).normalize()
        if latest is None or candidate > latest:
            latest = candidate
    return latest


def dictionary_lines(text: str) -> list[str]:
    """Solo los terminos que aparecen en el texto del reporte."""
    lines = []
    for term, meaning in DICTIONARY_TERMS.items():
        if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text, flags=re.IGNORECASE):
            lines.append(f"{term}: {meaning}")
    return lines


def finite(value: object) -> bool:
    number = _number(value)
    return number is not None and math.isfinite(number)
