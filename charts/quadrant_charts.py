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
FLAGGED_LEGEND = "Hueco: era anterior o +12 sem."
ROUTE_LABEL = "tu recorrido"


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _axis_range(values: list[float]) -> list[float]:
    low = min([60.0] + values) - 10.0
    high = max([140.0] + values) + 10.0
    return [max(0.0, low), high]


_LABEL_POSITIONS = (
    "top center",
    "bottom center",
    "middle right",
    "middle left",
    "top right",
    "top left",
    "bottom right",
    "bottom left",
)


def initials(athlete: str) -> str:
    """'Ignacio De La Vega' -> 'ID' (rotulo minimo en zonas densas; el hover da el nombre)."""
    parts = [part for part in str(athlete).split() if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:2]
    return f"{parts[0][0]}{parts[1][0]}".upper()


def _label_box(position: str, x: float, y: float, width: float, height: float, gap_x: float) -> tuple[float, float, float, float]:
    """Caja aproximada (x0, x1, y0, y1) del rotulo en coordenadas de datos."""
    vertical, horizontal = position.split()
    if horizontal == "center":
        x0, x1 = x - width / 2, x + width / 2
    elif horizontal == "right":
        x0 = x + gap_x
        x1 = x0 + width
    else:
        x1 = x - gap_x
        x0 = x1 - width
    if vertical == "top":
        y0, y1 = y + height * 0.4, y + height * 1.4
    elif vertical == "bottom":
        y0, y1 = y - height * 1.4, y - height * 0.4
    else:
        y0, y1 = y - height / 2, y + height / 2
    if vertical != "middle" and horizontal != "center":
        # Diagonales: el rotulo arranca pegado al punto, no centrado.
        y0, y1 = (y0 - height * 0.3, y1 - height * 0.3) if vertical == "top" else (y0 + height * 0.3, y1 + height * 0.3)
    return x0, x1, y0, y1


def _overlap(box: tuple[float, float, float, float], others: list[tuple[float, float, float, float]]) -> float:
    return sum(
        max(0.0, min(box[1], b[1]) - max(box[0], b[0])) * max(0.0, min(box[3], b[3]) - max(box[2], b[2]))
        for b in others
    )


