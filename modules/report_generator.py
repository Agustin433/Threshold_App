"""Shared report export, summary and narrative helpers."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import textwrap
import unicodedata

import pandas as pd


APP_ROOT = Path(__file__).resolve().parent.parent
BRAND_ASSET_DIR = APP_ROOT / "assets" / "brand"


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

    executive_df = build_executive_summary_df(state, report_athlete)
    if not executive_df.empty:
        sheets["Resumen_Ejecutivo"] = executive_df

    interpretation_df = build_interpretation_sheet(state, report_athlete)
    if not interpretation_df.empty:
        sheets["Interpretacion"] = interpretation_df

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

    if include_wellness and state.get("wellness_df") is not None:
        df = state["wellness_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Wellness"] = df.round(2)

    if include_jumps and state.get("jump_df") is not None:
        df = state["jump_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Evaluaciones_Saltos"] = df.round(2)

    if include_maxes and state.get("maxes_df") is not None:
        df = state["maxes_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Maximos_Ejercicios"] = df

    if include_volume and state.get("rep_load_df") is not None:
        df = state["rep_load_df"]
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Volumen_Sesion"] = df

    if include_completion and state.get("completion_df") is not None:
        sheets["Completion_Rate"] = state["completion_df"]

    return {name: df for name, df in sheets.items() if df is not None and not df.empty}


def export_excel(data_dict: dict[str, pd.DataFrame]) -> bytes:
    """Export selected dataframes to a multi-sheet Excel workbook."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in data_dict.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
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


def _build_cover_page(report_athlete: str, summary_df: pd.DataFrame, insights: dict[str, dict[str, object]]) -> str:
    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#F4F6F8")
    _pdf_rect(commands, 0, 742, 595, 100, "#0D3C5E")
    _pdf_text(commands, 48, 798, "THRESHOLD STRENGTH & CONDITIONING", font="F2", size=22, color="#FEFEFE")
    _pdf_text(commands, 48, 770, "Performance Report", font="F2", size=16, color="#FEFEFE")

    _pdf_text(commands, 48, 700, f"Scope: {report_athlete}", font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 676, f"Generated: {datetime.now():%d/%m/%Y %H:%M}", size=11, color="#5A595B")
    summary_line = (
        f"Executive rows: {len(summary_df)} | Active modules: {len(insights)}"
        if not summary_df.empty else
        "No executive summary rows available yet."
    )
    _pdf_text(commands, 48, 652, summary_line, size=11, color="#5A595B")

    y = 610
    _pdf_text(commands, 48, y, "Executive narrative", font="F2", size=14, color="#0D3C5E")
    y -= 28
    intro = insights.get("report", {}).get("summary", "Operational report ready for technical review.")
    y = _pdf_multiline(commands, 48, y, _wrap_lines(intro, 72), size=11, color="#221F20", leading=15)

    y -= 18
    _pdf_text(commands, 48, y, "Priority focuses", font="F2", size=14, color="#0D3C5E")
    y -= 24
    for focus in insights.get("report", {}).get("focuses", []):
        wrapped = _wrap_lines(f"- {focus}", 76)
        y = _pdf_multiline(commands, 60, y, wrapped, size=10, color="#221F20", leading=14) - 6

    y -= 10
    _pdf_line(commands, 48, y, 547, y)
    y -= 28
    footer = "Threshold S&C - Load monitoring, evaluations and athlete follow-up."
    _pdf_multiline(commands, 48, y, _wrap_lines(footer, 80), size=10, color="#708C9F", leading=14)
    return "\n".join(commands)


def _build_summary_pages(summary_df: pd.DataFrame) -> list[str]:
    if summary_df.empty:
        return []

    rows = []
    for _, row in summary_df.fillna("—").iterrows():
        line = " | ".join(
            [
                _ascii_text(row.get("Atleta", "—")),
                f"ACWR {row.get('ACWR EWMA', '—')}",
                f"Zona {row.get('Zona', '—')}",
                f"CMJ {row.get('CMJ cm', '—')}",
                f"DRI {row.get('DRI', '—')}",
                f"IMTP {row.get('IMTP N', '—')}",
            ]
        )
        rows.append(line)

    pages = []
    chunk_size = 22
    for start in range(0, len(rows), chunk_size):
        commands: list[str] = []
        _pdf_rect(commands, 0, 0, 595, 842, "#FEFEFE")
        _pdf_text(commands, 48, 800, "Executive summary", font="F2", size=18, color="#0D3C5E")
        _pdf_text(commands, 48, 780, "Most recent integrated KPI snapshot by athlete.", size=11, color="#5A595B")
        _pdf_line(commands, 48, 770, 547, 770, color="#9AA2A9")
        y = 744
        for line in rows[start:start + chunk_size]:
            wrapped = _wrap_lines(line, 84)
            y = _pdf_multiline(commands, 48, y, wrapped, font="F3", size=9, color="#221F20", leading=13) - 8
        pages.append("\n".join(commands))
    return pages


def _build_insight_page(insights: dict[str, dict[str, object]]) -> str:
    commands: list[str] = []
    _pdf_rect(commands, 0, 0, 595, 842, "#FEFEFE")
    _pdf_text(commands, 48, 800, "Interpretation and focus areas", font="F2", size=18, color="#0D3C5E")
    _pdf_text(commands, 48, 780, "Brief editorial reading for technical follow-up.", size=11, color="#5A595B")
    _pdf_line(commands, 48, 770, 547, 770, color="#9AA2A9")

    y = 744
    ordered_keys = ["overview", "load", "evaluations", "profile", "team"]
    for key in ordered_keys:
        payload = insights.get(key)
        if not payload:
            continue
        _pdf_text(commands, 48, y, payload.get("title", key.title()), font="F2", size=13, color="#0D3C5E")
        y -= 18
        y = _pdf_multiline(commands, 48, y, _wrap_lines(payload.get("summary", ""), 80), size=10, color="#221F20", leading=13) - 8
        for focus in payload.get("focuses", [])[:3]:
            y = _pdf_multiline(commands, 60, y, _wrap_lines(f"- {focus}", 78), size=10, color="#5A595B", leading=13) - 4
        y -= 12
        if y < 90:
            break
    return "\n".join(commands)


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
    page_contents.extend(_build_summary_pages(summary_df))
    page_contents.append(_build_insight_page(insights))
    return _build_pdf_document(page_contents)
