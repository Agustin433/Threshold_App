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
            row["Fecha evaluacion"] = pd.to_datetime(jump_row["Date"]).strftime("%d/%m/%Y")
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
) -> dict[str, dict[str, object]]:
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
            "Todavia no hay datasets activos para construir una lectura ejecutiva."
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
                load_notes.append("Verificar si la subcarga es planificada o si falta estimulo.")
            else:
                load_notes.append("La relacion agudo-cronica se mantiene en zona de trabajo util.")
        if monotony is not None and monotony > 2.0:
            load_notes.append("Aumentar variabilidad del microciclo para reducir monotonia.")
        if wellness is not None and wellness < 15:
            load_notes.append("Seguir recuperacion diaria porque el wellness reciente esta deprimido.")

        cmj_delta = _coerce_float(row.get("CMJ vs BL %"))
        eval_focus = []
        if cmj_delta is not None:
            if cmj_delta <= -5:
                eval_focus.append("El CMJ cae respecto a la base; conviene mirar fatiga y exposicion reciente.")
            elif cmj_delta >= 5:
                eval_focus.append("La salida vertical esta por encima de la base reciente.")
            else:
                eval_focus.append("La evaluacion se mantiene cerca de la linea base del atleta.")
        if row.get("Perfil NM") not in [None, "—"]:
            eval_focus.append(f"Perfil neuromuscular actual: {row.get('Perfil NM')}.")

        insights["load"] = {
            "title": "Lectura de carga",
            "summary": f"ACWR {row.get('ACWR EWMA', '—')} | Monotonia {row.get('Monotonia', '—')} | Wellness 3d {row.get('Wellness 3d', '—')}.",
            "focuses": load_notes or ["Sin suficientes datos para una lectura de carga completa."],
        }
        insights["evaluations"] = {
            "title": "Lectura de evaluacion",
            "summary": (
                f"CMJ {row.get('CMJ cm', '—')} cm | EUR {row.get('EUR', '—')} | DRI {row.get('DRI', '—')} | IMTP {row.get('IMTP N', '—')} N."
            ),
            "focuses": eval_focus or ["Sin suficientes evaluaciones para construir una interpretacion estable."],
        }
        insights["profile"] = {
            "title": "Foco del atleta",
            "summary": f"El perfil integrado de {report_athlete} combina carga reciente, percepcion de recuperacion y ultima evaluacion.",
            "focuses": list(dict.fromkeys((load_notes + eval_focus)))[:3] or ["Seguir acumulando historial para una lectura individual mas precisa."],
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
            "title": "Lectura de evaluacion",
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
            "Si la adherencia baja, revisar progresiones, disponibilidad y friccion operativa.",
            "Alinear reporte de carga y completion para entender si el volumen planificado realmente se ejecuta.",
        ],
    }
    insights["report"] = {
        "title": "Estado del reporte",
        "summary": (
            f"El reporte ejecutivo para {report_athlete} puede salir en Excel y PDF con resumen, narrativa y focos."
        ),
        "focuses": [
            "Verificar datasets faltantes antes de exportar para terceros.",
            "Usar el resumen ejecutivo como portada operativa para cuerpo tecnico y clientes.",
        ],
    }
    return insights


def build_interpretation_sheet(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
) -> pd.DataFrame:
    insights = generate_module_insights(state, report_athlete)
    rows = []
    for module_name, payload in insights.items():
        rows.append(
            {
                "Modulo": module_name.title(),
                "Lectura": payload.get("summary", ""),
                "Proximos focos": " | ".join(payload.get("focuses", [])),
            }
        )
    return pd.DataFrame(rows)


def _build_report_metadata_df(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
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
            {"Campo": "Reporte", "Valor": "Threshold S&C Performance Report"},
            {"Campo": "Alcance", "Valor": report_athlete},
            {"Campo": "Generado", "Valor": datetime.now().strftime("%d/%m/%Y %H:%M")},
            {"Campo": "Ventana operativa", "Valor": "Ultimas 6 semanas visibles"},
            {"Campo": "Atletas visibles", "Valor": len(visible_athletes)},
            {"Campo": "Datasets activos", "Valor": ", ".join(active_datasets) if active_datasets else "Sin datasets activos"},
            {"Campo": "Secciones incluidas", "Valor": ", ".join(included_sections) if included_sections else "Sin secciones"},
        ]
    )


