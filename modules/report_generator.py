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


APP_ROOT = Path(__file__).resolve().parent.parent
BRAND_ASSET_DIR = APP_ROOT / "assets" / "brand"

REPORT_SHEET_ORDER = [
    "Reporte_Meta",
    "Resumen_Ejecutivo",
    "Interpretacion",
    "ACWR_sRPE",
    "Monotonia_Strain",
    "Wellness",
    "Evaluaciones_Saltos",
    "Maximos_Ejercicios",
    "Volumen_Sesion",
    "Completion_Rate",
]

DATASET_LABELS = {
    "rpe_df": "RPE + Tiempo",
    "wellness_df": "Wellness",
    "completion_df": "Completion",
    "rep_load_df": "Rep/Load",
    "raw_df": "Raw Workouts",
    "maxes_df": "Maxes",
    "jump_df": "Evaluaciones",
}

REPORT_AUDIENCE_OPTIONS = {
    "Atleta": "atleta",
    "Profe": "profe",
    "Cliente": "cliente",
}

REPORT_AUDIENCE_LABELS = {value: key for key, value in REPORT_AUDIENCE_OPTIONS.items()}


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


def collect_report_athletes(state: dict[str, pd.DataFrame | None]) -> list[str]:
    athletes: set[str] = set()
    for key in ["rpe_df", "jump_df", "maxes_df", "rep_load_df"]:
        frame = state.get(key)
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        athletes.update(frame["Athlete"].dropna().astype(str).str.strip().tolist())
    return sorted(athletes)


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
    jdf = state.get("jump_df")
    if jdf is None or jdf.empty or "Athlete" not in jdf.columns or "CMJ_cm" not in jdf.columns:
        return None
    athlete_df = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    if athlete_df.empty or athlete_df["CMJ_cm"].dropna().empty:
        return None
    latest = athlete_df["CMJ_cm"].dropna().iloc[-1]
    baseline = athlete_df["CMJ_cm"].dropna().mean()
    if baseline == 0:
        return None
    return round(((latest - baseline) / baseline) * 100, 1)


def _team_completion_mean(state: dict[str, pd.DataFrame | None]) -> float | None:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty or "Pct" not in cdf.columns:
        return None
    return round(float(cdf["Pct"].mean()), 1)


def _athlete_completion_mean(state: dict[str, pd.DataFrame | None], athlete: str) -> float | None:
    cdf = state.get("completion_df")
    if cdf is None or cdf.empty or "Pct" not in cdf.columns:
        return None
    if "Athlete" in cdf.columns:
        athlete_df = cdf[cdf["Athlete"] == athlete]
        if not athlete_df.empty:
            return round(float(athlete_df["Pct"].mean()), 1)
    return _team_completion_mean(state)


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


def _has_text(value: object) -> bool:
    return _ascii_text(value).strip() not in {"", "-", "—"}


def _row_has_eval_data(row: pd.Series | None) -> bool:
    if row is None:
        return False
    numeric_cols = ["CMJ cm", "CMJ vs BL %", "EUR", "DRI", "IMTP N"]
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


