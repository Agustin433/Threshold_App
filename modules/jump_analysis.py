"""Shared jump evaluation calculations and neuromuscular profiling."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Ref1: Normative data EFL 2025 - professional male soccer.
# External z-scores below are orientative, not normative, for other sports.
# Ref2: McMahon et al. 2022 - Super League vs Championship Rugby League.
# Ref3: McMahon et al. 2019 - RSImod levels in Rugby League.
# Ref4: Female Gaelic Football 2024 - sport-specific jump profiling context.
# Ref5: Maastricht University - CMJ vs SJ (EUR / elastic utilization).
# Ref6: Healy et al. 2017 - DJ RSI strategy and contact-time interpretation.

EARTH_GRAVITY = 9.81

# "Excellent" is used here as the product-facing z=+1 anchor because the coach
# wants z=0 to represent the reference average and z=+1 to represent a
# practically "good" threshold in the radar.
EXTERNAL_BENCHMARKS: dict[str, dict[str, float]] = {
    "CMJ_cm": {"mean": 38.0, "excellent": 53.0},
    "DJ_RSI": {"mean": 1.71, "excellent": 2.68},
    "IMTP_N": {"mean": 3031.0, "excellent": 4678.0},
    "IMTP_relPF": {"mean": 37.39, "excellent": 53.43},
    "mRSI": {"mean": 0.56, "excellent": 0.93},
}

for _benchmark in EXTERNAL_BENCHMARKS.values():
    _benchmark["sd"] = _benchmark["excellent"] - _benchmark["mean"]

METRIC_LABELS = {
    "SJ_cm": "SJ",
    "CMJ_cm": "CMJ",
    "DJ_cm": "DJ height",
    "DJ_RSI": "DJ RSI",
    "DJ_tc_ms": "DJ TC",
    "TC_inv_Z": "TC inv",
    "IMTP_relPF": "IMTP relPF",
    "IMTP_N": "IMTP",
    "EUR": "EUR",
    "DSI": "DSI",
    "mRSI": "mRSI",
    "Jump_Momentum": "Jump Momentum",
    "CMJ_rel_impulse": "Impulso Relativo Propulsivo",
}

SEMAPHORE_LABELS = (
    (1.0, "Verde"),
    (0.0, "Amarillo"),
    (-1.0, "Naranja"),
    (-math.inf, "Rojo"),
)

PATTERN_LIBRARY = {
    "A": {
        "phys": "Buena capacidad concentrica y techo de fuerza aceptable, menor expresion en SSC rapido.",
        "bio": "Mayor tiempo de construccion de impulso en ventanas de contacto breves.",
        "train": "Fast SSC, stiffness util, pogos, drop jumps dosificados, sprints cortos, fuerza con intencion alta y bajo lastre.",
    },
    "B": {
        "phys": "Buena reutilizacion de energia elastica en SSC rapido, con techo de fuerza concentrica limitado.",
        "bio": "Alta rigidez muscular funcional pero menor capacidad propulsiva maxima en saltos sin ciclo.",
        "train": "Trabajo de fuerza maxima y potencia concentrica, sentadilla pesada, hip thrust, saltos con carga.",
    },
    "C": {
        "phys": "Potencia explosiva presente con deficit de fuerza isometrica relativa. DSI probablemente elevado.",
        "bio": "Buena transferencia explosiva pero con menor base de fuerza maxima para sostenerla.",
        "train": "Fuerza maxima, IMTP-specific, isometricos en angulo de trabajo funcional.",
    },
    "D": {
        "phys": "Deficit generalizado en capacidades neuromusculares evaluadas.",
        "bio": "Limitacion en produccion de fuerza, potencia y reutilizacion elastica.",
        "train": "Fase de acumulacion general. Priorizar fuerza basica antes de trabajo reactivo.",
    },
    "E": {
        "note": "Nota: CMJ < SJ. El atleta no aprovecha eficientemente el ciclo estiramiento-acortamiento en este test. Revisar fatiga acumulada, tecnica de CMJ o deficit especifico de SSC lento.",
        "bio_dj_rsi_high": "Buena rigidez muscular funcional en SSC rapido, pero el CMJ < SJ indica que el ciclo de estiramiento no esta potenciando el salto con contramovimiento. Posible dominancia reactiva con limitacion en SSC lento.",
        "bio_sj_high": "Buena capacidad concentrica en SJ, pero el CMJ no supera al SJ, lo que indica que el contramovimiento no genera impulso adicional util. Revisar tecnica, fatiga o deficit de stiffness en SSC lento.",
    },
}

RADAR_FULL_AXES = (
    ("SJ", "SJ_cm", "cm", "SJ_Z"),
    ("CMJ", "CMJ_cm", "cm", "CMJ_Z"),
    ("DJ height", "DJ_cm", "cm", "DJ_height_Z"),
    ("DJ RSI", "DJ_RSI", "m/s", "DJ_RSI_Z"),
    ("TC inv", "DJ_tc_ms", "ms", "TC_inv_Z"),
    ("IMTP relPF", "IMTP_relPF", "N/kg", "IMTP_relPF_Z"),
)

RADAR_NO_IMTP_AXES = (
    ("SJ", "SJ_cm", "cm", "SJ_Z"),
    ("CMJ", "CMJ_cm", "cm", "CMJ_Z"),
    ("DJ height", "DJ_cm", "cm", "DJ_height_Z"),
    ("DJ RSI", "DJ_RSI", "m/s", "DJ_RSI_Z"),
)

RADAR_NO_DJ_AXES = (
    ("SJ", "SJ_cm", "cm", "SJ_Z"),
    ("CMJ", "CMJ_cm", "cm", "CMJ_Z"),
    ("IMTP relPF", "IMTP_relPF", "N/kg", "IMTP_relPF_Z"),
    ("mRSI", "mRSI", "m/s", "mRSI_Z"),
)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _normalize_eur_series_to_ratio(series: pd.Series) -> pd.Series:
    """Normalize EUR values to a canonical CMJ/SJ ratio."""
    result = pd.to_numeric(series, errors="coerce")
    pct_mask = result > 5
    result.loc[pct_mask] = 1 + (result.loc[pct_mask] / 100)
    return result.round(3)


def _round_column(frame: pd.DataFrame, column: str, digits: int) -> None:
    if column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").round(digits)


def _group_internal_z(
    values: pd.Series,
    athlete_series: pd.Series | None,
    *,
    invert: bool = False,
    min_count: int = 2,
) -> pd.Series:
    zscores = pd.Series(np.nan, index=values.index, dtype=float)
    if athlete_series is None:
        return zscores

    grouped = pd.DataFrame({"value": values, "athlete": athlete_series})
    for athlete, idx in grouped.groupby("athlete").groups.items():
        if pd.isna(athlete):
            continue
        series = values.loc[idx]
        valid = series.dropna()
        if len(valid) < min_count:
            continue
        std = float(valid.std(ddof=0))
        if std <= 0:
            continue
        z = (series - float(valid.mean())) / std
        zscores.loc[idx] = -z if invert else z
    return zscores


def _dataset_fallback_z(values: pd.Series, *, invert: bool = False) -> pd.Series:
    valid = values.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=values.index, dtype=float)
    std = float(valid.std(ddof=0))
    if std <= 0:
        return pd.Series(np.nan, index=values.index, dtype=float)
    z = (values - float(valid.mean())) / std
    return (-z if invert else z).astype(float)


def _external_z(values: pd.Series, metric_key: str | None) -> pd.Series:
    if metric_key is None or metric_key not in EXTERNAL_BENCHMARKS:
        return pd.Series(np.nan, index=values.index, dtype=float)
    benchmark = EXTERNAL_BENCHMARKS[metric_key]
    sd = float(benchmark["sd"])
    if sd <= 0:
        return pd.Series(np.nan, index=values.index, dtype=float)
    return ((values - float(benchmark["mean"])) / sd).astype(float)


def _resolve_zscore(
    frame: pd.DataFrame,
    metric_col: str,
    *,
    benchmark_key: str | None = None,
    invert: bool = False,
    internal_min_count: int = 2,
    allow_dataset_fallback: bool = True,
) -> pd.Series:
    values = _numeric_series(frame, metric_col)
    athlete_series = frame["Athlete"] if "Athlete" in frame.columns else None
    external = _external_z(values, benchmark_key)
    internal = _group_internal_z(values, athlete_series, invert=invert, min_count=internal_min_count)
    dataset = (
        _dataset_fallback_z(values, invert=invert)
        if allow_dataset_fallback
        else pd.Series(np.nan, index=values.index, dtype=float)
    )

    if benchmark_key is not None:
        resolved = external
    else:
        resolved = internal.combine_first(dataset)

    return resolved.where(values.notna())


def calc_eur(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical EUR as a CMJ/SJ ratio."""
    if "EUR" in df.columns:
        df["EUR"] = _normalize_eur_series_to_ratio(df["EUR"])
    if {"CMJ_cm", "SJ_cm"}.issubset(df.columns):
        cmj = _numeric_series(df, "CMJ_cm")
        sj = _numeric_series(df, "SJ_cm")
        mask = cmj.notna() & sj.notna() & (sj != 0)
        df.loc[mask, "EUR"] = (cmj.loc[mask] / sj.loc[mask]).round(3)
    return df


