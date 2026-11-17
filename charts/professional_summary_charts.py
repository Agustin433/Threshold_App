"""Graficos del resumen ejecutivo del PDF profe.

Carga semanal: barras de sRPE de las ultimas 8 semanas, ACWR EWMA como linea
de contexto (gris, sin semaforo ni zonas) y las sesiones completadas (raw) en
el rotulo de cada semana. Los datos salen de
`modules.professional_summary.weekly_load_summary`.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.report_charts import PRINT_FONT_PX, ChartMode, apply_chart_mode

SUMMARY_LOAD_TITLE = "Carga semanal (sRPE) y ACWR"
SRPE_LABEL = "sRPE semanal (UA)"
ACWR_LABEL = "ACWR EWMA (contexto)"
NO_RPE_TEXT = "sin RPE"


def _week_tick(row: pd.Series) -> str:
    label = f"{pd.Timestamp(row['week_start']):%d/%m}"
    if bool(row.get("in_progress")):
        label += "*"
    sessions = int(row.get("sessions") or 0)
    return f"{label}<br>{sessions} ses."


def chart_summary_weekly_load(
    weekly: pd.DataFrame | None,
    *,
    theme: dict,
    mode: ChartMode = "print",
    print_height_mm: float = 52.0,
) -> go.Figure | None:
    """None si no hay ni sRPE ni sesiones en las 8 semanas."""
    if weekly is None or weekly.empty:
        return None
    srpe = pd.to_numeric(weekly["srpe"], errors="coerce")
    acwr = pd.to_numeric(weekly["acwr"], errors="coerce")
    sessions = pd.to_numeric(weekly["sessions"], errors="coerce").fillna(0)
    if srpe.isna().all() and not sessions.any():
        return None
    colors = theme["colors"]
    ticks = [_week_tick(row) for _, row in weekly.iterrows()]
    x = list(range(len(weekly)))
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=x,
            y=[0 if pd.isna(v) else float(v) for v in srpe],
            marker=dict(color=colors.get("steel", "#708C9F")),
            # "sin RPE" solo si esa semana hubo sesiones: sin sesiones no falta nada.
            text=[
                (NO_RPE_TEXT if n > 0 else "") if pd.isna(v) else f"{float(v):.0f}"
                for v, n in zip(srpe, sessions)
            ],
            textposition="outside",
            textfont=dict(size=PRINT_FONT_PX - 2 if mode == "print" else 11),
            cliponaxis=False,
            name=SRPE_LABEL,
        ),
        secondary_y=False,
    )
    if acwr.notna().any():
        fig.add_trace(
            go.Scatter(
                x=x,
                y=acwr,
                mode="lines+markers",
                connectgaps=False,
                line=dict(color=colors.get("gray", "#5A595B"), width=2, dash="dot"),
                marker=dict(size=7, color=colors.get("gray", "#5A595B")),
                name=ACWR_LABEL,
            ),
            secondary_y=True,
        )
    top = float(srpe.max()) if srpe.notna().any() else 100.0
    fig.update_yaxes(range=[0, max(top, 1.0) * 1.3], title_text="UA", secondary_y=False, zeroline=False)
    fig.update_yaxes(range=[0, 2.0], title_text="ACWR", secondary_y=True, showgrid=False, zeroline=False)
    fig.update_xaxes(tickvals=x, ticktext=ticks, showgrid=False)
    if mode == "print":
        return apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm)
    return apply_chart_mode(fig, "screen", theme=theme, title=SUMMARY_LOAD_TITLE, screen_height=320)
