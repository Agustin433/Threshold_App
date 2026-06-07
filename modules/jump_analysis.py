"""Shared jump evaluation calculations and neuromuscular profiling."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from modules.data_loader import _normalize_legacy_imtp_rfd_aliases_frame

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
    "DRI": "DRI",
    "DJ_tc_ms": "Tiempo de contacto",
    "TC_inv_Z": "Tiempo de contacto",
    "IMTP_relPF": "IMTP relPF",
    "IMTP_N": "IMTP",
    "EUR": "EUR",
    "DSI": "DSI",
    "mRSI": "mRSI",
    "Jump_Momentum": "Jump Momentum",
    "CMJ_rel_impulse": "Impulso Relativo Propulsivo",
}

PRIMARY_PROFILE_SOURCE_COLUMNS = ("CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "IMTP_N")

VARIABLE_META: dict[str, dict[str, object]] = {
    "CMJ_cm": {
        "label": "CMJ",
        "higher_is_better": True,
        "fallback_pct": 1.5,
        "fmt": "{:.1f}",
        "enabled_default": True,
    },
    "SJ_cm": {
        "label": "SJ",
        "higher_is_better": True,
        "fallback_pct": 1.5,
        "fmt": "{:.1f}",
        "enabled_default": True,
    },
    "DJ_cm": {
        "label": "DJ",
        "higher_is_better": True,
        "fallback_pct": 1.5,
        "fmt": "{:.1f}",
        "enabled_default": True,
    },
    "DJ_RSI": {
        "label": "DJ RSI",
        "higher_is_better": True,
        "fallback_pct": 2.0,
        "fmt": "{:.2f}",
        "enabled_default": True,
    },
    "DJ_tc_ms": {
        "label": "Tiempo de contacto",
        "higher_is_better": False,
        "fallback_pct": 2.0,
        "fmt": "{:.0f}",
        "enabled_default": True,
    },
    "IMTP_N": {
        "label": "IMTP",
        "higher_is_better": True,
        "fallback_pct": 2.0,
        "fmt": "{:.0f}",
        "enabled_default": True,
    },
    "IMTP_relPF": {
        "label": "IMTP relPF",
        "higher_is_better": True,
        "fallback_pct": 2.0,
        "fmt": "{:.2f}",
        "enabled_default": True,
    },
    "EUR": {
        "label": "EUR (ratio)",
        "higher_is_better": True,
        "fallback_pct": 2.0,
        "fmt": "{:.3f}",
        "enabled_default": True,
    },
    "DSI": {
        "label": "DSI",
        "higher_is_better": True,
        "fallback_pct": 3.0,
        "fmt": "{:.2f}",
        "enabled_default": False,
    },
    "CMJ_rel_impulse": {
        "label": "Impulso Relativo Propulsivo",
        "higher_is_better": True,
        "fallback_pct": 2.0,
        "fmt": "{:.2f}",
        "enabled_default": False,
    },
}

TEMPORAL_SIGNAL_BADGES = {
    "mejora relevante": "↑ mejora relevante",
    "caida relevante": "↓ caida relevante",
    "sin cambio relevante": "~ sin cambio relevante",
    "sin dato anterior": "— sin dato anterior",
}

BASELINE_MIN_VALID = 3
BASELINE_METHOD = "Promedio primeras 3 mediciones validas"
BASELINE_SIGNAL_BADGES = {
    "mejora vs baseline": "+ mejora vs baseline",
    "caida vs baseline": "- caida vs baseline",
    "sin cambio vs baseline": "~ sin cambio vs baseline",
    "baseline insuficiente": "baseline insuficiente",
    "sin dato actual": "sin dato actual",
}

SEMAPHORE_LABELS = (
    (1.0, "Verde"),
    (0.0, "Amarillo"),
    (-1.0, "Naranja"),
    (-math.inf, "Rojo"),
)

PATTERN_LIBRARY = {
    "A": {
        "label": "Patron A - Fuerza/propulsion con SSC rapido limitado",
        "phys": "Buena capacidad concentrica y techo de fuerza aceptable, menor expresion en SSC rapido.",
        "bio": "Mayor tiempo de construccion de impulso en ventanas de contacto breves.",
        "train": "Fast SSC, stiffness util, pogos, drop jumps dosificados, sprints cortos, fuerza con intencion alta y bajo lastre.",
        "summary_short": "Buen perfil concentrico con rezago reactivo rapido.",
        "summary_athlete": "Tenes una base concentrica util, pero hoy la reaccion rapida en contactos breves aparece mas limitada.",
        "summary_client": "Hay una base de fuerza/propulsion util, con margen para mejorar la reaccion rapida y la calidad de contacto.",
        "summary_professional": "Se observa buena salida concentrica con menor expresion del SSC rapido; conviene priorizar stiffness, contacto y transferencia reactiva.",
        "kpi_to_track": ["DJ_RSI", "DJ_tc_ms", "DRI"],
    },
    "B": {
        "label": "Patron B - Reactivo con techo de fuerza bajo",
        "phys": "Buena reutilizacion de energia elastica en SSC rapido, con techo de fuerza concentrica limitado.",
        "bio": "Alta rigidez muscular funcional pero menor capacidad propulsiva maxima en saltos sin ciclo.",
        "train": "Trabajo de fuerza maxima y potencia concentrica, sentadilla pesada, hip thrust, saltos con carga.",
        "summary_short": "Buen componente reactivo con base concentrica limitada.",
        "summary_athlete": "Respondés bien en acciones rapidas, pero todavia falta mas base de fuerza para sostener mejor esa reaccion.",
        "summary_client": "La reactividad aparece bien expresada, aunque la base concentrica todavia puede crecer para darle mas sostén al perfil.",
        "summary_professional": "Hay buena eficiencia reactiva relativa, con menor techo de fuerza/propulsion concentrica; conviene priorizar fuerza maxima y transferencia vertical.",
        "kpi_to_track": ["SJ_cm", "CMJ_cm", "IMTP_relPF"],
    },
    "C": {
        "label": "Patron C - Salida vertical con deficit isometrico relativo",
        "phys": "Potencia explosiva presente con deficit de fuerza isometrica relativa. DSI probablemente elevado.",
        "bio": "Buena transferencia explosiva pero con menor base de fuerza maxima para sostenerla.",
        "train": "Fuerza maxima, IMTP-specific, isometricos en angulo de trabajo funcional.",
        "summary_short": "Salida explosiva presente con base isometrica relativa rezagada.",
        "summary_athlete": "Hoy mostras una buena salida explosiva, pero la base de fuerza isometrica relativa aparece por debajo de lo deseado.",
        "summary_client": "Hay una salida explosiva util, aunque la fuerza base relativa todavia parece corta para sostener mejor esa expresion.",
        "summary_professional": "La salida vertical se conserva, pero la fuerza isometrica relativa aparece rezagada; priorizar fuerza maxima e isometricos especificos.",
        "kpi_to_track": ["IMTP_relPF", "IMTP_N", "DSI"],
    },
    "D": {
        "label": "Patron D - Deficit neuromuscular global",
        "phys": "Deficit generalizado en capacidades neuromusculares evaluadas.",
        "bio": "Limitacion en produccion de fuerza, potencia y reutilizacion elastica.",
        "train": "Fase de acumulacion general. Priorizar fuerza basica antes de trabajo reactivo.",
        "summary_short": "Perfil globalmente por debajo de la referencia disponible.",
        "summary_athlete": "Hoy varias cualidades del perfil aparecen por debajo de la referencia, por lo que conviene reconstruir base antes de pedir mas complejidad.",
        "summary_client": "El perfil actual muestra un rezago global y pide consolidar bases antes de subir complejidad o densidad reactiva.",
        "summary_professional": "Los z-scores renderizables del radar quedan deprimidos en conjunto; conviene priorizar acumulacion general, fuerza basica y progresion reactiva conservadora.",
        "kpi_to_track": ["CMJ_cm", "SJ_cm", "DJ_RSI", "IMTP_relPF"],
    },
    "E": {
        "label": "Patron E - CMJ menor que SJ",
        "phys": "El CMJ no supera al SJ, lo que sugiere menor aprovechamiento del contramovimiento en este test.",
        "bio": "El SSC lento no esta agregando impulso util; conviene revisar tecnica, fatiga y estrategia de contramovimiento.",
        "train": "Revisar tecnica de CMJ, control de fatiga y progresion de SSC lento antes de escalar el trabajo reactivo.",
        "summary_short": "CMJ por debajo de SJ: alerta sobre uso ineficiente del contramovimiento.",
        "summary_athlete": "Hoy el salto con contramovimiento no mejora al SJ, asi que conviene revisar tecnica, fatiga y calidad del gesto antes de exigir mas reactividad.",
        "summary_client": "El uso del contramovimiento aparece ineficiente en esta medicion; conviene validar tecnica, contexto y fatiga antes de sacar conclusiones fuertes.",
        "summary_professional": "CMJ < SJ sugiere una señal anomala o un deficit del SSC lento; confirmar tecnica, familiarizacion, fatiga y coherencia con el resto del bloque.",
        "kpi_to_track": ["EUR", "CMJ_cm", "SJ_cm", "DJ_RSI"],
        "note": "Nota: CMJ < SJ. El atleta no aprovecha eficientemente el ciclo estiramiento-acortamiento en este test. Revisar fatiga acumulada, tecnica de CMJ o deficit especifico de SSC lento.",
        "bio_dj_rsi_high": "Buena rigidez muscular funcional en SSC rapido, pero el CMJ < SJ indica que el ciclo de estiramiento no esta potenciando el salto con contramovimiento. Posible dominancia reactiva con limitacion en SSC lento.",
        "bio_sj_high": "Buena capacidad concentrica en SJ, pero el CMJ no supera al SJ, lo que indica que el contramovimiento no genera impulso adicional util. Revisar tecnica, fatiga o deficit de stiffness en SSC lento.",
    },
}

NEUROMUSCULAR_PATTERN_FIELDS = (
    "label",
    "phys",
    "bio",
    "train",
    "summary_short",
    "summary_athlete",
    "summary_client",
    "summary_professional",
    "kpi_to_track",
)

RADAR_FULL_AXES = (
    ("SJ", "SJ_cm", "cm", "SJ_Z"),
    ("CMJ", "CMJ_cm", "cm", "CMJ_Z"),
    ("DJ height", "DJ_cm", "cm", "DJ_height_Z"),
    ("DJ RSI", "DJ_RSI", "m/s", "DJ_RSI_Z"),
    ("Tiempo de contacto", "DJ_tc_ms", "ms", "TC_inv_Z"),
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

COMPOSITE_PROFILE_METRICS = (
    ("SJ", "SJ_cm", "cm", "SJ_Z", 1),
    ("CMJ", "CMJ_cm", "cm", "CMJ_Z", 1),
    ("DJ", "DJ_cm", "cm", "DJ_height_Z", 1),
    ("DRI", "DRI", "", "DRI_Z", 3),
    ("Tiempo de contacto", "DJ_tc_ms", "ms", "TC_inv_Z", 0),
    ("EUR", "EUR", "ratio", "EUR_Z", 3),
    ("IMTP", "IMTP_relPF", "N/kg", "IMTP_relPF_Z", 2),
)

COMPOSITE_PROFILE_DIRECTIONS = {
    "SJ_cm": "higher_is_better",
    "CMJ_cm": "higher_is_better",
    "DJ_cm": "higher_is_better",
    "DRI": "higher_is_better",
    "DJ_tc_ms": "lower_is_better_inverted_z",
    "EUR": "context_dependent",
    "IMTP_relPF": "higher_is_better",
    "IMTP_N": "higher_is_better",
}

ZSCORE_ALIAS_GROUPS = (
    ("DJ_height_Z", "DJ_Z"),
    ("TC_inv_Z", "DJtc_Z"),
    ("IMTP_relPF_Z", "IMTP_Z"),
)

COMPOSITE_PROFILE_SUPPORT_FIELDS = (
    "DJ_drop_height_cm",
    "DJ_RSI",
    "DJ_RSI_Z",
    "TC_inv_Z",
    "DSI",
    "mRSI",
    "TTT_s",
    "TTT_ms",
    "Jump_Momentum",
    "Jump_Momentum_Z",
    "CMJ_rel_impulse",
    "CMJ_rel_impulse_Z",
    "IMTP_N",
    "BW_kg",
)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _coalesced_numeric_value(row: pd.Series | dict[str, object], *columns: str) -> float | None:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    for column in columns:
        value = pd.to_numeric(pd.Series([row_series.get(column)]), errors="coerce").iloc[0]
        if pd.notna(value):
            return float(value)
    return None


def _coalesced_numeric_series(frame: pd.DataFrame, *columns: str) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for column in columns:
        if column not in frame.columns:
            continue
        result = result.combine_first(pd.to_numeric(frame[column], errors="coerce"))
    return result.astype(float)


def _zscore_aliases(z_col: str) -> tuple[str, ...]:
    canonical = z_col
    for group in ZSCORE_ALIAS_GROUPS:
        if z_col in group:
            canonical = group[0]
            break
    aliases = [canonical]
    for group in ZSCORE_ALIAS_GROUPS:
        if canonical == group[0]:
            aliases.extend(column for column in group[1:])
            break
    return tuple(dict.fromkeys(aliases))


def resolve_zscore(row: pd.Series | dict[str, object], canonical_field: str) -> float | None:
    """Resolve a canonical z-score from the current field or approved legacy aliases."""
    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    return _coalesced_numeric_value(row_series, *_zscore_aliases(str(canonical_field)))


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


def promote_legacy_dri_to_dj_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Move legacy DRI values into DJ_RSI when no drop-height context exists."""
    legacy_dri = _numeric_series(df, "DRI")
    dj_rsi = _numeric_series(df, "DJ_RSI")
    drop_height_cm = _numeric_series(df, "DJ_drop_height_cm")
    legacy_mask = dj_rsi.isna() & legacy_dri.notna() & (drop_height_cm.isna() | (drop_height_cm <= 0))
    if legacy_mask.any():
        df.loc[legacy_mask, "DJ_RSI"] = legacy_dri.loc[legacy_mask].round(3)
    return df