def calc_dj_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical DJ RSI in m/s using jump height (m) / contact time (s)."""
    if {"DJ_cm", "DJ_tc_ms"}.issubset(df.columns):
        dj_height_m = _numeric_series(df, "DJ_cm") / 100
        dj_tc_s = _numeric_series(df, "DJ_tc_ms") / 1000
        mask = dj_height_m.notna() & dj_tc_s.notna() & (dj_tc_s > 0)
        df.loc[mask, "DJ_RSI"] = (dj_height_m.loc[mask] / dj_tc_s.loc[mask]).round(3)
        # Backward-compatible alias. Older views and exports still look for DRI.
        df.loc[mask, "DRI"] = df.loc[mask, "DJ_RSI"]
    return df


def calc_dri(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for the legacy DRI field."""
    return calc_dj_rsi(df)


def calc_mrsi(df: pd.DataFrame) -> pd.DataFrame:
    """mRSI / RSImod in m/s, using CMJ height and real time-to-takeoff in seconds."""
    if "TTT_s" in df.columns:
        ttt_s = _numeric_series(df, "TTT_s")
    elif "TTT_ms" in df.columns:
        ttt_s = (_numeric_series(df, "TTT_ms") / 1000).round(3)
        df["TTT_s"] = ttt_s
    else:
        return df

    if "CMJ_cm" in df.columns:
        cmj_height_m = _numeric_series(df, "CMJ_cm") / 100
        mask = cmj_height_m.notna() & ttt_s.notna() & (ttt_s > 0)
        df.loc[mask, "mRSI"] = (cmj_height_m.loc[mask] / ttt_s.loc[mask]).round(3)
    return df


