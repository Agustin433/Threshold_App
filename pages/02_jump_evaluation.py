"""Vista dedicada de evaluaciones individuales."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from charts.dashboard_charts import chart_cmj_trend, chart_radar
from modules.jump_analysis import (
    build_jump_feedback_lines,
    build_jump_flag_rows,
    build_jump_metric_table,
)
from modules.page_state import ensure_page_state
from modules.page_visuals import build_page_theme


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

    metrics = st.columns(6)
    metric_config = [
        ("CMJ", "CMJ_cm", "cm", ".1f"),
        ("SJ", "SJ_cm", "cm", ".1f"),
        ("DJ", "DJ_cm", "cm", ".1f"),
        ("DJ RSI", "DJ_RSI", "m/s", ".2f"),
        ("IMTP relPF", "IMTP_relPF", "N/kg", ".2f"),
        ("EUR (ratio)", "EUR", "", ".3f"),
    ]
    for column, (label, key, unit, fmt) in zip(metrics, metric_config):
        value = selected_row.get(key)
        suffix = f" {unit}".rstrip()
        column.metric(label, f"{value:{fmt}}{suffix}" if pd.notna(value) else "-")

    st.caption(
        "Referencia EUR (ratio): 1.00-1.35. Los benchmarks externos son orientativos para futbol profesional masculino."
    )
    _render_flag_chips(build_jump_flag_rows(selected_row))
    _render_feedback(build_jump_feedback_lines(selected_row))

    chart_left, chart_right = st.columns([1.05, 0.95])
    with chart_left:
        st.plotly_chart(chart_radar(selected_row, athlete, None, theme=theme), use_container_width=True)
    with chart_right:
        metric_table = build_jump_metric_table(selected_row)
        st.markdown("### Lectura por variable")
        st.dataframe(metric_table, use_container_width=True, hide_index=True)
        if "CMJ_cm" in athlete_hist.columns and athlete_hist["CMJ_cm"].notna().sum() >= 2:
            st.plotly_chart(chart_cmj_trend(jdf, athlete, theme=theme), use_container_width=True)
        else:
            st.info("No hay suficientes puntos de CMJ para mostrar tendencia.")

    st.markdown("### Detalle de la evaluacion seleccionada")
    detail_cols = [column for column in selected_rows.columns if not column.endswith("_reps")]
    st.dataframe(
        selected_rows[detail_cols].rename(columns={"EUR": "EUR (ratio)"}),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Historial completo del atleta", expanded=False):
        history_cols = [column for column in athlete_hist.columns if not column.endswith("_reps")]
        st.dataframe(
            athlete_hist[history_cols].rename(columns={"EUR": "EUR (ratio)"}).sort_values("Date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
