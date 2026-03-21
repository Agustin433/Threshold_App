# charts/quadrant_chart.py

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np


def plot_quadrant_cmj_imtp(df: pd.DataFrame) -> go.Figure:
    """
    Cuadrante 1: Eje X = CMJ_cm | Eje Y = IMTP_N
    
    Interpretación de los 4 cuadrantes:
    ┌──────────────────┬──────────────────┐
    │ Q2: Alta F.Max   │ Q1: PERFIL ÉLITE │
    │ Baja Explosividad│ Alto CMJ + IMTP  │
    ├──────────────────┼──────────────────┤
    │ Q3: DEBILIDAD    │ Q4: Explosivo    │
    │ Bajo CMJ + IMTP  │ Alto CMJ sin base│
    └──────────────────┴──────────────────┘
    
    Líneas de corte = mediana del grupo (no media, más robusta a outliers).
    
    Decisión: atletas Q3 → priorizar fuerza máxima + RFD
              atletas Q2 → más trabajo pliométrico/potencia
              atletas Q4 → revisar si CMJ alto es real (técnica) o falso positivo
    """
    df_clean = df.dropna(subset=["CMJ_cm", "IMTP_N", "Athlete"])

    # Medianas grupales (líneas de corte)
    cmj_median  = df_clean["CMJ_cm"].median()
    imtp_median = df_clean["IMTP_N"].median()

    # Clasificar cuadrante
    def get_quadrant(row):
        if row["CMJ_cm"] >= cmj_median and row["IMTP_N"] >= imtp_median:
            return "Q1: Élite"
        elif row["CMJ_cm"] < cmj_median and row["IMTP_N"] >= imtp_median:
            return "Q2: Alta F. Máx"
        elif row["CMJ_cm"] >= cmj_median and row["IMTP_N"] < imtp_median:
            return "Q4: Explosivo"
        else:
            return "Q3: Deficiencia General"

    df_clean["Cuadrante"] = df_clean.apply(get_quadrant, axis=1)

    color_map = {
        "Q1: Élite":              "#00C853",
        "Q2: Alta F. Máx":        "#FFD600",
        "Q4: Explosivo":          "#FF9800",
        "Q3: Deficiencia General": "#FF1744",
    }

    fig = go.Figure()

    # ── Líneas de corte ──
    fig.add_vline(x=cmj_median,  line_dash="dash", line_color="rgba(255,255,255,0.3)",
                  annotation_text=f"Mediana CMJ: {cmj_median:.1f} cm",
                  annotation_font_color="rgba(255,255,255,0.5)")
    fig.add_hline(y=imtp_median, line_dash="dash", line_color="rgba(255,255,255,0.3)",
                  annotation_text=f"Mediana IMTP: {imtp_median:.0f} N",
                  annotation_font_color="rgba(255,255,255,0.5)")

    # ── Labels de cuadrante ──
    x_max = df_clean["CMJ_cm"].max()
    y_max = df_clean["IMTP_N"].max()
    x_min = df_clean["CMJ_cm"].min()
    y_min = df_clean["IMTP_N"].min()

    for quad, (tx, ty, color) in {
        "Q1: Élite":              (x_max*0.97, y_max*0.97, "#00C853"),
        "Q2: Alta F. Máx":        (x_min*1.03, y_max*0.97, "#FFD600"),
        "Q4: Explosivo":          (x_max*0.97, y_min*1.03, "#FF9800"),
        "Q3: Deficiencia General": (x_min*1.03, y_min*1.03, "#FF1744"),
    }.items():
        fig.add_annotation(
            x=tx, y=ty, text=quad,
            font=dict(color=color, size=10),
            showarrow=False, xanchor="right" if "Q1" in quad or "Q4" in quad else "left",
        )

    # ── Scatter por cuadrante ──
    for quad, color in color_map.items():
        d = df_clean[df_clean["Cuadrante"] == quad]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(
            x=d["CMJ_cm"], y=d["IMTP_N"],
            mode="markers+text",
            marker=dict(color=color, size=12, line=dict(color="white", width=1)),
            text=d["Athlete"].str.split().str[0],
            textposition="top center",
            textfont=dict(color="#E8EAED", size=9),
            name=quad,
            hovertemplate=(
                "<b>%{text}</b><br>"
                "CMJ: %{x:.1f} cm<br>"
                "IMTP: %{y:.0f} N<br>"
                f"<i>{quad}</i><extra></extra>"
            ),
        ))

    fig.update_layout(
        title="<b>Cuadrante CMJ × IMTP — Perfil Fuerza-Potencia</b>",
        xaxis_title="CMJ (cm) — Potencia / Explosividad",
        yaxis_title="IMTP (N) — Fuerza Máxima Isométrica",
        template="plotly_dark",
        paper_bgcolor="#0D0D0D",
        plot_bgcolor="#1A1A2E",
        height=520,
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def plot_quadrant_dri_sj(df: pd.DataFrame) -> go.Figure:
    """
    Cuadrante 2: Eje X = DRI | Eje Y = SJ_cm
    
    Interpretación:
    Q1 (alto DRI, alto SJ): Perfil completo — potencia + reactividad
    Q2 (bajo DRI, alto SJ):  Fuerte concéntrico, CEA rápido deficiente
    Q3 (bajo DRI, bajo SJ):  Débil general, prioridad fuerza base
    Q4 (alto DRI, bajo SJ):  Reactivo sin base de fuerza (lesión potencial)
    
    Decisión clínica Q4: reactivo sin fuerza = atleta frágil.
    Taleb: alta volatilidad sin robustez base = antifrágilidad falsa.
    Priorizar: fuerza concéntrica antes de más pliometría de alta intensidad.
    """
    df_clean = df.dropna(subset=["DRI", "SJ_cm", "Athlete"])

    dri_median = df_clean["DRI"].median()
    sj_median  = df_clean["SJ_cm"].median()

    def get_quadrant(row):
        if row["DRI"] >= dri_median and row["SJ_cm"] >= sj_median:
            return "Q1: Potencia+Reactividad"
        elif row["DRI"] < dri_median and row["SJ_cm"] >= sj_median:
            return "Q2: Fuerza sin Reactividad"
        elif row["DRI"] >= dri_median and row["SJ_cm"] < sj_median:
            return "Q4: Reactivo sin Base"
        else:
            return "Q3: Déficit General"

    df_clean["Cuadrante"] = df_clean.apply(get_quadrant, axis=1)

    color_map = {
        "Q1: Potencia+Reactividad": "#00C853",
        "Q2: Fuerza sin Reactividad": "#FFD600",
        "Q4: Reactivo sin Base":      "#FF9800",
        "Q3: Déficit General":        "#FF1744",
    }

    fig = go.Figure()

    fig.add_vline(x=dri_median, line_dash="dash", line_color="rgba(255,255,255,0.3)",
                  annotation_text=f"Mediana DRI: {dri_median:.2f}")
    fig.add_hline(y=sj_median,  line_dash="dash", line_color="rgba(255,255,255,0.3)",
                  annotation_text=f"Mediana SJ: {sj_median:.1f} cm")

    for quad, color in color_map.items():
        d = df_clean[df_clean["Cuadrante"] == quad]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(
            x=d["DRI"], y=d["SJ_cm"],
            mode="markers+text",
            marker=dict(color=color, size=12, line=dict(color="white", width=1)),
            text=d["Athlete"].str.split().str[0],
            textposition="top center",
            textfont=dict(color="#E8EAED", size=9),
            name=quad,
            hovertemplate=(
                "<b>%{text}</b><br>"
                "DRI: %{x:.2f}<br>"
                "SJ: %{y:.1f} cm<br>"
                f"<i>{quad}</i><extra></extra>"
            ),
        ))

    fig.update_layout(
        title="<b>Cuadrante DRI × SJ — Perfil Reactivo-Concéntrico</b>",
        xaxis_title="DRI — Índice Reactivo Dinámico (capacidad CEA rápido)",
        yaxis_title="SJ (cm) — Fuerza Concéntrica Pura",
        template="plotly_dark",
        paper_bgcolor="#0D0D0D",
        plot_bgcolor="#1A1A2E",
        height=520,
        legend=dict(orientation="h", y=-0.15),
    )
    return fig