def calc_dsi(df: pd.DataFrame) -> pd.DataFrame:
    """DSI using propulsive CMJ max force divided by IMTP peak force."""
    if {"CMJ_propulsive_PF_N", "IMTP_N"}.issubset(df.columns):
        cmj_pf = _numeric_series(df, "CMJ_propulsive_PF_N")
        imtp = _numeric_series(df, "IMTP_N")
        mask = cmj_pf.notna() & imtp.notna() & (imtp > 0)
        df.loc[mask, "DSI"] = (cmj_pf.loc[mask] / imtp.loc[mask]).round(3)
    return df


def calc_imtp_rel_pf(df: pd.DataFrame) -> pd.DataFrame:
    """Relative IMTP peak force in N/kg."""
    if {"IMTP_N", "BW_kg"}.issubset(df.columns):
        imtp = _numeric_series(df, "IMTP_N")
        bw = _numeric_series(df, "BW_kg")
        mask = imtp.notna() & bw.notna() & (bw > 0)
        df.loc[mask, "IMTP_relPF"] = (imtp.loc[mask] / bw.loc[mask]).round(2)
    return df


def calc_jump_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """Jump momentum in kg.m/s using body mass and CMJ-derived takeoff velocity."""
    if {"BW_kg", "CMJ_cm"}.issubset(df.columns):
        bw = _numeric_series(df, "BW_kg")
        cmj_height_m = _numeric_series(df, "CMJ_cm") / 100
        mask = bw.notna() & cmj_height_m.notna() & (cmj_height_m >= 0)
        df.loc[mask, "Jump_Momentum"] = (
            bw.loc[mask] * np.sqrt(2 * EARTH_GRAVITY * cmj_height_m.loc[mask])
        ).round(1)
    return df


