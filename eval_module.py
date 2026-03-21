"""
THRESHOLD S&C — Módulo de Evaluaciones
=======================================
Replica exacta del dashboard de tu Excel (Evaluaciones_Handball_SanMartin).

Gráficos implementados:
1. KPI Cards individuales (CMJ, SJ, DJ, IMTP, RSI, TC, EUR, mRSI)
   con % vs última, Z-Score, Mejor Histórico, Semáforo
2. Cuadrante grupal Z-Score IMTP (Y) vs Z-Score RSI (X)
3. Barras comparativas SJ/CMJ/DJ por jugador
4. Línea DJ vs RSI grupal
5. Tendencia sprints 20m y 10m con promedio
6. Radar individual vs mejor del equipo
7. Historial CMJ/SJ/DJ individual
8. Historial DJ/RSI individual
9. Historial EUR individual
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from io import BytesIO
import datetime
import logging

# Configurar logging
logger = logging.getLogger(__name__)

# ── Constantes de colores (heredan del sistema Threshold) ────────────
_C = {
    "navy":   "#1B3D72",
    "steel":  "#2A5F8E",
    "white":  "#F0F4F8",
    "gray":   "#5A6A7A",
    "bg":     "#000000",
    "card":   "#0C1524",
    "surface":"#080E18",
    "green":  "#4FC97E",
    "yellow": "#E8C84A",
    "red":    "#D94F4F",
    "blue":   "#4A9FD4",
    "muted":  "#3A4A5A",
}

_DARK = dict(
    template="plotly_dark",
    paper_bgcolor="#000000",
    plot_bgcolor="#0C1524",
    font=dict(family="DM Mono, monospace", color="#8899A8", size=11),
)

def _empty_figure(msg: str = "Sin datos") -> go.Figure:
    """Helper para crear figuras vacías con mensaje."""
    fig = go.Figure()
    fig.add_annotation(
        text=msg,
        showarrow=False,
        font=dict(size=14, color="gray")
    )
    fig.update_layout(**_DARK, height=300)
    return fig

# Columnas del CSV de evaluaciones
EVAL_COLS = [
    "JUGADOR", "FECHA",
    "CMJ_PF_N", "CMJ_RSI", "CMJ_cm",
    "SJ_PF_N", "SJ_asim_pct", "SJ_cm",
    "DJ_tc_ms", "DJ_cm", "DJ_RSI",
    "EUR",
    "IMTP_N", "IMTP_RFD100", "IMTP_RFD250",
    "Sprint_10m", "Sprint_20m",
]

# Métricas y sus propiedades para semáforo
# (nombre_display, columna, unidad, lower_is_better, umbral_pct_alert)
KPI_CONFIG = [
    ("CMJ",   "CMJ_cm",   "cm",  False, 5.0),
    ("SJ",    "SJ_cm",    "cm",  False, 5.0),
    ("DJ",    "DJ_cm",    "cm",  False, 5.0),
    ("IMTP",  "IMTP_N",   "N",   False, 5.0),
    ("RSI",   "DJ_RSI",   "",    False, 5.0),
    ("TC",    "DJ_tc_ms", "ms",  True,  5.0),   # menor es mejor
    ("EUR",   "EUR",      "",    False, 5.0),
    ("CMJ RSI","CMJ_RSI", "",    False, 5.0),
]

# Z-score pairs  (columna → nombre_z)
Z_COLS = {
    "CMJ_cm":   "Z_CMJ",
    "SJ_cm":    "Z_SJ",
    "DJ_RSI":   "Z_DJ_RSI",
    "DJ_tc_ms": "Z_DJ_TC",   # invertido
    "EUR":      "Z_EUR",
    "IMTP_N":   "Z_IMTP",
}


# ════════════════════════════════════════════════════════════════════
# DATA FUNCTIONS
# ════════════════════════════════════════════════════════════════════

def load_eval_csv(file) -> pd.DataFrame:
    """
    Carga el CSV de evaluaciones en formato estándar Threshold.
    Acepta tanto el formato nuevo (CSV) como el Excel DATOS.
    """
    try:
        name = file.name.lower()
        if name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = _parse_excel_datos(file)
    except Exception as e:
        logger.error(f"Error al leer archivo: {e}")
        raise ValueError(f"No se pudo procesar el archivo: {e}")

    df.columns = [c.strip() for c in df.columns]

    # Normalizar nombre de columnas (acepta variantes)
    col_map = {
        "Jugador": "JUGADOR", "jugador": "JUGADOR", "Athlete": "JUGADOR",
        "Fecha": "FECHA", "fecha": "FECHA", "Date": "FECHA",
    }
    df = df.rename(columns=col_map)

    try:
        df["FECHA"] = pd.to_datetime(df["FECHA"], dayfirst=True, errors="coerce")
        invalid_dates = df["FECHA"].isna().sum()
        if invalid_dates > 0:
            logger.warning(f"⚠️ {invalid_dates} fechas no pudieron ser parseadas")
    except Exception as e:
        logger.error(f"Error al parsear fechas: {e}")

    df["JUGADOR"] = df["JUGADOR"].astype(str).str.strip()

    numeric = [c for c in EVAL_COLS if c not in ("JUGADOR", "FECHA")]
    for c in numeric:
        if c in df.columns:
            before_nan = df[c].isna().sum()
            df[c] = pd.to_numeric(df[c], errors="coerce")
            after_nan = df[c].isna().sum()
            if after_nan > before_nan:
                loss_count = after_nan - before_nan
                logger.warning(f"⚠️ Columna '{c}': {loss_count} valores no convertibles a número")

    df = df.sort_values(["JUGADOR", "FECHA"]).reset_index(drop=True)
    return df


def _parse_excel_datos(file) -> pd.DataFrame:
    """Parsea el formato Excel del sheet DATOS."""
    import zipfile, xml.etree.ElementTree as ET

    file_bytes = file.read()
    with zipfile.ZipFile(BytesIO(file_bytes)) as z:
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with z.open("xl/sharedStrings.xml") as f:
            strings = ["".join(t.text or "" for t in si.findall(f".//{{{ns}}}t"))
                       for si in ET.parse(f).findall(f".//{{{ns}}}si")]
        with z.open("xl/worksheets/sheet1.xml") as f:
            rows_raw = []
            for row in ET.parse(f).findall(f".//{{{ns}}}row"):
                cells = {}
                for c in row.findall(f"{{{ns}}}c"):
                    col = "".join(filter(str.isalpha, c.get("r", "")))
                    t = c.get("t", "")
                    v_el = c.find(f"{{{ns}}}v")
                    if v_el is None: val = ""
                    elif t == "s": val = strings[int(v_el.text)] if int(v_el.text) < len(strings) else ""
                    else: val = v_el.text or ""
                    cells[col] = val
                if cells: rows_raw.append(cells)

    records = []
    for r in rows_raw[1:]:
        if not r.get("A", "").strip(): continue
        try:
            fecha = datetime.date(1899, 12, 30) + datetime.timedelta(days=float(r["B"]))
        except ValueError:
            logger.warning(f"No se pudo parsear fecha para {r.get('A', 'Unknown')}")
            continue
        def fv(k):
            try:
                return float(r.get(k, "") or 0)
            except ValueError:
                logger.debug(f"Valor inválido para {k}: {r.get(k, '')}")
                return None
        records.append({
            "JUGADOR": r["A"], "FECHA": pd.Timestamp(fecha),
            "CMJ_PF_N": fv("C"), "CMJ_RSI": fv("D"), "CMJ_cm": fv("E"),
            "SJ_PF_N": fv("F"), "SJ_asim_pct": fv("G"), "SJ_cm": fv("H"),
            "DJ_tc_ms": fv("I"), "DJ_cm": fv("J"), "DJ_RSI": fv("K"),
            "EUR": fv("L"), "IMTP_N": fv("M"), "IMTP_RFD100": fv("N"),
            "IMTP_RFD250": fv("O"), "Sprint_10m": fv("P"), "Sprint_20m": fv("Q"),
        })
    return pd.DataFrame(records)


@st.cache_data
def compute_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula Z-scores grupales para cada evaluación.
    Usa la última evaluación de cada jugador para el grupo.
    DJ_tc_ms: invertido (menor = mejor → Z positivo = mejor).
    CACHED: Evita recalcular en cada render.
    """
    # Usar TODOS los datos para la media/SD grupal (más robusto)
    for col, z_col in Z_COLS.items():
        if col not in df.columns:
            df[z_col] = np.nan
            continue
        vals = df[col].dropna()
        if len(vals) < 2 or vals.std() == 0:
            df[z_col] = 0.0
            continue
        mu, sigma = vals.mean(), vals.std()
        z = (df[col] - mu) / sigma
        df[z_col] = (-z if col == "DJ_tc_ms" else z).round(3)
    return df


