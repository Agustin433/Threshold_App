"""Vista dedicada de exportacion de reportes."""
from io import BytesIO

import pandas as pd
import streamlit as st
from local_store import build_load_models, load_recent_state


def ensure_state():
    keys = [
        "rpe_df", "wellness_df", "completion_df", "rep_load_df",
        "raw_df", "maxes_df", "jump_df", "acwr_dict", "mono_dict",
    ]
    for key in keys:
        if key not in st.session_state:
            st.session_state[key] = None

    stored_state = load_recent_state()
    for key in keys:
        if st.session_state[key] is None:
            st.session_state[key] = stored_state.get(key)

    if st.session_state.rpe_df is not None and (
        st.session_state.acwr_dict is None or st.session_state.mono_dict is None
    ):
        acwr_dict, mono_dict = build_load_models(st.session_state.rpe_df)
        st.session_state.acwr_dict = acwr_dict or None
        st.session_state.mono_dict = mono_dict or None


def export_excel(data_dict: dict) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in data_dict.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return buf.getvalue()


ensure_state()

st.header("Reportes")
st.caption("Esta vista exporta Excel. La carga de archivos se hace desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

report_athlete = "Todos"
athletes = set()
for df in [st.session_state.rpe_df, st.session_state.jump_df, st.session_state.maxes_df, st.session_state.rep_load_df]:
    if df is not None and "Athlete" in df.columns:
        athletes.update(df["Athlete"].dropna().unique())

if athletes:
    report_athlete = st.selectbox("Filtrar por atleta", ["Todos"] + sorted(athletes))

include_acwr = st.checkbox("ACWR + sRPE", value=True)
include_mono = st.checkbox("Monotonia + Strain", value=True)
include_wellness = st.checkbox("Wellness", value=True)
include_jumps = st.checkbox("Evaluaciones de saltos", value=True)
include_maxes = st.checkbox("Maximos", value=True)
include_volume = st.checkbox("Volumen por sesion", value=True)
include_completion = st.checkbox("Completion", value=True)

if st.button("Generar reporte Excel"):
    sheets = {}

    if include_acwr and st.session_state.acwr_dict:
        acwr_rows = []
        for athlete, adf in st.session_state.acwr_dict.items():
            if report_athlete != "Todos" and athlete != report_athlete:
                continue
            temp = adf.copy()
            temp["Athlete"] = athlete
            acwr_rows.append(temp)
        if acwr_rows:
            sheets["ACWR_sRPE"] = pd.concat(acwr_rows)

    if include_mono and st.session_state.mono_dict:
        mono_rows = []
        for athlete, mdf in st.session_state.mono_dict.items():
            if report_athlete != "Todos" and athlete != report_athlete:
                continue
            temp = mdf.copy()
            temp["Athlete"] = athlete
            mono_rows.append(temp)
        if mono_rows:
            sheets["Monotonia_Strain"] = pd.concat(mono_rows)

    if include_wellness and st.session_state.wellness_df is not None:
        df = st.session_state.wellness_df
        if report_athlete != "Todos":
            df = df[df["Athlete"] == report_athlete]
        sheets["Wellness"] = df

    if include_jumps and st.session_state.jump_df is not None:
        df = st.session_state.jump_df
        if report_athlete != "Todos":
            df = df[df["Athlete"] == report_athlete]
        sheets["Evaluaciones_Saltos"] = df

    if include_maxes and st.session_state.maxes_df is not None:
        df = st.session_state.maxes_df
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Maximos_Ejercicios"] = df

    if include_volume and st.session_state.rep_load_df is not None:
        df = st.session_state.rep_load_df
        if report_athlete != "Todos" and "Athlete" in df.columns:
            df = df[df["Athlete"] == report_athlete]
        sheets["Volumen_Sesion"] = df

    if include_completion and st.session_state.completion_df is not None:
        sheets["Completion_Rate"] = st.session_state.completion_df

    sheets = {name: df for name, df in sheets.items() if df is not None and not df.empty}
    if not sheets:
        st.warning("No hay datos para exportar.")
    else:
        st.download_button(
            "Descargar reporte Excel",
            data=export_excel(sheets),
            file_name=f"Threshold_SC_Reporte_{report_athlete.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

