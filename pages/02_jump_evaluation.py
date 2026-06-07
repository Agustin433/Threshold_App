"""Vista dedicada de evaluaciones individuales."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from charts.dashboard_charts import (
    chart_cmj_trend,
    chart_composite_profile_radar,
    chart_jump_metric_trend,
    make_force_time_points_chart,
    make_left_right_force_chart,
    make_rfd_points_chart,
)
from modules.force_time_analysis import (
    get_asymmetry_summary,
    get_force_time_points,
    get_force_time_interpretation_lines,
    get_force_time_presence_report,
    get_rfd_points,
    interpret_hamstring_force_time,
    interpret_imtp_force_time,
    list_force_time_test_rows,
    select_basic_force_time_test_row,
    select_force_time_test_row,
    summarize_force_time_test,
)
from modules.jump_analysis import (
    build_composite_profile_metric_table,
    build_composite_profile_snapshot,
    build_dashboard_neuromuscular_payload,
    build_jump_baseline_display_table,
    build_jump_delta_display_table,
    build_jump_temporal_context,
    compute_baseline_delta,
    compute_swc_delta,
    select_primary_profile_row,
)
from modules.page_state import ensure_page_state
from modules.page_visuals import build_page_theme


SELECTED_METRIC_CONFIG = [
    ("CMJ", "CMJ_cm", "cm", ".1f"),
    ("SJ", "SJ_cm", "cm", ".1f"),
    ("DJ", "DJ_cm", "cm", ".1f"),
    ("DJ RSI", "DJ_RSI", "m/s", ".2f"),
    ("DRI", "DRI", "", ".3f"),
    ("IMTP relPF", "IMTP_relPF", "N/kg", ".2f"),
    ("EUR (ratio)", "EUR", "", ".3f"),
]


def _render_flag_chips(flags: list[dict[str, str]]) -> None:
    if not flags:
        return

    palette = {
        "green": ("rgba(111,143,120,0.16)", "#446555"),
        "yellow": ("rgba(196,164,100,0.18)", "#7C5D1F"),
        "red": ("rgba(181,107,115,0.18)", "#7B3D45"),
        "gray": ("rgba(112,140,159,0.16)", "#41515E"),
    }
    chips = []
    for flag in flags:
        bg, fg = palette.get(flag["level"], ("rgba(112,140,159,0.16)", "#41515E"))
        chips.append(
            f'<span style="display:inline-flex;align-items:center;padding:0.35rem 0.7rem;'
            f'border-radius:999px;background:{bg};color:{fg};font-size:0.88rem;'
            'font-weight:600;border:1px solid rgba(13,60,94,0.08);">'
            f"{html.escape(flag['text'])}</span>"
        )
    st.markdown(
        f'<div style="display:flex;gap:0.45rem;flex-wrap:wrap;margin:0.2rem 0 0.9rem;">{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )


def _render_feedback(lines: list[str]) -> None:
    if not lines:
        return
    content = "".join(
        f'<div style="margin:0 0 0.38rem;color:#221F20;">{html.escape(line)}</div>'
        for line in lines
    )
    st.markdown(
        '<div style="background:#FEFEFE;border:1px solid rgba(13,60,94,0.10);'
        'border-radius:16px;padding:1rem 1.1rem;margin:0.6rem 0 1rem;'
        'box-shadow:0 1px 0 rgba(13,60,94,0.04);">'
        '<div style="font-size:0.78rem;letter-spacing:0.08em;text-transform:uppercase;'
        'color:#708C9F;font-weight:700;margin-bottom:0.55rem;">Devolucion automatica</div>'
        f"{content}</div>",
        unsafe_allow_html=True,
    )


def _render_temporal_delta_table(delta_df: pd.DataFrame) -> None:
    display_df = build_jump_delta_display_table(delta_df)
    if display_df.empty:
        st.caption("No hay variables comparables para esta evaluacion.")
        return

    signal_palette = {
        "mejora relevante": ("rgba(111,143,120,0.16)", "#446555"),
        "caida relevante": ("rgba(181,107,115,0.18)", "#7B3D45"),
        "sin cambio relevante": ("rgba(112,140,159,0.16)", "#41515E"),
        "sin dato anterior": ("rgba(196,164,100,0.12)", "#6D5D3C"),
    }
    signal_values = delta_df["Signal"].reset_index(drop=True)

    def _style_signal(column: pd.Series) -> list[str]:
        styles: list[str] = []
        for idx, _ in enumerate(column):
            bg, fg = signal_palette.get(signal_values.iloc[idx], ("rgba(112,140,159,0.16)", "#41515E"))
            styles.append(f"background-color: {bg}; color: {fg}; font-weight: 700;")
        return styles

    styler = display_df.style.apply(_style_signal, subset=["Senal"])
    st.dataframe(styler, use_container_width=True, hide_index=True)


def _render_baseline_delta_table(baseline_df: pd.DataFrame) -> None:
    display_df = build_jump_baseline_display_table(baseline_df)
    if display_df.empty:
        st.caption("No hay variables comparables para baseline.")
        return

    signal_palette = {
        "mejora vs baseline": ("rgba(111,143,120,0.16)", "#446555"),
        "caida vs baseline": ("rgba(181,107,115,0.18)", "#7B3D45"),
        "sin cambio vs baseline": ("rgba(112,140,159,0.16)", "#41515E"),
        "baseline insuficiente": ("rgba(196,164,100,0.12)", "#6D5D3C"),
        "sin dato actual": ("rgba(112,140,159,0.12)", "#41515E"),
    }
    signal_values = baseline_df["Signal"].reset_index(drop=True)

    def _style_signal(column: pd.Series) -> list[str]:
        styles: list[str] = []
        for idx, _ in enumerate(column):
            bg, fg = signal_palette.get(signal_values.iloc[idx], ("rgba(112,140,159,0.16)", "#41515E"))
            styles.append(f"background-color: {bg}; color: {fg}; font-weight: 700;")
        return styles

    styler = display_df.style.apply(_style_signal, subset=["Senal"])
    st.dataframe(styler, use_container_width=True, hide_index=True)


def _format_eval_date(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else "Sin fecha"


def _format_force_time_metric(value: object, *, fmt: str, unit: str) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "Sin dato"
    suffix = f" {unit}".rstrip()
    return f"{float(numeric):{fmt}}{suffix}"


def _format_side_label(side: object) -> str:
    if side == "left":
        return "izquierda"
    if side == "right":
        return "derecha"
    return "Sin dato"


def _format_force_time_presence_preview(value: object) -> str:
    if value is None:
        return "-"
    try:
        if bool(pd.isna(value)):
            return "-"
    except Exception:
        pass
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    text = str(value).strip()
    return text if len(text) <= 32 else f"{text[:29]}..."


def _build_force_time_field_presence_table(
    row_or_record: object,
    *,
    fields: list[str],
) -> pd.DataFrame:
    source = row_or_record.to_dict() if hasattr(row_or_record, "to_dict") else {}
    rows: list[dict[str, object]] = []
    for field in fields:
        value = source.get(field)
        try:
            non_null = not bool(pd.isna(value))
        except Exception:
            non_null = value is not None
        rows.append(
            {
                "Campo": field,
                "Columna existe": "Si" if field in source else "No",
                "Valor no nulo": "Si" if non_null else "No",
                "Vista previa": _format_force_time_presence_preview(value),
            }
        )
    return pd.DataFrame(rows)


def _prepare_force_time_detection_rows(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df is None or rows_df.empty:
        return pd.DataFrame(columns=["Fecha", "Dato basico", "Puntos force-time", "Force-time valido", "Campos no nulos"])
    display = rows_df.copy()
    display["Fecha"] = display["Date"].map(_format_eval_date)
    for column in ("has_basic_data", "has_force_time_points", "has_valid_force_time"):
        display[column] = display[column].map(lambda value: "Si" if bool(value) else "No")
    display = display.rename(
        columns={
            "has_basic_data": "Dato basico",
            "has_force_time_points": "Puntos force-time",
            "has_valid_force_time": "Force-time valido",
            "non_null_field_count": "Campos no nulos",
        }
    )
    return display[["Fecha", "Dato basico", "Puntos force-time", "Force-time valido", "Campos no nulos"]]


def _render_force_time_interpretation(
    interpretation: dict[str, object],
    *,
    heading: str,
) -> None:
    sections = get_force_time_interpretation_lines(interpretation)
    if not sections:
        return
    content = "".join(
        f'<div style="margin:0 0 0.42rem;color:#221F20;">{html.escape(section)}</div>'
        for section in sections
    )
    st.markdown(
        '<div style="background:#FEFEFE;border:1px solid rgba(13,60,94,0.10);'
        'border-radius:16px;padding:1rem 1.1rem;margin:0.4rem 0 1rem;'
        'box-shadow:0 1px 0 rgba(13,60,94,0.04);">'
        '<div style="font-size:0.78rem;letter-spacing:0.08em;text-transform:uppercase;'
        f'color:#708C9F;font-weight:700;margin-bottom:0.55rem;">{html.escape(heading)}</div>'
        f"{content}</div>",
        unsafe_allow_html=True,
    )


def _render_force_time_detail_block(
    *,
    title: str,
    caption: str,
    interpretation_heading: str,
    summary: dict[str, object],
    interpretation: dict[str, object],
    theme: dict,
) -> None:
    asymmetry_summary = get_asymmetry_summary(summary)
    force_time_points = get_force_time_points(summary)
    rfd_points = get_rfd_points(summary)

    st.markdown(f"### {title}")
    st.caption(caption)

    force_metrics = st.columns(4)
    force_metrics[0].metric(
        "Peak Force",
        _format_force_time_metric(summary.get("peak_force_n"), fmt=".0f", unit="N"),
    )
    force_metrics[1].metric(
        "Force Avg",
        _format_force_time_metric(summary.get("avg_force_n"), fmt=".0f", unit="N"),
    )
    force_metrics[2].metric(
        "Time to Peak",
        _format_force_time_metric(summary.get("time_to_peak_s"), fmt=".2f", unit="s"),
    )
    force_metrics[3].metric(
        "Asymmetry",
        _format_force_time_metric(summary.get("absolute_asymmetry_pct"), fmt=".1f", unit="%"),
    )

    asymmetry_chart_col, asymmetry_text_col = st.columns([1.1, 0.9])
    with asymmetry_chart_col:
        left_right_chart = make_left_right_force_chart(asymmetry_summary, theme=theme)
        if left_right_chart is None:
            st.info("Sin datos suficientes para comparar fuerza maxima entre lados.")
        else:
            st.plotly_chart(left_right_chart, use_container_width=True)
    with asymmetry_text_col:
        stronger_side = asymmetry_summary.get("stronger_side")
        weaker_side = asymmetry_summary.get("weaker_side")
        side_difference_n = asymmetry_summary.get("side_difference_n")
        st.markdown(f"**Mayor produccion:** {_format_side_label(stronger_side)}")
        st.markdown(f"**Menor produccion:** {_format_side_label(weaker_side)}")
        st.markdown(
            f"**Diferencia:** {_format_force_time_metric(side_difference_n, fmt='.0f', unit='N')}"
        )
        st.markdown(
            f"**Interpretacion:** {asymmetry_summary.get('interpretation') or 'Sin datos suficientes para interpretar asimetria.'}"
        )

    profile_left, profile_right = st.columns(2)
    with profile_left:
        force_time_chart = make_force_time_points_chart(force_time_points, theme=theme)
        if force_time_chart is None:
            st.info("Sin datos suficientes para mostrar el perfil force-time por puntos exportados.")
        else:
            st.plotly_chart(force_time_chart, use_container_width=True)
        st.caption(
            "Perfil force-time por puntos exportados: 50, 100, 150, 200, 250 ms y Peak Force."
        )
    with profile_right:
        rfd_chart = make_rfd_points_chart(rfd_points, theme=theme)
        if rfd_chart is None:
            st.info("Sin datos suficientes para mostrar RFD por ventanas exportadas.")
        else:
            st.plotly_chart(rfd_chart, use_container_width=True)
        st.caption(
            "RFD = tasa de desarrollo de fuerza. Sin un TE o umbral de confiabilidad propio, "
            "conviene leerla con cautela y como apoyo descriptivo."
        )

    _render_force_time_interpretation(interpretation, heading=interpretation_heading)


def _render_history_chart(
    athlete_hist: pd.DataFrame,
    athlete: str,
    label: str,
    metric_key: str,
    *,
    theme: dict,
) -> None:
    valid_points = 0
    if metric_key in athlete_hist.columns:
        valid_points = int(pd.to_numeric(athlete_hist[metric_key], errors="coerce").notna().sum())

    if valid_points < 2:
        st.info(f"No hay suficientes puntos de {label} para mostrar tendencia.")
        return

    if metric_key == "CMJ_cm":
        figure = chart_cmj_trend(athlete_hist, athlete, theme=theme)
    else:
        figure = chart_jump_metric_trend(athlete_hist, athlete, metric_key, theme=theme)
    st.plotly_chart(figure, use_container_width=True)


ensure_page_state(load_models=False)

st.header("Evaluacion de Saltos")
st.caption("Esta vista usa solo evaluaciones individuales cargadas desde la app principal.")
st.page_link("app.py", label="Abrir dashboard principal")

theme = build_page_theme()
jdf = st.session_state.jump_df

if jdf is None or jdf.empty:
    st.info("Todavia no hay evaluaciones individuales procesadas.")
else:
    athletes = sorted(jdf["Athlete"].dropna().unique()) or ["Sin atleta"]
    controls_left, controls_right = st.columns([1.3, 1])
    with controls_left:
        athlete = st.selectbox("Atleta", athletes)

    athlete_hist = jdf[jdf["Athlete"] == athlete].sort_values("Date")
    date_options = athlete_hist["Date"].dropna().drop_duplicates().sort_values(ascending=False).tolist()
    with controls_right:
        selected_date = st.selectbox(
            "Evaluacion",
            date_options,
            format_func=lambda value: pd.Timestamp(value).strftime("%d/%m/%Y"),
        )

    selected_date_value = pd.Timestamp(selected_date).normalize()
    selected_rows = athlete_hist[athlete_hist["Date"] == selected_date_value].sort_values("Date")
    fallback_selected_row = selected_rows.iloc[-1] if not selected_rows.empty else athlete_hist.iloc[-1]
    primary_profile_row = select_primary_profile_row(athlete_hist, selected_date_value)
    primary_detail_row = primary_profile_row if primary_profile_row is not None else fallback_selected_row
    primary_detail_date = pd.to_datetime(primary_detail_row.get("Date"), errors="coerce")
    primary_detail_rows = (
        athlete_hist[athlete_hist["Date"] == primary_detail_date].sort_values("Date")
        if pd.notna(primary_detail_date)
        else selected_rows
    )
    if primary_detail_rows.empty:
        primary_detail_rows = selected_rows if not selected_rows.empty else athlete_hist.tail(1)

    imtp_force_time_row = select_force_time_test_row(
        athlete_hist,
        test_id="imtp",
        selected_date=selected_date_value,
    )
    imtp_basic_row = select_basic_force_time_test_row(
        athlete_hist,
        test_id="imtp",
        selected_date=selected_date_value,
    )
    iso_ham_force_time_row = select_force_time_test_row(
        athlete_hist,
        test_id="iso_push_hamstring",
        selected_date=selected_date_value,
    )
    iso_ham_basic_row = select_basic_force_time_test_row(
        athlete_hist,
        test_id="iso_push_hamstring",
        selected_date=selected_date_value,
    )
    current_profile_row, current_profile_sources = build_composite_profile_snapshot(athlete_hist)
    delta_df = compute_swc_delta(athlete_hist, primary_detail_date)
    baseline_df = compute_baseline_delta(athlete_hist, primary_detail_date)
    temporal_lines = build_jump_temporal_context(delta_df)
    selected_profile_payload = build_dashboard_neuromuscular_payload(primary_detail_row)
    current_profile_payload = (
        build_dashboard_neuromuscular_payload(current_profile_row)
        if current_profile_row is not None
        else None
    )
    selected_feedback_lines = list(selected_profile_payload.get("feedback_lines", [])) + temporal_lines

    st.markdown("### Evaluacion seleccionada")
    st.caption(f"Fecha elegida para el detalle puntual: {_format_eval_date(selected_date)}")
    if pd.notna(primary_detail_date) and primary_detail_date != selected_date_value:
        st.caption(
            "La fecha elegida contiene solo datos complementarios o parciales. "
            f"El detalle principal usa la ultima evaluacion valida del {_format_eval_date(primary_detail_date)}."
        )
    metrics = st.columns(6)
    for column, (label, key, unit, fmt) in zip(metrics, SELECTED_METRIC_CONFIG):
        value = primary_detail_row.get(key)
        suffix = f" {unit}".rstrip()
        column.metric(label, f"{value:{fmt}}{suffix}" if pd.notna(value) else "-")

    st.caption(
        "Referencia EUR (ratio): 1.00-1.35. Los benchmarks externos son orientativos para futbol profesional masculino."
    )
    st.markdown("### Cambios vs evaluacion anterior")
    _render_temporal_delta_table(delta_df)
    if not delta_df.empty and delta_df["Signal"].eq("sin dato anterior").all():
        st.caption(
            "Primera evaluacion registrada para este atleta. El threshold individual tipo Hopkins estara disponible a partir de la tercera medicion valida por variable."
        )
    st.markdown("### Cambio vs baseline")
    st.caption("Baseline fijo por variable: promedio de las primeras 3 mediciones validas.")
    _render_baseline_delta_table(baseline_df)
    if not baseline_df.empty and baseline_df["Signal"].eq("baseline insuficiente").all():
        st.caption(
            "Baseline insuficiente: se necesitan al menos 3 mediciones validas por variable para establecer la referencia inicial."
        )
    _render_flag_chips(list(selected_profile_payload.get("flag_rows", [])))
    _render_feedback(selected_feedback_lines)

    st.markdown("### Detalle de la evaluacion seleccionada")
    detail_cols = [column for column in primary_detail_rows.columns if not column.endswith("_reps")]
    st.dataframe(
        primary_detail_rows[detail_cols].rename(columns={"EUR": "EUR (ratio)"}),
        use_container_width=True,
        hide_index=True,
    )

    imtp_force_time_summary = summarize_force_time_test(imtp_force_time_row, test_id="imtp")
    imtp_basic_presence = get_force_time_presence_report(imtp_basic_row, test_id="imtp")
    if imtp_force_time_summary.get("has_valid_force_time"):
        _render_force_time_detail_block(
            title="Detalle force-time IMTP",
            caption=(
                "Perfil por puntos derivado del resumen exportado. Este bloque usa valores exportados "
                "por ventana y no representa una curva force-time continua de adquisicion."
            ),
            interpretation_heading="Lectura IMTP force-time",
            summary=imtp_force_time_summary,
            interpretation=interpret_imtp_force_time(imtp_force_time_summary),
            theme=theme,
        )
    elif imtp_basic_presence.get("has_basic_data"):
        st.caption(
            "IMTP cargado, pero sin datos force-time suficientes para graficar el perfil por puntos."
        )

    iso_ham_force_time_summary = summarize_force_time_test(
        iso_ham_force_time_row,
        test_id="iso_push_hamstring",
    )
    if iso_ham_force_time_summary.get("has_valid_force_time"):
        _render_force_time_detail_block(
            title="Fuerza isometrica complementaria - ISO Push Hip-Hamstring",
            caption=(
                "Perfil force-time por puntos exportados para una lectura complementaria de la cadena posterior "
                "y los flexores de rodilla. Este bloque usa valores exportados por ventana y no representa "
                "una curva force-time continua de adquisicion."
            ),
            interpretation_heading="Lectura ISO Push Hip-Hamstring force-time",
            summary=iso_ham_force_time_summary,
            interpretation=interpret_hamstring_force_time(iso_ham_force_time_summary),
            theme=theme,
        )

    with st.expander("Estado de deteccion force-time", expanded=False):
        imtp_force_time_presence = get_force_time_presence_report(imtp_force_time_row, test_id="imtp")
        iso_ham_force_time_presence = get_force_time_presence_report(
            iso_ham_force_time_row,
            test_id="iso_push_hamstring",
        )
        iso_ham_basic_presence = get_force_time_presence_report(
            iso_ham_basic_row,
            test_id="iso_push_hamstring",
        )
        imtp_history = list_force_time_test_rows(athlete_hist, test_id="imtp")
        iso_ham_history = list_force_time_test_rows(athlete_hist, test_id="iso_push_hamstring")
        imtp_any_rows = imtp_history[imtp_history["non_null_field_count"] > 0].copy()
        imtp_force_rows = imtp_history[imtp_history["has_force_time_points"]].copy()
        imtp_candidate_row = imtp_force_time_row if imtp_force_time_row is not None else imtp_basic_row
        detection_rows = pd.DataFrame(
            [
                {
                    "Bloque": "IMTP force-time",
                    "Fecha basica": _format_eval_date(
                        imtp_basic_row.get("Date") if imtp_basic_row is not None else None
                    ),
                    "Fecha detectada": _format_eval_date(
                        imtp_force_time_row.get("Date") if imtp_force_time_row is not None else None
                    ),
                    "Force-time valido": "Si" if imtp_force_time_summary.get("has_valid_force_time") else "No",
                    "Campos no nulos": imtp_force_time_presence.get("non_null_field_count", 0),
                    "Columnas detectadas": imtp_force_time_presence.get("available_column_count", 0),
                },
                {
                    "Bloque": "ISO Push Hip-Hamstring",
                    "Fecha basica": _format_eval_date(
                        iso_ham_basic_row.get("Date") if iso_ham_basic_row is not None else None
                    ),
                    "Fecha detectada": _format_eval_date(
                        iso_ham_force_time_row.get("Date") if iso_ham_force_time_row is not None else None
                    ),
                    "Force-time valido": "Si" if iso_ham_force_time_summary.get("has_valid_force_time") else "No",
                    "Campos no nulos": iso_ham_force_time_presence.get("non_null_field_count", 0),
                    "Columnas detectadas": iso_ham_force_time_presence.get("available_column_count", 0),
                },
            ]
        )
        st.caption(f"Filas del atleta en el dataframe: {len(athlete_hist)}")
        st.dataframe(detection_rows, use_container_width=True, hide_index=True)
        if not imtp_basic_presence.get("has_basic_data") and not imtp_force_time_presence.get("has_valid_force_time"):
            st.caption("No se detectaron datos de IMTP para este atleta.")
        elif imtp_basic_presence.get("has_basic_data") and not imtp_force_time_summary.get("has_valid_force_time"):
            st.caption(
                "IMTP detectado, pero faltan los campos force-time por puntos. "
                "Volve a cargar el resumen exportado de Involution para generar el bloque force-time."
            )

        st.markdown("**Filas con algun campo IMTP**")
        if imtp_any_rows.empty:
            st.caption("Ninguna.")
        else:
            st.dataframe(
                _prepare_force_time_detection_rows(imtp_any_rows),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("**Filas con puntos force-time IMTP**")
        if imtp_force_rows.empty:
            st.caption("Ninguna.")
        else:
            st.dataframe(
                _prepare_force_time_detection_rows(imtp_force_rows),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("**Detalle de la fila IMTP candidata**")
        if imtp_candidate_row is None:
            st.caption("No hay una fila IMTP candidata para revisar.")
        else:
            st.dataframe(
                _build_force_time_field_presence_table(
                    imtp_candidate_row,
                    fields=[
                        "IMTP_N",
                        "IMTP_avg_N",
                        "IMTP_relPF",
                        "IMTP_force_50_N",
                        "IMTP_force_100_N",
                        "IMTP_force_150_N",
                        "IMTP_force_200_N",
                        "IMTP_force_250_N",
                        "IMTP_rfd_50_N_s",
                        "IMTP_rfd_100_N_s",
                        "IMTP_rfd_150_N_s",
                        "IMTP_rfd_250_N_s",
                        "IMTP_time_pull_s",
                    ],
                ),
                use_container_width=True,
                hide_index=True,
            )

        imtp_columns = imtp_force_time_presence.get("available_columns") or []
        if imtp_columns:
            st.caption("Columnas IMTP detectadas en la fila force-time: " + ", ".join(str(column) for column in imtp_columns))
        elif imtp_basic_presence.get("available_columns"):
            st.caption(
                "Columnas IMTP detectadas en la fila basica: "
                + ", ".join(str(column) for column in imtp_basic_presence.get("available_columns") or [])
            )

        iso_detection_rows = iso_ham_history[iso_ham_history["non_null_field_count"] > 0].copy()
        if not iso_detection_rows.empty:
            st.markdown("**Filas con campos ISO Push Hip-Hamstring**")
            st.dataframe(
                _prepare_force_time_detection_rows(iso_detection_rows),
                use_container_width=True,
                hide_index=True,
            )
        iso_columns = iso_ham_force_time_presence.get("available_columns") or []
        if iso_columns:
            st.caption("Columnas ISO_HAM detectadas en la fila force-time: " + ", ".join(str(column) for column in iso_columns))
        elif iso_ham_basic_presence.get("available_columns"):
            st.caption(
                "Columnas ISO_HAM detectadas en la fila basica: "
                + ", ".join(str(column) for column in iso_ham_basic_presence.get("available_columns") or [])
            )

    st.markdown("### Perfil actual compuesto")
    if current_profile_row is None:
        st.info(
            "No hay metricas suficientes para construir el perfil actual compuesto de este atleta."
        )
    else:
        st.caption(
            "Este bloque no depende de la fecha seleccionada. "
            "Usa el ultimo dato valido disponible por variable para construir un perfil compuesto."
        )
        chart_left, chart_right = st.columns([1.05, 0.95])
        with chart_left:
            st.plotly_chart(chart_composite_profile_radar(current_profile_row, athlete, theme=theme), use_container_width=True)
        with chart_right:
            metric_table = build_composite_profile_metric_table(current_profile_row)
            st.markdown("### Lectura por variable actual")
            st.dataframe(metric_table, use_container_width=True, hide_index=True)
        with st.expander("Origen por variable", expanded=False):
            st.dataframe(current_profile_sources, use_container_width=True, hide_index=True)
        if isinstance(current_profile_payload, dict):
            _render_flag_chips(list(current_profile_payload.get("flag_rows", [])))
            _render_feedback(list(current_profile_payload.get("feedback_lines", [])))

    st.markdown("### Historial temporal")
    st.caption("Estos graficos usan siempre la fecha de evaluacion como eje temporal y no dependen de la fecha seleccionada.")
    history_top_left, history_top_right = st.columns(2)
    with history_top_left:
        _render_history_chart(athlete_hist, athlete, "CMJ", "CMJ_cm", theme=theme)
    with history_top_right:
        _render_history_chart(athlete_hist, athlete, "EUR (ratio)", "EUR", theme=theme)

    history_bottom_left, history_bottom_right = st.columns(2)
    with history_bottom_left:
        _render_history_chart(athlete_hist, athlete, "DJ RSI", "DJ_RSI", theme=theme)
    with history_bottom_right:
        _render_history_chart(athlete_hist, athlete, "DJ", "DJ_cm", theme=theme)

    with st.expander("Historial completo del atleta", expanded=False):
        history_cols = [column for column in athlete_hist.columns if not column.endswith("_reps")]
        st.dataframe(
            athlete_hist[history_cols].rename(columns={"EUR": "EUR (ratio)"}).sort_values("Date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