def build_report_sheets(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str = "Todos",
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

    interpretation_df = build_interpretation_sheet(state, report_athlete)
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
        sheets["Reporte_Meta"] = _build_report_metadata_df(state, report_athlete, included_sections)

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
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


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


def _build_cover_page(report_athlete: str, summary_df: pd.DataFrame, insights: dict[str, dict[str, object]]) -> str:
    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    _pdf_rect(commands, 0, 742, 595, 100, "#221F20")
    _pdf_rect(commands, 48, 730, 220, 3, "#0D3C5E")
    _pdf_text(commands, 48, 794, "THRESHOLD STRENGTH & CONDITIONING", font="F2", size=21, color="#FEFEFE")
    _pdf_text(commands, 48, 770, "Performance Report", font="F2", size=14, color="#9AA2A9")

    _pdf_text(commands, 48, 698, "Scope", size=10, color="#708C9F")
    _pdf_text(commands, 48, 674, report_athlete, font="F2", size=20, color="#0D3C5E")
    _pdf_text(commands, 250, 698, "Generated", size=10, color="#708C9F")
    _pdf_text(commands, 250, 676, f"{datetime.now():%d/%m/%Y %H:%M}", font="F2", size=14, color="#221F20")
    _pdf_text(commands, 430, 698, "Executive rows", size=10, color="#708C9F")
    _pdf_text(commands, 430, 676, str(len(summary_df)), font="F2", size=14, color="#221F20")

    _pdf_rect(commands, 48, 560, 499, 84, "#FEFEFE")
    _pdf_stroke_rect(commands, 48, 560, 499, 84, color="#D8DEE4")
    _pdf_text(commands, 64, 620, "Executive narrative", font="F2", size=13, color="#221F20")
    intro = insights.get("report", {}).get("summary", "Operational report ready for technical review.")
    _pdf_multiline(commands, 64, 598, _wrap_lines(intro, 78), size=10, color="#5A595B", leading=14)

    overview_summary = insights.get("overview", {}).get("summary", "No overview available yet.")
    _pdf_label_value_card(commands, 48, 450, 156, 78, label="Report focus", value="Integrated review", accent="#0D3C5E")
    _pdf_label_value_card(commands, 220, 450, 156, 78, label="Window", value="Last 6 weeks", accent="#708C9F")
    _pdf_label_value_card(commands, 392, 450, 155, 78, label="Modules", value=str(len(insights)), accent="#5A595B")

    _pdf_text(commands, 48, 410, "Reading context", font="F2", size=13, color="#221F20")
    _pdf_multiline(commands, 48, 388, _wrap_lines(overview_summary, 82), size=10, color="#5A595B", leading=14)

    _pdf_text(commands, 48, 318, "Priority focuses", font="F2", size=13, color="#221F20")
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
    footer = "Threshold S&C - Load monitoring, evaluations and athlete follow-up."
    _pdf_multiline(commands, 48, 92, _wrap_lines(footer, 84), size=9, color="#708C9F", leading=13)
    return "\n".join(commands)


def _build_dashboard_page(
    state: dict[str, pd.DataFrame | None],
    report_athlete: str,
    summary_df: pd.DataFrame,
) -> str | None:
    if summary_df.empty:
        return None

    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    _pdf_text(commands, 48, 800, "Executive dashboard", font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 778, "Latest integrated snapshot for operational review.", size=10, color="#5A595B")
    _pdf_line(commands, 48, 766, 547, 766, color="#D8DEE4")

    if report_athlete != "Todos" and not summary_df.empty:
        focus_row = summary_df.iloc[0]
        title_text = _ascii_text(focus_row.get("Atleta", report_athlete))
    else:
        focus_row = summary_df.iloc[0]
        title_text = f"{len(summary_df)} visible athlete(s)"

    _pdf_text(commands, 48, 730, title_text, font="F2", size=22, color="#221F20")
    _pdf_text(commands, 48, 708, "Performance dashboard ready for technical review and client-facing export.", size=10, color="#708C9F")

    cards = [
        ("ACWR EWMA", _display_metric(focus_row.get("ACWR EWMA"), digits=2), _zone_color(focus_row.get("Zona"))),
        ("Load zone", _display_metric(focus_row.get("Zona")), "#708C9F"),
        ("Wellness 3d", _display_metric(focus_row.get("Wellness 3d"), digits=1), "#2F6B52"),
        ("Monotony", _display_metric(focus_row.get("Monotonia"), digits=2), "#5A595B"),
        ("CMJ", _display_metric(focus_row.get("CMJ cm"), digits=1, suffix=" cm"), "#0D3C5E"),
        ("IMTP", _display_metric(focus_row.get("IMTP N"), digits=0, suffix=" N"), "#134263"),
    ]

    positions = [
        (48, 604), (220, 604), (392, 604),
        (48, 504), (220, 504), (392, 504),
    ]
    for (label, value, accent), (x, y) in zip(cards, positions):
        _pdf_label_value_card(commands, x, y, 155, 82, label=label, value=value, accent=accent)

    completion_value = _team_completion_mean(state)
    completion_text = _display_metric(completion_value, digits=1, suffix="%") if completion_value is not None else "-"
    athletes_text = str(len(summary_df))
    datasets_count = len(
        [
            key for key in ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
            if state.get(key) is not None and not state.get(key).empty
        ]
    )

    _pdf_rect(commands, 48, 392, 499, 78, "#FEFEFE")
    _pdf_stroke_rect(commands, 48, 392, 499, 78, color="#D8DEE4")
    _pdf_text(commands, 64, 438, "Report pulse", font="F2", size=12, color="#221F20")
    _pdf_text(commands, 64, 414, f"Visible athletes: {athletes_text}", size=10, color="#5A595B")
    _pdf_text(commands, 220, 414, f"Active datasets: {datasets_count}", size=10, color="#5A595B")
    _pdf_text(commands, 392, 414, f"Completion mean: {completion_text}", size=10, color="#5A595B")

    _pdf_text(commands, 48, 346, "Export note", font="F2", size=12, color="#221F20")
    _pdf_multiline(
        commands,
        48,
        324,
        [
            "Use this page as the visual executive snapshot for coaches, athletes and clients.",
            "The detailed table and module readings continue on the next pages.",
        ],
        size=10,
        color="#5A595B",
        leading=14,
    )
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
        "Atleta": "Athlete",
        "ACWR EWMA": "ACWR",
        "Wellness 3d": "Wellness",
        "CMJ cm": "CMJ",
        "IMTP N": "IMTP",
        "Perfil NM": "NM Profile",
    }
    display_df = display_df.rename(columns=rename_map)

    rows_per_page = 14
    pages: list[str] = []
    columns = display_df.columns.tolist()
    widths = [120, 58, 72, 62, 52, 52, 62, 72][: len(columns)]

    for start in range(0, len(display_df), rows_per_page):
        chunk = display_df.iloc[start:start + rows_per_page]
        commands: list[str] = []
        _pdf_rect(commands, 0, 0, 595, 842, "#FEFEFE")
        _pdf_text(commands, 48, 800, "Athlete snapshot table", font="F2", size=18, color="#0D3C5E")
        _pdf_text(commands, 48, 778, "Integrated KPI table for the current visible window.", size=10, color="#5A595B")
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
                raw_value = row.get(col, "-")
                text_color = _zone_color(raw_value) if col == "Zone" else "#221F20"
                wrapped = _wrap_lines(raw_value, max(8, int(width / 6)))
                _pdf_multiline(commands, current_x + 6, current_y + 20, wrapped[:2], size=8, color=text_color, leading=10)
                current_x += width
            current_y -= row_h

        pages.append("\n".join(commands))
    return pages


def _build_insight_pages(insights: dict[str, dict[str, object]]) -> list[str]:
    ordered_keys = ["overview", "load", "evaluations", "profile", "team", "report"]
    payloads = [insights[key] for key in ordered_keys if insights.get(key)]
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
        _pdf_text(commands, 48, 800, "Interpretation and focus areas", font="F2", size=18, color="#0D3C5E")
        _pdf_text(commands, 48, 778, "Editorial reading by module for follow-up and reporting.", size=10, color="#5A595B")
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
        content_bytes = content.encode("ascii", "ignore")
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
) -> bytes | None:
    summary_df = build_executive_summary_df(state, report_athlete)
    insights = generate_module_insights(state, report_athlete)

    page_contents = [_build_cover_page(report_athlete, summary_df, insights)]
    dashboard_page = _build_dashboard_page(state, report_athlete, summary_df)
    if dashboard_page:
        page_contents.append(dashboard_page)
    page_contents.extend(_build_snapshot_pages(summary_df))
    page_contents.extend(_build_insight_pages(insights))
    return _build_pdf_document(page_contents)