def calc_dj_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical DJ RSI in m/s using jump height (m) / contact time (s)."""
    if {"DJ_cm", "DJ_tc_ms"}.issubset(df.columns):
        dj_height_m = _numeric_series(df, "DJ_cm") / 100
        dj_tc_s = _numeric_series(df, "DJ_tc_ms") / 1000
        mask = dj_height_m.notna() & dj_tc_s.notna() & (dj_tc_s > 0)
        df.loc[mask, "DJ_RSI"] = (dj_height_m.loc[mask] / dj_tc_s.loc[mask]).round(3)
    return df


def calc_dri(df: pd.DataFrame) -> pd.DataFrame:
    """DRI 2026 using drop height + jump height over gravity and contact time squared."""
    existing_dri = _numeric_series(df, "DRI").round(3)
    df["DRI"] = existing_dri
    dj_height_cm = _numeric_series(df, "DJ_cm")
    dj_tc_ms = _numeric_series(df, "DJ_tc_ms")
    raw_dj_mask = dj_height_cm.notna() & dj_tc_ms.notna()
    if raw_dj_mask.any():
        df.loc[raw_dj_mask, "DRI"] = np.nan
    if {"DJ_drop_height_cm", "DJ_cm", "DJ_tc_ms"}.issubset(df.columns):
        drop_height_m = _numeric_series(df, "DJ_drop_height_cm") / 100
        dj_height_m = dj_height_cm / 100
        dj_tc_s = dj_tc_ms / 1000
        mask = (
            drop_height_m.notna()
            & (drop_height_m > 0)
            & dj_height_m.notna()
            & dj_tc_s.notna()
            & (dj_tc_s > 0)
        )
        df.loc[mask, "DRI"] = (
            (drop_height_m.loc[mask] + dj_height_m.loc[mask])
            / (EARTH_GRAVITY * (dj_tc_s.loc[mask] ** 2))
        ).round(3)
    return df


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
        ("DRI", "DRI_Z", None, False),
        ("DJ_tc_ms", "TC_inv_Z", None, True),
        ("IMTP_relPF", "IMTP_relPF_Z", "IMTP_relPF", False),
        ("mRSI", "mRSI_Z", "mRSI", False),
        ("Jump_Momentum", "Jump_Momentum_Z", None, False),
        ("EUR", "EUR_Z", None, False),
        ("DSI", "DSI_Z", None, False),
        ("IMTP_N", "IMTP_N_Z", "IMTP_N", False),
    )

    for metric_col, z_col, benchmark_key, invert in zscore_specs:
        computed_z = _resolve_zscore(
            df,
            metric_col,
            benchmark_key=benchmark_key,
            invert=invert,
        )
        df[z_col] = computed_z.combine_first(_coalesced_numeric_series(df, z_col)).round(2)

    computed_rel_impulse_z = _resolve_zscore(
        df,
        "CMJ_rel_impulse",
        internal_min_count=3,
        allow_dataset_fallback=False,
    )
    df["CMJ_rel_impulse_Z"] = computed_rel_impulse_z.combine_first(
        _coalesced_numeric_series(df, "CMJ_rel_impulse_Z")
    ).round(2)

    # Backward-compatible aliases used elsewhere in the app/reporting.
    for primary_col, alias_col in ZSCORE_ALIAS_GROUPS:
        primary = _coalesced_numeric_series(df, primary_col, alias_col).round(2)
        alias = _coalesced_numeric_series(df, alias_col, primary_col).round(2)
        df[primary_col] = primary
        df[alias_col] = alias
    if "DRI_Z" in df.columns:
        df.loc[_numeric_series(df, "DRI").isna(), "DRI_Z"] = np.nan
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
    sj_z = resolve_zscore(row, "SJ_Z")
    dj_rsi_z = resolve_zscore(row, "DJ_RSI_Z")
    cmj_z = resolve_zscore(row, "CMJ_Z")
    imtp_relpf_z = resolve_zscore(row, "IMTP_relPF_Z")
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
        resolve_zscore(row, col)
        for col in radar_z_cols
    ]
    radar_values = [value for value in radar_values if pd.notna(value)]
    if radar_values and all(value < -0.5 for value in radar_values):
        patterns.append("D")
    if pd.notna(eur) and eur < 1.00:
        patterns.append("E")
    return patterns


def _pattern_text(row: pd.Series, pattern_code: str, field: str) -> str:
    payload = PATTERN_LIBRARY.get(pattern_code, {})
    if pattern_code != "E" or field != "bio":
        return str(payload.get(field, "")).strip()

    dj_rsi_z = resolve_zscore(row, "DJ_RSI_Z")
    sj_z = resolve_zscore(row, "SJ_Z")
    if dj_rsi_z is not None and dj_rsi_z > 0.5:
        return str(payload.get("bio_dj_rsi_high") or payload.get("bio", "")).strip()
    if sj_z is not None and sj_z > 0.5:
        return str(payload.get("bio_sj_high") or payload.get("bio", "")).strip()
    return str(payload.get("bio", "")).strip()


def _merge_unique_texts(values: list[str]) -> str:
    return " ".join(dict.fromkeys(value.strip() for value in values if str(value or "").strip()))


def _composite_metric_display_spec(
    row_series: pd.Series,
    value_col: str,
    unit: str,
    z_col: str,
    digits: int,
) -> dict[str, object]:
    display_value_col = value_col
    display_unit = unit
    display_z_col = z_col
    display_digits = digits
    if value_col == "IMTP_relPF":
        relpf_value = pd.to_numeric(pd.Series([row_series.get("IMTP_relPF")]), errors="coerce").iloc[0]
        imtp_value = pd.to_numeric(pd.Series([row_series.get("IMTP_N")]), errors="coerce").iloc[0]
        if pd.isna(relpf_value) and pd.notna(imtp_value):
            display_value_col = "IMTP_N"
            display_unit = "N"
            display_z_col = "IMTP_N_Z"
            display_digits = 0
    return {
        "value_col": display_value_col,
        "unit": display_unit,
        "z_col": display_z_col,
        "digits": display_digits,
    }


def _build_pattern_evidence(row: pd.Series, patterns: list[str]) -> list[str]:
    evidence: list[str] = []
    if "A" in patterns:
        evidence.extend(["SJ_Z alto", "DJ_RSI_Z bajo"])
    if "B" in patterns:
        evidence.extend(["SJ_Z bajo", "DJ_RSI_Z alto"])
    if "C" in patterns:
        evidence.extend(["IMTP_relPF_Z bajo", "CMJ_Z conservado"])
    if "D" in patterns:
        evidence.append("todos los z-scores renderizables del radar por debajo de -0.5")
    if "E" in patterns:
        if _coalesced_numeric_value(row, "EUR") is not None and float(_coalesced_numeric_value(row, "EUR")) < 1.0:
            evidence.append("EUR bajo")
        cmj = _coalesced_numeric_value(row, "CMJ_cm")
        sj = _coalesced_numeric_value(row, "SJ_cm")
        if cmj is not None and sj is not None and cmj < sj:
            evidence.append("CMJ menor que SJ")
    return list(dict.fromkeys(evidence))


def _default_neuromuscular_result() -> dict[str, object]:
    return {
        "profile_code": "UNCLASSIFIED",
        "profile_label": "Sin patron dominante",
        "confidence": "low",
        "phys": "Perfil equilibrado en los indices disponibles.",
        "bio": "Sin deficits biomecanicos marcados en los tests disponibles.",
        "train": "Continuar progresion planificada y completar la bateria faltante si hiciera falta.",
        "summary_short": "Sin patron dominante con las reglas actuales.",
        "summary_athlete": "Hoy no aparece un patron dominante con las reglas actuales; conviene completar o repetir mediciones antes de cambiar demasiado el foco.",
        "summary_client": "No aparece un patron dominante con las reglas actuales; la lectura debe tomarse con cautela y conviene completar mediciones clave.",
        "summary_professional": "La evidencia disponible no alcanza para clasificar un patron dominante con las reglas actuales; conviene completar variables clave y releer el contexto del test.",
        "metrics": {},
        "flags": [],
        "evidence": [],
        "kpi_to_track": [],
    }


def build_neuromuscular_profile_result(
    row,
    reference_df: pd.DataFrame | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a structured neuromuscular interpretation for a single row.

    The current implementation keeps the existing A/B/C/D/E pattern rules and
    output semantics stable. ``reference_df`` and ``context`` are reserved for
    future extensions and are accepted for compatibility with the planned API.
    """

    del reference_df, context

    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    result = _default_neuromuscular_result()

    metrics: dict[str, dict[str, object]] = {}
    for label, value_col, unit, z_col, digits in COMPOSITE_PROFILE_METRICS:
        display_spec = _composite_metric_display_spec(row_series, value_col, unit, z_col, digits)
        display_value_col = str(display_spec["value_col"])
        display_z_col = str(display_spec["z_col"])
        value = _coalesced_numeric_value(row_series, display_value_col)
        z_value = resolve_zscore(row_series, display_z_col)
        source_date = (
            row_series.get(f"{display_value_col}__source_date")
            or row_series.get(f"{value_col}__source_date")
            or "-"
        )
        metrics[value_col] = {
            "label": label,
            "value": value,
            "unit": str(display_spec["unit"]),
            "z_score": z_value,
            "direction": COMPOSITE_PROFILE_DIRECTIONS.get(display_value_col, "higher_is_better"),
            "semaphore": semaphore_label(z_value),
            "value_col": display_value_col,
            "z_col": display_z_col,
            "z_aliases": list(_zscore_aliases(display_z_col)),
            "source_date": source_date,
            "available": value is not None,
        }
    result["metrics"] = metrics

    flags: list[str] = []
    imtp_value = _coalesced_numeric_value(row_series, "IMTP_relPF", "IMTP_N")
    imtp_z = resolve_zscore(row_series, "IMTP_relPF_Z")
    if imtp_z is None:
        imtp_z = _coalesced_numeric_value(row_series, "IMTP_N_Z")
    if imtp_value is None or imtp_z is None:
        flags.append("missing_imtp")

    dj_required = (
        _coalesced_numeric_value(row_series, "DJ_RSI"),
        _coalesced_numeric_value(row_series, "DJ_tc_ms"),
        _coalesced_numeric_value(row_series, "DJ_cm"),
    )
    if any(value is None for value in dj_required):
        flags.append("missing_dj")

    eur = _coalesced_numeric_value(row_series, "EUR")
    cmj = _coalesced_numeric_value(row_series, "CMJ_cm")
    sj = _coalesced_numeric_value(row_series, "SJ_cm")
    if (eur is not None and eur < 1.00) or (cmj is not None and sj is not None and cmj < sj):
        flags.append("cmj_lower_than_sj")

    patterns = _pattern_matches(row_series)
    if not patterns:
        flags.append("insufficient_pattern_evidence")

    result["flags"] = flags
    result["evidence"] = _build_pattern_evidence(row_series, patterns)

    if patterns:
        payloads = [PATTERN_LIBRARY[code] for code in patterns if code in PATTERN_LIBRARY]
        result["profile_code"] = "+".join(patterns)
        result["profile_label"] = " + ".join(
            dict.fromkeys(str(payload.get("label", f"Patron {code}")).strip() for code, payload in zip(patterns, payloads))
        )
        result["phys"] = _merge_unique_texts([str(payload.get("phys", "")).strip() for payload in payloads])
        result["bio"] = _merge_unique_texts([_pattern_text(row_series, code, "bio") for code in patterns])
        result["train"] = _merge_unique_texts([str(payload.get("train", "")).strip() for payload in payloads])
        result["summary_short"] = _merge_unique_texts([str(payload.get("summary_short", "")).strip() for payload in payloads])
        result["summary_athlete"] = _merge_unique_texts([str(payload.get("summary_athlete", "")).strip() for payload in payloads])
        result["summary_client"] = _merge_unique_texts([str(payload.get("summary_client", "")).strip() for payload in payloads])
        result["summary_professional"] = _merge_unique_texts(
            [str(payload.get("summary_professional", "")).strip() for payload in payloads]
        )
        result["kpi_to_track"] = list(
            dict.fromkeys(
                metric
                for payload in payloads
                for metric in payload.get("kpi_to_track", [])
                if str(metric).strip()
            )
        )

    if "missing_imtp" in flags:
        result["kpi_to_track"] = list(dict.fromkeys([*result["kpi_to_track"], "IMTP_relPF"]))
    if "missing_dj" in flags:
        result["kpi_to_track"] = list(dict.fromkeys([*result["kpi_to_track"], "DJ_cm", "DJ_RSI", "DJ_tc_ms"]))
    if not result["kpi_to_track"]:
        result["kpi_to_track"] = ["CMJ_cm", "SJ_cm", "EUR", "DJ_RSI", "IMTP_relPF"]

    if "insufficient_pattern_evidence" in flags or "cmj_lower_than_sj" in flags or "E" in patterns:
        result["confidence"] = "low"
    elif "missing_imtp" in flags and "missing_dj" in flags:
        result["confidence"] = "low"
    elif "missing_imtp" in flags or "missing_dj" in flags:
        result["confidence"] = "moderate"
    else:
        result["confidence"] = "high"

    return result


