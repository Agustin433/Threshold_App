"""Vista dedicada de monitoreo de carga."""

import pandas as pd
import streamlit as st

from charts.load_charts import (
    chart_acwr,
    chart_monotony_strain,
    chart_volume_by_tag,
    chart_weekly_acwr_context,
    chart_weekly_external,
    chart_weekly_load,
    chart_weekly_strain,
    chart_weekly_wellness,
    chart_wellness,
)
from local_store import build_load_models, build_weekly_summaries, read_full_dataset
from modules.data_loader import prepare_raw_workouts_df
from modules.data_quality import compute_data_quality_report
from modules.load_monitoring import build_weekly_acwr_context
from modules.page_state import collect_state_athletes, ensure_page_state
from modules.page_visuals import build_page_theme, render_insight_block
from modules.report_generator import generate_module_insights

WEEKLY_SUMMARY_KEYS = {"weekly_load", "weekly_wellness", "weekly_external", "weekly_team"}


def _normalize_weekly_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "week_start" in result.columns:
        result["week_start"] = pd.to_datetime(result["week_start"], errors="coerce")
    if "is_current_week" in result.columns:
        result["is_current_week"] = result["is_current_week"].fillna(False).astype(bool)
    return result


def _weekly_summaries_from_state(
    rpe_df: pd.DataFrame | None,
    wellness_df: pd.DataFrame | None,
    raw_df: pd.DataFrame | None,
    acwr_dict: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    cached = st.session_state.get("weekly_summaries")
    if isinstance(cached, dict) and WEEKLY_SUMMARY_KEYS.issubset(cached.keys()):
        return cached

    summaries = build_weekly_summaries(rpe_df, wellness_df, raw_df, acwr_dict=acwr_dict)
    st.session_state.weekly_summaries = summaries
    return summaries


def _full_history_weekly_load(rpe_df: pd.DataFrame | None) -> pd.DataFrame:
    full_rpe = read_full_dataset("rpe_df")
    if full_rpe is None or full_rpe.empty:
        full_rpe = rpe_df
    if full_rpe is None or full_rpe.empty:
        return pd.DataFrame()
    full_acwr_dict, _ = build_load_models(full_rpe)
    summaries = build_weekly_summaries(
        full_rpe,
        None,
        None,
        acwr_dict=full_acwr_dict or {},
    )
    return _normalize_weekly_frame(summaries.get("weekly_load", pd.DataFrame()))


def _weekly_athletes(*frames: pd.DataFrame) -> list[str]:
    athletes: set[str] = set()
    for frame in frames:
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        athletes.update(frame["Athlete"].dropna().astype(str).str.strip().tolist())
    return sorted(athlete for athlete in athletes if athlete)


def _has_weekly_external_data(frame: pd.DataFrame) -> bool:
    if frame is None or frame.empty:
        return False
    metric_df = frame.drop(columns=["Athlete", "week_start", "is_current_week"], errors="ignore")
    if metric_df.empty:
        return False
    return bool(pd.to_numeric(metric_df.stack(), errors="coerce").fillna(0).gt(0).any())


def _format_week_label(week_start: object, is_current_week: bool = False) -> str:
    week_start_ts = pd.Timestamp(week_start).normalize()
    if is_current_week:
        today_ts = pd.Timestamp.today().normalize()
        return f"{week_start_ts:%d/%m} - {today_ts:%d/%m} (en curso)"
    return f"{week_start_ts:%d/%m} - {week_start_ts + pd.Timedelta(days=6):%d/%m}"


def _render_team_weekly_summary(weekly_team: pd.DataFrame) -> None:
    st.markdown("### Resumen semanal del equipo")
    if weekly_team.empty:
        st.caption("Todavia no hay resumen semanal del equipo para mostrar.")
        return

    team_display = weekly_team.copy().sort_values("week_start", ascending=False)
    if "week_start" in team_display.columns:
        team_display["Semana"] = team_display.apply(
            lambda row: _format_week_label(row["week_start"], bool(row.get("is_current_week", False))),
            axis=1,
        )
    rename_map = {
        "athletes_active": "Atletas activos",
        "team_sRPE_mean": "sRPE promedio",
        "team_monotony_mean": "Monotonia promedio",
        "team_strain_mean": "Strain promedio",
        "team_wellness_mean": "Wellness promedio",
    }
    display_cols = [
        "Semana",
        "Atletas activos",
        "sRPE promedio",
        "Monotonia promedio",
        "Strain promedio",
        "Wellness promedio",
    ]
    team_display = team_display.rename(columns=rename_map)
    available_cols = [column for column in display_cols if column in team_display.columns]
    st.dataframe(team_display[available_cols], use_container_width=True, hide_index=True)


def _render_weekly_block(
    athlete: str,
    weekly_load: pd.DataFrame,
    weekly_wellness: pd.DataFrame,
    weekly_external: pd.DataFrame,
    weekly_team: pd.DataFrame,
    theme: dict,
    acwr_context_weeks: int | None,
    rpe_df: pd.DataFrame | None,
) -> None:
    st.markdown("### Vista semanal canonica")
    athlete_load = (
        weekly_load[weekly_load["Athlete"] == athlete].copy()
        if not weekly_load.empty and "Athlete" in weekly_load.columns
        else pd.DataFrame()
    )
    athlete_wellness = (
        weekly_wellness[weekly_wellness["Athlete"] == athlete].copy()
        if not weekly_wellness.empty and "Athlete" in weekly_wellness.columns
        else pd.DataFrame()
    )
    athlete_external = (
        weekly_external[weekly_external["Athlete"] == athlete].copy()
        if not weekly_external.empty and "Athlete" in weekly_external.columns
        else pd.DataFrame()
    )

    if athlete_load.empty and athlete_wellness.empty and athlete_external.empty:
        st.info("Todavia no hay resumen semanal disponible para este atleta.")
    else:
        if athlete_load.empty:
            st.caption("Sin carga interna semanal para este atleta; se muestra cualquier fuente parcial disponible.")
        else:
            acwr_context_source = _full_history_weekly_load(rpe_df)
            weekly_acwr_context = build_weekly_acwr_context(
                acwr_context_source if not acwr_context_source.empty else weekly_load,
                athlete,
                weeks=acwr_context_weeks,
            )
            current_week_rows = (
                athlete_load.loc[athlete_load["is_current_week"].fillna(False)]
                if "is_current_week" in athlete_load.columns
                else pd.DataFrame()
            )
            if not current_week_rows.empty:
                current_week_start = pd.to_datetime(current_week_rows["week_start"], errors="coerce").dropna().max()
                if pd.notna(current_week_start):
                    st.caption(f"Incluye {_format_week_label(current_week_start, True)}.")
            st.plotly_chart(chart_weekly_acwr_context(weekly_acwr_context, athlete, theme=theme), use_container_width=True)

        chart_left, chart_right = st.columns(2)
        with chart_left:
            if athlete_load.empty:
                st.caption("Sin strain semanal porque no hay sRPE semanal.")
            else:
                st.plotly_chart(chart_weekly_strain(athlete_load, athlete, theme=theme), use_container_width=True)
        with chart_right:
            if athlete_wellness.empty:
                st.caption("Sin wellness semanal para este atleta.")
            else:
                st.plotly_chart(chart_weekly_wellness(athlete_wellness, athlete, theme=theme), use_container_width=True)

        if _has_weekly_external_data(athlete_external):
            st.plotly_chart(chart_weekly_external(athlete_external, athlete, theme=theme), use_container_width=True)
        else:
            st.caption("Sin carga externa semanal clasificada para este atleta.")

    _render_team_weekly_summary(weekly_team)


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
weekly_summaries = _weekly_summaries_from_state(rdf, wdf, raw_df, acwr_dict)
weekly_load = _normalize_weekly_frame(weekly_summaries.get("weekly_load", pd.DataFrame()))
weekly_wellness = _normalize_weekly_frame(weekly_summaries.get("weekly_wellness", pd.DataFrame()))
weekly_external = _normalize_weekly_frame(weekly_summaries.get("weekly_external", pd.DataFrame()))
weekly_team = _normalize_weekly_frame(weekly_summaries.get("weekly_team", pd.DataFrame()))
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

weekly_athlete_options = _weekly_athletes(weekly_load, weekly_wellness, weekly_external)
daily_athlete_options = (
    sorted(rdf["Athlete"].dropna().astype(str).str.strip().unique().tolist())
    if rdf is not None and "Athlete" in rdf.columns
    else []
)
athletes = sorted(set(weekly_athlete_options) | set(daily_athlete_options)) or ["Sin atleta"]
athlete = st.selectbox("Atleta", athletes)
acwr_context_window = st.radio(
    "Rango ACWR semanal",
    ["8 semanas", "16 semanas", "Temporada completa"],
    index=1,
    horizontal=True,
    key="load_page_weekly_acwr_context_window",
)
acwr_context_weeks = {
    "8 semanas": 8,
    "16 semanas": 16,
    "Temporada completa": None,
}.get(acwr_context_window, 16)

_render_weekly_block(
    athlete,
    weekly_load,
    weekly_wellness,
    weekly_external,
    weekly_team,
    theme,
    acwr_context_weeks,
    rdf,
)

if rdf is None or not acwr_dict:
    st.info("Sin modelo diario de carga procesado. La vista semanal canonica puede seguir mostrando wellness o carga externa parcial si existen.")
else:
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
