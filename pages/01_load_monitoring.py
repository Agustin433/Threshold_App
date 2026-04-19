"""Vista dedicada de monitoreo de carga."""

import pandas as pd
import streamlit as st

from charts.load_charts import chart_acwr, chart_monotony_strain, chart_volume_by_tag, chart_wellness
from modules.data_loader import prepare_raw_workouts_df
from modules.data_quality import compute_data_quality_report
from modules.page_state import collect_state_athletes, ensure_page_state
from modules.page_visuals import build_page_theme, render_insight_block
from modules.report_generator import generate_module_insights


def _render_quality_block(
    dataset_summary: pd.DataFrame,
    raw_category_breakdown: pd.DataFrame,
    raw_classification_summary: dict[str, float],
    athlete_summary: pd.DataFrame,
    alerts: list[str],
) -> None:
    with st.expander("📋 Calidad de datos", expanded=False):
        st.markdown("**Bloque A - Cobertura por dataset**")
        st.dataframe(dataset_summary, use_container_width=True, hide_index=True)
        if not raw_category_breakdown.empty:
            classified_pct = raw_classification_summary.get("classified_pct", 0.0)
            untagged_pct = raw_classification_summary.get("untagged_pct", 0.0)
            st.caption(f"Raw workouts: {classified_pct:.1f}% clasificado · {untagged_pct:.1f}% untagged")
            st.dataframe(raw_category_breakdown, use_container_width=True, hide_index=True)

        st.markdown("**Bloque B - Cobertura por atleta**")
        if athlete_summary.empty:
            st.caption("Sin datos de RPE o Wellness para calcular cobertura por atleta.")
        else:
            st.dataframe(athlete_summary, use_container_width=True, hide_index=True)

        st.markdown("**Bloque C - Alertas de calidad**")
        if alerts:
            for alert in alerts:
                st.warning(alert)
        else:
            st.success("✅ Sin alertas de calidad activas.")


ensure_page_state(load_models=True)

st.header("Monitoreo de Carga")
st.caption("La carga de archivos se hace desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

theme = build_page_theme()
rdf = st.session_state.rpe_df
wdf = st.session_state.wellness_df
raw_df = st.session_state.raw_df
acwr_dict = st.session_state.acwr_dict or {}
mono_dict = st.session_state.mono_dict or {}
prepared_raw_df = prepare_raw_workouts_df(raw_df) if raw_df is not None else None
quality_report = compute_data_quality_report(
    rdf,
    wdf,
    st.session_state.completion_df,
    prepared_raw_df,
    st.session_state.maxes_df,
    st.session_state.jump_df,
    collect_state_athletes(dataset_keys=["rpe_df", "wellness_df", "completion_df", "raw_df", "maxes_df", "jump_df"]),
    window_days=42,
)
dataset_summary = quality_report["dataset_summary"]
raw_category_breakdown = quality_report.get("raw_category_breakdown", pd.DataFrame())
raw_classification_summary = quality_report.get("raw_classification_summary", {})
athlete_summary = quality_report["athlete_summary"]
alerts = quality_report["alerts"]

if rdf is None or not acwr_dict:
    st.info("Todavia no hay datos de carga procesados. Carga RPE + Tiempo desde la pantalla principal y luego volve a esta pagina.")
else:
    athletes = sorted(rdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    athlete = st.selectbox("Atleta", athletes)

    sub_rpe = rdf[rdf["Athlete"] == athlete].sort_values("Date")
    acwr_df = acwr_dict.get(athlete)
    mono_df = mono_dict.get(athlete)
    if mono_df is None:
        mono_df = pd.DataFrame(columns=["Semana", "Monotonia", "Strain", "Alerta"])

    acwr_label = "ACWR EWMA"

    last_session = sub_rpe.tail(1)
    last_acwr = acwr_df[acwr_df["sRPE_diario"] > 0].tail(1) if acwr_df is not None else pd.DataFrame()
    last_mono = mono_df.tail(1) if mono_df is not None else pd.DataFrame()

    metrics = st.columns(5)
    metrics[0].metric("sRPE ultima sesion", f"{last_session['sRPE'].iloc[-1]:.0f} UA" if not last_session.empty else "-")
    metrics[1].metric("RPE ultima sesion", f"{last_session['RPE'].iloc[-1]:.1f}" if not last_session.empty else "-")
    metrics[2].metric(acwr_label, f"{last_acwr['ACWR_EWMA'].iloc[-1]:.2f}" if not last_acwr.empty else "-")
    metrics[3].metric("Monotonia", f"{last_mono['Monotonia'].iloc[-1]:.2f}" if not last_mono.empty else "-")
    metrics[4].metric("Strain", f"{last_mono['Strain'].iloc[-1]:.0f}" if not last_mono.empty else "-")

    if not last_acwr.empty:
        acwr_value = float(last_acwr["ACWR_EWMA"].iloc[-1])
        if acwr_value > 1.5:
            st.error(f"{acwr_label}: {acwr_value:.2f}. Zona alta; conviene bajar densidad o exposicion aguda.")
        elif acwr_value > 1.3:
            st.warning(f"{acwr_label}: {acwr_value:.2f}. Hay que monitorear el proximo bloque de 48 horas.")
        elif acwr_value < 0.8:
            st.info(f"{acwr_label}: {acwr_value:.2f}. Senal de subcarga o recuperacion prolongada.")
        else:
            st.success(f"{acwr_label}: {acwr_value:.2f}. La carga reciente esta dentro de la zona objetivo.")

    render_insight_block(generate_module_insights(dict(st.session_state), athlete).get("load"), fallback_title="Lectura de carga")

    chart_left, chart_right = st.columns(2)
    with chart_left:
        if acwr_df is not None and not acwr_df.empty:
            st.plotly_chart(
                chart_acwr(acwr_df, athlete, theme=theme),
                use_container_width=True,
            )
    with chart_right:
        if mono_df is not None and not mono_df.empty:
            st.plotly_chart(chart_monotony_strain(mono_df, theme=theme), use_container_width=True)

    if wdf is not None and athlete in wdf["Athlete"].values:
        st.markdown("### Wellness")
        athlete_wdf = wdf[wdf["Athlete"] == athlete].sort_values("Date")
        st.plotly_chart(chart_wellness(athlete_wdf, athlete, theme=theme), use_container_width=True)
        with st.expander("Detalle de wellness", expanded=False):
            st.dataframe(athlete_wdf.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

    if raw_df is not None:
        athlete_col = "Athlete" if "Athlete" in prepared_raw_df.columns else "Name" if "Name" in prepared_raw_df.columns else None
        if athlete_col and athlete in prepared_raw_df[athlete_col].astype(str).values:
            st.markdown("### Carga externa por tipo de estimulo")
            st.plotly_chart(chart_volume_by_tag(prepared_raw_df, athlete, theme=theme), use_container_width=True)

    with st.expander("Sesiones recientes", expanded=False):
        display_cols = [col for col in ["Date", "RPE", "Duration_min", "sRPE"] if col in sub_rpe.columns]
        st.dataframe(
            sub_rpe[display_cols].sort_values("Date", ascending=False).head(20),
            use_container_width=True,
            hide_index=True,
        )

_render_quality_block(
    dataset_summary,
    raw_category_breakdown,
    raw_classification_summary,
    athlete_summary,
    alerts,
)
