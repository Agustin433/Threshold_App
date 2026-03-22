"""Vista dedicada de monitoreo de carga."""
import pandas as pd
import streamlit as st


def ensure_state():
    keys = [
        "rpe_df", "wellness_df", "completion_df", "rep_load_df",
        "raw_df", "maxes_df", "jump_df", "acwr_dict", "mono_dict",
    ]
    for key in keys:
        if key not in st.session_state:
            st.session_state[key] = None


ensure_state()

st.header("Monitoreo de Carga")
st.caption("La carga de archivos se hace desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

rdf = st.session_state.rpe_df
wdf = st.session_state.wellness_df
acwr_dict = st.session_state.acwr_dict or {}
mono_dict = st.session_state.mono_dict or {}

if rdf is None or not acwr_dict:
    st.info("Todavia no hay datos de carga procesados. Carga RPE + Tiempo desde la pantalla principal y luego volve a esta pagina.")
else:
    athletes = sorted(rdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    athlete = st.selectbox("Atleta", athletes)

    sub_rpe = rdf[rdf["Athlete"] == athlete].sort_values("Date")
    acwr_df = acwr_dict.get(athlete)
    mono_df = mono_dict.get(athlete)

    last_session = sub_rpe.tail(1)
    last_acwr = acwr_df[acwr_df["sRPE_diario"] > 0].tail(1) if acwr_df is not None else pd.DataFrame()
    last_mono = mono_df.tail(1) if mono_df is not None else pd.DataFrame()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("sRPE ultima sesion", f"{last_session['sRPE'].iloc[-1]:.0f} UA" if not last_session.empty else "-")
    c2.metric("RPE ultima sesion", f"{last_session['RPE'].iloc[-1]:.1f}" if not last_session.empty else "-")
    c3.metric("ACWR EWMA", f"{last_acwr['ACWR_EWMA'].iloc[-1]:.2f}" if not last_acwr.empty else "-")
    c4.metric("Monotonia", f"{last_mono['Monotonia'].iloc[-1]:.2f}" if not last_mono.empty else "-")

    st.markdown("### Sesiones recientes")
    display_cols = [c for c in ["Date", "RPE", "Duration_min", "sRPE"] if c in sub_rpe.columns]
    st.dataframe(
        sub_rpe[display_cols].sort_values("Date", ascending=False).head(12),
        width="stretch",
        hide_index=True,
    )

    if acwr_df is not None:
        st.markdown("### Resumen ACWR")
        st.dataframe(
            acwr_df[["Date", "sRPE_diario", "ACWR_EWMA", "ACWR_Classic", "Zona"]]
            .sort_values("Date", ascending=False)
            .head(20),
            width="stretch",
            hide_index=True,
        )

    if mono_df is not None:
        st.markdown("### Monotonia y Strain")
        st.dataframe(
            mono_df.sort_values("Semana", ascending=False).head(12),
            width="stretch",
            hide_index=True,
        )

    if wdf is not None and athlete in wdf["Athlete"].values:
        st.markdown("### Wellness")
        w_sub = wdf[wdf["Athlete"] == athlete].sort_values("Date", ascending=False)
        st.dataframe(w_sub.head(12), width="stretch", hide_index=True)
