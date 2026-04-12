"""Vista dedicada de evaluaciones individuales."""

import pandas as pd
import streamlit as st

from charts.dashboard_charts import chart_cmj_trend, chart_radar
from modules.page_state import ensure_page_state
from modules.page_visuals import build_page_theme, render_insight_block
from modules.report_generator import generate_module_insights


ensure_page_state(load_models=False)

st.header("Evaluación de Saltos")
st.caption("Esta vista usa solo evaluaciones individuales cargadas desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

theme = build_page_theme()
jdf = st.session_state.jump_df

if jdf is None or jdf.empty:
    st.info("Todavía no hay evaluaciones individuales procesadas.")
else:
    athletes = sorted(jdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    controls_left, controls_right = st.columns([1.3, 1])
    with controls_left:
        athlete = st.selectbox("Atleta", athletes)

    athlete_hist = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    date_options = athlete_hist["Date"].dropna().drop_duplicates().sort_values(ascending=False).tolist()
    with controls_right:
        selected_date = st.selectbox(
            "Evaluación",
            date_options,
            format_func=lambda value: pd.Timestamp(value).strftime("%d/%m/%Y"),
        )

    selected_rows = athlete_hist[athlete_hist["Date"] == pd.Timestamp(selected_date)].sort_values("Date")
    selected_row = selected_rows.iloc[-1] if not selected_rows.empty else athlete_hist.iloc[-1]
    latest_team = jdf.sort_values("Date").groupby("Athlete").last().reset_index()
    team_mean = {key: latest_team[key].mean() for key in ["CMJ_Z", "SJ_Z", "DJtc_Z", "EUR_Z", "DRI_Z", "IMTP_Z"] if key in latest_team.columns}

    metrics = st.columns(6)
    metric_config = [
        ("CMJ", "CMJ_cm", "cm", ".1f"),
        ("SJ", "SJ_cm", "cm", ".1f"),
        ("DJ", "DJ_cm", "cm", ".1f"),
        ("DJ TC", "DJ_tc_ms", "ms", ".0f"),
        ("EUR (ratio)", "EUR", "", ".3f"),
        ("IMTP", "IMTP_N", "N", ".0f"),
    ]
    for column, (label, key, unit, fmt) in zip(metrics, metric_config):
        value = selected_row.get(key)
        suffix = f" {unit}".rstrip()
        column.metric(label, f"{value:{fmt}}{suffix}" if pd.notna(value) else "-")
    st.caption("Referencia EUR (ratio): 1.0-1.35.")

    render_insight_block(generate_module_insights(dict(st.session_state), athlete).get("evaluations"), fallback_title="Lectura de evaluación")

    chart_left, chart_right = st.columns([1.05, 0.95])
    with chart_left:
        st.plotly_chart(chart_radar(selected_row, athlete, team_mean, theme=theme), use_container_width=True)
    with chart_right:
        if "CMJ_cm" in athlete_hist.columns and athlete_hist["CMJ_cm"].notna().sum() >= 2:
            st.plotly_chart(chart_cmj_trend(jdf, athlete, theme=theme), use_container_width=True)
        else:
            st.info("No hay suficientes puntos de CMJ para mostrar tendencia.")

    st.markdown("### Detalle de la evaluación seleccionada")
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