def get_latest_per_player(df: pd.DataFrame) -> pd.DataFrame:
    """Retorna el registro más reciente de cada jugador."""
    return df.sort_values("FECHA").groupby("JUGADOR").last().reset_index()


def get_player_history(df: pd.DataFrame, jugador: str) -> pd.DataFrame:
    """Historial completo de un jugador, ordenado por fecha."""
    return df[df["JUGADOR"] == jugador].sort_values("FECHA").reset_index(drop=True)


def semaforo(delta_pct: float, lower_is_better: bool = False) -> tuple:
    """
    Retorna (color_hex, label) según variación porcentual.
    Umbrales: ±5% gris, >5% verde/rojo, <-5% rojo/verde
    """
    if delta_pct is None or np.isnan(delta_pct):
        return _C["muted"], "—"
    effective = -delta_pct if lower_is_better else delta_pct
    if abs(effective) < 2:
        return _C["gray"], "ZONA GRIS"
    elif effective >= 5:
        return _C["green"], "ÓPTIMO"
    elif effective > 0:
        return _C["yellow"], "ATENCIÓN"
    elif effective >= -5:
        return _C["yellow"], "ATENCIÓN"
    else:
        return _C["red"], "ALERTA"


# ════════════════════════════════════════════════════════════════════
# CHARTS
# ════════════════════════════════════════════════════════════════════