def build_executive_summary_df(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    athletes = _selected_athletes(state, report_athlete)

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
            row["EUR"] = _round_or_none(jump_row.get("EUR"), 3)
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
    return summary_df.fillna("—")


def generate_module_insights(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
) -> dict[str, dict[str, object]]:
    audience = normalize_report_audience(report_audience)
    summary_df = build_executive_summary_df(state, report_athlete)
    athletes = _selected_athletes(state, report_athlete)
    active_datasets = [
        key for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
        if state.get(key) is not None and not state.get(key).empty
    ]

    insights: dict[str, dict[str, object]] = {}

    insights["overview"] = {
        "title": "Lectura general",
        "summary": (
            f"{len(active_datasets)} dataset(s) activos y {len(athletes)} atleta(s) visibles en la ventana operativa actual."
            if active_datasets else
            "Todavía no hay datasets activos para construir una lectura ejecutiva."
        ),
        "focuses": [
            "Sostener la continuidad de carga y evaluaciones dentro de la misma ventana operativa.",
            "Priorizar datasets faltantes antes de compartir un reporte externo." if len(active_datasets) < 4 else "La base de datos ya permite una lectura integrada de carga, wellness y rendimiento.",
        ],
    }

    if report_athlete != "Todos" and not summary_df.empty:
        row = summary_df.iloc[0]
        load_notes = []
        acwr = _coerce_float(row.get("ACWR EWMA"))
        monotony = _coerce_float(row.get("Monotonia"))
        wellness = _coerce_float(row.get("Wellness 3d"))
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

        cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
        eval_focus = []
        if cmj_delta is not None:
            if cmj_delta <= -5:
                eval_focus.append("El CMJ cae respecto a la base; conviene mirar fatiga y exposición reciente.")
            elif cmj_delta >= 5:
                eval_focus.append("La salida vertical está por encima de la base reciente.")
            else:
                eval_focus.append("La evaluación se mantiene cerca de la línea base del atleta.")
        if row.get("Perfil NM") not in [None, "—"]:
            eval_focus.append(f"Perfil neuromuscular actual: {row.get('Perfil NM')}.")

        insights["load"] = {
            "title": "Lectura de carga",
            "summary": f"ACWR {row.get('ACWR EWMA', '—')} | Monotonía {row.get('Monotonia', '—')} | Wellness 3 días {row.get('Wellness 3d', '—')}.",
            "focuses": load_notes or ["Sin suficientes datos para una lectura de carga completa."],
        }
        insights["evaluations"] = {
            "title": "Lectura de evaluación",
            "summary": (
                f"CMJ {row.get('CMJ cm', '—')} cm | EUR {row.get('EUR', '—')} | DRI {row.get('DRI', '—')} | IMTP {row.get('IMTP N', '—')} N."
            ),
            "focuses": eval_focus or ["Sin suficientes evaluaciones para construir una interpretación estable."],
        }
        insights["profile"] = {
            "title": "Foco del atleta",
            "summary": f"El perfil integrado de {report_athlete} combina carga reciente, percepción de recuperación y última evaluación.",
            "focuses": list(dict.fromkeys((load_notes + eval_focus)))[:3] or ["Seguir acumulando historial para una lectura individual más precisa."],
        }
    else:
        zone_counts = summary_df["Zona"].value_counts().to_dict() if "Zona" in summary_df.columns else {}
        profile_counts = summary_df["Perfil NM"].value_counts().to_dict() if "Perfil NM" in summary_df.columns else {}
        zone_text = ", ".join(f"{key}: {value}" for key, value in zone_counts.items()) if zone_counts else "sin zonas de carga disponibles"
        profile_text = ", ".join(f"{key}: {value}" for key, value in profile_counts.items()) if profile_counts else "sin perfiles neuromusculares disponibles"

        insights["load"] = {
            "title": "Lectura de carga",
            "summary": f"Distribucion actual del equipo: {zone_text}.",
            "focuses": [
                "Revisar atletas en alto riesgo o precaucion antes del siguiente microciclo." if any(key in zone_counts for key in ["Alto riesgo", "Precaucion"]) else "La distribucion de carga no muestra acumulacion marcada de riesgo.",
                "Monitorear la monotonia de quienes concentran mas strain semanal.",
            ],
        }
        insights["evaluations"] = {
            "title": "Lectura de evaluación",
            "summary": f"Perfiles neuromusculares visibles: {profile_text}.",
            "focuses": [
                "Cruzar los perfiles reactivos con la carga reciente para decidir exposicion pliometrica.",
                "Usar IMTP, EUR y DRI para separar necesidades de fuerza base vs reactividad.",
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
    insights["team"] = {
        "title": "Adherencia del equipo",
        "summary": (
            f"Completion promedio del equipo: {completion_mean:.1f}%."
            if completion_mean is not None else
            "No hay completion cargado para evaluar adherencia."
        ),
        "focuses": [
            "Si la adherencia baja, revisar progresiones, disponibilidad y fricción operativa.",
            "Alinear reporte de carga y completion para entender si el volumen planificado realmente se ejecuta.",
        ],
    }
    insights["report"] = {
        "title": "Estado del reporte" if audience == "profe" else "Enfoque del reporte",
        "summary": (
            f"Versión técnica pensada para seguimiento detallado y toma de decisiones sobre {report_athlete}."
            if audience == "profe" else
            (
                f"Versión orientada al atleta, con foco en evaluaciones, perfil actual y próximos pasos de trabajo para {report_athlete}."
                if audience == "atleta" else
                f"Versión amigable para cliente, enfocada en explicar punto de partida, estado actual y próximos pasos de {report_athlete}."
            )
        ),
        "focuses": (
            [
                "Verificar datasets faltantes antes de exportar para terceros.",
                "Usar el resumen ejecutivo como portada operativa para cuerpo técnico y clientes.",
            ]
            if audience == "profe" else
            (
                [
                    "Destacar fortalezas, oportunidades y foco inmediato en lenguaje cuasi técnico.",
                    "Ordenar la información para que el atleta entienda qué sigue y por qué.",
                ]
                if audience == "atleta" else
                [
                    "Simplificar el lenguaje y evitar tecnicismos innecesarios.",
                    "Mostrar progreso, estado actual y próximos pasos con claridad.",
                ]
            )
        ),
    }
    return insights


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
) -> pd.DataFrame:
    active_datasets = [
        DATASET_LABELS.get(key, key)
        for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
        if state.get(key) is not None and not state.get(key).empty
    ]
    visible_athletes = collect_report_athletes(state)
    return pd.DataFrame(
        [
            {"Campo": "Reporte", "Valor": "Threshold S&C - Reporte de rendimiento"},
            {"Campo": "Alcance", "Valor": report_athlete},
            {"Campo": "Destinatario", "Valor": report_audience_label(report_audience)},
            {"Campo": "Generado", "Valor": datetime.now().strftime("%d/%m/%Y %H:%M")},
            {"Campo": "Ventana operativa", "Valor": "Últimas 6 semanas visibles"},
            {"Campo": "Atletas visibles", "Valor": len(visible_athletes)},
            {"Campo": "Datasets activos", "Valor": ", ".join(active_datasets) if active_datasets else "Sin datasets activos"},
            {"Campo": "Secciones incluidas", "Valor": ", ".join(included_sections) if included_sections else "Sin secciones"},
        ]
    )


def build_report_sheets(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
    report_audience: str = "profe",
    *,
    include_acwr: bool = True,
    include_mono: bool = True,
    include_wellness: bool = True,
    include_jumps: bool = True,
    include_maxes: bool = True,
    include_volume: bool = True,
    include_completion: bool = True,
) -> dict[str, pd.DataFrame]:
    sheets: dict[str, pd.DataFrame] = {}
    included_sections: list[str] = []

    executive_df = build_executive_summary_df(state, report_athlete)
    if not executive_df.empty:
        sheets["Resumen_Ejecutivo"] = executive_df
        included_sections.append("Resumen ejecutivo")

    interpretation_df = build_interpretation_sheet(state, report_athlete, report_audience)
    if not interpretation_df.empty:
        sheets["Interpretacion"] = interpretation_df
        included_sections.append("Interpretacion")

    acwr_dict = state.get("acwr_dict") or {}
    mono_dict = state.get("mono_dict") or {}

    if include_acwr and acwr_dict:
        acwr_rows = []
        for athlete, athlete_df in acwr_dict.items():
            if report_athlete != "Todos" and athlete != report_athlete:
                continue
            tmp = athlete_df.copy()
            tmp["Athlete"] = athlete
            acwr_rows.append(tmp)
        if acwr_rows:
            sheets["ACWR_sRPE"] = pd.concat(acwr_rows, ignore_index=True).round(2)
            included_sections.append("ACWR + sRPE")

    if include_mono and mono_dict:
        mono_rows = []
        for athlete, athlete_df in mono_dict.items():
            if report_athlete != "Todos" and athlete != report_athlete:
                continue
            tmp = athlete_df.copy()
            tmp["Athlete"] = athlete
            mono_rows.append(tmp)
        if mono_rows:
            sheets["Monotonia_Strain"] = pd.concat(mono_rows, ignore_index=True).round(2)
            included_sections.append("Monotonia + Strain")

    if include_wellness and state.get("wellness_df") is not None:
        df = state["wellness_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Wellness"] = df.round(2)
        if not df.empty:
            included_sections.append("Wellness")

    if include_jumps and state.get("jump_df") is not None:
        df = state["jump_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Evaluaciones_Saltos"] = df.round(2)
        if not df.empty:
            included_sections.append("Evaluaciones")

    if include_maxes and state.get("maxes_df") is not None:
        df = state["maxes_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Maximos_Ejercicios"] = df
        if not df.empty:
            included_sections.append("Maximos")

    if include_volume and state.get("rep_load_df") is not None:
        df = state["rep_load_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Volumen_Sesion"] = df
        if not df.empty:
            included_sections.append("Volumen")

    if include_completion and state.get("completion_df") is not None:
        df = state["completion_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            filtered_df = df[df["Athlete"] == report_athlete]
            if not filtered_df.empty:
                df = filtered_df
        sheets["Completion_Rate"] = df
        if not df.empty:
            included_sections.append("Completion")

    if sheets:
        sheets["Reporte_Meta"] = _build_report_metadata_df(state, report_athlete, report_audience, included_sections)

    return {name: df for name, df in sheets.items() if df is not None and not df.empty}


def _ordered_sheet_items(data_dict: dict[str, pd.DataFrame]) -> list[tuple[str, pd.DataFrame]]:
    ordered_names = [name for name in REPORT_SHEET_ORDER if name in data_dict]
    ordered_names.extend(name for name in data_dict if name not in ordered_names)
    return [(name, data_dict[name]) for name in ordered_names]


def _format_excel_sheet(worksheet, df: pd.DataFrame, sheet_name: str) -> None:
    header_fill = PatternFill(fill_type="solid", fgColor="0D3C5E")
    header_font = Font(color="FEFEFE", bold=True)
    body_font = Font(color="221F20")
    thin_side = Side(style="thin", color="D8DEE4")
    border = Border(bottom=thin_side)

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.sheet_view.showGridLines = False

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = body_font
            cell.alignment = Alignment(vertical="top")
            cell.border = border

    date_like_cols = [
        idx for idx, col in enumerate(df.columns, start=1)
        if "date" in str(col).lower() or "fecha" in str(col).lower() or "semana" in str(col).lower()
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

    for idx, column in enumerate(df.columns, start=1):
        values = [str(column)] + ["" if pd.isna(value) else str(value) for value in df[column].head(200)]
        max_len = min(max(len(value) for value in values) + 2, 36)
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
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                worksheet = writer.book[sheet_name[:31]]
                _format_excel_sheet(worksheet, df, sheet_name)
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
    if column == "ACWR":
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
            "Tu salto vertical se sostiene o mejora respecto a la base reciente."
            if audience != "profe" else
            "El CMJ se sostiene o mejora respecto a la línea base reciente."
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
            "Tu salto vertical cayó frente a tu base reciente; conviene recuperar calidad."
            if audience != "profe" else
            "El CMJ cae respecto a la base; conviene revisar fatiga reciente y exposición."
        )
    if acwr is not None and acwr > 1.5:
        gaps.append(
            "La carga reciente viene alta y puede pedir una semana más controlada."
            if audience != "profe" else
            "El ACWR queda alto y sugiere controlar densidad y exposición semanal."
        )
    elif acwr is not None and acwr < 0.8:
        gaps.append(
            "La carga reciente quedó baja; puede faltar continuidad de estímulo."
            if audience != "profe" else
            "El ACWR cae en subcarga; conviene revisar continuidad y volumen útil."
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


def _audience_dashboard_cards(
    state: dict[str, pd.DataFrame | None],
    focus_row: pd.Series,
    report_athlete: str,
    audience: str,
) -> list[tuple[str, str, str]]:
    completion_value = (
        _athlete_completion_mean(state, report_athlete)
        if report_athlete != "Todos" else
        _team_completion_mean(state)
    )
    if audience == "atleta":
        return [
            ("Perfil actual", _short_profile_label(focus_row.get("Perfil NM")), "#0D3C5E"),
            ("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"),
            ("DRI", _display_metric(focus_row.get("DRI"), digits=2), "#134263"),
            ("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N"), "#134263"),
            ("ACWR", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))),
            ("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"),
        ]
    if audience == "cliente":
        return [
            ("Estado actual", _display_zone(focus_row.get("Zona")), _zone_color(focus_row.get("Zona"))),
            ("Salto vertical", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"),
            ("Progreso CMJ", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%"), "#134263"),
            ("Bienestar", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"),
            ("Adherencia", _display_metric(completion_value, digits=1, suffix="%"), "#708C9F"),
            ("Perfil", _short_profile_label(focus_row.get("Perfil NM")), "#5A595B"),
        ]
    return [
        ("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))),
        ("Zona de carga", _display_zone(focus_row.get("Zona")), "#708C9F"),
        ("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"),
        ("Monotonía", _display_metric(focus_row.get("Monotonia"), digits=2), "#5A595B"),
        ("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"),
        ("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N"), "#134263"),
    ]


def _audience_metric_rows(
    state: dict[str, pd.DataFrame | None],
    focus_row: pd.Series,
    report_athlete: str,
    audience: str,
) -> list[tuple[str, str]]:
    completion_value = _athlete_completion_mean(state, report_athlete)
    if audience == "cliente":
        return [
            ("Estado actual", _display_zone(focus_row.get("Zona"))),
            ("Punto de referencia", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="% vs base")),
            ("Salto vertical hoy", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm")),
            ("Bienestar reciente", _display_metric(focus_row.get("Wellness 3d"), digits=1)),
            ("Adherencia", _display_metric(completion_value, digits=1, suffix="%")),
            ("Perfil actual", _ascii_text(focus_row.get("Perfil NM")).strip() or "-"),
        ]
    return [
        ("Perfil neuromuscular", _ascii_text(focus_row.get("Perfil NM")).strip() or "-"),
        ("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm")),
        ("DRI", _display_metric(focus_row.get("DRI"), digits=2)),
        ("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N")),
        ("ACWR", _display_metric(focus_row.get("ACWR EWMA"), digits=2)),
        ("Monotonía", _display_metric(focus_row.get("Monotonia"), digits=2)),
        ("Wellness 3 días", _display_metric(focus_row.get("Wellness 3d"), digits=1)),
        ("Completion", _display_metric(completion_value, digits=1, suffix="%")),
    ]


def _audience_blocks(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
    insights: dict[str, dict[str, object]],
    audience: str,
) -> list[dict[str, object]]:
    if audience == "profe" or report_athlete == "Todos" or summary_df.empty:
        ordered_keys = ["overview", "load", "evaluations", "profile", "team", "report"]
        return [insights[key] for key in ordered_keys if insights.get(key)]

    row = summary_df.iloc[0]
    strengths = _strengths_from_row(row, audience=audience)
    gaps = _gaps_from_row(row, audience=audience)
    next_steps = _next_steps_from_row(row, audience=audience)

    if audience == "cliente":
        return [
            {
                "title": "Punto de partida",
                "summary": "Tomamos como referencia tus primeras evaluaciones y la evolución del bloque reciente.",
                "focuses": [
                    f"Tu cambio frente a la base reciente hoy es {_display_metric(row.get('CMJ vs BL %'), digits=1, suffix='%')} en CMJ.",
                    f"El estado general actual se lee como {_display_zone(row.get('Zona'))}.",
                ],
            },
            {
                "title": "Dónde estás hoy",
                "summary": f"Hoy tu salto vertical está en {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')} y tu perfil actual se describe como {_ascii_text(row.get('Perfil NM')).strip() or 'sin perfil definido'}.",
                "focuses": strengths,
            },
            {
                "title": "Lo que vamos a trabajar",
                "summary": "Estos son los puntos con más margen de mejora para el próximo tramo.",
                "focuses": gaps,
            },
            {
                "title": "Siguientes pasos",
                "summary": "Plan de acción inmediato para seguir progresando sin perder claridad.",
                "focuses": next_steps,
            },
        ]

    return [
        {
            "title": "Perfil actual",
            "summary": f"Perfil neuromuscular: {_ascii_text(row.get('Perfil NM')).strip() or '-'} | CMJ {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')} | DRI {_display_metric(row.get('DRI'), digits=2)} | IMTP {_display_metric(row.get('IMTP N'), digits=0, suffix=' N')}.",
            "focuses": [
                f"ACWR actual: {_display_metric(row.get('ACWR EWMA'), digits=2)} en zona {_display_zone(row.get('Zona'))}.",
                f"Wellness reciente: {_display_metric(row.get('Wellness 3d'), digits=1)}.",
            ],
        },
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
            "title": "Siguientes pasos",
            "summary": "Próximas prioridades de trabajo con un lenguaje cuasi técnico y accionable.",
            "focuses": next_steps,
        },
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
            key for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
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
        "ACWR EWMA": "ACWR",
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


def _build_trend_page(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    report_audience: str,
) -> str | None:
    if report_athlete == "Todos":
        return None

    audience = normalize_report_audience(report_audience)
    cmj_series = _cmj_series(state, report_athlete)
    secondary_series = _acwr_series(state, report_athlete) if audience == "profe" else _wellness_series(state, report_athlete)
    if len(cmj_series) < 2 and len(secondary_series) < 2:
        return None

    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    title = "Tendencias clave" if audience != "cliente" else "Evolución reciente"
    subtitle = (
        "Dos curvas simples para seguir cómo se movió el rendimiento y la disponibilidad."
        if audience == "cliente" else
        "Lectura visual mínima para seguir evolución reciente sin sobrecargar el reporte."
    )
    _pdf_text(commands, 48, 800, title, font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 778, subtitle, size=10, color="#5A595B")
    _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

    _pdf_chart_panel(commands, 48, 408, 499, 280, title="CMJ", series=cmj_series, line_color="#0D3C5E")
    secondary_title = "ACWR EWMA" if audience == "profe" else "Wellness 3 días"
    secondary_color = "#708C9F" if audience == "profe" else "#2F6B52"
    _pdf_chart_panel(commands, 48, 96, 499, 280, title=secondary_title, series=secondary_series, line_color=secondary_color)
    return "\n".join(commands)


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
    summary_df = build_executive_summary_df(state, report_athlete)
    athletes = _selected_athletes(state, report_athlete)
    active_datasets = [
        key for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
        if state.get(key) is not None and not state.get(key).empty
    ]

    insights: dict[str, dict[str, object]] = {
        "overview": {
            "title": "Lectura general",
            "summary": (
                f"{_count_phrase(len(active_datasets), 'fuente activa', 'fuentes activas')} y {_count_phrase(len(athletes), 'atleta visible', 'atletas visibles')} dentro de la ventana operativa actual."
                if active_datasets else
                "Todavía no hay información suficiente para construir una lectura ejecutiva."
            ),
            "focuses": [
                "Sostener la continuidad de carga, evaluaciones y seguimiento dentro de la misma ventana operativa.",
                "Priorizar las fuentes faltantes antes de compartir un reporte externo." if len(active_datasets) < 4 else "La base actual ya permite una lectura integrada de carga, bienestar y rendimiento.",
            ],
        }
    }

    individual_eval_available = False
    if report_athlete != "Todos" and not summary_df.empty:
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
                eval_focus.append("El CMJ cae respecto a la base; conviene mirar fatiga y exposición reciente.")
            elif cmj_delta >= 5:
                eval_focus.append("La salida vertical está por encima de la base reciente.")
            else:
                eval_focus.append("La evaluación se mantiene cerca de la línea base del atleta.")
        if _has_text(row.get("Perfil NM")):
            eval_focus.append(f"Perfil neuromuscular actual: {_profile_text(row)}.")
        if not eval_available:
            eval_focus.append("Todavía no hay una evaluación reciente para construir una comparación objetiva.")

        load_summary_parts = _compact_lines(
            [
                f"ACWR {_display_metric(acwr, digits=2)}" if acwr is not None else None,
                f"Monotonía {_display_metric(monotony, digits=2)}" if monotony is not None else None,
                f"Wellness 3 días {_display_metric(wellness, digits=1)}" if wellness_available else None,
            ]
        )
        eval_summary_parts = _compact_lines(
            [
                f"CMJ {_display_metric(row.get('CMJ cm'), digits=1, suffix=' cm')}" if _coerce_float(row.get("CMJ cm")) is not None else None,
                f"EUR {_display_metric(row.get('EUR'), digits=2)}" if _coerce_float(row.get("EUR")) is not None else None,
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
            profile_summary = f"El perfil integrado de {report_athlete} combina carga reciente, percepción de recuperación y última evaluación."
        elif eval_available:
            profile_summary = f"La lectura actual de {report_athlete} se apoya principalmente en la última evaluación disponible."
        elif load_available or wellness_available:
            profile_summary = f"La lectura actual de {report_athlete} se apoya en carga y bienestar recientes, a la espera de una nueva evaluación."
        else:
            profile_summary = f"Todavía no hay información suficiente para construir un perfil integrado de {report_athlete}."

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
                "Usar IMTP, EUR y DRI para separar necesidades de fuerza base vs reactividad.",
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
    individual_completion = _focus_completion_value(state, report_athlete) if report_athlete != "Todos" else None
    insights["team"] = {
        "title": "Adherencia del plan" if report_athlete != "Todos" else "Adherencia del equipo",
        "summary": (
            f"Adherencia individual reciente: {individual_completion:.1f}%."
            if report_athlete != "Todos" and individual_completion is not None else
            (
                f"Adherencia promedio del equipo: {completion_mean:.1f}%."
                if completion_mean is not None else
                "No hay información de adherencia cargada para evaluar ejecución."
            )
        ),
        "focuses": [
            (
                "Si la adherencia baja, revisar barreras de cumplimiento, disponibilidad y organización semanal."
                if report_athlete != "Todos" else
                "Si la adherencia baja, revisar progresiones, disponibilidad y fricción operativa."
            ),
            (
                "Cruzar adherencia con carga y bienestar para entender si el plan realmente se está sosteniendo."
                if report_athlete != "Todos" else
                "Alinear carga y adherencia para entender si el volumen planificado realmente se ejecuta."
            ),
        ],
    }

    if audience == "profe":
        report_summary = f"Versión técnica pensada para seguimiento detallado y toma de decisiones sobre {report_athlete}."
        report_focuses = [
            "Verificar fuentes faltantes antes de exportar para terceros.",
            "Usar el resumen ejecutivo como portada operativa para cuerpo técnico y clientes.",
        ]
    elif audience == "atleta":
        report_summary = (
            f"Versión orientada al atleta, con foco en evaluaciones, perfil actual y próximos pasos de trabajo para {report_athlete}."
            if individual_eval_available else
            f"Versión orientada al atleta, centrada en estado actual, seguimiento y próximos pasos de trabajo para {report_athlete}."
        )
        report_focuses = [
            "Destacar fortalezas, oportunidades y foco inmediato en lenguaje cuasi técnico.",
            "Ordenar la información para que el atleta entienda qué sigue y por qué.",
        ]
    else:
        report_summary = (
            f"Versión amigable para cliente, enfocada en explicar punto de partida, estado actual y próximos pasos de {report_athlete}."
            if individual_eval_available else
            f"Versión amigable para cliente, enfocada en explicar el seguimiento actual y los próximos pasos de {report_athlete}."
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
            cards.append(("ACWR", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))))
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
            cards.append(("Cambio reciente", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%"), "#134263"))
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
            rows.append(("Cambio desde tu base", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%")))
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
            if _coerce_float(focus_row.get("EUR")) is not None:
                rows.append(("EUR", _display_metric(focus_row.get("EUR"), digits=2)))
            if _coerce_float(focus_row.get("CMJ vs BL %")) is not None:
                rows.append(("Cambio vs base", _display_metric(focus_row.get("CMJ vs BL %"), digits=1, suffix="%")))
        else:
            rows.append(("Evaluación reciente", "Sin evaluación física reciente"))

        if load_available and _coerce_float(focus_row.get("ACWR EWMA")) is not None:
            rows.append(("ACWR", _display_metric(focus_row.get("ACWR EWMA"), digits=2)))
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
        rows.append(("ACWR", _display_metric(focus_row.get("ACWR EWMA"), digits=2)))
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
    if audience == "profe" or report_athlete == "Todos" or summary_df.empty:
        ordered_keys = ["overview", "load", "evaluations", "profile", "team", "report"]
        return [insights[key] for key in ordered_keys if insights.get(key)]

    row = summary_df.iloc[0]
    eval_available = _row_has_eval_data(row)
    load_available = _row_has_load_data(row)
    wellness_available = _row_has_wellness_data(row)
    completion_value = _focus_completion_value(state, report_athlete)

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
        if eval_available:
            zone_text = (
                f" y tu estado general se lee como {_display_zone(row.get('Zona'))}"
                if load_available and _has_text(row.get("Zona")) else
                ""
            )
            progress_summary = (
                f"Tomamos como referencia tu línea base reciente. Hoy el cambio visible es {_display_metric(row.get('CMJ vs BL %'), digits=1, suffix='%')}{zone_text}."
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

        return [
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
                "focuses": gaps[:2] or ["Vamos a sostener el proceso y seguir ordenando la progresión."],
            },
            {
                "title": "Próximos pasos",
                "summary": "Plan de acción inmediato para seguir avanzando con claridad y continuidad.",
                "focuses": next_steps,
            },
        ]

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
                f"ACWR actual: {_display_metric(row.get('ACWR EWMA'), digits=2)} en zona {_display_zone(row.get('Zona'))}." if load_available and _coerce_float(row.get("ACWR EWMA")) is not None else None,
                f"Wellness reciente: {_display_metric(row.get('Wellness 3d'), digits=1)}." if wellness_available else None,
                f"Cambio frente a la base reciente: {_display_metric(row.get('CMJ vs BL %'), digits=1, suffix='%')}." if _coerce_float(row.get("CMJ vs BL %")) is not None else None,
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

    return [
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
            "focuses": gaps[:2] or ["La prioridad es sostener el perfil actual sin perder disponibilidad."],
        },
        {
            "title": "Siguientes pasos",
            "summary": "Próximas prioridades de trabajo con un lenguaje cuasi técnico y accionable.",
            "focuses": next_steps,
        },
    ]


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
    if report_athlete == "Todos":
        return []

    try:
        from charts.load_charts import chart_acwr, chart_wellness
        from charts.dashboard_charts import chart_cmj_trend, chart_radar
    except Exception:
        return []

    audience = normalize_report_audience(report_audience)
    theme = _build_report_chart_theme()
    figures: list[dict[str, object]] = []

    jdf = state.get("jump_df")
    if jdf is not None and not jdf.empty and "Athlete" in jdf.columns and report_athlete in jdf["Athlete"].values:
        athlete_jdf = jdf[jdf["Athlete"] == report_athlete].sort_values("Date")
        latest_row = athlete_jdf.iloc[-1]
        if audience in {"atleta", "profe"}:
            figures.append(
                {
                    "slug": "radar_perfil",
                    "title": "Perfil neuromuscular",
                    "figure": chart_radar(latest_row, report_athlete, _team_mean_for_radar(jdf), theme=theme),
                }
            )
        if len(_cmj_series(state, report_athlete)) >= 2:
            figures.append(
                {
                    "slug": "cmj_trend",
                    "title": "Tendencia de CMJ",
                    "figure": chart_cmj_trend(jdf, report_athlete, theme=theme),
                }
            )

    acwr_dict = state.get("acwr_dict") or {}
    acwr_df = acwr_dict.get(report_athlete)
    if acwr_df is not None and not acwr_df.empty and len(_acwr_series(state, report_athlete)) >= 2:
        figures.append(
            {
                "slug": "acwr",
                "title": "Carga reciente",
                "figure": chart_acwr(acwr_df, report_athlete, "ACWR_EWMA", theme=theme),
            }
        )

    wdf = state.get("wellness_df")
    if wdf is not None and not wdf.empty and "Athlete" in wdf.columns:
        athlete_wdf = wdf[wdf["Athlete"] == report_athlete].sort_values("Date")
        if not athlete_wdf.empty and len(_wellness_series(state, report_athlete)) >= 2:
            figures.append(
                {
                    "slug": "wellness",
                    "title": "Bienestar reciente",
                    "figure": chart_wellness(athlete_wdf, report_athlete, theme=theme),
                }
            )

    if audience == "cliente":
        preferred = {"cmj_trend", "wellness", "acwr"}
        figures = [item for item in figures if item["slug"] in preferred][:2]
    elif audience == "atleta":
        preferred = {"radar_perfil", "cmj_trend", "wellness", "acwr"}
        figures = [item for item in figures if item["slug"] in preferred][:3]
    else:
        preferred = {"radar_perfil", "cmj_trend", "acwr", "wellness"}
        figures = [item for item in figures if item["slug"] in preferred][:4]

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
        return None


def _resolve_brand_asset_path(kind: str = "wordmark") -> Path | None:
    patterns = {
        "wordmark": [
            "threshold_logo_horizontal.*",
            "threshold_wordmark.*",
            "Untitled-2.*",
            "untitled-2.*",
        ],
        "icon": [
            "threshold_isotipo.*",
            "threshold_icon.*",
            "Untitled-1.*",
            "untitled-1.*",
        ],
    }
    for pattern in patterns.get(kind, []):
        matches = sorted(BRAND_ASSET_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


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
    summary_df = build_executive_summary_df(state, report_athlete)
    insights = generate_module_insights(state, report_athlete, audience)
    blocks = _audience_blocks(state, report_athlete, summary_df, insights, audience)
    charts = collect_report_plotly_figures(state, report_athlete, audience)

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
        datasets_count = len(
            [
                key for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
                if state.get(key) is not None and not state.get(key).empty
            ]
        )
        athletes_count = len(summary_df)
        completion_value = _focus_completion_value(state, report_athlete)
        completion_text = _display_metric(completion_value, digits=1, suffix="%") if completion_value is not None else "Sin dato"
        adherence_label = "Adherencia del atleta" if report_athlete != "Todos" else "Adherencia promedio"
        data = [
            [
                _p(f"<b>{'Atleta visible' if athletes_count == 1 else 'Atletas visibles'}</b><br/>{athletes_count}", "ReportMuted"),
                _p(f"<b>{'Fuente activa' if datasets_count == 1 else 'Fuentes activas'}</b><br/>{datasets_count}", "ReportMuted"),
                _p(f"<b>{adherence_label}</b><br/>{completion_text}", "ReportMuted"),
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
                "ACWR EWMA": "ACWR",
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
            "ACWR": 18 * mm,
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
    if wordmark is not None:
        logo = _fit_image(wordmark, 150, 28)
        if logo is not None:
            story.append(logo)
            story.append(Spacer(1, 8 * mm))

    subtitle = {
        "atleta": "Reporte individual para atleta",
        "profe": "Reporte técnico para profesional",
        "cliente": "Reporte de progreso",
    }[audience]
    target_name = report_athlete if report_athlete != "Todos" else "Resumen general"
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
                _metric_cards_table(_audience_dashboard_cards(state, focus_row, report_athlete, audience)),
                Spacer(1, 5 * mm),
                _summary_meta_table(),
                Spacer(1, 5 * mm),
            ]
        )

        if report_athlete != "Todos":
            story.extend(_metric_table(_audience_metric_rows(state, focus_row, report_athlete, audience), title="Indicadores principales"))
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
    premium_pdf = _generate_visual_report_pdf_reportlab(state, report_athlete, audience)
    if premium_pdf:
        return premium_pdf

    summary_df = build_executive_summary_df(state, report_athlete)
    insights = generate_module_insights(state, report_athlete, audience)

    page_contents = [_build_cover_page(report_athlete, summary_df, insights, audience)]
    dashboard_page = _build_dashboard_page(state, report_athlete, summary_df, audience)
    if dashboard_page:
        page_contents.append(dashboard_page)
    if audience == "profe" or report_athlete == "Todos":
        page_contents.extend(_build_snapshot_pages(summary_df))
    else:
        metric_page = _build_metric_profile_page(state, report_athlete, summary_df, audience)
        if metric_page:
            page_contents.append(metric_page)
    trend_page = _build_trend_page(state, report_athlete, audience)
    if trend_page:
        page_contents.append(trend_page)
    page_contents.extend(_build_insight_pages(state, report_athlete, summary_df, insights, audience))
    return _build_pdf_document(page_contents)
