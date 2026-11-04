"""Reglas de validez de evaluaciones: una funcion por regla, una sola fuente.

Todas las superficies (dashboard, pagina de Jump Evaluation, Excel y los tres
PDF) consumen estas funciones a traves de `_prepare_jump_df` y de los
helpers de force-time; ninguna pantalla reimplementa una regla.

Reglas:
1. Calidad IMTP: curva sin subida tras el inicio ((Force@50 - pretension)
   < 50 N o RFD 0-50 ms < 1000 N/s) invalida la RFD y la fuerza a 50-250 ms.
   Peak Force y la fuerza relativa siguen siendo validas. El exceso de
   pretension sobre BW es solo informativo (PDF profesional).
2. Fuerza relativa IMTP: bruta (PF / masa) y neta ((PF - BW*g) / masa).
3. Peso corporal: valido solo entre 30 y 200 kg; 0 o fuera de rango = vacio.
4. Antiguedad de evaluacion: > 12 semanas = desactualizada.
5. Umbral de cambio: nunca por debajo del error tipico del instrumento.
6. Peso de plataforma invalido: si la plataforma calculo CMJ/SJ sin un peso
   valido (0, vacio o impulso relativo negativo), se descartan las metricas
   que dependen del peso: altura por impulso-momento, velocidad, potencia,
   impulso y fases.
7. Peso de una evaluacion cercana: sin peso valido, se toma el del mismo
   atleta medido a <= 14 dias, solo para las relativas que calcula la app
   (IMTP relPF, momentum). Nunca se guarda en la base.
8. Toma duplicada con fecha distinta: misma toma (>= 3 metricas identicas y
   >= 50% de las comparables) para el mismo atleta y fuente en otra fecha
   bloquea la carga.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

GRAVITY_M_S2 = 9.81

# ── Regla 3: peso corporal ────────────────────────────────────────────────
BW_KG_MIN = 30.0
BW_KG_MAX = 200.0


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def sanitize_bw_kg(value: object) -> float | None:
    """Peso valido (30-200 kg) o None. 0, negativos y fuera de rango = None."""
    number = _number(value)
    if number is None or number < BW_KG_MIN or number > BW_KG_MAX:
        return None
    return number


def validate_bw_kg_input(value: object) -> tuple[float | None, str | None]:
    """Valida el peso en la carga. Devuelve (valor limpio, aviso o None).

    Vacio es valido (sin aviso). Un valor presente fuera de 30-200 kg (incluido
    el 0 que exportan algunas plataformas cuando no se peso al atleta) se
    descarta y se avisa: guardarlo daria fuerza relativa y momentum absurdos.
    """
    number = _number(value)
    if number is None:
        return None, None
    clean = sanitize_bw_kg(number)
    if clean is None:
        return None, (
            f"Peso corporal {number:g} kg fuera de rango ({BW_KG_MIN:.0f}-{BW_KG_MAX:.0f} kg): "
            "se guarda vacío y no se calculan métricas relativas."
        )
    return clean, None


def sanitize_bw_kg_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.where((numeric >= BW_KG_MIN) & (numeric <= BW_KG_MAX))


# ── Regla 1: calidad IMTP ─────────────────────────────────────────────────
# Criterio: la curva tiene que SUBIR despues del inicio. En esta plataforma el
# exceso de pretension sobre el peso marcaba 9 de 10 tomas sin discriminar
# (Tomas +572 N con RFD50 9414 N/s es una toma buena), asi que queda solo como
# dato informativo del PDF profesional. Una toma sin subida (Force@50 casi
# igual a la pretension, o RFD 0-50 baja) tiene el inicio mal definido.
IMTP_F50_RISE_MIN_N = 50.0
IMTP_RFD50_MIN_N_S = 1000.0
IMTP_QUALITY_FLAG_COLUMN = "IMTP_quality_flag"
IMTP_PRETENSION_EXCESS_COLUMN = "IMTP_pretension_excess_N"
IMTP_NO_RISE_FLAG = "curva_sin_subida"
IMTP_NO_RISE_LABEL = "curva sin subida tras el inicio: RFD y fuerza a 50–250 ms no interpretables"
# Columnas dependientes del inicio de la contraccion: con el onset mal
# definido todas quedan fuera, incluida F@250.
IMTP_TIME_DEPENDENT_COLUMNS = (
    "IMTP_force_50_N",
    "IMTP_force_100_N",
    "IMTP_force_150_N",
    "IMTP_force_200_N",
    "IMTP_force_250_N",
    "IMTP_rfd_50_N_s",
    "IMTP_rfd_100_N_s",
    "IMTP_rfd_150_N_s",
    "IMTP_rfd_250_N_s",
)


def _get(source: Mapping[str, object] | pd.Series, *keys: str) -> float | None:
    for key in keys:
        try:
            value = source.get(key)  # type: ignore[union-attr]
        except Exception:
            value = None
        number = _number(value)
        if number is not None:
            return number
    return None


def imtp_pretension_excess_n(pretension_n: object, bw_kg: object) -> float | None:
    """Pretension sobre el peso corporal (N). Solo informativo: no bloquea nada."""
    pretension = _number(pretension_n)
    bw = sanitize_bw_kg(bw_kg)
    if pretension is None or bw is None:
        return None
    return round(pretension - bw * GRAVITY_M_S2, 1)


def assess_imtp_quality(
    pretension_n: object,
    force_50_n: object,
    rfd_50_n_s: object,
    *,
    bw_kg: object = None,
    existing_flag: object = None,
) -> dict[str, object]:
    """Calidad de una toma IMTP: no interpretable si la curva no sube.

    (Force@50 - pretension) < 50 N  O  RFD 0-50 < 1000 N/s.
    `existing_flag` permite re-evaluar un frame ya preparado (donde la RFD ya
    fue anulada) sin perder la marca. `bw_kg` solo alimenta el exceso de
    pretension informativo.
    """
    pretension = _number(pretension_n)
    force_50 = _number(force_50_n)
    rfd50 = _number(rfd_50_n_s)
    rise = force_50 - pretension if force_50 is not None and pretension is not None else None

    reasons: list[str] = []
    if rise is not None and rise < IMTP_F50_RISE_MIN_N:
        reasons.append(f"Force@50 − pretensión = {rise:.0f} N (< {IMTP_F50_RISE_MIN_N:.0f} N)")
    if rfd50 is not None and rfd50 < IMTP_RFD50_MIN_N_S:
        reasons.append(f"RFD 0–50 ms {rfd50:.0f} N/s (< {IMTP_RFD50_MIN_N_S:.0f} N/s)")
    flagged = bool(reasons) or str(existing_flag or "").strip() == IMTP_NO_RISE_FLAG
    return {
        "flagged": flagged,
        "flag": IMTP_NO_RISE_FLAG if flagged else None,
        "label": IMTP_NO_RISE_LABEL if flagged else None,
        "rise_50_n": round(rise, 1) if rise is not None else None,
        "pretension_excess_n": imtp_pretension_excess_n(pretension, bw_kg),
        "reasons": reasons,
    }


def assess_imtp_quality_row(row: Mapping[str, object] | pd.Series) -> dict[str, object]:
    return assess_imtp_quality(
        _get(row, "IMTP_pretension", "pre_tension_n"),
        _get(row, "IMTP_force_50_N", "force_50_n"),
        _get(row, "IMTP_rfd_50_N_s", "rfd_50_n_s", "RFD_50"),
        bw_kg=_get(row, "BW_kg"),
        existing_flag=row.get(IMTP_QUALITY_FLAG_COLUMN) if hasattr(row, "get") else None,
    )


def apply_imtp_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Marca tomas IMTP no interpretables y anula sus variables tempranas.

    Anular en la capa de datos (y no en cada pantalla) garantiza que RFD y
    Force@ms de una toma invalida no entren en graficos, tablas, z-scores,
    deltas ni comparaciones de equipo. El dato crudo queda en la base: al
    guardar, los NaN no se escriben.
    """
    if df is None or df.empty:
        return df
    existing = df[IMTP_QUALITY_FLAG_COLUMN] if IMTP_QUALITY_FLAG_COLUMN in df.columns else None
    flags: list[object] = []
    excesses: list[object] = []
    for idx, row in df.iterrows():
        result = assess_imtp_quality(
            _get(row, "IMTP_pretension"),
            _get(row, "IMTP_force_50_N"),
            _get(row, "IMTP_rfd_50_N_s"),
            bw_kg=_get(row, "BW_kg"),
            existing_flag=existing.loc[idx] if existing is not None else None,
        )
        flags.append(result["flag"])
        excesses.append(result["pretension_excess_n"] if result["pretension_excess_n"] is not None else np.nan)
    df[IMTP_QUALITY_FLAG_COLUMN] = pd.Series(flags, index=df.index, dtype=object)
    df[IMTP_PRETENSION_EXCESS_COLUMN] = pd.to_numeric(pd.Series(excesses, index=df.index), errors="coerce")
    mask = df[IMTP_QUALITY_FLAG_COLUMN].eq(IMTP_NO_RISE_FLAG)
    if mask.any():
        for column in IMTP_TIME_DEPENDENT_COLUMNS:
            if column in df.columns:
                df.loc[mask, column] = np.nan
    return df