def chart_kpi_cards(df: pd.DataFrame, jugador: str):
    """
    8 tarjetas KPI estilo Excel:
    valor actual | % vs última | Z-Score | Mejor Histórico | Semáforo
    """
    hist = get_player_history(df, jugador)
    if hist.empty:
        st.warning("Sin datos para este jugador.")
        return

    latest = hist.iloc[-1]
    prev   = hist.iloc[-2] if len(hist) > 1 else hist.iloc[-1]
    best   = hist.max(numeric_only=True)

    # Calcular Z-scores del jugador en el contexto grupal
    latest_z = {}
    for col, z_col in Z_COLS.items():
        if z_col in df.columns:
            row = df[df["JUGADOR"] == jugador].sort_values("FECHA").iloc[-1]
            latest_z[col] = row.get(z_col, 0)

    cards = [
        ("CMJ",     "CMJ_cm",   "cm",  False, "Z_CMJ"),
        ("SJ",      "SJ_cm",    "cm",  False, "Z_SJ"),
        ("DJ",      "DJ_cm",    "cm",  False, None),
        ("IMTP",    "IMTP_N",   "N",   False, "Z_IMTP"),
        ("RSI DJ",  "DJ_RSI",   "",    False, "Z_DJ_RSI"),
        ("TC DJ",   "DJ_tc_ms", "ms",  True,  "Z_DJ_TC"),
        ("EUR",     "EUR",      "",    False, "Z_EUR"),
        ("CMJ RSI", "CMJ_RSI",  "",    False, None),
    ]

    cols = st.columns(4)
    for i, (label, col, unit, lower, z_key) in enumerate(cards):
        if col not in latest.index or pd.isna(latest[col]):
            continue
        val = latest[col]
        prev_val = prev[col] if col in prev.index and not pd.isna(prev[col]) else val
        best_val = best[col] if col in best.index else val

        delta_pct = ((val - prev_val) / prev_val * 100) if prev_val != 0 else 0
        z_val = float(latest_z.get(col, 0)) if z_key and col in latest_z else None

        sem_color, sem_label = semaforo(delta_pct, lower)

        # Format display
        if unit == "N":
            val_str = f"{val:,.0f}"
            best_str = f"{best_val:,.0f}"
        elif unit == "ms":
            val_str = f"{val:.0f}"
            best_str = f"{best_val:.0f}"
        elif unit == "cm":
            val_str = f"{val:.2f}".replace(".", ",")
            best_str = f"{best_val:.2f}".replace(".", ",")
        else:
            val_str = f"{val:.3f}"
            best_str = f"{best_val:.3f}"

        delta_str = f"{delta_pct:+.2f}".replace(".", ",")
        z_str = f"{z_val:+.2f}" if z_val is not None else "—"

        arrow = "▲" if delta_pct > 0 else "▼" if delta_pct < 0 else "●"
        delta_color = _C["green"] if (delta_pct > 0 and not lower) or (delta_pct < 0 and lower) \
                      else _C["red"] if delta_pct != 0 else _C["gray"]

        # Colores del borde izquierdo y badge según semáforo — rgba para compatibilidad Streamlit
        border_colors = {
            _C["green"]:  ("rgba(79,201,126,0.9)",  "rgba(79,201,126,0.12)"),
            _C["yellow"]: ("rgba(232,200,74,0.9)",  "rgba(232,200,74,0.10)"),
            _C["red"]:    ("rgba(217,79,79,0.9)",   "rgba(217,79,79,0.12)"),
            _C["gray"]:   ("rgba(90,106,122,0.7)",  "rgba(90,106,122,0.08)"),
            _C["muted"]:  ("rgba(58,74,90,0.6)",    "rgba(58,74,90,0.06)"),
        }
        b_solid, b_bg = border_colors.get(sem_color, ("rgba(42,95,142,0.6)", "rgba(42,95,142,0.06)"))

        z_color = _C["green"] if z_val is not None and z_val >= 0.5 else \
                  _C["red"]   if z_val is not None and z_val <= -0.5 else _C["blue"]

        html = (
            f'<div style="background:{_C["card"]};border:1px solid rgba(42,95,142,0.18);'
            f'border-left:3px solid {b_solid};border-radius:6px;'
            f'padding:14px 14px 12px;margin-bottom:10px;min-height:138px;">'

            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            f'<span style="font-family:sans-serif;font-weight:700;font-size:10px;'
            f'letter-spacing:0.15em;text-transform:uppercase;color:{_C["steel"]};">{label}</span>'
            f'<span style="background:{b_bg};border:1px solid {b_solid};color:{sem_color};'
            f'font-family:sans-serif;font-size:8px;font-weight:700;letter-spacing:0.1em;'
            f'text-transform:uppercase;padding:2px 6px;border-radius:3px;">{sem_label}</span>'
            f'</div>'

            f'<div style="display:flex;align-items:baseline;gap:4px;margin-bottom:10px;">'
            f'<span style="font-family:monospace;font-weight:600;font-size:1.7rem;'
            f'color:{_C["white"]};line-height:1;">{val_str}</span>'
            f'<span style="font-family:sans-serif;font-size:11px;color:{_C["gray"]};margin-left:2px;">{unit}</span>'
            f'</div>'

            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:3px 8px;">'
            f'<div style="font-family:sans-serif;font-size:8px;text-transform:uppercase;color:{_C["muted"]};">Δ vs anterior</div>'
            f'<div style="font-family:sans-serif;font-size:8px;text-transform:uppercase;color:{_C["muted"]};">Z-Score</div>'
            f'<div style="font-family:monospace;font-size:12px;font-weight:600;color:{delta_color};">{arrow} {delta_str}%</div>'
            f'<div style="font-family:monospace;font-size:12px;font-weight:500;color:{z_color};">{z_str} σ</div>'
            f'<div style="font-family:sans-serif;font-size:8px;text-transform:uppercase;color:{_C["muted"]};margin-top:4px;">Mejor hist.</div>'
            f'<div style="font-family:sans-serif;font-size:8px;margin-top:4px;"></div>'
            f'<div style="font-family:monospace;font-size:11px;color:{_C["gray"]};">{best_str} <span style="font-size:9px;color:{_C["muted"]};">{unit}</span></div>'
            f'</div>'
            f'</div>'
        )

        with cols[i % 4]:
            st.markdown(html, unsafe_allow_html=True)


