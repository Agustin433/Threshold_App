"""Vista dedicada de dashboard grupal."""

import pandas as pd
import streamlit as st

from charts.load_charts import chart_completion
from modules.page_state import ensure_page_state
from modules.report_generator import collect_report_athletes


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
    if comp_df is None or comp_df.empty or not {"Date", "Pct"}.issubset(comp_df.columns):
        return pd.DataFrame(columns=["Date", "Pct"])

    result = comp_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Pct"] = pd.to_numeric(result["Pct"], errors="coerce")
    result = result.dropna(subset=["Date", "Pct"])

    if _completion_has_athlete_column(result) and athlete != "Todos":
        result["Athlete"] = result["Athlete"].astype(str).str.strip()
        result = result[result["Athlete"] == athlete]

    if result.empty:
        return pd.DataFrame(columns=["Date", "Pct"])

    return (
        result.groupby("Date", as_index=False)["Pct"]
        .mean()
        .sort_values("Date")
        .reset_index(drop=True)
    )


def _completion_detail_df(comp_df: pd.DataFrame | None, athlete: str = "Todos") -> pd.DataFrame:
    if comp_df is None or comp_df.empty or not {"Date", "Pct"}.issubset(comp_df.columns):
        return pd.DataFrame()

    result = comp_df.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
    result["Pct"] = pd.to_numeric(result["Pct"], errors="coerce")
    result = result.dropna(subset=["Date", "Pct"])

    if _completion_has_athlete_column(result) and athlete != "Todos":
        result["Athlete"] = result["Athlete"].astype(str).str.strip()
        result = result[result["Athlete"] == athlete]

    if result.empty:
        return pd.DataFrame()

    preferred_cols = ["Athlete", "Date", "Assigned", "Completed", "Pct"]
    available_cols = [column for column in preferred_cols if column in result.columns]
    available_cols.extend(column for column in result.columns if column not in available_cols)
    return result[available_cols].sort_values("Date", ascending=False).reset_index(drop=True)


ensure_page_state(load_models=True)

st.header("Dashboard Grupal")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

visible_athletes = collect_report_athletes(dict(st.session_state))
if visible_athletes:
    st.caption(f"{len(visible_athletes)} atleta(s) con datos visibles en la ventana actual.")

acwr_dict = st.session_state.acwr_dict or {}
mono_dict = st.session_state.mono_dict or {}
jdf = st.session_state.jump_df
completion_df = st.session_state.completion_df
maxes_df = st.session_state.maxes_df

if acwr_dict:
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
    st.dataframe(latest[show_cols], use_container_width=True, hide_index=True)

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
        st.info("No hay datos de completion para la selección actual.")
    else:
        metric_cols = st.columns(3)
        metric_cols[0].metric("Completion promedio", f"{completion_view['Pct'].mean():.0f}%")
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
            athlete_summary = (
                completion_detail.groupby("Athlete", as_index=False)
                .agg(
                    Completion_Promedio=("Pct", "mean"),
                    Sesiones=("Pct", "size"),
                    Ultima_Fecha=("Date", "max"),
                )
                .sort_values(["Completion_Promedio", "Sesiones"], ascending=[False, False])
                .reset_index(drop=True)
            )
            athlete_summary["Ultima_Fecha"] = athlete_summary["Ultima_Fecha"].dt.strftime("%d/%m/%Y")
            st.caption("Resumen por atleta")
            st.dataframe(athlete_summary, use_container_width=True, hide_index=True)

        with st.expander("Detalle de completion", expanded=False):
            st.dataframe(completion_detail, use_container_width=True, hide_index=True)