_DASHBOARD_CONFIDENCE_LABELS = {
    "high": "alta",
    "moderate": "moderada",
    "low": "baja",
}

_DASHBOARD_STRUCTURED_FLAG_MAP = {
    "missing_imtp": {"level": "gray", "text": "IMTP pendiente"},
    "missing_dj": {"level": "gray", "text": "DJ pendiente"},
    "cmj_lower_than_sj": {"level": "red", "text": "CMJ < SJ"},
    "insufficient_pattern_evidence": {"level": "yellow", "text": "Perfil parcial"},
}


def _dashboard_profile_metric_value(profile_payload: dict[str, object]) -> str:
    profile_code = str(profile_payload.get("profile_code") or "").strip()
    if not profile_code or profile_code == "UNCLASSIFIED":
        return "Sin patron"
    return f"Patron {profile_code}"


def _dashboard_signal_summary(row_series: pd.Series) -> tuple[list[str], list[str]]:
    axes, _ = _available_radar_axes(row_series)
    high_values: list[str] = []
    low_values: list[str] = []

    for label, _, _, z_col in axes:
        z_value = _coalesced_numeric_value(row_series, z_col, *_zscore_aliases(z_col))
        if z_value is None:
            continue
        if z_value > 0.5:
            high_values.append(f"{label} ({z_value:+.2f})")
        elif z_value < -0.5:
            low_values.append(f"{label} ({z_value:+.2f})")

    return high_values, low_values