def chart_quadrant_team(df: pd.DataFrame) -> go.Figure:
    """
    Cuadrante grupal: X = Z-Score RSI DJ | Y = Z-Score IMTP
    Replica exacta del gráfico 'Clasificación' del Excel.
    """
    latest = get_latest_per_player(df)
    latest = compute_zscores(latest)

    needed = {"Z_DJ_RSI", "Z_IMTP", "JUGADOR"}
    if not needed.issubset(latest.columns):
        return _empty_figure("Datos de Z-Score no disponibles")

    d = latest.dropna(subset=["Z_DJ_RSI", "Z_IMTP"])
    if d.empty:
        return _empty_figure("Sin datos de Z-Score válidos")

    # Color por cuadrante
    def quad_color(row):
        x, y = row["Z_DJ_RSI"], row["Z_IMTP"]
        if x >= 0 and y >= 0: return "#2A6E5E"
        if x < 0  and y >= 0: return "#2A4A8E"
        if x >= 0 and y < 0:  return "#8E5A2A"
        return "#6E2A2A"

    d = d.copy()
    d["color"] = d.apply(quad_color, axis=1)

    fig = go.Figure()

    # Líneas de referencia
    fig.add_hline(y=0, line_color="rgba(42,95,142,0.4)", line_width=1)
    fig.add_vline(x=0, line_color="rgba(42,95,142,0.4)", line_width=1)

    # Labels de cuadrante
    quads = [
        (1.8, 2.5,  "VELOCIDAD + FUERZA",    "#2A6E5E"),
        (-2.8, 2.5, "FUERZA / BAJA VEL.",    "#2A4A8E"),
        (1.8, -2.5, "VELOCIDAD / BAJA F.",   "#8E5A2A"),
        (-2.8, -2.5,"DÉFICIT GENERAL",       "#6E2A2A"),
    ]
    for x, y, label, col in quads:
        fig.add_annotation(x=x, y=y, text=label,
                           font=dict(size=8, color=col),
                           showarrow=False, xanchor="center")

    # Vectorized scatter — mucho más eficiente que .iterrows()
    if not d.empty:
        nombres_cortos = [str(j).split(",")[0] if "," in str(j) else str(j) for j in d["JUGADOR"]]
        hover_text = [
            f"<b>{j}</b><br>Z-RSI: {z_rsi:.2f}<br>Z-IMTP: {z_imtp:.2f}"
            for j, z_rsi, z_imtp in zip(d["JUGADOR"], d["Z_DJ_RSI"], d["Z_IMTP"])
        ]
        fig.add_trace(go.Scatter(
            x=d["Z_DJ_RSI"],
            y=d["Z_IMTP"],
            mode="markers+text",
            marker=dict(size=16, 
                        color=d["color"],
                        line=dict(color="rgba(255,255,255,0.3)", width=1)),
            text=nombres_cortos,
            textposition="top center",
            textfont=dict(size=9, color="#C8D8E8"),
            customdata=hover_text,
            hovertemplate="%{customdata}<extra></extra>",
            name="Jugadores",
            showlegend=False,
        ))

    fig.update_layout(
        **_DARK,
        title=dict(text="<b>CLASIFICACIÓN GRUPAL</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=14)),
        xaxis=dict(title=dict(text="VELOCIDAD (Z-Score RSI DJ)",
                              font=dict(size=10, color=_C["gray"])),
                   range=[-3.2, 3.2],
                   gridcolor="rgba(42,95,142,0.12)", zeroline=False),
        yaxis=dict(title=dict(text="FUERZA (Z-Score IMTP)",
                              font=dict(size=10, color=_C["gray"])),
                   range=[-3.2, 3.2],
                   gridcolor="rgba(42,95,142,0.12)", zeroline=False),
        height=480,
    )
    return fig


def chart_bar_comparativa(df: pd.DataFrame) -> go.Figure:
    """
    Barras agrupadas SJ/CMJ/DJ por jugador (última evaluación).
    """
    latest = get_latest_per_player(df)
    # Verificar que existan las columnas necesarias
    required_cols = ["CMJ_cm", "SJ_cm", "DJ_cm"]
    if not all(col in latest.columns for col in required_cols):
        return go.Figure().add_annotation(
            text="Sin datos de saltos",
            showarrow=False,
            font=dict(size=14, color="gray")
        )
    d = latest.dropna(subset=required_cols)
    if d.empty:
        return go.Figure()

    # Ordenar por CMJ desc
    d = d.sort_values("CMJ_cm", ascending=False)
    nombres = d["JUGADOR"].str.split(",").str[0]

    fig = go.Figure()
    for col, label, color in [
        ("SJ_cm",  "SJ",  _C["blue"]),
        ("CMJ_cm", "CMJ", _C["steel"]),
        ("DJ_cm",  "DJ",  _C["navy"]),
    ]:
        fig.add_trace(go.Bar(
            x=nombres, y=d[col], name=label,
            marker_color=color,
            hovertemplate=f"<b>%{{x}}</b><br>{label}: %{{y:.1f}} cm<extra></extra>",
        ))

    fig.update_layout(
        **_DARK, barmode="group", height=340,
        title=dict(text="<b>COMPARATIVA ALTURA (cm) — SJ · CMJ · DJ</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        xaxis=dict(tickfont=dict(size=9), gridcolor="rgba(42,95,142,0.08)"),
        yaxis=dict(title="cm", gridcolor="rgba(42,95,142,0.08)"),
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
    )
    return fig


def chart_dj_rsi_grupal(df: pd.DataFrame) -> go.Figure:
    """
    Línea DJ (cm) y RSI por jugador (eje dual) — última evaluación.
    """
    latest = get_latest_per_player(df)
    # Verificar que existan las columnas necesarias
    required_cols = ["DJ_cm", "DJ_RSI"]
    if not all(col in latest.columns for col in required_cols):
        return go.Figure().add_annotation(
            text="Sin datos de DJ/RSI",
            showarrow=False,
            font=dict(size=14, color="gray")
        )
    d = latest.dropna(subset=required_cols).sort_values("DJ_RSI", ascending=False)
    if d.empty:
        return go.Figure()

    nombres = d["JUGADOR"].str.split(",").str[0]
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=nombres, y=d["DJ_cm"], name="DJ (cm)",
        mode="lines+markers",
        line=dict(color=_C["steel"], width=2),
        marker=dict(size=7),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=nombres, y=d["DJ_RSI"], name="RSI",
        mode="lines+markers",
        line=dict(color=_C["red"], width=2, dash="dot"),
        marker=dict(size=7),
    ), secondary_y=True)

    fig.update_layout(
        **_DARK, height=300,
        title=dict(text="<b>DJ (cm) vs RSI — GRUPAL</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        legend=dict(orientation="h", y=1.08),
    )
    fig.update_yaxes(title_text="DJ (cm)", secondary_y=False,
                     gridcolor="rgba(42,95,142,0.08)")
    fig.update_yaxes(title_text="RSI", secondary_y=True, showgrid=False)
    return fig


def chart_sprint_tendencia(df: pd.DataFrame) -> go.Figure:
    """
    Tendencia de mejores tiempos de sprint 20m y 10m con promedio grupal.
    """
    # Verificar que existan las columnas necesarias
    required_cols = ["Sprint_20m", "FECHA"]
    if not all(col in df.columns for col in required_cols):
        return go.Figure().add_annotation(
            text="Sin datos de Sprint",
            showarrow=False,
            font=dict(size=14, color="gray")
        )
    
    d = df.dropna(subset=required_cols).copy()
    if d.empty:
        return go.Figure()

    # Promedio grupal por fecha
    avg = d.groupby("FECHA")[["Sprint_10m", "Sprint_20m"]].mean().reset_index()
    # Mejor tiempo (mínimo) por fecha
    best = d.groupby("FECHA")[["Sprint_10m", "Sprint_20m"]].min().reset_index()

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["SPRINT 20m", "SPRINT 10m"])

    for col_idx, (sprint_col, title) in enumerate([("Sprint_20m","20m"), ("Sprint_10m","10m")], 1):
        # Solo procesar si la columna existe en avg
        if sprint_col not in avg.columns or d[sprint_col].notna().sum() == 0:
            continue
        # Puntos individuales (scatter ligero)
        fig.add_trace(go.Scatter(
            x=d["FECHA"], y=d[sprint_col],
            mode="markers",
            marker=dict(size=5, color=_C["steel"], opacity=0.4),
            name=f"Ind {title}", showlegend=False,
            hovertemplate="%{x|%d/%m/%y}<br>%{y:.2f}s<extra></extra>",
        ), row=1, col=col_idx)

        # Promedio
        fig.add_trace(go.Scatter(
            x=avg["FECHA"], y=avg[sprint_col],
            mode="lines+markers",
            line=dict(color=_C["red"], width=2),
            marker=dict(size=6),
            name=f"AVG {title}",
            hovertemplate="AVG %{x|%d/%m/%y}<br>%{y:.2f}s<extra></extra>",
        ), row=1, col=col_idx)

        # Trend line
        if len(avg) > 1 and avg[sprint_col].std() > 0:
            x_num = np.arange(len(avg))
            try:
                filled_vals = avg[sprint_col].ffill()  # Deprecated: fillna(method="ffill")
                z = np.polyfit(x_num, filled_vals, 1)
                trend = np.poly1d(z)(x_num)
                fig.add_trace(go.Scatter(
                    x=avg["FECHA"], y=trend,
                    mode="lines",
                    line=dict(color=_C["gray"], width=1, dash="dash"),
                    name=f"Trend {title}", showlegend=False,
                ), row=1, col=col_idx)
            except (ValueError, np.linalg.LinAlgError):
                logger.warning(f"No se pudo calcular trend line para {title}")

    fig.update_layout(
        **_DARK, height=300,
        title=dict(text="<b>TENDENCIA SPRINTS — MEJORES TIEMPOS</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        legend=dict(orientation="h", y=1.1, font=dict(size=9)),
    )
    fig.update_yaxes(gridcolor="rgba(42,95,142,0.08)", autorange="reversed")
    return fig


def chart_radar_individual(df: pd.DataFrame, jugador: str) -> go.Figure:
    """
    Radar: Z-Scores del jugador vs mejor valor del equipo.
    """
    latest_all = get_latest_per_player(df)
    latest_all = compute_zscores(latest_all)

    z_labels = ["CMJ\nAltura", "SJ\nAltura", "DJ\nReactividad",
                 "EUR\nElasticidad", "IMTP\nFuerza"]
    z_keys   = ["Z_CMJ", "Z_SJ", "Z_DJ_RSI", "Z_EUR", "Z_IMTP"]

    player_row = latest_all[latest_all["JUGADOR"] == jugador]
    if player_row.empty:
        return go.Figure()

    vals_p = [float(player_row[k].values[0]) if k in player_row.columns else 0 for k in z_keys]
    vals_best = [float(latest_all[k].max()) if k in latest_all.columns else 0 for k in z_keys]

    close_p = vals_p + [vals_p[0]]
    close_b = vals_best + [vals_best[0]]
    cats = z_labels + [z_labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=close_b, theta=cats,
        fill="toself", fillcolor="rgba(42,95,142,0.08)",
        line=dict(color=_C["red"], width=1.5, dash="dot"),
        name="Mejor Equipo",
    ))
    fig.add_trace(go.Scatterpolar(
        r=close_p, theta=cats,
        fill="toself", fillcolor="rgba(27,61,114,0.3)",
        line=dict(color=_C["steel"], width=2.5),
        name=jugador.split(",")[0],
    ))
    fig.update_layout(
        **_DARK,
        polar=dict(
            radialaxis=dict(range=[-3, 3], tickvals=[-2,-1,0,1,2],
                            ticktext=["−2σ","−1σ","0","1σ","2σ"],
                            gridcolor="rgba(42,95,142,0.15)",
                            linecolor="rgba(42,95,142,0.2)",
                            tickfont=dict(size=8, color=_C["gray"])),
            angularaxis=dict(tickfont=dict(size=9, color="#C8D8E8"),
                             gridcolor="rgba(42,95,142,0.1)"),
            bgcolor="rgba(8,14,24,0.8)",
        ),
        title=dict(
            text=f"<b>PERFIL — {jugador.split(',')[0].upper()}</b>",
            font=dict(color=_C["white"], family="Barlow Condensed", size=13), x=0.5,
        ),
        legend=dict(font=dict(size=9), orientation="h", y=-0.1),
        height=380,
    )
    return fig


