"""Reusable evaluation and dashboard charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from modules.jump_analysis import (
    _prepare_jump_df,
    _available_radar_axes,
    build_composite_profile_metric_rows,
    choose_secondary_quadrant_x_spec,
    classify_neuromuscular_quadrant,
    compute_baseline_delta,
    resolve_zscore,
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


def _empty_state_figure(*, theme: dict, title: str, message: str, height: int = 480) -> go.Figure:
    colors, layout, _, _, _, _ = _theme_parts(theme)
    fig = go.Figure()
    fig.update_layout(
        **layout,
        height=height,
        title=dict(text=title, font=dict(color=colors["navy"], size=13)),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                align="center",
                font=dict(color=colors["muted"], size=13),
            )
        ],
    )
    return fig


def _prepare_frame(df: pd.DataFrame, profile_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if "Athlete" not in df.columns or "Date" not in df.columns:
        return df.copy()
    if "Profile_Composed" in df.columns and df["Profile_Composed"].fillna(False).astype(bool).any():
        return df.copy()

    prepared = _prepare_jump_df(df, profile_df=profile_df)
    return prepared if not prepared.empty else df.copy()


def _dri_missing_message(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "No hay datos suficientes para construir este grafico."

    dj_cm = pd.to_numeric(df.get("DJ_cm"), errors="coerce") if "DJ_cm" in df.columns else pd.Series(dtype=float)
    dj_tc = pd.to_numeric(df.get("DJ_tc_ms"), errors="coerce") if "DJ_tc_ms" in df.columns else pd.Series(dtype=float)
    drop_height = (
        pd.to_numeric(df.get("DJ_drop_height_cm"), errors="coerce")
        if "DJ_drop_height_cm" in df.columns
        else pd.Series(dtype=float)
    )
    dri = pd.to_numeric(df.get("DRI"), errors="coerce") if "DRI" in df.columns else pd.Series(dtype=float)

    has_dj_context = dj_cm.notna().any() and dj_tc.notna().any()
    has_drop_height = drop_height.notna().any() and (drop_height > 0).any()
    has_dri = dri.notna().any()

    if has_dj_context and not has_drop_height:
        return (
            "No hay DRI valido para graficar.<br>"
            "Completa la altura de caida (DJ drop height) en las evaluaciones DJ."
        )
    if has_dj_context and not has_dri:
        return (
            "Todavia no hay DRI suficiente para este grafico.<br>"
            "Revisa que las evaluaciones DJ tengan salto, tiempo de contacto y altura de caida."
        )
    return "No hay suficientes datos de DRI y SJ con z-score valido para construir este cuadrante."


def _rsi_missing_message(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "No hay datos suficientes para construir este grafico."

    dj_rsi = pd.to_numeric(df.get("DJ_RSI"), errors="coerce") if "DJ_RSI" in df.columns else pd.Series(dtype=float)
    sj = pd.to_numeric(df.get("SJ_cm"), errors="coerce") if "SJ_cm" in df.columns else pd.Series(dtype=float)

    if dj_rsi.notna().any() and sj.notna().any():
        return "Todavia no hay suficientes z-scores validos de DJ RSI y SJ para construir este cuadrante."
    return "No hay suficientes datos de DJ RSI y SJ para construir este cuadrante."


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


def _quadrant_classification(row: pd.Series, x_col: str, y_col: str) -> dict[str, object]:
    return classify_neuromuscular_quadrant(
        resolve_zscore(row, x_col),
        resolve_zscore(row, y_col),
    )


def _quadrant_chart_category(
    quadrant_payload: dict[str, object],
    *,
    both_high: str,
    x_low_y_high: str,
    x_high_y_low: str,
    both_low: str,
) -> str:
    x_zone = str(quadrant_payload.get("x_zone") or "missing")
    y_zone = str(quadrant_payload.get("y_zone") or "missing")
    if "missing" in (x_zone, y_zone):
        return "Sin datos"
    if "mid" in (x_zone, y_zone):
        return "Zona media / transicion"
    if x_zone == "high" and y_zone == "high":
        return both_high
    if x_zone == "low" and y_zone == "high":
        return x_low_y_high
    if x_zone == "high" and y_zone == "low":
        return x_high_y_low
    return both_low


def _resolve_radar_axes(row: pd.Series) -> tuple[pd.Series, list[tuple[str, str, str, str]], list[float], list[str]]:
    prepared_row = _prepare_row(row)
    axes, notes = _available_radar_axes(prepared_row)

    valid_axes: list[tuple[str, str, str, str]] = []
    values: list[float] = []
    for axis in axes:
        value = resolve_zscore(prepared_row, axis[3])
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
    for metric in build_composite_profile_metric_rows(row):
        label = str(metric.get("Variable", ""))
        value_col = str(metric.get("value_col", ""))
        unit = str(metric.get("Unidad", ""))
        raw_value = _numeric_value(row.get(value_col))
        z_value = _numeric_value(metric.get("Z-score"))
        if raw_value is not None:
            available_metric_count += 1
        categories.append(label)
        values.append(z_value if z_value is not None else missing_point_r)
        formatted_value = str(metric.get("Valor", "-") or "-")
        formatted_z = "-" if z_value is None else f"{z_value:.2f}"
        source_date = metric.get("Origen / referencia", "-") or "-"
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


def chart_quadrant_rsi_sj(df: pd.DataFrame, *, theme: dict, profile_df: pd.DataFrame | None = None) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    source_data = _prepare_frame(df, profile_df=profile_df)
    data = source_data.copy()
    data = data[data["Athlete"].notna()].copy() if "Athlete" in data.columns else pd.DataFrame()
    if not data.empty:
        data["DJ_RSI_Z_plot"] = data.apply(lambda row: resolve_zscore(row, "DJ_RSI_Z"), axis=1)
        data["SJ_Z_plot"] = data.apply(lambda row: resolve_zscore(row, "SJ_Z"), axis=1)
        data = data.dropna(subset=["DJ_RSI_Z_plot", "SJ_Z_plot"])
    if data.empty:
        return _empty_state_figure(
            theme=theme,
            title="<b>Cuadrante Principal - SJ z vs DJ RSI z</b>",
            message=_rsi_missing_message(source_data),
            height=500,
        )

    color_map = {
        "Completo": colors["green"],
        "Fuerza/Propulsion - RSI limitado": colors["yellow"],
        "Reactivo - techo de fuerza bajo": colors["orange"],
        "Deficit global": colors["red"],
        "Zona media / transicion": colors["gray"],
    }

    data = data.copy()
    data["QuadrantData"] = data.apply(lambda row: _quadrant_classification(row, "DJ_RSI_Z", "SJ_Z"), axis=1)
    data["Quadrant"] = data["QuadrantData"].apply(
        lambda payload: _quadrant_chart_category(
            payload,
            both_high="Completo",
            x_low_y_high="Fuerza/Propulsion - RSI limitado",
            x_high_y_low="Reactivo - techo de fuerza bajo",
            both_low="Deficit global",
        )
    )

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)

    for quadrant_name, color in color_map.items():
        subset = data[data["Quadrant"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["DJ_RSI_Z_plot"],
                y=subset["SJ_Z_plot"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].astype(str).str.split().str[0],
                customdata=subset["QuadrantData"].apply(
                    lambda payload: [payload.get("quadrant_label", ""), payload.get("interpretation", "")]
                ).tolist(),
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate=(
                    "<b>%{text}</b><br>DJ RSI z: %{x:.2f}<br>SJ z: %{y:.2f}"
                    "<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>"
                ),
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


def chart_quadrant_dri_sj(df: pd.DataFrame, *, theme: dict, profile_df: pd.DataFrame | None = None) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    source_data = _prepare_frame(df, profile_df=profile_df)
    data = source_data.copy()
    data = data[data["Athlete"].notna()].copy() if "Athlete" in data.columns else pd.DataFrame()
    if not data.empty:
        data["DRI_Z_plot"] = data.apply(lambda row: resolve_zscore(row, "DRI_Z"), axis=1)
        data["SJ_Z_plot"] = data.apply(lambda row: resolve_zscore(row, "SJ_Z"), axis=1)
        data = data.dropna(subset=["DRI_Z_plot", "SJ_Z_plot"])
    if data.empty:
        return _empty_state_figure(
            theme=theme,
            title="<b>Cuadrante Principal - SJ z vs DRI z</b>",
            message=_dri_missing_message(source_data),
            height=500,
        )

    color_map = {
        "Completo": colors["green"],
        "Fuerza/Propulsion - SSC rapido limitado": colors["yellow"],
        "Reactivo - techo de fuerza bajo": colors["orange"],
        "Deficit global": colors["red"],
        "Zona media / transicion": colors["gray"],
    }

    data = data.copy()
    data["QuadrantData"] = data.apply(lambda row: _quadrant_classification(row, "DRI_Z", "SJ_Z"), axis=1)
    data["Quadrant"] = data["QuadrantData"].apply(
        lambda payload: _quadrant_chart_category(
            payload,
            both_high="Completo",
            x_low_y_high="Fuerza/Propulsion - SSC rapido limitado",
            x_high_y_low="Reactivo - techo de fuerza bajo",
            both_low="Deficit global",
        )
    )

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)

    for quadrant_name, color in color_map.items():
        subset = data[data["Quadrant"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["DRI_Z_plot"],
                y=subset["SJ_Z_plot"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].astype(str).str.split().str[0],
                customdata=subset["QuadrantData"].apply(
                    lambda payload: [payload.get("quadrant_label", ""), payload.get("interpretation", "")]
                ).tolist(),
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate=(
                    "<b>%{text}</b><br>DRI z: %{x:.2f}<br>SJ z: %{y:.2f}"
                    "<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        **layout,
        height=500,
        title=dict(text="<b>Cuadrante Principal - SJ z vs DRI z</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="DRI z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        yaxis=dict(title="SJ z", gridcolor=grid_soft, zeroline=False, range=[-2.5, 2.5]),
        legend=legend,
    )
    return fig


def chart_quadrant_cmj_imtp(df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, reference_line, legend = _theme_parts(theme)
    data = _prepare_frame(df)
    x_col, x_label = choose_secondary_quadrant_x_spec(data)
    data = data.copy()
    data = data[data["Athlete"].notna()].copy() if "Athlete" in data.columns else pd.DataFrame()
    if not data.empty:
        data[f"{x_col}_plot"] = data.apply(lambda row: resolve_zscore(row, x_col), axis=1)
        data["IMTP_relPF_Z_plot"] = data.apply(lambda row: resolve_zscore(row, "IMTP_relPF_Z"), axis=1)
        data = data.dropna(subset=[f"{x_col}_plot", "IMTP_relPF_Z_plot"])
    if data.empty:
        return go.Figure()

    color_map = {
        "Alto en ambos": colors["steel"],
        "Base de fuerza > salida": colors["yellow"],
        "Salida > fuerza relativa": colors["orange"],
        "Deficit global": colors["red"],
        "Zona media / transicion": colors["gray"],
    }

    data = data.copy()
    data["QuadrantData"] = data.apply(lambda row: _quadrant_classification(row, x_col, "IMTP_relPF_Z"), axis=1)
    data["Quadrant"] = data["QuadrantData"].apply(
        lambda payload: _quadrant_chart_category(
            payload,
            both_high="Alto en ambos",
            x_low_y_high="Base de fuerza > salida",
            x_high_y_low="Salida > fuerza relativa",
            both_low="Deficit global",
        )
    )

    fig = go.Figure()
    fig.add_vline(x=0, line_dash="dash", line_color=reference_line)
    fig.add_hline(y=0, line_dash="dash", line_color=reference_line)

    for quadrant_name, color in color_map.items():
        subset = data[data["Quadrant"] == quadrant_name]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset[f"{x_col}_plot"],
                y=subset["IMTP_relPF_Z_plot"],
                mode="markers+text",
                marker=dict(size=13, color=color, line=dict(color=colors["card"], width=1.5)),
                text=subset["Athlete"].astype(str).str.split().str[0],
                customdata=subset["QuadrantData"].apply(
                    lambda payload: [payload.get("quadrant_label", ""), payload.get("interpretation", "")]
                ).tolist(),
                textposition="top center",
                textfont=dict(size=9, color=colors["gray"]),
                name=quadrant_name,
                hovertemplate=(
                    f"<b>%{{text}}</b><br>{x_label}: %{{x:.2f}}<br>IMTP relPF z: %{{y:.2f}}"
                    "<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>"
                ),
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
    source_data = _prepare_frame(df)
    data = source_data.dropna(subset=["DRI_Z", "SJ_Z", "Athlete"])
    if data.empty:
        return _empty_state_figure(
            theme=theme,
            title="<b>DRI experimental - interpretar con cautela</b>",
            message=_dri_missing_message(source_data),
            height=460,
        )

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


def make_left_right_force_chart(asymmetry_summary: dict[str, object] | None, *, theme: dict) -> go.Figure | None:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    summary = asymmetry_summary or {}
    left_force = _numeric_value(summary.get("left_force_n"))
    right_force = _numeric_value(summary.get("right_force_n"))

    bars: list[tuple[str, float, str]] = []
    if left_force is not None:
        bars.append(("Izquierda", left_force, colors["steel"]))
    if right_force is not None:
        bars.append(("Derecha", right_force, colors["yellow"]))
    if not bars:
        return None

    fig = go.Figure(
        data=[
            go.Bar(
                x=[item[0] for item in bars],
                y=[item[1] for item in bars],
                marker=dict(color=[item[2] for item in bars], line=dict(color=colors["card"], width=1.2)),
                text=[f"{item[1]:.0f} N" for item in bars],
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>%{y:.0f} N<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        **layout,
        height=320,
        showlegend=False,
        title=dict(text="<b>Fuerza maxima por lado</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="N", gridcolor=grid_soft, zeroline=False),
    )
    return fig


def make_force_time_points_chart(
    force_time_points: list[dict[str, object]] | None,
    *,
    theme: dict,
) -> go.Figure | None:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    points = force_time_points or []
    labels = [str(point.get("label") or "") for point in points]
    values = [_numeric_value(point.get("value_n")) for point in points]
    if not any(value is not None for value in values):
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            connectgaps=False,
            line=dict(color=colors["steel"], width=2.5),
            marker=dict(size=8, color=colors["steel"], line=dict(color=colors["card"], width=1)),
            hovertemplate="<b>%{x}</b><br>%{y:.0f} N<extra></extra>",
            name="Fuerza",
        )
    )
    fig.update_layout(
        **layout,
        height=320,
        showlegend=False,
        title=dict(text="<b>Perfil force-time por puntos</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Ventana exportada", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="N", gridcolor=grid_soft, zeroline=False),
    )
    return fig


def make_rfd_points_chart(rfd_points: list[dict[str, object]] | None, *, theme: dict) -> go.Figure | None:
    colors, layout, _, grid_soft, _, _ = _theme_parts(theme)
    points = rfd_points or []
    filtered_points = [point for point in points if point.get("time_ms") != 200]
    labels = [str(point.get("label") or "") for point in filtered_points]
    values = [_numeric_value(point.get("value_n_s")) for point in filtered_points]
    if not any(value is not None for value in values):
        return None

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker=dict(color=colors["blue"], line=dict(color=colors["card"], width=1.2)),
                hovertemplate="<b>%{x}</b><br>%{y:.0f} N/s<extra></extra>",
                name="RFD",
            )
        ]
    )
    fig.update_layout(
        **layout,
        height=320,
        showlegend=False,
        title=dict(text="<b>RFD por ventana exportada</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Ventana exportada", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="N/s", gridcolor=grid_soft, zeroline=False),
    )
    return fig
