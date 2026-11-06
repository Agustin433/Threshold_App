"""Cuadrante Fuerza vs Explosividad del gimnasio (IMTP vs CMJ por vuelo, % de la meta).

Una funcion para dashboard, PDF profe y PDF atleta/cliente. Los datos salen de
`modules.strength_quadrant.build_quadrant_map`.
"""

from __future__ import annotations

import plotly.graph_objects as go

from charts.report_charts import PRINT_FONT_PX, ChartMode, apply_chart_mode
from modules.strength_quadrant import (
    AGE_GROUPS,
    AGE_UNKNOWN,
    QUADRANT_BASE,
    QUADRANT_COMPLETE,
    QUADRANT_EXPLOSIVE,
    QUADRANT_STRONG,
    QuadrantMap,
    short_name,
)

QUADRANT_TITLE = "Fuerza vs Explosividad del gimnasio"
X_TITLE = "Fuerza máxima (IMTP relativo, % de la meta)"
Y_TITLE = "Salto (CMJ por vuelo, % de la meta)"
AGE_COLORS = {
    "<18": "#2F6B52",
    "18-29": "#134263",
    "30-44": "#C4A464",
    "45+": "#B56B73",
    AGE_UNKNOWN: "#9A9A9A",
}
ANONYMOUS_COLOR = "#B8C2CC"
FLAGGED_ALPHA = 0.35
ROUTE_LABEL = "tu recorrido"


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _axis_range(values: list[float]) -> list[float]:
    low = min([60.0] + values) - 10.0
    high = max([140.0] + values) + 10.0
    return [max(0.0, low), high]


_LABEL_POSITIONS = ("top center", "bottom center", "middle right", "middle left")


def _label_positions(points: list[tuple[float, float, str]], x_span: float, y_span: float) -> list[str]:
    """Posicion de cada rotulo evitando pisar los ya ubicados (cajas aproximadas)."""
    boxes: list[tuple[float, float, float, float]] = []
    chosen: list[str] = []
    char_w, height = x_span * 0.011, y_span * 0.045
    for x, y, label in points:
        width = max(1, len(label)) * char_w
        best, best_overlap = _LABEL_POSITIONS[0], None
        for position in _LABEL_POSITIONS:
            if position == "top center":
                box = (x - width / 2, x + width / 2, y + height * 0.4, y + height * 1.4)
            elif position == "bottom center":
                box = (x - width / 2, x + width / 2, y - height * 1.4, y - height * 0.4)
            elif position == "middle right":
                box = (x + x_span * 0.012, x + x_span * 0.012 + width, y - height / 2, y + height / 2)
            else:
                box = (x - x_span * 0.012 - width, x - x_span * 0.012, y - height / 2, y + height / 2)
            overlap = sum(
                max(0.0, min(box[1], b[1]) - max(box[0], b[0])) * max(0.0, min(box[3], b[3]) - max(box[2], b[2]))
                for b in boxes
            )
            if best_overlap is None or overlap < best_overlap:
                best, best_overlap, best_box = position, overlap, box
            if overlap == 0:
                break
        boxes.append(best_box)
        chosen.append(best)
    return chosen


