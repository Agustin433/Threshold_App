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
    if df is None or df.empty or "IMTP_N" not in df.columns or "BW_kg" not in df.columns:
        return df
    peak = pd.to_numeric(df["IMTP_N"], errors="coerce")
    bw = sanitize_bw_kg_series(df["BW_kg"])
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
