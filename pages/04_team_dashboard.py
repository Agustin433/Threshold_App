"""Vista dedicada de dashboard grupal."""

import pandas as pd
import streamlit as st

from charts.load_charts import chart_completion
from local_store import load_dataset_for_history_mode
from modules.history_mode import history_mode_caption, render_history_mode_selector
from modules.metrics import calculate_completion_rate, summarize_completion_by_group
from modules.page_state import ensure_load_state, ensure_page_state
from modules.report_generator import collect_report_athletes

WEEKLY_SUMMARY_KEYS = {"weekly_load", "weekly_wellness", "weekly_external", "weekly_team"}


TEAM_COLORS = {
    "navy": "#0D3C5E",
    "steel": "#708C9F",
    "green": "#6F8F78",
    "yellow": "#C4A464",
    "red": "#B56B73",
    "muted": "#5E6A74",
    "bg": "#F5F4F0",
    "card": "#FEFEFE",
    "white": "#221F20",
    "gray": "#4B5560",
    "border": "#D8DEE4",
}

TEAM_THEME = {
    "colors": TEAM_COLORS,
    "layout": dict(
        template="plotly_white",
        paper_bgcolor=TEAM_COLORS["bg"],
        plot_bgcolor=TEAM_COLORS["card"],
        font=dict(family="Barlow, sans-serif", color=TEAM_COLORS["white"], size=11),
        margin=dict(l=44, r=32, t=68, b=48),
    ),
    "grid": "rgba(34, 31, 32, 0.08)",
    "grid_soft": "rgba(34, 31, 32, 0.05)",
    "reference_line": "rgba(34, 31, 32, 0.18)",
    "reference_fill": "rgba(13, 60, 94, 0.06)",
    "legend": dict(
        orientation="h",
        y=-0.18,
        bgcolor="rgba(254, 254, 254, 0.92)",
        bordercolor=TEAM_COLORS["border"],
        borderwidth=1,
        font=dict(size=9, color=TEAM_COLORS["gray"]),
    ),
    "monotony_high": 2.0,
}


def _completion_has_athlete_column(comp_df: pd.DataFrame | None) -> bool:
    return (
        comp_df is not None
        and not comp_df.empty
        and "Athlete" in comp_df.columns
        and comp_df["Athlete"].dropna().astype(str).str.strip().ne("").any()
    )


def _completion_options(comp_df: pd.DataFrame | None) -> list[str]:
    if not _completion_has_athlete_column(comp_df):
        return ["Todos"]
    athletes = sorted(comp_df["Athlete"].dropna().astype(str).str.strip().unique().tolist())
    return ["Todos"] + athletes


def _completion_view_df(comp_df: pd.DataFrame | None, athlete: str = "Todos") -> pd.DataFrame:
    if comp_df is None or comp_df.empty or "Date" not in comp_df.columns:
        return pd.DataFrame(columns=["Date", "Pct"])

    result = comp_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result = result.dropna(subset=["Date"])

    if _completion_has_athlete_column(result) and athlete != "Todos":
        result["Athlete"] = result["Athlete"].astype(str).str.strip()
        result = result[result["Athlete"] == athlete]

    if result.empty:
        return pd.DataFrame(columns=["Date", "Pct"])

    grouped = summarize_completion_by_group(result, "Date", value_column="Pct")
    if grouped.empty:
        return pd.DataFrame(columns=["Date", "Pct"])
    return grouped[["Date", "Pct"]].sort_values("Date").reset_index(drop=True)


def _completion_detail_df(comp_df: pd.DataFrame | None, athlete: str = "Todos") -> pd.DataFrame:
    if comp_df is None or comp_df.empty:
        return pd.DataFrame()

    result = comp_df.copy()
    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    if "Pct" in result.columns:
        result["Pct"] = pd.to_numeric(result["Pct"], errors="coerce")

    if _completion_has_athlete_column(result) and athlete != "Todos":
        result["Athlete"] = result["Athlete"].astype(str).str.strip()
        result = result[result["Athlete"] == athlete]

    if result.empty:
        return pd.DataFrame()

    dated_rows = result.dropna(subset=["Date"]).copy() if "Date" in result.columns else pd.DataFrame()
    if not dated_rows.empty:
        result = dated_rows.sort_values("Date", ascending=False)

    preferred_cols = ["Athlete", "Date", "Assigned", "Completed", "Pct", "completion_scope", "source_type"]
    available_cols = [column for column in preferred_cols if column in result.columns]
    available_cols.extend(column for column in result.columns if column not in available_cols)
    return result[available_cols].reset_index(drop=True)