def imtp_quality_label(row: Mapping[str, object] | pd.Series | None) -> str | None:
    if row is None:
        return None
    return assess_imtp_quality_row(row).get("label")  # type: ignore[return-value]


# ── Regla 2: fuerza relativa IMTP bruta y neta ────────────────────────────
IMTP_REL_GROSS_COLUMN = "IMTP_relPF"
IMTP_REL_NET_COLUMN = "IMTP_relPF_net"
IMTP_REL_GROSS_LABEL = "IMTP relPF bruta"
IMTP_REL_NET_LABEL = "IMTP relPF neta"
IMTP_REL_GROSS_HELP = "Fuerza pico / masa (incluye el peso corporal)"
IMTP_REL_NET_HELP = "(Fuerza pico − peso corporal) / masa"


def imtp_relative_force(peak_force_n: object, bw_kg: object) -> tuple[float | None, float | None]:
    """(bruta, neta) en N/kg; (None, None) si el peso no es valido."""
    peak = _number(peak_force_n)
    bw = sanitize_bw_kg(bw_kg)
    if peak is None or bw is None or peak <= 0:
        return None, None
    gross = round(peak / bw, 2)
    net = round((peak - bw * GRAVITY_M_S2) / bw, 2)
    return gross, net


def calc_imtp_relative_force(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "IMTP_N" not in df.columns:
        return df
    if "BW_kg" not in df.columns and BW_IMPUTED_COLUMN not in df.columns:
        return df
    peak = pd.to_numeric(df["IMTP_N"], errors="coerce")
    bw = effective_bw_kg_series(df)
    mask = peak.notna() & (peak > 0) & bw.notna()
    if IMTP_REL_GROSS_COLUMN not in df.columns:
        df[IMTP_REL_GROSS_COLUMN] = np.nan
    if IMTP_REL_NET_COLUMN not in df.columns:
        df[IMTP_REL_NET_COLUMN] = np.nan
    df[IMTP_REL_GROSS_COLUMN] = pd.to_numeric(df[IMTP_REL_GROSS_COLUMN], errors="coerce").where(mask)
    df[IMTP_REL_NET_COLUMN] = pd.to_numeric(df[IMTP_REL_NET_COLUMN], errors="coerce").where(mask)
    df.loc[mask, IMTP_REL_GROSS_COLUMN] = (peak[mask] / bw[mask]).round(2)
    df.loc[mask, IMTP_REL_NET_COLUMN] = ((peak[mask] - bw[mask] * GRAVITY_M_S2) / bw[mask]).round(2)
    return df


# ── Regla 4: antiguedad de la evaluacion ──────────────────────────────────
STALE_EVALUATION_WEEKS = 12


def evaluation_staleness(
    evaluation_dates: object,
    reference_date: object = None,
) -> dict[str, object]:
    """Antiguedad de la medicion mas vieja que sostiene una lectura.

    `evaluation_dates` puede ser una fecha o un iterable (perfil compuesto:
    se usa la mas antigua, porque es la que limita la confianza).
    """
    if reference_date is None:
        from modules.app_clock import app_today

        reference_date = app_today()
    if isinstance(evaluation_dates, (str, bytes)) or not isinstance(evaluation_dates, Iterable):
        candidates = [evaluation_dates]
    else:
        candidates = list(evaluation_dates)
    parsed = pd.to_datetime(pd.Series(candidates, dtype=object), errors="coerce", dayfirst=False).dropna()
    reference = pd.to_datetime(reference_date, errors="coerce")
    if parsed.empty or pd.isna(reference):
        return {"is_stale": False, "weeks": None, "oldest_date": None, "label": None}
    oldest = parsed.min().normalize()
    weeks = int((reference.normalize() - oldest).days // 7)
    is_stale = weeks > STALE_EVALUATION_WEEKS
    return {
        "is_stale": is_stale,
        "weeks": weeks,
        "oldest_date": oldest,
        "label": f"Evaluación desactualizada (hace {weeks} semanas)" if is_stale else None,
    }


_CONFIDENCE_ORDER = ("high", "moderate", "low")


def downgrade_confidence(confidence: str) -> str:
    clean = str(confidence or "low").strip().lower()
    if clean not in _CONFIDENCE_ORDER:
        return "low"
    return _CONFIDENCE_ORDER[min(_CONFIDENCE_ORDER.index(clean) + 1, len(_CONFIDENCE_ORDER) - 1)]


# ── Regla 5: umbral de cambio ─────────────────────────────────────────────
# Error tipico (CV%) del instrumento por variable. Valores conservadores de la
# literatura de confiabilidad test-retest en plataforma de fuerza; se usan
# solo mientras no hay TE intraindividual.
INSTRUMENT_TYPICAL_ERROR_PCT: dict[str, float] = {
    "CMJ_cm": 3.0,
    "SJ_cm": 3.0,
    "DJ_cm": 3.0,
    "DJ_RSI": 5.0,
    "DJ_tc_ms": 4.0,
    "IMTP_N": 3.0,
    "IMTP_relPF": 3.0,
    "IMTP_relPF_net": 4.0,
    "EUR": 4.0,
    "DSI": 5.0,
    "CMJ_rel_impulse": 3.0,
    "Jump_Momentum": 3.0,
}
DEFAULT_INSTRUMENT_TYPICAL_ERROR_PCT = 3.0
INTRAINDIVIDUAL_MIN_VALID = 3


def drop_identical_consecutive_takes(values: list[float]) -> list[float]:
    """Quita una toma identica a la anterior (misma medicion cargada dos veces).

    Dos tomas reales nunca dan exactamente el mismo valor: un par identico es
    un duplicado (p. ej. la misma toma con la fecha corrida). Dejarlo da una
    diferencia 0 que baja el TE intraindividual hacia 0 y achica la SD de
    Hopkins: el umbral queda por debajo del ruido real y el error se lee como
    cambio.
    """
    kept: list[float] = []
    for value in values:
        if kept and math.isclose(value, kept[-1], rel_tol=1e-9, abs_tol=1e-9):
            continue
        kept.append(value)
    return kept


def resolve_change_threshold(
    variable: str,
    previous_value: object,
    history_values: Iterable[object],
    *,
    swc_pct: float,
) -> dict[str, object]:
    """Umbral minimo de cambio real y su fuente: max(TE, SWC), siempre.

    Candidatos (gana el mayor; la fuente se rotula):
    - SWC: con >= 3 mediciones validas, 0.2*SD intraindividual (Hopkins);
      con menos, el SWC fijo de la variable (% del valor anterior).
    - TE del instrumento (% del valor anterior): siempre. Un umbral por
      debajo del ruido de medicion convierte el error en "cambio" (antes,
      con 3+ tomas, el SJ quedaba en 0.6 cm "Hopkins 0.2·SD").
    - TE intraindividual = SD de las diferencias sucesivas / sqrt(2), con
      >= 3 mediciones. Los pares de tomas identicas se excluyen antes (TE = 0
      no es fisiologico: es la misma toma cargada dos veces).
    """
    previous = _number(previous_value)
    values = drop_identical_consecutive_takes(
        [v for v in (_number(x) for x in history_values) if v is not None]
    )
    n_valid = len(values)
    intraindividual = n_valid >= INTRAINDIVIDUAL_MIN_VALID
    suffix = f", N={n_valid}" if intraindividual else ""

    # (umbral, metodo, etiqueta). El orden desempata: ante igualdad gana el
    # primero, que es el ruido (TE) y no el SWC.
    candidates: list[tuple[float, str, str]] = []
    reference = previous if previous is not None and previous > 0 else (values[-1] if values else None)
    if reference is not None and reference > 0:
        te_pct = INSTRUMENT_TYPICAL_ERROR_PCT.get(variable, DEFAULT_INSTRUMENT_TYPICAL_ERROR_PCT)
        candidates.append((abs(reference * float(te_pct) / 100), "TE instrumento", f"TE instrumento {te_pct:g}%{suffix}"))
    if intraindividual:
        diffs = np.diff(values)
        if len(diffs) >= 2:
            te_abs = float(np.std(diffs, ddof=1) / math.sqrt(2))
            candidates.append((te_abs, "TE intraindividual", f"TE intraindividual{suffix}"))
        sd = float(np.std(values, ddof=1))
        candidates.append((abs(0.2 * sd), "Hopkins", f"Hopkins 0.2·SD{suffix}"))
    elif previous is not None and previous > 0:
        candidates.append((abs(previous * float(swc_pct) / 100), "SWC fijo", f"SWC fijo {float(swc_pct):g}%"))

    candidates = [c for c in candidates if not math.isnan(c[0])]
    if not candidates:
        return {"threshold_abs": float("nan"), "method": None, "label": None}
    best = candidates[0]
    for candidate in candidates[1:]:
        if candidate[0] > best[0]:
            best = candidate
    return {"threshold_abs": best[0], "method": best[1], "label": best[2]}


CHANGE_THRESHOLD_CAPTION = (
    "Umbral de cambio = max(TE, SWC) en todas las variables. TE: error típico del instrumento "
    "(p. ej. 3% en altura de salto en plataforma) y, desde la tercera medición, el TE "
    "intraindividual. SWC: fijo con menos de 3 mediciones válidas, 0.2·SD individual (Hopkins) "
    "desde la tercera. Gana el mayor y su fuente se rotula entre paréntesis."
)


# ── Regla 6: peso de plataforma invalido ──────────────────────────────────
# La plataforma estima la altura por impulso-momento: a = (F - peso) / masa,
# integrada hasta la velocidad de despegue. Sin un peso valido (Involution
# exporta 0 o nada en algunas tomas) ese calculo arrastra el error a
# velocidad, altura, potencia, impulso y a las fases definidas por la
# velocidad (frenado, propulsion, contraccion). Lo que la app recibe ya viene
# calculado: cargarle un peso despues no lo corrige, por eso se descarta.
# Las fuerzas crudas, el tiempo de vuelo, las asimetrias y la recepcion no
# dependen del peso y se conservan.
# Marcadores: solo se evalua una toma que trae cinematica calculada por la
# plataforma. Una carga manual con solo la altura no se toca.
PLATFORM_BW_FLAG_COLUMN = "BW_platform_flag"
PLATFORM_BW_DETAIL_COLUMN = "BW_platform_detail"
PLATFORM_BW_TESTS: dict[str, dict[str, tuple[str, ...]]] = {
    "CMJ": {
        "markers": (
            "CMJ_takeoff_velocity_m_s",
            "CMJ_peak_power_W",
            "CMJ_rel_impulse",
            "CMJ_contraction_ms",
        ),
        "dependent": (
            "CMJ_cm",
            "CMJ_takeoff_velocity_m_s",
            "CMJ_peak_power_W",
            "CMJ_rel_impulse",
            "CMJ_RSI",
            "CMJ_landing_stiffness_N_m",
            "CMJ_brake_ms",
            "CMJ_conc_ms",
            "CMJ_contraction_ms",
            "CMJ_efficiency_tvtc",
            "CMJ_braking_RFD_N_s",
            "CMJ_propulsive_RFD_N_s",
            # Derivada de la app con la altura descartada.
            "Jump_Momentum",
        ),
    },
    "SJ": {
        "markers": (
            "SJ_takeoff_velocity_m_s",
            "SJ_peak_power_W",
            "SJ_rel_impulse",
            "SJ_conc_ms",
        ),
        "dependent": (
            "SJ_cm",
            "SJ_takeoff_velocity_m_s",
            "SJ_peak_power_W",
            "SJ_rel_impulse",
            "SJ_RSI",
            "SJ_conc_ms",
        ),
    },
}


def _flight_time_height_cm(flight_ms: float | None) -> float | None:
    if flight_ms is None or flight_ms <= 0:
        return None
    seconds = flight_ms / 1000.0
    return GRAVITY_M_S2 * seconds * seconds / 8.0 * 100.0


def _parse_flagged_tests(existing_flag: object) -> list[str]:
    text = str(existing_flag or "").strip()
    if not text or text.lower() == "nan":
        return []
    return [test for test in (part.strip().upper() for part in text.split(",")) if test in PLATFORM_BW_TESTS]


def assess_platform_body_weight(
    row: Mapping[str, object] | pd.Series,
    *,
    source: object = None,
) -> dict[str, object]:
    """Que tests de una toma de plataforma se calcularon sin un peso valido.

    Devuelve {"tests": [...], "flag": "CMJ,SJ" | None, "detail": str | None}.
    `row` debe traer el peso tal como vino del archivo (antes de sanear) para
    poder decir si fue un 0. Re-evaluar un frame ya preparado conserva la
    marca a traves de PLATFORM_BW_FLAG_COLUMN.
    """
    getter = row.get if hasattr(row, "get") else (lambda _key, _default=None: None)
    row_source = source if source is not None else getter("Source")
    existing_tests = _parse_flagged_tests(getter(PLATFORM_BW_FLAG_COLUMN))
    existing_detail = getter(PLATFORM_BW_DETAIL_COLUMN)
    if existing_tests:
        detail = existing_detail if isinstance(existing_detail, str) and existing_detail.strip() else None
        return {"tests": existing_tests, "flag": ",".join(existing_tests), "detail": detail}

    from modules.evaluation_sources import SOURCE_PLATFORM, normalize_source

    if normalize_source(row_source) != SOURCE_PLATFORM:
        return {"tests": [], "flag": None, "detail": None}

    raw_bw = _get(row, "BW_kg")
    bw_valid = sanitize_bw_kg(raw_bw) is not None
    tests: list[str] = []
    reasons: list[str] = []
    heights: list[str] = []
    for test, spec in PLATFORM_BW_TESTS.items():
        if not any(_get(row, column) is not None for column in spec["markers"]):
            continue
        rel_impulse = _get(row, f"{test}_rel_impulse")
        negative_impulse = rel_impulse is not None and rel_impulse < 0
        if bw_valid and not negative_impulse:
            continue
        tests.append(test)
        if negative_impulse:
            reasons.append(f"impulso relativo del {test} negativo ({rel_impulse:.2f}), físicamente imposible")
        exported = _get(row, f"{test}_cm")
        flight_height = _flight_time_height_cm(_get(row, f"{test}_flight_ms"))
        if exported is not None:
            text = f"{test} exportado {exported:.1f} cm"
            if flight_height is not None:
                text += f" (por tiempo de vuelo {flight_height:.1f} cm, otro método, no comparable)"
            heights.append(text)

    if not tests:
        return {"tests": [], "flag": None, "detail": None}

    if raw_bw is None:
        weight_reason = "Involution no exportó el peso corporal"
    elif not bw_valid:
        weight_reason = f"Involution exportó peso corporal {raw_bw:g} kg"
    else:
        weight_reason = None
    all_reasons = ([weight_reason] if weight_reason else []) + reasons
    tests_text = " y ".join(tests)
    detail = (
        f"{'; '.join(all_reasons)}. La plataforma calculó el {tests_text} sin un peso válido: "
        f"se descartan altura, velocidad de despegue, potencia, impulso y fases de esta toma. "
        f"Fuerzas, tiempo de vuelo y asimetrías se conservan."
    )
    if heights:
        detail += f" Dato descartado: {'; '.join(heights)}."
    return {"tests": tests, "flag": ",".join(tests), "detail": detail}


def apply_platform_body_weight_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Marca y anula las metricas CMJ/SJ calculadas sin peso valido.

    Corre ANTES de sanear el peso, para distinguir un 0 exportado de un vacio.
    El dato crudo queda en la base: al guardar, los NaN no se escriben.
    """
    if df is None or df.empty:
        return df
    flags: list[object] = []
    details: list[object] = []
    for _, row in df.iterrows():
        result = assess_platform_body_weight(row)
        flags.append(result["flag"])
        details.append(result["detail"])
    df[PLATFORM_BW_FLAG_COLUMN] = pd.Series(flags, index=df.index, dtype=object)
    df[PLATFORM_BW_DETAIL_COLUMN] = pd.Series(details, index=df.index, dtype=object)
    for test, spec in PLATFORM_BW_TESTS.items():
        mask = df[PLATFORM_BW_FLAG_COLUMN].map(lambda value, t=test: t in _parse_flagged_tests(value))
        if mask.any():
            for column in spec["dependent"]:
                if column in df.columns:
                    df.loc[mask, column] = np.nan
    return df


def platform_body_weight_label(row: Mapping[str, object] | pd.Series | None) -> str | None:
    if row is None:
        return None
    return assess_platform_body_weight(row).get("detail")  # type: ignore[return-value]


def platform_body_weight_upload_warning(
    record: Mapping[str, object],
    *,
    test_type: str,
    source: object,
) -> str | None:
    """Aviso al cargar una toma CMJ/SJ de plataforma sin peso valido."""
    if str(test_type or "").strip().upper() not in PLATFORM_BW_TESTS:
        return None
    result = assess_platform_body_weight(record, source=source)
    return result.get("detail")  # type: ignore[return-value]


# ── Regla 6b: altura por impulso inconsistente con el tiempo de vuelo ─────
# La plataforma informa la altura por impulso-momento (v_despegue^2 / 2g, con
# v integrada desde (F - peso) / masa). El tiempo de vuelo da otra estimacion
# independiente del peso: h = g * t^2 / 8. Las dos difieren poco en una toma
# bien hecha (el vuelo sobreestima algo por la postura de aterrizaje: Moir
# 2008, Meas Phys Educ Exerc Sci 12:207-218). Un error de pocos kg en la fase
# de pesaje se integra durante todo el impulso y desplaza la velocidad de
# despegue (Street et al. 2001, J Appl Biomech 17:43-54): una diferencia
# mayor a max(3 cm, 8% de la altura por vuelo) no es ruido de tecnica.
# Esa altura no entra a radar, z-score, cohorte ni comparaciones. El dato
# crudo queda en la base (los NaN no se escriben al guardar); la altura por
# vuelo se conserva aparte solo para mostrarla rotulada en el PDF profe.
JUMP_HEIGHT_FLAG_COLUMN = "Jump_height_flag"
JUMP_HEIGHT_DETAIL_COLUMN = "Jump_height_detail"
JUMP_HEIGHT_TESTS = ("CMJ", "SJ")
JUMP_HEIGHT_MIN_DIFF_CM = 3.0
JUMP_HEIGHT_MIN_DIFF_PCT = 8.0
JUMP_HEIGHT_REASON = (
    "altura por impulso inconsistente con tiempo de vuelo "
    "(probable error de peso en la fase de pesaje)"
)
# Metricas de la app que salen de la altura descartada.
JUMP_HEIGHT_DEPENDENT: dict[str, tuple[str, ...]] = {
    "CMJ": ("CMJ_cm", "Jump_Momentum", "EUR"),
    "SJ": ("SJ_cm", "EUR"),
}


def jump_height_reported_column(test: str) -> str:
    return f"{test}_cm_reported"


def jump_height_flight_column(test: str) -> str:
    return f"{test}_flight_height_cm"


def flight_time_height_cm(flight_ms: object) -> float | None:
    """h = g * t^2 / 8 (cm). Independiente del peso corporal."""
    return _flight_time_height_cm(_number(flight_ms))


def jump_height_tolerance_cm(flight_height_cm: float) -> float:
    return max(JUMP_HEIGHT_MIN_DIFF_CM, abs(flight_height_cm) * JUMP_HEIGHT_MIN_DIFF_PCT / 100.0)


def is_jump_height_inconsistent(reported_cm: object, flight_ms: object) -> bool:
    reported = _number(reported_cm)
    flight_height = flight_time_height_cm(flight_ms)
    if reported is None or flight_height is None:
        return False
    return abs(reported - flight_height) > jump_height_tolerance_cm(flight_height)


def _jump_height_detail(items: list[dict[str, object]]) -> str:
    parts = [
        f"{item['test']}: informada {float(item['reported']):.1f} cm vs "
        f"por tiempo de vuelo {float(item['flight']):.1f} cm"
        for item in items
    ]
    return (
        f"{JUMP_HEIGHT_REASON[0].upper()}{JUMP_HEIGHT_REASON[1:]}. {'; '.join(parts)}. "
        "La altura informada no entra a radar, z-score, cohorte ni comparaciones."
    )


def assess_jump_height_consistency(row: Mapping[str, object] | pd.Series) -> dict[str, object]:
    """Que alturas CMJ/SJ de una toma de plataforma no cierran con su vuelo.

    Devuelve {"tests": [...], "flag": "CMJ,SJ" | None, "detail": str | None,
    "items": [{"test", "reported", "flight"}]}. Re-evaluar un frame ya
    preparado conserva la marca (la altura ya quedo en NaN).
    """
    getter = row.get if hasattr(row, "get") else (lambda _key, _default=None: None)
    existing_text = str(getter(JUMP_HEIGHT_FLAG_COLUMN) or "").strip()
    existing = [
        part.strip().upper()
        for part in existing_text.split(",")
        if existing_text.lower() != "nan" and part.strip().upper() in JUMP_HEIGHT_TESTS
    ]
    if existing:
        items = [
            {
                "test": test,
                "reported": _get(row, jump_height_reported_column(test)),
                "flight": _get(row, jump_height_flight_column(test)),
            }
            for test in existing
        ]
        detail = getter(JUMP_HEIGHT_DETAIL_COLUMN)
        if not isinstance(detail, str) or not detail.strip() or detail.strip().lower() == "nan":
            complete = [item for item in items if item["reported"] is not None and item["flight"] is not None]
            detail = _jump_height_detail(complete) if complete else JUMP_HEIGHT_REASON
        return {"tests": existing, "flag": ",".join(existing), "detail": detail, "items": items}

    from modules.evaluation_sources import SOURCE_PLATFORM, normalize_source

    if normalize_source(getter("Source")) != SOURCE_PLATFORM:
        return {"tests": [], "flag": None, "detail": None, "items": []}

    items: list[dict[str, object]] = []
    for test in JUMP_HEIGHT_TESTS:
        reported = _get(row, f"{test}_cm")
        flight_ms = _get(row, f"{test}_flight_ms")
        if not is_jump_height_inconsistent(reported, flight_ms):
            continue
        items.append({"test": test, "reported": reported, "flight": flight_time_height_cm(flight_ms)})
    if not items:
        return {"tests": [], "flag": None, "detail": None, "items": []}
    tests = [str(item["test"]) for item in items]
    return {"tests": tests, "flag": ",".join(tests), "detail": _jump_height_detail(items), "items": items}


def apply_jump_height_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """Marca y saca de todo calculo las alturas CMJ/SJ inconsistentes con el vuelo.

    Corre despues de la regla 6 (una toma sin peso valido ya perdio la altura
    y se rotula por esa causa). Guarda la altura informada y la de vuelo en
    columnas propias, que no se persisten.
    """
    if df is None or df.empty:
        return df
    flags: list[object] = []
    details: list[object] = []
    reported_values: dict[str, list[float]] = {test: [] for test in JUMP_HEIGHT_TESTS}
    flight_values: dict[str, list[float]] = {test: [] for test in JUMP_HEIGHT_TESTS}
    for _, row in df.iterrows():
        result = assess_jump_height_consistency(row)
        flags.append(result["flag"])
        details.append(result["detail"])
        by_test = {item["test"]: item for item in result["items"]}  # type: ignore[union-attr]
        for test in JUMP_HEIGHT_TESTS:
            item = by_test.get(test)
            reported_values[test].append(np.nan if item is None or item["reported"] is None else float(item["reported"]))
            flight_values[test].append(np.nan if item is None or item["flight"] is None else float(item["flight"]))
    df[JUMP_HEIGHT_FLAG_COLUMN] = pd.Series(flags, index=df.index, dtype=object)
    df[JUMP_HEIGHT_DETAIL_COLUMN] = pd.Series(details, index=df.index, dtype=object)
    for test in JUMP_HEIGHT_TESTS:
        df[jump_height_reported_column(test)] = pd.Series(reported_values[test], index=df.index, dtype=float)
        df[jump_height_flight_column(test)] = pd.Series(flight_values[test], index=df.index, dtype=float)
        mask = df[jump_height_reported_column(test)].notna()
        if mask.any():
            for column in JUMP_HEIGHT_DEPENDENT[test]:
                if column in df.columns:
                    df.loc[mask, column] = np.nan
    return df


def jump_height_consistency_label(row: Mapping[str, object] | pd.Series | None) -> str | None:
    """Rotulo corto para dashboard y PDF de atleta/cliente: sin la altura por
    vuelo, que solo se muestra (rotulada) en el PDF profe."""
    if row is None:
        return None
    tests = assess_jump_height_consistency(row).get("tests") or []
    if not tests:
        return None
    return (
        f"{' y '.join(tests)}: {JUMP_HEIGHT_REASON}. "
        "Esa altura no entra a radar, z-score, cohorte ni comparaciones."
    )


def jump_height_consistency_rows(df: pd.DataFrame | None) -> list[dict[str, object]]:
    """Tomas marcadas, con ambas alturas, para listarlas (PDF profe)."""
    if df is None or df.empty or JUMP_HEIGHT_FLAG_COLUMN not in df.columns:
        return []
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        result = assess_jump_height_consistency(row)
        for item in result["items"]:  # type: ignore[union-attr]
            if item["reported"] is None or item["flight"] is None:
                continue
            rows.append(
                {
                    "Athlete": row.get("Athlete"),
                    "Date": row.get("Date"),
                    "Test": item["test"],
                    "reported_cm": float(item["reported"]),
                    "flight_height_cm": float(item["flight"]),
                }
            )
    return rows


# ── Regla 7: peso de una evaluacion cercana ───────────────────────────────
# Sin peso valido, la fuerza relativa del IMTP y el momentum no existen. Si
# el mismo atleta tiene un peso medido a <= 14 dias, se usa ese y se rotula de
# donde salio. Va en columnas propias (no en BW_kg) para que nunca se guarde
# en la base como si fuera medido, y no rescata nada de la regla 6: lo que la
# plataforma calculo sin peso sigue descartado.
BW_IMPUTE_WINDOW_DAYS = 14
BW_IMPUTED_COLUMN = "BW_kg_imputed"
BW_IMPUTED_FROM_COLUMN = "BW_kg_imputed_from"


def impute_body_weight(df: pd.DataFrame, *, window_days: int = BW_IMPUTE_WINDOW_DAYS) -> pd.DataFrame:
    if df is None or df.empty or not {"Athlete", "Date"}.issubset(df.columns):
        return df
    measured = sanitize_bw_kg_series(df["BW_kg"]) if "BW_kg" in df.columns else pd.Series(np.nan, index=df.index)
    dates = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    imputed = pd.Series(np.nan, index=df.index, dtype=float)
    imputed_from = pd.Series(None, index=df.index, dtype=object)
    for idx in df.index[measured.isna() & dates.notna()]:
        same = (df["Athlete"] == df.at[idx, "Athlete"]) & measured.notna() & dates.notna()
        same.loc[idx] = False
        if not same.any():
            continue
        gaps = (dates[same] - dates.loc[idx]).dt.days
        close = gaps[gaps.abs() <= window_days]
        if close.empty:
            continue
        # El mas cercano; a igual distancia, el anterior (peso ya conocido).
        best = sorted(close.items(), key=lambda item: (abs(item[1]), item[1] > 0))[0][0]
        imputed.loc[idx] = float(measured.loc[best])
        imputed_from.loc[idx] = dates.loc[best].strftime("%d/%m/%Y")
    df[BW_IMPUTED_COLUMN] = imputed
    df[BW_IMPUTED_FROM_COLUMN] = imputed_from
    return df


def effective_bw_kg_series(df: pd.DataFrame) -> pd.Series:
    """Peso medido valido; si falta, el de una evaluacion cercana (regla 7)."""
    if "BW_kg" in df.columns:
        measured = sanitize_bw_kg_series(df["BW_kg"])
    else:
        measured = pd.Series(np.nan, index=df.index, dtype=float)
    if BW_IMPUTED_COLUMN in df.columns:
        measured = measured.fillna(sanitize_bw_kg_series(df[BW_IMPUTED_COLUMN]))
    return measured


def imputed_body_weight_label(row: Mapping[str, object] | pd.Series | None) -> str | None:
    if row is None or not hasattr(row, "get"):
        return None
    if sanitize_bw_kg(row.get("BW_kg")) is not None:
        return None
    value = sanitize_bw_kg(row.get(BW_IMPUTED_COLUMN))
    source_date = row.get(BW_IMPUTED_FROM_COLUMN)
    if value is None or not isinstance(source_date, str) or not source_date.strip():
        return None
    return (
        f"Peso tomado de la evaluación del {source_date} ({value:.1f} kg): "
        "la fuerza relativa y el momentum usan ese peso"
    )


# ── Regla 8: toma duplicada con fecha distinta ────────────────────────────
# Dos tomas reales no repiten exactamente varias metricas. Con los datos de
# noviembre 2026: los IMTP duplicados con el anio corrido coincidian en 17/17
# metricas; el par real mas parecido, en 2/8 (DJ de Gray: altura y tiempo de
# vuelo, que son el mismo dato porque la altura sale del vuelo). Por eso,
# ademas del minimo de 3, se pide que coincida al menos la mitad de lo
# comparable: una metrica derivada repetida no alcanza para bloquear.
DUPLICATE_MIN_MATCHES = 3
DUPLICATE_MIN_SHARE = 0.5
# Valores fijos del protocolo: coinciden siempre y no identifican la toma.
DUPLICATE_EXCLUDED_COLUMNS = frozenset({"BW_kg", "DJ_drop_height_cm"})
DUPLICATE_EXCLUDED_SUFFIXES = ("_time_pull_s",)


def _duplicate_comparable_columns(columns: Iterable[str]) -> list[str]:
    return [
        column
        for column in columns
        if column not in DUPLICATE_EXCLUDED_COLUMNS
        and not column.endswith(DUPLICATE_EXCLUDED_SUFFIXES)
        and not column.startswith("__")
        and not column.endswith("_reps")
        and column not in {"Athlete", "Date", "Source", "Device", "test_type"}
    ]


def _row_date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def find_duplicate_takes(
    record: Mapping[str, object],
    candidates: Iterable[Mapping[str, object] | pd.Series],
    *,
    metric_columns: Iterable[str],
) -> list[dict[str, object]]:
    """Tomas del mismo atleta y fuente, en OTRA fecha, con los mismos valores.

    `metric_columns` son las metricas del test que se esta cargando. Devuelve
    una lista (vacia si no hay duplicado) con fecha, coincidencias y columnas.
    La misma fecha no cuenta: eso es superponer una toma, no duplicarla.
    """
    from modules.athlete_names import normalize_athlete_name
    from modules.evaluation_sources import normalize_source

    athlete = normalize_athlete_name(record.get("Athlete"))
    source = normalize_source(record.get("Source"))
    record_date = _row_date(record.get("Date"))
    columns = _duplicate_comparable_columns(metric_columns)
    own_values = {column: _number(record.get(column)) for column in columns}
    own_values = {column: value for column, value in own_values.items() if value is not None}
    if not athlete or record_date is None or len(own_values) < DUPLICATE_MIN_MATCHES:
        return []

    found: dict[pd.Timestamp, dict[str, object]] = {}
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "get"):
            continue
        if normalize_athlete_name(candidate.get("Athlete")) != athlete:
            continue
        if normalize_source(candidate.get("Source")) != source:
            continue
        candidate_date = _row_date(candidate.get("Date"))
        if candidate_date is None or candidate_date == record_date:
            continue
        comparable = 0
        matched: list[str] = []
        for column, value in own_values.items():
            other = _number(candidate.get(column))
            if other is None:
                continue
            comparable += 1
            if math.isclose(value, other, rel_tol=1e-9, abs_tol=1e-9):
                matched.append(column)
        if len(matched) < DUPLICATE_MIN_MATCHES or comparable == 0:
            continue
        if len(matched) / comparable < DUPLICATE_MIN_SHARE:
            continue
        previous = found.get(candidate_date)
        if previous is None or len(matched) > len(previous["columns"]):
            found[candidate_date] = {
                "date": candidate_date,
                "matches": len(matched),
                "comparable": comparable,
                "columns": matched,
            }
    return [found[key] for key in sorted(found)]


def duplicate_take_message(duplicates: list[dict[str, object]]) -> str | None:
    """Texto de bloqueo: 'posible toma duplicada con fecha distinta (DD/MM/AAAA)'."""
    if not duplicates:
        return None
    parts = []
    for item in duplicates:
        columns = list(item["columns"])  # type: ignore[arg-type]
        shown = ", ".join(columns[:3]) + ("…" if len(columns) > 3 else "")
        parts.append(
            f"posible toma duplicada con fecha distinta ({item['date']:%d/%m/%Y}): "
            f"{item['matches']} de {item['comparable']} métricas idénticas ({shown})"
        )
    return (
        "; ".join(parts)
        + ". No se guardó. Si la fecha correcta es la otra, borrá o corregí esa toma antes de cargar esta."
    )


def _history_rows(history: object) -> list[Mapping[str, object]]:
    if history is None:
        return []
    if isinstance(history, pd.DataFrame):
        if history.empty:
            return []
        return [row for _, row in history.iterrows()]
    return [row for row in history if hasattr(row, "get")]  # type: ignore[union-attr]


def check_duplicate_take(
    record: Mapping[str, object],
    *,
    history: object = None,
    pending: Iterable[Mapping[str, object]] = (),
    metric_columns: Iterable[str] | None = None,
) -> str | None:
    """Mensaje de bloqueo si `record` repite una toma ya guardada o en cola."""
    columns = list(metric_columns) if metric_columns is not None else list(record.get("__metric_fields") or [])
    candidates = _history_rows(history) + [item for item in pending if item is not record]
    return duplicate_take_message(find_duplicate_takes(record, candidates, metric_columns=columns))


# ── Regla 9: fecha de evaluacion elegida a proposito ─────────────────────
# El archivo de Involution no trae fecha: la pone quien carga. Con el selector
# en "hoy" por defecto y el anio facil de errar, entraron tomas con el anio
# corrido (IMTP 2025 en vez de 2026) y fechas de carga en vez de evaluacion.
# El selector arranca vacio, y una fecha vieja (> 90 dias), de otro anio o
# futura pide confirmacion explicita antes de agregarse a la cola.
EVAL_DATE_CONFIRM_DAYS = 90


def evaluation_date_check(value: object, today: object = None) -> dict[str, object]:
    """{'missing', 'needs_confirmation', 'reason'} para la fecha elegida."""
    if today is None:
        from modules.app_clock import app_today

        today = app_today()
    reference = _row_date(today)
    chosen = _row_date(value) if value is not None else None
    if chosen is None or reference is None:
        return {"missing": chosen is None, "needs_confirmation": False, "reason": None}
    reasons: list[str] = []
    age_days = (reference - chosen).days
    if age_days < 0:
        reasons.append("es una fecha futura")
    elif age_days > EVAL_DATE_CONFIRM_DAYS:
        reasons.append(f"tiene {age_days} días (más de {EVAL_DATE_CONFIRM_DAYS})")
    if chosen.year != reference.year:
        reasons.append(f"es de {chosen.year}, no de {reference.year}")
    if not reasons:
        return {"missing": False, "needs_confirmation": False, "reason": None}
    return {
        "missing": False,
        "needs_confirmation": True,
        "reason": f"La fecha {chosen:%d/%m/%Y} {' y '.join(reasons)}",
    }