def calc_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """Neuromuscular z-scores with external-first and internal fallback logic."""
    zscore_specs = (
        ("SJ_cm", "SJ_Z", None, False),
        ("CMJ_cm", "CMJ_Z", "CMJ_cm", False),
        ("DJ_cm", "DJ_height_Z", None, False),
        ("DJ_RSI", "DJ_RSI_Z", "DJ_RSI", False),
        ("DJ_tc_ms", "TC_inv_Z", None, True),
        ("IMTP_relPF", "IMTP_relPF_Z", "IMTP_relPF", False),
        ("mRSI", "mRSI_Z", "mRSI", False),
        ("Jump_Momentum", "Jump_Momentum_Z", None, False),
        ("EUR", "EUR_Z", None, False),
        ("DSI", "DSI_Z", None, False),
        ("IMTP_N", "IMTP_N_Z", "IMTP_N", False),
    )

    for metric_col, z_col, benchmark_key, invert in zscore_specs:
        df[z_col] = _resolve_zscore(
            df,
            metric_col,
            benchmark_key=benchmark_key,
            invert=invert,
        ).round(2)

    df["CMJ_rel_impulse_Z"] = _resolve_zscore(
        df,
        "CMJ_rel_impulse",
        internal_min_count=3,
        allow_dataset_fallback=False,
    ).round(2)

    # Backward-compatible aliases used elsewhere in the app/reporting.
    df["DJtc_Z"] = df["TC_inv_Z"]
    df["DRI_Z"] = df["DJ_RSI_Z"]
    df["IMTP_Z"] = df["IMTP_relPF_Z"]
    return df


