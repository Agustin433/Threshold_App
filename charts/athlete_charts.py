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


def chart_athlete_evolution(
    series: list[dict[str, object]] | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    print_height_mm: float = 62.0,
) -> go.Figure | None:
    """Una linea por prueba (columnas lado a lado), un punto por toma con fecha y valor.

    El eje X tiene un lugar por evaluacion (no es proporcional al tiempo).
    Banda sombreada = primera toma +/- max(TE, SWC): lo que queda dentro no es
    un cambio distinguible del error de medicion. None sin series (1 sola
    evaluacion): no se dibuja un grafico de un punto.
    """
    if not series:
        return None
    colors = theme["colors"]
    titles = [str(item["label"]) + (f" ({item['unit']})" if item.get("unit") else "") for item in series]
    fig = make_subplots(rows=1, cols=len(series), subplot_titles=titles, horizontal_spacing=0.09)
    font_px = PRINT_FONT_PX if mode == "print" else 12
    for index, item in enumerate(series, start=1):
        dates = [pd.Timestamp(date) for date in item["dates"]]
        values = [float(value) for value in item["values"]]
        digits = int(item.get("digits", 1))
        band = item.get("band")
        # Un punto por evaluacion (eje de categorias): tomas cercanas en el
        # tiempo no se pisan; la fecha va en el rotulo de cada punto.
        categories = [f"{date:%d/%m/%y}" for date in dates]
        fig.add_trace(
            go.Scatter(
                x=categories,
                y=values,
                mode="lines+markers+text",
                text=[_value_text(value, digits, "") for value in values],
                textposition="top center",
                textfont=dict(size=font_px, color=colors.get("navy", "#0D3C5E")),
                line=dict(color=colors.get("steel", "#134263"), width=3),
                marker=dict(size=10, color=colors.get("steel", "#134263")),
                showlegend=False,
                hovertemplate="%{x|%d/%m/%Y}: %{y}<extra></extra>",
            ),
            row=1,
            col=index,
        )
        if band:
            # Despues de la traza: add_hrect saltea subplots sin datos.
            fig.add_hrect(
                y0=float(band[0]), y1=float(band[1]), row=1, col=index,
                fillcolor="rgba(112,140,159,0.22)", line_width=0, layer="below",
            )
        low = min(values + ([float(band[0])] if band else []))
        high = max(values + ([float(band[1])] if band else []))
        pad = (high - low) * 0.25 or abs(high) * 0.1 or 1.0
        fig.update_yaxes(range=[low - pad * 0.6, high + pad * 1.4], row=1, col=index, showgrid=True)
        fig.update_xaxes(type="category", tickangle=0, range=[-0.4, len(categories) - 0.6], row=1, col=index)
    if mode == "print":
        fig = apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm)
        fig.update_layout(margin=dict(l=60, r=20, t=PRINT_FONT_PX * 2 + 6, b=PRINT_FONT_PX * 2 + 12))
        fig.update_annotations(font_size=PRINT_FONT_PX)
        return fig
    return apply_chart_mode(fig, "screen", theme=theme, title=EVOLUTION_TITLE, screen_height=320)


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
        height = print_height_mm if print_height_mm is not None else 18.0 + 11.0 * len(bars)
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