def chart_historial_saltos(df: pd.DataFrame, jugador: str) -> go.Figure:
    """
    Historial CMJ/SJ/DJ (cm) del jugador a lo largo del tiempo.
    """
    hist = get_player_history(df, jugador)
    if hist.empty or len(hist) < 2:
        return go.Figure()

    fig = go.Figure()
    for col, label, color in [
        ("CMJ_cm", "CMJ", _C["steel"]),
        ("SJ_cm",  "SJ",  _C["yellow"]),
        ("DJ_cm",  "DJ",  _C["navy"]),
    ]:
        if col not in hist.columns: continue
        d = hist.dropna(subset=[col])
        fig.add_trace(go.Scatter(
            x=d["FECHA"], y=d[col],
            mode="lines+markers+text",
            name=label,
            line=dict(color=color, width=2),
            marker=dict(size=7),
            text=[f"{v:.1f}" for v in d[col]],
            textposition="top center",
            textfont=dict(size=8),
            hovertemplate=f"{label}: %{{y:.1f}} cm<br>%{{x|%d/%m/%y}}<extra></extra>",
        ))

    fig.update_layout(
        **_DARK, height=300,
        title=dict(text=f"<b>CMJ · SJ · DJ HISTORIAL — {jugador.split(',')[0].upper()}</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        xaxis=dict(title="Fecha", gridcolor="rgba(42,95,142,0.08)"),
        yaxis=dict(title="cm", gridcolor="rgba(42,95,142,0.08)"),
        legend=dict(orientation="h", y=1.08),
    )
    return fig


def chart_historial_dj_rsi(df: pd.DataFrame, jugador: str) -> go.Figure:
    """
    Historial DJ (cm) y RSI del jugador — eje dual.
    """
    hist = get_player_history(df, jugador)
    if hist.empty:
        return go.Figure()
    
    # Verificar que existan las columnas necesarias
    if "DJ_cm" not in hist.columns or "DJ_RSI" not in hist.columns:
        return go.Figure().add_annotation(
            text="Sin datos de DJ/RSI",
            showarrow=False,
            font=dict(size=14, color="gray")
        )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    d = hist.dropna(subset=["DJ_cm", "DJ_RSI"])

    fig.add_trace(go.Scatter(
        x=d["FECHA"], y=d["DJ_cm"],
        mode="lines+markers", name="DJ (cm)",
        line=dict(color=_C["steel"], width=2),
        marker=dict(size=7),
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=d["FECHA"], y=d["DJ_RSI"],
        mode="lines+markers", name="RSI",
        line=dict(color=_C["red"], width=2, dash="dot"),
        marker=dict(size=7),
    ), secondary_y=True)

    fig.update_layout(
        **_DARK, height=280,
        title=dict(text=f"<b>DJ · RSI HISTORIAL — {jugador.split(',')[0].upper()}</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_yaxes(title_text="DJ (cm)", secondary_y=False,
                     gridcolor="rgba(42,95,142,0.08)")
    fig.update_yaxes(title_text="RSI", secondary_y=True, showgrid=False)
    return fig


def chart_historial_eur(df: pd.DataFrame, jugador: str) -> go.Figure:
    """
    Historial EUR del jugador.
    """
    hist = get_player_history(df, jugador)
    d = hist.dropna(subset=["EUR"]) if "EUR" in hist.columns else pd.DataFrame()
    if d.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["FECHA"], y=d["EUR"],
        mode="lines+markers",
        fill="tozeroy", fillcolor="rgba(27,61,114,0.15)",
        line=dict(color=_C["steel"], width=2),
        marker=dict(size=7),
        hovertemplate="EUR: %{y:.3f}<br>%{x|%d/%m/%y}<extra></extra>",
    ))
    baseline = d["EUR"].mean()
    fig.add_hline(y=baseline, line_dash="dash", line_color=_C["gray"],
                  annotation_text=f"Media {baseline:.3f}",
                  annotation_font_color=_C["gray"])

    fig.update_layout(
        **_DARK, height=260,
        title=dict(text=f"<b>EUR HISTORIAL — {jugador.split(',')[0].upper()}</b>",
                   font=dict(color=_C["white"], family="Barlow Condensed", size=13)),
        xaxis=dict(gridcolor="rgba(42,95,142,0.08)"),
        yaxis=dict(title="EUR (ratio)", gridcolor="rgba(42,95,142,0.08)"),
    )
    return fig