def calc_nm_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Official NM profile based on canonical EUR ratio thresholds."""
    if "EUR" not in df.columns:
        return df

    eur_ratio = _normalize_eur_series_to_ratio(df["EUR"])
    conditions = [
        eur_ratio >= 1.10,
        eur_ratio >= 1.00,
        eur_ratio < 1.00,
    ]
    labels = ["Reactivo", "Mixto", "Base de Fuerza"]
    df["EUR"] = eur_ratio
    df["NM_Profile"] = np.select(conditions, labels, default="Sin datos")
    return df


def _available_radar_axes(row: pd.Series | dict[str, object]) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    has_imtp = pd.notna(row_series.get("IMTP_relPF"))
    has_dj = pd.notna(row_series.get("DJ_cm")) and pd.notna(row_series.get("DJ_RSI"))
    has_mrsi = pd.notna(row_series.get("mRSI"))

    notes: list[str] = []
    if has_dj and has_imtp:
        axes = list(RADAR_FULL_AXES)
    elif has_dj:
        axes = list(RADAR_NO_IMTP_AXES)
        notes.append("IMTP no disponible")
    elif has_imtp:
        axes = list(RADAR_NO_DJ_AXES)
        notes.append("DJ no disponible")
        if not has_mrsi:
            axes = [axis for axis in axes if axis[1] != "mRSI"]
            notes.append("TTT no disponible")
    else:
        axes = list(RADAR_NO_IMTP_AXES[:2])
        notes.append("Perfil parcial")

    return axes, notes


def build_jump_flag_rows(row: pd.Series | dict[str, object]) -> list[dict[str, str]]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    flags: list[dict[str, str]] = []

    eur = pd.to_numeric(pd.Series([row_series.get("EUR")]), errors="coerce").iloc[0]
    if pd.notna(eur):
        if eur >= 1.10:
            flags.append({"level": "green", "text": "EUR ✓ SSC eficiente"})
        elif eur >= 1.00:
            flags.append({"level": "yellow", "text": "EUR ~ SSC moderado"})
        else:
            flags.append({"level": "red", "text": "EUR ↓ SSC deficiente"})

    dsi = pd.to_numeric(pd.Series([row_series.get("DSI")]), errors="coerce").iloc[0]
    if pd.notna(dsi):
        if dsi >= 1.0:
            flags.append({"level": "green", "text": "DSI ✓ Fuerza explosiva"})
        elif dsi >= 0.8:
            flags.append({"level": "yellow", "text": "DSI ~ Balanceado"})
        else:
            flags.append({"level": "red", "text": "DSI ↓ Deficit isometrico relativo"})

    has_real_ttt = False
    for ttt_col in ("TTT_s", "TTT_ms"):
        ttt_value = pd.to_numeric(pd.Series([row_series.get(ttt_col)]), errors="coerce").iloc[0]
        if pd.notna(ttt_value) and ttt_value > 0:
            has_real_ttt = True
            break

    mrsi = pd.to_numeric(pd.Series([row_series.get("mRSI")]), errors="coerce").iloc[0]
    if not has_real_ttt:
        flags.append({"level": "gray", "text": "mRSI — requiere TTT del export"})
    elif pd.notna(mrsi):
        if mrsi >= 0.70:
            flags.append({"level": "green", "text": "mRSI ✓"})
        elif mrsi >= 0.45:
            flags.append({"level": "yellow", "text": "mRSI ~"})
        else:
            flags.append({"level": "red", "text": "mRSI ↓"})

    return flags


def _pattern_matches(row: pd.Series) -> list[str]:
    sj_z = pd.to_numeric(pd.Series([row.get("SJ_Z")]), errors="coerce").iloc[0]
    dj_rsi_z = pd.to_numeric(pd.Series([row.get("DJ_RSI_Z")]), errors="coerce").iloc[0]
    cmj_z = pd.to_numeric(pd.Series([row.get("CMJ_Z")]), errors="coerce").iloc[0]
    imtp_relpf_z = pd.to_numeric(pd.Series([row.get("IMTP_relPF_Z")]), errors="coerce").iloc[0]
    eur = pd.to_numeric(pd.Series([row.get("EUR")]), errors="coerce").iloc[0]

    patterns: list[str] = []
    if pd.notna(sj_z) and pd.notna(dj_rsi_z) and sj_z > 0.5 and dj_rsi_z < -0.5:
        patterns.append("A")
    if pd.notna(sj_z) and pd.notna(dj_rsi_z) and sj_z < -0.5 and dj_rsi_z > 0.5:
        patterns.append("B")
    if pd.notna(imtp_relpf_z) and pd.notna(cmj_z) and imtp_relpf_z < -0.5 and cmj_z >= -0.5:
        patterns.append("C")

    radar_z_cols = [axis[3] for axis in _available_radar_axes(row)[0]]
    radar_values = [
        pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        for col in radar_z_cols
    ]
    radar_values = [value for value in radar_values if pd.notna(value)]
    if radar_values and all(value < -0.5 for value in radar_values):
        patterns.append("D")
    if pd.notna(eur) and eur < 1.00:
        patterns.append("E")
    return patterns


def build_jump_feedback_lines(row: pd.Series | dict[str, object]) -> list[str]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    axes, _ = _available_radar_axes(row_series)
    high_values: list[str] = []
    low_values: list[str] = []

    for label, _, _, z_col in axes:
        z_value = pd.to_numeric(pd.Series([row_series.get(z_col)]), errors="coerce").iloc[0]
        if pd.isna(z_value):
            continue
        if z_value > 0.5:
            high_values.append(f"{label} ({z_value:+.2f})")
        elif z_value < -0.5:
            low_values.append(f"{label} ({z_value:+.2f})")

    patterns = _pattern_matches(row_series)
    pattern_keys = [key for key in patterns if key in {"A", "B", "C", "D"}]

    if not high_values and not low_values:
        if "E" in patterns:
            biomecanico = (
                "CMJ < SJ: el contramovimiento no esta aportando impulso adicional util en este test. "
                "Revisar tecnica, fatiga acumulada o limitacion especifica del SSC lento."
            )
        else:
            biomecanico = "Sin deficits marcados en los tests disponibles."

        lines = [
            "Alto: sin variables > 0.5.",
            "Bajo: sin variables < -0.5.",
            "Fisiologico: Perfil equilibrado en todos los indices evaluados.",
            f"Biomecanico: {biomecanico}",
            "Proximo bloque: Continuar progresion planificada.",
        ]
        if "E" in patterns:
            lines.append(PATTERN_LIBRARY["E"]["note"])
        return lines

    phys_parts: list[str] = []
    bio_parts: list[str] = []
    train_parts: list[str] = []
    for key in pattern_keys:
        payload = PATTERN_LIBRARY[key]
        if payload["phys"] not in phys_parts:
            phys_parts.append(payload["phys"])
        if payload["bio"] not in bio_parts:
            bio_parts.append(payload["bio"])
        if payload["train"] not in train_parts:
            train_parts.append(payload["train"])

    if not phys_parts:
        texto_alto = (
            f"Mayor expresion en {', '.join(high_values)}"
            if high_values
            else "Sin variables con expresion alta marcada"
        )
        texto_bajo = (
            f"menor expresion en {', '.join(low_values)}"
            if low_values
            else "sin deficits marcados en el resto de variables"
        )
        phys_parts.append(f"{texto_alto}; {texto_bajo}.")
    if not bio_parts:
        if "E" in patterns and any(value.startswith("DJ RSI") for value in high_values):
            bio_parts.append(PATTERN_LIBRARY["E"]["bio_dj_rsi_high"])
        elif "E" in patterns and any(value.startswith("SJ") for value in high_values):
            bio_parts.append(PATTERN_LIBRARY["E"]["bio_sj_high"])
        else:
            bio_parts.append(
                "La mecanica no muestra un patron unico; interpretar junto al historial y al contexto del test."
            )
    if not train_parts:
        train_parts.append(
            "Sostener la capacidad dominante y priorizar la variable mas rezagada en el proximo bloque."
        )

    lines = [
        f"Alto: {', '.join(high_values) if high_values else 'sin variables > 0.5.'}",
        f"Bajo: {', '.join(low_values) if low_values else 'sin variables < -0.5.'}",
        f"Fisiologico: {' '.join(phys_parts)}",
        f"Biomecanico: {' '.join(bio_parts)}",
        f"Proximo bloque: {' '.join(dict.fromkeys(train_parts))}",
    ]
    if "E" in patterns:
        lines.append(PATTERN_LIBRARY["E"]["note"])
    return lines[:6]


def semaphore_label(z_value: float | int | None) -> str:
    if z_value is None or pd.isna(z_value):
        return "-"
    value = float(z_value)
    if value > 1.0:
        return "Verde"
    if 0.0 <= value <= 1.0:
        return "Amarillo"
    if -1.0 <= value < 0.0:
        return "Naranja"
    return "Rojo"


def build_jump_metric_table(row: pd.Series | dict[str, object]) -> pd.DataFrame:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    axes, _ = _available_radar_axes(row_series)
    rows: list[dict[str, object]] = []

    for label, value_col, unit, z_col in axes:
        value = pd.to_numeric(pd.Series([row_series.get(value_col)]), errors="coerce").iloc[0]
        z_value = pd.to_numeric(pd.Series([row_series.get(z_col)]), errors="coerce").iloc[0]
        rows.append(
            {
                "Variable": label,
                "Valor": round(float(value), 3) if pd.notna(value) else None,
                "Unidad": unit,
                "Z": round(float(z_value), 2) if pd.notna(z_value) else "-",
                "Semaforo": semaphore_label(z_value),
            }
        )

    rel_impulse = pd.to_numeric(pd.Series([row_series.get("CMJ_rel_impulse")]), errors="coerce").iloc[0]
    if pd.notna(rel_impulse):
        rel_impulse_z = pd.to_numeric(
            pd.Series([row_series.get("CMJ_rel_impulse_Z")]),
            errors="coerce",
        ).iloc[0]
        rows.append(
            {
                "Variable": "Impulso Relativo Propulsivo",
                "Valor": round(float(rel_impulse), 3),
                "Unidad": "N·s/kg",
                "Z": round(float(rel_impulse_z), 2) if pd.notna(rel_impulse_z) else "-",
                "Semaforo": semaphore_label(rel_impulse_z),
            }
        )
    return pd.DataFrame(rows)


def choose_secondary_quadrant_x_spec(df: pd.DataFrame) -> tuple[str, str]:
    # In heavier collision profiles, jump momentum avoids undervaluing heavier
    # athletes whose propulsive capability is not fully described by jump height.
    # Ref2 / Ref6 support this practical decision rule.
    average_bw = pd.to_numeric(df.get("BW_kg", pd.Series(dtype=float)), errors="coerce").dropna().mean()
    sport_text = " ".join(
        str(value).strip().lower()
        for col in ["Sport", "sport", "Deporte", "deporte"]
        if col in df.columns
        for value in df[col].dropna().tolist()
    )
    heavy_collision_context = (
        pd.notna(average_bw) and float(average_bw) > 85
    ) or any(token in sport_text for token in ("rugby", "handball pesado"))

    if heavy_collision_context:
        return "Jump_Momentum_Z", "Jump Momentum z"
    return "CMJ_Z", "CMJ z"


def _prepare_jump_df(jump_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the unified evaluations table and recompute derived metrics."""
    if jump_df is None or jump_df.empty:
        return pd.DataFrame()

    result = jump_df.copy()
    if "Athlete" in result.columns:
        result["Athlete"] = result["Athlete"].astype(str).str.strip().str.title()
    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce").dt.normalize()

    numeric_cols = [col for col in result.columns if col not in {"Athlete", "Date", "NM_Profile"}]
    for col in numeric_cols:
        result[col] = pd.to_numeric(result[col], errors="coerce")

    valid_subset = [col for col in ["Athlete", "Date"] if col in result.columns]
    result = result.dropna(subset=valid_subset)
    if result.empty:
        return pd.DataFrame()

    result = result.sort_values(["Athlete", "Date"]).drop_duplicates(
        subset=["Athlete", "Date"],
        keep="last",
    )
    result = calc_eur(result)
    result = calc_dj_rsi(result)
    result = calc_mrsi(result)
    result = calc_dsi(result)
    result = calc_imtp_rel_pf(result)
    result = calc_jump_momentum(result)
    result = calc_zscores(result)
    result = calc_nm_profile(result)

    for column, digits in (
        ("EUR", 3),
        ("DJ_RSI", 3),
        ("DRI", 3),
        ("mRSI", 3),
        ("DSI", 3),
        ("IMTP_relPF", 2),
        ("Jump_Momentum", 1),
    ):
        _round_column(result, column, digits)

    return result.sort_values(["Athlete", "Date"]).reset_index(drop=True)


def _records_to_jump_df(records: list[dict]) -> pd.DataFrame:
    """Consolidate individual test records into one row per athlete/date."""
    if not records:
        return pd.DataFrame()

    rows: dict[tuple[str, pd.Timestamp], dict[str, object]] = {}
    for record in records:
        athlete = str(record.get("Athlete", "")).strip().title()
        date = pd.to_datetime(record.get("Date"), errors="coerce")
        if not athlete or pd.isna(date):
            continue

        key = (athlete, date.normalize())
        row = rows.setdefault(key, {"Athlete": athlete, "Date": date.normalize()})
        for field, value in record.items():
            if (
                field in {"Athlete", "Date", "test_type"}
                or field.endswith("_reps")
                or field.startswith("__")
            ):
                continue
            if value is not None and not (isinstance(value, float) and np.isnan(value)):
                row[field] = value

    return _prepare_jump_df(pd.DataFrame(rows.values()))
