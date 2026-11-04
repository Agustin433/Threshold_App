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


def resolve_change_threshold(
    variable: str,
    previous_value: object,
    history_values: Iterable[object],
    *,
    swc_pct: float,
) -> dict[str, object]:
    """Umbral minimo de cambio real y su fuente.

    - Con >= 3 mediciones validas: max(0.2*SD intraindividual [Hopkins],
      TE intraindividual = SD de las diferencias sucesivas / sqrt(2)).
    - Con menos: max(SWC fijo, TE tipico del instrumento), ambos como % del
      valor anterior. Un umbral por debajo del ruido de medicion convierte el
      error en "cambio".
    """
    previous = _number(previous_value)
    values = [v for v in (_number(x) for x in history_values) if v is not None]
    n_valid = len(values)

    if n_valid >= INTRAINDIVIDUAL_MIN_VALID:
        sd = float(np.std(values, ddof=1))
        swc_abs = abs(0.2 * sd)
        diffs = np.diff(values)
        te_abs = float(np.std(diffs, ddof=1) / math.sqrt(2)) if len(diffs) >= 2 else float("nan")
        if not math.isnan(te_abs) and te_abs > swc_abs:
            return {
                "threshold_abs": te_abs,
                "method": "TE intraindividual",
                "label": f"TE intraindividual, N={n_valid}",
            }
        return {
            "threshold_abs": swc_abs,
            "method": "Hopkins",
            "label": f"Hopkins 0.2·SD, N={n_valid}",
        }

    if previous is None or previous <= 0:
        return {"threshold_abs": float("nan"), "method": None, "label": None}
    te_pct = INSTRUMENT_TYPICAL_ERROR_PCT.get(variable, DEFAULT_INSTRUMENT_TYPICAL_ERROR_PCT)
    swc_abs = abs(previous * float(swc_pct) / 100)
    te_abs = abs(previous * float(te_pct) / 100)
    if te_abs >= swc_abs:
        return {
            "threshold_abs": te_abs,
            "method": "TE instrumento",
            "label": f"TE instrumento {te_pct:g}%",
        }
    return {
        "threshold_abs": swc_abs,
        "method": "SWC fijo",
        "label": f"SWC fijo {float(swc_pct):g}%",
    }


CHANGE_THRESHOLD_CAPTION = (
    "Umbral de cambio: con menos de 3 mediciones válidas se usa el mayor entre el SWC fijo y el "
    "error típico del instrumento (p. ej. 3% en altura de salto en plataforma); desde la tercera "
    "medición, el mayor entre 0.2·SD individual (Hopkins) y el TE intraindividual. La fuente "
    "se rotula entre paréntesis."
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