# ════════════════════════════════════════════════════════════════════
# TEMPLATE CSV GENERATOR
# ════════════════════════════════════════════════════════════════════

def generate_template_csv() -> bytes:
    """Genera plantilla CSV descargable con el formato correcto."""
    tmpl = pd.DataFrame([{
        "JUGADOR": "Lopez, J.",
        "FECHA": "05/08/2024",
        "CMJ_PF_N": 2124.0,
        "CMJ_RSI": 0.912,
        "CMJ_cm": 35.5,
        "SJ_PF_N": 1707.0,
        "SJ_asim_pct": 8.9,
        "SJ_cm": 36.3,
        "DJ_tc_ms": 228.0,
        "DJ_cm": 28.4,
        "DJ_RSI": 1.246,
        "EUR": 0.978,
        "IMTP_N": 2737.0,
        "IMTP_RFD100": 3606.0,
        "IMTP_RFD250": 2761.0,
        "Sprint_10m": 1.879,
        "Sprint_20m": 2.971,
    }, {
        "JUGADOR": "Garcia, M.",
        "FECHA": "05/08/2024",
        "CMJ_PF_N": 2050.0,
        "CMJ_RSI": 0.880,
        "CMJ_cm": 34.1,
        "SJ_PF_N": 1650.0,
        "SJ_asim_pct": 7.2,
        "SJ_cm": 35.0,
        "DJ_tc_ms": 235.0,
        "DJ_cm": 27.8,
        "DJ_RSI": 1.183,
        "EUR": 0.974,
        "IMTP_N": 2580.0,
        "IMTP_RFD100": 3400.0,
        "IMTP_RFD250": 2600.0,
        "Sprint_10m": 1.920,
        "Sprint_20m": 3.010,
    }])
    return tmpl.to_csv(index=False).encode("utf-8")
