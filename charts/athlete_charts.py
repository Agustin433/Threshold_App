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
