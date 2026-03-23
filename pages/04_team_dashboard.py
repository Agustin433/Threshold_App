"""Vista dedicada de dashboard grupal."""
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


ensure_state()

st.header("Dashboard Grupal")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

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
        rows.append({
            "Atleta": athlete,
            "sRPE": round(float(last["sRPE_diario"].iloc[-1]), 0),
            "ACWR EWMA": round(float(last["ACWR_EWMA"].iloc[-1]), 2),
            "Zona": last["Zona"].iloc[-1],
            "Monotonia": round(float(mono_last["Monotonia"].iloc[-1]), 2) if not mono_last.empty else None,
            "Strain": round(float(mono_last["Strain"].iloc[-1]), 0) if not mono_last.empty else None,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if jdf is not None and not jdf.empty:
    st.markdown("### Ultima evaluacion por atleta")
    latest = jdf.sort_values("Date").groupby("Athlete").last().reset_index()
    show_cols = [c for c in ["Athlete", "Date", "CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "EUR", "DRI", "IMTP_N", "NM_Profile"] if c in latest.columns]
    st.dataframe(latest[show_cols], use_container_width=True, hide_index=True)

if maxes_df is not None and not maxes_df.empty:
    st.markdown("### Maximos")
    show_cols = [c for c in ["Athlete", "Exercise Name", "Added Date", "Max Value"] if c in maxes_df.columns]
    st.dataframe(
        maxes_df[show_cols].sort_values("Added Date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

if completion_df is not None and not completion_df.empty:
    st.markdown("### Completion")
    st.dataframe(
        completion_df.sort_values("Date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

