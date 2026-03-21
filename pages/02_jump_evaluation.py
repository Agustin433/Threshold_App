"""Vista dedicada de evaluaciones."""
import streamlit as st

from eval_module import generate_template_csv


def ensure_state():
    keys = [
        "rpe_df", "wellness_df", "completion_df", "rep_load_df",
        "raw_df", "maxes_df", "jump_df", "acwr_dict", "mono_dict", "eval_df",
    ]
    for key in keys:
        if key not in st.session_state:
            st.session_state[key] = None


ensure_state()

st.header("Evaluacion de Saltos")
st.caption("La carga y el procesamiento se hacen desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

ev_df = st.session_state.eval_df
if ev_df is None or ev_df.empty:
    st.info("Todavia no hay evaluaciones cargadas.")
    st.download_button(
        "Descargar plantilla CSV",
        data=generate_template_csv(),
        file_name="threshold_evaluaciones_template.csv",
        mime="text/csv",
    )
else:
    players = sorted(ev_df["JUGADOR"].dropna().unique())
    player = st.selectbox("Jugador", players)

    player_hist = ev_df[ev_df["JUGADOR"] == player].sort_values("FECHA")
    latest_player = player_hist.tail(1)
    latest_team = ev_df.sort_values("FECHA").groupby("JUGADOR").last().reset_index()

    st.markdown("### Ultima evaluacion del jugador")
    st.dataframe(latest_player, width="stretch", hide_index=True)

    st.markdown("### Historial del jugador")
    st.dataframe(
        player_hist.sort_values("FECHA", ascending=False),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Ranking grupal")
    show_cols = [
        c for c in [
            "JUGADOR", "FECHA", "CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms",
            "DJ_RSI", "EUR", "IMTP_N", "Sprint_10m", "Sprint_20m",
        ] if c in latest_team.columns
    ]
    st.dataframe(
        latest_team[show_cols].sort_values("CMJ_cm", ascending=False),
        width="stretch",
        hide_index=True,
    )