def _weekly_summaries_from_state(acwr_dict: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    del acwr_dict
    # Centralized build_weekly_summaries(...) caching lives in ensure_load_state().
    ensure_load_state(ensure_base_state=False)
    cached = st.session_state.get("weekly_summaries")
    return cached if isinstance(cached, dict) else {}


def _normalize_weekly_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "week_start" in result.columns:
        result["week_start"] = pd.to_datetime(result["week_start"], errors="coerce")
    if "is_current_week" in result.columns:
        result["is_current_week"] = result["is_current_week"].fillna(False).astype(bool)
    return result


def _current_or_latest_week(frame: pd.DataFrame) -> pd.DataFrame:
    result = _normalize_weekly_frame(frame)
    if result.empty:
        return result
    if "is_current_week" in result.columns:
        current = result[result["is_current_week"].fillna(False)]
        if not current.empty:
            return current.copy()
    if "week_start" in result.columns and result["week_start"].notna().any():
        latest_week = result["week_start"].dropna().max()
        return result[result["week_start"].eq(latest_week)].copy()
    return result


ensure_page_state(load_models=True)

st.header("Dashboard Grupal")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

visible_athletes = collect_report_athletes(dict(st.session_state))
if visible_athletes:
    st.caption(f"{len(visible_athletes)} atleta(s) con datos visibles en la ventana actual.")

ensure_load_state(ensure_base_state=False)
acwr_dict = st.session_state.acwr_dict or {}
mono_dict = st.session_state.mono_dict or {}
jdf = st.session_state.jump_df
completion_df = st.session_state.completion_df
maxes_df = st.session_state.maxes_df
weekly_summaries = _weekly_summaries_from_state(acwr_dict)
weekly_load = _normalize_weekly_frame(weekly_summaries.get("weekly_load", pd.DataFrame()))
weekly_team = _normalize_weekly_frame(weekly_summaries.get("weekly_team", pd.DataFrame()))

current_week_load = _current_or_latest_week(weekly_load)
current_week_team = _current_or_latest_week(weekly_team)

if not current_week_load.empty:
    st.markdown("### Estado semanal de carga del equipo")
    load_display = current_week_load.copy()
    load_display = load_display.sort_values(["weekly_sRPE", "sessions_count"], ascending=[False, False])
    rows = pd.DataFrame(
        {
            "Atleta": load_display["Athlete"],
            "sRPE semanal": pd.to_numeric(load_display["weekly_sRPE"], errors="coerce").round(0),
            "Sesiones": pd.to_numeric(load_display["sessions_count"], errors="coerce").fillna(0).astype(int),
            "ACWR EWMA": pd.to_numeric(load_display["ACWR_EWMA_last"], errors="coerce").round(2),
            "Monotonia": pd.to_numeric(load_display["monotony"], errors="coerce").round(2),
            "Strain": pd.to_numeric(load_display["strain"], errors="coerce").round(0),
        }
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)
elif not current_week_team.empty:
    st.markdown("### Estado semanal del equipo")
    team_display = current_week_team.copy().sort_values("week_start", ascending=False)
    rename_map = {
        "team_sRPE_mean": "sRPE promedio",
        "team_sRPE_sum": "sRPE total",
        "athletes_active": "Atletas activos",
        "team_wellness_mean": "Wellness promedio",
        "team_monotony_mean": "Monotonia promedio",
        "team_strain_mean": "Strain promedio",
    }
    team_display = team_display.rename(columns=rename_map)
    display_cols = [column for column in rename_map.values() if column in team_display.columns]
    st.dataframe(team_display[display_cols], use_container_width=True, hide_index=True)
elif acwr_dict:
    st.markdown("### Estado de carga del equipo")
    rows = []
    for athlete, adf in acwr_dict.items():
        last = adf[adf["sRPE_diario"] > 0].tail(1)
        mono = mono_dict.get(athlete)
        mono_last = mono.tail(1) if mono is not None else pd.DataFrame()
        if last.empty:
            continue
        rows.append(
            {
                "Atleta": athlete,
                "sRPE": round(float(last["sRPE_diario"].iloc[-1]), 0),
                "ACWR EWMA": round(float(last["ACWR_EWMA"].iloc[-1]), 2),
                "Zona": last["Zona"].iloc[-1],
                "Monotonia": round(float(mono_last["Monotonia"].iloc[-1]), 2) if not mono_last.empty else None,
                "Strain": round(float(mono_last["Strain"].iloc[-1]), 0) if not mono_last.empty else None,
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if jdf is not None and not jdf.empty:
    st.markdown("### Ultima evaluacion por atleta")
    latest = jdf.sort_values("Date").groupby("Athlete").last().reset_index()
    show_cols = [
        col
        for col in ["Athlete", "Date", "CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "EUR", "DRI", "IMTP_N", "NM_Profile"]
        if col in latest.columns
    ]
    st.dataframe(
        latest[show_cols].rename(columns={"EUR": "EUR (ratio)"}),
        use_container_width=True,
        hide_index=True,
    )

if maxes_df is not None and not maxes_df.empty:
    st.markdown("### Maximos")
    show_cols = [col for col in ["Athlete", "Exercise Name", "Added Date", "Max Value"] if col in maxes_df.columns]
    st.dataframe(
        maxes_df[show_cols].sort_values("Added Date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

if completion_df is not None and not completion_df.empty:
    st.markdown("### Completion")
    completion_history_mode = render_history_mode_selector(key="team_dashboard_completion_history_mode")
    completion_df = load_dataset_for_history_mode("completion_df", completion_history_mode)
    completion_scope = "Todos"
    if _completion_has_athlete_column(completion_df):
        completion_scope = st.selectbox(
            "Filtrar completion por atleta",
            _completion_options(completion_df),
            key="team_dashboard_completion_scope",
        )
    else:
        st.caption("El Completion Report actual no trae columna de atleta. Se muestra la vista global.")

    completion_view = _completion_view_df(completion_df, completion_scope)
    completion_detail = _completion_detail_df(completion_df, completion_scope)

    if completion_view.empty:
        if completion_detail.empty:
            st.info("No hay datos de completion para la selección actual.")
        else:
            completion_rate = calculate_completion_rate(completion_detail)
            completion_value = completion_rate.value if completion_rate.value is not None else 0.0
            st.caption("Vista: historial sin fechas. Se muestra como snapshot acumulado del periodo cargado.")
            metric_cols = st.columns(3)
            metric_cols[0].metric("Completion ponderado", f"{completion_value:.0f}%")
            metric_cols[1].metric("Filas visibles", len(completion_detail))
            metric_cols[2].metric("Rango", "Sin fechas")
            detail_cols = [column for column in ["Athlete", "Assigned", "Completed", "Pct"] if column in completion_detail.columns]
            st.dataframe(completion_detail[detail_cols], use_container_width=True, hide_index=True)
    else:
        completion_rate = calculate_completion_rate(completion_detail)
        if completion_rate.value is None:
            completion_rate = calculate_completion_rate(completion_view)
        completion_value = completion_rate.value if completion_rate.value is not None else 0.0
        st.caption(history_mode_caption(completion_view, mode=completion_history_mode, date_col="Date"))
        metric_cols = st.columns(3)
        metric_cols[0].metric("Completion ponderado", f"{completion_value:.0f}%")
        metric_cols[1].metric("Sesiones visibles", len(completion_view))
        metric_cols[2].metric(
            "Ultima fecha",
            completion_view["Date"].max().strftime("%d/%m/%Y"),
        )

        st.plotly_chart(
            chart_completion(completion_view, theme=TEAM_THEME, athlete_label=completion_scope),
            use_container_width=True,
        )

        if completion_scope == "Todos" and _completion_has_athlete_column(completion_detail):
            athlete_summary = summarize_completion_by_group(
                completion_detail,
                "Athlete",
                value_column="Completion_Promedio",
            )
            athlete_meta = (
                completion_detail.groupby("Athlete", as_index=False)
                .agg(Sesiones=("Date", "size"), Ultima_Fecha=("Date", "max"))
            )
            athlete_summary = athlete_summary.merge(athlete_meta, on="Athlete", how="left")
            athlete_summary = athlete_summary.sort_values(
                ["Completion_Promedio", "Sesiones"],
                ascending=[False, False],
            ).reset_index(drop=True)
            athlete_summary["Ultima_Fecha"] = athlete_summary["Ultima_Fecha"].dt.strftime("%d/%m/%Y")
            st.caption("Resumen por atleta")
            st.dataframe(athlete_summary, use_container_width=True, hide_index=True)

        with st.expander("Detalle de completion", expanded=False):
            st.dataframe(completion_detail, use_container_width=True, hide_index=True)
