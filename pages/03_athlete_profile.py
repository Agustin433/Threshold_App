"""Vista dedicada de perfil de atleta."""

import streamlit as st

from modules.page_state import collect_state_athletes, ensure_page_state


ensure_page_state(load_models=True)

st.header("Perfil del Atleta")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

jdf = st.session_state.jump_df
rdf = st.session_state.rpe_df
wdf = st.session_state.wellness_df
maxes_df = st.session_state.maxes_df

athletes = collect_state_athletes()

if not athletes:
    st.info("Todavia no hay datos de atletas cargados.")
else:
    athlete = st.selectbox("Atleta", athletes)

    c1, c2, c3 = st.columns(3)
    if st.session_state.acwr_dict and athlete in st.session_state.acwr_dict:
        acwr_last = st.session_state.acwr_dict[athlete]
        acwr_last = acwr_last[acwr_last["sRPE_diario"] > 0].tail(1)
        c1.metric("ACWR EWMA", f"{acwr_last['ACWR_EWMA'].iloc[-1]:.2f}" if not acwr_last.empty else "-")
    if wdf is not None and athlete in wdf["Athlete"].values:
        w_last = wdf[wdf["Athlete"] == athlete].sort_values("Date").tail(3)
        c2.metric("Wellness promedio", f"{w_last['Wellness_Score'].mean():.1f}" if not w_last.empty else "-")
    if jdf is not None and athlete in jdf["Athlete"].values:
        j_last = jdf[jdf["Athlete"] == athlete].sort_values("Date").tail(1)
        c3.metric("Ultimo CMJ", f"{j_last['CMJ_cm'].iloc[-1]:.1f} cm" if "CMJ_cm" in j_last.columns and not j_last.empty else "-")

    if jdf is not None and athlete in jdf["Athlete"].values:
        st.markdown("### Evaluaciones")
        st.dataframe(
            jdf[jdf["Athlete"] == athlete].sort_values("Date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    if rdf is not None and athlete in rdf["Athlete"].values:
        st.markdown("### Carga")
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

    if maxes_df is not None and "Athlete" in maxes_df.columns and athlete in maxes_df["Athlete"].values:
        st.markdown("### Maximos")
        st.dataframe(
            maxes_df[maxes_df["Athlete"] == athlete].sort_values("Added Date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
