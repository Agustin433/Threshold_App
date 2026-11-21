"""Columna "vs estudios" del ranking de Equipo (PR R).

Es una lectura SEPARADA del z de gimnasio: nunca entra al orden del ranking ni
a la cohorte. Responde "a que porcentaje del promedio publicado de una
poblacion de referencia esta este atleta".

Por que una tabla propia y no `REFERENCE_TABLES`: sumar Ripley o Radovic alli
haria que esos atletas resuelvan LITERATURE_Z antes que la cohorte en toda la
app (radar, PDF) y perderian su z de gimnasio. Aca solo se usan para el % de
contexto; el z publicado se agrega solo si la poblacion coincide en deporte,
nivel, sexo, instrumento y era (la misma regla de LITERATURE_Z).

Solo entradas verificadas contra el paper. IMTP no tiene entrada hasta
validar la plataforma: la era Involution da ~30% mas que Valkyria y no hay
forma honesta de anclarlo a una tabla publicada todavia.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from modules.athlete_profile import (
    DEMAND_GENERAL,
    Sexo,
    demand_group,
    normalize_deporte,
    normalize_sexo,
    primary_deporte,
)
from modules.evaluation_sources import SOURCE_PLATFORM, normalize_source
from modules.measurement_eras import ERA_INVOLUTION_STRAPS

STUDY_EMPTY = "-"
STUDY_LEGEND = (
    "vs estudios = % del promedio publicado de una población de referencia; "
    "con nivel distinto es contexto, no meta."
)
STUDY_NOT_COMPARABLE_NOTE = (
    "Sin % para tomas de alfombra/MyJump o de la era Valkyria: los estudios se "
    "midieron en plataforma por impulso-momento, con pesaje correcto."
)

# Metricas de la app con tabla publicada. CMJ_mRSI es el RSI-mod real
# (altura por vuelo / tiempo de contraccion, m/s). CMJ_RSI es el "RSI" de
# Valkyria (otra definicion, 1.15-1.74): NUNCA se compara con estudios.
STUDY_METRICS: tuple[str, ...] = ("CMJ_cm", "CMJ_mRSI")
NEVER_COMPARED_WITH_STUDIES: frozenset[str] = frozenset({"CMJ_RSI"})

_MCMAHON = "McMahon et al. 2022, Sensors 22(22):8669, doi:10.3390/s22228669"
_RIPLEY = "Ripley et al. 2025, Biomechanics 5(2):32"
_RADOVIC = "Radovic et al. 2024, Front Sports Act Living"

# Las alturas por impulso con Valkyria estan infladas (+3 a +5 cm): solo la
# era Involution es comparable con una plataforma de investigacion.
_COMPARABLE_ERAS = (ERA_INVOLUTION_STRAPS,)


def _entry(metric, deporte, nivel, sexo, subgroup, mean, sd, n, cite, source):
    return {
        "metric": metric,
        "deporte": deporte,
        "nivel": nivel,
        "sexo": sexo,
        "instrument_class": SOURCE_PLATFORM,
        "eras": _COMPARABLE_ERAS,
        "subgroup": subgroup,
        "mean": mean,
        "sd": sd,
        "n": n,
        "cite": cite,
        "source": source,
    }


STUDY_REFERENCES: tuple[dict[str, object], ...] = (
    # McMahon 2022: rugby league profesional, Kistler, impulso-momento.
    _entry("CMJ_cm", "Rugby League", "Alto rendimiento", Sexo.MASCULINO, "forwards", 34.1, 4.2, 66,
           "McMahon 2022, rugby league pro (forwards)", _MCMAHON),
    _entry("CMJ_cm", "Rugby League", "Alto rendimiento", Sexo.MASCULINO, "backs", 36.4, 4.5, 55,
           "McMahon 2022, rugby league pro (backs)", _MCMAHON),
    _entry("CMJ_mRSI", "Rugby League", "Alto rendimiento", Sexo.MASCULINO, "forwards", 0.44, 0.08, 66,
           "McMahon 2022, rugby league pro (forwards)", _MCMAHON),
    _entry("CMJ_mRSI", "Rugby League", "Alto rendimiento", Sexo.MASCULINO, "backs", 0.49, 0.08, 55,
           "McMahon 2022, rugby league pro (backs)", _MCMAHON),
    # Ripley 2025: futbol pro/semipro, Hawkin; combinado de la tabla 2.
    _entry("CMJ_cm", "Fútbol", "Alto rendimiento", Sexo.MASCULINO, "pro/semipro", 38.5, 5.5, 76,
           "Ripley 2025, fútbol semi/pro", _RIPLEY),
    _entry("CMJ_mRSI", "Fútbol", "Alto rendimiento", Sexo.MASCULINO, "pro/semipro", 0.58, 0.11, 76,
           "Ripley 2025, fútbol semi/pro", _RIPLEY),
    # Radovic 2024: handball profesional femenino, VALD.
    _entry("CMJ_cm", "Handball", "Alto rendimiento", Sexo.FEMENINO, "pro", 26.7, 4.0, 42,
           "Radovic 2024, handball pro fem.", _RADOVIC),
    _entry("CMJ_mRSI", "Handball", "Alto rendimiento", Sexo.FEMENINO, "pro", 0.376, 0.091, 42,
           "Radovic 2024, handball pro fem.", _RADOVIC),
)


@dataclass(frozen=True)
class StudyComparison:
    text: str
    pct: float | None = None
    z: float | None = None
    reference: dict[str, object] | None = None
    # "", "sin_tabla", "sin_valor", "instrumento", "era"
    reason: str = ""

    @property
    def not_comparable(self) -> bool:
        return self.reason in {"instrumento", "era"}


def _key(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def closest_study(metric: str, *, deporte: object, sexo: object) -> dict[str, object] | None:
    """Tabla publicada mas cercana: mismo deporte y sexo; si no, mismo grupo de demanda y sexo.

    Empates (varios subgrupos o varios deportes del grupo): la de mayor n.
    Sin sexo, sin deporte reconocido o fuera de los grupos con tabla: None.
    """
    sexo_key = normalize_sexo(sexo)
    if sexo_key is Sexo.NO_ESPECIFICADO or metric not in STUDY_METRICS or metric in NEVER_COMPARED_WITH_STUDIES:
        return None
    candidates = [
        entry for entry in STUDY_REFERENCES
        if entry["metric"] == metric and normalize_sexo(entry["sexo"]) is sexo_key
    ]
    if not candidates:
        return None
    sport = _key(primary_deporte(deporte))
    same_sport = [entry for entry in candidates if sport and _key(primary_deporte(entry["deporte"])) == sport]
    if same_sport:
        pool = same_sport
    else:
        group = demand_group(deporte)
        if group == DEMAND_GENERAL:
            return None
        pool = [entry for entry in candidates if demand_group(entry["deporte"]) == group]
    if not pool:
        return None
    return dict(max(pool, key=lambda entry: int(entry.get("n") or 0)))


def _same_population(entry: dict[str, object], profile: dict[str, object]) -> bool:
    return (
        _key(normalize_deporte(profile.get("Deporte"))) == _key(entry["deporte"])
        and _key(profile.get("Nivel")) == _key(entry["nivel"])
        and normalize_sexo(profile.get("Sexo")) is normalize_sexo(entry["sexo"])
    )


def study_comparison(
    metric: str,
    value: object,
    *,
    profile: dict[str, object] | None,
    source: object = SOURCE_PLATFORM,
    era: object = None,
) -> StudyComparison:
    """Celda "vs estudios": "87% · Ripley 2025, fútbol semi/pro" (+ z si la poblacion coincide)."""
    profile = profile or {}
    entry = closest_study(metric, deporte=profile.get("Deporte"), sexo=profile.get("Sexo"))
    if entry is None:
        return StudyComparison(STUDY_EMPTY, reason="sin_tabla")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = math.nan
    if math.isnan(numeric) or numeric <= 0:
        return StudyComparison(STUDY_EMPTY, reference=entry, reason="sin_valor")
    if normalize_source(source) != normalize_source(entry["instrument_class"]):
        return StudyComparison(STUDY_EMPTY, reference=entry, reason="instrumento")
    if era is not None and str(era) not in tuple(entry["eras"]):
        return StudyComparison(STUDY_EMPTY, reference=entry, reason="era")
    pct = numeric / float(entry["mean"]) * 100.0
    text = f"{pct:.0f}% · {entry['cite']}"
    z = None
    if _same_population(entry, profile):
        z = (numeric - float(entry["mean"])) / float(entry["sd"])
        text += f" · z {z:+.1f}"
    return StudyComparison(text, pct=pct, z=z, reference=entry)


# ── Tabla del ranking ──────────────────────────────────────────────────────
COHORT_Z_SOURCE = "cohort_z"
COL_ATHLETE = "Atleta"
COL_VALUE = "Valor"
COL_GYM_Z = "z gimnasio"
COL_STUDIES = "vs estudios"

# (etiqueta, columna de valor, campo de z canonico)
RANKING_METRICS: tuple[tuple[str, str, str], ...] = (
    ("CMJ (cm)", "CMJ_cm", "CMJ_Z"),
    ("RSI-mod CMJ (vuelo / contracción, m/s)", "CMJ_mRSI", "CMJ_mRSI_Z"),
    ("SJ (cm)", "SJ_cm", "SJ_Z"),
    ("DJ tiempo de contacto (ms)", "DJ_tc_ms", "TC_inv_Z"),
    ("EUR (CMJ/SJ)", "EUR", "EUR_Z"),
    ("DRI", "DRI", "DRI_Z"),
    ("IMTP relativo (N/kg)", "IMTP_relPF", "IMTP_relPF_Z"),
)


def build_ranking_table(
    latest,
    value_col: str,
    z_field: str,
    *,
    profile_lookup: dict[str, dict[str, object]] | None,
    default_source: object = SOURCE_PLATFORM,
):
    """Atleta | Valor | z gimnasio | vs estudios, ordenado SOLO por z gimnasio.

    "z gimnasio" es el z de cohorte propia (>= 8, mismo sexo e instrumento);
    cualquier otro origen queda vacio. "vs estudios" no participa del orden.
    Devuelve (tabla, hubo_tomas_no_comparables).
    """
    import pandas as pd

    from modules.jump_analysis import resolve_zscore
    from modules.measurement_eras import resolve_era

    profile_lookup = profile_lookup or {}
    rows: list[dict[str, object]] = []
    not_comparable = False
    if latest is None or getattr(latest, "empty", True) or value_col not in latest.columns:
        return pd.DataFrame(columns=[COL_ATHLETE, COL_VALUE, COL_GYM_Z, COL_STUDIES]), False
    for _, row in latest.iterrows():
        athlete = str(row.get("Athlete") or "").strip()
        value = pd.to_numeric(pd.Series([row.get(value_col)]), errors="coerce").iloc[0]
        gym_z = resolve_zscore(row, z_field)
        if str(row.get(f"{z_field}_source") or "") != COHORT_Z_SOURCE:
            gym_z = None
        source = row.get("Source")
        if source is None or (isinstance(source, float) and math.isnan(source)) or not str(source).strip():
            source = default_source
        era = resolve_era(row.get("Device"), row.get("Date"), source)
        comparison = study_comparison(
            value_col, value, profile=profile_lookup.get(athlete), source=source, era=era,
        )
        not_comparable = not_comparable or comparison.not_comparable
        rows.append({
            COL_ATHLETE: athlete,
            COL_VALUE: None if pd.isna(value) else float(value),
            COL_GYM_Z: None if gym_z is None or pd.isna(gym_z) else round(float(gym_z), 2),
            COL_STUDIES: comparison.text,
        })
    table = pd.DataFrame(rows, columns=[COL_ATHLETE, COL_VALUE, COL_GYM_Z, COL_STUDIES])
    table[COL_GYM_Z] = pd.to_numeric(table[COL_GYM_Z], errors="coerce")
    table = table.sort_values(
        [COL_GYM_Z, COL_ATHLETE], ascending=[False, True], na_position="last", kind="mergesort"
    ).reset_index(drop=True)
    return table, not_comparable