_FAR_DIRECTIONS = (
    (0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (-1.0, 0.0),
    (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7),
)
_FAR_RADII = (2.0, 3.2, 4.4, 5.6)


def _label_layout(
    points: list[tuple[float, float, str, str]],
    x_span: float,
    y_span: float,
    bounds: tuple[float, float, float, float] | None = None,
    guides: tuple[float, float] | None = None,
) -> list[dict[str, object]]:
    """Donde va cada rotulo para no pisar otros rotulos ni puntos.

    `points` = (x, y, rotulo corto, rotulo minimo). Orden de preferencia:
    1. pegado al punto (8 posiciones) con el rotulo corto;
    2. pegado al punto con el rotulo minimo (iniciales);
    3. desplazado con linea guia (iniciales), en anillos crecientes;
    4. si nada queda libre, la opcion pegada de menor superposicion.
    Devuelve por punto: {"kind": "near"|"far", "position", "text", "box",
    "anchor"} (anchor = posicion del texto desplazado, en datos).
    `guides` = (x, y) de las lineas de referencia: el texto no se apoya encima.
    """
    char_w, height = x_span * 0.011, y_span * 0.045
    gap_x = x_span * 0.012
    marker_w, marker_h = x_span * 0.010, y_span * 0.016
    unit_x, unit_y = x_span * 0.035, y_span * 0.06
    x_min, x_max, y_min, y_max = bounds if bounds is not None else (float("-inf"), float("inf"), float("-inf"), float("inf"))

    def _inside(box: tuple[float, float, float, float]) -> bool:
        return box[0] >= x_min and box[1] <= x_max and box[2] >= y_min and box[3] <= y_max

    # Los puntos tambien son obstaculos: un rotulo no puede tapar a otro atleta.
    marker_boxes = [(x - marker_w, x + marker_w, y - marker_h, y + marker_h) for x, y, _, _ in points]
    placed: list[tuple[float, float, float, float]] = []
    if guides is not None:
        guide_x, guide_y = guides
        placed += [
            (guide_x - x_span * 0.002, guide_x + x_span * 0.002, y_min, y_max),
            (x_min, x_max, guide_y - y_span * 0.004, guide_y + y_span * 0.004),
        ]
    result: list[dict[str, object]] = []
    for index, (x, y, label, minimal) in enumerate(points):
        if not label:
            result.append({"kind": "near", "position": _LABEL_POSITIONS[0], "text": "", "box": None, "anchor": None})
            continue
        minimal = minimal or label
        obstacles = placed + [box for other, box in enumerate(marker_boxes) if other != index]
        choice: dict[str, object] | None = None
        fallback: tuple[float, dict[str, object]] | None = None
        for text in dict.fromkeys([label, minimal]):
            width = max(1, len(text)) * char_w
            for position in _LABEL_POSITIONS:
                box = _label_box(position, x, y, width, height, gap_x)
                overlap = _overlap(box, obstacles) + (0.0 if _inside(box) else 1e6)
                candidate = {"kind": "near", "position": position, "text": text, "box": box, "anchor": None}
                if overlap == 0:
                    choice = candidate
                    break
                if fallback is None or overlap < fallback[0]:
                    fallback = (overlap, candidate)
            if choice is not None:
                break
        if choice is None:
            width = max(1, len(minimal)) * char_w
            for radius in _FAR_RADII:
                for dx, dy in _FAR_DIRECTIONS:
                    ax, ay = x + dx * radius * unit_x, y + dy * radius * unit_y
                    box = (ax - width / 2, ax + width / 2, ay - height / 2, ay + height / 2)
                    if _inside(box) and _overlap(box, obstacles) == 0:
                        choice = {"kind": "far", "position": "middle center", "text": minimal, "box": box, "anchor": (ax, ay)}
                        break
                if choice is not None:
                    break
        if choice is None:
            assert fallback is not None
            choice = fallback[1]
        placed.append(choice["box"])  # type: ignore[arg-type]
        result.append(choice)
    return result


def chart_strength_quadrant(
    quadrant_map: QuadrantMap | None,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    highlight: str | None = None,
    anonymous: bool = False,
    print_height_mm: float = 105.0,
    show_goals: bool = True,
) -> go.Figure | None:
    """Mapa del gimnasio. Lineas al 100% de la meta; meta = "Completo".

    - `anonymous=False` (dashboard y PDF profe): todos con nombre.
    - `anonymous=True` + `highlight` (PDF atleta/cliente): solo el atleta con
      nombre; el resto, puntos sin rotulo.
    - Relleno claro: protocolo anterior o evaluacion de mas de 12 semanas.
    - Flecha de la ubicacion anterior a la actual (punteada si cruza protocolos):
      del atleta resaltado, o de todos en la vista profe.
    - Metas: en pantalla, texto arriba del grafico (`show_goals`); impreso
      nunca dentro del grafico: el PDF las pone como nota debajo.
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
    # En zonas densas el rotulo pasa a iniciales; el nombre completo queda en el hover.
    layout = _label_layout(
        [
            (
                p.pct_imtp,
                p.pct_cmj,
                label_of[p.athlete],
                # PDF atleta/cliente: el unico rotulo (el propio) nunca se abrevia.
                label_of[p.athlete] if anonymous else (initials(p.athlete) if label_of[p.athlete] else ""),
            )
            for p in ordered
        ],
        x_range[1] - x_range[0],
        y_range[1] - y_range[0],
        bounds=(x_range[0], x_range[1], y_range[0], y_range[1]),
        guides=(100.0, 100.0),
    )
    positions = {p.athlete: str(item["position"]) for p, item in zip(ordered, layout)}
    # Rotulo desplazado: el punto queda sin texto y el rotulo va con linea guia.
    label_of = {p.athlete: (str(item["text"]) if item["kind"] == "near" else "") for p, item in zip(ordered, layout)}
    for placement, item in zip(ordered, layout):
        if item["kind"] != "far":
            continue
        anchor_x, anchor_y = item["anchor"]  # type: ignore[misc]
        fig.add_annotation(
            x=placement.pct_imtp, y=placement.pct_cmj, ax=anchor_x, ay=anchor_y, axref="x", ayref="y",
            text=str(item["text"]), showarrow=True, arrowhead=0, arrowwidth=0.8, standoff=6,
            arrowcolor=colors.get("gray", "#5A595B"),
            font=dict(size=font_px - 2 if mode == "print" else 11, color=colors.get("navy", "#0D3C5E")),
            hovertext=placement.athlete,
        )

    # Puntos por grupo de edad (una entrada de leyenda por grupo presente).
    for group in (*AGE_GROUPS, AGE_UNKNOWN):
        members = [p for p in placements if p.age_group == group]
        if not members:
            continue
        base = AGE_COLORS[group]
        labels, fills, sizes, borders, widths = [], [], [], [], []
        for placement in members:
            is_highlight = placement.athlete.casefold() == key
            show_name = (not anonymous) or is_highlight
            labels.append(label_of[placement.athlete] if show_name else "")
            color = base if (not anonymous or is_highlight) else ANONYMOUS_COLOR
            # Era anterior o evaluacion vieja: hueco con borde grueso (se
            # distingue impreso en blanco y negro, no solo por el tono).
            fills.append("#FFFFFF" if placement.flagged else color)
            borders.append("#000000" if is_highlight else color)
            sizes.append(18 if is_highlight else 12)
            widths.append(3.5 if placement.flagged else 2)
        fig.add_trace(
            go.Scatter(
                x=[p.pct_imtp for p in members],
                y=[p.pct_cmj for p in members],
                mode="markers+text",
                text=labels,
                textposition=[positions[p.athlete] for p in members],
                textfont=dict(size=font_px - 2 if mode == "print" else 11, color=colors.get("navy", "#0D3C5E")),
                marker=dict(size=sizes, color=fills, line=dict(color=borders, width=widths)),
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
    if any(p.flagged for p in placements):
        # Leyenda corta del punto hueco (tambien en la version anonima).
        fig.add_trace(
            go.Scatter(
                x=[None], y=[None], mode="markers", name=FLAGGED_LEGEND,
                marker=dict(size=12, color="#FFFFFF", line=dict(color=colors.get("gray", "#5A595B"), width=3.5)),
                showlegend=True, hoverinfo="skip",
            )
        )
    # Impreso, las metas van como nota debajo del grafico (no se cortan ni
    # pisan los rotulos de los cuadrantes).
    if show_goals and mode != "print":
        fig.add_annotation(
            text="<b>Metas</b> — " + "<br>".join(quadrant_map.legend_lines), x=0, y=1.0, xref="paper", yref="paper", yanchor="bottom", xanchor="left",
            showarrow=False, align="left", font=dict(size=font_px - 4 if mode == "print" else 11, color=colors.get("gray", "#5A595B")),
        )
    if mode == "print":
        fig = apply_chart_mode(fig, "print", theme=theme, title=None, print_height_mm=print_height_mm)
        fig.update_layout(margin=dict(t=16))
        return fig
    return apply_chart_mode(fig, "screen", theme=theme, title=QUADRANT_TITLE, screen_height=560)