def chart_strength_quadrant(
    quadrant_map: QuadrantMap | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    highlight: str | None = None,
    anonymous: bool = False,
    print_height_mm: float = 105.0,
) -> go.Figure | None:
    """Mapa del gimnasio. Lineas al 100% de la meta; meta = "Completo".

    - `anonymous=False` (dashboard y PDF profe): todos con nombre.
    - `anonymous=True` + `highlight` (PDF atleta/cliente): solo el atleta con
      nombre; el resto, puntos sin rotulo.
    - Relleno claro: protocolo anterior o evaluacion de mas de 12 semanas.
    - Flecha de la ubicacion anterior a la actual (punteada si cruza protocolos):
      del atleta resaltado, o de todos en la vista profe.
    """
    if quadrant_map is None or not quadrant_map.placements:
        return None
    colors = theme["colors"]
    placements = quadrant_map.placements
    key = str(highlight or "").strip().casefold()
    xs = [p.pct_imtp for p in placements] + [h.pct_imtp for p in placements for h in p.history]
    ys = [p.pct_cmj for p in placements] + [h.pct_cmj for p in placements for h in p.history]
    x_range, y_range = _axis_range(xs), _axis_range(ys)
    font_px = PRINT_FONT_PX if mode == "print" else 12

    fig = go.Figure()
    # Zona meta ("Completo") sombreada; las demas sin relleno.
    fig.add_shape(
        type="rect", x0=100, x1=x_range[1], y0=100, y1=y_range[1], layer="below", line_width=0,
        fillcolor="rgba(47,107,82,0.08)",
    )
    fig.add_vline(x=100, line=dict(color=colors.get("navy", "#0D3C5E"), width=1.5, dash="dash"))
    fig.add_hline(y=100, line=dict(color=colors.get("navy", "#0D3C5E"), width=1.5, dash="dash"))
    corner_labels = (
        (x_range[1], y_range[1], "right", "top", QUADRANT_COMPLETE),
        (x_range[1], y_range[0], "right", "bottom", QUADRANT_STRONG),
        (x_range[0], y_range[1], "left", "top", QUADRANT_EXPLOSIVE),
        (x_range[0], y_range[0], "left", "bottom", QUADRANT_BASE),
    )
    for x, y, xanchor, yanchor, text in corner_labels:
        fig.add_annotation(
            x=x, y=y, text=f"<b>{text}</b>", showarrow=False, xanchor=xanchor, yanchor=yanchor,
            font=dict(size=font_px, color=colors.get("gray", "#5A595B")),
        )

    # Recorridos: de la ubicacion anterior a la actual.
    for placement in placements:
        if not placement.history:
            continue
        if anonymous and placement.athlete.casefold() != key:
            continue
        previous = placement.history[-1]
        fig.add_trace(
            go.Scatter(
                x=[previous.pct_imtp, placement.pct_imtp],
                y=[previous.pct_cmj, placement.pct_cmj],
                mode="lines+markers",
                line=dict(
                    color=colors.get("gray", "#5A595B"), width=1.6,
                    dash="dot" if placement.crosses_protocol else "solid",
                ),
                marker=dict(symbol=["circle-open", "arrow"], angleref="previous", size=[8, 14],
                            color=colors.get("gray", "#5A595B")),
                showlegend=False,
                hoverinfo="skip",
                name=ROUTE_LABEL,
            )
        )

    # Rotulos cortos ('Ignacio D.') ubicados para no pisarse.
    label_of = {
        p.athlete: (short_name(p.athlete) if (not anonymous or p.athlete.casefold() == key) else "")
        for p in placements
    }
    ordered = sorted(placements, key=lambda p: (-p.pct_cmj, p.pct_imtp))
    positions = dict(
        zip(
            [p.athlete for p in ordered],
            _label_positions(
                [(p.pct_imtp, p.pct_cmj, label_of[p.athlete]) for p in ordered],
                x_range[1] - x_range[0],
                y_range[1] - y_range[0],
            ),
        )
    )

    # Puntos por grupo de edad (una entrada de leyenda por grupo presente).
    for group in (*AGE_GROUPS, AGE_UNKNOWN):
        members = [p for p in placements if p.age_group == group]
        if not members:
            continue
        base = AGE_COLORS[group]
        labels, fills, sizes, borders = [], [], [], []
        for placement in members:
            is_highlight = placement.athlete.casefold() == key
            show_name = (not anonymous) or is_highlight
            labels.append(label_of[placement.athlete] if show_name else "")
            color = base if (not anonymous or is_highlight) else ANONYMOUS_COLOR
            fills.append(_rgba(color, FLAGGED_ALPHA) if placement.flagged else color)
            borders.append("#000000" if is_highlight else color)
            sizes.append(18 if is_highlight else 12)
        fig.add_trace(
            go.Scatter(
                x=[p.pct_imtp for p in members],
                y=[p.pct_cmj for p in members],
                mode="markers+text",
                text=labels,
                textposition=[positions[p.athlete] for p in members],
                textfont=dict(size=font_px - 2 if mode == "print" else 11, color=colors.get("navy", "#0D3C5E")),
                marker=dict(size=sizes, color=fills, line=dict(color=borders, width=2)),
                name=group if group == AGE_UNKNOWN else f"{group} años",
                customdata=[[p.athlete, p.quadrant, p.note(professional=True) or ""] for p in members],
                hovertemplate="<b>%{customdata[0]}</b><br>IMTP %{x:.0f}% · CMJ %{y:.0f}%<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>"
                if not anonymous
                else "%{x:.0f}% · %{y:.0f}%<extra></extra>",
                showlegend=not anonymous,
            )
        )

    fig.update_xaxes(range=x_range, title_text=X_TITLE, zeroline=False, ticksuffix="%")
    fig.update_yaxes(range=y_range, title_text=Y_TITLE, zeroline=False, ticksuffix="%")
    fig.add_annotation(
        text="<b>Metas</b> — " + "<br>".join(quadrant_map.legend_lines), x=0, y=1.0, xref="paper", yref="paper", yanchor="bottom", xanchor="left",
        showarrow=False, align="left", font=dict(size=font_px - 4 if mode == "print" else 11, color=colors.get("gray", "#5A595B")),
    )
    if mode == "print":
        fig = apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm)
        fig.update_layout(margin=dict(t=PRINT_FONT_PX * 3 + 10))
        return fig
    return apply_chart_mode(fig, "screen", theme=theme, title=QUADRANT_TITLE, screen_height=560)
