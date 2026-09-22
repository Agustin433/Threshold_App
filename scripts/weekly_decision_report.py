"""Reporte semanal de decision (Threshold S&C).

Genera un archivo Markdown corto, por atleta, con el mismo lenguaje del
Manual de Toma de Decisiones (semaforo verde/amarillo/rojo + reglas de
progresion), a partir de datos ya cargados en el store local:

  - Cumplimiento semanal      -> completion_df (completion_history.csv)
  - Volumen por patron        -> raw_df (raw_workouts_history.csv), columna Category
  - Tendencia de sRPE         -> rpe_df (rpe_history.csv)
  - Alerta de tendencia wellness (NO semaforo compuesto) -> wellness_df
  - Perfilado (CMJ/SJ/DJ/IMTP) -> jump_df, SOLO si hay test nuevo esta semana

Deliberadamente NO usa modules/alerts.py ni modules/load_monitoring.py
(ACWR/EWMA/monotonia): esos modulos tienen bugs de semaforo y de promediado
de wellness ya identificados. Todo el calculo de abajo es propio, simple y
auditable a mano.

Uso:
    python scripts/weekly_decision_report.py --week-start YYYY-MM-DD [--out reporte.md]

--week-start es el LUNES de la semana que se esta reportando (debe coincidir
con el --week-start que se uso en weekly_ingest.py esa semana).
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

import local_store as ls  # noqa: E402

BASELINE_WEEKS = 6
MIN_BASELINE_WEEKS = 3
Z_NOTABLE = 1.5
Z_SEVERE = 2.0

METRIC_BY_CATEGORY = {
    "strength_loaded": "Volume_Load_kg",
    "olympic_derivatives": "Volume_Load_kg",
    "plyo_jump": "Contacts",
    "landing_mechanics": "Contacts",
    "sprint_cod": "Distance_m",
    "iso": "Exposures",
    "core_stability": "Exposures",
    "mobility_prehab": "Exposures",
}
CATEGORY_LABEL_ES = {
    "strength_loaded": "fuerza / carga externa",
    "olympic_derivatives": "derivados olimpicos",
    "plyo_jump": "pliometria / salto",
    "landing_mechanics": "mecanica de aterrizaje",
    "sprint_cod": "sprint / cambio de direccion",
    "iso": "isometricos",
    "core_stability": "core / estabilidad",
    "mobility_prehab": "movilidad / prehab",
}


def _most_recent_completed_monday(today: date | None = None) -> date:
    """Debe coincidir siempre con el mismo helper de weekly_ingest.py."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def week_monday(d: pd.Timestamp) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    return d - pd.Timedelta(days=d.weekday())


