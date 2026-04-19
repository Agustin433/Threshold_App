"""Vista dedicada de perfil de atleta."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from charts.dashboard_charts import (
    chart_composite_profile_radar,
    chart_quadrant_cmj_imtp,
    chart_quadrant_dri_sj,
    chart_quadrant_exploratory,
)
from charts.load_charts import chart_maxes_trend
from modules.jump_analysis import (
    build_composite_profile_metric_table,
    build_composite_profile_snapshot,
    build_jump_feedback_lines,
    build_jump_flag_rows,
)
from modules.page_state import collect_state_athletes, ensure_page_state
from modules.page_visuals import build_page_theme
from modules.report_generator import build_executive_summary_df


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
    st.info("Todavia no hay datos de atletas cargados.")
else:
    athlete = st.selectbox("Atleta", athletes)
    athlete_hist = (
        jdf[jdf["Athlete"] == athlete].sort_values("Date")
        if jdf is not None and "Athlete" in jdf.columns and athlete in jdf["Athlete"].values
        else pd.DataFrame()
    )
    current_profile_row, current_profile_sources = build_composite_profile_snapshot(athlete_hist)
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
        metrics[1].metric("Wellness 3 dias", f"{w_last['Wellness_Score'].mean():.1f}" if not w_last.empty else "-")
    if not athlete_hist.empty:
        j_last = athlete_hist.tail(1)
        metrics[2].metric(
            "CMJ perfil actual",
            f"{current_profile_row['CMJ_cm']:.1f} cm"
            if current_profile_row is not None and pd.notna(current_profile_row.get("CMJ_cm"))
            else f"{j_last['CMJ_cm'].iloc[-1]:.1f} cm"
            if "CMJ_cm" in j_last.columns and not j_last.empty and pd.notna(j_last["CMJ_cm"].iloc[-1])
            else "-",
        )
        metrics[3].metric(
            "Perfil NM actual",
            current_profile_row["NM_Profile"]
            if current_profile_row is not None and pd.notna(current_profile_row.get("NM_Profile"))
            else j_last["NM_Profile"].iloc[-1]
            if "NM_Profile" in j_last.columns and not j_last.empty
            else "-",
        )

    if not athlete_hist.empty:
        latest_team = jdf.sort_values("Date").groupby("Athlete").last().reset_index()

        st.markdown("### Perfil actual compuesto")
        if current_profile_row is None:
            st.info(
                "No hay metricas suficientes para construir el perfil actual compuesto de este atleta."
            )
        else:
            st.caption(
                "Este bloque no depende de una unica evaluacion por fecha. "
                "Usa el ultimo dato valido disponible por variable para construir un perfil compuesto."
            )
            _render_flag_chips(build_jump_flag_rows(current_profile_row))
            _render_feedback(build_jump_feedback_lines(current_profile_row))

            radar_col, table_col = st.columns([1.1, 0.9])
            with radar_col:
                st.plotly_chart(
                    chart_composite_profile_radar(current_profile_row, athlete, theme=theme),
                    use_container_width=True,
                )
            with table_col:
                st.markdown("### Lectura por variable actual")
                st.dataframe(
                    build_composite_profile_metric_table(current_profile_row),
                    use_container_width=True,
                    hide_index=True,
                )
            with st.expander("Origen por variable", expanded=False):
                st.dataframe(
                    current_profile_sources,
                    use_container_width=True,
                    hide_index=True,
                )

        if len(latest_team) > 1:
            st.markdown("### Cuadrantes")
            quad_left, quad_right = st.columns(2)
            with quad_left:
                st.plotly_chart(chart_quadrant_dri_sj(latest_team, theme=theme), use_container_width=True)
            with quad_right:
                st.plotly_chart(chart_quadrant_cmj_imtp(latest_team, theme=theme), use_container_width=True)
            with st.expander("DRI experimental", expanded=False):
                st.plotly_chart(chart_quadrant_exploratory(latest_team, theme=theme), use_container_width=True)

    if maxes_df is not None and "Athlete" in maxes_df.columns:
        athlete_maxes = maxes_df[maxes_df["Athlete"] == athlete]
        if not athlete_maxes.empty and "Exercise Name" in athlete_maxes.columns:
            exercises = sorted(athlete_maxes["Exercise Name"].dropna().unique())
            if exercises:
                st.markdown("### Progresion de maximos")
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
                jdf[jdf["Athlete"] == athlete].rename(columns={"EUR": "EUR (ratio)"}).sort_values("Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
        if maxes_df is not None and "Athlete" in maxes_df.columns and athlete in maxes_df["Athlete"].values:
            st.markdown("### Maximos")
            st.dataframe(
                maxes_df[maxes_df["Athlete"] == athlete].sort_values("Added Date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
