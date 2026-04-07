"""Vista dedicada de perfil de atleta."""

import pandas as pd
import streamlit as st

from charts.dashboard_charts import chart_radar
from charts.load_charts import chart_maxes_trend
from modules.page_state import collect_state_athletes, ensure_page_state
from modules.page_visuals import build_page_theme, render_insight_block
from modules.report_generator import build_executive_summary_df, generate_module_insights


ensure_page_state(load_models=True)

st.header("Perfil del Atleta")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

theme = build_page_theme()
jdf = st.session_state.jump_df
rdf = st.session_state.rpe_df
wdf = st.session_state.wellness_df
maxes_df = st.session_state.maxes_df

athletes = collect_state_athletes()

if not athletes:
    st.info("Todavía no hay datos de atletas cargados.")
else:
    athlete = st.selectbox("Atleta", athletes)
    executive_df = build_executive_summary_df(dict(st.session_state), athlete)

    if not executive_df.empty:
        st.markdown("### Resumen ejecutivo")
        st.dataframe(executive_df, use_container_width=True, hide_index=True)

    metrics = st.columns(4)
    if st.session_state.acwr_dict and athlete in st.session_state.acwr_dict:
        acwr_last = st.session_state.acwr_dict[athlete]
        acwr_last = acwr_last[acwr_last["sRPE_diario"] > 0].tail(1)
        metrics[0].metric("ACWR EWMA", f"{acwr_last['ACWR_EWMA'].iloc[-1]:.2f}" if not acwr_last.empty else "-")
    if wdf is not None and athlete in wdf["Athlete"].values:
        w_last = wdf[wdf["Athlete"] == athlete].sort_values("Date").tail(3)
        metrics[1].metric("Wellness 3 días", f"{w_last['Wellness_Score'].mean():.1f}" if not w_last.empty else "-")
    if jdf is not None and athlete in jdf["Athlete"].values:
        j_last = jdf[jdf["Athlete"] == athlete].sort_values("Date").tail(1)
        metrics[2].metric("Último CMJ", f"{j_last['CMJ_cm'].iloc[-1]:.1f} cm" if "CMJ_cm" in j_last.columns and not j_last.empty else "-")
        metrics[3].metric("Perfil NM", j_last["NM_Profile"].iloc[-1] if "NM_Profile" in j_last.columns and not j_last.empty else "-")

    render_insight_block(generate_module_insights(dict(st.session_state), athlete).get("profile"), fallback_title="Síntesis integrada")

    if jdf is not None and athlete in jdf["Athlete"].values:
        latest_team = jdf.sort_values("Date").groupby("Athlete").last().reset_index()
        team_mean = {key: latest_team[key].mean() for key in ["CMJ_Z", "SJ_Z", "DJtc_Z", "EUR_Z", "DRI_Z", "IMTP_Z"] if key in latest_team.columns}
        latest_row = jdf[jdf["Athlete"] == athlete].sort_values("Date").iloc[-1]
        st.markdown("### Perfil neuromuscular")
        st.plotly_chart(chart_radar(latest_row, athlete, team_mean, theme=theme), use_container_width=True)

    if maxes_df is not None and "Athlete" in maxes_df.columns:
        athlete_maxes = maxes_df[maxes_df["Athlete"] == athlete]
        if not athlete_maxes.empty and "Exercise Name" in athlete_maxes.columns:
            exercises = sorted(athlete_maxes["Exercise Name"].dropna().unique())
            if exercises:
                st.markdown("### Progresión de máximos")
                selected_exercise = st.selectbox("Ejercicio", exercises, key="profile_page_exercise")
                st.plotly_chart(chart_maxes_trend(athlete_maxes, selected_exercise, theme=theme), use_container_width=True)

    detail_left, detail_right = st.columns(2)
    with detail_left:
        if rdf is not None and athlete in rdf["Athlete"].values:
            st.markdown("### Carga reciente")
            st.dataframe(
                rdf[rdf["Athlete"] == athlete].sort_values("Date", ascending=False).head(12),
                use_container_width=True,
                hide_index=True,
            )
        if wdf is not None and athlete in wdf["Athlete"].values:
            st.markdown("### Wellness")
            st.dataframe(
                wdf[wdf["Athlete"] == athlete].sort_values("Date", ascending=False).head(12),
                use_container_width=True,
                hide_index=True,
            )
    with detail_right:
        if jdf is not None and athlete in jdf["Athlete"].values:
            st.markdown("### Evaluaciones")
            st.dataframe(
                jdf[jdf["Athlete"] == athlete].sort_values("Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
        if maxes_df is not None and "Athlete" in maxes_df.columns and athlete in maxes_df["Athlete"].values:
            st.markdown("### Máximos")
            st.dataframe(
                maxes_df[maxes_df["Athlete"] == athlete].sort_values("Added Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
