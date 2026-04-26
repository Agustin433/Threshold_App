"""Vista dedicada de exportacion de reportes."""

import pandas as pd
import streamlit as st

from modules.page_state import ensure_page_state
from modules.report_generator import (
    REPORT_AUDIENCE_OPTIONS,
    REPORT_SHEET_ORDER,
    REPORT_SHEET_EXPORT_NAMES,
    build_report_executive_sheet,
    build_report_sheets,
    collect_report_athletes,
    export_excel,
    generate_visual_report_pdf,
    normalize_report_audience,
    report_requires_individual,
    resolve_report_scope,
)


ensure_page_state(load_models=True)

st.header("Reportes")
st.caption("Esta vista exporta Excel. La carga de archivos se hace desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

report_state = dict(st.session_state)
report_athlete = "Todos"
audience_choice = st.selectbox("Destinatario del PDF", list(REPORT_AUDIENCE_OPTIONS.keys()), index=1)
report_audience = normalize_report_audience(REPORT_AUDIENCE_OPTIONS[audience_choice])
athletes = collect_report_athletes(report_state)
scope_options = athletes if report_requires_individual(report_audience) else ["Todos"] + athletes
if scope_options:
    report_athlete = st.selectbox(
        "Atleta del reporte" if report_requires_individual(report_audience) else "Filtrar por atleta",
        scope_options,
    )
elif report_requires_individual(report_audience):
    st.warning("No hay atletas disponibles para esta audiencia individual.")

include_technical_annex = st.checkbox(
    "Agregar anexo tecnico al Excel",
    value=False,
    disabled=report_audience != "profe",
)
if include_technical_annex:
    include_acwr = st.checkbox("ACWR + sRPE", value=True)
    include_mono = st.checkbox("Monotonia + Strain", value=True)
    include_wellness = st.checkbox("Wellness", value=True)
    include_jumps = st.checkbox("Evaluaciones de saltos", value=True)
    include_maxes = st.checkbox("Maximos", value=True)
    include_volume = st.checkbox("Volumen por sesion", value=True)
    include_completion = st.checkbox("Completion detallado", value=True)
else:
    include_acwr = False
    include_mono = False
    include_wellness = False
    include_jumps = False
    include_maxes = False
    include_volume = False
    include_completion = False

effective_report_athlete = resolve_report_scope(report_state, report_athlete, report_audience)
summary_df = build_report_executive_sheet(report_state, report_athlete, report_audience)
if not summary_df.empty:
    st.markdown("### Resumen ejecutivo")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

if st.button("Generar reporte Excel", disabled=effective_report_athlete is None):
    sheets = build_report_sheets(
        report_state,
        effective_report_athlete or report_athlete,
        report_audience=report_audience,
        include_technical_annex=include_technical_annex,
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
        ordered_sheet_names = [name for name in REPORT_SHEET_ORDER if name in sheets]
        ordered_sheet_names.extend(name for name in sheets if name not in ordered_sheet_names)
        curated_sheets = {"Resumen_Ejecutivo", "Interpretacion", "Completion_Resumen", "Reporte_Meta"}
        sheet_rows = [
            {
                "Tipo": "Corazon curado" if sheet_name in curated_sheets else "Anexo tecnico",
                "Seccion": sheet_name.replace("_", " "),
                "Hoja Excel": REPORT_SHEET_EXPORT_NAMES.get(sheet_name, sheet_name),
                "Filas": len(sheets[sheet_name]),
            }
            for sheet_name in ordered_sheet_names
        ]
        st.caption("Paquete exportable listo")
        st.dataframe(pd.DataFrame(sheet_rows), use_container_width=True, hide_index=True)
        pdf_bytes = generate_visual_report_pdf(report_state, effective_report_athlete or report_athlete, report_audience)
        audience_slug = audience_choice.replace(" ", "_")
        athlete_slug = (effective_report_athlete or report_athlete).replace(" ", "_")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "Descargar reporte Excel",
                data=export_excel(sheets),
                file_name=f"Threshold_SC_Reporte_{athlete_slug}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.download_button(
                "Descargar reporte visual PDF",
                data=pdf_bytes,
                file_name=f"Threshold_SC_Reporte_{athlete_slug}_{audience_slug}.pdf",
                mime="application/pdf",
            )
