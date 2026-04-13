"""Reusable load monitoring charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from modules.data_loader import prepare_raw_workouts_df


def _theme_parts(theme: dict) -> tuple[dict, dict, str, str, dict]:
    colors = theme["colors"]
    layout = theme["layout"]
    grid = theme["grid"]
    grid_soft = theme["grid_soft"]
    legend = theme["legend"]
    return colors, layout, grid, grid_soft, legend


def chart_acwr(
    acwr_df: pd.DataFrame,
    athlete: str,
    selected_method: str = "ACWR_EWMA",
    *,
    theme: dict,
) -> go.Figure:
    colors, layout, _, grid_soft, legend = _theme_parts(theme)
    fig = go.Figure()

    band_data = [
        (0.0, 0.8, "rgba(112,140,159,0.10)", "Subcarga"),
        (0.8, 1.3, "rgba(111,143,120,0.10)", "Optimo"),
        (1.3, 1.5, "rgba(196,164,100,0.12)", "Precaucion"),
        (1.5, 3.0, "rgba(181,107,115,0.10)", "Alto riesgo"),
    ]
    for y0, y1, fill, label in band_data:
        fig.add_hrect(
            y0=y0,
            y1=y1,
            fillcolor=fill,
            layer="below",
            line_width=0,
            annotation_text=label,
            annotation_position="right",
            annotation_font=dict(size=9, color=colors["muted"]),
        )

    fig.add_trace(
        go.Bar(
            x=acwr_df["Date"],
            y=acwr_df["sRPE_diario"],
            name="sRPE diario",
            marker_color="rgba(112,140,159,0.35)",
            yaxis="y2",
            hovertemplate="%{x|%d/%m}<br>sRPE: %{y:.0f} UA<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=acwr_df["Date"],
            y=acwr_df["ACWR_EWMA"],
            name="ACWR EWMA",
            mode="lines",
            line=dict(color=colors["steel"], width=3),
            hovertemplate="%{x|%d/%m}<br>ACWR EWMA: %{y:.2f}<extra></extra>",
        )
    )

    srpe_max = acwr_df["sRPE_diario"].max() if not acwr_df.empty else 0
    fig.update_layout(
        **layout,
        title=dict(text=f"<b>ACWR + sRPE Diario - {athlete}</b>", font=dict(size=14, color=colors["navy"])),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="ACWR", range=[0, 2.5], gridcolor=grid_soft, zeroline=False),
        yaxis2=dict(
            title="sRPE (UA)",
            overlaying="y",
            side="right",
            range=[0, srpe_max * 4 if srpe_max > 0 else 10],
            showgrid=False,
            color=colors["muted"],
        ),
        legend=legend,
        height=420,
    )
    return fig


def chart_monotony_strain(w_df: pd.DataFrame, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, _ = _theme_parts(theme)
    monotony_high = theme["monotony_high"]
    required_cols = {"Semana", "Monotonia", "Strain", "Alerta"}
    if not required_cols.issubset(w_df.columns):
        w_df = pd.DataFrame(columns=["Semana", "Monotonia", "Strain", "Alerta"])

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        subplot_titles=["Monotonia (umbral > 2.0)", "Strain semanal"],
        vertical_spacing=0.12,
    )

    bar_colors = [colors["red"] if value else colors["green"] for value in w_df["Alerta"]]
    fig.add_trace(
        go.Bar(
            x=w_df["Semana"],
            y=w_df["Monotonia"],
            marker_color=bar_colors,
            name="Monotonia",
            hovertemplate="%{x|Sem %d/%m}<br>Monotonia: %{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_hline(
        y=monotony_high,
        line_dash="dash",
        line_color=colors["yellow"],
        annotation_text="Limite Foster (2.0)",
        row=1,
        col=1,
        annotation_font_color=colors["yellow"],
    )
    fig.add_trace(
        go.Bar(
            x=w_df["Semana"],
            y=w_df["Strain"],
            marker_color=colors["blue"],
            name="Strain",
            hovertemplate="%{x|Sem %d/%m}<br>Strain: %{y:.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        **layout,
        height=400,
        title=dict(text="<b>Monotonia & Strain - Foster 2001</b>", font=dict(color=colors["navy"], size=13)),
        showlegend=False,
    )
    fig.update_annotations(font=dict(color=colors["gray"], size=11))
    fig.update_yaxes(gridcolor=grid_soft, zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def chart_wellness(w_df: pd.DataFrame, athlete: str, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, legend = _theme_parts(theme)
    if "Date" not in w_df.columns:
        w_df = pd.DataFrame(columns=["Date"])

    fig = go.Figure()
    config = [
        ("Sueno_hs", "Sueno (hs)", colors["blue"]),
        ("Estres", "Estres", colors["yellow"]),
        ("Dolor", "Dolor", colors["red"]),
        ("Wellness_Score", "Score Total", colors["green"]),
    ]
    for column, label, color in config:
        if column in w_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=w_df["Date"],
                    y=w_df[column],
                    name=label,
                    mode="lines+markers",
                    line=dict(color=color, width=2),
                    marker=dict(size=5),
                )
            )
    fig.update_layout(
        **layout,
        height=380,
        title=dict(text=f"<b>Wellness - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="Score / Horas", gridcolor=grid_soft, zeroline=False),
        legend=legend,
    )
    return fig


def chart_volume_by_tag(raw_df: pd.DataFrame, athlete: str, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, legend = _theme_parts(theme)
    prepared = prepare_raw_workouts_df(raw_df)
    required_cols = {"Assigned Date", "Category", "stimulus_category", "Volume_Load_kg", "Contacts", "Exposures"}
    if prepared is None or not required_cols.issubset(prepared.columns):
        fig = go.Figure()
        fig.update_layout(
            **layout,
            height=360,
            title=dict(text="<b>Carga externa por tipo de estimulo</b>", font=dict(color=colors["navy"], size=13)),
            annotations=[
                dict(
                    text="Faltan columnas para graficar la distribucion externa.",
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

    athlete_col = "Athlete" if "Athlete" in prepared.columns else "Name"
    athlete_df = prepared[prepared[athlete_col] == athlete] if athlete_col in prepared.columns else prepared
    athlete_df = athlete_df[
        ~athlete_df["is_invalid"].fillna(False)
        & ~athlete_df["is_untagged"].fillna(False)
    ].copy()

    if athlete_df.empty:
        fig = go.Figure()
        fig.update_layout(
            **layout,
            height=360,
            title=dict(text=f"<b>Carga externa por tipo de estimulo - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
            annotations=[
                dict(
                    text="No hay datos clasificados para el periodo seleccionado.",
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

    athlete_df["Week_Start"] = athlete_df["Assigned Date"].dt.normalize() - pd.to_timedelta(
        athlete_df["Assigned Date"].dt.weekday,
        unit="D",
    )

    sections = [
        {
            "title": "Fuerza con carga",
            "question": "Como se distribuyo el tonelaje por patron",
            "categories": ["strength_loaded"],
            "value_col": "Volume_Load_kg",
            "yaxis": "kg x rep",
        },
        {
            "title": "Pliometria y aterrizajes",
            "question": "Cuantos contactos pliometricos hubo",
            "categories": ["plyo_jump", "landing_mechanics"],
            "value_col": "Contacts",
            "yaxis": "Contactos",
        },
        {
            "title": "Derivados olimpicos",
            "question": "Cuantas exposiciones a DLO",
            "categories": ["olympic_derivatives"],
            "value_col": "Exposures",
            "yaxis": "Exposiciones",
        },
        {
            "title": "Iso y estabilidad",
            "question": "Cuanto trabajo de iso y estabilidad",
            "categories": ["iso", "core_stability"],
            "value_col": "Exposures",
            "yaxis": "Exposiciones",
        },
        {
            "title": "Movilidad y prehab",
            "question": "Cuanta exposicion a prehab y movilidad",
            "categories": ["mobility_prehab"],
            "value_col": "Exposures",
            "yaxis": "Exposiciones",
        },
        {
            "title": "Sprint / COD",
            "question": "Cuantos esfuerzos de sprint y COD",
            "categories": ["sprint_cod"],
            "value_col": "Exposures",
            "yaxis": "Esfuerzos",
        },
    ]

    palette = [
        colors["navy"],
        colors["steel"],
        colors["blue"],
        colors["green"],
        colors["yellow"],
        colors["orange"],
        colors["gray"],
        "#8AA0AE",
        "#B8C2C9",
        "#59758A",
        "#A7B4BC",
        "#C6D0D6",
        "#7F96A6",
    ]

    active_sections: list[dict[str, object]] = []
    for section in sections:
        section_df = athlete_df[
            athlete_df["stimulus_category"].isin(section["categories"])
            & athlete_df[section["value_col"]].notna()
            & athlete_df[section["value_col"]].gt(0)
        ].copy()
        if section_df.empty:
            continue
        grouped = (
            section_df.groupby(["Week_Start", "Category"])[section["value_col"]]
            .sum()
            .reset_index()
        )
        active_sections.append({**section, "grouped": grouped})

    if not active_sections:
        fig = go.Figure()
        fig.update_layout(
            **layout,
            height=360,
            title=dict(text=f"<b>Carga externa por tipo de estimulo - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
            annotations=[
                dict(
                    text="No hay categorias con carga externa util para mostrar.",
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

    fig = make_subplots(
        rows=len(active_sections),
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.08,
        subplot_titles=[
            f"{section['title']} - {section['question']}"
            for section in active_sections
        ],
    )

    color_lookup: dict[str, str] = {}
    palette_index = 0
    for row_index, section in enumerate(active_sections, start=1):
        grouped = section["grouped"]
        category_names = grouped["Category"].dropna().astype(str).unique().tolist()
        for category_name in category_names:
            if category_name not in color_lookup:
                color_lookup[category_name] = palette[palette_index % len(palette)]
                palette_index += 1
            category_df = grouped[grouped["Category"] == category_name]
            fig.add_trace(
                go.Bar(
                    x=category_df["Week_Start"],
                    y=category_df[section["value_col"]],
                    name=category_name,
                    legendgroup=category_name,
                    marker_color=color_lookup[category_name],
                    hovertemplate=f"<b>{category_name}</b><br>Semana: %{{x|%d/%m}}<br>Valor: %{{y:.1f}}<extra></extra>",
                    showlegend=row_index == 1,
                ),
                row=row_index,
                col=1,
            )
        fig.update_yaxes(
            title_text=section["yaxis"],
            gridcolor=grid_soft,
            zeroline=False,
            row=row_index,
            col=1,
        )

    fig.update_layout(
        **layout,
        barmode="stack",
        height=max(340, 240 * len(active_sections)),
        title=dict(text=f"<b>Carga externa por tipo de estimulo - {athlete}</b>", font=dict(color=colors["navy"], size=13)),
        legend=legend,
    )
    for row_index in range(1, len(active_sections) + 1):
        fig.update_xaxes(title="Semana", gridcolor=grid_soft, zeroline=False, row=row_index, col=1)
    return fig


def chart_maxes_trend(maxes_df: pd.DataFrame, exercise: str, *, theme: dict) -> go.Figure:
    colors, layout, _, grid_soft, legend = _theme_parts(theme)
    data = maxes_df[maxes_df["Exercise Name"] == exercise].sort_values("Added Date")
    fig = go.Figure()
    if data.empty:
        fig.update_layout(**layout, height=320, title=dict(text=f"<b>Progresion MAX - {exercise}</b>"))
        return fig

    if "Athlete" in data.columns and data["Athlete"].nunique() > 1:
        for athlete_name, athlete_df in data.groupby("Athlete"):
            fig.add_trace(
                go.Scatter(
                    x=athlete_df["Added Date"],
                    y=athlete_df["Max Value"],
                    mode="lines+markers",
                    name=athlete_name,
                    hovertemplate=f"<b>{athlete_name}</b><br>%{{x|%d/%m/%Y}}<br>%{{y}} kg<extra></extra>",
                )
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=data["Added Date"],
                y=data["Max Value"],
                mode="lines+markers",
                line=dict(color=colors["steel"], width=2.5),
                marker=dict(size=8, color=colors["steel"], line=dict(color=colors["card"], width=1)),
                hovertemplate="%{x|%d/%m/%Y}<br>%{y} kg<extra></extra>",
                name=exercise,
            )
        )

    if len(data) == 1:
        last = data.iloc[-1]
        fig.add_annotation(
            x=last["Added Date"],
            y=last["Max Value"],
            text=f"<b>{last['Max Value']:.0f} kg</b>",
            showarrow=True,
            arrowhead=2,
            font=dict(color=colors["yellow"], size=12),
            arrowcolor=colors["yellow"],
        )

    fig.update_layout(
        **layout,
        height=320,
        title=dict(text=f"<b>Progresion MAX - {exercise}</b>", font=dict(color=colors["navy"], size=13)),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="kg", gridcolor=grid_soft, zeroline=False),
        legend=legend,
    )
    return fig


def chart_completion(comp_df: pd.DataFrame, *, theme: dict, athlete_label: str = "Todos") -> go.Figure:
    colors, layout, _, grid_soft, _ = _theme_parts(theme)
    if comp_df is None or comp_df.empty or not {"Date", "Pct"}.issubset(comp_df.columns):
        fig = go.Figure()
        fig.update_layout(
            **layout,
            height=300,
            title=dict(text="<b>Completion Rate por Sesion</b>", font=dict(color=colors["navy"], size=13)),
            annotations=[
                dict(
                    text="No hay datos de completion para la seleccion actual.",
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

    fig = go.Figure()
    bar_colors = [
        colors["green"] if pct >= 90 else colors["yellow"] if pct >= 70 else colors["red"]
        for pct in comp_df["Pct"]
    ]
    fig.add_trace(
        go.Bar(
            x=comp_df["Date"],
            y=comp_df["Pct"],
            marker_color=bar_colors,
            hovertemplate="%{x|%d/%m}<br>%{y:.0f}%<extra></extra>",
        )
    )
    fig.add_hline(y=90, line_dash="dash", line_color=colors["green"], annotation_text="90%", annotation_font_color=colors["green"])
    fig.update_layout(
        **layout,
        height=300,
        title=dict(
            text=f"<b>Completion Rate por Sesion - {'Equipo' if athlete_label == 'Todos' else athlete_label}</b>",
            font=dict(color=colors["navy"], size=13),
        ),
        xaxis=dict(title="Fecha", gridcolor=grid_soft, zeroline=False),
        yaxis=dict(title="% Completado", range=[0, 105], gridcolor=grid_soft, zeroline=False),
    )
    return fig
