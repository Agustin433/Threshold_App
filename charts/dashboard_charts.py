"""Reusable evaluation and dashboard charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def _theme_parts(theme: dict) -> tuple[dict, dict, str, str, str, dict]:
    colors = theme["colors"]
    layout = theme["layout"]
    grid = theme["grid"]
    grid_soft = theme["grid_soft"]
    reference_line = theme["reference_line"]
    legend = theme["legend"]
    return colors, layout, grid, grid_soft, reference_line, legend


def chart_radar(df_row: pd.Series, athlete: str, team_mean: dict | None = None, *, theme: dict) -> go.Figure:
    colors, layout, grid, _, reference_line, _ = _theme_parts(theme)
    categories = ["CMJ\nAltura", "SJ\nF.Concentrica", "DJ\nReactividad", "EUR\nElasticidad", "DRI\nInd. Reactivo", "IMTP\nF.Maxima"]
    z_keys = ["CMJ_Z", "SJ_Z", "DJtc_Z", "EUR_Z", "DRI_Z", "IMTP_Z"]

    values = [float(df_row.get(key, 0) or 0) for key in z_keys]
    values_closed = values + [values[0]]
    categories_closed = categories + [categories[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=[1] * len(categories_closed),
            theta=categories_closed,
            fill="toself",
            fillcolor="rgba(112,140,159,0.08)",
            line=dict(color=reference_line, dash="dot", width=1),
            name="±1σ Grupo",
            hoverinfo="skip",
        )
    )

    if team_mean:
        team_values = [float(team_mean.get(key, 0) or 0) for key in z_keys]
        team_closed = team_values + [team_values[0]]
        fig.add_trace(
            go.Scatterpolar(
                r=team_closed,
                theta=categories_closed,
                fill="toself",
                fillcolor="rgba(112,140,159,0.10)",
                line=dict(color=colors["gray"], width=1.5, dash="dash"),
                name="Media Equipo",
            )
        )

    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill="toself",
            fillcolor="rgba(13,60,94,0.16)",
            line=dict(color=colors["steel"], width=2.5),
            name=athlete,
            hovertemplate="<b>%{theta}</b><br>Z: %{r:.2f}σ<extra></extra>",
        )
    )

    fig.update_layout(
        **layout,
        polar=dict(
            radialaxis=dict(
                range=[-3, 3],
                tickvals=[-2, -1, 0, 1, 2],
                ticktext=["-2σ", "-1σ", "Media", "+1σ", "+2σ"],
                gridcolor=grid,
                linecolor=reference_line,
                tickfont=dict(size=8, color=colors["gray"]),
            ),
            angularaxis=dict(tickfont=dict(size=10, color=colors["white"]), gridcolor=grid),
            bgcolor=colors["card"],
        ),
        legend=dict(font=dict(size=9), bgcolor="rgba(254, 254, 254, 0.92)", bordercolor=colors["border"], borderwidth=1),
        title=dict(text=f"<b>Perfil Neuromuscular - {athlete}</b>", font=dict(color=colors["navy"], size=13), x=0.5),
        height=480,
    )
    return fig


def chart_quadrant_cmj_imtp(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = df.dropna(subset=["CMJ_cm", "IMTP_N", "Athlete"])
    if data.empty:
        return go.Figure()

    cmj_med = data["CMJ_cm"].median()
    imtp_med = data["IMTP_N"].median()

    def quadrant(row):
        horizontal = row["CMJ_cm"] >= cmj_med
        vertical = row["IMTP_N"] >= imtp_med
        if horizontal and vertical:
            return "Q1 - Elite"
        if not horizontal and vertical:
            return "Q2 - Alta F.Max"
        if horizontal and not vertical:
            return "Q4 - Explosivo"
        return "Q3 - Deficit General"

    data = data.copy()
    data["Quad"] = data.apply(quadrant, axis=1)
    color_map = {
        "Q1 - Elite": colors["steel"],
        "Q2 - Alta F.Max": colors["yellow"],
        "Q4 - Explosivo": colors["orange"],
        "Q3 - Deficit General": colors["red"],
    }

    fig = go.Figure()
    fig.add_vline(
        x=cmj_med,
        line_dash="dash",
        line_color=reference_line,
        annotation_text=f"Med CMJ {cmj_med:.1f}cm",
        annotation_font=dict(color=colors["gray"], size=9),
    )
    fig.add_hline(
        y=imtp_med,
        line_dash="dash",
        line_color=reference_line,
        annotation_text=f"Med IMTP {imtp_med:.0f}N",
        annotation_font=dict(color=colors["gray"], size=9),
    )

    for quadrant_name, color in color_map.items():
        subset = data[data["Quad"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["CMJ_cm"],
                y=subset["IMTP_N"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].str.split().str[0],
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate="<b>%{text}</b><br>CMJ: %{x:.1f} cm<br>IMTP: %{y:.0f} N<extra></extra>",
            )
        )

    fig.update_layout(
        **layout,
        height=500,
        title=dict(text="<b>Cuadrante CMJ x IMTP - Potencia / Fuerza Maxima</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="CMJ (cm)", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="IMTP (N)", gridcolor=grid_soft, zeroline=False),
        legend=legend,
    )
    return fig


def chart_quadrant_dri_sj(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = df.dropna(subset=["DRI", "SJ_cm", "Athlete"])
    if data.empty:
        return go.Figure()

    dri_med = data["DRI"].median()
    sj_med = data["SJ_cm"].median()

    def quadrant(row):
        horizontal = row["DRI"] >= dri_med
        vertical = row["SJ_cm"] >= sj_med
        if horizontal and vertical:
            return "Q1 - Potencia + Reactividad"
        if not horizontal and vertical:
            return "Q2 - Fuerza sin Reactividad"
        if horizontal and not vertical:
            return "Q4 - Reactivo sin Base"
        return "Q3 - Deficit General"

    data = data.copy()
    data["Quad"] = data.apply(quadrant, axis=1)
    color_map = {
        "Q1 - Potencia + Reactividad": colors["green"],
        "Q2 - Fuerza sin Reactividad": colors["yellow"],
        "Q4 - Reactivo sin Base": colors["orange"],
        "Q3 - Deficit General": colors["red"],
    }

    fig = go.Figure()
    fig.add_vline(
        x=dri_med,
        line_dash="dash",
        line_color=reference_line,
        annotation_text=f"Med DRI {dri_med:.2f}",
        annotation_font=dict(color=colors["gray"], size=9),
    )
    fig.add_hline(
        y=sj_med,
        line_dash="dash",
        line_color=reference_line,
        annotation_text=f"Med SJ {sj_med:.1f}cm",
        annotation_font=dict(color=colors["gray"], size=9),
    )

    for quadrant_name, color in color_map.items():
        subset = data[data["Quad"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["DRI"],
                y=subset["SJ_cm"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].str.split().str[0],
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate="<b>%{text}</b><br>DRI: %{x:.2f}<br>SJ: %{y:.1f} cm<extra></extra>",
            )
        )

    fig.update_layout(
        **layout,
        height=500,
        title=dict(text="<b>Cuadrante DRI x SJ - CEA Reactivo / Concentrico</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="DRI (u.a.)", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="SJ (cm)", gridcolor=grid_soft, zeroline=False),
        legend=legend,
    )
    return fig


def chart_cmj_trend(jump_df: pd.DataFrame, athlete: str, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    data = jump_df[jump_df["Athlete"] == athlete].sort_values("Date")
    if data.empty:
        return go.Figure()

    baseline = data["CMJ_cm"].mean()
    fig = go.Figure()
    fig.add_hrect(
        y0=baseline * 0.95,
        y1=baseline * 1.05,
        fillcolor="rgba(111,143,120,0.10)",
        line_width=0,
        annotation_text="±5% Baseline",
        annotation_font_color=colors["gray"],
        annotation_font_size=9,
    )
    fig.add_hline(y=baseline, line_dash="dash", line_color=colors["gray"], annotation_text=f"BL {baseline:.1f}cm")
    fig.add_trace(
        go.Scatter(
            x=data["Date"],
            y=data["CMJ_cm"],
            mode="lines+markers",
            line=dict(color=colors["steel"], width=2.5),
            marker=dict(
                size=8,
                color=[
                    colors["red"] if abs((value - baseline) / baseline * 100) > 5 else colors["green"]
                    for value in data["CMJ_cm"]
                ],
                line=dict(color=colors["card"], width=1),
            ),
            hovertemplate="%{x|%d/%m/%Y}<br>CMJ: %{y:.1f} cm<extra></extra>",
            name="CMJ",
        )
    )
    fig.update_layout(
        **layout,
        height=340,
        title=dict(text=f"<b>Tendencia CMJ - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="cm", gridcolor=grid_soft, zeroline=False),
    )
    return fig
