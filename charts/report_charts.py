"""Graficos de carga y wellness: UNA funcion por grafico para dashboard y PDF.

Cada funcion devuelve una figura Plotly y recibe `mode`:

- "screen": la usa el dashboard (tamano adaptable, hover).
- "print": la usa el PDF (tamano fijo pensado para el ancho completo de la
  pagina, fuente >= 11 pt una vez impresa, leyenda abajo sin pisar los ejes,
  sin hover).

El PDF solo cae al grafico dibujado a mano (reportlab) si kaleido no puede
renderizar la figura.

Convenciones fisiologicas/metodologicas:

- ACWR: una sola metrica en toda la app, EWMA (Williams et al. 2017,
  Br J Sports Med 51:209-210). La linea de carga cronica es la EWMA cronica
  expresada como equivalente semanal (x7) y se CORTA en semanas sin datos:
  interpolar inventaria una carga cronica que no se observo.
- Wellness: el score se lee contra la propia variabilidad del atleta
  (banda media +/- 1 DE de los 28 dias previos; sin banda con < 10 registros),
  no contra un umbral de grupo. Sueno, estres y dolor tienen escalas distintas
  (horas vs 0-10) y nunca comparten eje con el score.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from modules.wellness_scales import PAIN_LABEL, SLEEP_LABEL, STRESS_LABEL, WELLNESS_RESPONSE_MAX

ChartMode = Literal["screen", "print"]

# --- Modo impresion -------------------------------------------------------
# El PNG se coloca a ancho completo de pagina: 168 mm (174 mm de area util
# menos el relleno del recuadro). Con un lienzo de 1000 px, 1 px impreso =
# 168 mm / 1000 = 0.476 pt; para >= 11 pt la fuente tiene que ser >= 24 px.
PRINT_WIDTH_MM = 168.0
PRINT_CANVAS_WIDTH_PX = 1000
PRINT_SCALE = 2
PRINT_MIN_FONT_PT = 11.0
PT_PER_PX = PRINT_WIDTH_MM * 72.0 / 25.4 / PRINT_CANVAS_WIDTH_PX
PRINT_FONT_PX = int(math.ceil(PRINT_MIN_FONT_PT / PT_PER_PX))
PRINT_TITLE_FONT_PX = PRINT_FONT_PX + 2
PRINT_LEGEND_COLUMNS = 2
PRINT_LEGEND_MAX_CHARS = 32

WELLNESS_SCORE_MAX = 30.0
WELLNESS_BAND_WINDOW_DAYS = 28
WELLNESS_BAND_MIN_RECORDS = 10
ACWR_EWMA_LABEL = "ACWR EWMA"
CHRONIC_LABEL = "Crónica EWMA (UA/semana)"
ESTIMATED_LABEL = "Estimada (sin sRPE)"
REPORTED_LABEL = "sRPE reportado"
NOT_CALCULABLE_LABEL = "ACWR no calculable"
BAND_LABEL = f"Banda ± 1 DE ({WELLNESS_BAND_WINDOW_DAYS} días previos)"
BAND_MEAN_LABEL = f"Media ({WELLNESS_BAND_WINDOW_DAYS} días previos)"

# Estados del modelo (modules.load_monitoring) en los que la cronica no existe.
CHRONIC_NOT_ESTABLISHED = {"historial_insuficiente", "sin_carga_cronica"}

ACWR_ZONES = (
    (0.0, 0.8, "rgba(74,159,212,0.10)", "Subcarga"),
    (0.8, 1.3, "rgba(111,143,120,0.12)", "Óptimo"),
    (1.3, 1.5, "rgba(196,164,100,0.14)", "Precaución"),
    (1.5, 2.6, "rgba(181,107,115,0.12)", "Alto riesgo"),
)


def print_height_px(height_mm: float) -> int:
    """Alto del lienzo para que, a PRINT_WIDTH_MM de ancho, la imagen mida `height_mm`."""
    return int(round(PRINT_CANVAS_WIDTH_PX * float(height_mm) / PRINT_WIDTH_MM))


def _theme_parts(theme: dict) -> tuple[dict, dict, str, str, dict]:
    return theme["colors"], theme["layout"], theme["grid"], theme["grid_soft"], theme["legend"]


def apply_chart_mode(
    fig: go.Figure,
    mode: ChartMode,
    *,
    theme: dict,
    title: str | None,
    screen_height: int = 420,
    print_height_mm: float = 70.0,
) -> go.Figure:
    """Aplica el modo pantalla o impresion a una figura ya armada."""
    colors, layout, _, _, legend = _theme_parts(theme)
    if mode == "screen":
        fig.update_layout(
            **layout,
            height=screen_height,
            title=dict(text=f"<b>{title}</b>", font=dict(color=colors["navy"], size=13)) if title else None,
            legend={**legend, "traceorder": "normal"},
        )
        return fig

    width = PRINT_CANVAS_WIDTH_PX
    height = print_height_px(print_height_mm)
    names = [
        str(trace.name)
        for trace in fig.data
        if trace.name and trace.showlegend is not False
    ]
    # Leyenda en columnas fijas (2, o 1 si algun rotulo es largo): alto
    # predecible y sin pisar los ejes ni otros rotulos.
    columns = PRINT_LEGEND_COLUMNS if all(len(name) <= PRINT_LEGEND_MAX_CHARS for name in names) else 1
    rows = int(math.ceil(len(names) / columns)) if names else 0
    # Abajo: etiquetas del eje X (1 renglon) + leyenda en su propio margen.
    bottom = 18 + int(PRINT_FONT_PX * 1.6) + rows * int(PRINT_FONT_PX * 1.6)
    print_layout = {key: value for key, value in layout.items() if key not in {"margin", "font", "height", "width"}}
    fig.update_layout(
        **print_layout,
        width=width,
        height=height,
        font=dict(family="Helvetica", size=PRINT_FONT_PX, color=colors.get("black", "#221F20")),
        title=(
            dict(text=f"<b>{title}</b>", font=dict(size=PRINT_TITLE_FONT_PX, color=colors["navy"]), x=0.01, xanchor="left")
            if title
            else None
        ),
        margin=dict(l=90, r=30, t=(PRINT_TITLE_FONT_PX * 2 + 10) if title else 24, b=bottom),
        hovermode=False,
        showlegend=bool(names),
        legend=dict(
            orientation="h",
            yref="container",
            y=0.0,
            yanchor="bottom",
            x=0.0,
            xanchor="left",
            font=dict(size=PRINT_FONT_PX, color=colors.get("gray", "#5A595B")),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            itemsizing="constant",
            traceorder="normal",
            entrywidthmode="fraction",
            entrywidth=1.0 / columns - 0.01,
        ),
    )
    fig.update_traces(hoverinfo="skip", hovertemplate=None)
    fig.update_xaxes(tickfont=dict(size=PRINT_FONT_PX), title_font=dict(size=PRINT_FONT_PX), ticklabelstandoff=8)
    fig.update_yaxes(tickfont=dict(size=PRINT_FONT_PX), title_font=dict(size=PRINT_FONT_PX), ticklabelstandoff=8)
    fig.update_annotations(font_size=PRINT_FONT_PX)
    return fig


def _empty_figure(message: str, *, theme: dict, mode: ChartMode, title: str, print_height_mm: float) -> go.Figure:
    colors = theme["colors"]
    fig = go.Figure()
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
        font=dict(color=colors["muted"], size=13),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_chart_mode(fig, mode, theme=theme, title=title, screen_height=320, print_height_mm=print_height_mm)


# --- Carga ------------------------------------------------------------------


def _week_start(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce").dt.normalize()
    return dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")


def weekly_load_frame(
    weekly_load_df: pd.DataFrame | None,
    acwr_df: pd.DataFrame | None = None,
    *,
    weeks: int | None = 16,
) -> pd.DataFrame:
    """Una fila por semana calendario (sin huecos) con todo lo que dibuja `load_chart`.

    Las semanas sin ningun dato quedan con NaN (no con 0 ni interpoladas).
    """
    columns = [
        "week_start", "reported", "estimated", "sessions_done", "sessions_with_srpe",
        "partial", "has_data", "chronic_weekly", "acwr_ewma", "acwr_not_calculable",
    ]
    if weekly_load_df is None or weekly_load_df.empty or "week_start" not in weekly_load_df.columns:
        return pd.DataFrame(columns=columns)
    frame = weekly_load_df.copy()
    frame["week_start"] = _week_start(frame["week_start"])
    frame = frame.dropna(subset=["week_start"]).sort_values("week_start")
    frame = frame.groupby("week_start", as_index=False).last()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    full_range = pd.date_range(frame["week_start"].min(), frame["week_start"].max(), freq="W-MON")
    frame = frame.set_index("week_start").reindex(full_range)
    frame.index.name = "week_start"
    reported = pd.to_numeric(frame.get("weekly_sRPE"), errors="coerce")
    model = pd.to_numeric(frame.get("weekly_sRPE_model"), errors="coerce") if "weekly_sRPE_model" in frame else reported
    done = pd.to_numeric(frame.get("sessions_done"), errors="coerce") if "sessions_done" in frame else pd.Series(np.nan, index=frame.index)
    missing = pd.to_numeric(frame.get("sessions_missing"), errors="coerce") if "sessions_missing" in frame else pd.Series(0.0, index=frame.index)
    has_data = reported.fillna(0).gt(0) | done.fillna(0).gt(0)
    result = pd.DataFrame(index=frame.index)
    result["reported"] = reported.where(has_data)
    result["estimated"] = (model.fillna(reported) - reported).clip(lower=0).where(has_data)
    result["sessions_done"] = done.where(has_data)
    result["sessions_with_srpe"] = (done - missing.fillna(0)).clip(lower=0).where(has_data)
    result["partial"] = (missing.fillna(0) > 0) & has_data
    result["has_data"] = has_data

    result["chronic_weekly"] = np.nan
    result["acwr_ewma"] = np.nan
    result["acwr_not_calculable"] = False
    if acwr_df is not None and not acwr_df.empty and "Date" in acwr_df.columns:
        daily = acwr_df.copy()
        daily["Date"] = pd.to_datetime(daily["Date"], errors="coerce").dt.normalize()
        daily = daily.dropna(subset=["Date"]).sort_values("Date")
        daily["week_start"] = _week_start(daily["Date"])
        last = daily.groupby("week_start").last()
        if "EWMA_Cronica" in last.columns:
            chronic = pd.to_numeric(last["EWMA_Cronica"], errors="coerce") * 7.0
            if "ACWR_Estado" in last.columns:
                # Con historial insuficiente la EWMA cronica todavia arrastra su
                # valor inicial: no describe una carga cronica establecida.
                status = last["ACWR_Estado"].astype(str).str.strip()
                chronic = chronic.where(~status.isin(CHRONIC_NOT_ESTABLISHED))
            result["chronic_weekly"] = chronic.reindex(result.index)
        if "ACWR_EWMA" in last.columns:
            acwr = pd.to_numeric(last["ACWR_EWMA"], errors="coerce")
            if "ACWR_Estado" in last.columns:
                status = last["ACWR_Estado"].astype(str).str.strip()
                acwr = acwr.where(status.eq("ok"))
                not_calc = status.ne("ok").reindex(result.index).fillna(False).astype(bool)
            else:
                not_calc = acwr.isna().reindex(result.index).fillna(False).astype(bool)
            result["acwr_ewma"] = acwr.reindex(result.index)
            result["acwr_not_calculable"] = not_calc & has_data
    # Sin datos esa semana: la cronica y el ACWR se cortan (no se interpolan).
    result.loc[~has_data, ["chronic_weekly", "acwr_ewma"]] = np.nan
    result = result.reset_index()
    if weeks:
        result = result.tail(int(weeks)).reset_index(drop=True)
    return result[columns]


def _daily_monday_ticks(fig: go.Figure, dates: pd.Series) -> None:
    """Graficos diarios: marcas cada lunes (mismo criterio que los semanales)."""
    values = pd.to_datetime(dates, errors="coerce").dropna()
    if values.empty:
        return
    first = values.min().normalize()
    monday = first - pd.Timedelta(days=int(first.dayofweek))
    span_weeks = max(1, int((values.max() - monday).days // 7) + 1)
    step = max(1, int(math.ceil(span_weeks / 9)))
    fig.update_xaxes(tick0=monday, dtick=7 * step * 86_400_000, tickformat="%d/%m")


def _weekly_ticks(fig: go.Figure, weeks: pd.Series, *, max_labels: int = 9) -> None:
    """Marcas del eje X en el lunes de cada semana (no en fechas automaticas)."""
    values = list(pd.to_datetime(weeks).dropna())
    if not values:
        return
    step = max(1, int(math.ceil(len(values) / max_labels)))
    shown = values[::step]
    fig.update_xaxes(tickvals=shown, ticktext=[value.strftime("%d/%m") for value in shown])


def load_chart(
    weekly_load_df: pd.DataFrame | None,
    acwr_df: pd.DataFrame | None,
    athlete: str,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    show_acwr: bool = True,
    weeks: int | None = 16,
    print_height_mm: float | None = None,
) -> go.Figure:
    """Carga semanal (+ carga cronica) y, si `show_acwr`, ACWR EWMA semanal.

    - Barras: sRPE reportado; apiladas y rayadas, la carga estimada de
      sesiones sin sRPE (el modelo las imputa); rotulo n/N en semanas parciales.
    - Linea: carga cronica EWMA (equivalente semanal), cortada en semanas sin datos.
    - Panel ACWR (solo profesional/dashboard): ACWR EWMA con zonas y marca
      "no calculable" cuando el modelo no lo emite.
    """
    colors = theme["colors"]
    title = f"Carga semanal{' y ACWR EWMA' if show_acwr else ''} - {athlete}"
    height_mm = print_height_mm or (100.0 if show_acwr else 70.0)
    frame = weekly_load_frame(weekly_load_df, acwr_df, weeks=weeks)
    if frame.empty or not frame["has_data"].any():
        return _empty_figure("No hay datos semanales de carga.", theme=theme, mode=mode, title=title, print_height_mm=height_mm)

    if show_acwr:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.14, row_heights=[0.6, 0.4],
            subplot_titles=["Carga semanal (UA)", ACWR_EWMA_LABEL],
        )
        load_row = dict(row=1, col=1)
    else:
        fig = go.Figure()
        load_row = {}

    x = frame["week_start"]
    partial_text = [
        f"{int(w)}/{int(d)}" if bool(p) and pd.notna(d) and pd.notna(w) else ""
        for p, d, w in zip(frame["partial"], frame["sessions_done"], frame["sessions_with_srpe"])
    ]
    fig.add_trace(
        go.Bar(
            x=x, y=frame["reported"], name=REPORTED_LABEL, marker_color=colors["steel"],
            hovertemplate="%{x|Sem %d/%m}<br>sRPE reportado: %{y:.0f} UA<extra></extra>",
        ),
        **load_row,
    )
    if frame["estimated"].fillna(0).gt(0).any():
        fig.add_trace(
            go.Bar(
                x=x, y=frame["estimated"], name=ESTIMATED_LABEL,
                marker=dict(color="rgba(0,0,0,0)", line=dict(color=colors.get("orange", colors["yellow"]), width=1.5),
                            pattern=dict(shape="/", fgcolor=colors.get("orange", colors["yellow"]))),
                text=partial_text, textposition="outside", cliponaxis=False,
                textfont=dict(color=colors.get("orange", colors["yellow"])),
                hovertemplate="%{x|Sem %d/%m}<br>Estimada: %{y:.0f} UA<extra></extra>",
            ),
            **load_row,
        )
    elif any(partial_text):
        fig.add_trace(
            go.Scatter(
                x=x, y=frame["reported"], mode="text", text=partial_text, textposition="top center",
                showlegend=False, textfont=dict(color=colors.get("orange", colors["yellow"])),
            ),
            **load_row,
        )
    fig.add_trace(
        go.Scatter(
            x=x, y=frame["chronic_weekly"], name=CHRONIC_LABEL, mode="lines+markers",
            connectgaps=False, line=dict(color=colors["navy"], width=2.5), marker=dict(size=6),
            hovertemplate="%{x|Sem %d/%m}<br>Crónica: %{y:.0f} UA/sem<extra></extra>",
        ),
        **load_row,
    )
    fig.update_layout(barmode="stack")

    if show_acwr:
        for y0, y1, fill, label in ACWR_ZONES:
            fig.add_hrect(
                y0=y0, y1=y1, fillcolor=fill, layer="below", line_width=0,
                row=2, col=1, exclude_empty_subplots=False,
            )
        fig.add_trace(
            go.Scatter(
                x=x, y=frame["acwr_ewma"], name=ACWR_EWMA_LABEL, mode="lines+markers", connectgaps=False,
                line=dict(color=colors["red"], width=2.5), marker=dict(size=7),
                hovertemplate="%{x|Sem %d/%m}<br>ACWR EWMA: %{y:.2f}<extra></extra>",
            ),
            row=2, col=1,
        )
        not_calc = frame[frame["acwr_not_calculable"]]
        if not not_calc.empty:
            fig.add_trace(
                go.Scatter(
                    x=not_calc["week_start"], y=[0.15] * len(not_calc), name=NOT_CALCULABLE_LABEL,
                    mode="markers", marker=dict(size=11, color=colors["muted"], symbol="x"),
                    hovertemplate="%{x|Sem %d/%m}<br>ACWR no calculable<extra></extra>",
                ),
                row=2, col=1,
            )
        fig.update_yaxes(range=[0, 2.6], title_text="", row=2, col=1)
        fig.update_yaxes(title_text="", rangemode="tozero", row=1, col=1)
    else:
        fig.update_yaxes(title_text="UA", rangemode="tozero")
    fig.update_xaxes(showgrid=False)
    _weekly_ticks(fig, x)
    fig.update_yaxes(gridcolor=theme["grid_soft"], zeroline=False)
    return apply_chart_mode(
        fig, mode, theme=theme, title=title if mode == "screen" else None,
        screen_height=620 if show_acwr else 420, print_height_mm=height_mm,
    )


def sessions_per_week_chart(
    training_dates: pd.DatetimeIndex | list | None,
    srpe_dates: pd.Series | list | None,
    athlete: str,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    weeks: int = 12,
    reference_date: object | None = None,
    print_height_mm: float = 62.0,
) -> go.Figure:
    """Sesiones realizadas por semana (adherencia, no UA), para el reporte cliente.

    Sesion = dia con actividad en Raw Workouts (Fecha_sesion) o con sRPE.
    Las semanas sin sesiones son 0 reales (no entrenó), no datos faltantes.
    """
    title = f"Sesiones por semana - {athlete}"
    combined = list(training_dates if training_dates is not None else []) + list(srpe_dates if srpe_dates is not None else [])
    days = pd.to_datetime(pd.Series(combined, dtype="object"), errors="coerce").dropna()
    days = pd.Series(days.dt.normalize().unique())
    if days.empty:
        return _empty_figure("Todavía no hay sesiones registradas.", theme=theme, mode=mode, title=title, print_height_mm=print_height_mm)
    week = _week_start(days)
    counts = week.value_counts().sort_index()
    end = _week_start(pd.Series([pd.Timestamp(reference_date) if reference_date is not None else days.max()])).iloc[0]
    # Desde la primera semana con sesiones: antes de eso el atleta no estaba
    # en el registro (un 0 ahi no seria "no entreno").
    start = max(end - pd.Timedelta(weeks=weeks - 1), counts.index.min())
    full_range = pd.date_range(start, end, freq="W-MON")
    counts = counts.reindex(full_range, fill_value=0)
    colors = theme["colors"]
    fig = go.Figure(
        go.Bar(
            x=counts.index, y=counts.values, name="Sesiones realizadas", marker_color=colors["steel"],
            text=[str(int(value)) for value in counts.values], textposition="outside", cliponaxis=False,
            hovertemplate="%{x|Sem %d/%m}<br>Sesiones: %{y}<extra></extra>",
        )
    )
    fig.update_yaxes(title_text="sesiones", rangemode="tozero", dtick=1, gridcolor=theme["grid_soft"], zeroline=False)
    fig.update_xaxes(showgrid=False)
    _weekly_ticks(fig, pd.Series(counts.index))
    return apply_chart_mode(
        fig, mode, theme=theme, title=title if mode == "screen" else None,
        screen_height=360, print_height_mm=print_height_mm,
    )


# --- Wellness ----------------------------------------------------------------


def wellness_band(
    dates: pd.Series,
    scores: pd.Series,
    *,
    window_days: int = WELLNESS_BAND_WINDOW_DAYS,
    min_records: int = WELLNESS_BAND_MIN_RECORDS,
) -> pd.DataFrame:
    """Media y DE de los `window_days` previos (sin el dia actual) por fecha.

    Sin banda (NaN) si en esa ventana hay menos de `min_records` registros: con
    pocos datos la DE individual no es estable.
    """
    frame = pd.DataFrame({"Date": pd.to_datetime(dates, errors="coerce").dt.normalize(), "score": pd.to_numeric(scores, errors="coerce")})
    frame = frame.dropna().groupby("Date", as_index=False)["score"].mean().sort_values("Date")
    means, sds = [], []
    for day in frame["Date"]:
        prior = frame[(frame["Date"] < day) & (frame["Date"] >= day - pd.Timedelta(days=window_days))]["score"]
        if len(prior) >= min_records:
            means.append(float(prior.mean()))
            sds.append(float(prior.std(ddof=1)))
        else:
            means.append(np.nan)
            sds.append(np.nan)
    frame["band_mean"] = means
    frame["band_sd"] = sds
    frame["band_low"] = (frame["band_mean"] - frame["band_sd"]).clip(lower=0)
    frame["band_high"] = (frame["band_mean"] + frame["band_sd"]).clip(upper=WELLNESS_SCORE_MAX)
    return frame


def wellness_score_chart(
    wellness_df: pd.DataFrame | None,
    athlete: str,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    days: int | None = 56,
    score_col: str = "Wellness_Score",
    print_height_mm: float = 62.0,
) -> go.Figure:
    """Score total de wellness (0-30) con banda individual media +/- 1 DE."""
    title = f"Wellness score (0-{WELLNESS_SCORE_MAX:.0f}) - {athlete}"
    if wellness_df is None or wellness_df.empty or score_col not in wellness_df.columns or "Date" not in wellness_df.columns:
        return _empty_figure("Sin datos de wellness.", theme=theme, mode=mode, title=title, print_height_mm=print_height_mm)
    frame = wellness_band(wellness_df["Date"], wellness_df[score_col])
    if frame.empty:
        return _empty_figure("Sin datos de wellness.", theme=theme, mode=mode, title=title, print_height_mm=print_height_mm)
    if days:
        frame = frame[frame["Date"] >= frame["Date"].max() - pd.Timedelta(days=int(days) - 1)]
    colors = theme["colors"]
    fig = go.Figure()
    if frame["band_mean"].notna().any():
        fig.add_trace(go.Scatter(
            x=frame["Date"], y=frame["band_high"], mode="lines", line=dict(width=0), connectgaps=False,
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=frame["Date"], y=frame["band_low"], mode="lines", line=dict(width=0), connectgaps=False,
            fill="tonexty", fillcolor="rgba(13,60,94,0.12)", name=BAND_LABEL,
            hovertemplate="%{x|%d/%m}<br>Banda: %{y:.1f} - media ± 1 DE<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=frame["Date"], y=frame["band_mean"], mode="lines", connectgaps=False,
            line=dict(color=colors["navy"], width=1.2, dash="dot"), name=BAND_MEAN_LABEL,
            hovertemplate="%{x|%d/%m}<br>Media previa: %{y:.1f}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=frame["Date"], y=frame["score"], mode="lines+markers", name="Wellness score",
        line=dict(color=colors["green"], width=2.5), marker=dict(size=7),
        hovertemplate="%{x|%d/%m}<br>Score: %{y:.1f}/30<extra></extra>",
    ))
    fig.update_yaxes(range=[0, WELLNESS_SCORE_MAX], title_text=f"score /{WELLNESS_SCORE_MAX:.0f}", gridcolor=theme["grid_soft"], zeroline=False)
    fig.update_xaxes(showgrid=False)
    _daily_monday_ticks(fig, frame["Date"])
    return apply_chart_mode(
        fig, mode, theme=theme, title=title if mode == "screen" else None,
        screen_height=380, print_height_mm=print_height_mm,
    )


def wellness_components_chart(
    frame: pd.DataFrame | None,
    athlete: str,
    *,
    theme: dict,
    mode: ChartMode = "screen",
    date_col: str = "Date",
    sleep_col: str = "Sueno_hs",
    stress_col: str = "Estres",
    pain_col: str = "Dolor",
    days: int | None = 56,
    title_prefix: str = "Sueño, estrés y dolor",
    print_height_mm: float = 92.0,
) -> go.Figure:
    """Small multiples: sueno (h), estres (0-10) y dolor (0-10), cada uno con su eje."""
    title = f"{title_prefix} - {athlete}"
    panels = [
        (sleep_col, SLEEP_LABEL, "blue", None),
        (stress_col, STRESS_LABEL, "yellow", (0, WELLNESS_RESPONSE_MAX)),
        (pain_col, PAIN_LABEL, "red", (0, WELLNESS_RESPONSE_MAX)),
    ]
    if frame is None or frame.empty or date_col not in frame.columns:
        return _empty_figure("Sin datos de wellness.", theme=theme, mode=mode, title=title, print_height_mm=print_height_mm)
    data = frame.copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data = data.dropna(subset=[date_col]).sort_values(date_col)
    if days:
        data = data[data[date_col] >= data[date_col].max() - pd.Timedelta(days=int(days) - 1)]
    available = [panel for panel in panels if panel[0] in data.columns and pd.to_numeric(data[panel[0]], errors="coerce").notna().any()]
    if not available:
        return _empty_figure("Sin datos de sueño, estrés o dolor.", theme=theme, mode=mode, title=title, print_height_mm=print_height_mm)
    colors = theme["colors"]
    fig = make_subplots(
        rows=len(available), cols=1, shared_xaxes=True, vertical_spacing=0.12,
        subplot_titles=[label for _, label, _, _ in available],
    )
    for index, (column, label, color_key, y_range) in enumerate(available, start=1):
        values = pd.to_numeric(data[column], errors="coerce")
        fig.add_trace(
            go.Scatter(
                x=data[date_col], y=values, mode="lines+markers", name=label, showlegend=False,
                connectgaps=False, line=dict(color=colors.get(color_key, colors["navy"]), width=2.2), marker=dict(size=6),
                hovertemplate=f"%{{x|%d/%m}}<br>{label}: %{{y:.1f}}<extra></extra>",
            ),
            row=index, col=1,
        )
        if y_range is None:
            top = max(10.0, float(np.nanmax(values.to_numpy())) + 1 if values.notna().any() else 10.0)
            y_range = (0, top)
        fig.update_yaxes(range=list(y_range), gridcolor=theme["grid_soft"], zeroline=False, row=index, col=1)
    fig.update_xaxes(showgrid=False)
    _daily_monday_ticks(fig, data[date_col])
    return apply_chart_mode(
        fig, mode, theme=theme, title=title if mode == "screen" else None,
        screen_height=520, print_height_mm=print_height_mm,
    )
