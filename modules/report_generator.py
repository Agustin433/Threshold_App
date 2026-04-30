"""Shared report export, summary and narrative helpers."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import textwrap
import unicodedata

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from local_store import build_weekly_summaries
from modules.data_loader import prepare_raw_workouts_df
from modules.data_quality import compute_data_quality_report
from modules.jump_analysis import _prepare_jump_df, compute_baseline_delta, compute_swc_delta
from modules.metrics import calculate_completion_rate, summarize_completion_by_group


APP_ROOT = Path(__file__).resolve().parent.parent
BRAND_ASSET_DIR = APP_ROOT / "assets" / "brand"

REPORT_SHEET_ORDER = [
    "Resumen_Ejecutivo",
    "Interpretacion",
    "Contexto_Operativo",
    "Completion_Resumen",
    "ACWR_sRPE",
    "Monotonia_Strain",
    "Wellness",
    "Evaluaciones_Saltos",
    "Maximos_Ejercicios",
    "Volumen_Carga_Externa",
    "Volumen_RepLoad_Legacy",
    "Completion_Rate",
    "Session_Notes",
    "Reporte_Meta",
]

REPORT_SHEET_EXPORT_NAMES = {
    "Resumen_Ejecutivo": "01_Resumen",
    "Interpretacion": "02_Interpretacion",
    "Contexto_Operativo": "03_Contexto_Operativo",
    "Completion_Resumen": "03_Completion_Resumen",
    "ACWR_sRPE": "04_Carga_ACWR",
    "Monotonia_Strain": "05_Carga_Monotonia",
    "Wellness": "06_Wellness",
    "Evaluaciones_Saltos": "07_Evaluaciones",
    "Maximos_Ejercicios": "08_Maximos",
    "Volumen_Carga_Externa": "09_Carga_Externa",
    "Volumen_RepLoad_Legacy": "09_RepLoad_Legacy",
    "Completion_Rate": "10_Completion_Detalle",
    "Session_Notes": "11_Session_Notes",
    "Reporte_Meta": "99_Meta",
}

DATASET_LABELS = {
    "rpe_df": "RPE + Tiempo",
    "wellness_df": "Wellness",
    "completion_df": "Completion",
    "rep_load_df": "Rep/Load (legacy opcional)",
    "raw_df": "Raw Workouts",
    "session_notes_df": "Opt-outs / Notes",
    "maxes_df": "Maxes",
    "jump_df": "Evaluaciones",
}

MODERN_REPORT_DATASET_KEYS = [
    "rpe_df",
    "wellness_df",
    "completion_df",
    "raw_df",
    "session_notes_df",
    "maxes_df",
    "jump_df",
]
LEGACY_REPORT_DATASET_KEYS = ["rep_load_df"]

REPORT_AUDIENCE_OPTIONS = {
    "Atleta": "atleta",
    "Profe": "profe",
    "Cliente": "cliente",
}

REPORT_AUDIENCE_LABELS = {value: key for key, value in REPORT_AUDIENCE_OPTIONS.items()}
EUR_RATIO_LABEL = "EUR (ratio)"
PDF_MISSING_TEXT = "Faltan datos"
PROFESSIONAL_NO_EVALUATION_TEXT = (
    "Faltan datos de evaluación para este atleta en el período seleccionado.\n"
    "Este reporte se genera con la información disponible de entrenamiento, carga interna y wellness.\n"
    "Para completar el perfil físico profesional se recomienda cargar al menos una batería de evaluación con CMJ, SJ, DJ/RSI e IMTP."
)
PROFESSIONAL_NO_EVOLUTION_TEXT = (
    "Faltan datos para mostrar evolución entre evaluaciones.\n"
    "Se necesitan al menos dos fechas de evaluación para analizar cambios del perfil físico entre bloques."
)
PROFESSIONAL_NO_QUADRANTS_TEXT = (
    "Faltan datos para construir los cuadrantes de perfil físico.\n"
    "Para generar esta sección se necesitan combinaciones mínimas como IMTP + CMJ, RSI + Contact Time, y SJ + CMJ."
)
PROFESSIONAL_PDF_METRICS = (
    {
        "title": "CMJ",
        "value_cols": ("CMJ_cm",),
        "z_cols": ("CMJ_Z",),
        "unit": "cm",
        "digits": 1,
        "higher_is_better": True,
    },
    {
        "title": "SJ",
        "value_cols": ("SJ_cm",),
        "z_cols": ("SJ_Z",),
        "unit": "cm",
        "digits": 1,
        "higher_is_better": True,
    },
    {
        "title": "DJ",
        "value_cols": ("DJ_cm",),
        "z_cols": ("DJ_height_Z",),
        "unit": "cm",
        "digits": 1,
        "higher_is_better": True,
    },
    {
        "title": "RSI",
        "value_cols": ("DJ_RSI", "DRI"),
        "z_cols": ("DJ_RSI_Z", "DRI_Z"),
        "unit": "m/s",
        "digits": 3,
        "higher_is_better": True,
    },
    {
        "title": "Contact Time",
        "value_cols": ("DJ_tc_ms",),
        "z_cols": ("TC_inv_Z", "DJtc_Z"),
        "unit": "ms",
        "digits": 0,
        "higher_is_better": False,
    },
    {
        "title": "EUR",
        "value_cols": ("EUR",),
        "z_cols": ("EUR_Z",),
        "unit": "ratio",
        "digits": 3,
        "higher_is_better": True,
    },
    {
        "title": "mRSI",
        "value_cols": ("mRSI",),
        "z_cols": ("mRSI_Z",),
        "unit": "m/s",
        "digits": 3,
        "higher_is_better": True,
    },
    {
        "title": "IMTP",
        "value_cols": ("IMTP_N", "IMTP_relPF"),
        "z_cols": ("IMTP_N_Z", "IMTP_Z", "IMTP_relPF_Z"),
        "unit": {"IMTP_N": "N", "IMTP_relPF": "N/kg"},
        "digits": {"IMTP_N": 0, "IMTP_relPF": 2},
        "higher_is_better": True,
    },
)


def normalize_report_audience(audience: str | None) -> str:
    clean = (audience or "profe").strip().lower()
    aliases = {
        "atleta": "atleta",
        "athlete": "atleta",
        "profe": "profe",
        "profesional": "profe",
        "staff": "profe",
        "coach": "profe",
        "cliente": "cliente",
        "client": "cliente",
    }
    return aliases.get(clean, "profe")


def report_audience_label(audience: str | None) -> str:
    return REPORT_AUDIENCE_LABELS.get(normalize_report_audience(audience), "Profe")


def _summary_eur_value(row: pd.Series | None) -> object:
    if row is None:
        return None
    return row.get(EUR_RATIO_LABEL, row.get("EUR"))


def collect_report_athletes(state: dict[str, pd.DataFrame | None]) -> list[str]:
    athletes: set[str] = set()
    for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "session_notes_df", "maxes_df", "jump_df"]:
        frame = state.get(key)
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        athletes.update(frame["Athlete"].dropna().astype(str).str.strip().tolist())
    return sorted(athletes)


def _has_rows(frame: pd.DataFrame | None) -> bool:
    return frame is not None and not frame.empty


def build_report_source_checklist(state: dict[str, pd.DataFrame | None]) -> list[dict[str, object]]:
    """Checklist semantico: Raw Workouts es oficial; Rep/Load solo fallback legacy."""
    raw_loaded = _has_rows(state.get("raw_df"))
    rep_load_loaded = _has_rows(state.get("rep_load_df"))
    volume_ok = raw_loaded or rep_load_loaded
    if raw_loaded:
        volume_status = "Cubierto por Raw Workouts"
        volume_detail = "Fuente oficial para carga externa y analisis por estimulo."
    elif rep_load_loaded:
        volume_status = "Fallback legacy disponible"
        volume_detail = "Rep/Load no reemplaza Raw Workouts como fuente moderna."
    else:
        volume_status = "Faltante"
        volume_detail = "Cargar Raw Data Report - Workouts."

    rows = [
        {
            "label": "RPE + Tiempo (sRPE, ACWR EWMA)",
            "ok": _has_rows(state.get("rpe_df")),
            "status": "Activo" if _has_rows(state.get("rpe_df")) else "Faltante",
            "role": "principal",
        },
        {
            "label": "Wellness 3 preguntas",
            "ok": _has_rows(state.get("wellness_df")),
            "status": "Activo" if _has_rows(state.get("wellness_df")) else "Faltante",
            "role": "principal",
        },
        {
            "label": "Completion rate",
            "ok": _has_rows(state.get("completion_df")),
            "status": "Activo" if _has_rows(state.get("completion_df")) else "Faltante",
            "role": "principal",
        },
        {
            "label": "Volumen/carga externa (Raw Workouts)",
            "ok": volume_ok,
            "status": volume_status,
            "role": "principal" if raw_loaded else "legacy_fallback" if rep_load_loaded else "principal",
            "detail": volume_detail,
        },
        {
            "label": "Maximos ejercicios",
            "ok": _has_rows(state.get("maxes_df")),
            "status": "Activo" if _has_rows(state.get("maxes_df")) else "Faltante",
            "role": "principal",
        },
        {
            "label": "Evaluaciones saltos (CMJ/SJ/DJ/IMTP)",
            "ok": _has_rows(state.get("jump_df")),
            "status": "Activo" if _has_rows(state.get("jump_df")) else "Faltante",
            "role": "principal",
        },
    ]
    rows.append(
        {
            "label": "Rep/Load (legacy opcional)",
            "ok": rep_load_loaded,
            "status": "Legacy disponible" if rep_load_loaded else "Opcional no cargado",
            "role": "legacy_optional",
            "detail": "Fuente legacy. Usar Raw Data Report - Workouts como fuente oficial para carga externa.",
        }
    )
    return rows


def report_requires_individual(audience: str | None) -> bool:
    return normalize_report_audience(audience) in {"atleta", "cliente"}


def resolve_report_scope(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> str | None:
    audience = normalize_report_audience(report_audience)
    athletes = collect_report_athletes(state)
    clean_athlete = str(report_athlete or "Todos").strip() or "Todos"

    if report_requires_individual(audience):
        if not athletes:
            return None
        if clean_athlete == "Todos":
            return athletes[0]
        return clean_athlete

    if clean_athlete == "Todos":
        return "Todos"
    return clean_athlete


def _selected_athletes(state: dict[str, pd.DataFrame | None], report_athlete: str) -> list[str]:
    athletes = collect_report_athletes(state)
    if report_athlete != "Todos":
        return [report_athlete]
    return athletes


def _latest_acwr_row(state: dict[str, pd.DataFrame | None], athlete: str) -> pd.Series | None:
    acwr_dict = state.get("acwr_dict") or {}
    acwr_df = acwr_dict.get(athlete)
    if acwr_df is None or acwr_df.empty:
        return None
    latest = acwr_df[acwr_df["sRPE_diario"] > 0].tail(1)
    if latest.empty:
        return None
    return latest.iloc[-1]


def _latest_mono_row(state: dict[str, pd.DataFrame | None], athlete: str) -> pd.Series | None:
    mono_dict = state.get("mono_dict") or {}
    mono_df = mono_dict.get(athlete)
    if mono_df is None or mono_df.empty:
        return None
    latest = mono_df.tail(1)
    if latest.empty:
        return None
    return latest.iloc[-1]


def _recent_wellness_mean(state: dict[str, pd.DataFrame | None], athlete: str) -> float | None:
    wdf = state.get("wellness_df")
    if wdf is None or wdf.empty or "Athlete" not in wdf.columns:
        return None
    athlete_df = wdf[wdf["Athlete"] == athlete].sort_values("Date").tail(3)
    if athlete_df.empty or "Wellness_Score" not in athlete_df.columns:
        return None
    return round(float(athlete_df["Wellness_Score"].mean()), 1)


def _latest_jump_row(state: dict[str, pd.DataFrame | None], athlete: str) -> pd.Series | None:
    jdf = state.get("jump_df")
    if jdf is None or jdf.empty or "Athlete" not in jdf.columns:
        return None
    athlete_df = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    if athlete_df.empty:
        return None
    return athlete_df.iloc[-1]


def _cmj_delta_vs_baseline(state: dict[str, pd.DataFrame | None], athlete: str) -> float | None:
    # Product v1 baseline: fixed per variable as the mean of the first
    # three valid measurements. Function name/column stay for report
    # compatibility, but the old full-history CMJ mean is deprecated.
    jdf = state.get("jump_df")
    if jdf is None or jdf.empty or "Athlete" not in jdf.columns or "CMJ_cm" not in jdf.columns:
        return None
    athlete_df = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    if athlete_df.empty or "Date" not in athlete_df.columns:
        return None
    latest_date = pd.to_datetime(athlete_df["Date"], errors="coerce").dropna()
    if latest_date.empty:
        return None
    baseline_df = compute_baseline_delta(athlete_df, latest_date.max(), variables=["CMJ_cm"])
    if baseline_df.empty:
        return None
    cmj_row = baseline_df.iloc[0]
    if cmj_row.get("Signal") in {"baseline insuficiente", "sin dato actual"}:
        return None
    delta_pct = pd.to_numeric(pd.Series([cmj_row.get("Delta_pct")]), errors="coerce").iloc[0]
    if pd.isna(delta_pct):
        return None
    return round(float(delta_pct), 1)


def _team_completion_mean(state: dict[str, pd.DataFrame | None]) -> float | None:
    return _completion_snapshot(state, "Todos").get("numeric")


def _athlete_completion_mean(state: dict[str, pd.DataFrame | None], athlete: str) -> float | None:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty:
        return None
    if "Athlete" in cdf.columns:
        athlete_df = cdf[cdf["Athlete"] == athlete]
        if athlete_df.empty:
            return None
    return _completion_snapshot(state, athlete).get("numeric")


def _completion_plot_df(state: dict[str, pd.DataFrame | None], athlete: str = "Todos") -> pd.DataFrame:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty or "Date" not in cdf.columns:
        return pd.DataFrame(columns=["Date", "Pct"])

    result = cdf.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.dropna(subset=["Date"])
    if result.empty:
        return pd.DataFrame(columns=["Date", "Pct"])

    if athlete != "Todos" and "Athlete" in result.columns:
        result = result[result["Athlete"].astype(str).str.strip() == athlete]
        if result.empty:
            return pd.DataFrame(columns=["Date", "Pct"])

    grouped = summarize_completion_by_group(result, "Date", value_column="Pct")
    if grouped.empty:
        return pd.DataFrame(columns=["Date", "Pct"])
    return grouped[["Date", "Pct"]].sort_values("Date").reset_index(drop=True)


def _report_weekly_summaries(state: dict[str, pd.DataFrame | None]) -> dict[str, pd.DataFrame]:
    cached = state.get("weekly_summaries")
    if isinstance(cached, dict) and {"weekly_load", "weekly_wellness", "weekly_external", "weekly_team"}.issubset(cached.keys()):
        return cached
    return build_weekly_summaries(
        state.get("rpe_df"),
        state.get("wellness_df"),
        state.get("raw_df"),
        acwr_dict=state.get("acwr_dict"),
    )


def _report_quality_report(state: dict[str, pd.DataFrame | None]) -> dict[str, object]:
    athletes = collect_report_athletes(state)
    return compute_data_quality_report(
        state.get("rpe_df"),
        state.get("wellness_df"),
        state.get("completion_df"),
        state.get("raw_df"),
        state.get("maxes_df"),
        state.get("jump_df"),
        athletes,
    )


def _normalize_weekly_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "week_start" in result.columns:
        result["week_start"] = pd.to_datetime(result["week_start"], errors="coerce")
    if "is_current_week" in result.columns:
        result["is_current_week"] = result["is_current_week"].fillna(False).astype(bool)
    return result


def _current_week_slice(frame: pd.DataFrame | None, athlete: str = "Todos") -> pd.DataFrame:
    result = _normalize_weekly_frame(frame)
    if result.empty:
        return result
    if athlete != "Todos" and "Athlete" in result.columns:
        result = result[result["Athlete"].astype(str).str.strip() == athlete]
        if result.empty:
            return result
    if "is_current_week" in result.columns:
        current = result[result["is_current_week"].fillna(False)]
        if not current.empty:
            return current.copy()
    if "week_start" in result.columns and result["week_start"].notna().any():
        latest_week = result["week_start"].dropna().max()
        return result[result["week_start"] == latest_week].copy()
    return result.tail(1).copy()


def _completion_snapshot(
    state: dict[str, pd.DataFrame | None],
    athlete: str = "Todos",
    *,
    today: pd.Timestamp | None = None,
) -> dict[str, object]:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty or "Date" not in cdf.columns:
        return {"value": "Sin dato", "detail": "Sin completion cargado.", "numeric": None, "period_label": "Sin dato"}

    result = cdf.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.dropna(subset=["Date"])
    if athlete != "Todos" and "Athlete" in result.columns:
        result = result[result["Athlete"].astype(str).str.strip() == athlete]
    if result.empty:
        detail = "Sin completion para el atleta seleccionado." if athlete != "Todos" else "Sin completion visible."
        return {"value": "Sin dato", "detail": detail, "numeric": None, "period_label": "Sin dato"}

    today_ts = (pd.Timestamp(today) if today is not None else pd.Timestamp(datetime.now())).normalize()
    current_week = today_ts - pd.Timedelta(days=today_ts.weekday())
    current = result[
        (result["Date"].dt.normalize() >= current_week)
        & (result["Date"].dt.normalize() <= today_ts)
    ].copy()
    period_label = "Semana actual"
    if current.empty:
        latest_date = result["Date"].max().normalize()
        current = result[result["Date"].dt.normalize().eq(latest_date)].copy()
        period_label = f"Ultima fecha util ({latest_date:%d/%m})"

    completion_result = calculate_completion_rate(current)
    if completion_result.value is None:
        return {"value": "Sin dato", "detail": period_label, "numeric": None, "period_label": period_label}
    completion_mean = round(float(completion_result.value), 1)
    return {
        "value": f"{completion_mean:.1f}%",
        "detail": period_label,
        "numeric": completion_mean,
        "period_label": period_label,
    }


def _readiness_payload(quality_report: dict[str, object]) -> dict[str, object]:
    """Readiness real derivado del quality report, no inventario local de archivos."""
    dataset_summary = quality_report.get("dataset_summary", pd.DataFrame())
    alerts = quality_report.get("alerts", [])
    if dataset_summary is None or dataset_summary.empty:
        return {
            "label": "Limitado",
            "detail": "Sin fuentes validas para evaluar readiness.",
            "loaded_count": 0,
            "partial_count": 0,
            "total_count": 0,
            "alerts_count": len(alerts),
        }

    statuses = dataset_summary["Estado"].fillna("").astype(str).str.lower()
    loaded_count = int(statuses.str.contains("cargado").sum())
    partial_count = int(statuses.str.contains("parcial").sum())
    total_count = int(len(dataset_summary))
    alerts_count = int(len(alerts))

    if loaded_count >= 4 and alerts_count <= 1 and partial_count <= 1:
        label = "Listo"
    elif loaded_count >= 2:
        label = "Parcial"
    else:
        label = "Limitado"

    detail = f"{loaded_count}/{total_count} fuentes listas · {partial_count} parciales · {alerts_count} alerta(s)."
    return {
        "label": label,
        "detail": detail,
        "loaded_count": loaded_count,
        "partial_count": partial_count,
        "total_count": total_count,
        "alerts_count": alerts_count,
    }


def _quality_athlete_row(quality_report: dict[str, object], athlete: str) -> pd.Series | None:
    athlete_summary = quality_report.get("athlete_summary", pd.DataFrame())
    if athlete_summary is None or athlete_summary.empty or "Atleta" not in athlete_summary.columns:
        return None
    subset = athlete_summary[athlete_summary["Atleta"].astype(str).str.strip() == athlete]
    if subset.empty:
        return None
    return subset.iloc[0]


def _cmj_series(state: dict[str, pd.DataFrame | None], athlete: str) -> list[tuple[str, float]]:
    jdf = state.get("jump_df")
    if jdf is None or jdf.empty or "Athlete" not in jdf.columns or "CMJ_cm" not in jdf.columns:
        return []
    athlete_df = (
        jdf[jdf["Athlete"] == athlete]
        .dropna(subset=["CMJ_cm"])
        .sort_values("Date")
        .tail(8)
    )
    return [
        (pd.to_datetime(row["Date"]).strftime("%d/%m"), float(row["CMJ_cm"]))
        for _, row in athlete_df.iterrows()
    ]


def _acwr_series(state: dict[str, pd.DataFrame | None], athlete: str) -> list[tuple[str, float]]:
    acwr_dict = state.get("acwr_dict") or {}
    adf = acwr_dict.get(athlete)
    if adf is None or adf.empty or "ACWR_EWMA" not in adf.columns:
        return []
    filtered = adf.dropna(subset=["ACWR_EWMA"]).tail(10)
    return [
        (pd.to_datetime(row["Date"]).strftime("%d/%m"), float(row["ACWR_EWMA"]))
        for _, row in filtered.iterrows()
    ]


def _wellness_series(state: dict[str, pd.DataFrame | None], athlete: str) -> list[tuple[str, float]]:
    wdf = state.get("wellness_df")
    if wdf is None or wdf.empty or "Athlete" not in wdf.columns or "Wellness_Score" not in wdf.columns:
        return []
    athlete_df = (
        wdf[wdf["Athlete"] == athlete]
        .dropna(subset=["Wellness_Score"])
        .sort_values("Date")
        .tail(10)
    )
    return [
        (pd.to_datetime(row["Date"]).strftime("%d/%m"), float(row["Wellness_Score"]))
        for _, row in athlete_df.iterrows()
    ]


def _round_or_none(value, digits: int = 1):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _coerce_float(value) -> float | None:
    if value in [None, "", "—", "-"]:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


def safe_value(value: object, fallback: str = PDF_MISSING_TEXT) -> str:
    """Render scalar values safely for reports without leaking NaN/None."""
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text in {"", "-", "—", "â€”", "nan", "NaN", "None", "<NA>", "NaT", "Sin dato", "sin dato"}:
        return fallback
    return text


def _professional_name_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().strip().split())


def _professional_athlete_mask(series: pd.Series, athlete: str) -> pd.Series:
    target = _professional_name_key(athlete)
    return series.apply(_professional_name_key).eq(target)


def _has_text(value: object) -> bool:
    return _ascii_text(value).strip() not in {"", "-", "—"}


def _row_has_eval_data(row: pd.Series | None) -> bool:
    if row is None:
        return False
    numeric_cols = ["CMJ cm", "CMJ vs BL %", EUR_RATIO_LABEL, "EUR", "DRI", "IMTP N"]
    return any(_coerce_float(row.get(col)) is not None for col in numeric_cols) or _has_text(row.get("Perfil NM"))


def _row_has_load_data(row: pd.Series | None) -> bool:
    if row is None:
        return False
    return any(
        [
            _coerce_float(row.get("ACWR EWMA")) is not None,
            _coerce_float(row.get("Monotonia")) is not None,
            _has_text(row.get("Zona")),
        ]
    )


def _row_has_wellness_data(row: pd.Series | None) -> bool:
    return row is not None and _coerce_float(row.get("Wellness 3d")) is not None


def _focus_completion_value(state: dict[str, pd.DataFrame | None], report_athlete: str) -> float | None:
    return (
        _athlete_completion_mean(state, report_athlete)
        if report_athlete != "Todos" else
        _team_completion_mean(state)
    )


def _profile_text(row: pd.Series, fallback: str = "-") -> str:
    text = _ascii_text(row.get("Perfil NM")).strip()
    return text or fallback


def _compact_lines(items: list[str | None]) -> list[str]:
    return [item for item in items if item and _ascii_text(item).strip()]


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    label = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {label}"


def _current_focus_text(row: pd.Series, *, audience: str) -> str:
    profile = _ascii_text(row.get("Perfil NM")).lower().strip()
    acwr = _coerce_float(row.get("ACWR EWMA"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
    eval_available = _row_has_eval_data(row)

    if not eval_available:
        return "Hacer nueva evaluación" if audience == "cliente" else "Nueva evaluación"
    if "poca base" in profile:
        return "Construir fuerza base" if audience == "cliente" else "Fuerza base"
    if cmj_delta is not None and cmj_delta <= -5:
        return "Recuperar potencia" if audience == "cliente" else "Recuperar CMJ"
    if acwr is not None and acwr > 1.5:
        return "Ordenar carga" if audience == "cliente" else "Regular carga"
    if acwr is not None and acwr < 0.8:
        return "Ganar continuidad" if audience == "cliente" else "Subir estimulo"
    return "Sostener progreso" if audience == "cliente" else "Sostener perfil"


def _objective_focuses_from_row(row: pd.Series, *, audience: str) -> list[str]:
    focus = _current_focus_text(row, audience=audience)
    profile = _ascii_text(row.get("Perfil NM")).lower().strip()
    acwr = _coerce_float(row.get("ACWR EWMA"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
    eval_available = _row_has_eval_data(row)

    if not eval_available:
        return [
            "Necesitamos una referencia objetiva para ordenar mejor el siguiente bloque.",
            "La próxima evaluación va a permitir medir cambios reales y ajustar el plan.",
        ]
    if "poca base" in profile:
        return [
            "Esta prioridad busca mejorar la base de fuerza que sostiene el resto del perfil.",
            "Si responde bien, después va a tener más sentido pedir reactividad o velocidad.",
        ]
    if cmj_delta is not None and cmj_delta <= -5:
        return [
            "La prioridad es recuperar calidad de expresión antes de volver a escalar el trabajo.",
            "El próximo control debería mostrar una mejor respuesta de salto y disponibilidad.",
        ]
    if acwr is not None and acwr > 1.5:
        return [
            "El foco inmediato es bajar ruido y recuperar tolerancia para volver a producir bien.",
            "Si la carga se ordena, las próximas semanas deberían mostrar mejor disponibilidad.",
        ]
    if acwr is not None and acwr < 0.8:
        return [
            "La prioridad es recuperar continuidad de estímulo sin perder control del proceso.",
            "El próximo tramo debería dar una señal más clara sobre la adaptación real.",
        ]
    return [
        f"El foco inmediato es {focus.lower()} sin perder calidad en el resto de las variables.",
        "La próxima revisión debería confirmar si esta prioridad ya se está trasladando al rendimiento.",
    ]


def _technical_planning_focuses(row: pd.Series, completion_value: float | None) -> list[str]:
    focuses: list[str] = []
    profile = _ascii_text(row.get("Perfil NM")).lower().strip()
    acwr = _coerce_float(row.get("ACWR EWMA"))
    monotony = _coerce_float(row.get("Monotonia"))
    wellness = _coerce_float(row.get("Wellness 3d"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))

    if "poca base" in profile:
        focuses.append("Priorizar fuerza base y fuerza máxima antes de aumentar la densidad reactiva.")
    if cmj_delta is not None and cmj_delta <= -5:
        focuses.append("Controlar fatiga reciente y repetir control corto de CMJ antes de progresar volumen reactivo.")
    elif cmj_delta is not None and cmj_delta >= 5:
        focuses.append("La salida vertical acompaña; se puede sostener o transferir sin abrir demasiados frentes.")
    if acwr is not None and acwr > 1.5:
        focuses.append("Reducir densidad o exposición del próximo microciclo para salir de zona alta.")
    elif acwr is not None and acwr < 0.8:
        focuses.append("Subir continuidad de estímulo para salir de subcarga y ganar lectura más estable.")
    if monotony is not None and monotony > 2.0:
        focuses.append("Aumentar variabilidad semanal para bajar monotonía antes de seguir acumulando strain.")
    if wellness is not None and wellness < 15:
        focuses.append("Seguir recuperación diaria y cruzar wellness con adherencia para evitar falsas lecturas.")
    if completion_value is not None and completion_value < 70:
        focuses.append("La adherencia actual limita la interpretación del bloque; conviene intervenir primero sobre cumplimiento.")
    if not focuses:
        focuses.append("Sostener el bloque actual y recontrolar en la próxima ventana para confirmar tendencia.")
    focuses.append("En la próxima medición, volver a controlar CMJ, perfil neuromuscular y disponibilidad general.")
    return list(dict.fromkeys(focuses))[:4]


def build_executive_summary_df(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str | None = None,
) -> pd.DataFrame:
    effective_athlete = (
        resolve_report_scope(state, report_athlete, report_audience)
        if report_audience is not None else
        report_athlete
    )
    if effective_athlete is None:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    athletes = _selected_athletes(state, effective_athlete)

    for athlete in athletes:
        load_row = _latest_acwr_row(state, athlete)
        mono_row = _latest_mono_row(state, athlete)
        jump_row = _latest_jump_row(state, athlete)

        row = {"Atleta": athlete}
        if load_row is not None:
            row["Fecha carga"] = pd.to_datetime(load_row["Date"]).strftime("%d/%m/%Y")
            row["sRPE"] = _round_or_none(load_row.get("sRPE_diario"), 0)
            row["ACWR EWMA"] = _round_or_none(load_row.get("ACWR_EWMA"), 2)
            row["Zona"] = load_row.get("Zona")
        if mono_row is not None:
            row["Monotonia"] = _round_or_none(mono_row.get("Monotonia"), 2)
            row["Strain"] = _round_or_none(mono_row.get("Strain"), 0)

        row["Wellness 3d"] = _recent_wellness_mean(state, athlete)

        if jump_row is not None:
            row["Fecha evaluación"] = pd.to_datetime(jump_row["Date"]).strftime("%d/%m/%Y")
            row["CMJ cm"] = _round_or_none(jump_row.get("CMJ_cm"), 1)
            row["CMJ vs BL %"] = _cmj_delta_vs_baseline(state, athlete)
            row[EUR_RATIO_LABEL] = _round_or_none(jump_row.get("EUR"), 3)
            row["DRI"] = _round_or_none(jump_row.get("DRI"), 3)
            row["IMTP N"] = _round_or_none(jump_row.get("IMTP_N"), 0)
            row["Perfil NM"] = jump_row.get("NM_Profile")

        rows.append(row)

    if not rows:
        completion_mean = _team_completion_mean(state)
        if completion_mean is None:
            return pd.DataFrame()
        return pd.DataFrame([{"Atleta": "Equipo", "Completion promedio": completion_mean}])

    summary_df = pd.DataFrame(rows)
    completion_mean = _team_completion_mean(state)
    if completion_mean is not None:
        summary_df["Completion equipo %"] = completion_mean
    
    # Convert all columns to string type to ensure Arrow serialization compatibility
    # This avoids mixing numeric and string types which causes Arrow errors
    for col in summary_df.columns:
        summary_df[col] = summary_df[col].apply(
            lambda x: "—" if pd.isna(x) or x is None else str(x) if not isinstance(x, str) else x
        )
    
    return summary_df


def _quality_detail_text(athlete_quality: pd.Series | None) -> str | None:
    if athlete_quality is None:
        return None
    srpe_cov = _coerce_float(athlete_quality.get("% cobertura sRPE"))
    wellness_cov = _coerce_float(athlete_quality.get("% cobertura Wellness"))
    parts = _compact_lines(
        [
            f"sRPE {_display_metric(srpe_cov, digits=0, suffix='%')}" if srpe_cov is not None else None,
            f"Wellness {_display_metric(wellness_cov, digits=0, suffix='%')}" if wellness_cov is not None else None,
        ]
    )
    return " | ".join(parts) if parts else None


def _latest_eval_summary(summary_df: pd.DataFrame) -> tuple[str, str]:
    if summary_df.empty or "Fecha evaluación" not in summary_df.columns:
        return "Pendiente", "Sin evaluación útil dentro de la ventana visible."

    eval_rows = summary_df[summary_df["Fecha evaluación"].apply(_has_text)].copy()
    if eval_rows.empty:
        return "Pendiente", "Sin evaluación útil dentro de la ventana visible."

    eval_rows["_eval_date"] = pd.to_datetime(eval_rows["Fecha evaluación"], format="%d/%m/%Y", errors="coerce")
    eval_rows = eval_rows.dropna(subset=["_eval_date"])
    if eval_rows.empty:
        return "Pendiente", "Sin evaluación útil dentro de la ventana visible."

    latest_eval = eval_rows["_eval_date"].max()
    profiles = eval_rows["Perfil NM"].fillna("-").astype(str)
    profile_counts = profiles[profiles.apply(_has_text)].value_counts()
    profile_text = ", ".join(f"{name}: {count}" for name, count in profile_counts.head(2).items())
    detail_parts = [
        f"{len(eval_rows)} atleta(s) con evaluación visible" if "Atleta" in eval_rows.columns else None,
        profile_text if profile_text else None,
    ]
    return latest_eval.strftime("%d/%m/%Y"), " | ".join(part for part in detail_parts if part)


def _session_notes_source(state: dict[str, pd.DataFrame | None]) -> pd.DataFrame:
    df = state.get("session_notes_df")
    if df is None or df.empty or "Date" not in df.columns or "Athlete" not in df.columns:
        return pd.DataFrame()

    result = df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()
    if "Date_Assigned" in result.columns:
        result["Date_Assigned"] = pd.to_datetime(result["Date_Assigned"], errors="coerce").dt.normalize()
    result["Athlete"] = result["Athlete"].astype(str).str.strip().str.title()
    return result.dropna(subset=["Date", "Athlete"])


def _session_notes_for_scope(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    *,
    days: int | None = 42,
    max_rows: int | None = 6,
) -> pd.DataFrame:
    df = _session_notes_source(state)
    if df.empty:
        return df

    if report_athlete != "Todos":
        target = str(report_athlete).strip().casefold()
        df = df[df["Athlete"].astype(str).str.strip().str.casefold() == target]
        if df.empty:
            return df

    if days is not None and "Date" in df.columns:
        reference_date = pd.to_datetime(df["Date"], errors="coerce").max()
        if pd.notna(reference_date):
            window_start = pd.Timestamp(reference_date).normalize() - pd.Timedelta(days=max(days - 1, 0))
            df = df[df["Date"] >= window_start]

    sort_cols = [column for column in ["Date", "Athlete", "Source_Page"] if column in df.columns]
    ascending = [False, True, True][: len(sort_cols)]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending, na_position="last")
    if max_rows is not None:
        df = df.head(max_rows)
    return df.reset_index(drop=True)


def _note_text(value: object, fallback: str = "-") -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _note_date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else "-"


def _session_note_summary(notes_df: pd.DataFrame) -> str:
    if notes_df.empty:
        return "Sin incidencias operativas recientes cargadas."
    categories = notes_df.get("Reason_Category", pd.Series(dtype=object)).dropna().astype(str)
    category_text = ", ".join(f"{name}: {count}" for name, count in categories.value_counts().head(2).items())
    latest = notes_df.iloc[0]
    latest_text = _compact_lines(
        [
            _note_text(latest.get("Opt_Out_Type")) if _has_text(latest.get("Opt_Out_Type")) else None,
            _note_text(latest.get("Assigned_Exercise")) if _has_text(latest.get("Assigned_Exercise")) else None,
        ]
    )
    return " | ".join(
        part for part in [
            f"{len(notes_df)} incidencia(s) recientes",
            category_text or None,
            f"Ultima: {', '.join(latest_text)}" if latest_text else None,
        ]
        if part
    )


def build_operational_context_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    *,
    max_rows: int = 6,
) -> pd.DataFrame:
    notes_df = _session_notes_for_scope(state, report_athlete, days=42, max_rows=max_rows)
    if notes_df.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for _, note in notes_df.iterrows():
        rows.append(
            {
                "Fecha": _note_date_text(note.get("Date")),
                "Atleta": _note_text(note.get("Athlete")),
                "Ejercicio asignado": _note_text(note.get("Assigned_Exercise")),
                "Tipo": _note_text(note.get("Opt_Out_Type")),
                "Categoria": _note_text(note.get("Reason_Category")),
                "Reemplazo": _note_text(note.get("Replacement_Exercise")),
                "Explicacion": _note_text(note.get("Explanation_Text")),
            }
        )
    return pd.DataFrame(rows)


def _build_session_notes_annex_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
) -> pd.DataFrame:
    notes_df = _session_notes_for_scope(state, report_athlete, days=None, max_rows=None)
    if notes_df.empty:
        return pd.DataFrame()
    ordered_columns = [
        "Date",
        "Athlete",
        "Date_Assigned",
        "Assigned_Exercise",
        "Opt_Out_Type",
        "Reason_Category",
        "Replacement_Exercise",
        "Explanation_Text",
        "Source",
        "Source_Page",
        "Raw_Text",
    ]
    return _preferred_columns(notes_df, ordered_columns)


def _build_raw_external_volume_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
) -> pd.DataFrame:
    prepared = prepare_raw_workouts_df(state.get("raw_df"))
    if prepared is None or prepared.empty:
        return pd.DataFrame()

    result = prepared.copy()
    if report_athlete != "Todos" and "Athlete" in result.columns:
        result = result[result["Athlete"].astype(str).str.strip() == report_athlete]
    if result.empty:
        return pd.DataFrame()

    result = result[
        ~result.get("is_invalid", pd.Series(False, index=result.index)).fillna(False)
        & ~result.get("is_untagged", pd.Series(False, index=result.index)).fillna(False)
    ].copy()
    if result.empty:
        return pd.DataFrame()

    if "Assigned Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Assigned Date"], errors="coerce")
    elif "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Source"] = "Raw Workouts"
    columns = [
        "Source",
        "Athlete",
        "Date",
        "Exercise",
        "Exercise Name",
        "Tags",
        "stimulus_category",
        "Category",
        "Result",
        "Reps",
        "Sets",
        "Volume_Load_kg",
        "Contacts",
        "Exposures",
        "Distance_m",
    ]
    available = [column for column in columns if column in result.columns]
    result = result[available].copy()
    sort_cols = [column for column in ["Athlete", "Date", "stimulus_category", "Exercise"] if column in result.columns]
    if sort_cols:
        result = result.sort_values(sort_cols, ascending=[True, False, True, True][: len(sort_cols)], na_position="last")
    return result.reset_index(drop=True)


def _build_rep_load_legacy_volume_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
) -> pd.DataFrame:
    df = state.get("rep_load_df")
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    if report_athlete != "Todos" and "Athlete" in result.columns:
        result = result[result["Athlete"].astype(str).str.strip() == report_athlete]
    if result.empty:
        return pd.DataFrame()
    result["Source"] = "Rep/Load legacy"
    return result.reset_index(drop=True)


def build_report_executive_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> pd.DataFrame:
    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return pd.DataFrame()

    summary_df = build_executive_summary_df(state, effective_athlete, audience)
    quality_report = _report_quality_report(state)
    readiness = _readiness_payload(quality_report)
    alerts = quality_report.get("alerts", [])
    weekly_summaries = _report_weekly_summaries(state)
    completion_snapshot = _completion_snapshot(state, effective_athlete)

    rows: list[dict[str, object]] = []

    def add_row(block: str, indicator: str, value: object, detail: str) -> None:
        rows.append(
            {
                "Bloque": block,
                "Indicador": indicator,
                "Valor": value,
                "Detalle": detail,
            }
        )

    scope_label = effective_athlete if effective_athlete != "Todos" else "Equipo"
    add_row(
        "Alcance",
        "Reporte",
        scope_label,
        f"{report_audience_label(audience)} {'individual' if effective_athlete != 'Todos' else 'equipo'}".strip(),
    )
    add_row("Readiness", "Estado del sistema", readiness["label"], readiness["detail"])

    if effective_athlete == "Todos":
        current_team = _current_week_slice(weekly_summaries.get("weekly_team"))
        current_load = _current_week_slice(weekly_summaries.get("weekly_load"))
        team_row = current_team.tail(1).iloc[0] if not current_team.empty else pd.Series(dtype=object)
        risk_count = 0
        if not current_load.empty and "ACWR_EWMA_last" in current_load.columns:
            risk_series = pd.to_numeric(current_load["ACWR_EWMA_last"], errors="coerce")
            risk_count = int(risk_series.gt(1.3).sum())

        week_label = "Semana actual"
        athletes_active = _display_metric(team_row.get("athletes_active"), digits=0)
        load_value = _display_metric(team_row.get("team_sRPE_sum"), digits=0)
        load_detail = " | ".join(
            part for part in [
                f"{athletes_active} atleta(s) activos" if athletes_active != "Sin dato" else None,
                f"Monotonía media {_display_metric(team_row.get('team_monotony_mean'), digits=2)}" if _coerce_float(team_row.get("team_monotony_mean")) is not None else None,
                f"{risk_count} en precaución/riesgo" if risk_count > 0 else None,
            ]
            if part
        ) or "Sin lectura semanal consolidada."
        add_row("Semana actual", "Carga del equipo", load_value, f"{week_label} | {load_detail}")

        wellness_value = _display_metric(team_row.get("team_wellness_mean"), digits=1)
        strain_detail = _compact_lines(
            [
                completion_snapshot["detail"] if completion_snapshot["numeric"] is not None else None,
                f"Strain medio {_display_metric(team_row.get('team_strain_mean'), digits=0)}" if _coerce_float(team_row.get("team_strain_mean")) is not None else None,
            ]
        )
        add_row("Semana actual", "Wellness promedio", wellness_value, " | ".join(strain_detail) or "Sin wellness consolidado.")

        add_row("Adherencia", "Completion equipo", completion_snapshot["value"], completion_snapshot["detail"])
        eval_value, eval_detail = _latest_eval_summary(summary_df)
        add_row("Evaluación útil", "Última evaluación visible", eval_value, eval_detail)
    else:
        current_load = _current_week_slice(weekly_summaries.get("weekly_load"), effective_athlete)
        current_wellness = _current_week_slice(weekly_summaries.get("weekly_wellness"), effective_athlete)
        load_row = current_load.tail(1).iloc[0] if not current_load.empty else pd.Series(dtype=object)
        wellness_row = current_wellness.tail(1).iloc[0] if not current_wellness.empty else pd.Series(dtype=object)
        athlete_quality = _quality_athlete_row(quality_report, effective_athlete)
        quality_detail = _quality_detail_text(athlete_quality)
        if athlete_quality is not None:
            add_row(
                "Readiness",
                "Cobertura del atleta",
                athlete_quality.get("Semaforo", "Sin dato"),
                quality_detail or "Sin cobertura reciente para resumir.",
            )

        weekly_value = _display_metric(load_row.get("weekly_sRPE"), digits=0)
        weekly_detail = " | ".join(
            part for part in [
                f"{_display_metric(load_row.get('sessions_count'), digits=0)} sesión(es)" if _coerce_float(load_row.get("sessions_count")) is not None else None,
                f"ACWR EWMA {_display_metric(load_row.get('ACWR_EWMA_last'), digits=2)}" if _coerce_float(load_row.get("ACWR_EWMA_last")) is not None else None,
                f"Monotonía {_display_metric(load_row.get('monotony'), digits=2)}" if _coerce_float(load_row.get("monotony")) is not None else None,
            ]
            if part
        ) or "Sin carga semanal útil para el atleta."
        add_row("Semana actual", "Carga semanal", weekly_value, f"Semana actual | {weekly_detail}")

        wellness_value = _display_metric(wellness_row.get("Wellness_mean"), digits=1)
        wellness_detail = " | ".join(
            part for part in [
                f"{_display_metric(wellness_row.get('wellness_days'), digits=0)} registro(s)" if _coerce_float(wellness_row.get("wellness_days")) is not None else None,
                f"Cumplimiento {_display_metric(_coerce_float(wellness_row.get('wellness_compliance')) * 100, digits=0, suffix='%')}" if _coerce_float(wellness_row.get("wellness_compliance")) is not None else None,
            ]
            if part
        ) or "Sin wellness útil para la semana actual."
        add_row("Semana actual", "Wellness promedio", wellness_value, wellness_detail)

        add_row("Adherencia", "Completion", completion_snapshot["value"], completion_snapshot["detail"])

        focus_row = summary_df.iloc[0] if not summary_df.empty else pd.Series(dtype=object)
        eval_value = focus_row.get("Fecha evaluación", "Pendiente")
        eval_detail = " | ".join(
            part for part in [
                f"CMJ {_display_metric(focus_row.get('CMJ cm'), digits=1, suffix=' cm')}" if _coerce_float(focus_row.get("CMJ cm")) is not None else None,
                f"CMJ vs BL {_display_metric(focus_row.get('CMJ vs BL %'), digits=1, suffix='%')}" if _coerce_float(focus_row.get("CMJ vs BL %")) is not None else None,
                f"Perfil {_profile_text(focus_row)}" if _has_text(focus_row.get("Perfil NM")) else None,
            ]
            if part
        ) or "Sin evaluación útil dentro de la ventana visible."
        add_row("Evaluación útil", "Último test", eval_value, eval_detail)

    operational_notes = _session_notes_for_scope(state, effective_athlete, days=42, max_rows=3)
    if not operational_notes.empty:
        add_row(
            "Contexto operativo",
            "Opt-outs / notes recientes",
            str(len(operational_notes)),
            _session_note_summary(operational_notes),
        )

    top_alert = _ascii_text(alerts[0]) if alerts else "Sin alertas activas en la ventana visible."
    add_row("Calidad", "Alertas activas", str(len(alerts)), top_alert)

    return pd.DataFrame(rows, columns=["Bloque", "Indicador", "Valor", "Detalle"])


def build_interpretation_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> pd.DataFrame:
    insights = generate_module_insights(state, report_athlete, report_audience)
    rows = []
    for module_name, payload in insights.items():
        rows.append(
            {
                "Modulo": module_name.title(),
                "Lectura": payload.get("summary", ""),
                "Próximos focos": " | ".join(payload.get("focuses", [])),
            }
        )
    return pd.DataFrame(rows)


def _build_report_metadata_df(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    report_audience: str,
    included_sections: list[str],
    *,
    include_technical_annex: bool = False,
) -> pd.DataFrame:
    active_datasets = [
        DATASET_LABELS.get(key, key)
        for key in MODERN_REPORT_DATASET_KEYS
        if state.get(key) is not None and not state.get(key).empty
    ]
    legacy_datasets = [
        DATASET_LABELS.get(key, key)
        for key in LEGACY_REPORT_DATASET_KEYS
        if state.get(key) is not None and not state.get(key).empty
    ]
    visible_athletes = collect_report_athletes(state)
    return pd.DataFrame(
        [
            {"Campo": "Reporte", "Valor": "Threshold S&C - Reporte de rendimiento"},
            {"Campo": "Alcance", "Valor": report_athlete},
            {"Campo": "Destinatario", "Valor": report_audience_label(report_audience)},
            {"Campo": "Modo exportacion", "Valor": "Curado + anexo tecnico" if include_technical_annex else "Curado"},
            {"Campo": "Generado", "Valor": datetime.now().strftime("%d/%m/%Y %H:%M")},
            {"Campo": "Ventana operativa", "Valor": "Últimas 6 semanas visibles"},
            {"Campo": "Atletas visibles", "Valor": len(visible_athletes)},
            {"Campo": "Fuentes modernas activas", "Valor": ", ".join(active_datasets) if active_datasets else "Sin fuentes modernas activas"},
            {"Campo": "Fuentes legacy opcionales", "Valor": ", ".join(legacy_datasets) if legacy_datasets else "Sin fuentes legacy"},
            {"Campo": "Secciones incluidas", "Valor": ", ".join(included_sections) if included_sections else "Sin secciones"},
        ]
    )


def build_report_sheets(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
    *,
    include_technical_annex: bool = False,
    include_acwr: bool = True,
    include_mono: bool = True,
    include_wellness: bool = True,
    include_jumps: bool = True,
    include_maxes: bool = True,
    include_volume: bool = True,
    include_completion: bool = True,
) -> dict[str, pd.DataFrame]:
    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return {}

    include_technical_annex = bool(include_technical_annex and audience == "profe")
    sheets: dict[str, pd.DataFrame] = {}
    included_sections: list[str] = []

    executive_df = build_report_executive_sheet(state, effective_athlete, audience)
    if not executive_df.empty:
        sheets["Resumen_Ejecutivo"] = executive_df
        included_sections.append("Resumen ejecutivo")

    interpretation_df = build_interpretation_sheet(state, effective_athlete, audience)
    if not interpretation_df.empty:
        sheets["Interpretacion"] = interpretation_df
        included_sections.append("Interpretacion")

    operational_context_df = build_operational_context_sheet(state, effective_athlete, max_rows=6)
    if not operational_context_df.empty:
        sheets["Contexto_Operativo"] = operational_context_df
        included_sections.append("Contexto operativo")

    if state.get("completion_df") is not None:
        completion_df = state["completion_df"]
        if effective_athlete != "Todos" and "Athlete" in completion_df.columns:
            completion_df = completion_df[completion_df["Athlete"].astype(str).str.strip() == effective_athlete]
        summary_df = _build_completion_summary_sheet(completion_df, effective_athlete)
        if not summary_df.empty:
            sheets["Completion_Resumen"] = summary_df
            included_sections.append("Completion resumen")

    if include_technical_annex:
        acwr_dict = state.get("acwr_dict") or {}
        mono_dict = state.get("mono_dict") or {}

        if include_acwr and acwr_dict:
            acwr_rows = []
            for athlete, athlete_df in acwr_dict.items():
                if effective_athlete != "Todos" and athlete != effective_athlete:
                    continue
                tmp = athlete_df.copy()
                tmp["Athlete"] = athlete
                acwr_rows.append(tmp)
            if acwr_rows:
                sheets["ACWR_sRPE"] = pd.concat(acwr_rows, ignore_index=True).round(2)
                included_sections.append("ACWR EWMA + sRPE")

        if include_mono and mono_dict:
            mono_rows = []
            for athlete, athlete_df in mono_dict.items():
                if effective_athlete != "Todos" and athlete != effective_athlete:
                    continue
                tmp = athlete_df.copy()
                tmp["Athlete"] = athlete
                mono_rows.append(tmp)
            if mono_rows:
                sheets["Monotonia_Strain"] = pd.concat(mono_rows, ignore_index=True).round(2)
                included_sections.append("Monotonia + Strain")

        if include_wellness and state.get("wellness_df") is not None:
            df = state["wellness_df"]
            if effective_athlete != "Todos" and "Athlete" in df.columns:
                df = df[df["Athlete"].astype(str).str.strip() == effective_athlete]
            sheets["Wellness"] = df.round(2)
            if not df.empty:
                included_sections.append("Wellness")

        if include_jumps and state.get("jump_df") is not None:
            df = state["jump_df"]
            if effective_athlete != "Todos" and "Athlete" in df.columns:
                df = df[df["Athlete"].astype(str).str.strip() == effective_athlete]
            sheets["Evaluaciones_Saltos"] = df.round(2)
            if not df.empty:
                included_sections.append("Evaluaciones")

        if include_maxes and state.get("maxes_df") is not None:
            df = state["maxes_df"]
            if effective_athlete != "Todos" and "Athlete" in df.columns:
                df = df[df["Athlete"].astype(str).str.strip() == effective_athlete]
            sheets["Maximos_Ejercicios"] = df
            if not df.empty:
                included_sections.append("Maximos")

        if include_volume:
            raw_volume_df = _build_raw_external_volume_sheet(state, effective_athlete)
            if not raw_volume_df.empty:
                sheets["Volumen_Carga_Externa"] = raw_volume_df
                included_sections.append("Carga externa Raw Workouts")
            else:
                legacy_volume_df = _build_rep_load_legacy_volume_sheet(state, effective_athlete)
                if not legacy_volume_df.empty:
                    sheets["Volumen_RepLoad_Legacy"] = legacy_volume_df
                    included_sections.append("Volumen Rep/Load legacy")

        if include_completion and state.get("completion_df") is not None:
            df = state["completion_df"]
            if effective_athlete != "Todos" and "Athlete" in df.columns:
                df = df[df["Athlete"].astype(str).str.strip() == effective_athlete]
            if not df.empty:
                sheets["Completion_Rate"] = df
                included_sections.append("Completion detalle")

        session_notes_annex_df = _build_session_notes_annex_sheet(state, effective_athlete)
        if not session_notes_annex_df.empty:
            sheets["Session_Notes"] = session_notes_annex_df
            included_sections.append("Opt-outs / Notes detalle")

    if sheets:
        sheets["Reporte_Meta"] = _build_report_metadata_df(
            state,
            effective_athlete,
            audience,
            included_sections,
            include_technical_annex=include_technical_annex,
        )

    return {name: df for name, df in sheets.items() if df is not None and not df.empty}


def _ordered_sheet_items(data_dict: dict[str, pd.DataFrame]) -> list[tuple[str, pd.DataFrame]]:
    ordered_names = [name for name in REPORT_SHEET_ORDER if name in data_dict]
    ordered_names.extend(name for name in data_dict if name not in ordered_names)
    return [(name, data_dict[name]) for name in ordered_names]


def _preferred_columns(df: pd.DataFrame, ordered_columns: list[str]) -> pd.DataFrame:
    selected = [column for column in ordered_columns if column in df.columns]
    selected.extend(column for column in df.columns if column not in selected)
    return df[selected]


def _normalize_date_like_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for column in result.columns:
        col_text = str(column).lower()
        if "date" in col_text or "fecha" in col_text or "semana" in col_text:
            parsed = pd.to_datetime(result[column], errors="coerce")
            if parsed.notna().any():
                result[column] = parsed
    return result


def _sort_export_frame(df: pd.DataFrame, sort_columns: list[str], ascending: list[bool]) -> pd.DataFrame:
    valid_columns = [column for column in sort_columns if column in df.columns]
    if not valid_columns:
        return df.reset_index(drop=True)
    valid_ascending = ascending[: len(valid_columns)]
    return df.sort_values(valid_columns, ascending=valid_ascending, na_position="last").reset_index(drop=True)


def _build_completion_summary_sheet(df: pd.DataFrame | None, report_athlete: str) -> pd.DataFrame:
    if df is None or df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    result = df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.dropna(subset=["Date"])
    if result.empty:
        return pd.DataFrame()

    scope_label = report_athlete if report_athlete != "Todos" else "Equipo"
    grouped = summarize_completion_by_group(result, "Date", value_column="Pct_Promedio")
    if grouped.empty:
        return pd.DataFrame()
    session_counts = result.groupby("Date").size().reset_index(name="Sesiones")
    grouped = grouped.merge(session_counts, on="Date", how="left")
    grouped = grouped.sort_values("Date", ascending=False).reset_index(drop=True)
    grouped.insert(0, "Alcance", scope_label)
    if "Athlete" in result.columns:
        athlete_counts = (
            result.groupby("Date")["Athlete"]
            .nunique(dropna=True)
            .reset_index(name="Atletas")
        )
        grouped = grouped.merge(athlete_counts, on="Date", how="left")
    return grouped


def _prepare_export_frame(sheet_name: str, df: pd.DataFrame) -> pd.DataFrame:
    result = _normalize_date_like_columns(df)

    if sheet_name == "ACWR_sRPE":
        result = _preferred_columns(
            result,
            ["Athlete", "Date", "sRPE_diario", "Aguda_7d", "Cronica_28d", "ACWR", "EWMA_Aguda", "EWMA_Cronica", "ACWR_EWMA", "Zona"],
        )
        return _sort_export_frame(result, ["Athlete", "Date"], [True, False])
    if sheet_name == "Monotonia_Strain":
        result = _preferred_columns(
            result,
            ["Athlete", "Semana", "Carga_Semanal", "Monotonia", "Monotony_Status", "Monotony_Warning", "Strain"],
        )
        return _sort_export_frame(result, ["Athlete", "Semana"], [True, False])
    if sheet_name == "Wellness":
        result = _preferred_columns(
            result,
            ["Athlete", "Date", "Sueno_hs", "Estres", "Dolor", "Wellness_Score"],
        )
        return _sort_export_frame(result, ["Athlete", "Date"], [True, False])
    if sheet_name == "Evaluaciones_Saltos":
        result = _preferred_columns(
            result,
            ["Athlete", "Date", "CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "EUR", "DRI", "IMTP_N", "NM_Profile"],
        )
        result = result.rename(columns={"EUR": EUR_RATIO_LABEL})
        return _sort_export_frame(result, ["Athlete", "Date"], [True, False])
    if sheet_name == "Maximos_Ejercicios":
        result = _preferred_columns(
            result,
            ["Athlete", "Exercise Name", "Added Date", "Max Value"],
        )
        return _sort_export_frame(result, ["Athlete", "Added Date", "Exercise Name"], [True, False, True])
    if sheet_name == "Volumen_Carga_Externa":
        result = _preferred_columns(
            result,
            [
                "Source",
                "Athlete",
                "Date",
                "Exercise",
                "Exercise Name",
                "Tags",
                "stimulus_category",
                "Category",
                "Result",
                "Reps",
                "Sets",
                "Volume_Load_kg",
                "Contacts",
                "Exposures",
                "Distance_m",
            ],
        )
        return _sort_export_frame(result, ["Athlete", "Date", "stimulus_category", "Exercise"], [True, False, True, True])
    if sheet_name in {"Volumen_RepLoad_Legacy", "Volumen_Sesion"}:
        result = _preferred_columns(
            result,
            ["Source", "Athlete", "Date", "Exercise", "Reps_Assigned", "Reps_Completed", "Load_kg"],
        )
        if "Date" not in result.columns and "Assigned Date" in result.columns:
            result = _preferred_columns(
                result,
                ["Source", "Athlete", "Assigned Date", "Exercise", "Reps_Assigned", "Reps_Completed", "Load_kg", "Volume_Load", "Category"],
            )
            return _sort_export_frame(result, ["Athlete", "Assigned Date", "Exercise"], [True, False, True])
        return _sort_export_frame(result, ["Athlete", "Date", "Exercise"], [True, False, True])
    if sheet_name == "Completion_Resumen":
        result = _preferred_columns(
            result,
            ["Alcance", "Date", "Pct_Promedio", "Sesiones", "Atletas"],
        )
        return _sort_export_frame(result, ["Date"], [False])
    if sheet_name == "Completion_Rate":
        result = _preferred_columns(
            result,
            ["Athlete", "Date", "Assigned", "Completed", "Pct"],
        )
        return _sort_export_frame(result, ["Athlete", "Date"], [True, False])
    return result.reset_index(drop=True)


def _format_excel_sheet(worksheet, df: pd.DataFrame, sheet_name: str) -> None:
    header_fill = PatternFill(fill_type="solid", fgColor="0D3C5E")
    header_font = Font(color="FEFEFE", bold=True)
    body_font = Font(color="221F20")
    thin_side = Side(style="thin", color="D8DEE4")
    border = Border(bottom=thin_side)
    stripe_fill = PatternFill(fill_type="solid", fgColor="F7FAFC")

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.sheet_view.showGridLines = False
    worksheet.row_dimensions[1].height = 22

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for row_idx, row in enumerate(worksheet.iter_rows(min_row=2), start=2):
        for cell in row:
            cell.font = body_font
            cell.alignment = Alignment(vertical="top", wrap_text=sheet_name in {"Interpretacion", "Reporte_Meta"})
            cell.border = border
            if row_idx % 2 == 0:
                cell.fill = stripe_fill

    date_like_cols = [
        idx for idx, col in enumerate(df.columns, start=1)
        if "date" in str(col).lower() or "fecha" in str(col).lower() or "semana" in str(col).lower()
    ]
    percent_like_cols = [
        idx for idx, col in enumerate(df.columns, start=1)
        if "pct" in str(col).lower() or "%" in str(col) or "completion promedio" in str(col).lower()
    ]
    numeric_like_cols = [
        idx for idx, col in enumerate(df.columns, start=1)
        if pd.api.types.is_numeric_dtype(df[col])
    ]

    for col_idx in date_like_cols:
        for cell in worksheet[get_column_letter(col_idx)][1:]:
            cell.number_format = "DD/MM/YYYY"

    for col_idx in numeric_like_cols:
        for cell in worksheet[get_column_letter(col_idx)][1:]:
            cell.alignment = Alignment(horizontal="right", vertical="top")

    for col_idx in percent_like_cols:
        for cell in worksheet[get_column_letter(col_idx)][1:]:
            cell.number_format = '0.0"%"'

    for idx, column in enumerate(df.columns, start=1):
        values = [str(column)] + ["" if pd.isna(value) else str(value) for value in df[column].head(200)]
        max_len = min(max(len(value) for value in values) + 2, 42)
        worksheet.column_dimensions[get_column_letter(idx)].width = max(12, max_len)

    if sheet_name == "Reporte_Meta":
        worksheet.column_dimensions["A"].width = 22
        worksheet.column_dimensions["B"].width = 72


def export_excel(data_dict: dict[str, pd.DataFrame]) -> bytes:
    """Export selected dataframes to a multi-sheet Excel workbook."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in _ordered_sheet_items(data_dict):
            if df is not None and not df.empty:
                prepared_df = _prepare_export_frame(sheet_name, df)
                export_name = REPORT_SHEET_EXPORT_NAMES.get(sheet_name, sheet_name)[:31]
                prepared_df.to_excel(writer, sheet_name=export_name, index=False)
                worksheet = writer.book[export_name]
                _format_excel_sheet(worksheet, prepared_df, sheet_name)
    return buffer.getvalue()


