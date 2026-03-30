"""Vista dedicada de exportacion de reportes."""

import streamlit as st

from modules.page_state import ensure_page_state
from modules.report_generator import (
    build_executive_summary_df,
    build_report_sheets,
    collect_report_athletes,
    export_excel,
    generate_visual_report_pdf,
)


ensure_page_state(load_models=True)

st.header("Reportes")
st.caption("Esta vista exporta Excel. La carga de archivos se hace desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

report_athlete = "Todos"
athletes = collect_report_athletes(dict(st.session_state))
if athletes:
    report_athlete = st.selectbox("Filtrar por atleta", ["Todos"] + athletes)

include_acwr = st.checkbox("ACWR + sRPE", value=True)
include_mono = st.checkbox("Monotonia + Strain", value=True)
include_wellness = st.checkbox("Wellness", value=True)
include_jumps = st.checkbox("Evaluaciones de saltos", value=True)
include_maxes = st.checkbox("Maximos", value=True)
include_volume = st.checkbox("Volumen por sesion", value=True)
include_completion = st.checkbox("Completion", value=True)

summary_df = build_executive_summary_df(dict(st.session_state), report_athlete)
if not summary_df.empty:
    st.markdown("### Resumen ejecutivo")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

if st.button("Generar reporte Excel"):
    sheets = build_report_sheets(
        dict(st.session_state),
        report_athlete,
        include_acwr=include_acwr,
        include_mono=include_mono,
        include_wellness=include_wellness,
        include_jumps=include_jumps,
        include_maxes=include_maxes,
        include_volume=include_volume,
        include_completion=include_completion,
    )
    if not sheets:
        st.warning("No hay datos para exportar.")
    else:
        pdf_bytes = generate_visual_report_pdf(dict(st.session_state), report_athlete)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "Descargar reporte Excel",
                data=export_excel(sheets),
                file_name=f"Threshold_SC_Reporte_{report_athlete.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.download_button(
                "Descargar reporte visual PDF",
                data=pdf_bytes,
                file_name=f"Threshold_SC_Reporte_{report_athlete.replace(' ', '_')}.pdf",
                mime="application/pdf",
            )
