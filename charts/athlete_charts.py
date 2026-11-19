"""Graficos del reporte de atleta/cliente: "Tu evolucion" y "Tu posicion en el grupo".

Una funcion por grafico, para dashboard (mode="screen") y PDF (mode="print"),
igual que `charts.report_charts`. Los datos salen de
`modules.athlete_report.evolution_series` y `group_position`: el PDF y el
dashboard dibujan lo mismo.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.report_charts import PRINT_FONT_PX, ChartMode, apply_chart_mode

EVOLUTION_TITLE = "Tu evolución"
POSITION_TITLE = "Tu posición en el grupo"


def _value_text(value: float, digits: int, unit: str) -> str:
    return f"{value:.{digits}f}" + (f" {unit}" if unit else "")


# Titulo corto del grafico cuando el rotulo no entra a media pagina.
EVOLUTION_SHORT_TITLES = {
    "CMJ_ft_cm": "Salto CMJ por vuelo (cm)",
    "DJ_RSI": "Reactividad (DJ RSI)",
    "IMTP_relPF": "Fuerza máxima (N/kg)",
}
EVOLUTION_TITLE_MAX_CHARS = 26
EVOLUTION_COLUMNS = 2
ERA_CHANGE_LABEL = "cambio de equipo"


def evolution_rows(series: list[dict[str, object]] | None) -> int:
    """Filas del grafico de evolucion: 2 por fila, nunca 3."""
    count = len(series or [])
    return max(1, -(-count // EVOLUTION_COLUMNS))


def _evolution_title(item: dict[str, object]) -> str:
    title = str(item["label"]) + (f" ({item['unit']})" if item.get("unit") else "")
    if len(title) > EVOLUTION_TITLE_MAX_CHARS:
        title = EVOLUTION_SHORT_TITLES.get(str(item.get("variable")), title)
    return title


def chart_athlete_evolution(
    series: list[dict[str, object]] | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    print_height_mm: float = 62.0,
) -> go.Figure | None:
    """Una linea por prueba (2 por fila), un punto por toma con fecha y valor.

    El eje X tiene un lugar por evaluacion (no es proporcional al tiempo) y
    se rotula con mes y año en español ("nov 25"). Banda sombreada = primera
    toma +/- max(TE, SWC). En una serie que mezcla eras (IMTP) el tramo entre
    eras va punteado, con una linea vertical "cambio de equipo", y los puntos
    de la era anterior van huecos con borde marcado. `print_height_mm` es la
    altura de cada fila. None sin series (1 sola evaluacion).
    """
    from charts.report_charts import spanish_month_year

    if not series:
        return None
    colors = theme["colors"]
    steel = colors.get("steel", "#134263")
    rows = evolution_rows(series)
    cols = min(EVOLUTION_COLUMNS, len(series))
    titles = [_evolution_title(item) for item in series]
    fig = make_subplots(
        rows=rows, cols=cols, subplot_titles=titles, horizontal_spacing=0.12, vertical_spacing=0.32 / rows,
    )
    font_px = PRINT_FONT_PX if mode == "print" else 12
    for index, item in enumerate(series):
        row, col = index // cols + 1, index % cols + 1
        dates = [pd.Timestamp(date) for date in item["dates"]]
        values = [float(value) for value in item["values"]]
        digits = int(item.get("digits", 1))
        band = item.get("band")
        previous = list(item.get("previous_protocol") or [False] * len(values))
        eras = list(item.get("point_eras") or [None] * len(values))
        x = list(range(len(values)))
        # Tramos: solido dentro de la misma era, punteado si cruza eras.
        for i in range(len(values) - 1):
            crosses = eras[i] is not None and eras[i + 1] is not None and eras[i] != eras[i + 1]
            fig.add_trace(
                go.Scatter(
                    x=[x[i], x[i + 1]], y=[values[i], values[i + 1]], mode="lines",
                    line=dict(color=steel, width=3, dash="dot" if crosses else "solid"),
                    showlegend=False, hoverinfo="skip",
                ),
                row=row, col=col,
            )
            if crosses:
                fig.add_vline(x=i + 0.5, row=row, col=col, line=dict(color="rgba(90,89,91,0.7)", width=1))
                axis_index = (row - 1) * cols + col
                suffix = "" if axis_index == 1 else str(axis_index)
                fig.add_annotation(
                    x=i + 0.5, y=1, xref=f"x{suffix}", yref=f"y{suffix} domain", yanchor="top",
                    text=ERA_CHANGE_LABEL.replace(" ", "<br>", 1), showarrow=False, align="center",
                    font=dict(size=font_px - 6 if mode == "print" else 10, color=colors.get("gray", "#5A595B")),
                    bgcolor="rgba(255,255,255,0.85)",
                )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=values,
                mode="markers+text",
                text=[_value_text(value, digits, "") for value in values],
                textposition="top center",
                textfont=dict(size=font_px, color=colors.get("navy", "#0D3C5E")),
                cliponaxis=False,
                # Era anterior: punto hueco con borde marcado.
                marker=dict(
                    size=12,
                    color=["#FFFFFF" if old else steel for old in previous],
                    line=dict(color=steel, width=[3 if old else 1 for old in previous]),
                ),
                customdata=[f"{date:%d/%m/%Y}" for date in dates],
                showlegend=False,
                hovertemplate="%{customdata}: %{y}<extra></extra>",
            ),
            row=row, col=col,
        )
        if band:
            # Despues de la traza: add_hrect saltea subplots sin datos.
            fig.add_hrect(
                y0=float(band[0]), y1=float(band[1]), row=row, col=col,
                fillcolor="rgba(112,140,159,0.22)", line_width=0, layer="below",
            )
        low = min(values + ([float(band[0])] if band else []))
        high = max(values + ([float(band[1])] if band else []))
        pad = (high - low) * 0.25 or abs(high) * 0.1 or 1.0
        # Margen arriba para que la etiqueta de valor no pise el borde.
        # Con "cambio de equipo" arriba, mas aire para que no pise las etiquetas.
        has_era_change = any(
            eras[i] is not None and eras[i + 1] is not None and eras[i] != eras[i + 1] for i in range(len(values) - 1)
        )
        top_pad = pad * (4.6 if has_era_change else 1.8)
        fig.update_yaxes(range=[low - pad * 0.6, high + top_pad], row=row, col=col, showgrid=True, nticks=5)
        fig.update_xaxes(
            tickmode="array", tickvals=x, ticktext=[spanish_month_year(date) for date in dates],
            tickangle=0, range=[-0.5, len(values) - 0.5], row=row, col=col, showgrid=False,
        )
    if mode == "print":
        fig = apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm * rows)
        fig.update_layout(margin=dict(l=60, r=24, t=PRINT_FONT_PX * 2 + 6, b=PRINT_FONT_PX * 2 + 12))
        fig.update_xaxes(showgrid=False, zeroline=False)
        for annotation in fig.layout.annotations:
            if annotation.text in titles:
                annotation.font.size = PRINT_FONT_PX
        return fig
    return apply_chart_mode(fig, "screen", theme=theme, title=EVOLUTION_TITLE, screen_height=300 * rows)


def chart_group_position(
    position: dict[str, object] | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    print_height_mm: float | None = None,
) -> go.Figure | None:
    """Barras horizontales 0-100: punto = percentil, banda = rango por incertidumbre.

    Sin z numerico: solo la posicion entre pares. None sin pruebas con
    referencia.
    """
    if not position or not position.get("bars"):
        return None
    colors = theme["colors"]
    bars = list(position["bars"])[::-1]  # la primera prueba arriba
    labels = [str(bar["label"]) for bar in bars]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=labels, x=[100] * len(bars), orientation="h", marker=dict(color="rgba(112,140,159,0.12)"),
            hoverinfo="skip", showlegend=False, width=0.5,
        )
    )
    band_low = [bar["band"][0] if bar.get("band") else bar["percentile"] for bar in bars]
    band_high = [bar["band"][1] if bar.get("band") else bar["percentile"] for bar in bars]
    fig.add_trace(
        go.Bar(
            y=labels, x=[high - low for low, high in zip(band_low, band_high)], base=band_low, orientation="h",
            marker=dict(color="rgba(19,66,99,0.30)"), hoverinfo="skip", showlegend=False, width=0.5,
        )
    )
    fig.add_trace(
        go.Scatter(
            y=labels,
            x=[bar["percentile"] for bar in bars],
            mode="markers+text",
            marker=dict(size=16, color=colors.get("navy", "#0D3C5E"), line=dict(color="white", width=2)),
            text=[f"{float(bar['percentile']):.0f}" for bar in bars],
            textposition="middle right",
            textfont=dict(size=PRINT_FONT_PX if mode == "print" else 12, color=colors.get("navy", "#0D3C5E")),
            showlegend=False,
            hovertemplate="%{y}: posición %{x:.0f} de 100<extra></extra>",
        )
    )
    fig.add_vline(x=50, line=dict(color=colors.get("gray", "#5A595B"), dash="dot", width=1))
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.update_xaxes(range=[0, 104], tickvals=[0, 25, 50, 75, 100], title_text="Posición (0-100)")
    fig.update_yaxes(automargin=True)
    if mode == "print":
        height = print_height_mm if print_height_mm is not None else 15.0 + 9.0 * len(bars)
        fig = apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=height)
        fig.update_layout(margin=dict(l=20, r=30, t=10, b=PRINT_FONT_PX * 3 + 10), showlegend=False)
        fig.update_yaxes(automargin=True)
        return fig
    return apply_chart_mode(fig, "screen", theme=theme, title=POSITION_TITLE, screen_height=110 + 55 * len(bars))


TOLERANCE_TITLE = "Cómo venís aguantando"
TOLERANCE_SCORE_LABEL = "Bienestar"
TOLERANCE_BAND_LABEL = "Rango habitual (±1 DE, 28 d)"
TOLERANCE_LOAD_LABEL = "Carga semanal (UA)"
FEW_RECORDS_LEGEND = "pocos registros"


def chart_tolerance(
    reading: dict[str, object] | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    print_height_mm: float = 60.0,
) -> go.Figure | None:
    """Bienestar diario (6 semanas) con banda personal y, si hay sRPE, carga semanal en barras.

    Mismo eje temporal; la carga va en el eje derecho. Sin sRPE no hay barras
    (ni eje). Con 3-5 registros: puntos sin banda y la leyenda "pocos
    registros". None sin lectura (< 3 registros).
    """
    if not reading:
        return None
    colors = theme["colors"]
    points = reading.get("points")
    if points is None or len(points) == 0:
        return None
    weekly = reading.get("weekly_load")
    has_load = weekly is not None and len(weekly) > 0
    fig = make_subplots(specs=[[{"secondary_y": has_load}]])
    if has_load:
        fig.add_trace(
            go.Bar(
                x=[pd.Timestamp(week) + pd.Timedelta(days=3) for week in weekly["week_start"]],
                y=[float(value) for value in weekly["load"]],
                width=[6 * 24 * 3600 * 1000] * len(weekly),
                marker=dict(color="rgba(112,140,159,0.28)"),
                name=TOLERANCE_LOAD_LABEL,
                hovertemplate="Semana del %{x|%d/%m}: %{y:.0f} UA<extra></extra>",
            ),
            secondary_y=True,
        )
    full = reading.get("mode") == "completo"
    if full and points["band_mean"].notna().any():
        fig.add_trace(
            go.Scatter(x=points["Date"], y=points["band_high"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=points["Date"], y=points["band_low"], mode="lines", line=dict(width=0), fill="tonexty",
                fillcolor="rgba(47,107,82,0.15)", name=TOLERANCE_BAND_LABEL, hoverinfo="skip",
            ),
            secondary_y=False,
        )
    fig.add_trace(
        go.Scatter(
            x=points["Date"],
            y=points["score"],
            mode="lines+markers" if full else "markers",
            line=dict(color=colors.get("green", "#2F6B52"), width=2.5),
            marker=dict(size=9, color=colors.get("green", "#2F6B52")),
            name=TOLERANCE_SCORE_LABEL + ("" if full else f" — {FEW_RECORDS_LEGEND}"),
            hovertemplate="%{x|%d/%m}: %{y:.0f}/30<extra></extra>",
        ),
        secondary_y=False,
    )
    start = pd.Timestamp(reading["window_start"])
    end = pd.Timestamp(reading["window_end"])
    first_monday = start + pd.Timedelta(days=(7 - start.dayofweek) % 7)
    fig.update_xaxes(
        range=[start, end + pd.Timedelta(days=1)], tickformat="%d/%m", tick0=first_monday,
        dtick=7 * 24 * 3600 * 1000, showgrid=False,
    )
    fig.update_yaxes(range=[0, 30], title_text="bienestar /30", secondary_y=False, zeroline=False)
    if has_load:
        # Las barras ocupan la mitad de abajo: la linea de bienestar es lo principal.
        top = float(max(weekly["load"])) * 2.1
        fig.update_yaxes(range=[0, top], title_text="UA", secondary_y=True, showgrid=False, zeroline=False)
    if mode == "print":
        return apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm)
    return apply_chart_mode(fig, "screen", theme=theme, title=TOLERANCE_TITLE, screen_height=360)
