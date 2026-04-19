"""Vista dedicada de evaluaciones individuales."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from charts.dashboard_charts import chart_cmj_trend, chart_composite_profile_radar, chart_jump_metric_trend
from modules.jump_analysis import (
    build_composite_profile_metric_table,
    build_composite_profile_snapshot,
    build_jump_delta_display_table,
    build_jump_feedback_lines,
    build_jump_flag_rows,
    build_jump_temporal_context,
    compute_swc_delta,
)
from modules.page_state import ensure_page_state
from modules.page_visuals import build_page_theme


SELECTED_METRIC_CONFIG = [
    ("CMJ", "CMJ_cm", "cm", ".1f"),
    ("SJ", "SJ_cm", "cm", ".1f"),
    ("DJ", "DJ_cm", "cm", ".1f"),
    ("DJ RSI", "DJ_RSI", "m/s", ".2f"),
    ("IMTP relPF", "IMTP_relPF", "N/kg", ".2f"),
    ("EUR (ratio)", "EUR", "", ".3f"),
]


def _render_flag_chips(flags: list[dict[str, str]]) -> None:
    if not flags:
        return

    palette = {
        "green": ("rgba(111,143,120,0.16)", "#446555"),
        "yellow": ("rgba(196,164,100,0.18)", "#7C5D1F"),
        "red": ("rgba(181,107,115,0.18)", "#7B3D45"),
        "gray": ("rgba(112,140,159,0.16)", "#41515E"),
    }
    chips = []
    for flag in flags:
        bg, fg = palette.get(flag["level"], ("rgba(112,140,159,0.16)", "#41515E"))
        chips.append(
            f'<span style="display:inline-flex;align-items:center;padding:0.35rem 0.7rem;'
            f'border-radius:999px;background:{bg};color:{fg};font-size:0.88rem;'
            'font-weight:600;border:1px solid rgba(13,60,94,0.08);">'
            f"{html.escape(flag['text'])}</span>"
        )
    st.markdown(
        f'<div style="display:flex;gap:0.45rem;flex-wrap:wrap;margin:0.2rem 0 0.9rem;">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )


def _render_feedback(lines: list[str]) -> None:
    if not lines:
        return
    content = "".join(
        f'<div style="margin:0 0 0.38rem;color:#221F20;">{html.escape(line)}</div>'
        for line in lines
    )
    st.markdown(
        '<div style="background:#FEFEFE;border:1px solid rgba(13,60,94,0.10);'
        'border-radius:16px;padding:1rem 1.1rem;margin:0.6rem 0 1rem;'
        'box-shadow:0 1px 0 rgba(13,60,94,0.04);">'
        '<div style="font-size:0.78rem;letter-spacing:0.08em;text-transform:uppercase;'
        'color:#708C9F;font-weight:700;margin-bottom:0.55rem;">Devolucion automatica</div>'
        f"{content}</div>",
        unsafe_allow_html=True,
    )


def _render_temporal_delta_table(delta_df: pd.DataFrame) -> None:
    display_df = build_jump_delta_display_table(delta_df)
    if display_df.empty:
        st.caption("No hay variables comparables para esta evaluacion.")
        return

    signal_palette = {
        "mejora relevante": ("rgba(111,143,120,0.16)", "#446555"),
        "caida relevante": ("rgba(181,107,115,0.18)", "#7B3D45"),
        "sin cambio relevante": ("rgba(112,140,159,0.16)", "#41515E"),
        "sin dato anterior": ("rgba(196,164,100,0.12)", "#6D5D3C"),
    }
    signal_values = delta_df["Signal"].reset_index(drop=True)

    def _style_signal(column: pd.Series) -> list[str]:
        styles: list[str] = []
        for idx, _ in enumerate(column):
            bg, fg = signal_palette.get(signal_values.iloc[idx], ("rgba(112,140,159,0.16)", "#41515E"))
            styles.append(f"background-color: {bg}; color: {fg}; font-weight: 700;")
        return styles

    styler = display_df.style.apply(_style_signal, subset=["Senal"])
    st.dataframe(styler, use_container_width=True, hide_index=True)


def _format_eval_date(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else "Sin fecha"


def _render_history_chart(
    athlete_hist: pd.DataFrame,
    athlete: str,
    label: str,
    metric_key: str,
    *,
    theme: dict,
) -> None:
    valid_points = 0
    if metric_key in athlete_hist.columns:
        valid_points = int(pd.to_numeric(athlete_hist[metric_key], errors="coerce").notna().sum())

    if valid_points < 2:
        st.info(f"No hay suficientes puntos de {label} para mostrar tendencia.")
        return

    if metric_key == "CMJ_cm":
        figure = chart_cmj_trend(athlete_hist, athlete, theme=theme)
    else:
        figure = chart_jump_metric_trend(athlete_hist, athlete, metric_key, theme=theme)
    st.plotly_chart(figure, use_container_width=True)


ensure_page_state(load_models=False)

st.header("Evaluacion de Saltos")
st.caption("Esta vista usa solo evaluaciones individuales cargadas desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

theme = build_page_theme()
jdf = st.session_state.jump_df

if jdf is None or jdf.empty:
    st.info("Todavia no hay evaluaciones individuales procesadas.")
else:
    athletes = sorted(jdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    controls_left, controls_right = st.columns([1.3, 1])
    with controls_left:
        athlete = st.selectbox("Atleta", athletes)

    athlete_hist = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    date_options = athlete_hist["Date"].dropna().drop_duplicates().sort_values(ascending=False).tolist()
    with controls_right:
        selected_date = st.selectbox(
            "Evaluacion",
            date_options,
            format_func=lambda value: pd.Timestamp(value).strftime("%d/%m/%Y"),
        )

    selected_rows = athlete_hist[athlete_hist["Date"] == pd.Timestamp(selected_date)].sort_values("Date")
    selected_row = selected_rows.iloc[-1] if not selected_rows.empty else athlete_hist.iloc[-1]
    current_profile_row, current_profile_sources = build_composite_profile_snapshot(athlete_hist)
    delta_df = compute_swc_delta(athlete_hist, selected_date)
    temporal_lines = build_jump_temporal_context(delta_df)
    selected_feedback_lines = build_jump_feedback_lines(selected_row) + temporal_lines

    st.markdown("### Evaluacion seleccionada")
    st.caption(f"Fecha elegida para el detalle puntual: {_format_eval_date(selected_date)}")
    metrics = st.columns(6)
    for column, (label, key, unit, fmt) in zip(metrics, SELECTED_METRIC_CONFIG):
        value = selected_row.get(key)
        suffix = f" {unit}".rstrip()
        column.metric(label, f"{value:{fmt}}{suffix}" if pd.notna(value) else "-")

    st.caption(
        "Referencia EUR (ratio): 1.00-1.35. Los benchmarks externos son orientativos para futbol profesional masculino."
    )
    st.markdown("### Cambios vs evaluacion anterior")
    _render_temporal_delta_table(delta_df)
    if not delta_df.empty and delta_df["Signal"].eq("sin dato anterior").all():
        st.caption(
            "Primera evaluacion registrada para este atleta. El threshold individual tipo Hopkins estara disponible a partir de la tercera medicion valida por variable."
        )
    _render_flag_chips(build_jump_flag_rows(selected_row))
    _render_feedback(selected_feedback_lines)

    st.markdown("### Detalle de la evaluacion seleccionada")
    detail_cols = [column for column in selected_rows.columns if not column.endswith("_reps")]
    st.dataframe(
        selected_rows[detail_cols].rename(columns={"EUR": "EUR (ratio)"}),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Perfil actual compuesto")
    if current_profile_row is None:
        st.info(
            "No hay metricas suficientes para construir el perfil actual compuesto de este atleta."
        )
    else:
        st.caption(
            "Este bloque no depende de la fecha seleccionada. "
            "Usa el ultimo dato valido disponible por variable para construir un perfil compuesto."
        )
        chart_left, chart_right = st.columns([1.05, 0.95])
        with chart_left:
            st.plotly_chart(chart_composite_profile_radar(current_profile_row, athlete, theme=theme), use_container_width=True)
        with chart_right:
            metric_table = build_composite_profile_metric_table(current_profile_row)
            st.markdown("### Lectura por variable actual")
            st.dataframe(metric_table, use_container_width=True, hide_index=True)
        with st.expander("Origen por variable", expanded=False):
            st.dataframe(current_profile_sources, use_container_width=True, hide_index=True)
        _render_flag_chips(build_jump_flag_rows(current_profile_row))
        _render_feedback(build_jump_feedback_lines(current_profile_row))

    st.markdown("### Historial temporal")
    st.caption("Estos graficos usan siempre la fecha de evaluacion como eje temporal y no dependen de la fecha seleccionada.")
    history_top_left, history_top_right = st.columns(2)
    with history_top_left:
        _render_history_chart(athlete_hist, athlete, "CMJ", "CMJ_cm", theme=theme)
    with history_top_right:
        _render_history_chart(athlete_hist, athlete, "EUR (ratio)", "EUR", theme=theme)

    history_bottom_left, history_bottom_right = st.columns(2)
    with history_bottom_left:
        _render_history_chart(athlete_hist, athlete, "DJ RSI", "DJ_RSI", theme=theme)
    with history_bottom_right:
        _render_history_chart(athlete_hist, athlete, "DJ", "DJ_cm", theme=theme)

    with st.expander("Historial completo del atleta", expanded=False):
        history_cols = [column for column in athlete_hist.columns if not column.endswith("_reps")]
        st.dataframe(
            athlete_hist[history_cols].rename(columns={"EUR": "EUR (ratio)"}).sort_values("Date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
