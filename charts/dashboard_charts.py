"""Reusable evaluation and dashboard charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from modules.jump_analysis import (
    COMPOSITE_PROFILE_METRICS,
    _prepare_jump_df,
    _available_radar_axes,
    choose_secondary_quadrant_x_spec,
    compute_baseline_delta,
)


JUMP_HISTORY_METRIC_CONFIG: dict[str, dict[str, object]] = {
    "EUR": {
        "label": "EUR (ratio)",
        "title": "Tendencia EUR",
        "yaxis": "ratio",
        "digits": 3,
        "color": "yellow",
    },
    "DJ_RSI": {
        "label": "DJ RSI",
        "title": "Tendencia DJ RSI",
        "yaxis": "m/s",
        "digits": 3,
        "color": "blue",
    },
    "DJ_cm": {
        "label": "DJ",
        "title": "Tendencia DJ",
        "yaxis": "cm",
        "digits": 1,
        "color": "orange",
    },
}


def _theme_parts(theme: dict) -> tuple[dict, dict, str, str, str, dict]:
    colors = theme["colors"]
    layout = theme["layout"]
    grid = theme["grid"]
    grid_soft = theme["grid_soft"]
    reference_line = theme["reference_line"]
    legend = theme["legend"]
    return colors, layout, grid, grid_soft, reference_line, legend


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if {"SJ_Z", "CMJ_Z"}.issubset(df.columns):
        return df.copy()
    return _prepare_jump_df(df)


def _prepare_row(row: pd.Series) -> pd.Series:
    prepared = _prepare_frame(pd.DataFrame([row.to_dict()]))
    if prepared.empty:
        return row
    return prepared.iloc[0]


def _numeric_value(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _resolve_radar_axes(row: pd.Series) -> tuple[pd.Series, list[tuple[str, str, str, str]], list[float], list[str]]:
    prepared_row = _prepare_row(row)
    axes, notes = _available_radar_axes(prepared_row)

    valid_axes: list[tuple[str, str, str, str]] = []
    values: list[float] = []
    for axis in axes:
        value = _numeric_value(prepared_row.get(axis[3]))
        if value is None:
            continue
        valid_axes.append(axis)
        values.append(value)

    return prepared_row, valid_axes, values, notes


def find_latest_valid_radar_row(jump_df: pd.DataFrame) -> pd.Series | None:
    data = _prepare_frame(jump_df)
    if data.empty:
        return None

    if "Date" in data.columns:
        data = data.sort_values("Date", ascending=False)

    for _, row in data.iterrows():
        _, valid_axes, _, _ = _resolve_radar_axes(row)
        if valid_axes:
            return row

    return None


def chart_radar(df_row: pd.Series, athlete: str, team_mean: dict | None = None, *, theme: dict) -> go.Figure:
    colors, layout, grid, _, reference_line, legend = _theme_parts(theme)
    row, axes, values, notes = _resolve_radar_axes(df_row)
    categories = [axis[0] for axis in axes]
    z_keys = [axis[3] for axis in axes]

    if not categories:
        return go.Figure()

    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]
    polygon_fill = "toself" if len(categories) >= 3 else "none"
    trace_mode = "lines+markers" if len(categories) < 3 else "lines"

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=[1.0] * len(categories_closed),
            theta=categories_closed,
            mode=trace_mode,
            fill="none",
            line=dict(color=reference_line, dash="dot", width=1),
            marker=dict(size=5, color=reference_line),
            name="z = 1",
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
                mode=trace_mode,
                fill=polygon_fill,
                fillcolor="rgba(112,140,159,0.10)",
                line=dict(color=colors["gray"], width=1.5, dash="dash"),
                marker=dict(size=5, color=colors["gray"]),
                name="Media equipo",
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            mode=trace_mode,
            fill=polygon_fill,
            fillcolor="rgba(13,60,94,0.16)",
            line=dict(color=colors["steel"], width=2.5),
            marker=dict(size=7, color=colors["steel"]),
            name=athlete,
            hovertemplate="<b>%{theta}</b><br>Z: %{r:.2f}<extra></extra>",
        )
    )

    title_suffix = f" - {' / '.join(notes)}" if notes else ""
    fig.update_layout(
        **layout,
        polar=dict(
            radialaxis=dict(
                range=[-2.5, 2.5],
                tickvals=[-2, -1, 0, 1, 2],
                ticktext=["-2", "-1", "0", "+1", "+2"],
                gridcolor=grid,
                linecolor=reference_line,
                tickfont=dict(size=8, color=colors["gray"]),
            ),
            angularaxis=dict(tickfont=dict(size=10, color=colors["white"]), gridcolor=grid),
            bgcolor=colors["card"],
        ),
        legend=legend,
        title=dict(text=f"<b>Radar Neuromuscular - {athlete}{title_suffix}</b>", font=dict(color=colors["navy"], size=13), x=0.5),
        height=480,
    )
    return fig


def chart_composite_profile_radar(profile_row: pd.Series, athlete: str, *, theme: dict) -> go.Figure:
    colors, layout, grid, _, reference_line, legend = _theme_parts(theme)
    row = profile_row if isinstance(profile_row, pd.Series) else pd.Series(profile_row)
    radar_min = -2.5
    radar_max = 2.5
    missing_point_r = radar_min

    categories: list[str] = []
    values: list[float] = []
    customdata: list[list[object]] = []
    available_metric_count = 0
    for label, value_col, unit, z_col, digits in COMPOSITE_PROFILE_METRICS:
        raw_value = _numeric_value(row.get(value_col))
        z_value = _numeric_value(row.get(z_col))
        if raw_value is not None:
            available_metric_count += 1
        categories.append(label)
        values.append(z_value if z_value is not None else missing_point_r)
        formatted_raw = "-" if raw_value is None else f"{raw_value:.{digits}f}"
        formatted_value = formatted_raw if raw_value is None or unit in {"", "ratio"} else f"{formatted_raw} {unit}"
        formatted_z = "-" if z_value is None else f"{z_value:.2f}"
        source_date = row.get(f"{value_col}__source_date", "-") or "-"
        customdata.append([formatted_value, formatted_z, source_date])

    fig = go.Figure()
    if available_metric_count < 2:
        fig.update_layout(
            **layout,
            height=480,
            title=dict(text=f"<b>Perfil actual compuesto - {athlete}</b>", font=dict(color=colors["navy"], size=13), x=0.5),
            annotations=[
                dict(
                    text="Sin metricas suficientes con z-score valido para construir un perfil util.",
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                    font=dict(color=colors["muted"], size=13),
                )
            ],
        )
        return fig

    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]
    customdata_closed = customdata + [customdata[0]]

    fig.add_trace(
        go.Scatterpolar(
            r=[1.0] * len(categories_closed),
            theta=categories_closed,
            mode="lines",
            fill="none",
            line=dict(color=reference_line, dash="dot", width=1),
            name="z = 1",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            mode="lines+markers",
            fill="toself",
            fillcolor="rgba(13,60,94,0.16)",
            line=dict(color=colors["steel"], width=2.5),
            marker=dict(size=7, color=colors["steel"]),
            customdata=customdata_closed,
            name=athlete,
            hovertemplate="<b>%{theta}</b><br>Valor: %{customdata[0]}<br>Z-score: %{customdata[1]}<br>Origen: %{customdata[2]}<extra></extra>",
        )
    )
    fig.update_layout(
        **layout,
        polar=dict(
            radialaxis=dict(
                range=[radar_min, radar_max],
                tickvals=[-2, -1, 0, 1, 2],
                ticktext=["-2", "-1", "0", "+1", "+2"],
                gridcolor=grid,
                linecolor=reference_line,
                tickfont=dict(size=8, color=colors["gray"]),
            ),
            angularaxis=dict(tickfont=dict(size=10, color=colors["white"]), gridcolor=grid),
            bgcolor=colors["card"],
        ),
        legend=legend,
        title=dict(text=f"<b>Perfil actual compuesto - {athlete}</b>", font=dict(color=colors["navy"], size=13), x=0.5),
        height=480,
    )
    return fig


def chart_quadrant_dri_sj(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = _prepare_frame(df)
    data = data.dropna(subset=["DJ_RSI_Z", "SJ_Z", "Athlete"])
    if data.empty:
        return go.Figure()

    def quadrant(row: pd.Series) -> str:
        high_x = row["DJ_RSI_Z"] >= 0
        high_y = row["SJ_Z"] >= 0
        if high_x and high_y:
            return "Completo"
        if not high_x and high_y:
            return "Fuerza/Propulsion - SSC rapido limitado"
        if high_x and not high_y:
            return "Reactivo - techo de fuerza bajo"
        return "Deficit global"

    color_map = {
        "Completo": colors["green"],
        "Fuerza/Propulsion - SSC rapido limitado": colors["yellow"],
        "Reactivo - techo de fuerza bajo": colors["orange"],
        "Deficit global": colors["red"],
    }

    data = data.copy()
    data["Quadrant"] = data.apply(quadrant, axis=1)

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)

    for quadrant_name, color in color_map.items():
        subset = data[data["Quadrant"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["DJ_RSI_Z"],
                y=subset["SJ_Z"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].astype(str).str.split().str[0],
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate="<b>%{text}</b><br>DJ RSI z: %{x:.2f}<br>SJ z: %{y:.2f}<extra></extra>",
            )
        )

    fig.update_layout(
        **layout,
        height=500,
        title=dict(text="<b>Cuadrante Principal - SJ z vs DJ RSI z</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="DJ RSI z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        yaxis=dict(title="SJ z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        legend=legend,
    )
    return fig


def chart_quadrant_cmj_imtp(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = _prepare_frame(df)
    x_col, x_label = choose_secondary_quadrant_x_spec(data)
    data = data.dropna(subset=[x_col, "IMTP_relPF_Z", "Athlete"])
    if data.empty:
        return go.Figure()

    def quadrant(row: pd.Series) -> str:
        high_x = row[x_col] >= 0
        high_y = row["IMTP_relPF_Z"] >= 0
        if high_x and high_y:
            return "Alto en ambos"
        if not high_x and high_y:
            return "Base de fuerza > salida"
        if high_x and not high_y:
            return "Salida > fuerza relativa"
        return "Deficit global"

    color_map = {
        "Alto en ambos": colors["steel"],
        "Base de fuerza > salida": colors["yellow"],
        "Salida > fuerza relativa": colors["orange"],
        "Deficit global": colors["red"],
    }

    data = data.copy()
    data["Quadrant"] = data.apply(quadrant, axis=1)

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)

    for quadrant_name, color in color_map.items():
        subset = data[data["Quadrant"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset[x_col],
                y=subset["IMTP_relPF_Z"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].astype(str).str.split().str[0],
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate=f"<b>%{{text}}</b><br>{x_label}: %{{x:.2f}}<br>IMTP relPF z: %{{y:.2f}}<extra></extra>",
            )
        )

    fig.update_layout(
        **layout,
        height=500,
        title=dict(text=f"<b>Cuadrante Secundario - IMTP relPF z vs {x_label}</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title=x_label, gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        yaxis=dict(title="IMTP relPF z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        legend=legend,
    )
    return fig


def chart_quadrant_exploratory(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = _prepare_frame(df)
    data = data.dropna(subset=["DRI_Z", "SJ_Z", "Athlete"])
    if data.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)
    fig.add_trace(
        go.Scatter(
            x=data["DRI_Z"],
            y=data["SJ_Z"],
            mode="markers+text",
            marker=dict(size=12, color=colors["blue"], line=dict(color=colors["card"], width=1.5)),
            text=data["Athlete"].astype(str).str.split().str[0],
            textposition="top center",
            textfont=dict(size=9, color=colors["gray"]),
            name="DRI experimental",
            hovertemplate="<b>%{text}</b><br>DRI z: %{x:.2f}<br>SJ z: %{y:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        **layout,
        height=460,
        title=dict(text="<b>DRI experimental - interpretar con cautela</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="DRI z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        yaxis=dict(title="SJ z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        legend=legend,
    )
    return fig


def chart_cmj_trend(jump_df: pd.DataFrame, athlete: str, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    data = jump_df[jump_df["Athlete"] == athlete].sort_values("Date")
    if data.empty:
        return go.Figure()

    baseline = pd.to_numeric(data["CMJ_cm"], errors="coerce").mean()
    current_dates = pd.to_datetime(data["Date"], errors="coerce").dropna()
    if not current_dates.empty:
        baseline_df = compute_baseline_delta(data, current_dates.max(), variables=["CMJ_cm"])
        if not baseline_df.empty:
            baseline_row = baseline_df.iloc[0]
            baseline_value = pd.to_numeric(pd.Series([baseline_row.get("Baseline_value")]), errors="coerce").iloc[0]
            if pd.notna(baseline_value):
                baseline = float(baseline_value)
    fig = go.Figure()
    fig.add_hrect(
        y0=baseline * 0.95,
        y1=baseline * 1.05,
        fillcolor="rgba(111,143,120,0.10)",
        line_width=0,
        annotation_text="+/-5% baseline",
        annotation_font_color=colors["gray"],
        annotation_font_size=9,
    )
    fig.add_hline(y=baseline, line_dash="dash", line_color=colors["gray"], annotation_text=f"BL {baseline:.1f} cm")
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


def chart_jump_metric_trend(
    jump_df: pd.DataFrame,
    athlete: str,
    metric_key: str,
    *,
    theme: dict,
) -> go.Figure:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    config = JUMP_HISTORY_METRIC_CONFIG.get(metric_key)
    if config is None:
        return go.Figure()

    data = _prepare_frame(jump_df)
    required_cols = {"Athlete", "Date", metric_key}
    if data.empty or not required_cols.issubset(data.columns):
        return go.Figure()

    data = data[data["Athlete"] == athlete][["Date", metric_key]].copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data[metric_key] = pd.to_numeric(data[metric_key], errors="coerce")
    data = data.dropna(subset=["Date", metric_key]).sort_values("Date")
    if data.empty:
        return go.Figure()

    digits = int(config["digits"])
    unit = str(config["yaxis"])
    value_suffix = f" {unit}" if unit else ""

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["Date"],
            y=data[metric_key],
            mode="lines+markers",
            line=dict(color=colors[str(config["color"])], width=2.5),
            marker=dict(
                size=8,
                color=colors[str(config["color"])],
                line=dict(color=colors["card"], width=1),
            ),
            hovertemplate=(
                "%{x|%d/%m/%Y}<br>"
                f"{config['label']}: %{{y:.{digits}f}}{value_suffix}"
                "<extra></extra>"
            ),
            name=str(config["label"]),
        )
    )
    fig.update_layout(
        **layout,
        height=320,
        title=dict(text=f"<b>{config['title']} - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title=unit, gridcolor=grid_soft, zeroline=False),
    )
    return fig