def _dashboard_structured_flag_rows(profile_payload: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    profile_value = _dashboard_profile_metric_value(profile_payload)
    confidence = str(profile_payload.get("confidence") or "low").strip().lower()
    rows.append(
        {
            "level": {"high": "green", "moderate": "yellow"}.get(confidence, "gray"),
            "text": f"Perfil: {profile_value}",
        }
    )

    for flag in profile_payload.get("flags", []):
        flag_key = str(flag).strip()
        if flag_key == "insufficient_pattern_evidence" and profile_payload.get("profile_code") != "UNCLASSIFIED":
            continue
        mapped = _DASHBOARD_STRUCTURED_FLAG_MAP.get(flag_key)
        if mapped:
            rows.append(dict(mapped))

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("level") or ""), str(row.get("text") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_dashboard_neuromuscular_payload(
    row,
    reference_df: pd.DataFrame | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    core_context = dict(context or {})
    core_context.setdefault("audience", "dashboard")

    try:
        profile_payload = build_neuromuscular_profile_result(
            row_series,
            reference_df=reference_df,
            context=core_context,
        )
        core_available = isinstance(profile_payload, dict)
    except Exception:
        profile_payload = {}
        core_available = False

    if not core_available:
        return {
            "source": "legacy_fallback",
            "profile_code": "UNCLASSIFIED",
            "profile_label": "Sin patron dominante",
            "confidence": "low",
            "confidence_label": _DASHBOARD_CONFIDENCE_LABELS["low"],
            "summary_short": "Sin patron dominante con las reglas actuales.",
            "phys": "",
            "bio": "",
            "train": "",
            "metrics": {},
            "flags": [],
            "evidence": [],
            "kpi_to_track": [],
            "profile_metric_value": "Sin patron",
            "flag_rows": build_jump_flag_rows(row_series),
            "feedback_lines": build_jump_feedback_lines(row_series),
        }

    high_values, low_values = _dashboard_signal_summary(row_series)
    confidence = str(profile_payload.get("confidence") or "low").strip().lower()
    payload = dict(profile_payload)
    payload["source"] = "core"
    payload["confidence_label"] = _DASHBOARD_CONFIDENCE_LABELS.get(confidence, _DASHBOARD_CONFIDENCE_LABELS["low"])
    payload["profile_metric_value"] = _dashboard_profile_metric_value(profile_payload)
    payload["flag_rows"] = [*build_jump_flag_rows(row_series), *_dashboard_structured_flag_rows(profile_payload)]
    payload["feedback_lines"] = [
        f"Perfil: {profile_payload.get('profile_label', 'Sin patron dominante')} (confianza {payload['confidence_label']})",
        f"Alto: {', '.join(high_values) if high_values else 'sin variables > 0.5.'}",
        f"Bajo: {', '.join(low_values) if low_values else 'sin variables < -0.5.'}",
        f"Fisiologico: {str(profile_payload.get('phys') or '').strip()}",
        f"Biomecanico: {str(profile_payload.get('bio') or '').strip()}",
        f"Proximo bloque: {str(profile_payload.get('train') or '').strip()}",
    ]
    return payload


def build_jump_feedback_lines(row: pd.Series | dict[str, object]) -> list[str]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    axes, _ = _available_radar_axes(row_series)
    high_values: list[str] = []
    low_values: list[str] = []

    for label, _, _, z_col in axes:
        z_value = resolve_zscore(row_series, z_col)
        if z_value is None or pd.isna(z_value):
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


def _default_temporal_variables(athlete_df: pd.DataFrame, variables: list[str] | None = None) -> list[str]:
    if variables is not None:
        return [variable for variable in variables if variable in athlete_df.columns]

    ordered = [
        variable
        for variable, meta in VARIABLE_META.items()
        if meta.get("enabled_default", False)
    ]
    optional = ["DSI", "CMJ_rel_impulse"]
    selected = [variable for variable in ordered if variable in athlete_df.columns]
    for variable in optional:
        if variable in athlete_df.columns and athlete_df[variable].notna().any():
            selected.append(variable)
    return selected


def compute_swc_delta(
    athlete_df: pd.DataFrame,
    current_date,
    variables: list[str] | None = None,
) -> pd.DataFrame:
    columns = [
        "Variable",
        "Label",
        "Valor_actual",
        "Valor_anterior",
        "Fecha_actual",
        "Fecha_anterior",
        "Delta_abs",
        "Delta_pct",
        "Threshold_abs",
        "Threshold_method",
        "N_valid",
        "Signal",
        "Higher_is_better",
    ]
    if athlete_df is None or athlete_df.empty or "Date" not in athlete_df.columns:
        return pd.DataFrame(columns=columns)

    working_df = athlete_df.copy()
    working_df["Date"] = pd.to_datetime(working_df["Date"], errors="coerce").dt.normalize()
    current_ts = pd.Timestamp(current_date).normalize()
    working_df = working_df[working_df["Date"].notna() & (working_df["Date"] <= current_ts)].sort_values("Date")
    if working_df.empty:
        return pd.DataFrame(columns=columns)

    current_rows = working_df[working_df["Date"] == current_ts].sort_values("Date")
    current_row = current_rows.iloc[-1] if not current_rows.empty else working_df.iloc[-1]
    current_row_date = pd.Timestamp(current_row["Date"]).normalize()

    selected_variables = _default_temporal_variables(working_df, variables=variables)
    rows: list[dict[str, object]] = []
    for variable in selected_variables:
        if variable not in VARIABLE_META or variable not in working_df.columns:
            continue

        meta = VARIABLE_META[variable]
        series = pd.to_numeric(working_df[variable], errors="coerce")
        valid_rows = working_df.loc[series.notna(), ["Date"]].copy()
        valid_rows[variable] = series.loc[series.notna()].values
        if valid_rows.empty:
            continue

        current_value = pd.to_numeric(pd.Series([current_row.get(variable)]), errors="coerce").iloc[0]
        previous_rows = valid_rows[valid_rows["Date"] < current_row_date].sort_values("Date")
        previous_value = pd.to_numeric(previous_rows[variable], errors="coerce").iloc[-1] if not previous_rows.empty else np.nan
        previous_date = previous_rows["Date"].iloc[-1] if not previous_rows.empty else pd.NaT
        valid_until_current = valid_rows[valid_rows["Date"] <= current_row_date]
        n_valid = int(len(valid_until_current))

        delta_abs = np.nan
        delta_pct = np.nan
        threshold_abs = np.nan
        threshold_method = pd.NA
        signal = "sin dato anterior"

        if pd.notna(current_value) and pd.notna(previous_value):
            delta_abs = float(current_value) - float(previous_value)
            if float(previous_value) > 0:
                delta_pct = ((float(current_value) - float(previous_value)) / float(previous_value)) * 100

            if n_valid >= 3:
                std_value = pd.to_numeric(valid_until_current[variable], errors="coerce").std()
                if pd.notna(std_value):
                    threshold_abs = abs(0.2 * float(std_value))
                    threshold_method = "Hopkins"
            elif float(previous_value) > 0:
                threshold_abs = abs(float(previous_value) * (float(meta["fallback_pct"]) / 100))
                threshold_method = "Fijo"

            if pd.notna(threshold_abs):
                threshold_abs = float(threshold_abs)
                if bool(meta["higher_is_better"]):
                    if delta_abs > threshold_abs:
                        signal = "mejora relevante"
                    elif delta_abs < -threshold_abs:
                        signal = "caida relevante"
                    else:
                        signal = "sin cambio relevante"
                else:
                    if delta_abs < -threshold_abs:
                        signal = "mejora relevante"
                    elif delta_abs > threshold_abs:
                        signal = "caida relevante"
                    else:
                        signal = "sin cambio relevante"

        rows.append(
            {
                "Variable": variable,
                "Label": str(meta["label"]),
                "Valor_actual": float(current_value) if pd.notna(current_value) else np.nan,
                "Valor_anterior": float(previous_value) if pd.notna(previous_value) else np.nan,
                "Fecha_actual": current_row_date,
                "Fecha_anterior": pd.Timestamp(previous_date).normalize() if pd.notna(previous_date) else pd.NaT,
                "Delta_abs": float(delta_abs) if pd.notna(delta_abs) else np.nan,
                "Delta_pct": float(delta_pct) if pd.notna(delta_pct) else np.nan,
                "Threshold_abs": float(threshold_abs) if pd.notna(threshold_abs) else np.nan,
                "Threshold_method": threshold_method,
                "N_valid": n_valid,
                "Signal": signal,
                "Higher_is_better": bool(meta["higher_is_better"]),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def build_jump_temporal_context(delta_df: pd.DataFrame) -> list[str]:
    if delta_df is None or delta_df.empty or "Signal" not in delta_df.columns:
        return []

    comparable = delta_df[delta_df["Signal"] != "sin dato anterior"].copy()
    if comparable.empty:
        return []

    lines: list[str] = []
    improvements = comparable[comparable["Signal"] == "mejora relevante"]
    declines = comparable[comparable["Signal"] == "caida relevante"]

    if not improvements.empty:
        improvement_date = pd.to_datetime(improvements["Fecha_anterior"], errors="coerce").dropna().max()
        improvement_vars = ", ".join(improvements["Label"].dropna().astype(str).unique().tolist())
        if pd.notna(improvement_date):
            lines.append(
                f"Respecto a la evaluacion anterior ({pd.Timestamp(improvement_date).strftime('%d/%m/%Y')}): mejora relevante en {improvement_vars}."
            )
        else:
            lines.append(f"Respecto a la evaluacion anterior: mejora relevante en {improvement_vars}.")

    if not declines.empty:
        decline_date = pd.to_datetime(declines["Fecha_anterior"], errors="coerce").dropna().max()
        decline_vars = ", ".join(declines["Label"].dropna().astype(str).unique().tolist())
        if pd.notna(decline_date):
            lines.append(
                f"Respecto a la evaluacion anterior ({pd.Timestamp(decline_date).strftime('%d/%m/%Y')}): caida relevante en {decline_vars}. Revisar contexto de carga previa."
            )
        else:
            lines.append(f"Respecto a la evaluacion anterior: caida relevante en {decline_vars}. Revisar contexto de carga previa.")

    if declines.empty and improvements.empty and comparable["Signal"].eq("sin cambio relevante").all():
        lines.append("Cambios sin relevancia practica respecto a la evaluacion anterior. Continuar seguimiento.")

    return lines


def build_jump_delta_display_table(delta_df: pd.DataFrame) -> pd.DataFrame:
    if delta_df is None or delta_df.empty:
        return pd.DataFrame(columns=["Variable", "Actual", "Anterior", "Delta abs", "Delta %", "Threshold", "Senal"])

    rows: list[dict[str, object]] = []
    for _, row in delta_df.iterrows():
        meta = VARIABLE_META.get(str(row["Variable"]), {})
        formatter = meta.get("fmt", "{:.2f}")

        def _fmt_value(value) -> str:
            if value is None or pd.isna(value):
                return "-"
            return str(formatter).format(float(value))

        threshold_text = "-"
        threshold_value = row.get("Threshold_abs")
        threshold_method = row.get("Threshold_method")
        if pd.notna(threshold_value):
            threshold_text = _fmt_value(threshold_value)
            if threshold_method == "Hopkins":
                threshold_text = f"{threshold_text} (Hopkins, N={int(row.get('N_valid', 0))})"
            elif threshold_method == "Fijo":
                threshold_text = f"{threshold_text} (Fijo)"

        delta_pct = row.get("Delta_pct")
        delta_pct_text = f"{float(delta_pct):+.1f}%" if pd.notna(delta_pct) else "-"
        delta_abs = row.get("Delta_abs")
        delta_abs_text = _fmt_value(delta_abs) if pd.notna(delta_abs) else "-"
        if pd.notna(delta_abs):
            delta_abs_text = f"{float(delta_abs):+.{3 if row['Variable'] == 'EUR' else 2}f}".rstrip("0").rstrip(".")

        rows.append(
            {
                "Variable": row["Label"],
                "Actual": _fmt_value(row.get("Valor_actual")),
                "Anterior": _fmt_value(row.get("Valor_anterior")),
                "Delta abs": delta_abs_text,
                "Delta %": delta_pct_text,
                "Threshold": threshold_text,
                "Senal": TEMPORAL_SIGNAL_BADGES.get(str(row.get("Signal")), str(row.get("Signal", "-"))),
            }
        )

    return pd.DataFrame(rows, columns=["Variable", "Actual", "Anterior", "Delta abs", "Delta %", "Threshold", "Senal"])


def compute_baseline_delta(
    athlete_df: pd.DataFrame,
    current_date,
    variables: list[str] | None = None,
) -> pd.DataFrame:
    columns = [
        "Variable",
        "Label",
        "Valor_actual",
        "Baseline_value",
        "Fecha_actual",
        "Baseline_start_date",
        "Baseline_end_date",
        "Delta_abs",
        "Delta_pct",
        "Baseline_method",
        "N_valid",
        "Signal",
        "Higher_is_better",
    ]
    if athlete_df is None or athlete_df.empty or "Date" not in athlete_df.columns:
        return pd.DataFrame(columns=columns)

    working_df = athlete_df.copy()
    working_df["Date"] = pd.to_datetime(working_df["Date"], errors="coerce").dt.normalize()
    current_ts = pd.Timestamp(current_date).normalize()
    working_df = working_df[working_df["Date"].notna() & (working_df["Date"] <= current_ts)].sort_values("Date")
    if working_df.empty:
        return pd.DataFrame(columns=columns)

    current_rows = working_df[working_df["Date"] == current_ts].sort_values("Date")
    current_row = current_rows.iloc[-1] if not current_rows.empty else working_df.iloc[-1]
    current_row_date = pd.Timestamp(current_row["Date"]).normalize()
    selected_variables = _default_temporal_variables(working_df, variables=variables)

    rows: list[dict[str, object]] = []
    for variable in selected_variables:
        if variable not in VARIABLE_META or variable not in working_df.columns:
            continue

        meta = VARIABLE_META[variable]
        series = pd.to_numeric(working_df[variable], errors="coerce")
        valid_rows = working_df.loc[series.notna(), ["Date"]].copy()
        valid_rows[variable] = series.loc[series.notna()].values
        valid_rows = valid_rows[valid_rows["Date"] <= current_row_date].sort_values("Date")
        if valid_rows.empty:
            continue

        current_value = pd.to_numeric(pd.Series([current_row.get(variable)]), errors="coerce").iloc[0]
        n_valid = int(len(valid_rows))
        baseline_value = np.nan
        baseline_start_date = pd.NaT
        baseline_end_date = pd.NaT
        delta_abs = np.nan
        delta_pct = np.nan
        baseline_method = pd.NA
        signal = "baseline insuficiente"

        if n_valid >= BASELINE_MIN_VALID:
            baseline_rows = valid_rows.head(BASELINE_MIN_VALID)
            baseline_value = pd.to_numeric(baseline_rows[variable], errors="coerce").mean()
            baseline_start_date = baseline_rows["Date"].iloc[0]
            baseline_end_date = baseline_rows["Date"].iloc[-1]
            baseline_method = BASELINE_METHOD
            if pd.notna(current_value) and pd.notna(baseline_value):
                delta_abs = float(current_value) - float(baseline_value)
                if float(baseline_value) > 0:
                    delta_pct = (delta_abs / float(baseline_value)) * 100

                if bool(meta["higher_is_better"]):
                    if delta_abs > 0:
                        signal = "mejora vs baseline"
                    elif delta_abs < 0:
                        signal = "caida vs baseline"
                    else:
                        signal = "sin cambio vs baseline"
                else:
                    if delta_abs < 0:
                        signal = "mejora vs baseline"
                    elif delta_abs > 0:
                        signal = "caida vs baseline"
                    else:
                        signal = "sin cambio vs baseline"
            else:
                signal = "sin dato actual"

        rows.append(
            {
                "Variable": variable,
                "Label": str(meta["label"]),
                "Valor_actual": float(current_value) if pd.notna(current_value) else np.nan,
                "Baseline_value": float(baseline_value) if pd.notna(baseline_value) else np.nan,
                "Fecha_actual": current_row_date,
                "Baseline_start_date": pd.Timestamp(baseline_start_date).normalize() if pd.notna(baseline_start_date) else pd.NaT,
                "Baseline_end_date": pd.Timestamp(baseline_end_date).normalize() if pd.notna(baseline_end_date) else pd.NaT,
                "Delta_abs": float(delta_abs) if pd.notna(delta_abs) else np.nan,
                "Delta_pct": float(delta_pct) if pd.notna(delta_pct) else np.nan,
                "Baseline_method": baseline_method,
                "N_valid": n_valid,
                "Signal": signal,
                "Higher_is_better": bool(meta["higher_is_better"]),
            }
        )

    return pd.DataFrame(rows, columns=columns)


def build_jump_baseline_display_table(baseline_df: pd.DataFrame) -> pd.DataFrame:
    if baseline_df is None or baseline_df.empty:
        return pd.DataFrame(columns=["Variable", "Actual", "Baseline", "Delta abs", "Delta %", "Metodo", "Senal"])

    rows: list[dict[str, object]] = []
    for _, row in baseline_df.iterrows():
        meta = VARIABLE_META.get(str(row["Variable"]), {})
        formatter = meta.get("fmt", "{:.2f}")

        def _fmt_value(value) -> str:
            if value is None or pd.isna(value):
                return "-"
            return str(formatter).format(float(value))

        delta_pct = row.get("Delta_pct")
        delta_pct_text = f"{float(delta_pct):+.1f}%" if pd.notna(delta_pct) else "-"
        delta_abs = row.get("Delta_abs")
        delta_abs_text = "-"
        if pd.notna(delta_abs):
            delta_abs_text = f"{float(delta_abs):+.{3 if row['Variable'] == 'EUR' else 2}f}".rstrip("0").rstrip(".")

        baseline_method = row.get("Baseline_method")
        if pd.notna(baseline_method):
            start_date = pd.to_datetime(row.get("Baseline_start_date"), errors="coerce")
            end_date = pd.to_datetime(row.get("Baseline_end_date"), errors="coerce")
            date_range = ""
            if pd.notna(start_date) and pd.notna(end_date):
                date_range = f" ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})"
            method_text = f"Primeras 3{date_range}"
        else:
            method_text = f"Baseline insuficiente (N={int(row.get('N_valid', 0))}/{BASELINE_MIN_VALID})"

        rows.append(
            {
                "Variable": row["Label"],
                "Actual": _fmt_value(row.get("Valor_actual")),
                "Baseline": _fmt_value(row.get("Baseline_value")),
                "Delta abs": delta_abs_text,
                "Delta %": delta_pct_text,
                "Metodo": method_text,
                "Senal": BASELINE_SIGNAL_BADGES.get(str(row.get("Signal")), str(row.get("Signal", "-"))),
            }
        )

    return pd.DataFrame(rows, columns=["Variable", "Actual", "Baseline", "Delta abs", "Delta %", "Metodo", "Senal"])


def _format_profile_source_date(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else "-"


def _format_composite_metric_value(value: object, unit: str, digits: int) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "-"
    formatted = f"{float(numeric):.{digits}f}"
    return formatted if unit in {"", "ratio"} else f"{formatted} {unit}"


def _latest_valid_numeric_row(df: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce")
    valid = df.loc[values.notna()].copy()
    if valid.empty:
        return None
    if "Date" in valid.columns:
        valid["Date"] = pd.to_datetime(valid["Date"], errors="coerce")
        valid = valid.sort_values("Date", ascending=False)
    return valid.iloc[0]


def _latest_valid_numeric_source_row(
    df: pd.DataFrame,
    columns: tuple[str, ...],
) -> tuple[pd.Series, str] | None:
    best: tuple[pd.Series, str] | None = None
    best_key: tuple[int, int] | None = None

    for priority, column in enumerate(columns):
        row = _latest_valid_numeric_row(df, column)
        if row is None:
            continue
        parsed_date = pd.to_datetime(row.get("Date"), errors="coerce")
        date_key = int(parsed_date.value) if pd.notna(parsed_date) else -1
        candidate_key = (date_key, -priority)
        if best_key is None or candidate_key > best_key:
            best = (row, column)
            best_key = candidate_key

    return best


def row_has_primary_profile_data(row: pd.Series | dict[str, object]) -> bool:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    for column in PRIMARY_PROFILE_SOURCE_COLUMNS:
        numeric = pd.to_numeric(pd.Series([row_series.get(column)]), errors="coerce").iloc[0]
        if pd.notna(numeric):
            return True
    return False


def select_primary_profile_row(
    jump_df: pd.DataFrame,
    selected_date: object | None = None,
) -> pd.Series | None:
    data = _prepare_jump_df(jump_df)
    if data.empty:
        return None

    selected_timestamp = pd.to_datetime(selected_date, errors="coerce")
    if pd.notna(selected_timestamp) and "Date" in data.columns:
        same_day_rows = data.loc[data["Date"] == selected_timestamp.normalize()].copy()
        if not same_day_rows.empty:
            same_day_rows = same_day_rows.sort_values("Date", ascending=False)
            for _, row in same_day_rows.iterrows():
                if row_has_primary_profile_data(row):
                    return row

    if "Date" in data.columns:
        data = data.sort_values("Date", ascending=False)
    for _, row in data.iterrows():
        if row_has_primary_profile_data(row):
            return row
    return None


def build_composite_profile_snapshot(jump_df: pd.DataFrame) -> tuple[pd.Series | None, pd.DataFrame]:
    data = _prepare_jump_df(jump_df)
    if data.empty:
        return None, pd.DataFrame(columns=["Variable", "Fecha origen"])

    if "Date" in data.columns:
        data = data.sort_values("Date", ascending=False)

    athlete_name = None
    if "Athlete" in data.columns:
        athlete_candidates = data["Athlete"].dropna()
        athlete_name = athlete_candidates.iloc[0] if not athlete_candidates.empty else None

    snapshot: dict[str, object] = {
        "Athlete": athlete_name,
        "Profile_Composed": True,
    }
    source_rows: list[dict[str, object]] = []

    for label, value_col, _, z_col, _ in COMPOSITE_PROFILE_METRICS:
        source = (
            _latest_valid_numeric_source_row(data, ("IMTP_relPF", "IMTP_N"))
            if value_col == "IMTP_relPF"
            else _latest_valid_numeric_source_row(data, (value_col,))
        )
        if source is None:
            snapshot[f"{value_col}__source_date"] = "-"
            source_rows.append({"Variable": label, "Fecha origen": "-"})
            continue

        source_row, source_value_col = source
        source_date = _format_profile_source_date(source_row.get("Date"))
        source_z_col = "IMTP_N_Z" if source_value_col == "IMTP_N" else z_col
        snapshot[source_value_col] = source_row.get(source_value_col)
        resolved_source_z = (
            resolve_zscore(source_row, source_z_col)
            if source_z_col != "IMTP_N_Z"
            else _coalesced_numeric_value(source_row, "IMTP_N_Z")
        )
        snapshot[source_z_col] = resolved_source_z
        snapshot[f"{value_col}__source_date"] = source_date
        snapshot[f"{source_value_col}__source_date"] = source_date
        if value_col == "DJ_tc_ms":
            tc_z = resolve_zscore(source_row, "TC_inv_Z")
            snapshot["TC_inv_Z"] = tc_z
            snapshot["DJtc_Z"] = tc_z
        if value_col == "IMTP_relPF":
            snapshot["IMTP_N"] = source_row.get("IMTP_N")
            if source_value_col == "IMTP_relPF":
                imtp_z = resolve_zscore(source_row, "IMTP_relPF_Z")
                snapshot["IMTP_relPF_Z"] = imtp_z
                snapshot["IMTP_Z"] = imtp_z
            else:
                snapshot["IMTP_N_Z"] = _coalesced_numeric_value(source_row, "IMTP_N_Z")

        source_rows.append(
            {
                "Variable": label,
                "Fecha origen": source_date,
            }
        )

    for field in COMPOSITE_PROFILE_SUPPORT_FIELDS:
        if field in snapshot:
            continue
        source_row = _latest_valid_numeric_row(data, field)
        if source_row is not None:
            snapshot[field] = source_row.get(field)

    for primary_col, alias_col in ZSCORE_ALIAS_GROUPS:
        z_value = resolve_zscore(snapshot, primary_col)
        if z_value is None:
            continue
        snapshot[primary_col] = z_value
        snapshot[alias_col] = z_value

    snapshot_df = pd.DataFrame([snapshot])
    if "EUR" in snapshot_df.columns:
        snapshot_df = calc_nm_profile(snapshot_df)
    snapshot_row = snapshot_df.iloc[0]
    return snapshot_row, pd.DataFrame(source_rows, columns=["Variable", "Fecha origen"])


def _count_renderable_radar_axes(row: pd.Series | dict[str, object]) -> int:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    axes, _ = _available_radar_axes(row_series)
    renderable = 0
    for _, _, _, z_col in axes:
        z_value = resolve_zscore(row_series, z_col)
        if z_value is not None and pd.notna(z_value):
            renderable += 1
    return renderable


def build_profile_radar_row(jump_df: pd.DataFrame) -> pd.Series | None:
    """Choose the safest radar row, upgrading to a composed snapshot only when it adds axes."""
    data = _prepare_jump_df(jump_df)
    if data.empty:
        return None

    if "Date" in data.columns:
        data = data.sort_values("Date")
    latest_row = data.iloc[-1]

    composite_row, _ = build_composite_profile_snapshot(data)
    if composite_row is None:
        return latest_row

    if _count_renderable_radar_axes(composite_row) > _count_renderable_radar_axes(latest_row):
        return composite_row
    return latest_row


def build_composite_profile_metric_rows(row: pd.Series | dict[str, object]) -> list[dict[str, object]]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    rows: list[dict[str, object]] = []

    for label, value_col, unit, z_col, digits in COMPOSITE_PROFILE_METRICS:
        display_spec = _composite_metric_display_spec(row_series, value_col, unit, z_col, digits)
        display_value_col = str(display_spec["value_col"])
        display_unit = str(display_spec["unit"])
        display_z_col = str(display_spec["z_col"])
        display_digits = int(display_spec["digits"])

        value = pd.to_numeric(pd.Series([row_series.get(display_value_col)]), errors="coerce").iloc[0]
        z_value = resolve_zscore(row_series, display_z_col)
        rounded_value = round(float(value), display_digits) if pd.notna(value) else None
        z_score_display = round(float(z_value), 2) if pd.notna(z_value) else "\u2014"
        rows.append(
            {
                "Variable": label,
                "Valor": _format_composite_metric_value(rounded_value, display_unit, display_digits),
                "Unidad": display_unit,
                "Z-score": z_score_display,
                "Origen / referencia": (
                    row_series.get(f"{display_value_col}__source_date", None)
                    or row_series.get(f"{value_col}__source_date", "-")
                    or "-"
                ),
                "Etiqueta visible profesional": label,
                "Direccion": COMPOSITE_PROFILE_DIRECTIONS.get(display_value_col, "higher_is_better"),
                "value_col": display_value_col,
                "z_col": display_z_col,
            }
        )

    return rows


def build_composite_profile_metric_table(row: pd.Series | dict[str, object]) -> pd.DataFrame:
    rows = build_composite_profile_metric_rows(row)
    return pd.DataFrame(rows, columns=["Variable", "Valor", "Z-score", "Origen / referencia"])


def build_jump_metric_table(row: pd.Series | dict[str, object]) -> pd.DataFrame:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    axes, _ = _available_radar_axes(row_series)
    rows: list[dict[str, object]] = []

    for label, value_col, unit, z_col in axes:
        value = pd.to_numeric(pd.Series([row_series.get(value_col)]), errors="coerce").iloc[0]
        z_value = resolve_zscore(row_series, z_col)
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


def _merge_duplicate_athlete_date_rows(jump_df: pd.DataFrame) -> pd.DataFrame:
    if jump_df.empty or not {"Athlete", "Date"}.issubset(jump_df.columns):
        return jump_df
    if not jump_df.duplicated(subset=["Athlete", "Date"]).any():
        return jump_df

    merged_rows: list[dict[str, object]] = []
    grouped = jump_df.sort_values(["Athlete", "Date"]).groupby(["Athlete", "Date"], sort=False, dropna=False)
    for (_, _), group in grouped:
        merged_row: dict[str, object] = {
            "Athlete": group.iloc[-1]["Athlete"],
            "Date": group.iloc[-1]["Date"],
        }
        for column in group.columns:
            if column in {"Athlete", "Date", "NM_Profile"}:
                continue

            numeric_values = pd.to_numeric(group[column], errors="coerce")
            if column == "BW_kg":
                positive_values = numeric_values[(numeric_values.notna()) & (numeric_values > 0)]
                if not positive_values.empty:
                    merged_row[column] = positive_values.iloc[-1]
                    continue

            valid_values = numeric_values[numeric_values.notna()]
            if not valid_values.empty:
                merged_row[column] = valid_values.iloc[-1]

        merged_rows.append(merged_row)

    return pd.DataFrame(merged_rows)


def _prepare_jump_df(jump_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the unified evaluations table and recompute derived metrics."""
    if jump_df is None or jump_df.empty:
        return pd.DataFrame()

    result = jump_df.copy()
    result = _normalize_legacy_imtp_rfd_aliases_frame(result)
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

    result = _merge_duplicate_athlete_date_rows(result)
    result = promote_legacy_dri_to_dj_rsi(result)
    result = calc_eur(result)
    result = calc_dj_rsi(result)
    result = calc_dri(result)
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
            if field == "BW_kg":
                numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
                existing_bw = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
                if pd.notna(existing_bw) and existing_bw > 0 and (pd.isna(numeric_value) or numeric_value <= 0):
                    continue
            if value is not None and not (isinstance(value, float) and np.isnan(value)):
                row[field] = value

    return _prepare_jump_df(pd.DataFrame(rows.values()))
