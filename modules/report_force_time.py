from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from modules.force_time_analysis import (
    get_asymmetry_summary,
    get_force_time_points,
    get_rfd_points,
    interpret_imtp_force_time,
    summarize_force_time_test,
)


def _normalize_report_type(report_type: str | None) -> str:
    clean = str(report_type or "professional").strip().lower()
    aliases = {
        "professional": "professional",
        "profe": "professional",
        "coach": "professional",
        "athlete": "athlete",
        "atleta": "athlete",
        "client": "client",
        "cliente": "client",
    }
    return aliases.get(clean, "professional")


def _coerce_number(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _format_number(value: object, *, digits: int = 0, unit: str = "") -> str:
    numeric = _coerce_number(value)
    if numeric is None:
        return "Sin dato"
    rendered = f"{numeric:.{digits}f}"
    if digits == 0:
        rendered = rendered.split(".")[0]
    return f"{rendered} {unit}".strip()


def _format_side(side: object) -> str:
    if side == "left":
        return "izquierda"
    if side == "right":
        return "derecha"
    return "Sin dato"


def _line_text(points: list[dict[str, object]], value_key: str, unit: str) -> str:
    parts: list[str] = []
    for point in points:
        label = str(point.get("label") or "").strip()
        value = _coerce_number(point.get(value_key))
        if not label or value is None:
            continue
        parts.append(f"{label}: {_format_number(value, digits=0, unit=unit)}")
    return " | ".join(parts) if parts else "Sin dato"


def build_force_time_report_payload(
    row_or_record: object,
    test_id: str = "imtp",
    report_type: str = "professional",
) -> dict[str, object]:
    summary = summarize_force_time_test(row_or_record, test_id=test_id)
    payload = {
        "test_id": str(summary.get("test_id") or test_id),
        "display_name": str(summary.get("display_name") or str(test_id).upper()),
        "summary": summary,
        "force_time_points": get_force_time_points(summary),
        "rfd_points": get_rfd_points(summary),
        "asymmetry": get_asymmetry_summary(summary),
        "interpretation": interpret_imtp_force_time(summary),
        "has_valid_force_time": bool(summary.get("has_valid_force_time")),
        "report_type": _normalize_report_type(report_type),
    }
    return payload


def _key_value_table(
    pdf: Mapping[str, object],
    rows: list[tuple[str, str]],
    *,
    label_style: str,
    value_style: str,
    col_widths_mm: tuple[float, float],
):
    Table = pdf["Table"]
    TableStyle = pdf["TableStyle"]
    mm = pdf["mm"]
    p = pdf["p"]
    palette = pdf["palette"]
    data = [[p(label, label_style), p(value, value_style)] for label, value in rows]
    table = Table(data, colWidths=[col_widths_mm[0] * mm, col_widths_mm[1] * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, palette["line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                ("BACKGROUND", (0, 0), (-1, -1), palette["card"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def draw_force_time_test_block(
    pdf: Mapping[str, object],
    payload: Mapping[str, object] | None,
    report_type: str = "professional",
) -> None:
    if not payload or not payload.get("has_valid_force_time"):
        return

    story = pdf.get("story")
    p = pdf.get("p")
    box = pdf.get("box")
    Spacer = pdf.get("Spacer")
    mm = pdf.get("mm")
    if not isinstance(story, list) or p is None or box is None or Spacer is None or mm is None:
        return

    mode = _normalize_report_type(report_type)
    summary = dict(payload.get("summary", {}))
    asymmetry = dict(payload.get("asymmetry", {}))
    interpretation = dict(payload.get("interpretation", {}))
    force_time_points = list(payload.get("force_time_points", []))
    rfd_points = list(payload.get("rfd_points", []))

    if mode == "client":
        return

    if mode == "athlete":
        story.append(p("IMTP force-time", "ReportSection"))
        story.append(
            box(
                [
                    p(
                        "Perfil force-time por puntos basado en valores exportados del resumen de la evaluacion. "
                        "No representa una curva continua de adquisicion.",
                        "ReportMuted",
                    ),
                    p(f"Peak Force: {_format_number(summary.get('peak_force_n'), digits=0, unit='N')}", "ReportBody"),
                    p(
                        f"Asimetria: {_format_number(summary.get('absolute_asymmetry_pct'), digits=1, unit='%')} | "
                        f"Mayor produccion: {_format_side(asymmetry.get('stronger_side'))}",
                        "ReportBody",
                    ),
                    p(
                        "Perfil por puntos: " + _line_text(force_time_points, "value_n", "N"),
                        "ReportBody",
                    ),
                    p(
                        "RFD: " + _line_text(rfd_points, "value_n_s", "N/s"),
                        "ReportBody",
                    ),
                    p(
                        "Peak Force describe la produccion maxima de fuerza isometrica en la posicion de IMTP. "
                        "Los puntos temporales muestran como se expresa la fuerza entre ventanas tempranas e intermedias.",
                        "ReportMuted",
                    ),
                    p(
                        "La RFD describe la tasa de desarrollo de fuerza y conviene interpretarla con cautela "
                        "cuando no hay un TE o umbral de confiabilidad especifico del test.",
                        "ReportMuted",
                    ),
                ],
                padding=8,
            )
        )
        story.append(Spacer(1, 4 * mm))
        return

    story.append(p("IMTP force-time", "ProfSection"))
    story.append(
        box(
            [
                p(
                    "Perfil force-time por puntos basado en valores exportados del resumen de la evaluacion. "
                    "No representa una curva continua de adquisicion.",
                    "ProfMuted",
                )
            ],
            padding=6,
        )
    )
    story.append(Spacer(1, 3 * mm))

    main_rows = [
        ("Peak Force", _format_number(summary.get("peak_force_n"), digits=0, unit="N")),
        ("Force Avg", _format_number(summary.get("avg_force_n"), digits=0, unit="N")),
        ("Time to Peak", _format_number(summary.get("time_to_peak_s"), digits=2, unit="s")),
        ("Time Pull", _format_number(summary.get("time_pull_s"), digits=2, unit="s")),
        ("Pre-tension", _format_number(summary.get("pre_tension_n"), digits=0, unit="N")),
        ("Left Force", _format_number(summary.get("left_force_n"), digits=0, unit="N")),
        ("Right Force", _format_number(summary.get("right_force_n"), digits=0, unit="N")),
        ("Asymmetry", _format_number(summary.get("absolute_asymmetry_pct"), digits=1, unit="%")),
        ("Lado mas fuerte", _format_side(asymmetry.get("stronger_side"))),
        ("Lado mas debil", _format_side(asymmetry.get("weaker_side"))),
        ("Diferencia lateral", _format_number(asymmetry.get("side_difference_n"), digits=0, unit="N")),
    ]
    story.append(
        _key_value_table(
            pdf,
            main_rows,
            label_style="ProfCardTitle",
            value_style="ProfMuted",
            col_widths_mm=(54, 120),
        )
    )
    story.append(Spacer(1, 3 * mm))

    force_rows = [(str(point.get("label") or "-"), _format_number(point.get("value_n"), digits=0, unit="N")) for point in force_time_points]
    story.append(p("Fuerza por ventana exportada", "ProfCardTitle"))
    story.append(
        _key_value_table(
            pdf,
            force_rows,
            label_style="ProfCardTitle",
            value_style="ProfMuted",
            col_widths_mm=(36, 138),
        )
    )
    story.append(Spacer(1, 3 * mm))

    rfd_rows = [(str(point.get("label") or "-"), _format_number(point.get("value_n_s"), digits=0, unit="N/s")) for point in rfd_points]
    story.append(p("RFD por ventana exportada", "ProfCardTitle"))
    story.append(
        _key_value_table(
            pdf,
            rfd_rows,
            label_style="ProfCardTitle",
            value_style="ProfMuted",
            col_widths_mm=(36, 138),
        )
    )
    story.append(Spacer(1, 3 * mm))

    note_lines = [
        interpretation.get("peak_force_text"),
        interpretation.get("force_time_text"),
        interpretation.get("asymmetry_text"),
        interpretation.get("rfd_text"),
        "La RFD es sensible al protocolo, la pre-tension, el criterio de inicio de la contraccion y la familiarizacion. "
        "Sin un TE o umbral de confiabilidad especifico del test, conviene interpretarla con cautela.",
        interpretation.get("decision_note"),
    ]
    story.append(
        box(
            [p(str(line), "ProfMuted") for line in note_lines if str(line or "").strip()],
            padding=6,
        )
    )
    story.append(Spacer(1, 4 * mm))