def _zscore(current: float, baseline_values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(baseline_values) < MIN_BASELINE_WEEKS:
        return None, None, None
    mean = statistics.mean(baseline_values)
    sd = statistics.pstdev(baseline_values)
    if sd == 0:
        return None, mean, sd
    return (current - mean) / sd, mean, sd


def build_pattern_zscores(raw_df: pd.DataFrame, current_week: pd.Timestamp) -> dict[str, list[dict]]:
    """Z-score INTRA-atleta por categoria de patron (no contra el grupo)."""
    if raw_df is None or raw_df.empty:
        return {}
    df = raw_df.copy()
    df["Assigned Date"] = pd.to_datetime(df["Assigned Date"], errors="coerce")
    df = df.dropna(subset=["Assigned Date", "Athlete", "Category"])
    df["week"] = df["Assigned Date"].apply(week_monday)

    out: dict[str, list[dict]] = {}
    for (athlete, category), group in df.groupby(["Athlete", "Category"]):
        if category in ("untagged", "Untagged", "invalid", "Invalid"):
            continue
        metric_col = METRIC_BY_CATEGORY.get(category)
        if metric_col is None or metric_col not in group.columns:
            continue
        weekly = group.groupby("week")[metric_col].sum()
        current_val = float(weekly.get(current_week, 0.0))
        baseline_weeks = sorted(w for w in weekly.index if w < current_week)[-BASELINE_WEEKS:]
        baseline_vals = [float(weekly[w]) for w in baseline_weeks]
        z, mean, sd = _zscore(current_val, baseline_vals)
        if z is None:
            continue
        out.setdefault(athlete, []).append(
            {
                "category": category,
                "metric": metric_col,
                "current": current_val,
                "baseline_mean": mean,
                "z": z,
                "weeks_of_history": len(baseline_vals),
            }
        )
    return out


def build_srpe_trend(rpe_df: pd.DataFrame, current_week: pd.Timestamp) -> dict[str, dict]:
    if rpe_df is None or rpe_df.empty:
        return {}
    df = rpe_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Athlete"])
    df["week"] = df["Date"].apply(week_monday)
    out: dict[str, dict] = {}
    for athlete, group in df.groupby("Athlete"):
        weekly = group.groupby("week")["sRPE"].mean()
        current_val = weekly.get(current_week)
        baseline_weeks = sorted(w for w in weekly.index if w < current_week)[-BASELINE_WEEKS:]
        baseline_vals = [float(weekly[w]) for w in baseline_weeks if pd.notna(weekly[w])]
        if current_val is None or pd.isna(current_val):
            continue
        z, mean, sd = _zscore(float(current_val), baseline_vals)
        out[athlete] = {"current": float(current_val), "baseline_mean": mean, "z": z}
    return out


def build_wellness_trend(wellness_df: pd.DataFrame, current_week: pd.Timestamp) -> dict[str, dict]:
    """Alerta de TENDENCIA por atleta (no semaforo compuesto, no ACWR)."""
    if wellness_df is None or wellness_df.empty:
        return {}
    df = wellness_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Athlete"])
    df["week"] = df["Date"].apply(week_monday)
    out: dict[str, dict] = {}
    for athlete, group in df.groupby("Athlete"):
        weekly = group.groupby("week")[["Sueno_hs", "Estres", "Dolor"]].mean()
        if current_week not in weekly.index:
            continue
        baseline_weeks = sorted(w for w in weekly.index if w < current_week)[-BASELINE_WEEKS:]
        if len(baseline_weeks) < MIN_BASELINE_WEEKS:
            continue
        alerts = []
        for col, bad_direction in (("Sueno_hs", "down"), ("Estres", "up"), ("Dolor", "up")):
            current_val = weekly.loc[current_week, col]
            baseline_vals = [weekly.loc[w, col] for w in baseline_weeks if pd.notna(weekly.loc[w, col])]
            if pd.isna(current_val) or len(baseline_vals) < MIN_BASELINE_WEEKS:
                continue
            z, mean, sd = _zscore(float(current_val), [float(v) for v in baseline_vals])
            if z is None:
                continue
            worsening = (bad_direction == "down" and z <= -Z_NOTABLE) or (bad_direction == "up" and z >= Z_NOTABLE)
            if worsening:
                alerts.append({"variable": col, "z": z, "current": float(current_val), "baseline_mean": mean})
        if alerts:
            out[athlete] = {"alerts": alerts}
    return out


def build_compliance(completion_df: pd.DataFrame, current_week: pd.Timestamp) -> dict[str, dict]:
    if completion_df is None or completion_df.empty:
        return {}
    df = completion_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    current_rows = df[df["Date"] == current_week]
    baseline_rows = df[(df["Date"] < current_week) & (df["Date"] >= current_week - pd.Timedelta(weeks=BASELINE_WEEKS))]
    out: dict[str, dict] = {}
    baseline_by_athlete = baseline_rows.groupby("Athlete")["Pct"].mean() if not baseline_rows.empty else pd.Series(dtype=float)
    for _, row in current_rows.iterrows():
        athlete = row["Athlete"]
        out[athlete] = {
            "pct": row.get("Pct"),
            "assigned": row.get("Assigned"),
            "completed": row.get("Completed"),
            "baseline_pct": baseline_by_athlete.get(athlete),
        }
    return out


def build_profiling(jump_df: pd.DataFrame, current_week: pd.Timestamp) -> dict[str, dict]:
    if jump_df is None or jump_df.empty:
        return {}
    df = jump_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    week_end = current_week + pd.Timedelta(days=6)
    in_week = df[(df["Date"] >= current_week) & (df["Date"] <= week_end)]
    out: dict[str, dict] = {}
    z_cols = ["SJ_Z", "CMJ_Z", "DJ_height_Z", "DJ_RSI_Z", "IMTP_relPF_Z"]
    for athlete, group in in_week.groupby("Athlete"):
        row = group.sort_values("Date").iloc[-1]
        z_values = {c: row[c] for c in z_cols if c in row and pd.notna(row[c])}
        out[athlete] = {"date": row["Date"], "z_values": z_values, "nm_profile": row.get("NM_Profile")}
    return out


def adherencia(compliance: dict) -> tuple[str, str | None]:
    """Adherencia es un eje SEPARADO del semaforo de carga.

    Faltar al gimnasio no es una senal de sobrecarga: no hay estimulo que
    "bajar" si el estimulo no ocurrio. Tratarlo como si fuera lo mismo que un
    sRPE disparado es el error de prescribir un deload por una ausencia -
    intervenir sobre la variable equivocada. Esto solo describe si hubo o no
    el volumen de trabajo esperado; la decision de que hacer con eso vive en
    build_note(), no en el semaforo de carga.
    """
    pct = compliance.get("pct") if compliance else None
    if pct is None or pd.isna(pct):
        return "SIN DATO", None
    if pct < 50:
        return "BAJA", f"cumplimiento bajo esta semana ({pct:.0f}%)"
    if pct < 70:
        return "PARCIAL", f"cumplimiento parcial esta semana ({pct:.0f}%)"
    return "OK", None


def semaforo(athlete: str, srpe: dict, patterns: list[dict], wellness: dict) -> tuple[str, list[str]]:
    """Clasifica verde/amarillo/rojo de CARGA/FATIGA unicamente.

    Deliberadamente NO toma cumplimiento como input: cumplimiento es un eje
    de adherencia (ver adherencia()), no de manejo de carga. Reglas
    calcadas de la seccion 3.3 del Manual de Toma de Decisiones (semaforo de
    ajuste), aplicadas a variables propias en vez del semaforo compuesto
    bugueado de la app.
    """
    señales: list[str] = []
    severity = 0  # 0 verde, 1 amarillo, 2 rojo

    if srpe and srpe.get("z") is not None:
        z = srpe["z"]
        if z >= Z_SEVERE:
            severity = max(severity, 2)
            señales.append(f"sRPE muy por encima de lo habitual (z={z:+.1f})")
        elif z >= Z_NOTABLE:
            severity = max(severity, 1)
            señales.append(f"sRPE por encima de lo habitual (z={z:+.1f})")
        elif z <= -Z_SEVERE:
            severity = max(severity, 1)
            señales.append(f"sRPE muy por debajo de lo habitual (z={z:+.1f})")

    for p in patterns:
        z = p["z"]
        label = CATEGORY_LABEL_ES.get(p["category"], p["category"])
        if abs(z) >= Z_SEVERE:
            severity = max(severity, 2)
            direction = "por encima" if z > 0 else "por debajo"
            señales.append(f"{label}: muy {direction} de su propio promedio (z={z:+.1f})")
        elif abs(z) >= Z_NOTABLE:
            severity = max(severity, 1)
            direction = "por encima" if z > 0 else "por debajo"
            señales.append(f"{label}: {direction} de su propio promedio (z={z:+.1f})")

    if wellness and wellness.get("alerts"):
        severity = max(severity, 1)
        for a in wellness["alerts"]:
            var_label = {"Sueno_hs": "sueño en baja", "Estres": "estrés en alza", "Dolor": "dolor en alza"}[a["variable"]]
            if abs(a["z"]) >= Z_SEVERE:
                severity = max(severity, 2)
            señales.append(f"tendencia de wellness: {var_label} (z={a['z']:+.1f})")

    color = {0: "VERDE", 1: "AMARILLO", 2: "ROJO"}[severity]
    return color, señales


def load_suggestion(color: str, patterns: list[dict]) -> str:
    worst_pattern = max(patterns, key=lambda p: abs(p["z"]), default=None)
    if color == "ROJO":
        base = "Bajar volumen/densidad primero y proteger el driver neural; deload de 3-7 dias segun el caso."
    elif color == "AMARILLO":
        base = "Mantener la dosis actual, priorizar calidad y descanso; no sumar complejidad esta semana."
    else:
        base = "Segue el plan; si sostiene, subi 1 variable (una sola): +1 set, +1-2% o +1 exposicion."
    if worst_pattern and abs(worst_pattern["z"]) >= Z_NOTABLE:
        label = CATEGORY_LABEL_ES.get(worst_pattern["category"], worst_pattern["category"])
        base += f" Punto concreto a mirar: {label}."
    return base


def adherence_suggestion(adherence_status: str) -> str | None:
    if adherence_status == "BAJA":
        return (
            "Antes de tocar la programacion: entender por que no vino (lesion, logistica, motivacion) - "
            "no es un problema de dosis. Si vuelve esta semana, reingreso progresivo (no arrancar donde "
            "habia quedado el plan): el riesgo real de una ausencia es el salto agudo:cronico al volver, no la sobrecarga."
        )
    if adherence_status == "PARCIAL":
        return "Confirmar con el atleta si el faltante fue puntual o si hay que ajustar la logistica del calendario."
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--week-start",
        default=None,
        help=(
            "LUNES (YYYY-MM-DD) de la semana a reportar - debe coincidir con el que se uso en "
            "weekly_ingest.py esa semana. Por defecto, el lunes de la ultima semana cerrada."
        ),
    )
    parser.add_argument("--out", default=None, help="Archivo .md de salida (por defecto imprime a stdout)")
    args = parser.parse_args()

    week_start_date = date.fromisoformat(args.week_start) if args.week_start else _most_recent_completed_monday()
    current_week = week_monday(pd.Timestamp(week_start_date))

    raw_df = ls.read_full_dataset("raw_df")
    rpe_df = ls.read_full_dataset("rpe_df")
    wellness_df = ls.read_full_dataset("wellness_df")
    completion_df = ls.read_full_dataset("completion_df")
    jump_df = ls.read_full_dataset("jump_df")

    patterns_by_athlete = build_pattern_zscores(raw_df, current_week)
    srpe_by_athlete = build_srpe_trend(rpe_df, current_week)
    wellness_by_athlete = build_wellness_trend(wellness_df, current_week)
    compliance_by_athlete = build_compliance(completion_df, current_week)
    profiling_by_athlete = build_profiling(jump_df, current_week)

    athletes = sorted(
        set(patterns_by_athlete) | set(srpe_by_athlete) | set(wellness_by_athlete) | set(compliance_by_athlete)
    )

    rows = []
    for athlete in athletes:
        compliance = compliance_by_athlete.get(athlete, {})
        srpe = srpe_by_athlete.get(athlete, {})
        patterns = patterns_by_athlete.get(athlete, [])
        wellness = wellness_by_athlete.get(athlete, {})

        adherence_status, adherence_note = adherencia(compliance)

        evaluable_carga = bool(srpe) or bool(patterns) or bool(wellness)
        if not evaluable_carga and adherence_status == "SIN DATO":
            rows.append(
                {
                    "athlete": athlete,
                    "color": "SIN DATOS",
                    "señales": ["historial insuficiente para evaluar tendencia (recien empieza a acumularse)"],
                    "adherencia": adherence_status,
                    "sugerencia_carga": None,
                    "sugerencia_adherencia": None,
                    "profiling": profiling_by_athlete.get(athlete),
                }
            )
            continue

        if evaluable_carga:
            color, señales = semaforo(athlete, srpe, patterns, wellness)
        else:
            color, señales = "SIN DATOS", ["historial insuficiente para evaluar carga/fatiga"]

        rows.append(
            {
                "athlete": athlete,
                "color": color,
                "señales": señales,
                "adherencia": adherence_status,
                "adherencia_nota": adherence_note,
                "sugerencia_carga": load_suggestion(color, patterns) if evaluable_carga else None,
                "sugerencia_adherencia": adherence_suggestion(adherence_status),
                "profiling": profiling_by_athlete.get(athlete),
            }
        )

    # Orden de atencion: lo mas urgente primero, mezclando el eje de carga y
    # el de adherencia (son independientes, pero ambos compiten por tu tiempo
    # esta semana).
    color_rank = {"ROJO": 0, "AMARILLO": 1, "VERDE": 2, "SIN DATOS": 3}
    adherence_rank = {"BAJA": 0, "PARCIAL": 1, "OK": 2, "SIN DATO": 3}

    def sort_key(r):
        return (min(color_rank[r["color"]], adherence_rank.get(r.get("adherencia", "SIN DATO"), 3)), r["athlete"])

    rows.sort(key=sort_key)

    lines = []
    lines.append(f"# Reporte semanal de decision - semana del {current_week.date().isoformat()}")
    lines.append("")
    lines.append(
        "Dos ejes SEPARADOS, a proposito: adherencia (cumplimiento de lo asignado) no es lo mismo que "
        "carga/fatiga (sRPE, patron de trabajo, wellness) - faltar al gimnasio no es una senal de "
        "sobrecarga, es un problema aparte. El semaforo de carga sale solo de sRPE, z-score por patron "
        "(contra el propio historial del atleta, no contra el grupo) y tendencia de wellness (sueño/estres/dolor, "
        "sin pasar por el motor de semaforo de la app). El perfilado (CMJ/SJ/DJ/IMTP) solo aparece si hubo "
        "test nuevo esta semana."
    )
    lines.append("")

    for r in rows:
        lines.append(f"## {r['athlete']}")
        lines.append(f"- **Carga:** {r['color']}")
        if r["señales"]:
            for s in r["señales"]:
                lines.append(f"  - {s}")
        else:
            lines.append("  - sin señales fuera de rango esta semana")
        adherencia_label = {
            "BAJA": "BAJA",
            "PARCIAL": "PARCIAL",
            "OK": "OK",
            "SIN DATO": "sin dato esta semana",
        }[r["adherencia"]]
        lines.append(f"- **Adherencia:** {adherencia_label}" + (f" ({r['adherencia_nota']})" if r.get("adherencia_nota") else ""))
        if r["profiling"] and r["profiling"].get("z_values"):
            z_txt = ", ".join(f"{k}={v:+.1f}" for k, v in r["profiling"]["z_values"].items())
            lines.append(f"- Perfilado nuevo esta semana ({r['profiling']['date'].date().isoformat()}): {z_txt}")
        if r["sugerencia_carga"]:
            lines.append(f"- **Sugerencia (carga):** {r['sugerencia_carga']}")
        if r["sugerencia_adherencia"]:
            lines.append(f"- **Sugerencia (adherencia):** {r['sugerencia_adherencia']}")
        lines.append("")

    if not rows:
        lines.append("_No hay datos suficientes para esta semana (revisar ingesta)._")

    output = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Reporte escrito en {args.out} ({len(rows)} atleta(s)).")
    else:
        print(output)


if __name__ == "__main__":
    main()