def _ascii_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = (
        text.replace("—", "-")
        .replace("±", "+/-")
        .replace("σ", "sd")
        .replace("·", "-")
        .replace("→", "->")
    )
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.encode("latin-1", "ignore").decode("latin-1")


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str, width: int) -> list[str]:
    clean = _ascii_text(text).strip()
    if not clean:
        return [""]
    return textwrap.wrap(clean, width=width) or [clean]


def _pdf_color(hex_color: str) -> tuple[float, float, float]:
    hex_clean = hex_color.lstrip("#")
    return tuple(int(hex_clean[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _pdf_text(commands: list[str], x: int, y: int, text: str, *, font: str = "F1", size: int = 11, color: str = "#221F20") -> None:
    r, g, b = _pdf_color(color)
    commands.append("BT")
    commands.append(f"/{font} {size} Tf")
    commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
    commands.append(f"{x} {y} Td")
    commands.append(f"({_pdf_escape(_ascii_text(text))}) Tj")
    commands.append("ET")


def _pdf_multiline(
    commands: list[str],
    x: int,
    y: int,
    lines: list[str],
    *,
    font: str = "F1",
    size: int = 11,
    color: str = "#221F20",
    leading: int = 14,
) -> int:
    current_y = y
    for line in lines:
        _pdf_text(commands, x, current_y, line, font=font, size=size, color=color)
        current_y -= leading
    return current_y


def _pdf_rect(commands: list[str], x: int, y: int, w: int, h: int, fill: str) -> None:
    r, g, b = _pdf_color(fill)
    commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
    commands.append(f"{x} {y} {w} {h} re f")


def _pdf_line(commands: list[str], x1: int, y1: int, x2: int, y2: int, color: str = "#D8DEE4") -> None:
    r, g, b = _pdf_color(color)
    commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
    commands.append("1 w")
    commands.append(f"{x1} {y1} m {x2} {y2} l S")


def _pdf_stroke_rect(
    commands: list[str],
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    color: str = "#D8DEE4",
    width: float = 1.0,
) -> None:
    r, g, b = _pdf_color(color)
    commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
    commands.append(f"{width:.1f} w")
    commands.append(f"{x} {y} {w} {h} re S")


def _zone_color(zone: object) -> str:
    zone_text = _ascii_text(zone).strip().lower()
    if "alto" in zone_text or "riesgo" in zone_text:
        return "#B85C38"
    if "precauc" in zone_text:
        return "#C58A2D"
    if "opt" in zone_text:
        return "#2F6B52"
    if "sub" in zone_text:
        return "#708C9F"
    return "#5A595B"


def _display_metric(value: object, *, digits: int | None = None, suffix: str = "") -> str:
    numeric = _coerce_float(value)
    if numeric is not None:
        if digits is None:
            rendered = f"{numeric:g}"
        else:
            rendered = f"{numeric:.{digits}f}"
        return f"{rendered}{suffix}"
    text = _ascii_text(value).strip()
    return text or "-"


def _display_zone(zone: object) -> str:
    clean = _ascii_text(zone).strip().lower()
    mapping = {
        "optimo": "Óptimo",
        "precaucion": "Precaución",
        "subcarga": "Subcarga",
        "alto riesgo": "Alto riesgo",
    }
    return mapping.get(clean, _ascii_text(zone).strip() or "-")


def _snapshot_value(column: str, raw_value: object) -> str:
    if column == "Atleta":
        return _ascii_text(raw_value).strip() or "-"
    if column in {"ACWR", "ACWR EWMA"}:
        return _display_metric(raw_value, digits=2)
    if column == "Zona":
        return _display_zone(raw_value)
    if column == "Wellness":
        return _display_metric(raw_value, digits=1)
    if column == "CMJ":
        return _display_metric(raw_value, digits=1, suffix=" cm")
    if column == "DRI":
        return _display_metric(raw_value, digits=2)
    if column == "IMTP":
        return _display_metric(raw_value, digits=0, suffix=" N")
    if column == "Perfil NM":
        return _ascii_text(raw_value).strip() or "-"
    return _display_metric(raw_value)


def _short_profile_label(profile: object) -> str:
    text = _ascii_text(profile).strip()
    if not text:
        return "-"
    return text.split("/")[0].strip()[:18]


def _strengths_from_row(row: pd.Series, *, audience: str) -> list[str]:
    strengths: list[str] = []
    acwr = _coerce_float(row.get("ACWR EWMA"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
    wellness = _coerce_float(row.get("Wellness 3d"))
    profile = _ascii_text(row.get("Perfil NM")).strip()
    if cmj_delta is not None and cmj_delta >= 0:
        strengths.append(
            "Tu salto vertical se sostiene o mejora respecto al baseline inicial."
            if audience != "profe" else
            "El CMJ se sostiene o mejora respecto al baseline inicial."
        )
    if acwr is not None and 0.8 <= acwr <= 1.3:
        strengths.append(
            "La carga reciente está en una zona útil para seguir construyendo."
            if audience != "profe" else
            "La relación agudo-crónica está dentro de una zona operativa útil."
        )
    if wellness is not None and wellness >= 15:
        strengths.append(
            "La recuperación percibida acompaña bien el bloque actual."
            if audience != "profe" else
            "El wellness reciente acompaña sin señales claras de caída."
        )
    if profile:
        strengths.append(
            f"El perfil actual muestra una base de trabajo definida: {profile}."
            if audience == "cliente" else
            f"El perfil neuromuscular actual es {profile}."
        )
    return list(dict.fromkeys(strengths))[:3] or [
        "Hay una base mínima de información para seguir comparando la evolución."
        if audience != "cliente" else
        "Ya contamos con información suficiente para seguir tu progreso con más claridad."
    ]


def _gaps_from_row(row: pd.Series, *, audience: str) -> list[str]:
    gaps: list[str] = []
    acwr = _coerce_float(row.get("ACWR EWMA"))
    monotony = _coerce_float(row.get("Monotonia"))
    wellness = _coerce_float(row.get("Wellness 3d"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
    profile = _ascii_text(row.get("Perfil NM")).lower().strip()

    if cmj_delta is not None and cmj_delta <= -5:
        gaps.append(
            "Tu salto vertical cayo frente a tu baseline inicial; conviene recuperar calidad."
            if audience != "profe" else
            "El CMJ cae respecto al baseline inicial; conviene revisar fatiga reciente y exposicion."
        )
    if acwr is not None and acwr > 1.5:
        gaps.append(
            "La carga reciente viene alta y puede pedir una semana más controlada."
            if audience != "profe" else
            "El ACWR EWMA queda alto y sugiere controlar densidad y exposición semanal."
        )
    elif acwr is not None and acwr < 0.8:
        gaps.append(
            "La carga reciente quedó baja; puede faltar continuidad de estímulo."
            if audience != "profe" else
            "El ACWR EWMA cae en subcarga; conviene revisar continuidad y volumen útil."
        )
    if monotony is not None and monotony > 2.0:
        gaps.append(
            "La semana se repite demasiado y conviene darle más variación."
            if audience != "profe" else
            "La monotonía semanal está alta y puede limitar tolerancia al bloque."
        )
    if wellness is not None and wellness < 15:
        gaps.append(
            "La recuperación percibida viene baja y requiere seguimiento cercano."
            if audience != "profe" else
            "El wellness reciente cae y sugiere revisar recuperación diaria."
        )
    if "poca base" in profile:
        gaps.append(
            "Todavía hay margen para construir una base de fuerza más sólida."
            if audience != "profe" else
            "El perfil actual sigue marcando necesidad de consolidar fuerza base."
        )
    return list(dict.fromkeys(gaps))[:3] or [
        "No aparece una alerta dominante; el foco está en sostener continuidad y calidad."
        if audience != "cliente" else
        "No aparece una alarma grande; la prioridad es sostener lo que ya está funcionando."
    ]


def _next_steps_from_row(row: pd.Series, *, audience: str) -> list[str]:
    steps: list[str] = []
    profile = _ascii_text(row.get("Perfil NM")).lower().strip()
    acwr = _coerce_float(row.get("ACWR EWMA"))
    monotony = _coerce_float(row.get("Monotonia"))
    cmj_delta = _coerce_float(row.get("CMJ vs BL %"))

    if "poca base" in profile:
        steps.append(
            "Construir fuerza base antes de pedir más reactividad."
            if audience != "cliente" else
            "Dedicar más trabajo a la base de fuerza para que el progreso sea más estable."
        )
    if cmj_delta is not None and cmj_delta <= -5:
        steps.append(
            "Bajar fatiga y recuperar calidad de salto en la próxima ventana."
            if audience != "cliente" else
            "Buscar que el salto vuelva a acercarse a tu mejor referencia reciente."
        )
    if acwr is not None and acwr > 1.5:
        steps.append(
            "Regular la densidad de trabajo del próximo microciclo."
            if audience != "cliente" else
            "Ordenar la carga de la semana para que el cuerpo la tolere mejor."
        )
    if monotony is not None and monotony > 2.0:
        steps.append(
            "Meter más variación semanal y ajustar recuperación."
            if audience != "cliente" else
            "Variar más el trabajo de la semana para que no todo se sienta igual."
        )
    return steps[:3] or [
        "Sostener la línea actual y volver a medir en la próxima ventana operativa."
        if audience != "cliente" else
        "Mantener la línea actual y volver a medir para confirmar el progreso."
    ]


def _pdf_label_value_card(
    commands: list[str],
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    label: str,
    value: str,
    accent: str = "#0D3C5E",
    fill: str = "#FEFEFE",
    border: str = "#D8DEE4",
    value_color: str = "#221F20",
) -> None:
    _pdf_rect(commands, x, y, w, h, fill)
    _pdf_stroke_rect(commands, x, y, w, h, color=border)
    _pdf_rect(commands, x, y + h - 4, w, 4, accent)
    _pdf_text(commands, x + 14, y + h - 24, label, size=9, color="#5A595B")
    _pdf_text(commands, x + 14, y + h - 50, value, font="F2", size=18, color=value_color)


def _pdf_module_block(
    commands: list[str],
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    title: str,
    summary: str,
    focuses: list[str],
    accent: str = "#0D3C5E",
) -> None:
    _pdf_rect(commands, x, y, w, h, "#FEFEFE")
    _pdf_stroke_rect(commands, x, y, w, h, color="#D8DEE4")
    _pdf_rect(commands, x, y + h - 6, w, 6, accent)
    _pdf_text(commands, x + 14, y + h - 28, title, font="F2", size=12, color="#221F20")
    current_y = _pdf_multiline(
        commands,
        x + 14,
        y + h - 48,
        _wrap_lines(summary, 42),
        size=9,
        color="#5A595B",
        leading=12,
    ) - 8
    for focus in focuses[:2]:
        if current_y < y + 20:
            break
        current_y = _pdf_multiline(
            commands,
            x + 18,
            current_y,
            _wrap_lines(f"- {focus}", 40),
            size=8,
            color="#221F20",
            leading=11,
        ) - 4


def _pdf_chart_panel(
    commands: list[str],
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    title: str,
    series: list[tuple[str, float]],
    line_color: str = "#0D3C5E",
) -> None:
    _pdf_rect(commands, x, y, w, h, "#FEFEFE")
    _pdf_stroke_rect(commands, x, y, w, h, color="#D8DEE4")
    _pdf_text(commands, x + 14, y + h - 24, title, font="F2", size=11, color="#221F20")

    if not series or len(series) < 2:
        _pdf_text(commands, x + 14, y + h - 54, "Sin historial suficiente para mostrar tendencia.", size=9, color="#708C9F")
        return

    plot_x = x + 16
    plot_y = y + 24
    plot_w = w - 32
    plot_h = h - 58
    _pdf_line(commands, plot_x, plot_y, plot_x + plot_w, plot_y, color="#D8DEE4")
    _pdf_line(commands, plot_x, plot_y, plot_x, plot_y + plot_h, color="#D8DEE4")

    values = [value for _, value in series]
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        max_v += 1
        min_v -= 1

    r, g, b = _pdf_color(line_color)
    commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
    commands.append("1.6 w")
    for idx, (_, value) in enumerate(series):
        px = plot_x + (plot_w * idx / max(1, len(series) - 1))
        py = plot_y + ((value - min_v) / (max_v - min_v) * plot_h)
        if idx == 0:
            commands.append(f"{px:.1f} {py:.1f} m")
        else:
            commands.append(f"{px:.1f} {py:.1f} l")
    commands.append("S")

    first_label = series[0][0]
    last_label = series[-1][0]
    _pdf_text(commands, plot_x, y + 10, first_label, size=8, color="#708C9F")
    _pdf_text(commands, plot_x + plot_w - 28, y + 10, last_label, size=8, color="#708C9F")
    _pdf_text(commands, plot_x, plot_y + plot_h + 6, _display_metric(min_v, digits=1), size=8, color="#708C9F")
    _pdf_text(commands, plot_x + plot_w - 28, plot_y + plot_h + 6, _display_metric(max_v, digits=1), size=8, color="#708C9F")


def _build_cover_page(
    report_athlete: str,
    summary_df: pd.DataFrame,
    insights: dict[str, dict[str, object]],
    report_audience: str,
) -> str:
    audience = normalize_report_audience(report_audience)
    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    _pdf_rect(commands, 0, 742, 595, 100, "#221F20")
    _pdf_rect(commands, 48, 730, 220, 3, "#0D3C5E")
    _pdf_text(commands, 48, 794, "THRESHOLD STRENGTH & CONDITIONING", font="F2", size=21, color="#FEFEFE")
    subtitle = {
        "atleta": "Versión atleta",
        "profe": "Versión técnica",
        "cliente": "Versión cliente",
    }[audience]
    _pdf_text(commands, 48, 770, subtitle, font="F2", size=14, color="#9AA2A9")

    _pdf_text(commands, 48, 698, "Alcance", size=10, color="#708C9F")
    _pdf_text(commands, 48, 674, report_athlete, font="F2", size=20, color="#0D3C5E")
    _pdf_text(commands, 250, 698, "Generado", size=10, color="#708C9F")
    _pdf_text(commands, 250, 676, f"{datetime.now():%d/%m/%Y %H:%M}", font="F2", size=14, color="#221F20")
    _pdf_text(commands, 430, 698, "Filas ejecutivas", size=10, color="#708C9F")
    _pdf_text(commands, 430, 676, str(len(summary_df)), font="F2", size=14, color="#221F20")

    _pdf_rect(commands, 48, 560, 499, 84, "#FEFEFE")
    _pdf_stroke_rect(commands, 48, 560, 499, 84, color="#D8DEE4")
    _pdf_text(commands, 64, 620, "Narrativa ejecutiva", font="F2", size=13, color="#221F20")
    intro = insights.get("report", {}).get("summary", "Reporte operativo listo para revisión técnica.")
    _pdf_multiline(commands, 64, 598, _wrap_lines(intro, 78), size=10, color="#5A595B", leading=14)

    overview_summary = insights.get("overview", {}).get("summary", "Todavía no hay una lectura general disponible.")
    focus_value = {
        "atleta": "Evaluación y perfil",
        "profe": "Lectura integrada",
        "cliente": "Progreso y claridad",
    }[audience]
    _pdf_label_value_card(commands, 48, 450, 156, 78, label="Foco del reporte", value=focus_value, accent="#0D3C5E")
    _pdf_label_value_card(commands, 220, 450, 156, 78, label="Ventana", value="Últimas 6 semanas", accent="#708C9F")
    _pdf_label_value_card(commands, 392, 450, 155, 78, label="Módulos", value=str(len(insights)), accent="#5A595B")

    _pdf_text(commands, 48, 410, "Contexto de lectura", font="F2", size=13, color="#221F20")
    _pdf_multiline(commands, 48, 388, _wrap_lines(overview_summary, 82), size=10, color="#5A595B", leading=14)

    _pdf_text(commands, 48, 318, "Focos prioritarios", font="F2", size=13, color="#221F20")
    current_y = 294
    for focus in insights.get("report", {}).get("focuses", []):
        current_y = _pdf_multiline(
            commands,
            60,
            current_y,
            _wrap_lines(f"- {focus}", 78),
            size=10,
            color="#221F20",
            leading=14,
        ) - 6

    _pdf_line(commands, 48, 112, 547, 112, color="#D8DEE4")
    footer = "Threshold S&C - Monitoreo de carga, evaluaciones y seguimiento de atletas."
    _pdf_multiline(commands, 48, 92, _wrap_lines(footer, 84), size=9, color="#708C9F", leading=13)
    return "\n".join(commands)


def _build_dashboard_page(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
    report_audience: str,
) -> str | None:
    audience = normalize_report_audience(report_audience)
    if summary_df.empty:
        return None

    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    page_title = {
        "atleta": "Resumen de rendimiento",
        "profe": "Dashboard ejecutivo",
        "cliente": "Resumen de progreso",
    }[audience]
    page_subtitle = {
        "atleta": "Lectura cuasi técnica para entender perfil actual, fortalezas y próximos pasos.",
        "profe": "Última foto integrada para revisión operativa.",
        "cliente": "Lectura clara del estado actual y del progreso reciente.",
    }[audience]
    _pdf_text(commands, 48, 800, page_title, font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 778, page_subtitle, size=10, color="#5A595B")
    _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

    if report_athlete != "Todos" and not summary_df.empty:
        focus_row = summary_df.iloc[0]
        title_text = _ascii_text(focus_row.get("Atleta", report_athlete))
    else:
        focus_row = summary_df.iloc[0]
        title_text = _count_phrase(len(summary_df), "atleta visible", "atletas visibles")

    _pdf_text(commands, 48, 730, title_text, font="F2", size=22, color="#221F20")
    dashboard_note = {
        "atleta": "En esta versión priorizamos evaluaciones, perfil y foco inmediato de trabajo.",
        "profe": "Tablero listo para revisión técnica y exportación profesional.",
        "cliente": "En esta versión priorizamos comprensión, progreso y próximos pasos.",
    }[audience]
    _pdf_text(commands, 48, 708, dashboard_note, size=10, color="#708C9F")

    cards = _audience_dashboard_cards(state, focus_row, report_athlete, audience)

    positions = [
        (48, 604), (220, 604), (392, 604),
        (48, 504), (220, 504), (392, 504),
    ]
    for (label, value, accent), (x, y) in zip(cards, positions):
        _pdf_label_value_card(commands, x, y, 155, 82, label=label, value=value, accent=accent)

    completion_value = (
        _athlete_completion_mean(state, report_athlete)
        if report_athlete != "Todos" else
        _team_completion_mean(state)
    )
    completion_text = _display_metric(completion_value, digits=1, suffix="%") if completion_value is not None else "-"
    athletes_text = str(len(summary_df))
    datasets_count = len(
        [
            key for key in MODERN_REPORT_DATASET_KEYS
            if state.get(key) is not None and not state.get(key).empty
        ]
    )
    athletes_label = "Atleta visible" if len(summary_df) == 1 else "Atletas visibles"
    datasets_label = "Fuente activa" if datasets_count == 1 else "Fuentes activas"
    adherence_label = "Adherencia del atleta" if report_athlete != "Todos" else "Adherencia promedio"

    _pdf_rect(commands, 48, 392, 499, 78, "#FEFEFE")
    _pdf_stroke_rect(commands, 48, 392, 499, 78, color="#D8DEE4")
    pulse_title = "Pulso del reporte" if audience == "profe" else "Lectura rápida"
    _pdf_text(commands, 64, 438, pulse_title, font="F2", size=12, color="#221F20")
    _pdf_text(commands, 64, 414, f"{athletes_label}: {athletes_text}", size=10, color="#5A595B")
    _pdf_text(commands, 220, 414, f"{datasets_label}: {datasets_count}", size=10, color="#5A595B")
    _pdf_text(commands, 392, 414, f"{adherence_label}: {completion_text}", size=10, color="#5A595B")

    _pdf_text(commands, 48, 346, "Nota de exportación", font="F2", size=12, color="#221F20")
    _pdf_multiline(
        commands,
        48,
        324,
        (
            [
                "Usa esta página como snapshot ejecutivo para cuerpo técnico y para toma de decisiones.",
                "La tabla integrada y la lectura por módulos continúan en las siguientes páginas.",
            ]
            if audience == "profe" else
            (
                [
                    "Esta página resume tu estado actual con foco en evaluaciones, perfil y próximos pasos.",
                    "Después vas a ver un perfil más claro y una lectura específica para vos.",
                ]
                if audience == "atleta" else
                [
                    "Esta página resume de forma simple dónde estás hoy y qué viene después.",
                    "Más abajo vas a ver un perfil resumido y los próximos pasos recomendados.",
                ]
            )
        ),
        size=10,
        color="#5A595B",
        leading=14,
    )
    return "\n".join(commands)


def _build_metric_profile_page(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
    report_audience: str,
) -> str | None:
    audience = normalize_report_audience(report_audience)
    if summary_df.empty or report_athlete == "Todos":
        return None

    focus_row = summary_df.iloc[0]
    rows = _audience_metric_rows(state, focus_row, report_athlete, audience)
    title = "Perfil actual" if audience == "atleta" else "Dónde estás hoy"
    subtitle = (
        "Resumen cuasi técnico de tus evaluaciones, carga y recuperación."
        if audience == "atleta" else
        "Resumen simple del estado actual y de los indicadores más importantes."
    )

    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#FEFEFE")
    _pdf_text(commands, 48, 800, title, font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 778, subtitle, size=10, color="#5A595B")
    _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

    box_x = 48
    box_y = 176
    box_w = 499
    box_h = 552
    _pdf_rect(commands, box_x, box_y, box_w, box_h, "#F8FAFB")
    _pdf_stroke_rect(commands, box_x, box_y, box_w, box_h, color="#D8DEE4")

    left_rows = rows[::2]
    right_rows = rows[1::2]
    for col_idx, chunk in enumerate([left_rows, right_rows]):
        start_x = box_x + 20 + col_idx * 240
        current_y = box_y + box_h - 42
        for label, value in chunk:
            _pdf_text(commands, start_x, current_y, label, font="F2", size=10, color="#5A595B")
            _pdf_text(commands, start_x, current_y - 20, value, size=12, color="#221F20")
            _pdf_line(commands, start_x, current_y - 32, start_x + 205, current_y - 32, color="#E5E9ED")
            current_y -= 62
    return "\n".join(commands)


def _build_snapshot_pages(summary_df: pd.DataFrame) -> list[str]:
    if summary_df.empty:
        return []

    display_df = summary_df.copy().fillna("-")
    keep_cols = [
        col for col in ["Atleta", "ACWR EWMA", "Zona", "Wellness 3d", "CMJ cm", "DRI", "IMTP N", "Perfil NM"]
        if col in display_df.columns
    ]
    display_df = display_df[keep_cols]
    rename_map = {
        "Atleta": "Atleta",
        "ACWR EWMA": "ACWR EWMA",
        "Wellness 3d": "Wellness",
        "CMJ cm": "CMJ",
        "IMTP N": "IMTP",
        "Perfil NM": "Perfil NM",
    }
    display_df = display_df.rename(columns=rename_map)

    rows_per_page = 14
    pages: list[str] = []
    columns = display_df.columns.tolist()
    widths = [122, 52, 58, 56, 44, 44, 56, 67][: len(columns)]

    for start in range(0, len(display_df), rows_per_page):
        chunk = display_df.iloc[start:start + rows_per_page]
        commands: list[str] = []
        _pdf_rect(commands, 0, 0, 595, 842, "#FEFEFE")
        _pdf_text(commands, 48, 800, "Tabla ejecutiva integrada", font="F2", size=18, color="#0D3C5E")
        _pdf_text(commands, 48, 778, "KPIs más recientes para la ventana operativa visible.", size=10, color="#5A595B")
        _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

        table_x = 48
        header_y = 726
        row_h = 34
        current_x = table_x
        for col, width in zip(columns, widths):
            _pdf_rect(commands, current_x, header_y, width, row_h, "#0D3C5E")
            _pdf_text(commands, current_x + 8, header_y + 12, col, font="F2", size=8, color="#FEFEFE")
            current_x += width

        current_y = header_y - row_h
        for row_idx, (_, row) in enumerate(chunk.iterrows()):
            fill = "#F8FAFB" if row_idx % 2 == 0 else "#FEFEFE"
            current_x = table_x
            for col, width in zip(columns, widths):
                _pdf_rect(commands, current_x, current_y, width, row_h, fill)
                _pdf_stroke_rect(commands, current_x, current_y, width, row_h, color="#D8DEE4", width=0.8)
                raw_value = _snapshot_value(col, row.get(col, "-"))
                text_color = _zone_color(raw_value) if col == "Zona" else "#221F20"
                wrap_width = max(8, int(width / 5.8))
                if col in {"Atleta", "Perfil NM"}:
                    wrap_width = max(10, int(width / 6.4))
                wrapped = _wrap_lines(raw_value, wrap_width)
                _pdf_multiline(commands, current_x + 6, current_y + 20, wrapped[:2], size=8, color=text_color, leading=10)
                current_x += width
            current_y -= row_h

        pages.append("\n".join(commands))
    return pages


def _build_insight_pages(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
    insights: dict[str, dict[str, object]],
    report_audience: str,
) -> list[str]:
    audience = normalize_report_audience(report_audience)
    payloads = _audience_blocks(state, report_athlete, summary_df, insights, audience)
    if not payloads:
        return []

    positions = [
        (48, 558), (306, 558),
        (48, 366), (306, 366),
        (48, 174), (306, 174),
    ]
    pages: list[str] = []
    blocks_per_page = len(positions)

    for start in range(0, len(payloads), blocks_per_page):
        commands: list[str] = []
        _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
        title = "Interpretación y focos" if audience == "profe" else ("Fortalezas y próximos pasos" if audience == "atleta" else "Lectura simple y próximos pasos")
        subtitle = (
            "Lectura editorial por módulo para seguimiento y reporte."
            if audience == "profe" else
            (
                "Bloques ordenados para entender qué está bien, qué mejorar y cómo seguir."
                if audience == "atleta" else
                "Resumen amigable para entender dónde estás hoy y cómo seguimos."
            )
        )
        _pdf_text(commands, 48, 800, title, font="F2", size=18, color="#0D3C5E")
        _pdf_text(commands, 48, 778, subtitle, size=10, color="#5A595B")
        _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

        for payload, (x, y) in zip(payloads[start:start + blocks_per_page], positions):
            _pdf_module_block(
                commands,
                x,
                y,
                241,
                152,
                title=payload.get("title", "Module"),
                summary=payload.get("summary", ""),
                focuses=payload.get("focuses", []),
            )
        pages.append("\n".join(commands))
    return pages


def generate_module_insights(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> dict[str, dict[str, object]]:
    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return {
            "overview": {
                "title": "Lectura general",
                "summary": "Todavía no hay atletas válidos para preparar un reporte individual.",
                "focuses": ["Cargar datos y seleccionar un atleta antes de exportar."],
            }
        }

    summary_df = build_executive_summary_df(state, effective_athlete, audience)
    athletes = _selected_athletes(state, effective_athlete)
    active_datasets = [
        key for key in MODERN_REPORT_DATASET_KEYS
        if state.get(key) is not None and not state.get(key).empty
    ]
    quality_report = _report_quality_report(state)
    readiness = _readiness_payload(quality_report)
    alerts = quality_report.get("alerts", [])
    weekly_summaries = _report_weekly_summaries(state)
    current_team = _current_week_slice(weekly_summaries.get("weekly_team"))
    current_load = _current_week_slice(weekly_summaries.get("weekly_load"), effective_athlete)
    current_team_row = current_team.tail(1).iloc[0] if not current_team.empty else pd.Series(dtype=object)
    current_load_row = current_load.tail(1).iloc[0] if not current_load.empty else pd.Series(dtype=object)
    completion_snapshot = _completion_snapshot(state, effective_athlete)

    if effective_athlete == "Todos":
        overview_summary = (
            f"Readiness {readiness['label'].lower()}: {readiness['detail']} "
            f"Semana actual con {_display_metric(current_team_row.get('athletes_active'), digits=0)} atleta(s) activos."
            if active_datasets else
            "Todavía no hay información suficiente para construir una lectura ejecutiva."
        )
        overview_focuses = [
            "Priorizar la semana actual, adherencia y readiness antes de compartir el reporte.",
            alerts[0] if alerts else "La base actual ya permite una lectura integrada de carga, bienestar y rendimiento.",
        ]
    else:
        athlete_quality = _quality_athlete_row(quality_report, effective_athlete)
        quality_text = _quality_detail_text(athlete_quality)
        weekly_parts = _compact_lines(
            [
                f"sRPE semanal {_display_metric(current_load_row.get('weekly_sRPE'), digits=0)}" if _coerce_float(current_load_row.get("weekly_sRPE")) is not None else None,
                f"ACWR EWMA {_display_metric(current_load_row.get('ACWR_EWMA_last'), digits=2)}" if _coerce_float(current_load_row.get("ACWR_EWMA_last")) is not None else None,
                completion_snapshot["value"] if completion_snapshot["numeric"] is not None else None,
            ]
        )
        overview_summary = (
            f"Readiness {readiness['label'].lower()} para {effective_athlete}. "
            f"{' | '.join(weekly_parts)}."
            if active_datasets else
            f"Todavía no hay información suficiente para construir una lectura ejecutiva de {effective_athlete}."
        )
        overview_focuses = [
            quality_text or "Cuidar continuidad de carga, adherencia y evaluaciones dentro de la misma ventana operativa.",
            alerts[0] if alerts else "El reporte prioriza semana actual, última evaluación útil y readiness del atleta.",
        ]

    insights: dict[str, dict[str, object]] = {
        "overview": {
            "title": "Lectura general",
            "summary": overview_summary,
            "focuses": overview_focuses,
        }
    }

    operational_notes = _session_notes_for_scope(state, effective_athlete, days=42, max_rows=4)
    if not operational_notes.empty:
        focus_lines = []
        for _, note in operational_notes.head(3).iterrows():
            detail = _compact_lines(
                [
                    _note_text(note.get("Assigned_Exercise")) if _has_text(note.get("Assigned_Exercise")) else None,
                    _note_text(note.get("Opt_Out_Type")) if _has_text(note.get("Opt_Out_Type")) else None,
                    _note_text(note.get("Explanation_Text")) if _has_text(note.get("Explanation_Text")) else None,
                ]
            )
            label = _note_text(note.get("Athlete")) if effective_athlete == "Todos" else _note_date_text(note.get("Date"))
            focus_lines.append(f"{label}: {' | '.join(detail)}" if detail else f"{label}: revisar nota operativa.")
        insights["operational_context"] = {
            "title": "Contexto operativo",
            "summary": _session_note_summary(operational_notes),
            "focuses": focus_lines,
        }

    individual_eval_available = False
    if effective_athlete != "Todos" and not summary_df.empty:
        row = summary_df.iloc[0]
        eval_available = _row_has_eval_data(row)
        load_available = _row_has_load_data(row)
        wellness_available = _row_has_wellness_data(row)
        individual_eval_available = eval_available

        acwr = _coerce_float(row.get("ACWR EWMA"))
        monotony = _coerce_float(row.get("Monotonia"))
        wellness = _coerce_float(row.get("Wellness 3d"))
        cmj_delta = _coerce_float(row.get("CMJ vs BL %"))

        load_notes: list[str] = []
        if acwr is not None:
            if acwr > 1.5:
                load_notes.append("Bajar carga aguda y revisar tolerancia de la semana.")
            elif acwr < 0.8:
                load_notes.append("Verificar si la subcarga es planificada o si falta estímulo.")
            else:
                load_notes.append("La relación agudo-crónica se mantiene en una zona de trabajo útil.")
        if monotony is not None and monotony > 2.0:
            load_notes.append("Aumentar variabilidad del microciclo para reducir monotonía.")
        if wellness is not None and wellness < 15:
            load_notes.append("Seguir recuperación diaria porque el wellness reciente está deprimido.")

        eval_focus: list[str] = []
        if cmj_delta is not None:
            if cmj_delta <= -5:
                eval_focus.append("El CMJ cae respecto al baseline inicial; conviene mirar fatiga y exposicion reciente.")
            elif cmj_delta >= 5:
                eval_focus.append("La salida vertical esta por encima del baseline inicial.")
            else:
                eval_focus.append("La evaluación se mantiene cerca de la línea base del atleta.")
        if _has_text(row.get("Perfil NM")):
            eval_focus.append(f"Perfil neuromuscular actual: {_profile_text(row)}.")
        if not eval_available:
            eval_focus.append("Todavía no hay una evaluación reciente para construir una comparación objetiva.")

        load_summary_parts = _compact_lines(
            [
                f"ACWR EWMA {_display_metric(acwr, digits=2)}" if acwr is not None else None,
                f"Monotonía {_display_metric(monotony, digits=2)}" if monotony is not None else None,
                f"Wellness 3 días {_display_metric(wellness, digits=1)}" if wellness_available else None,
            ]
        )
        eval_summary_parts = _compact_lines(
            [
                f"CMJ {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')}" if _coerce_float(row.get("CMJ cm")) is not None else None,
                f"{EUR_RATIO_LABEL} {_display_metric(_summary_eur_value(row), digits=2)}" if _coerce_float(_summary_eur_value(row)) is not None else None,
                f"DRI {_display_metric(row.get('DRI'), digits=2)}" if _coerce_float(row.get("DRI")) is not None else None,
                f"IMTP {_display_metric(row.get('IMTP N'), digits=0, suffix=' N')}" if _coerce_float(row.get("IMTP N")) is not None else None,
            ]
        )

        insights["load"] = {
            "title": "Lectura de carga",
            "summary": " | ".join(load_summary_parts) if load_summary_parts else "No hay datos recientes de carga y recuperación para una lectura estable.",
            "focuses": load_notes or ["Sin suficientes datos para una lectura de carga completa."],
        }
        insights["evaluations"] = {
            "title": "Lectura de evaluación",
            "summary": " | ".join(eval_summary_parts) if eval_summary_parts else "No hay una evaluación reciente cargada para este atleta.",
            "focuses": eval_focus,
        }

        if eval_available and (load_available or wellness_available):
            profile_summary = f"El perfil integrado de {effective_athlete} combina carga reciente, percepción de recuperación y última evaluación."
        elif eval_available:
            profile_summary = f"La lectura actual de {effective_athlete} se apoya principalmente en la última evaluación disponible."
        elif load_available or wellness_available:
            profile_summary = f"La lectura actual de {effective_athlete} se apoya en carga y bienestar recientes, a la espera de una nueva evaluación."
        else:
            profile_summary = f"Todavía no hay información suficiente para construir un perfil integrado de {effective_athlete}."

        insights["profile"] = {
            "title": "Foco del atleta",
            "summary": profile_summary,
            "focuses": list(dict.fromkeys(load_notes + eval_focus))[:3] or ["Seguir acumulando historial para una lectura individual más precisa."],
        }
    else:
        zone_counts = summary_df["Zona"].value_counts().to_dict() if "Zona" in summary_df.columns else {}
        profile_counts = summary_df["Perfil NM"].value_counts().to_dict() if "Perfil NM" in summary_df.columns else {}
        zone_text = ", ".join(f"{key}: {value}" for key, value in zone_counts.items()) if zone_counts else "sin zonas de carga disponibles"
        profile_text = ", ".join(f"{key}: {value}" for key, value in profile_counts.items()) if profile_counts else "sin perfiles neuromusculares disponibles"

        insights["load"] = {
            "title": "Lectura de carga",
            "summary": f"Distribución actual del equipo: {zone_text}.",
            "focuses": [
                "Revisar atletas en alto riesgo o precaución antes del siguiente microciclo." if any(key in zone_counts for key in ["Alto riesgo", "Precaucion", "Precaución"]) else "La distribución de carga no muestra acumulación marcada de riesgo.",
                "Monitorear la monotonía de quienes concentran más strain semanal.",
            ],
        }
        insights["evaluations"] = {
            "title": "Lectura de evaluación",
            "summary": f"Perfiles neuromusculares visibles: {profile_text}.",
            "focuses": [
                "Cruzar los perfiles reactivos con la carga reciente para decidir exposición pliométrica.",
                f"Usar IMTP, {EUR_RATIO_LABEL} y DRI para separar necesidades de fuerza base vs reactividad.",
            ],
        }
        insights["profile"] = {
            "title": "Lectura del equipo",
            "summary": "La lectura grupal resume la foto actual del plantel dentro de la ventana operativa visible.",
            "focuses": [
                "Identificar atletas fuera de rango antes de programar el siguiente bloque.",
                "Completar wellness y evaluaciones faltantes para cerrar la lectura por jugador.",
            ],
        }

    completion_mean = _team_completion_mean(state)
    individual_completion = _focus_completion_value(state, effective_athlete) if effective_athlete != "Todos" else None
    insights["team"] = {
        "title": "Adherencia del plan" if effective_athlete != "Todos" else "Adherencia del equipo",
        "summary": (
            f"Adherencia individual reciente: {individual_completion:.1f}%."
            if effective_athlete != "Todos" and individual_completion is not None else
            (
                f"Adherencia promedio del equipo: {completion_mean:.1f}%."
                if completion_mean is not None else
                "No hay información de adherencia cargada para evaluar ejecución."
            )
        ),
        "focuses": [
            (
                "Si la adherencia baja, revisar barreras de cumplimiento, disponibilidad y organización semanal."
                if effective_athlete != "Todos" else
                "Si la adherencia baja, revisar progresiones, disponibilidad y fricción operativa."
            ),
            (
                "Cruzar adherencia con carga y bienestar para entender si el plan realmente se está sosteniendo."
                if effective_athlete != "Todos" else
                "Alinear carga y adherencia para entender si el volumen planificado realmente se ejecuta."
            ),
        ],
    }

    if audience == "profe":
        target = effective_athlete if effective_athlete != "Todos" else "el equipo"
        report_summary = f"Versión técnica curada para {target}, priorizando semana actual, última evaluación útil, adherencia y readiness."
        report_focuses = [
            "El corazón del reporte resume semana actual, evaluación útil, adherencia y calidad del dato.",
            "El anexo técnico queda opt-in para no convertir el export en un dump de tablas.",
        ]
    elif audience == "atleta":
        report_summary = (
            f"Versión individual orientada al atleta, con foco en semana actual, evaluación útil y próximos pasos de trabajo para {effective_athlete}."
            if individual_eval_available else
            f"Versión individual orientada al atleta, centrada en estado actual, adherencia y próximos pasos de trabajo para {effective_athlete}."
        )
        report_focuses = [
            "Destacar fortalezas, oportunidades y foco inmediato en lenguaje cuasi técnico.",
            "Ordenar la información para que el atleta entienda qué sigue y por qué.",
        ]
    else:
        report_summary = (
            f"Versión individual amigable para cliente, enfocada en explicar semana actual, estado actual y próximos pasos de {effective_athlete}."
            if individual_eval_available else
            f"Versión individual amigable para cliente, enfocada en explicar seguimiento actual y próximos pasos de {effective_athlete}."
        )
        report_focuses = [
            "Simplificar el lenguaje y evitar tecnicismos innecesarios.",
            "Mostrar progreso, estado actual y próximos pasos con claridad.",
        ]

    insights["report"] = {
        "title": "Estado del reporte" if audience == "profe" else "Enfoque del reporte",
        "summary": report_summary,
        "focuses": report_focuses,
    }
    return insights


def _audience_dashboard_cards(
    state: dict[str, pd.DataFrame | None],
    focus_row: pd.Series,
    report_athlete: str,
    audience: str,
) -> list[tuple[str, str, str]]:
    completion_value = _focus_completion_value(state, report_athlete)
    eval_available = _row_has_eval_data(focus_row)
    load_available = _row_has_load_data(focus_row)
    wellness_available = _row_has_wellness_data(focus_row)
    cards: list[tuple[str, str, str]] = []

    if audience == "atleta":
        if eval_available:
            if _has_text(focus_row.get("Perfil NM")):
                cards.append(("Perfil actual", _short_profile_label(focus_row.get("Perfil NM")), "#0D3C5E"))
            if _coerce_float(focus_row.get("CMJ cm")) is not None:
                cards.append(("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"))
        else:
            cards.append(("Evaluación reciente", "Pendiente", "#708C9F"))

        if load_available:
            cards.append(("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))))
        if wellness_available:
            cards.append(("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"))
        if completion_value is not None:
            cards.append(("Adherencia", _display_metric(completion_value, digits=1, suffix="%"), "#708C9F"))
        cards.append(("Objetivo actual", _current_focus_text(focus_row, audience="atleta"), "#5A595B"))
        return cards[:6]

    if audience == "cliente":
        if load_available and _has_text(focus_row.get("Zona")):
            cards.append(("Estado actual", _display_zone(focus_row.get("Zona")), _zone_color(focus_row.get("Zona"))))
        else:
            cards.append(("Estado actual", "En seguimiento", "#708C9F"))

        if eval_available and _coerce_float(focus_row.get("CMJ cm")) is not None:
            cards.append(("Salto vertical", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"))
        if eval_available and _coerce_float(focus_row.get("CMJ vs BL %")) is not None:
            cards.append(("Cambio vs baseline", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%"), "#134263"))
        elif not eval_available:
            cards.append(("Evaluación física", "Pendiente", "#708C9F"))

        if wellness_available:
            cards.append(("Bienestar", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"))
        if completion_value is not None:
            cards.append(("Constancia", _display_metric(completion_value, digits=1, suffix="%"), "#708C9F"))
        if eval_available and _has_text(focus_row.get("Perfil NM")):
            cards.append(("Perfil actual", _short_profile_label(focus_row.get("Perfil NM")), "#5A595B"))
        cards.append(("Próximo foco", _current_focus_text(focus_row, audience="cliente"), "#134263"))
        return cards[:6]

    if load_available and _coerce_float(focus_row.get("ACWR EWMA")) is not None:
        cards.append(("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))))
    if load_available and _has_text(focus_row.get("Zona")):
        cards.append(("Zona de carga", _display_zone(focus_row.get("Zona")), "#708C9F"))
    if wellness_available:
        cards.append(("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"))
    if _coerce_float(focus_row.get("Monotonia")) is not None:
        cards.append(("Monotonía", _display_metric(focus_row.get("Monotonia"), digits=2), "#5A595B"))
    if eval_available and _coerce_float(focus_row.get("CMJ cm")) is not None:
        cards.append(("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"))
    if eval_available and _coerce_float(focus_row.get("IMTP N")) is not None:
        cards.append(("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N"), "#134263"))
    if not eval_available:
        cards.append(("Evaluación", "Sin registro reciente", "#708C9F"))
    if completion_value is not None and len(cards) < 6:
        cards.append(("Adherencia", _display_metric(completion_value, digits=1, suffix="%"), "#708C9F"))
    return cards[:6]


def _audience_metric_rows(
    state: dict[str, pd.DataFrame | None],
    focus_row: pd.Series,
    report_athlete: str,
    audience: str,
) -> list[tuple[str, str]]:
    completion_value = _focus_completion_value(state, report_athlete)
    eval_available = _row_has_eval_data(focus_row)
    load_available = _row_has_load_data(focus_row)
    wellness_available = _row_has_wellness_data(focus_row)
    rows: list[tuple[str, str]] = []

    if audience == "cliente":
        if load_available and _has_text(focus_row.get("Zona")):
            rows.append(("Cómo venís hoy", _display_zone(focus_row.get("Zona"))))
        if eval_available and _coerce_float(focus_row.get("CMJ vs BL %")) is not None:
            rows.append(("Cambio vs baseline inicial", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%")))
        elif not eval_available:
            rows.append(("Chequeo físico", "Todavía no contamos con una medición física comparable."))
        if eval_available and _coerce_float(focus_row.get("CMJ cm")) is not None:
            rows.append(("Tu salto hoy", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm")))
        if wellness_available:
            rows.append(("Bienestar reciente", _display_metric(focus_row.get("Wellness 3d"), digits=1)))
        if completion_value is not None:
            rows.append(("Constancia del plan", _display_metric(completion_value, digits=1, suffix="%")))
        if eval_available and _has_text(focus_row.get("Perfil NM")):
            rows.append(("Lectura actual", _profile_text(focus_row)))
        elif load_available or wellness_available:
            rows.append(("Lo que estamos mirando", "Ya hay información reciente para seguir tu proceso."))
        rows.append(("Objetivo actual", _current_focus_text(focus_row, audience="cliente")))
        return rows or [("Estado actual", "Falta información reciente para resumir tu progreso.")]

    if audience == "atleta":
        if eval_available:
            if _has_text(focus_row.get("Perfil NM")):
                rows.append(("Perfil neuromuscular", _profile_text(focus_row)))
            if _coerce_float(focus_row.get("CMJ cm")) is not None:
                rows.append(("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm")))
            if _coerce_float(focus_row.get("DRI")) is not None:
                rows.append(("DRI", _display_metric(focus_row.get("DRI"), digits=2)))
            if _coerce_float(focus_row.get("IMTP N")) is not None:
                rows.append(("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N")))
            focus_eur = _summary_eur_value(focus_row)
            if _coerce_float(focus_eur) is not None:
                rows.append((EUR_RATIO_LABEL, _display_metric(focus_eur, digits=2)))
            if _coerce_float(focus_row.get("CMJ vs BL %")) is not None:
                rows.append(("Cambio vs baseline inicial", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%")))
        else:
            rows.append(("Evaluación reciente", "Sin evaluación física reciente"))

        if load_available and _coerce_float(focus_row.get("ACWR EWMA")) is not None:
            rows.append(("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2)))
        if load_available and _coerce_float(focus_row.get("Monotonia")) is not None:
            rows.append(("Monotonía", _display_metric(focus_row.get("Monotonia"), digits=2)))
        if wellness_available:
            rows.append(("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1)))
        if completion_value is not None:
            rows.append(("Adherencia al plan", _display_metric(completion_value, digits=1, suffix="%")))
        rows.append(("Objetivo actual", _current_focus_text(focus_row, audience="atleta")))
        if not eval_available:
            rows.append(("Próxima acción", "Programar una nueva batería de evaluaciones."))
        return rows

    if _has_text(focus_row.get("Perfil NM")):
        rows.append(("Perfil neuromuscular", _profile_text(focus_row)))
    if _coerce_float(focus_row.get("CMJ cm")) is not None:
        rows.append(("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm")))
    if _coerce_float(focus_row.get("DRI")) is not None:
        rows.append(("DRI", _display_metric(focus_row.get("DRI"), digits=2)))
    if _coerce_float(focus_row.get("IMTP N")) is not None:
        rows.append(("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N")))
    if _coerce_float(focus_row.get("ACWR EWMA")) is not None:
        rows.append(("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2)))
    if _coerce_float(focus_row.get("Monotonia")) is not None:
        rows.append(("Monotonía", _display_metric(focus_row.get("Monotonia"), digits=2)))
    if wellness_available:
        rows.append(("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1)))
    if completion_value is not None:
        rows.append(("Adherencia", _display_metric(completion_value, digits=1, suffix="%")))
    return rows or [("Estado actual", "Sin datos suficientes para una lectura técnica estable.")]


def _audience_blocks(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
    insights: dict[str, dict[str, object]],
    audience: str,
) -> list[dict[str, object]]:
    if report_athlete == "Todos" or summary_df.empty:
        ordered_keys = ["overview", "load", "operational_context", "evaluations", "profile", "team", "report"]
        return [insights[key] for key in ordered_keys if insights.get(key)]

    row = summary_df.iloc[0]
    eval_available = _row_has_eval_data(row)
    load_available = _row_has_load_data(row)
    wellness_available = _row_has_wellness_data(row)
    completion_value = _focus_completion_value(state, report_athlete)

    if audience == "profe":
        integrated_focuses = _compact_lines(
            [
                f"Perfil actual: {_profile_text(row)}." if _has_text(row.get("Perfil NM")) else None,
                f"ACWR EWMA {_display_metric(row.get('ACWR EWMA'), digits=2)} en zona {_display_zone(row.get('Zona'))}." if load_available and _coerce_float(row.get("ACWR EWMA")) is not None else None,
                f"CMJ {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')} y DRI {_display_metric(row.get('DRI'), digits=2)}." if eval_available and _coerce_float(row.get("CMJ cm")) is not None and _coerce_float(row.get("DRI")) is not None else None,
                f"IMTP {_display_metric(row.get('IMTP N'), digits=0, suffix=' N')}." if eval_available and _coerce_float(row.get("IMTP N")) is not None else None,
            ]
        )
        planning_focuses = _technical_planning_focuses(row, completion_value)
        blocks = [
            {
                "title": "Carga actual",
                "summary": insights.get("load", {}).get("summary", "Sin lectura de carga disponible."),
                "focuses": insights.get("load", {}).get("focuses", []),
            },
            {
                "title": "Evaluación actual",
                "summary": insights.get("evaluations", {}).get("summary", "Sin evaluación reciente disponible."),
                "focuses": insights.get("evaluations", {}).get("focuses", []),
            },
            {
                "title": "Lectura integrada",
                "summary": "Cruce actual entre carga, evaluación y disponibilidad para orientar decisiones del próximo bloque.",
                "focuses": integrated_focuses or ["Todavía no hay datos suficientes para una síntesis técnica robusta."],
            },
            {
                "title": "Implicancias para la planificación",
                "summary": "Prioridades concretas para decidir qué cualidad empujar y qué controlar en la próxima ventana.",
                "focuses": planning_focuses,
            },
            {
                "title": insights.get("team", {}).get("title", "Adherencia del plan"),
                "summary": insights.get("team", {}).get("summary", "Sin lectura de adherencia disponible."),
                "focuses": insights.get("team", {}).get("focuses", []),
            },
        ]
        operational = insights.get("operational_context")
        if operational:
            blocks.insert(2, operational)
        return blocks

    strengths = _strengths_from_row(row, audience=audience)
    gaps = _gaps_from_row(row, audience=audience)
    next_steps = _next_steps_from_row(row, audience=audience)
    if not eval_available:
        next_steps = list(
            dict.fromkeys(
                ["Completar una nueva batería de evaluaciones para tener una referencia objetiva."] + next_steps
            )
        )[:3]

    if audience == "cliente":
        objective_focuses = _objective_focuses_from_row(row, audience="cliente")
        if eval_available:
            zone_text = (
                f" y tu estado general se lee como {_display_zone(row.get('Zona'))}"
                if load_available and _has_text(row.get("Zona")) else
                ""
            )
            progress_summary = (
                f"Tomamos como referencia tu baseline inicial. Hoy el cambio visible es {_display_metric(row.get('CMJ vs BL %'), digits=1, suffix='%')}{zone_text}."
                if _coerce_float(row.get("CMJ vs BL %")) is not None else
                "Ya contamos con una evaluación reciente para ubicar mejor tu punto actual y seguir el proceso con más claridad."
            )
        else:
            progress_summary = "Todavía no tenemos una comparación física completa, así que esta lectura se apoya en tu seguimiento reciente y en cómo viene respondiendo el proceso."

        current_focuses = _compact_lines(
            [
                f"Estado actual: {_display_zone(row.get('Zona'))}." if load_available and _has_text(row.get("Zona")) else None,
                f"Bienestar reciente: {_display_metric(row.get('Wellness 3d'), digits=1)}." if wellness_available else None,
                f"Constancia reciente: {_display_metric(completion_value, digits=1, suffix='%')}." if completion_value is not None else None,
                f"Salto vertical actual: {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')}." if eval_available and _coerce_float(row.get("CMJ cm")) is not None else None,
            ]
        ) or ["Seguimos construyendo información útil para entender mejor tu evolución."]

        blocks = [
            {
                "title": "Tu progreso hasta hoy",
                "summary": progress_summary,
                "focuses": current_focuses,
            },
            {
                "title": "Qué está funcionando bien",
                "summary": "Estos puntos muestran dónde el proceso ya está dando señales favorables.",
                "focuses": strengths,
            },
            {
                "title": "Lo que vamos a seguir mejorando",
                "summary": "Todavía hay margen de mejora y eso orienta lo que conviene trabajar ahora.",
                "focuses": gaps,
            },
            {
                "title": "Objetivo actual",
                "summary": f"El foco inmediato del trabajo es {_current_focus_text(row, audience='cliente').lower()}.",
                "focuses": objective_focuses or ["Vamos a sostener el proceso y seguir ordenando la progresión."],
            },
            {
                "title": "Próximos pasos",
                "summary": "Plan de acción inmediato para seguir avanzando con claridad y continuidad.",
                "focuses": next_steps,
            },
        ]
        operational = insights.get("operational_context")
        if operational:
            blocks.insert(-1, operational)
        return blocks

    if eval_available:
        profile_summary = " | ".join(
            _compact_lines(
                [
                    f"Perfil neuromuscular: {_profile_text(row)}" if _has_text(row.get("Perfil NM")) else None,
                    f"CMJ {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')}" if _coerce_float(row.get("CMJ cm")) is not None else None,
                    f"DRI {_display_metric(row.get('DRI'), digits=2)}" if _coerce_float(row.get("DRI")) is not None else None,
                    f"IMTP {_display_metric(row.get('IMTP N'), digits=0, suffix=' N')}" if _coerce_float(row.get("IMTP N")) is not None else None,
                ]
            )
        )
        profile_focuses = _compact_lines(
            [
                f"ACWR EWMA actual: {_display_metric(row.get('ACWR EWMA'), digits=2)} en zona {_display_zone(row.get('Zona'))}." if load_available and _coerce_float(row.get("ACWR EWMA")) is not None else None,
                f"Wellness reciente: {_display_metric(row.get('Wellness 3d'), digits=1)}." if wellness_available else None,
                f"Cambio frente al baseline inicial: {_display_metric(row.get('CMJ vs BL %'), digits=1, suffix='%')}." if _coerce_float(row.get("CMJ vs BL %")) is not None else None,
            ]
        ) or strengths[:2]
        first_block = {
            "title": "Perfil actual",
            "summary": profile_summary or "Hay evaluación reciente, pero faltan algunas métricas clave para completar la lectura.",
            "focuses": profile_focuses,
        }
    else:
        first_block = {
            "title": "Estado actual",
            "summary": "Todavía no hay una evaluación reciente cargada; por ahora la lectura se apoya en carga, bienestar y adherencia.",
            "focuses": _compact_lines(
                [
                    f"Estado de carga: {_display_zone(row.get('Zona'))}." if load_available and _has_text(row.get("Zona")) else None,
                    f"Wellness reciente: {_display_metric(row.get('Wellness 3d'), digits=1)}." if wellness_available else None,
                    f"Adherencia promedio: {_display_metric(completion_value, digits=1, suffix='%')}." if completion_value is not None else None,
                ]
            ) or ["La prioridad es completar una nueva evaluación para definir mejor el perfil actual."],
        }

    objective_focuses = _objective_focuses_from_row(row, audience="atleta")

    blocks = [
        first_block,
        {
            "title": "Fortalezas actuales",
            "summary": "Variables que hoy acompañan bien tu rendimiento y tu disponibilidad.",
            "focuses": strengths,
        },
        {
            "title": "Cosas a mejorar",
            "summary": "Variables a vigilar para que el próximo bloque sea más sólido.",
            "focuses": gaps,
        },
        {
            "title": "Objetivo actual",
            "summary": f"El foco inmediato del bloque es {_current_focus_text(row, audience='atleta').lower()}.",
            "focuses": objective_focuses or ["La prioridad es sostener el perfil actual sin perder disponibilidad."],
        },
        {
            "title": "Siguientes pasos",
            "summary": "Próximas prioridades de trabajo con un lenguaje cuasi técnico y accionable.",
            "focuses": next_steps,
        },
    ]
    operational = insights.get("operational_context")
    if operational:
        blocks.insert(-1, operational)
    return blocks


def _build_trend_page(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    report_audience: str,
) -> str | None:
    if report_athlete == "Todos":
        return None

    audience = normalize_report_audience(report_audience)
    candidates = {
        "profe": [
            ("CMJ", _cmj_series(state, report_athlete), "#0D3C5E"),
            ("ACWR EWMA", _acwr_series(state, report_athlete), "#708C9F"),
            ("Wellness 3 días", _wellness_series(state, report_athlete), "#2F6B52"),
        ],
        "atleta": [
            ("CMJ", _cmj_series(state, report_athlete), "#0D3C5E"),
            ("Wellness 3 días", _wellness_series(state, report_athlete), "#2F6B52"),
            ("ACWR EWMA", _acwr_series(state, report_athlete), "#708C9F"),
        ],
        "cliente": [
            ("Progreso de salto", _cmj_series(state, report_athlete), "#0D3C5E"),
            ("Bienestar reciente", _wellness_series(state, report_athlete), "#2F6B52"),
            ("Seguimiento del proceso", _acwr_series(state, report_athlete), "#708C9F"),
        ],
    }[audience]
    panels = [(title, series, color) for title, series, color in candidates if len(series) >= 2][:2]
    if not panels:
        return None

    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    title = "Tendencias clave" if audience != "cliente" else "Evolución reciente"
    subtitle = (
        "Curvas mínimas para seguir cómo se movieron las variables con mejor valor de decisión."
        if audience == "profe" else
        (
            "Lectura simple para ver cómo cambió tu estado reciente."
            if audience == "cliente" else
            "Lectura visual mínima para seguir tu evolución sin sobrecargar el reporte."
        )
    )
    _pdf_text(commands, 48, 800, title, font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 778, subtitle, size=10, color="#5A595B")
    _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

    if len(panels) == 1:
        panel_title, series, color = panels[0]
        _pdf_chart_panel(commands, 48, 196, 499, 470, title=panel_title, series=series, line_color=color)
    else:
        first_title, first_series, first_color = panels[0]
        second_title, second_series, second_color = panels[1]
        _pdf_chart_panel(commands, 48, 408, 499, 280, title=first_title, series=first_series, line_color=first_color)
        _pdf_chart_panel(commands, 48, 96, 499, 280, title=second_title, series=second_series, line_color=second_color)
    return "\n".join(commands)


def report_plotly_export_ready() -> bool:
    try:
        import plotly.io as pio  # noqa: F401
        import kaleido  # noqa: F401
    except Exception:
        return False
    return True


def _build_report_chart_theme() -> dict:
    colors = {
        "bg": "#F4F6F8",
        "card": "#FEFEFE",
        "navy": "#0D3C5E",
        "steel": "#134263",
        "black": "#221F20",
        "white": "#221F20",
        "gray": "#5A595B",
        "muted": "#708C9F",
        "border": "#D8DEE4",
        "blue": "#0D3C5E",
        "green": "#2F6B52",
        "yellow": "#C4A464",
        "orange": "#B87445",
        "red": "#B56B73",
    }
    return {
        "colors": colors,
        "layout": dict(
            template="plotly_white",
            paper_bgcolor=colors["bg"],
            plot_bgcolor=colors["card"],
            font=dict(family="Helvetica", color=colors["black"], size=11),
            margin=dict(l=44, r=28, t=68, b=46),
        ),
        "grid": "rgba(34, 31, 32, 0.08)",
        "grid_soft": "rgba(34, 31, 32, 0.05)",
        "reference_line": "rgba(34, 31, 32, 0.18)",
        "reference_fill": "rgba(13, 60, 94, 0.06)",
        "legend": dict(
            orientation="h",
            y=-0.18,
            bgcolor="rgba(254, 254, 254, 0.92)",
            bordercolor=colors["border"],
            borderwidth=1,
            font=dict(size=9, color=colors["gray"]),
        ),
        "monotony_high": 2.0,
    }


def _team_mean_for_radar(jdf: pd.DataFrame) -> dict[str, float]:
    z_keys = ["CMJ_Z", "SJ_Z", "DJtc_Z", "EUR_Z", "DRI_Z", "IMTP_Z"]
    return {key: float(jdf[key].mean()) for key in z_keys if key in jdf.columns and not jdf[key].dropna().empty}


def collect_report_plotly_figures(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> list[dict[str, object]]:
    try:
        from charts.load_charts import chart_acwr, chart_completion, chart_wellness
        from charts.dashboard_charts import (
            chart_cmj_trend,
            chart_quadrant_cmj_imtp,
            chart_quadrant_dri_sj,
            chart_radar,
        )
    except Exception:
        return []

    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return []
    theme = _build_report_chart_theme()
    figures: list[dict[str, object]] = []
    jdf = state.get("jump_df")

    if effective_athlete == "Todos":
        completion_plot_df = _completion_plot_df(state, "Todos")
        if not completion_plot_df.empty:
            figures.append(
                {
                    "slug": "completion_team",
                    "title": "Adherencia del equipo",
                    "figure": chart_completion(completion_plot_df, theme=theme, athlete_label="Todos"),
                }
            )

        if jdf is not None and not jdf.empty and "Athlete" in jdf.columns:
            latest_team = jdf.sort_values("Date").groupby("Athlete").last().reset_index()
            if len(latest_team) > 1 and {"CMJ_cm", "IMTP_N"}.issubset(latest_team.columns):
                figures.append(
                    {
                        "slug": "quadrant_cmj_imtp",
                        "title": "Mapa de potencia y fuerza máxima",
                        "figure": chart_quadrant_cmj_imtp(latest_team, theme=theme),
                    }
                )
            if len(latest_team) > 1 and {"DRI", "SJ_cm"}.issubset(latest_team.columns):
                figures.append(
                    {
                        "slug": "quadrant_dri_sj",
                        "title": "Mapa de reactividad y fuerza concéntrica",
                        "figure": chart_quadrant_dri_sj(latest_team, theme=theme),
                    }
                )

        if audience == "cliente":
            preferred = {"completion_team", "quadrant_cmj_imtp"}
        elif audience == "atleta":
            preferred = {"completion_team", "quadrant_cmj_imtp"}
        else:
            preferred = {"completion_team", "quadrant_cmj_imtp", "quadrant_dri_sj"}
        return [item for item in figures if item["slug"] in preferred][:2]

    if jdf is not None and not jdf.empty and "Athlete" in jdf.columns and effective_athlete in jdf["Athlete"].values:
        athlete_jdf = jdf[jdf["Athlete"] == effective_athlete].sort_values("Date")
        latest_row = athlete_jdf.iloc[-1]
        if audience in {"atleta", "profe"}:
            figures.append(
                {
                    "slug": "radar_perfil",
                    "title": "Perfil neuromuscular",
                    "figure": chart_radar(latest_row, effective_athlete, _team_mean_for_radar(jdf), theme=theme),
                }
            )
        if len(_cmj_series(state, effective_athlete)) >= 2:
            figures.append(
                {
                    "slug": "cmj_trend",
                    "title": "Tendencia de CMJ",
                    "figure": chart_cmj_trend(jdf, effective_athlete, theme=theme),
                }
            )

    acwr_dict = state.get("acwr_dict") or {}
    acwr_df = acwr_dict.get(effective_athlete)
    if acwr_df is not None and not acwr_df.empty and len(_acwr_series(state, effective_athlete)) >= 2:
        figures.append(
            {
                "slug": "acwr",
                "title": "Carga reciente",
                "figure": chart_acwr(acwr_df, effective_athlete, theme=theme),
                }
            )

    wdf = state.get("wellness_df")
    if wdf is not None and not wdf.empty and "Athlete" in wdf.columns:
        athlete_wdf = wdf[wdf["Athlete"] == effective_athlete].sort_values("Date")
        if not athlete_wdf.empty and len(_wellness_series(state, effective_athlete)) >= 2:
            figures.append(
                {
                    "slug": "wellness",
                    "title": "Bienestar reciente",
                    "figure": chart_wellness(athlete_wdf, effective_athlete, theme=theme),
                }
            )

    completion_plot_df = _completion_plot_df(state, effective_athlete)
    if not completion_plot_df.empty and len(completion_plot_df) >= 2:
        figures.append(
            {
                "slug": "completion",
                "title": "Adherencia reciente",
                "figure": chart_completion(completion_plot_df, theme=theme, athlete_label=effective_athlete),
            }
        )

    if audience == "cliente":
        preferred = {"cmj_trend", "wellness", "acwr", "completion"}
        figures = [item for item in figures if item["slug"] in preferred][:2]
    elif audience == "atleta":
        preferred = {"radar_perfil", "cmj_trend", "wellness", "acwr", "completion"}
        figures = [item for item in figures if item["slug"] in preferred][:2]
    else:
        preferred = {"radar_perfil", "cmj_trend", "acwr", "wellness", "completion"}
        figures = [item for item in figures if item["slug"] in preferred][:2]

    return figures


def export_plotly_figure_png(
    figure: object,
    *,
    width: int = 1200,
    height: int = 700,
    scale: int = 2,
) -> bytes | None:
    try:
        import plotly.io as pio
    except Exception:
        return None
    try:
        return pio.to_image(figure, format="png", width=width, height=height, scale=scale)
    except Exception:
        pass
    try:
        import kaleido
        chrome_path = kaleido.get_chrome_sync()
        if chrome_path:
            return pio.to_image(figure, format="png", width=width, height=height, scale=scale)
    except Exception:
        pass
    return None


def _professional_jump_history(state: dict[str, pd.DataFrame | None], athlete: str) -> pd.DataFrame:
    jdf = state.get("jump_df")
    if jdf is None or jdf.empty or "Athlete" not in jdf.columns:
        return pd.DataFrame()
    try:
        data = _prepare_jump_df(jdf.copy())
    except Exception:
        data = jdf.copy()
    if data.empty or "Date" not in data.columns or "Athlete" not in data.columns:
        return pd.DataFrame()
    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    data["Athlete"] = data["Athlete"].astype(str).str.strip()
    data = data.dropna(subset=["Date"])
    if athlete != "Todos":
        data = data[_professional_athlete_mask(data["Athlete"], athlete)]
    if data.empty:
        return pd.DataFrame()
    return data.sort_values(["Athlete", "Date"]).reset_index(drop=True)


def _professional_latest_team_jump_rows(state: dict[str, pd.DataFrame | None]) -> pd.DataFrame:
    data = _professional_jump_history(state, "Todos")
    if data.empty or "Athlete" not in data.columns:
        return pd.DataFrame()
    return data.sort_values("Date").groupby("Athlete", as_index=False).tail(1).reset_index(drop=True)


def _professional_completion_snapshot(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> dict[str, object]:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty or "Date" not in cdf.columns:
        return {"value": PDF_MISSING_TEXT, "detail": PDF_MISSING_TEXT, "numeric": None}
    result = cdf.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.dropna(subset=["Date"])
    if "Athlete" in result.columns:
        result = result[_professional_athlete_mask(result["Athlete"], athlete)]
    if result.empty:
        return {"value": PDF_MISSING_TEXT, "detail": PDF_MISSING_TEXT, "numeric": None}

    today_ts = pd.Timestamp(datetime.now()).normalize()
    current_week = today_ts - pd.Timedelta(days=today_ts.weekday())
    current = result[
        (result["Date"].dt.normalize() >= current_week)
        & (result["Date"].dt.normalize() <= today_ts)
    ].copy()
    period_label = "Semana actual"
    if current.empty:
        latest_date = result["Date"].max().normalize()
        current = result[result["Date"].dt.normalize().eq(latest_date)].copy()
        period_label = f"Ultima fecha util ({latest_date:%d/%m})"

    completion_result = calculate_completion_rate(current)
    if completion_result.value is None:
        return {"value": PDF_MISSING_TEXT, "detail": period_label, "numeric": None}
    completion_mean = round(float(completion_result.value), 1)
    return {
        "value": f"{completion_mean:.1f}%",
        "detail": period_label,
        "numeric": completion_mean,
    }


def _professional_metric_value_col(frame: pd.DataFrame, spec: dict[str, object]) -> str:
    value_cols = tuple(spec.get("value_cols", ()))
    for column in value_cols:
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").notna().any():
            return str(column)
    for column in value_cols:
        if column in frame.columns:
            return str(column)
    return str(value_cols[0]) if value_cols else ""


def _professional_metric_unit(spec: dict[str, object], value_col: str) -> str:
    unit = spec.get("unit", "")
    if isinstance(unit, dict):
        return str(unit.get(value_col, ""))
    return str(unit or "")


def _professional_metric_digits(spec: dict[str, object], value_col: str) -> int:
    digits = spec.get("digits", 1)
    if isinstance(digits, dict):
        return int(digits.get(value_col, 1))
    return int(digits)


def _format_professional_metric_value(value: object, spec: dict[str, object], value_col: str) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return PDF_MISSING_TEXT
    digits = _professional_metric_digits(spec, value_col)
    unit = _professional_metric_unit(spec, value_col)
    rendered = f"{numeric:.{digits}f}"
    if unit and unit != "ratio":
        return f"{rendered} {unit}"
    return rendered


def _professional_z_value(row: pd.Series | None, spec: dict[str, object]) -> float | None:
    if row is None:
        return None
    for column in tuple(spec.get("z_cols", ())):
        if column in row.index:
            numeric = _coerce_float(row.get(column))
            if numeric is not None:
                return numeric
    return None


def _professional_delta_text(
    current_value: float | None,
    previous_value: float | None,
    spec: dict[str, object],
    value_col: str,
) -> str:
    if current_value is None or previous_value is None:
        return PDF_MISSING_TEXT
    delta = current_value - previous_value
    digits = _professional_metric_digits(spec, value_col)
    unit = _professional_metric_unit(spec, value_col)
    rendered_delta = f"{delta:+.{digits}f}"
    if unit and unit != "ratio":
        rendered_delta = f"{rendered_delta} {unit}"
    pct = None
    if previous_value != 0:
        pct = (delta / previous_value) * 100
    return f"{rendered_delta} ({pct:+.1f}%)" if pct is not None else rendered_delta


def _professional_best_text(series: pd.Series, spec: dict[str, object], value_col: str) -> str:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return PDF_MISSING_TEXT
    best = valid.max() if bool(spec.get("higher_is_better", True)) else valid.min()
    return _format_professional_metric_value(best, spec, value_col)


def _professional_metric_signal(
    current_value: float | None,
    previous_value: float | None,
    z_value: float | None,
    spec: dict[str, object],
) -> tuple[str, str]:
    if current_value is None:
        return PDF_MISSING_TEXT, "#708C9F"
    if z_value is not None:
        if z_value >= 0.5:
            return "Verde", "#2F6B52"
        if z_value <= -0.5:
            return "Rojo", "#B56B73"
        return "Amarillo", "#C4A464"
    if previous_value is None:
        return PDF_MISSING_TEXT, "#708C9F"
    delta = current_value - previous_value
    if abs(delta) < 1e-9:
        return "Amarillo", "#C4A464"
    improved = delta > 0 if bool(spec.get("higher_is_better", True)) else delta < 0
    return ("Verde", "#2F6B52") if improved else ("Rojo", "#B56B73")


def _professional_metric_interpretation(label: str, current_value: float | None) -> str:
    if current_value is None or label == PDF_MISSING_TEXT:
        return "Faltan datos para generar una interpretación confiable."
    if label == "Verde":
        return "Señal favorable frente a la referencia disponible; puede sostenerse o progresarse con contexto."
    if label == "Rojo":
        return "Señal por debajo de referencia; revisar fatiga, tecnica, dolor y prioridad del bloque."
    return "Señal estable o intermedia; decidir junto con carga, wellness y contexto deportivo."


def _build_professional_metric_cards(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> list[dict[str, object]]:
    history = _professional_jump_history(state, athlete)
    cards: list[dict[str, object]] = []
    for spec in PROFESSIONAL_PDF_METRICS:
        value_col = _professional_metric_value_col(history, spec)
        metric_rows = pd.DataFrame()
        if not history.empty and value_col in history.columns:
            metric_rows = history[["Date", value_col] + [col for col in tuple(spec.get("z_cols", ())) if col in history.columns]].copy()
            metric_rows[value_col] = pd.to_numeric(metric_rows[value_col], errors="coerce")
            metric_rows = metric_rows.dropna(subset=[value_col]).sort_values("Date")

        latest_row = metric_rows.iloc[-1] if not metric_rows.empty else None
        previous_row = metric_rows.iloc[-2] if len(metric_rows) >= 2 else None
        current_value = _coerce_float(latest_row.get(value_col)) if latest_row is not None else None
        previous_value = _coerce_float(previous_row.get(value_col)) if previous_row is not None else None
        z_value = _professional_z_value(latest_row, spec)
        signal, color = _professional_metric_signal(current_value, previous_value, z_value, spec)
        missing_fields = sum(
            [
                current_value is None,
                previous_value is None,
                z_value is None,
                metric_rows.empty,
            ]
        )
        cards.append(
            {
                "title": spec["title"],
                "state": "missing" if current_value is None else "partial" if missing_fields else "available",
                "value": _format_professional_metric_value(current_value, spec, value_col),
                "delta": _professional_delta_text(current_value, previous_value, spec, value_col),
                "z_score": f"{z_value:+.2f}" if z_value is not None else PDF_MISSING_TEXT,
                "best": _professional_best_text(metric_rows[value_col] if not metric_rows.empty else pd.Series(dtype=float), spec, value_col),
                "signal": signal,
                "signal_color": color,
                "interpretation": _professional_metric_interpretation(signal, current_value),
            }
        )
    return cards


def _build_professional_evolution_sections(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> list[dict[str, object]]:
    history = _professional_jump_history(state, athlete)
    sections: list[dict[str, object]] = []
    for spec in PROFESSIONAL_PDF_METRICS:
        value_col = _professional_metric_value_col(history, spec)
        points: list[dict[str, object]] = []
        if not history.empty and value_col in history.columns:
            metric_rows = history[["Date", value_col]].copy()
            metric_rows[value_col] = pd.to_numeric(metric_rows[value_col], errors="coerce")
            metric_rows = metric_rows.dropna(subset=["Date", value_col]).sort_values("Date")
            points = [
                {
                    "label": pd.Timestamp(row["Date"]).strftime("%d/%m"),
                    "date": row["Date"],
                    "value": float(row[value_col]),
                }
                for _, row in metric_rows.iterrows()
            ]

        delta_text = PDF_MISSING_TEXT
        threshold_text = PDF_MISSING_TEXT
        signal = PDF_MISSING_TEXT
        if len(points) >= 2:
            latest_date = points[-1]["date"]
            try:
                delta_df = compute_swc_delta(history, latest_date, variables=[value_col])
            except Exception:
                delta_df = pd.DataFrame()
            if not delta_df.empty:
                row = delta_df.iloc[0]
                current_value = _coerce_float(row.get("Valor_actual"))
                previous_value = _coerce_float(row.get("Valor_anterior"))
                delta_text = _professional_delta_text(current_value, previous_value, spec, value_col)
                threshold = _coerce_float(row.get("Threshold_abs"))
                method = safe_value(row.get("Threshold_method"), fallback="")
                if threshold is not None:
                    threshold_text = f"+/- {_format_professional_metric_value(threshold, spec, value_col)}"
                    if method:
                        threshold_text = f"{threshold_text} ({method})"
                signal = safe_value(row.get("Signal"))

        if len(points) < 2:
            state_label = "missing"
            message = "Faltan datos para mostrar la evolución de esta métrica."
        elif threshold_text == PDF_MISSING_TEXT:
            state_label = "partial"
            message = "Zona de ruido/CV/TE: Faltan datos"
        else:
            state_label = "available"
            message = ""

        sections.append(
            {
                "title": str(spec["title"]),
                "state": state_label,
                "points": points,
                "unit": _professional_metric_unit(spec, value_col),
                "delta": delta_text,
                "threshold": threshold_text,
                "signal": signal,
                "message": message,
                "what": "Evolución entre evaluaciones de perfil físico separadas por ventanas de 6-8 semanas.",
                "meaning": f"Cambio vs evaluación previa: {delta_text}. Zona de ruido/CV/TE: {threshold_text}.",
                "decision": "Usar la dirección del cambio para ajustar prioridades del siguiente bloque, no como readiness semanal.",
            }
        )
    return sections


def _build_professional_quadrant_sections(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> list[dict[str, object]]:
    data = _professional_latest_team_jump_rows(state)
    specs = [
        {
            "title": "Cuadrante fuerza relativa vs salida vertical",
            "x_cols": ("CMJ_Z", "Jump_Momentum_Z"),
            "x_label": "CMJ z",
            "y_col": "IMTP_relPF_Z",
            "y_label": "IMTP relPF z",
            "what": "Cruza salida vertical con fuerza isometrica relativa.",
            "meaning": "Arriba/derecha sugiere perfil fuerte y expresivo; abajo/izquierda marca deficit global.",
            "decision": "Priorizar fuerza base, potencia o transferencia según el cuadrante del atleta.",
        },
        {
            "title": "Cuadrante reactividad rapida vs fuerza concentrica",
            "x_cols": ("DJ_RSI_Z", "DRI_Z"),
            "x_label": "DJ RSI z",
            "y_col": "SJ_Z",
            "y_label": "SJ z",
            "what": "Cruza RSI de drop jump con salida concentrica en SJ.",
            "meaning": "Distingue si el limite viene mas por reactividad rapida o por capacidad concentrica.",
            "decision": "Orientar el bloque hacia fuerza/propulsión, stiffness/reactividad o integración.",
        },
        {
            "title": "Cuadrante eficiencia SSC lenta vs CMJ",
            "x_cols": ("EUR_Z",),
            "x_label": "EUR z",
            "y_col": "CMJ_Z",
            "y_label": "CMJ z",
            "what": "Cruza el uso del contramovimiento con el rendimiento vertical actual.",
            "meaning": "Ayuda a separar atletas que saltan alto por capacidad general de quienes aprovechan mejor el SSC.",
            "decision": "Ajustar técnica, fuerza concéntrica o estrategia elástica según la ubicación.",
        },
    ]
    sections: list[dict[str, object]] = []
    for spec in specs:
        x_col = next((col for col in spec["x_cols"] if col in data.columns), "")
        y_col = str(spec["y_col"])
        points: list[dict[str, object]] = []
        selected = None
        if x_col and y_col in data.columns and "Athlete" in data.columns:
            plot_df = data[["Athlete", x_col, y_col]].copy()
            plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors="coerce")
            plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")
            plot_df = plot_df.dropna(subset=[x_col, y_col])
            target = str(athlete).strip().casefold()
            for _, row in plot_df.iterrows():
                is_selected = str(row["Athlete"]).strip().casefold() == target
                point = {
                    "x": float(row[x_col]),
                    "y": float(row[y_col]),
                    "selected": is_selected,
                }
                if is_selected:
                    selected = point
                points.append(point)
        state_label = "available" if selected is not None and len(points) > 1 else "partial" if selected is not None else "missing"
        sections.append(
            {
                **spec,
                "x_col": x_col,
                "points": points,
                "selected": selected,
                "state": state_label,
                "message": "" if selected is not None else "Faltan datos para ubicar al atleta en este cuadrante.",
            }
        )
    return sections


def _build_professional_training_context(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> dict[str, object]:
    rows: list[tuple[str, str]] = []
    completion = _professional_completion_snapshot(state, athlete)
    weekly_summaries = _report_weekly_summaries(state)
    weekly_load = _normalize_weekly_frame(weekly_summaries.get("weekly_load"))
    if not weekly_load.empty and "Athlete" in weekly_load.columns:
        weekly_load = weekly_load[_professional_athlete_mask(weekly_load["Athlete"], athlete)].copy()
    weekly_load = weekly_load.sort_values("week_start") if "week_start" in weekly_load.columns else weekly_load
    current_load = weekly_load.tail(1).copy()
    load_row = current_load.iloc[-1] if not current_load.empty else pd.Series(dtype=object)
    sessions_count = _coerce_float(load_row.get("sessions_count"))
    weekly_srpe = _coerce_float(load_row.get("weekly_sRPE"))
    sessions_text = f"{int(sessions_count)} sesión(es)" if sessions_count is not None else PDF_MISSING_TEXT
    if completion.get("numeric") is not None:
        adherence_text = safe_value(completion.get("value"))
    elif sessions_count is not None:
        adherence_text = f"Faltan datos. Sesiones registradas: {int(sessions_count)}."
    else:
        adherence_text = PDF_MISSING_TEXT
    rows.append(("Adherencia formal", adherence_text))
    rows.append(("Sesiones registradas", sessions_text))
    rows.append(("sRPE semanal", f"{weekly_srpe:.0f} UA" if weekly_srpe is not None else PDF_MISSING_TEXT))

    load_evolution = PDF_MISSING_TEXT
    if not weekly_load.empty and "weekly_sRPE" in weekly_load.columns:
        valid_load = weekly_load.copy()
        valid_load["weekly_sRPE"] = pd.to_numeric(valid_load["weekly_sRPE"], errors="coerce")
        valid_load = valid_load.dropna(subset=["weekly_sRPE"]).sort_values("week_start" if "week_start" in valid_load.columns else "weekly_sRPE")
        if len(valid_load) >= 2:
            current = float(valid_load.iloc[-1]["weekly_sRPE"])
            previous = float(valid_load.iloc[-2]["weekly_sRPE"])
            delta = current - previous
            pct = (delta / previous * 100) if previous else None
            load_evolution = f"{delta:+.0f} UA vs semana previa"
            if pct is not None:
                load_evolution = f"{load_evolution} ({pct:+.1f}%)"
    rows.append(("Evolucion de carga", load_evolution))

    exercises_text = PDF_MISSING_TEXT
    prepared = prepare_raw_workouts_df(state.get("raw_df"))
    if prepared is not None and not prepared.empty and "Athlete" in prepared.columns:
        athlete_df = prepared[_professional_athlete_mask(prepared["Athlete"], athlete)].copy()
        if not athlete_df.empty:
            invalid = athlete_df.get("is_invalid", pd.Series(False, index=athlete_df.index)).fillna(False)
            untagged = athlete_df.get("is_untagged", pd.Series(False, index=athlete_df.index)).fillna(False)
            athlete_df = athlete_df[~invalid & ~untagged]
            exercise_col = "Exercise" if "Exercise" in athlete_df.columns else "Exercise Name" if "Exercise Name" in athlete_df.columns else None
            if exercise_col and not athlete_df.empty:
                top_exercises = athlete_df[exercise_col].dropna().astype(str).str.strip()
                top_exercises = top_exercises[top_exercises != ""].value_counts().head(4)
                if not top_exercises.empty:
                    exercises_text = ", ".join(top_exercises.index.tolist())
    rows.append(("Ejercicios principales", exercises_text))

    available_count = sum(value != PDF_MISSING_TEXT for _, value in rows)
    has_training = any(
        [
            completion.get("numeric") is not None,
            sessions_count is not None,
            weekly_srpe is not None,
            exercises_text != PDF_MISSING_TEXT,
        ]
    )
    state_label = "available" if available_count == len(rows) else "partial" if available_count else "missing"
    return {
        "state": state_label if has_training else "missing",
        "rows": rows,
        "message": "" if has_training else "Faltan datos de entrenamiento para este período.",
        "what": "Resumen del bloque de entrenamiento visible para contextualizar el perfil físico.",
        "meaning": "Ayuda a separar cambios por adaptación real de cambios explicados por exposición, asistencia o carga.",
        "decision": "Ajustar la siguiente progresión según adherencia, sesiones cumplidas y ejercicios dominantes.",
    }


def _build_professional_internal_load_context(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
) -> dict[str, object]:
    rpe_df = state.get("rpe_df")
    daily_points: list[dict[str, object]] = []
    if rpe_df is not None and not rpe_df.empty and {"Athlete", "Date", "sRPE"}.issubset(rpe_df.columns):
        data = rpe_df.copy()
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
        data["sRPE"] = pd.to_numeric(data["sRPE"], errors="coerce")
        data = data.dropna(subset=["Athlete", "Date", "sRPE"])
        data = data[_professional_athlete_mask(data["Athlete"], athlete)]
        data = data[data["sRPE"] > 0].sort_values("Date")
        if not data.empty:
            latest_date = data["Date"].max()
            week_start = latest_date - pd.Timedelta(days=int(latest_date.weekday()))
            week_df = data[(data["Date"] >= week_start) & (data["Date"] <= week_start + pd.Timedelta(days=6))]
            daily_sum = week_df.groupby("Date", as_index=False)["sRPE"].sum()
            daily_lookup = {
                pd.Timestamp(row["Date"]).normalize(): float(row["sRPE"])
                for _, row in daily_sum.iterrows()
            }
            daily_points = [
                {
                    "label": (week_start + pd.Timedelta(days=day)).strftime("%d/%m"),
                    "value": daily_lookup.get(week_start + pd.Timedelta(days=day), 0.0),
                }
                for day in range(7)
            ]
            sessions_registered = int(len(week_df))
            days_with_data = int(week_df["Date"].nunique())
        else:
            sessions_registered = 0
            days_with_data = 0
    else:
        sessions_registered = 0
        days_with_data = 0

    weekly_summaries = _report_weekly_summaries(state)
    weekly_load = _normalize_weekly_frame(weekly_summaries.get("weekly_load"))
    weekly_points: list[dict[str, object]] = []
    if not weekly_load.empty and {"Athlete", "week_start", "weekly_sRPE"}.issubset(weekly_load.columns):
        weekly_load = weekly_load[_professional_athlete_mask(weekly_load["Athlete"], athlete)].copy()
        weekly_load["weekly_sRPE"] = pd.to_numeric(weekly_load["weekly_sRPE"], errors="coerce")
        weekly_load = weekly_load.dropna(subset=["week_start", "weekly_sRPE"]).sort_values("week_start").tail(16)
        if not weekly_load.empty:
            weekly_load["EMA6"] = weekly_load["weekly_sRPE"].ewm(span=6, adjust=False).mean()
            eval_weeks = set()
            jump_history = _professional_jump_history(state, athlete)
            if not jump_history.empty and "Date" in jump_history.columns:
                eval_dates = pd.to_datetime(jump_history["Date"], errors="coerce").dropna()
                eval_weeks = {
                    (pd.Timestamp(value).normalize() - pd.Timedelta(days=int(pd.Timestamp(value).weekday())))
                    for value in eval_dates.tolist()
                }
            weekly_points = [
                {
                    "label": pd.Timestamp(row["week_start"]).strftime("%d/%m"),
                    "week_start": pd.Timestamp(row["week_start"]).normalize(),
                    "value": float(row["weekly_sRPE"]),
                    "ema": float(row["EMA6"]),
                    "sessions": _coerce_float(row.get("sessions_count")),
                    "evaluation": pd.Timestamp(row["week_start"]).normalize() in eval_weeks,
                }
                for _, row in weekly_load.iterrows()
            ]

    has_daily = len(daily_points) > 0
    has_weekly = len(weekly_points) >= 2
    total_last_week = sum(float(point.get("value") or 0) for point in daily_points) if daily_points else None
    weekly_change = None
    weekly_change_pct = None
    if len(weekly_points) >= 2:
        current_week_value = _coerce_float(weekly_points[-1].get("value"))
        previous_week_value = _coerce_float(weekly_points[-2].get("value"))
        if current_week_value is not None and previous_week_value is not None:
            weekly_change = current_week_value - previous_week_value
            if previous_week_value:
                weekly_change_pct = (weekly_change / previous_week_value) * 100
    missing_parts = []
    if not has_daily:
        missing_parts.append("sRPE última semana")
    if not has_weekly:
        missing_parts.append("sRPE semanal + EMA 6 semanas")
    state_label = "available" if has_daily and has_weekly else "partial" if has_daily or has_weekly else "missing"
    return {
        "state": state_label,
        "daily_points": daily_points,
        "weekly_points": weekly_points,
        "message": "" if has_daily or has_weekly else "Faltan datos de carga interna para este período.",
        "missing_parts": missing_parts,
        "last_week_total": total_last_week,
        "sessions_registered": sessions_registered,
        "days_without_data": max(0, 7 - days_with_data) if has_daily else None,
        "weekly_change": weekly_change,
        "weekly_change_pct": weekly_change_pct,
        "daily_explanation": {
            "what": "sRPE diario o por sesión de la última semana útil.",
            "meaning": "Contexto agudo de carga interna percibida y duración acumulada.",
            "decision": "Regular densidad inmediata si aparecen picos, días sin registro o acumulación brusca.",
        },
        "weekly_explanation": {
            "what": "Barras de sRPE semanal de las últimas 16 semanas con línea EMA de 6 semanas.",
            "meaning": "Permite observar tendencia del bloque, acumulaciones, descargas o aumentos bruscos.",
            "decision": "Cruzar la tendencia con wellness, dolor, adherencia y calendario deportivo.",
        },
    }


def _professional_metric_display_groups(cards: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[str]]:
    available = [card for card in cards if card.get("state") != "missing"]
    missing = [str(card.get("title")) for card in cards if card.get("state") == "missing"]
    return available, missing


def _professional_assessment_date_count(state: dict[str, pd.DataFrame | None], athlete: str) -> int:
    history = _professional_jump_history(state, athlete)
    if history.empty or "Date" not in history.columns:
        return 0
    return int(pd.to_datetime(history["Date"], errors="coerce").dropna().dt.normalize().nunique())


def _professional_quadrants_ready(sections: list[dict[str, object]]) -> bool:
    return len(sections) >= 3 and all(section.get("selected") is not None for section in sections[:3])


def _professional_status_label(state_label: object) -> str:
    clean = str(state_label or "").strip().lower()
    if clean == "available":
        return "Disponible"
    if clean == "partial":
        return "Parcial"
    return "Faltan datos"


def _professional_infer_response_scale(values: pd.Series | list[object]) -> str:
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if numeric.empty:
        return "Escala no definida"
    max_value = float(numeric.max())
    min_value = float(numeric.min())
    if min_value >= 0 and max_value <= 5:
        return "/5"
    if min_value >= 0 and max_value <= 10:
        return "/10"
    return "Escala no definida"


def _professional_wellness_scales(frame: pd.DataFrame) -> dict[str, str]:
    return {
        "sleep": "h",
        "stress": _professional_infer_response_scale(frame["Estres"]) if "Estres" in frame.columns else "Escala no definida",
        "pain": _professional_infer_response_scale(frame["Dolor"]) if "Dolor" in frame.columns else "Escala no definida",
        "score": "escala no definida",
    }


def _professional_wellness_context(state: dict[str, pd.DataFrame | None], athlete: str) -> dict[str, object]:
    wdf = state.get("wellness_df")
    if wdf is None or wdf.empty or "Athlete" not in wdf.columns:
        return {
            "state": "missing",
            "rows": 0,
            "latest": PDF_MISSING_TEXT,
            "daily_points": [],
            "weekly_points": [],
            "last_week_summary": {},
            "scales": {"sleep": "h", "stress": "Escala no definida", "pain": "Escala no definida", "score": "escala no definida"},
            "message": "Faltan datos de wellness para este período.",
        }
    result = wdf.copy()
    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()
    result = result[_professional_athlete_mask(result["Athlete"], athlete)]
    numeric_cols = ["Sueno_hs", "Estres", "Dolor", "Wellness_Score"]
    for column in numeric_cols:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    if result.empty:
        return {
            "state": "missing",
            "rows": 0,
            "latest": PDF_MISSING_TEXT,
            "daily_points": [],
            "weekly_points": [],
            "last_week_summary": {},
            "scales": {"sleep": "h", "stress": "Escala no definida", "pain": "Escala no definida", "score": "escala no definida"},
            "message": "Faltan datos de wellness para este período.",
        }
    rows_count = int(len(result))
    scales = _professional_wellness_scales(result)
    latest = PDF_MISSING_TEXT
    if "Date" in result.columns and result["Date"].notna().any():
        latest = result["Date"].max().strftime("%d/%m/%Y")

    daily_points: list[dict[str, object]] = []
    last_week_summary: dict[str, object] = {}
    if "Date" in result.columns and result["Date"].notna().any():
        latest_date = result["Date"].max()
        week_start = latest_date - pd.Timedelta(days=int(latest_date.weekday()))
        week_df = result[(result["Date"] >= week_start) & (result["Date"] <= week_start + pd.Timedelta(days=6))].copy()
        for day in range(7):
            date = week_start + pd.Timedelta(days=day)
            day_df = week_df[week_df["Date"].eq(date)]
            point = {"label": date.strftime("%d/%m")}
            for source_col, output_col in [
                ("Sueno_hs", "sleep"),
                ("Estres", "stress"),
                ("Dolor", "pain"),
                ("Wellness_Score", "score"),
            ]:
                point[output_col] = (
                    float(day_df[source_col].mean())
                    if source_col in day_df.columns and day_df[source_col].notna().any()
                    else None
                )
            daily_points.append(point)
        for source_col, output_col in [
            ("Sueno_hs", "sleep_mean"),
            ("Estres", "stress_mean"),
            ("Dolor", "pain_mean"),
            ("Wellness_Score", "score_mean"),
        ]:
            last_week_summary[output_col] = (
                float(week_df[source_col].mean())
                if source_col in week_df.columns and week_df[source_col].notna().any()
                else None
            )
        last_week_summary["days"] = int(week_df["Date"].nunique()) if not week_df.empty else 0

    weekly_summaries = _report_weekly_summaries(state)
    weekly_wellness = _normalize_weekly_frame(weekly_summaries.get("weekly_wellness"))
    weekly_points: list[dict[str, object]] = []
    if not weekly_wellness.empty and {"Athlete", "week_start"}.issubset(weekly_wellness.columns):
        weekly_wellness = weekly_wellness[_professional_athlete_mask(weekly_wellness["Athlete"], athlete)].copy()
        for column in ["Sueno_mean", "Estres_mean", "Dolor_mean", "Wellness_mean"]:
            if column in weekly_wellness.columns:
                weekly_wellness[column] = pd.to_numeric(weekly_wellness[column], errors="coerce")
        weekly_wellness = weekly_wellness.dropna(subset=["week_start"]).sort_values("week_start").tail(16)
        weekly_points = [
            {
                "label": pd.Timestamp(row["week_start"]).strftime("%d/%m"),
                "week_start": pd.Timestamp(row["week_start"]).normalize(),
                "sleep": _coerce_float(row.get("Sueno_mean")),
                "stress": _coerce_float(row.get("Estres_mean")),
                "pain": _coerce_float(row.get("Dolor_mean")),
                "score": _coerce_float(row.get("Wellness_mean")),
                "days": _coerce_float(row.get("wellness_days")),
            }
            for _, row in weekly_wellness.iterrows()
        ]

    has_any_metric = any(
        result[column].notna().any()
        for column in numeric_cols
        if column in result.columns
    )
    missing_variables = [
        label
        for column, label in [
            ("Sueno_hs", "sueño"),
            ("Estres", "estrés"),
            ("Dolor", "dolor"),
            ("Wellness_Score", "wellness score"),
        ]
        if column not in result.columns or not result[column].notna().any()
    ]
    if not has_any_metric:
        state_label = "missing"
    elif rows_count >= 3 and not missing_variables:
        state_label = "available"
    else:
        state_label = "partial"
    return {
        "state": state_label,
        "rows": rows_count,
        "latest": latest,
        "daily_points": daily_points,
        "weekly_points": weekly_points,
        "last_week_summary": last_week_summary,
        "missing_variables": missing_variables,
        "scales": scales,
        "message": "" if state_label != "missing" else "Faltan datos de wellness para este período.",
    }


def _professional_period_label(state: dict[str, pd.DataFrame | None], athlete: str) -> str:
    dates: list[pd.Timestamp] = []

    def add_dates(frame: pd.DataFrame | None, date_candidates: tuple[str, ...], *, athlete_col: str = "Athlete") -> None:
        if frame is None or frame.empty:
            return
        result = frame.copy()
        if athlete_col in result.columns:
            result = result[_professional_athlete_mask(result[athlete_col], athlete)]
        for column in date_candidates:
            if column not in result.columns:
                continue
            parsed = pd.to_datetime(result[column], errors="coerce").dropna()
            dates.extend(pd.Timestamp(value).normalize() for value in parsed.tolist())
            break

    add_dates(state.get("jump_df"), ("Date",))
    add_dates(state.get("rpe_df"), ("Date",))
    add_dates(state.get("wellness_df"), ("Date",))
    add_dates(state.get("completion_df"), ("Date",))
    add_dates(state.get("raw_df"), ("Assigned Date", "Date"))

    if not dates:
        return PDF_MISSING_TEXT
    start = min(dates)
    end = max(dates)
    if start == end:
        return start.strftime("%d/%m/%Y")
    return f"{start:%d/%m/%Y} - {end:%d/%m/%Y}"


def _build_professional_report_overview(
    state: dict[str, pd.DataFrame | None],
    athlete: str,
    cards: list[dict[str, object]],
    training_context: dict[str, object],
    internal_load: dict[str, object],
) -> dict[str, object]:
    available_cards, _ = _professional_metric_display_groups(cards)
    wellness = _professional_wellness_context(state, athlete)
    evaluation_state = "missing"
    if len(available_cards) == len(PROFESSIONAL_PDF_METRICS):
        evaluation_state = "available"
    elif available_cards:
        evaluation_state = "partial"

    if evaluation_state == "available":
        reading = "Perfil físico disponible con batería de evaluación útil para orientar prioridades del bloque."
        decision = "Usar las métricas, cuadrantes y carga interna para ajustar el siguiente bloque con criterio profesional."
    elif evaluation_state == "partial":
        reading = "Perfil físico parcial: hay señales útiles, pero algunas métricas limitan la interpretación completa."
        decision = "Tomar decisiones con las métricas disponibles y completar la batería faltante en la próxima evaluación."
    elif internal_load.get("state") != "missing" or training_context.get("state") != "missing":
        reading = "Sin perfil físico suficiente; el reporte se apoya en entrenamiento, carga interna y contexto del bloque."
        decision = "Completar una batería de evaluación y usar la carga disponible para regular el corto plazo."
    else:
        reading = "Información insuficiente para una lectura profesional completa."
        decision = "Cargar evaluaciones, entrenamiento y sRPE antes de tomar decisiones de bloque."

    return {
        "athlete": athlete,
        "date": f"{datetime.now():%d/%m/%Y}",
        "period": _professional_period_label(state, athlete),
        "statuses": {
            "Evaluaciones físicas": _professional_status_label(evaluation_state),
            "Entrenamiento": _professional_status_label(training_context.get("state")),
            "Carga interna": _professional_status_label(internal_load.get("state")),
            "Wellness": _professional_status_label(wellness.get("state")),
        },
        "reading": reading,
        "decision": decision,
    }


def _professional_trend_delta(points: list[dict[str, object]], key: str) -> float | None:
    valid = [_coerce_float(point.get(key)) for point in points]
    valid = [value for value in valid if value is not None]
    if len(valid) < 2:
        return None
    return float(valid[-1] - valid[-2])

def _build_professional_integrated_interpretation(
    internal_load: dict[str, object],
    wellness_context: dict[str, object],
) -> list[str]:
    lines: list[str] = []
    weekly_change_pct = _coerce_float(internal_load.get("weekly_change_pct"))
    weekly_change = _coerce_float(internal_load.get("weekly_change"))
    if weekly_change_pct is not None:
        direction = "aumentó" if weekly_change_pct > 0 else "disminuyó" if weekly_change_pct < 0 else "se mantuvo estable"
        lines.append(f"La carga interna semanal {direction} {weekly_change_pct:+.1f}% respecto a la semana previa.")
    elif weekly_change is not None:
        direction = "aumentó" if weekly_change > 0 else "disminuyó" if weekly_change < 0 else "se mantuvo estable"
        lines.append(f"La carga interna semanal {direction} {weekly_change:+.0f} UA respecto a la semana previa.")
    else:
        lines.append("Faltan datos para comparar la carga interna contra la semana previa.")

    weekly_wellness = wellness_context.get("weekly_points", [])
    sleep_delta = _professional_trend_delta(weekly_wellness, "sleep")
    stress_delta = _professional_trend_delta(weekly_wellness, "stress")
    pain_delta = _professional_trend_delta(weekly_wellness, "pain")
    score_delta = _professional_trend_delta(weekly_wellness, "score")
    summary = wellness_context.get("last_week_summary", {}) if isinstance(wellness_context.get("last_week_summary"), dict) else {}
    stress_mean = _coerce_float(summary.get("stress_mean"))
    pain_mean = _coerce_float(summary.get("pain_mean"))
    sleep_mean = _coerce_float(summary.get("sleep_mean"))
    scales = wellness_context.get("scales", {}) if isinstance(wellness_context.get("scales"), dict) else {}

    def high_context(value: float | None, scale: object) -> bool:
        if value is None:
            return False
        scale_text = str(scale or "")
        if scale_text == "/5":
            return value >= 4
        if scale_text == "/10":
            return value >= 7
        return False

    wellness_comments: list[str] = []
    if sleep_delta is not None and sleep_delta < -0.2:
        wellness_comments.append(f"El sueño cambió {sleep_delta:+.1f} h respecto a la semana previa; si baja, reduce margen de recuperación.")
    if stress_delta is not None and stress_delta > 0.2:
        wellness_comments.append(f"El estrés cambió {stress_delta:+.1f} respecto a la semana previa y puede sumar carga contextual al bloque.")
    if pain_delta is not None and pain_delta > 0.2:
        wellness_comments.append(f"El dolor cambió {pain_delta:+.1f} respecto a la semana previa; conviene controlar volumen, densidad y selección de ejercicios.")
    score_label = "wellness score" if str(scales.get("score", "")).lower().startswith("escala no definida") else "wellness"
    if score_delta is not None:
        magnitude = abs(score_delta)
        if abs(score_delta) <= 0.5:
            wellness_comments.append(f"El {score_label} cambió {score_delta:+.1f} puntos respecto a la semana previa y se mantiene relativamente estable.")
        elif score_delta < -0.5:
            wellness_comments.append(f"El {score_label} disminuyó {magnitude:.1f} puntos respecto a la semana previa.")
        else:
            wellness_comments.append(f"El {score_label} aumentó {magnitude:.1f} puntos respecto a la semana previa, señal compatible con buena tolerancia si el contexto acompaña.")
    if weekly_change_pct is not None and weekly_change_pct > 10 and high_context(stress_mean, scales.get("stress")):
        wellness_comments.append(
            f"El estrés promedio fue elevado ({stress_mean:.1f}{scales.get('stress', '')}), por lo que conviene progresar de manera conservadora y controlar volumen/densidad."
        )
    if pain_mean is not None and high_context(pain_mean, scales.get("pain")):
        wellness_comments.append(f"El dolor promedio fue elevado ({pain_mean:.1f}{scales.get('pain', '')}); revisar tolerancia antes de aumentar carga.")
    if sleep_mean is not None and sleep_mean < 6.5:
        wellness_comments.append(f"El sueño promedio fue bajo ({sleep_mean:.1f} h); priorizar recuperación antes de escalar volumen.")
    if not wellness_comments and wellness_context.get("state") == "missing":
        wellness_comments.append("Faltan datos de wellness para cruzar la carga interna con recuperación percibida.")
    elif not wellness_comments:
        wellness_comments.append("No aparece una señal dominante de wellness; interpretar junto con sueño, estrés, dolor y asistencia.")
    score_comment_idx = next((idx for idx, comment in enumerate(wellness_comments) if score_label in comment), None)
    stress_comment_idx = next((idx for idx, comment in enumerate(wellness_comments) if "estrés promedio fue elevado" in comment), None)
    if (
        weekly_change_pct is not None
        and weekly_change_pct > 10
        and score_comment_idx is not None
        and stress_comment_idx is not None
    ):
        lines.append(
            f"{wellness_comments[score_comment_idx]} {wellness_comments[stress_comment_idx]} Esto no implica necesariamente mala tolerancia, pero sí sugiere que la siguiente progresión debería priorizar control de volumen, densidad y calidad de ejecución antes que aumentar carga de forma agresiva."
        )
        lines.extend(
            comment
            for idx, comment in enumerate(wellness_comments)
            if idx not in {score_comment_idx, stress_comment_idx}
        )
    else:
        lines.extend(wellness_comments[:3])
    lines.append(
        "La carga interna no debe interpretarse sola. Su utilidad aumenta cuando se cruza con sueño, estrés, dolor, adherencia, calendario deportivo y criterio profesional."
    )
    return lines


def _build_professional_next_steps(has_evaluations: bool) -> list[str]:
    if not has_evaluations:
        return [
            "Completar batería de evaluación: CMJ, SJ, DJ/RSI e IMTP.",
            "Mantener registro de sRPE y wellness durante las próximas semanas.",
            "Usar la próxima evaluación como línea base del perfil físico.",
            "No interpretar carga interna como perfil físico.",
        ]
    return [
        "Usar perfil físico para orientar el próximo bloque.",
        "Usar carga interna y wellness para regular el corto plazo.",
        "Repetir evaluación en 6-8 semanas.",
    ]


def _resolve_brand_asset_path(kind: str = "wordmark") -> Path | None:
    patterns = {
        "wordmark": [
            "threshold_logo_horizontal.*",
            "threshold_wordmark.*",
            "threshold-wordmark.*",
            "threshold-horizontal.*",
            "wordmark.*",
            "Untitled-2.*",
            "untitled-2.*",
        ],
        "icon": [
            "threshold_isotipo.*",
            "threshold_icon.*",
            "threshold-isotype.*",
            "threshold-icon.*",
            "isotype.*",
            "Untitled-1.*",
            "untitled-1.*",
        ],
    }
    for pattern in patterns.get(kind, []):
        matches = sorted(BRAND_ASSET_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


def _generate_professional_profile_pdf_reportlab(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
) -> bytes | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from xml.sax.saxutils import escape
    except Exception:
        return None

    palette = {
        "bg": colors.HexColor("#F4F6F8"),
        "card": colors.HexColor("#FEFEFE"),
        "navy": colors.HexColor("#0D3C5E"),
        "steel": colors.HexColor("#134263"),
        "ink": colors.HexColor("#221F20"),
        "muted": colors.HexColor("#708C9F"),
        "gray": colors.HexColor("#5A595B"),
        "line": colors.HexColor("#D8DEE4"),
        "green": colors.HexColor("#2F6B52"),
        "yellow": colors.HexColor("#C4A464"),
        "orange": colors.HexColor("#B87445"),
        "red": colors.HexColor("#B56B73"),
    }

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ProfTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=palette["navy"],
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProfSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=palette["navy"],
            spaceBefore=5,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProfBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=palette["ink"],
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProfMuted",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=palette["gray"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProfCardTitle",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=palette["navy"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ProfCardValue",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=palette["ink"],
            spaceAfter=5,
        )
    )

    def _p(text: object, style_name: str = "ProfBody") -> Paragraph:
        safe = escape(_ascii_text(safe_value(text, fallback=""))).replace("\n", "<br/>")
        return Paragraph(safe, styles[style_name])

    def _box(flowables: list[object], *, background=None, padding: int = 8) -> Table:
        table = Table([[flowables]], colWidths=[174 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), background or palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), padding),
                    ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _missing_box(message: str) -> Table:
        return _box([_p(message, "ProfBody"), _p("Faltan datos para generar una interpretación confiable.", "ProfMuted")])

    def _collapsed_box(message: str) -> Table:
        return _box([_p(line, "ProfBody") for line in str(message).splitlines() if line.strip()])

    def _overview_table(overview: dict[str, object]) -> Table:
        statuses = overview.get("statuses", {})
        data = [
            [_p("Atleta", "ProfCardTitle"), _p(overview.get("athlete", PDF_MISSING_TEXT), "ProfBody")],
            [_p("Fecha del reporte", "ProfCardTitle"), _p(overview.get("date", PDF_MISSING_TEXT), "ProfBody")],
            [_p("Período analizado", "ProfCardTitle"), _p(overview.get("period", PDF_MISSING_TEXT), "ProfBody")],
        ]
        for label, value in statuses.items():
            data.append([_p(label, "ProfCardTitle"), _p(value, "ProfBody")])
        data.extend(
            [
                [_p("Lectura principal", "ProfCardTitle"), _p(overview.get("reading", PDF_MISSING_TEXT), "ProfBody")],
                [_p("Decisión sugerida", "ProfCardTitle"), _p(overview.get("decision", PDF_MISSING_TEXT), "ProfBody")],
            ]
        )
        table = Table(data, colWidths=[54 * mm, 120 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _metric_cards_table(cards: list[dict[str, object]]) -> Table:
        rows: list[list[object]] = []
        row: list[object] = []
        for idx, card in enumerate(cards, start=1):
            color = colors.HexColor(str(card.get("signal_color", "#708C9F")))
            cell_flow = [
                _p(card.get("title", "-"), "ProfCardTitle"),
                _p(card.get("value", PDF_MISSING_TEXT), "ProfCardValue"),
                _p(f"Delta vs última: {card.get('delta', PDF_MISSING_TEXT)}", "ProfMuted"),
                _p(f"Z-score: {card.get('z_score', PDF_MISSING_TEXT)}", "ProfMuted"),
                _p(f"Mejor valor historico: {card.get('best', PDF_MISSING_TEXT)}", "ProfMuted"),
                _p(f"Semaforo: {card.get('signal', PDF_MISSING_TEXT)}", "ProfMuted"),
                _p(card.get("interpretation", ""), "ProfBody"),
            ]
            cell = Table([[cell_flow]], colWidths=[84 * mm])
            cell.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                        ("LINEABOVE", (0, 0), (-1, 0), 4, color),
                        ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            row.append(cell)
            if idx % 2 == 0:
                rows.append(row)
                row = []
        if row:
            row.append("")
            rows.append(row)
        table = Table(rows, colWidths=[87 * mm, 87 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return table

    def _scale(value: float, min_value: float, max_value: float, start: float, length: float) -> float:
        if max_value == min_value:
            return start + (length / 2)
        return start + ((value - min_value) / (max_value - min_value) * length)

    def _line_chart(points: list[dict[str, object]], *, width_mm: float = 82, height_mm: float = 42, color=None) -> Drawing | None:
        values = [_coerce_float(point.get("value")) for point in points]
        values = [value for value in values if value is not None]
        if len(values) < 2:
            return None
        color = color or palette["steel"]
        width = width_mm * mm
        height = height_mm * mm
        left = 20
        bottom = 15
        plot_w = width - 30
        plot_h = height - 24
        min_v = min(values)
        max_v = max(values)
        if min_v == max_v:
            min_v -= 1
            max_v += 1
        drawing = Drawing(width, height)
        drawing.add(Rect(0, 0, width, height, fillColor=palette["card"], strokeColor=palette["line"], strokeWidth=0.5))
        drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=palette["line"], strokeWidth=0.7))
        drawing.add(Line(left, bottom, left, bottom + plot_h, strokeColor=palette["line"], strokeWidth=0.7))
        coords: list[float] = []
        valid_points = [point for point in points if _coerce_float(point.get("value")) is not None]
        for idx, point in enumerate(valid_points):
            value = float(_coerce_float(point.get("value")) or 0)
            x = left + (plot_w * idx / max(1, len(valid_points) - 1))
            y = _scale(value, min_v, max_v, bottom, plot_h)
            coords.extend([x, y])
        drawing.add(PolyLine(coords, strokeColor=color, strokeWidth=1.7))
        for idx, point in enumerate(valid_points):
            value = float(_coerce_float(point.get("value")) or 0)
            x = left + (plot_w * idx / max(1, len(valid_points) - 1))
            y = _scale(value, min_v, max_v, bottom, plot_h)
            drawing.add(Circle(x, y, 2.2, fillColor=color, strokeColor=colors.white, strokeWidth=0.4))
        drawing.add(String(left, 4, safe_value(valid_points[0].get("label"), ""), fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(String(left + plot_w - 20, 4, safe_value(valid_points[-1].get("label"), ""), fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(String(left + 2, bottom + plot_h + 3, f"{max_v:.1f}", fontSize=6.5, fillColor=palette["muted"]))
        return drawing

    def _bar_chart(
        points: list[dict[str, object]],
        *,
        width_mm: float = 82,
        height_mm: float = 42,
        title: str = "",
        y_unit: str = "UA",
        show_values: bool = True,
    ) -> Drawing | None:
        values = [_coerce_float(point.get("value")) for point in points]
        values = [value for value in values if value is not None]
        if not values:
            return None
        width = width_mm * mm
        height = height_mm * mm
        left = 20
        bottom = 15
        top_pad = 13 if title else 5
        plot_w = width - 32
        plot_h = height - bottom - top_pad
        max_v = max(values) if max(values) > 0 else 1
        drawing = Drawing(width, height)
        drawing.add(Rect(0, 0, width, height, fillColor=palette["card"], strokeColor=palette["line"], strokeWidth=0.5))
        drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=palette["line"], strokeWidth=0.7))
        drawing.add(Line(left, bottom, left, bottom + plot_h, strokeColor=palette["line"], strokeWidth=0.7))
        if title:
            drawing.add(String(left, height - 9, title, fontSize=7.5, fillColor=palette["navy"]))
        if y_unit:
            drawing.add(String(4, bottom + plot_h - 2, y_unit, fontSize=6.5, fillColor=palette["muted"]))
        bar_gap = 3
        bar_w = max(4, (plot_w - (bar_gap * max(0, len(points) - 1))) / max(1, len(points)))
        for idx, point in enumerate(points):
            value = _coerce_float(point.get("value"))
            if value is None:
                continue
            x = left + idx * (bar_w + bar_gap)
            bar_h = (value / max_v) * plot_h
            drawing.add(Rect(x, bottom, bar_w, bar_h, fillColor=palette["steel"], strokeColor=None))
            if show_values and value > 0:
                drawing.add(String(x, bottom + bar_h + 2, f"{value:.0f}", fontSize=5.5, fillColor=palette["gray"]))
            drawing.add(String(x, 4, safe_value(point.get("label"), ""), fontSize=6, fillColor=palette["gray"]))
        drawing.add(String(left + 2, bottom + plot_h + 3, f"{max_v:.0f}", fontSize=6.5, fillColor=palette["muted"]))
        return drawing

    def _weekly_ema_chart(points: list[dict[str, object]], *, width_mm: float = 174, height_mm: float = 55) -> Drawing | None:
        values = [_coerce_float(point.get("value")) for point in points]
        emas = [_coerce_float(point.get("ema")) for point in points]
        values = [value for value in values if value is not None]
        emas = [value for value in emas if value is not None]
        if len(values) < 2 or len(emas) < 2:
            return None
        width = width_mm * mm
        height = height_mm * mm
        left = 28
        bottom = 17
        plot_w = width - 46
        plot_h = height - 32
        max_v = max(values + emas)
        min_v = min([0] + values + emas)
        if min_v == max_v:
            max_v += 1
        drawing = Drawing(width, height)
        drawing.add(Rect(0, 0, width, height, fillColor=palette["card"], strokeColor=palette["line"], strokeWidth=0.5))
        drawing.add(String(left, height - 9, "sRPE semanal + EMA 6 semanas", fontSize=8, fillColor=palette["navy"]))
        drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=palette["line"], strokeWidth=0.7))
        drawing.add(Line(left, bottom, left, bottom + plot_h, strokeColor=palette["line"], strokeWidth=0.7))
        drawing.add(String(7, bottom + plot_h - 2, "UA", fontSize=6.5, fillColor=palette["muted"]))
        bar_gap = 4
        bar_w = max(5, (plot_w - (bar_gap * max(0, len(points) - 1))) / max(1, len(points)))
        ema_coords: list[float] = []
        for idx, point in enumerate(points):
            value = _coerce_float(point.get("value"))
            ema = _coerce_float(point.get("ema"))
            x = left + idx * (bar_w + bar_gap)
            if value is not None:
                bar_h = ((value - min_v) / (max_v - min_v)) * plot_h
                drawing.add(Rect(x, bottom, bar_w, bar_h, fillColor=colors.HexColor("#DCE5EA"), strokeColor=None))
                if idx == len(points) - 1:
                    drawing.add(String(x, bottom + bar_h + 2, f"{value:.0f}", fontSize=6, fillColor=palette["gray"]))
            if ema is not None:
                ema_x = x + (bar_w / 2)
                ema_y = _scale(ema, min_v, max_v, bottom, plot_h)
                ema_coords.extend([ema_x, ema_y])
        if len(ema_coords) >= 4:
            drawing.add(PolyLine(ema_coords, strokeColor=palette["navy"], strokeWidth=2.0))
        for idx, point in enumerate(points):
            if idx in {0, len(points) - 1}:
                x = left + idx * (bar_w + bar_gap)
                drawing.add(String(x, 4, safe_value(point.get("label"), ""), fontSize=6.5, fillColor=palette["gray"]))
            if point.get("evaluation"):
                x = left + idx * (bar_w + bar_gap) + (bar_w / 2)
                drawing.add(Line(x, bottom, x, bottom + plot_h, strokeColor=palette["orange"], strokeWidth=0.8))
                drawing.add(String(x + 2, bottom + plot_h - 8, "evaluación", fontSize=5.8, fillColor=palette["orange"]))
        drawing.add(String(left + 2, bottom + plot_h + 3, f"{max_v:.0f}", fontSize=6.5, fillColor=palette["muted"]))
        legend_y = height - 10
        legend_x = left + plot_w - 78
        drawing.add(Rect(legend_x, legend_y - 4, 7, 4, fillColor=colors.HexColor("#DCE5EA"), strokeColor=None))
        drawing.add(String(legend_x + 10, legend_y - 4, "sRPE semanal", fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(Line(legend_x + 50, legend_y - 2, legend_x + 62, legend_y - 2, strokeColor=palette["navy"], strokeWidth=1.4))
        drawing.add(String(legend_x + 65, legend_y - 4, "EMA 6", fontSize=6.5, fillColor=palette["gray"]))
        return drawing

    def _wellness_chart(points: list[dict[str, object]], *, width_mm: float = 82, height_mm: float = 42) -> Drawing | None:
        valid_values = [_coerce_float(point.get("score")) for point in points]
        valid_values = [value for value in valid_values if value is not None]
        if len(valid_values) < 2:
            return None
        width = width_mm * mm
        height = height_mm * mm
        left = 24
        bottom = 15
        plot_w = width - 36
        plot_h = height - 28
        min_v = min(valid_values)
        max_v = max(valid_values)
        if min_v == max_v:
            min_v -= 1
            max_v += 1
        drawing = Drawing(width, height)
        drawing.add(Rect(0, 0, width, height, fillColor=palette["card"], strokeColor=palette["line"], strokeWidth=0.5))
        drawing.add(String(left, height - 9, "Wellness score", fontSize=7.5, fillColor=palette["navy"]))
        drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=palette["line"], strokeWidth=0.7))
        drawing.add(Line(left, bottom, left, bottom + plot_h, strokeColor=palette["line"], strokeWidth=0.7))
        coords: list[float] = []
        valid_points = [point for point in points if _coerce_float(point.get("score")) is not None]
        for idx, point in enumerate(valid_points):
            value = float(_coerce_float(point.get("score")) or 0)
            x = left + (plot_w * idx / max(1, len(valid_points) - 1))
            y = _scale(value, min_v, max_v, bottom, plot_h)
            coords.extend([x, y])
        drawing.add(PolyLine(coords, strokeColor=palette["green"], strokeWidth=1.7))
        for idx, point in enumerate(valid_points):
            if idx not in {0, len(valid_points) - 1}:
                continue
            value = float(_coerce_float(point.get("score")) or 0)
            x = left + (plot_w * idx / max(1, len(valid_points) - 1))
            y = _scale(value, min_v, max_v, bottom, plot_h)
            drawing.add(Circle(x, y, 2.2, fillColor=palette["green"], strokeColor=colors.white, strokeWidth=0.4))
        drawing.add(String(left, 4, safe_value(valid_points[0].get("label"), ""), fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(String(left + plot_w - 20, 4, safe_value(valid_points[-1].get("label"), ""), fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(String(left + 2, bottom + plot_h + 3, f"{max_v:.1f}", fontSize=6.5, fillColor=palette["muted"]))
        drawing.add(String(left + plot_w - 62, bottom + plot_h + 3, "Wellness score", fontSize=6.5, fillColor=palette["gray"]))
        return drawing

    def _key_value_table(rows: list[tuple[str, str]]) -> Table:
        data = [[_p(label, "ProfCardTitle"), _p(value, "ProfBody")] for label, value in rows]
        table = Table(data, colWidths=[56 * mm, 118 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _mini_cards_table(rows: list[tuple[str, str]]) -> Table:
        cells: list[object] = []
        for label, value in rows:
            card = Table(
                [[[_p(label, "ProfCardTitle"), _p(value, "ProfBody")]]],
                colWidths=[84 * mm],
            )
            card.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                        ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            cells.append(card)
        table_rows = [cells[idx:idx + 2] for idx in range(0, len(cells), 2)]
        if table_rows and len(table_rows[-1]) == 1:
            table_rows[-1].append("")
        table = Table(table_rows, colWidths=[87 * mm, 87 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return table

    def _load_summary_rows(payload: dict[str, object]) -> list[tuple[str, str]]:
        change_pct = _coerce_float(payload.get("weekly_change_pct"))
        change = _coerce_float(payload.get("weekly_change"))
        if change_pct is not None:
            change_text = f"{change_pct:+.1f}%"
        elif change is not None:
            change_text = f"{change:+.0f} UA"
        else:
            change_text = PDF_MISSING_TEXT
        total = _coerce_float(payload.get("last_week_total"))
        return [
            ("Total semanal", f"{total:.0f} UA" if total is not None else PDF_MISSING_TEXT),
            ("Sesiones registradas", str(int(payload.get("sessions_registered") or 0)) if payload.get("sessions_registered") is not None else PDF_MISSING_TEXT),
            ("Días sin sesión registrada", str(int(payload.get("days_without_data"))) if payload.get("days_without_data") is not None else PDF_MISSING_TEXT),
            ("Cambio vs semana previa", change_text),
        ]

    def _wellness_summary_rows(payload: dict[str, object]) -> list[tuple[str, str]]:
        summary = payload.get("last_week_summary", {}) if isinstance(payload.get("last_week_summary"), dict) else {}
        scales = payload.get("scales", {}) if isinstance(payload.get("scales"), dict) else {}
        def fmt(value: object, digits: int = 1) -> str:
            numeric = _coerce_float(value)
            return f"{numeric:.{digits}f}" if numeric is not None else PDF_MISSING_TEXT
        def with_scale(value: object, key: str) -> str:
            rendered = fmt(value)
            if rendered == PDF_MISSING_TEXT:
                return rendered
            scale = str(scales.get(key, "Escala no definida"))
            if scale == "h":
                return f"{rendered} h"
            if scale.startswith("/"):
                return f"{rendered}{scale}"
            return f"{rendered} · {scale}"
        return [
            ("Sueño promedio", with_scale(summary.get("sleep_mean"), "sleep")),
            ("Estrés promedio", with_scale(summary.get("stress_mean"), "stress")),
            ("Dolor promedio", with_scale(summary.get("pain_mean"), "pain")),
            ("Wellness score", with_scale(summary.get("score_mean"), "score")),
            ("Días con registro", str(int(summary.get("days"))) if summary.get("days") is not None else PDF_MISSING_TEXT),
        ]

    def _quadrant_chart(section: dict[str, object], *, width_mm: float = 82, height_mm: float = 55) -> Drawing | None:
        if section.get("selected") is None:
            return None
        points = section.get("points", [])
        width = width_mm * mm
        height = height_mm * mm
        left = 25
        bottom = 18
        plot_w = width - 38
        plot_h = height - 30
        min_v = -2.5
        max_v = 2.5
        drawing = Drawing(width, height)
        drawing.add(Rect(0, 0, width, height, fillColor=palette["card"], strokeColor=palette["line"], strokeWidth=0.5))
        x0 = _scale(0, min_v, max_v, left, plot_w)
        y0 = _scale(0, min_v, max_v, bottom, plot_h)
        drawing.add(Line(left, y0, left + plot_w, y0, strokeColor=palette["line"], strokeWidth=0.8))
        drawing.add(Line(x0, bottom, x0, bottom + plot_h, strokeColor=palette["line"], strokeWidth=0.8))
        for point in points:
            x_value = max(min_v, min(max_v, float(point["x"])))
            y_value = max(min_v, min(max_v, float(point["y"])))
            x = _scale(x_value, min_v, max_v, left, plot_w)
            y = _scale(y_value, min_v, max_v, bottom, plot_h)
            if point.get("selected"):
                drawing.add(Circle(x, y, 4.2, fillColor=palette["navy"], strokeColor=colors.white, strokeWidth=0.8))
                drawing.add(String(min(x + 5, left + plot_w - 45), min(y + 5, bottom + plot_h - 8), report_athlete[:22], fontSize=7, fillColor=palette["navy"]))
            else:
                drawing.add(Circle(x, y, 2.4, fillColor=colors.HexColor("#B8C2C9"), strokeColor=None))
        drawing.add(String(left, 4, str(section.get("x_label", "")), fontSize=6.5, fillColor=palette["gray"]))
        drawing.add(String(2, bottom + plot_h - 5, str(section.get("y_label", ""))[:18], fontSize=6.5, fillColor=palette["gray"]))
        return drawing

    def _explanation_lines(payload: dict[str, object]) -> list[object]:
        if payload.get("state") == "missing":
            return [_p("Faltan datos para generar una interpretación confiable.", "ProfMuted")]
        return [
            _p(f"Qué estoy viendo: {payload.get('what', PDF_MISSING_TEXT)}", "ProfMuted"),
            _p(f"Qué significa: {payload.get('meaning', PDF_MISSING_TEXT)}", "ProfMuted"),
            _p(f"Qué decisión sugiere: {payload.get('decision', PDF_MISSING_TEXT)}", "ProfMuted"),
        ]

    def _chart_explanation_panel(chart: Drawing, title: str, payload: dict[str, object]) -> Table:
        return Table(
            [[chart, [_p(title, "ProfCardTitle")] + _explanation_lines(payload)]],
            colWidths=[86 * mm, 88 * mm],
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        )

    cards = _build_professional_metric_cards(state, report_athlete)
    evolution_sections = _build_professional_evolution_sections(state, report_athlete)
    quadrant_sections = _build_professional_quadrant_sections(state, report_athlete)
    training_context = _build_professional_training_context(state, report_athlete)
    internal_load = _build_professional_internal_load_context(state, report_athlete)
    wellness_context = _professional_wellness_context(state, report_athlete)
    overview = _build_professional_report_overview(state, report_athlete, cards, training_context, internal_load)
    available_cards, missing_metric_titles = _professional_metric_display_groups(cards)
    has_evaluations = bool(available_cards)
    integrated_lines = _build_professional_integrated_interpretation(internal_load, wellness_context)
    next_steps = _build_professional_next_steps(has_evaluations)

    def _append_metric_cards(target: list[object]) -> None:
        if not available_cards:
            target.append(_p("Evaluaciones físicas no disponibles", "ProfSection"))
            target.append(_collapsed_box(PROFESSIONAL_NO_EVALUATION_TEXT))
            return
        target.append(_p("Tarjetas de evaluación", "ProfSection"))
        target.append(_metric_cards_table(available_cards))
        if missing_metric_titles:
            target.append(Spacer(1, 3 * mm))
            target.append(_box([_p(f"Métricas no disponibles: {', '.join(missing_metric_titles)}.", "ProfMuted")]))

    def _append_evolution_section(target: list[object]) -> None:
        target.extend(
            [
                _p("Evolución del perfil físico", "ProfSection"),
                _p("Evolución entre fechas de evaluación. No interpretar como readiness semanal.", "ProfMuted"),
            ]
        )
        if _professional_assessment_date_count(state, report_athlete) < 2:
            target.append(_collapsed_box(PROFESSIONAL_NO_EVOLUTION_TEXT))
            return
        missing_evolution_titles: list[str] = []
        for section in evolution_sections:
            chart = _line_chart(section.get("points", []), color=palette["steel"])
            if chart is None:
                missing_evolution_titles.append(str(section.get("title", "Métrica")))
                continue
            target.append(_chart_explanation_panel(chart, str(section.get("title", "Métrica")), section))
            target.append(Spacer(1, 4 * mm))
        if missing_evolution_titles:
            target.append(_box([_p(f"Métricas sin evolución suficiente: {', '.join(missing_evolution_titles)}. Faltan datos.", "ProfMuted")]))

    def _append_quadrants_section(target: list[object]) -> None:
        target.append(_p("Cuadrantes de perfil físico", "ProfSection"))
        if not _professional_quadrants_ready(quadrant_sections):
            target.append(_collapsed_box(PROFESSIONAL_NO_QUADRANTS_TEXT))
            return
        for section in quadrant_sections[:3]:
            chart = _quadrant_chart(section)
            if chart is None:
                continue
            target.append(_chart_explanation_panel(chart, str(section.get("title", "Cuadrante")), section))
            target.append(Spacer(1, 4 * mm))

    def _append_training_section(target: list[object]) -> None:
        target.append(_p("Contexto de entrenamiento", "ProfSection"))
        if training_context["state"] == "missing":
            target.append(_collapsed_box("Faltan datos de entrenamiento para este período."))
            return
        target.append(_key_value_table([(str(label), str(value)) for label, value in training_context["rows"]]))
        target.append(Spacer(1, 3 * mm))
        target.append(_box(_explanation_lines(training_context), padding=6))

    def _append_internal_last_week(target: list[object], *, include_title: bool = True, compact: bool = False) -> None:
        if include_title:
            target.append(_p("Carga interna - última semana", "ProfSection"))
        if internal_load["state"] == "missing":
            target.append(_collapsed_box("Faltan datos de carga interna para este período."))
            return
        summary_rows = _load_summary_rows(internal_load)
        if compact:
            target.append(_box([_p(" | ".join(f"{label}: {value}" for label, value in summary_rows), "ProfMuted")], padding=5))
        else:
            target.append(_key_value_table(summary_rows))
        daily_chart = _bar_chart(
            internal_load.get("daily_points", []),
            height_mm=34 if compact else 42,
            title="sRPE diario",
            y_unit="UA",
        )
        if daily_chart is None:
            target.append(Spacer(1, 3 * mm))
            target.append(_collapsed_box("Faltan datos de carga interna de la última semana."))
            return
        target.append(Spacer(1, 2 * mm if compact else 3 * mm))
        target.append(
            _chart_explanation_panel(
                daily_chart,
                "sRPE diario",
                {"state": "available", **internal_load["daily_explanation"]},
            )
        )

    def _append_internal_16_weeks(target: list[object], *, include_title: bool = True, compact: bool = False) -> None:
        if include_title:
            target.append(_p("Carga interna - últimas 16 semanas", "ProfSection"))
        weekly_chart = _weekly_ema_chart(internal_load.get("weekly_points", []), height_mm=42 if compact else 55)
        if weekly_chart is None:
            target.append(_collapsed_box("Faltan datos para mostrar sRPE semanal + EMA 6 semanas."))
            return
        target.append(weekly_chart)
        total = _coerce_float(internal_load.get("last_week_total"))
        change_pct = _coerce_float(internal_load.get("weekly_change_pct"))
        summary = f"Total última semana: {total:.0f} UA." if total is not None else "Total última semana: Faltan datos."
        if change_pct is not None:
            summary = f"{summary} Cambio vs semana previa: {change_pct:+.1f}%."
        target.append(
            _box(
                [
                    _p(summary, "ProfMuted"),
                    _p(
                        "Permite observar tendencia de carga, acumulaciones, descargas o aumentos bruscos del bloque.",
                        "ProfMuted",
                    ),
                ],
                padding=5 if compact else 6,
            )
        )

    def _append_wellness_last_week(target: list[object], *, include_title: bool = True, compact: bool = False) -> None:
        if include_title:
            target.append(_p("Wellness - última semana", "ProfSection"))
        if wellness_context.get("state") == "missing":
            target.append(_collapsed_box("Faltan datos de wellness para este período."))
            return
        summary_rows = _wellness_summary_rows(wellness_context)
        target.append(_mini_cards_table(summary_rows))
        daily_chart = _wellness_chart(wellness_context.get("daily_points", []), height_mm=34 if compact else 42)
        if daily_chart is None:
            target.append(Spacer(1, 3 * mm))
            target.append(_collapsed_box("Faltan datos para mostrar tendencia diaria de wellness score."))
            return
        target.append(Spacer(1, 2 * mm if compact else 3 * mm))
        target.append(
            _chart_explanation_panel(
                daily_chart,
                "Wellness score",
                {
                    "state": wellness_context.get("state"),
                    "what": "Tendencia diaria del wellness score de la última semana registrada.",
                    "meaning": "Muestra recuperación percibida y carga contextual alrededor del entrenamiento sin mezclar escalas crudas.",
                    "decision": "Regular volumen, densidad o selección de ejercicios si empeoran sueño, estrés o dolor.",
                },
            )
        )

    def _append_wellness_16_weeks(target: list[object], *, include_title: bool = True, compact: bool = False) -> None:
        if include_title:
            target.append(_p("Wellness - últimas 16 semanas", "ProfSection"))
        if wellness_context.get("state") == "missing":
            target.append(_collapsed_box("Faltan datos de wellness para este período."))
            return
        weekly_chart = _wellness_chart(wellness_context.get("weekly_points", []), width_mm=174, height_mm=38 if compact else 46)
        if weekly_chart is None:
            target.append(_collapsed_box("Faltan datos para mostrar tendencia de wellness score de las últimas 16 semanas."))
            return
        target.append(weekly_chart)
        missing_variables = wellness_context.get("missing_variables") or []
        note = "Cruzar la tendencia del score con carga interna ayuda a distinguir tolerancia aparente de fatiga contextual sin mezclar escalas crudas."
        if missing_variables:
            note = f"{note} Variables no disponibles: {', '.join(map(str, missing_variables))}."
        target.append(_box([_p(note, "ProfMuted")], padding=5 if compact else 6))

    def _append_acute_interpretation(target: list[object]) -> None:
        target.append(_p("Interpretación aguda", "ProfSection"))
        lines: list[str] = []
        total = _coerce_float(internal_load.get("last_week_total"))
        weekly_change_pct = _coerce_float(internal_load.get("weekly_change_pct"))
        if total is not None:
            load_text = f"La carga interna de la última semana fue {total:.0f} UA."
            if weekly_change_pct is not None:
                load_text = f"{load_text} Cambió {weekly_change_pct:+.1f}% respecto a la semana previa."
            else:
                load_text = f"{load_text} No hay comparación suficiente contra la semana previa."
            lines.append(load_text)
        else:
            lines.append("Faltan datos para interpretar la carga interna aguda.")

        summary = wellness_context.get("last_week_summary", {}) if isinstance(wellness_context.get("last_week_summary"), dict) else {}
        scales = wellness_context.get("scales", {}) if isinstance(wellness_context.get("scales"), dict) else {}
        stress_mean = _coerce_float(summary.get("stress_mean"))
        pain_mean = _coerce_float(summary.get("pain_mean"))
        sleep_mean = _coerce_float(summary.get("sleep_mean"))
        if wellness_context.get("state") == "missing":
            lines.append("Faltan datos de wellness para cruzar la carga aguda con recuperación percibida.")
        else:
            details = []
            if sleep_mean is not None:
                details.append(f"sueño {sleep_mean:.1f} h")
            if stress_mean is not None:
                details.append(f"estrés {stress_mean:.1f}{scales.get('stress', '')}")
            if pain_mean is not None:
                details.append(f"dolor {pain_mean:.1f}{scales.get('pain', '')}")
            lines.append("Wellness última semana: " + (", ".join(details) if details else PDF_MISSING_TEXT) + ".")
        lines.append("Decisión sugerida: progresar con cautela si sube la carga y aparecen peor sueño, estrés elevado, dolor o caída de calidad de sesión.")
        target.append(_box([_p(" ".join(lines), "ProfMuted")], padding=5))

    def _append_integrated_interpretation(target: list[object], *, compact: bool = False) -> None:
        target.append(_p("Interpretación integrada", "ProfSection"))
        if compact:
            target.append(_box([_p(" ".join(integrated_lines), "ProfMuted")], padding=5))
            return
        target.append(_box([_p(line, "ProfBody") for line in integrated_lines], padding=6))

    def _append_next_steps(target: list[object], *, compact: bool = False) -> None:
        target.append(_p("Próximo paso recomendado", "ProfSection"))
        if compact:
            target.append(_box([_p(" ".join(f"{idx}. {line}" for idx, line in enumerate(next_steps, start=1)), "ProfMuted")], padding=5))
            return
        target.append(_box([_p(f"- {line}", "ProfBody") for line in next_steps], padding=6))

    def _append_limitations(target: list[object], *, compact: bool = False) -> None:
        target.append(_p("Limitaciones del reporte", "ProfSection"))
        if compact:
            target.append(
                _box(
                    [
                        _p(
                            "Las evaluaciones son perfilado físico cada 6-8 semanas y no deben interpretarse como readiness semanal. El sRPE es una estimación práctica de carga interna.",
                            "ProfMuted",
                        ),
                        _p(
                            "Las decisiones deben considerar contexto deportivo, dolor, wellness y criterio profesional. Si una sección muestra \"Faltan datos\", no había información suficiente para generar esa parte del análisis.",
                            "ProfMuted",
                        ),
                    ],
                    padding=5,
                )
            )
            return
        target.append(
            _box(
                [
                    _p("- Las evaluaciones son perfilado físico cada 6-8 semanas.", "ProfBody"),
                    _p("- No deben interpretarse como readiness semanal.", "ProfBody"),
                    _p("- El sRPE es una estimación práctica de carga interna.", "ProfBody"),
                    _p("- Las decisiones deben considerar contexto deportivo, dolor, wellness y criterio profesional.", "ProfBody"),
                    _p("- Si una sección muestra \"Faltan datos\", no había información suficiente para generar esa parte del análisis.", "ProfBody"),
                ],
                padding=6,
            )
        )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=14 * mm,
    )
    story: list[object] = []
    story.extend(
        [
            _p("Reporte profesional", "ProfMuted"),
            _p(report_athlete, "ProfTitle"),
            _p(f"Generado el {datetime.now():%d/%m/%Y %H:%M}", "ProfMuted"),
            _box(
                [
                    _p("Informe de perfil físico y toma de decisiones para profesional.", "ProfBody"),
                    _p(
                        "Las evaluaciones se tratan como perfilado físico cada 6-8 semanas; la carga interna y el contexto de entrenamiento ayudan a decidir el siguiente bloque.",
                        "ProfMuted",
                    ),
                ]
            ),
            Spacer(1, 6 * mm),
            _p("Resumen ejecutivo", "ProfSection"),
            _overview_table(overview),
            Spacer(1, 6 * mm),
        ]
    )

    _append_metric_cards(story)

    if not has_evaluations:
        story.append(PageBreak())
        _append_internal_last_week(story, compact=True)
        story.append(Spacer(1, 3 * mm))
        _append_wellness_last_week(story, compact=True)
        story.append(Spacer(1, 3 * mm))
        _append_acute_interpretation(story)
        story.append(PageBreak())
        _append_internal_16_weeks(story, compact=True)
        story.append(Spacer(1, 3 * mm))
        _append_wellness_16_weeks(story, compact=True)
        story.append(Spacer(1, 3 * mm))
        _append_integrated_interpretation(story, compact=True)
        _append_next_steps(story, compact=True)
        _append_limitations(story, compact=True)
    else:
        story.append(PageBreak())
        _append_evolution_section(story)
        story.append(PageBreak())
        _append_quadrants_section(story)
        story.append(PageBreak())
        _append_training_section(story)
        story.append(Spacer(1, 5 * mm))
        _append_internal_last_week(story)
        story.append(Spacer(1, 5 * mm))
        _append_wellness_last_week(story)
        story.append(PageBreak())
        _append_internal_16_weeks(story)
        story.append(Spacer(1, 5 * mm))
        _append_wellness_16_weeks(story)
        story.append(Spacer(1, 5 * mm))
        _append_integrated_interpretation(story)
        _append_next_steps(story)
        _append_limitations(story)

    try:
        doc.build(story)
    except Exception:
        return None
    return buffer.getvalue()


def _generate_visual_report_pdf_reportlab(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> bytes | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from xml.sax.saxutils import escape
    except Exception:
        return None

    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return None
    if audience == "profe" and effective_athlete != "Todos":
        professional_pdf = _generate_professional_profile_pdf_reportlab(state, effective_athlete)
        if professional_pdf:
            return professional_pdf

    summary_df = build_executive_summary_df(state, effective_athlete, audience)
    insights = generate_module_insights(state, effective_athlete, audience)
    blocks = _audience_blocks(state, effective_athlete, summary_df, insights, audience)
    charts = collect_report_plotly_figures(state, effective_athlete, audience)

    palette = {
        "bg": colors.HexColor("#F4F6F8"),
        "card": colors.HexColor("#FEFEFE"),
        "navy": colors.HexColor("#0D3C5E"),
        "steel": colors.HexColor("#134263"),
        "ink": colors.HexColor("#221F20"),
        "muted": colors.HexColor("#708C9F"),
        "gray": colors.HexColor("#5A595B"),
        "line": colors.HexColor("#D8DEE4"),
    }

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=23,
            leading=28,
            textColor=palette["navy"],
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=palette["navy"],
            spaceAfter=8,
            spaceBefore=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=palette["ink"],
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportMuted",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=palette["gray"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CardLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=palette["gray"],
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CardValue",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=palette["ink"],
        )
    )
    styles.add(
        ParagraphStyle(
            name="BlockTitle",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=palette["ink"],
            spaceAfter=5,
        )
    )

    def _p(text: object, style_name: str = "ReportBody") -> Paragraph:
        safe = escape(_ascii_text(text) or "").replace("\n", "<br/>")
        return Paragraph(safe, styles[style_name])

    def _fit_image(path: Path, max_width_mm: float, max_height_mm: float) -> Image | None:
        try:
            reader = ImageReader(str(path))
            width, height = reader.getSize()
        except Exception:
            return None
        max_width = max_width_mm * mm
        max_height = max_height_mm * mm
        scale = min(max_width / width, max_height / height)
        return Image(str(path), width=width * scale, height=height * scale)

    def _metric_cards_table(cards: list[tuple[str, str, str]]) -> Table:
        rows = []
        row: list[object] = []
        for idx, (label, value, _) in enumerate(cards, start=1):
            cell = Table(
                [[_p(label, "CardLabel")], [_p(value, "CardValue")]],
                colWidths=[54 * mm],
            )
            cell.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                        ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            row.append(cell)
            if idx % 3 == 0:
                rows.append(row)
                row = []
        if row:
            while len(row) < 3:
                row.append("")
            rows.append(row)
        table = Table(rows, colWidths=[56 * mm, 56 * mm, 56 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return table

    def _summary_meta_table() -> Table:
        readiness = _readiness_payload(_report_quality_report(state))
        weekly_summaries = _report_weekly_summaries(state)
        current_team = _current_week_slice(weekly_summaries.get("weekly_team"))
        current_load = _current_week_slice(weekly_summaries.get("weekly_load"), effective_athlete)
        completion_value = _focus_completion_value(state, effective_athlete)
        completion_text = _display_metric(completion_value, digits=1, suffix="%") if completion_value is not None else "Sin dato"
        adherence_label = "Adherencia del atleta" if effective_athlete != "Todos" else "Adherencia promedio"
        if effective_athlete == "Todos":
            current_row = current_team.tail(1).iloc[0] if not current_team.empty else pd.Series(dtype=object)
            athletes_active = _coerce_float(current_row.get("athletes_active"))
            week_value = f"{int(athletes_active)} activos" if athletes_active is not None else "Sin dato"
        else:
            current_row = current_load.tail(1).iloc[0] if not current_load.empty else pd.Series(dtype=object)
            sessions_count = _coerce_float(current_row.get("sessions_count"))
            week_value = f"{int(sessions_count)} sesiones" if sessions_count is not None else "Sin dato"
        data = [
            [
                _p(f"Semana actual\n{week_value}", "ReportMuted"),
                _p(f"Readiness\n{readiness['label']}", "ReportMuted"),
                _p(f"{adherence_label}\n{completion_text}", "ReportMuted"),
            ]
        ]
        table = Table(data, colWidths=[56 * mm, 56 * mm, 56 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def _metric_table(rows: list[tuple[str, str]], *, title: str) -> list[object]:
        data = [[_p(label, "CardLabel"), _p(value, "ReportBody")] for label, value in rows]
        table = Table(data, colWidths=[58 * mm, 112 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return [_p(title, "ReportSection"), table]

    def _snapshot_table() -> Table | None:
        if summary_df.empty:
            return None
        display_df = summary_df.copy().fillna("-")
        keep_cols = [col for col in ["Atleta", "ACWR EWMA", "Zona", "Wellness 3d", "CMJ cm", "DRI", "IMTP N", "Perfil NM"] if col in display_df.columns]
        if not keep_cols:
            return None
        display_df = display_df[keep_cols]
        display_df = display_df.rename(
            columns={
                "ACWR EWMA": "ACWR EWMA",
                "Wellness 3d": "Wellness",
                "CMJ cm": "CMJ",
                "IMTP N": "IMTP",
            }
        )
        data: list[list[object]] = [[_p(col, "CardLabel") for col in display_df.columns]]
        for _, row in display_df.iterrows():
            data.append([_p(_snapshot_value(col, row.get(col, "-")), "ReportBody") for col in display_df.columns])
        widths_map = {
            "Atleta": 38 * mm,
            "ACWR EWMA": 18 * mm,
            "Zona": 24 * mm,
            "Wellness": 24 * mm,
            "CMJ": 18 * mm,
            "DRI": 18 * mm,
            "IMTP": 22 * mm,
            "Perfil NM": 36 * mm,
        }
        col_widths = [widths_map.get(col, 24 * mm) for col in display_df.columns]
        table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                    ("BACKGROUND", (0, 0), (-1, 0), palette["navy"]),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("BACKGROUND", (0, 1), (-1, -1), palette["card"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def _chart_story(chart_payload: dict[str, object]) -> list[object]:
        image_bytes = export_plotly_figure_png(chart_payload.get("figure"))
        if not image_bytes:
            return []
        image = Image(BytesIO(image_bytes), width=175 * mm, height=102 * mm)
        image.hAlign = "LEFT"
        return [
            _p(chart_payload.get("title", "Gráfico"), "ReportSection"),
            image,
        ]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=14 * mm,
    )

    story: list[object] = []
    wordmark = _resolve_brand_asset_path("wordmark")
    icon = _resolve_brand_asset_path("icon")
    wordmark_logo = _fit_image(wordmark, 150, 28) if wordmark is not None else None
    icon_logo = _fit_image(icon, 18, 18) if icon is not None else None
    if icon_logo is not None and wordmark_logo is not None:
        brand_table = Table(
            [[icon_logo, wordmark_logo]],
            colWidths=[22 * mm, 128 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )
        story.append(brand_table)
        story.append(Spacer(1, 8 * mm))
    elif wordmark_logo is not None:
        story.append(wordmark_logo)
        story.append(Spacer(1, 8 * mm))
    elif icon_logo is not None:
        story.append(icon_logo)
        story.append(Spacer(1, 8 * mm))

    subtitle = {
        "atleta": "Reporte individual para atleta",
        "profe": "Reporte técnico para profesional",
        "cliente": "Reporte de progreso",
    }[audience]
    target_name = effective_athlete if effective_athlete != "Todos" else "Resumen general"
    story.extend(
        [
            _p(subtitle, "ReportMuted"),
            _p(target_name, "ReportTitle"),
            _p(f"Generado el {datetime.now():%d/%m/%Y %H:%M} | Ventana visible: últimas 6 semanas", "ReportMuted"),
            Spacer(1, 4 * mm),
            Table(
                [[_p(insights.get("report", {}).get("summary", "Reporte listo para revisión."), "ReportBody")]],
                colWidths=[174 * mm],
                style=TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                        ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                ),
            ),
            Spacer(1, 6 * mm),
            _p("Focos prioritarios", "ReportSection"),
        ]
    )
    for focus in insights.get("report", {}).get("focuses", []):
        story.append(_p(f"- {focus}", "ReportBody"))
    story.append(PageBreak())

    if not summary_df.empty:
        focus_row = summary_df.iloc[0]
        story.extend(
            [
                _p("Resumen ejecutivo", "ReportSection"),
                _p(
                    {
                        "atleta": "Lectura cuasi técnica de tu estado actual, perfil y prioridades inmediatas.",
                        "profe": "Última foto integrada para revisar disponibilidad, perfil y toma de decisiones.",
                        "cliente": "Lectura clara del estado actual y del progreso reciente.",
                    }[audience],
                    "ReportMuted",
                ),
                _metric_cards_table(_audience_dashboard_cards(state, focus_row, effective_athlete, audience)),
                Spacer(1, 5 * mm),
                _summary_meta_table(),
                Spacer(1, 5 * mm),
            ]
        )

        if effective_athlete != "Todos":
            story.extend(_metric_table(_audience_metric_rows(state, focus_row, effective_athlete, audience), title="Indicadores principales"))
        else:
            snapshot = _snapshot_table()
            if snapshot is not None:
                story.append(_p("Tabla ejecutiva integrada", "ReportSection"))
                story.append(snapshot)

    for chart in charts:
        chart_story = _chart_story(chart)
        if chart_story:
            story.append(PageBreak())
            story.extend(chart_story)

    if blocks:
        story.append(PageBreak())
        header = {
            "profe": "Interpretación y focos",
            "atleta": "Fortalezas y próximos pasos",
            "cliente": "Lectura simple y próximos pasos",
        }[audience]
        story.append(_p(header, "ReportSection"))
        for block in blocks:
            box_story = [
                _p(block.get("title", "Bloque"), "BlockTitle"),
                _p(block.get("summary", ""), "ReportBody"),
            ]
            for item in block.get("focuses", []):
                box_story.append(_p(f"- {item}", "ReportBody"))
            table = Table(
                [[box_story]],
                colWidths=[174 * mm],
                style=TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                        ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                ),
            )
            story.append(table)
            story.append(Spacer(1, 4 * mm))

    try:
        doc.build(story)
    except Exception:
        return None
    return buffer.getvalue()


def _build_pdf_document(page_contents: list[str]) -> bytes:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    font_objects = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    pages_object_num = 2
    first_dynamic_obj = 3 + len(font_objects)
    page_obj_nums = []
    content_obj_nums = []

    for idx in range(len(page_contents)):
        page_obj_nums.append(first_dynamic_obj + idx * 2)
        content_obj_nums.append(first_dynamic_obj + idx * 2 + 1)

    kids = " ".join(f"{obj} 0 R" for obj in page_obj_nums)
    objects.append(f"<< /Type /Pages /Count {len(page_contents)} /Kids [{kids}] >>".encode("ascii"))
    objects.extend(font_objects)

    for page_obj_num, content_obj_num, content in zip(page_obj_nums, content_obj_nums, page_contents):
        page_obj = (
            f"<< /Type /Page /Parent {pages_object_num} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {content_obj_num} 0 R >>"
        )
        objects.append(page_obj.encode("ascii"))
        content_bytes = content.encode("latin-1", "ignore")
        stream = b"<< /Length " + str(len(content_bytes)).encode("ascii") + b" >>\nstream\n" + content_bytes + b"\nendstream"
        objects.append(stream)

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
    return bytes(output)


def generate_visual_report_pdf(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> bytes | None:
    audience = normalize_report_audience(report_audience)
    effective_athlete = resolve_report_scope(state, report_athlete, audience)
    if effective_athlete is None:
        return None
    premium_pdf = _generate_visual_report_pdf_reportlab(state, effective_athlete, audience)
    if premium_pdf:
        return premium_pdf

    summary_df = build_executive_summary_df(state, effective_athlete, audience)
    insights = generate_module_insights(state, effective_athlete, audience)

    page_contents = [_build_cover_page(effective_athlete, summary_df, insights, audience)]
    dashboard_page = _build_dashboard_page(state, effective_athlete, summary_df, audience)
    if dashboard_page:
        page_contents.append(dashboard_page)
    if audience == "profe" or effective_athlete == "Todos":
        page_contents.extend(_build_snapshot_pages(summary_df))
    else:
        metric_page = _build_metric_profile_page(state, effective_athlete, summary_df, audience)
        if metric_page:
            page_contents.append(metric_page)
    trend_page = _build_trend_page(state, effective_athlete, audience)
    if trend_page:
        page_contents.append(trend_page)
    page_contents.extend(_build_insight_pages(state, effective_athlete, summary_df, insights, audience))
    return _build_pdf_document(page_contents)
