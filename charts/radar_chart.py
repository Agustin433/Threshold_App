# charts/radar_chart.py

import plotly.graph_objects as go
import pandas as pd
import numpy as np


def plot_athlete_radar(
    athlete_data: dict,
    athlete_name: str,
    team_avg: dict = None
) -> go.Figure:
    """
    Radar/Spider chart del perfil atlético.
    
    Variables (Z-scores):
    - CMJ_Z        (altura CMJ vs grupo)
    - SJ_Z         (fuerza concéntrica pura)
    - DJ_Reactividad_Z (TC invertido: menor TC = mejor)
    - EUR_Z        (índice de elasticidad)
    - DRI_Z        (índice reactivo dinámico)
    - IMTP_Z       (fuerza isométrica máxima)
    
    Todos en Z-scores: el centro = promedio del grupo (Z=0)
    Cada unidad = 1 desviación estándar del grupo.
    """

    categories = [
        "CMJ\n(Altura)", 
        "SJ\n(F. Concéntrica)",
        "DJ Reactividad\n(CEA Rápido)",
        "EUR\n(Elasticidad)",
        "DRI\n(Índice Reactivo)",
        "IMTP\n(F. Máxima)",
    ]
    z_keys = ["CMJ_Z", "SJ_Z", "DJ_Reactividad_Z", "EUR_Z", "DRI_Z", "IMTP_Z"]

    # Valores del atleta
    values = [athlete_data.get(k, 0) for k in z_keys]
    values_closed = values + [values[0]]   # cerrar el polígono
    cats_closed = categories + [categories[0]]

    fig = go.Figure()

    # ── Zona de referencia (±1 SD del grupo) ──
    fig.add_trace(go.Scatterpolar(
        r=[1] * len(cats_closed),
        theta=cats_closed,
        fill="toself",
        fillcolor="rgba(255, 214, 0, 0.08)",
        line=dict(color="rgba(255,214,0,0.3)", dash="dot"),
        name="±1 SD Grupo",
        hoverinfo="skip",
    ))

    # ── Promedio del equipo (si se pasa) ──
    if team_avg:
        team_vals = [team_avg.get(k, 0) for k in z_keys]
        team_vals_closed = team_vals + [team_vals[0]]
        fig.add_trace(go.Scatterpolar(
            r=team_vals_closed,
            theta=cats_closed,
            fill="toself",
            fillcolor="rgba(120,144,156,0.15)",
            line=dict(color="#78909C", width=1, dash="dash"),
            name="Promedio Equipo",
        ))

    # ── Atleta seleccionado ──
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=cats_closed,
        fill="toself",
        fillcolor="rgba(0,200,83,0.25)",
        line=dict(color="#00C853", width=3),
        name=athlete_name,
        hovertemplate="<b>%{theta}</b><br>Z-score: %{r:.2f}<extra></extra>",
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[-3, 3],
                tickvals=[-2, -1, 0, 1, 2],
                ticktext=["−2σ", "−1σ", "Media", "+1σ", "+2σ"],
                gridcolor="rgba(255,255,255,0.1)",
                linecolor="rgba(255,255,255,0.2)",
                tickfont=dict(color="#78909C", size=9),
            ),
            angularaxis=dict(
                tickfont=dict(color="#E8EAED", size=11),
                gridcolor="rgba(255,255,255,0.1)",
                linecolor="rgba(255,255,255,0.2)",
            ),
            bgcolor="rgba(26,26,46,0.8)",
        ),
        paper_bgcolor="rgba(13,13,13,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            font=dict(color="#E8EAED"),
            bgcolor="rgba(26,26,46,0.8)",
            bordercolor="rgba(255,255,255,0.1)",
        ),
        title=dict(
            text=f"<b>Perfil Neuromuscular — {athlete_name}</b>",
            font=dict(color="#E8EAED", size=16),
            x=0.5,
        ),
        height=500,
    )

    return fig