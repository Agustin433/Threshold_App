"""Vista dedicada de evaluaciones individuales."""
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

st.header("Evaluacion de Saltos")
st.caption("Esta vista usa solo evaluaciones individuales cargadas desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

jdf = st.session_state.jump_df
if jdf is None or jdf.empty:
    st.info("Todavia no hay evaluaciones individuales procesadas.")
else:
    athletes = sorted(jdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    athlete = st.selectbox("Atleta", athletes)

    athlete_hist = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    latest_eval = athlete_hist.tail(1)

    st.markdown("### Ultima evaluacion")
    st.dataframe(latest_eval, use_container_width=True, hide_index=True)

    st.markdown("### Historial completo")
    st.dataframe(
        athlete_hist.sort_values("Date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

