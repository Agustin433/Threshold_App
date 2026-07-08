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
        "phys": "Mejor capacidad concentrica/propulsiva relativa, con menor expresion en SSC rapido.",
        "bio": "El SJ disponible supera la expresion reactiva rapida; conviene leerlo junto con el resto de la bateria.",
        "train": "Fast SSC, stiffness util, pogos, drop jumps dosificados, sprints cortos, fuerza con intencion alta y bajo lastre.",
        "summary_short": "Buen perfil concentrico con rezago reactivo rapido.",
        "summary_athlete": "Tenes una base concentrica util, pero hoy la reaccion rapida en contactos breves aparece mas limitada.",
        "summary_client": "Hay una base de fuerza/propulsion util, con margen para mejorar la reaccion rapida y la calidad de contacto.",
        "summary_professional": "Se observa mejor salida concentrica relativa con menor expresion del SSC rapido; conviene priorizar contacto y transferencia reactiva sin cerrar la lectura de fuerza base solo con este patron.",
        "kpi_to_track": ["DJ_RSI", "DJ_tc_ms", "DRI"],
    },
    "B": {
        "label": "Patron B - Reactivo relativo con base concentrica limitada",
        "phys": "DJ RSI relativamente mejor que SJ en esta foto, con base concentrica menos destacada.",
        "bio": "La respuesta rapida disponible conviene validarla junto con altura de DJ, tiempo de contacto y DRI antes de cerrarla como fortaleza global.",
        "train": "Trabajo de fuerza maxima y potencia concentrica, sentadilla pesada, hip thrust, saltos con carga.",
        "summary_short": "Buen componente reactivo con base concentrica limitada.",
        "summary_athlete": "Respondés bien en acciones rapidas, pero todavia falta mas base de fuerza para sostener mejor esa reaccion.",
        "summary_client": "La reactividad aparece bien expresada, aunque la base concentrica todavia puede crecer para darle mas sostén al perfil.",
        "summary_professional": "Hay una senal reactiva relativa por DJ RSI, con menor SJ; conviene validarla con altura/contacto/DRI y reforzar fuerza base.",
        "kpi_to_track": ["SJ_cm", "CMJ_cm", "IMTP_relPF"],
    },
    "C": {
        "label": "Patron C - Salida vertical con deficit isometrico relativo",
        "phys": "Buena expresion vertical relativa con IMTP relPF por debajo de la referencia disponible.",
        "bio": "La salida vertical se sostiene mejor que la referencia de fuerza base disponible.",
        "train": "Fuerza maxima, IMTP-specific, isometricos en angulo de trabajo funcional.",
        "summary_short": "Salida explosiva presente con base isometrica relativa rezagada.",
        "summary_athlete": "Hoy mostras una buena salida explosiva, pero la base de fuerza isometrica relativa aparece por debajo de lo deseado.",
        "summary_client": "Hay una salida explosiva util, aunque la base de fuerza todavia parece corta para sostener mejor esa expresion.",
        "summary_professional": "La salida vertical se conserva, pero la fuerza base relativa aparece rezagada; priorizar fuerza maxima e isometricos especificos.",
        "kpi_to_track": ["IMTP_relPF", "IMTP_N", "DSI"],
    },
    "D": {
        "label": "Patron D - Deficit neuromuscular global",
        "phys": "Las variables disponibles muestran un rezago amplio del perfil actual.",
        "bio": "Las variables disponibles sugieren limitaciones compartidas en fuerza y expresion del salto, con interpretacion mas firme si la bateria esta completa.",
        "train": "Priorizar base general y progresion conservadora antes de complejizar el bloque, especialmente si la bateria actual es parcial.",
        "summary_short": "Varias variables disponibles quedan por debajo de la referencia.",
        "summary_athlete": "Hoy varias cualidades disponibles aparecen por debajo de la referencia, por lo que conviene reconstruir base antes de pedir mas complejidad.",
        "summary_client": "El perfil actual muestra varias senales por debajo de la referencia y pide consolidar bases antes de sumar mas exigencia.",
        "summary_professional": "Las variables disponibles del radar quedan deprimidas en conjunto; conviene priorizar acumulacion general y progresion reactiva conservadora, con mas cautela si la bateria es parcial.",
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

DJ_DROP_HEIGHT_BACKFILL_COLUMNS = (
    "Athlete",
    "Date",
    "DJ_drop_height_cm",
    "DJ_cm",
    "DJ_tc_ms",
    "DJ_RSI",
    "DRI",
)

ZSCORE_ALIAS_GROUPS = (
    ("DJ_height_Z", "DJ_Z"),
    ("TC_inv_Z", "DJtc_Z"),
    ("IMTP_relPF_Z", "IMTP_Z"),
)

NEUROMUSCULAR_QUADRANT_NEUTRAL_BAND = 0.35

_NEUROMUSCULAR_QUADRANT_ZONE_META = {
    "low": {
        "label": "bajo",
        "code_suffix": "low",
    },
    "mid": {
        "label": "intermedio",
        "code_suffix": "mid",
    },
    "high": {
        "label": "alto",
        "code_suffix": "high",
    },
    "missing": {
        "label": "sin dato",
        "code_suffix": "missing",
    },
}

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

PROFILE_SOURCE_CONFIG = {
    "latest_valid_row": {
        "label": "Ultima evaluacion valida",
        "note": "El perfil surge de una unica evaluacion valida.",
        "is_composite": False,
    },
    "composite_snapshot": {
        "label": "Perfil compuesto",
        "note": "El perfil combina las ultimas metricas validas disponibles por variable. Puede incluir datos de fechas distintas.",
        "is_composite": True,
    },
    "unknown": {
        "label": "Fuente no determinada",
        "note": "No se pudo determinar con claridad la fuente del perfil.",
        "is_composite": False,
    },
}

PROFILE_SOURCE_DATE_FIELDS = (
    ("SJ_cm", ("SJ_cm",)),
    ("CMJ_cm", ("CMJ_cm",)),
    ("DJ_cm", ("DJ_cm",)),
    ("DJ_RSI", ("DJ_RSI",)),
    ("DJ_tc_ms", ("DJ_tc_ms",)),
    ("DRI", ("DRI",)),
    ("EUR", ("EUR",)),
    ("IMTP_relPF", ("IMTP_relPF", "IMTP_N")),
    ("DSI", ("DSI",)),
    ("mRSI", ("mRSI",)),
)

EUR_PROFILE_THRESHOLDS = (
    (1.10, "Reactivo"),
    (1.00, "Mixto"),
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


def _eur_profile_label_from_ratio(eur_ratio: object) -> str:
    numeric = pd.to_numeric(pd.Series([eur_ratio]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "Sin datos"
    ratio = float(numeric)
    for threshold, label in EUR_PROFILE_THRESHOLDS:
        if ratio >= threshold:
            return label
    return "Base de Fuerza"


def _eur_profile_from_row(row: pd.Series | dict[str, object]) -> str:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    for field in ("EUR_Profile", "EUR_based_profile", "NM_Profile"):
        value = str(row_series.get(field) or "").strip()
        if value:
            return value
    return _eur_profile_label_from_ratio(row_series.get("EUR"))


def _coerce_quadrant_z(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _quadrant_zone(value: float | None, neutral_band: float) -> str:
    if value is None:
        return "missing"
    if value <= -neutral_band:
        return "low"
    if value >= neutral_band:
        return "high"
    return "mid"


def classify_neuromuscular_quadrant(
    x_z: object,
    y_z: object,
    neutral_band: float = NEUROMUSCULAR_QUADRANT_NEUTRAL_BAND,
) -> dict[str, object]:
    """Classify a neuromuscular quadrant with a shared neutral band."""
    band = _coerce_quadrant_z(neutral_band)
    if band is None or band <= 0:
        band = NEUROMUSCULAR_QUADRANT_NEUTRAL_BAND

    x_value = _coerce_quadrant_z(x_z)
    y_value = _coerce_quadrant_z(y_z)
    x_zone = _quadrant_zone(x_value, band)
    y_zone = _quadrant_zone(y_value, band)

    if "missing" in (x_zone, y_zone):
        return {
            "x_z": x_value,
            "y_z": y_value,
            "x_zone": x_zone,
            "y_zone": y_zone,
            "quadrant_code": "missing",
            "quadrant_label": "Datos insuficientes",
            "interpretation": "Faltan datos numericos suficientes para ubicar el punto en el cuadrante.",
            "neutral_band": band,
        }

    zone_pair = (x_zone, y_zone)
    labels = _NEUROMUSCULAR_QUADRANT_ZONE_META
    quadrant_code = f"{labels[x_zone]['code_suffix']}_{labels[y_zone]['code_suffix']}"
    quadrant_label_map = {
        ("high", "high"): "Ambos altos",
        ("low", "high"): "X bajo / Y alto",
        ("high", "low"): "X alto / Y bajo",
        ("low", "low"): "Ambos bajos",
        ("mid", "mid"): "Ambos en banda media",
        ("mid", "high"): "X intermedio / Y alto",
        ("high", "mid"): "X alto / Y intermedio",
        ("low", "mid"): "X bajo / Y intermedio",
        ("mid", "low"): "X intermedio / Y bajo",
    }
    interpretation_map = {
        ("high", "high"): "Ambos ejes quedan por encima de la banda neutral.",
        ("low", "high"): "El eje X queda bajo y el eje Y alto respecto a la banda neutral.",
        ("high", "low"): "El eje X queda alto y el eje Y bajo respecto a la banda neutral.",
        ("low", "low"): "Ambos ejes quedan por debajo de la banda neutral.",
        ("mid", "mid"): "Ambos ejes quedan dentro de la banda neutral.",
        ("mid", "high"): "El eje Y queda alto y el eje X permanece en banda neutral.",
        ("high", "mid"): "El eje X queda alto y el eje Y permanece en banda neutral.",
        ("low", "mid"): "El eje X queda bajo y el eje Y permanece en banda neutral.",
        ("mid", "low"): "El eje Y queda bajo y el eje X permanece en banda neutral.",
    }

    return {
        "x_z": x_value,
        "y_z": y_value,
        "x_zone": x_zone,
        "y_zone": y_zone,
        "quadrant_code": quadrant_code,
        "quadrant_label": quadrant_label_map[zone_pair],
        "interpretation": interpretation_map[zone_pair],
        "neutral_band": band,
    }


def _normalize_profile_source(value: object) -> str:
    source = str(value or "").strip()
    return source if source in PROFILE_SOURCE_CONFIG else "unknown"


def _format_profile_source_iso_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        parsed = pd.to_datetime(text, errors="coerce")
    else:
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else "-"


def _profile_source_dates_from_row(row: pd.Series | dict[str, object]) -> dict[str, str]:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    row_date_iso = _format_profile_source_iso_date(row_series.get("Date"))
    source_dates: dict[str, str] = {}

    for metric_key, value_columns in PROFILE_SOURCE_DATE_FIELDS:
        value = _coalesced_numeric_value(row_series, *value_columns)
        if value is None:
            continue

        source_date = "-"
        for value_col in value_columns:
            source_date = (
                row_series.get(f"{value_col}__source_date_iso")
                or row_series.get(f"{value_col}__source_date")
                or source_date
            )
            if str(source_date).strip() and str(source_date).strip() != "-":
                break
        if (not str(source_date).strip()) or str(source_date).strip() == "-":
            source_date = row_date_iso

        iso_date = _format_profile_source_iso_date(source_date)
        if iso_date != "-":
            source_dates[metric_key] = iso_date

    return source_dates


def _infer_profile_source(
    row: pd.Series | dict[str, object],
    *,
    context: dict[str, object] | None = None,
    profile_source_dates: dict[str, str] | None = None,
) -> str:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    explicit_source = _normalize_profile_source((context or {}).get("profile_source"))
    if explicit_source != "unknown":
        return explicit_source

    if bool(row_series.get("Profile_Composed")):
        return "composite_snapshot"

    has_metric_source_fields = any(
        str(column).endswith("__source_date") or str(column).endswith("__source_date_iso")
        for column in row_series.index
    )
    source_dates = dict(profile_source_dates or {})
    if has_metric_source_fields and source_dates:
        return "composite_snapshot"

    if pd.notna(pd.to_datetime(row_series.get("Date"), errors="coerce")):
        return "latest_valid_row"

    return "unknown"


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


def dj_drop_height_backfill_mask(df: pd.DataFrame | None) -> pd.Series:
    if df is None:
        return pd.Series(dtype=bool)
    if df.empty:
        return pd.Series(False, index=df.index, dtype=bool)
    if not {"DJ_cm", "DJ_tc_ms"}.issubset(df.columns):
        return pd.Series(False, index=df.index, dtype=bool)

    dj_height_cm = _numeric_series(df, "DJ_cm")
    dj_tc_ms = _numeric_series(df, "DJ_tc_ms")
    raw_dj_mask = dj_height_cm.notna() & dj_tc_ms.notna()

    if "DJ_drop_height_cm" not in df.columns:
        return raw_dj_mask

    drop_height_cm = _numeric_series(df, "DJ_drop_height_cm")
    return raw_dj_mask & (drop_height_cm.isna() | (drop_height_cm <= 0))


def build_dj_drop_height_backfill_candidates(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(DJ_DROP_HEIGHT_BACKFILL_COLUMNS))

    mask = dj_drop_height_backfill_mask(df)
    candidate_cols = [col for col in DJ_DROP_HEIGHT_BACKFILL_COLUMNS if col in df.columns]
    candidates = df.loc[mask, candidate_cols].copy()

    for col in DJ_DROP_HEIGHT_BACKFILL_COLUMNS:
        if col not in candidates.columns:
            candidates[col] = np.nan

    if "Date" in candidates.columns:
        candidates["Date"] = pd.to_datetime(candidates["Date"], errors="coerce").dt.normalize()

    return candidates[list(DJ_DROP_HEIGHT_BACKFILL_COLUMNS)].reset_index(drop=True)


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
    """Populate the legacy EUR-based profile fields.

    ``NM_Profile`` is kept only as a backward-compatible alias based on EUR.
    It should not be used as the global neuromuscular profile; the structured
    profile must come from ``build_neuromuscular_profile_result(...)``.
    """
    if "EUR" not in df.columns:
        return df

    eur_ratio = _normalize_eur_series_to_ratio(df["EUR"])
    conditions = [eur_ratio >= threshold for threshold, _ in EUR_PROFILE_THRESHOLDS]
    labels = [label for _, label in EUR_PROFILE_THRESHOLDS]
    df["EUR"] = eur_ratio
    eur_profile = np.select(conditions, labels, default="Base de Fuerza")
    eur_profile = pd.Series(eur_profile, index=df.index).where(eur_ratio.notna(), "Sin datos")
    df["EUR_Profile"] = eur_profile
    # Legacy alias based only on EUR. Do not use as the main neuromuscular profile.
    df["NM_Profile"] = eur_profile
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
            flags.append({"level": "green", "text": "EUR alto: revisar junto con SJ y CMJ"})
        elif eur >= 1.00:
            flags.append({"level": "yellow", "text": "EUR intermedio: leer junto con SJ y CMJ"})
        else:
            flags.append({"level": "red", "text": "EUR bajo: posible bajo aporte del contramovimiento; validar tecnica y fatiga"})

    dsi = pd.to_numeric(pd.Series([row_series.get("DSI")]), errors="coerce").iloc[0]
    if pd.notna(dsi):
        if dsi >= 1.0:
            flags.append({"level": "green", "text": "DSI alto: relacion dinamica/isometrica elevada; interpretar con IMTP y CMJ"})
        elif dsi >= 0.8:
            flags.append({"level": "yellow", "text": "DSI intermedio: interpretar con IMTP y CMJ"})
        else:
            flags.append({"level": "red", "text": "DSI bajo: relacion dinamica/isometrica reducida; interpretar con IMTP y CMJ"})

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
            flags.append({"level": "green", "text": "mRSI alto: eficiencia temporal del CMJ; no equivalente a DJ RSI"})
        elif mrsi >= 0.45:
            flags.append({"level": "yellow", "text": "mRSI intermedio: leer junto con CMJ y el protocolo aplicado"})
        else:
            flags.append({"level": "red", "text": "mRSI bajo: eficiencia temporal del CMJ a validar con el protocolo aplicado"})

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


def _append_unique_text(base_text: object, extra_text: object) -> str:
    base = str(base_text or "").strip()
    extra = str(extra_text or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base} {extra}".strip()


def _replace_text_tokens(text: object, replacements: dict[str, str]) -> str:
    updated = str(text or "")
    for source, target in replacements.items():
        updated = updated.replace(source, target)
    return updated.strip()


def _is_near_threshold(value: object, *, threshold: float = 0.5, margin: float = 0.1) -> bool:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return False
    return abs(abs(float(numeric)) - threshold) <= margin


def _pattern_has_near_threshold_evidence(row: pd.Series, patterns: list[str]) -> bool:
    sj_z = resolve_zscore(row, "SJ_Z")
    dj_rsi_z = resolve_zscore(row, "DJ_RSI_Z")
    cmj_z = resolve_zscore(row, "CMJ_Z")
    imtp_relpf_z = resolve_zscore(row, "IMTP_relPF_Z")
    eur = _coalesced_numeric_value(row, "EUR")

    if "A" in patterns and (_is_near_threshold(sj_z) or _is_near_threshold(dj_rsi_z)):
        return True
    if "B" in patterns and (_is_near_threshold(sj_z) or _is_near_threshold(dj_rsi_z)):
        return True
    if "C" in patterns and (
        _is_near_threshold(imtp_relpf_z) or (cmj_z is not None and abs(float(cmj_z) - (-0.5)) <= 0.1)
    ):
        return True
    if "E" in patterns and eur is not None and abs(float(eur) - 1.0) <= 0.03:
        return True
    return False


def _profile_has_partial_battery(flags: list[str]) -> bool:
    flag_set = set(flags)
    return "missing_imtp" in flag_set or "missing_dj" in flag_set


def _profile_confidence_from_context(
    *,
    patterns: list[str],
    flags: list[str],
    profile_source: str,
) -> str:
    flag_set = set(flags)
    if "insufficient_pattern_evidence" in flag_set or "cmj_lower_than_sj" in flag_set or "E" in patterns:
        return "low"
    if "D" in patterns and "partial_battery_caution" in flag_set:
        return "low"
    if {"missing_imtp", "missing_dj"}.issubset(flag_set):
        return "low"
    if "near_threshold_evidence" in flag_set:
        return "moderate"
    if "partial_battery_caution" in flag_set:
        return "moderate"
    if profile_source in {"composite_snapshot", "unknown"}:
        return "moderate"
    if "composite_profile_caution" in flag_set:
        return "moderate"
    return "high"


def _apply_pattern_claim_guards(
    result: dict[str, object],
    row_series: pd.Series,
    *,
    patterns: list[str],
    flags: list[str],
) -> None:
    flag_set = set(flags)
    has_imtp_reference = "missing_imtp" not in flag_set
    has_dj_complete = "missing_dj" not in flag_set
    partial_battery = "partial_battery_caution" in flag_set

    if "A" in patterns and not has_imtp_reference:
        caution_common = "Sin una referencia IMTP comparable, no conviene cerrar conclusiones sobre la base de fuerza."
        caution_client = "Sin una referencia extra de fuerza, conviene tomar esta lectura como parcial."
        result["phys"] = _append_unique_text(result.get("phys"), caution_common)
        result["bio"] = _append_unique_text(result.get("bio"), caution_common)
        result["summary_athlete"] = _append_unique_text(result.get("summary_athlete"), caution_common)
        result["summary_client"] = _append_unique_text(result.get("summary_client"), caution_client)
        result["summary_professional"] = _append_unique_text(result.get("summary_professional"), caution_common)

    if "B" in patterns:
        dj_context = "Esta senal conviene validarla con altura de DJ, tiempo de contacto y DRI antes de cerrarla como fortaleza reactiva."
        if not has_dj_complete:
            result["bio"] = _append_unique_text(result.get("bio"), dj_context)
        result["summary_professional"] = _append_unique_text(result.get("summary_professional"), dj_context)
        if not has_imtp_reference:
            caution_common = "Sin una referencia IMTP comparable, no conviene cerrar conclusiones sobre la base de fuerza."
            caution_client = "Sin una referencia extra de fuerza, conviene tomar esta lectura como parcial."
            result["phys"] = _append_unique_text(result.get("phys"), caution_common)
            result["summary_athlete"] = _append_unique_text(result.get("summary_athlete"), caution_common)
            result["summary_client"] = _append_unique_text(result.get("summary_client"), caution_client)
            result["summary_professional"] = _append_unique_text(result.get("summary_professional"), caution_common)

    if "C" in patterns and _coalesced_numeric_value(row_series, "DSI") is None:
        replacements = {"DSI probablemente elevado.": ""}
        for field in ("phys", "bio", "summary_short", "summary_athlete", "summary_client", "summary_professional"):
            result[field] = _replace_text_tokens(result.get(field), replacements)

    if "D" in patterns and partial_battery:
        caution_common = "La bateria actual es parcial y la interpretacion queda limitada a las variables disponibles."
        caution_client = "Como faltan partes de la evaluacion, esta lectura queda limitada a los datos disponibles."
        for field in ("phys", "bio", "summary_short", "summary_athlete", "summary_professional", "train"):
            result[field] = _append_unique_text(result.get(field), caution_common)
        result["summary_client"] = _append_unique_text(result.get("summary_client"), caution_client)

    if "E" in patterns and len(patterns) > 1:
        caution_prof = "Aunque aparezcan otras senales del perfil, la cautela por CMJ < SJ debe preservarse antes de cambiar prioridades."
        caution_client = "Antes de sacar conclusiones mas fuertes, conviene confirmar primero la senal de CMJ frente a SJ."
        result["summary_professional"] = _append_unique_text(result.get("summary_professional"), caution_prof)
        result["summary_client"] = _append_unique_text(result.get("summary_client"), caution_client)
        result["summary_athlete"] = _append_unique_text(result.get("summary_athlete"), caution_prof)


def _default_neuromuscular_result() -> dict[str, object]:
    return {
        "profile_code": "UNCLASSIFIED",
        "profile_label": "Sin patron dominante",
        "eur_profile": "Sin datos",
        "nm_profile_legacy": "Sin datos",
        "confidence": "low",
        "profile_source": "unknown",
        "profile_source_label": PROFILE_SOURCE_CONFIG["unknown"]["label"],
        "profile_source_note": PROFILE_SOURCE_CONFIG["unknown"]["note"],
        "profile_source_dates": {},
        "profile_source_is_composite": PROFILE_SOURCE_CONFIG["unknown"]["is_composite"],
        "phys": "La informacion disponible no alcanza para clasificar un perfil neuromuscular estable.",
        "bio": "No aparece un patron biomecanico dominante suficiente con los datos disponibles; conviene leerlo junto con tecnica y contexto del test.",
        "train": "Conviene repetir o completar la bateria antes de sacar conclusiones fuertes; sostener el plan solo si carga y contexto lo respaldan.",
        "summary_short": "La informacion disponible no alcanza para clasificar un patron estable.",
        "summary_athlete": "Hoy la foto neuromuscular no alcanza para cerrar un patron estable; conviene completar o repetir mediciones antes de cambiar demasiado el foco.",
        "summary_client": "Con la informacion disponible no conviene sacar conclusiones fuertes; hace falta completar o repetir mediciones clave.",
        "summary_professional": "La evidencia disponible no alcanza para clasificar un patron dominante estable; conviene completar variables clave y releer el contexto del test.",
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

    del reference_df

    row_series = row if isinstance(row, pd.Series) else pd.Series(row or {}, dtype=object)
    result = _default_neuromuscular_result()
    result["eur_profile"] = _eur_profile_from_row(row_series)
    result["nm_profile_legacy"] = str(row_series.get("NM_Profile") or result["eur_profile"] or "Sin datos").strip() or "Sin datos"
    row_date_display = _format_profile_source_date(row_series.get("Date"))

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
            or row_date_display
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
    if imtp_value is not None and imtp_z is None:
        flags.append("imtp_reference_missing")

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
    if _profile_has_partial_battery(flags):
        flags.append("partial_battery_caution")
    if _pattern_has_near_threshold_evidence(row_series, patterns):
        flags.append("near_threshold_evidence")
        flags.append("near_threshold")

    profile_source_dates = _profile_source_dates_from_row(row_series)
    profile_source = _infer_profile_source(
        row_series,
        context=context,
        profile_source_dates=profile_source_dates,
    )
    source_meta = PROFILE_SOURCE_CONFIG.get(profile_source, PROFILE_SOURCE_CONFIG["unknown"])
    result["profile_source"] = profile_source
    result["profile_source_label"] = str(source_meta["label"])
    result["profile_source_note"] = str(source_meta["note"])
    result["profile_source_dates"] = profile_source_dates
    result["profile_source_is_composite"] = bool(source_meta["is_composite"])
    if result["profile_source_is_composite"]:
        flags.append("composite_profile_caution")

    result["flags"] = list(dict.fromkeys(flags))
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
        _apply_pattern_claim_guards(
            result,
            row_series,
            patterns=patterns,
            flags=result["flags"],
        )

    if "missing_imtp" in result["flags"]:
        result["kpi_to_track"] = list(dict.fromkeys([*result["kpi_to_track"], "IMTP_relPF"]))
    if "missing_dj" in result["flags"]:
        result["kpi_to_track"] = list(dict.fromkeys([*result["kpi_to_track"], "DJ_cm", "DJ_RSI", "DJ_tc_ms"]))
    if not result["kpi_to_track"]:
        result["kpi_to_track"] = ["CMJ_cm", "SJ_cm", "EUR", "DJ_RSI", "IMTP_relPF"]

    result["confidence"] = _profile_confidence_from_context(
        patterns=patterns,
        flags=result["flags"],
        profile_source=profile_source,
    )

    return result


_DASHBOARD_CONFIDENCE_LABELS = {
    "high": "alta",
    "moderate": "moderada",
    "low": "baja",
}

_DASHBOARD_STRUCTURED_FLAG_MAP = {
    "missing_imtp": {"level": "gray", "text": "Referencia IMTP incompleta"},
    "imtp_reference_missing": {"level": "gray", "text": "IMTP sin referencia comparable"},
    "missing_dj": {"level": "gray", "text": "DJ pendiente"},
    "cmj_lower_than_sj": {"level": "red", "text": "CMJ < SJ"},
    "insufficient_pattern_evidence": {"level": "yellow", "text": "Perfil parcial"},
    "partial_battery_caution": {"level": "yellow", "text": "Bateria parcial"},
    "composite_profile_caution": {"level": "yellow", "text": "Perfil compuesto"},
    "near_threshold_evidence": {"level": "yellow", "text": "Senal cerca del umbral"},
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
            "profile_label": "Sin patrón definido",
            "eur_profile": _eur_profile_from_row(row_series),
            "nm_profile_legacy": str(row_series.get("NM_Profile") or _eur_profile_from_row(row_series) or "Sin datos").strip() or "Sin datos",
            "confidence": "low",
            "confidence_label": _DASHBOARD_CONFIDENCE_LABELS["low"],
            "profile_source": "unknown",
            "profile_source_label": PROFILE_SOURCE_CONFIG["unknown"]["label"],
            "profile_source_note": PROFILE_SOURCE_CONFIG["unknown"]["note"],
            "profile_source_dates": {},
            "profile_source_is_composite": PROFILE_SOURCE_CONFIG["unknown"]["is_composite"],
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
    profile_label = str(payload.get("profile_label") or "").strip()
    profile_code = str(payload.get("profile_code") or "").strip().upper()
    if profile_code in {"", "UNCLASSIFIED", "NONE"} and "sin patron" in profile_label.casefold():
        payload["profile_label"] = "Sin patrón definido"
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
            biomecanico = "No aparece un patron biomecanico dominante con los datos disponibles; conviene completar bateria y contexto."

        lines = [
            "Alto: sin variables > 0.5.",
            "Bajo: sin variables < -0.5.",
            "Fisiologico: La informacion disponible no muestra una senal dominante suficiente para cerrar un perfil estable.",
            f"Biomecanico: {biomecanico}",
            "Proximo bloque: Evitar cambios fuertes solo por este perfil aislado; repetir o completar mediciones si hace falta.",
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
        source_date_iso = _format_profile_source_iso_date(source_row.get("Date"))
        source_z_col = "IMTP_N_Z" if source_value_col == "IMTP_N" else z_col
        snapshot[source_value_col] = source_row.get(source_value_col)
        resolved_source_z = (
            resolve_zscore(source_row, source_z_col)
            if source_z_col != "IMTP_N_Z"
            else _coalesced_numeric_value(source_row, "IMTP_N_Z")
        )
        snapshot[source_z_col] = resolved_source_z
        snapshot[f"{value_col}__source_date"] = source_date
        snapshot[f"{value_col}__source_date_iso"] = source_date_iso
        snapshot[f"{source_value_col}__source_date"] = source_date
        snapshot[f"{source_value_col}__source_date_iso"] = source_date_iso
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
            snapshot[f"{field}__source_date"] = _format_profile_source_date(source_row.get("Date"))
            snapshot[f"{field}__source_date_iso"] = _format_profile_source_iso_date(source_row.get("Date"))

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
            if column in {"Athlete", "Date", "NM_Profile", "EUR_Profile", "EUR_based_profile"}:
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

    numeric_cols = [
        col
        for col in result.columns
        if col not in {"Athlete", "Date", "NM_Profile", "EUR_Profile", "EUR_based_profile"}
    ]
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
