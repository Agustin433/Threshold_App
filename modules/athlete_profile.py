"""Domain helpers for athlete profiles: options, keyword suggestions and validation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd


CONTEXTO_OPTIONS: tuple[str, ...] = ("Club", "Gimnasio")

NIVEL_OPTIONS: tuple[str, ...] = (
    "Población general",
    "Recreativo",
    "Competitivo",
    "Alto rendimiento",
)

OBJETIVO_OPTIONS: tuple[str, ...] = (
    "Rendimiento deportivo específico",
    "Fuerza máxima",
    "Recomposición corporal",
    "Hipertrofia",
    "Prevención de lesiones",
    "Rehabilitación y retorno deportivo (RTP)",
    "Resistencia física",
    "Salud general y calidad de vida",
    "Otro",
)

OBJECTIVE_KEYWORDS: dict[str, list[str]] = {
    "Rendimiento deportivo específico": [
        "velocidad", "sprint", "rendimiento", "competir",
        "torneo", "partido", "temporada",
    ],
    "Prevención de lesiones": [
        "dolor", "molestia", "lesion", "lesión",
        "prevenir", "cuidar",
    ],
    "Rehabilitación y retorno deportivo (RTP)": [
        "rehabilitacion", "rehabilitación", "post-operatorio",
        "postoperatorio", "vuelta", "retorno", "cirugia", "cirugía",
    ],
    "Recomposición corporal": [
        "estetica", "estética", "verse", "bajar de peso",
        "definicion", "definición",
    ],
}

ATHLETE_PROFILE_COLUMNS: list[str] = [
    "Athlete",
    "Fecha_nacimiento",
    "Altura_cm",
    "Peso_kg",
    "Contexto",
    "Deporte",
    "Nivel",
    "Objetivo_primario",
    "Objetivos_secundarios",
    "Objetivo_otro_texto",
    "Es_RTP",
    "Fecha_actualizacion",
]

REQUIRED_PROFILE_FIELDS: tuple[str, ...] = ("Contexto", "Nivel", "Objetivo_primario")

FIELD_LABELS: dict[str, str] = {
    "Athlete": "Nombre del atleta",
    "Contexto": "Contexto",
    "Nivel": "Nivel",
    "Objetivo_primario": "Objetivo primario",
}

SECONDARY_OBJECTIVES_DELIMITER = "|"


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return not text or text.lower() == "nan"


def suggest_objective_from_text(text: str) -> str | None:
    """Suggest an objective from free text via keyword substring match.

    Returns the suggested objective label to show as a confirmation prompt
    in the UI ("Quisiste decir X?"). Never assigns it automatically.
    """
    if not text:
        return None
    lowered = text.strip().casefold()
    if not lowered:
        return None

    for objective, keywords in OBJECTIVE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lowered:
                return objective
    return None


def secondary_objective_options(primary: str | None) -> list[str]:
    return [option for option in OBJETIVO_OPTIONS if option != primary]


def serialize_secondary_objectives(values: Iterable[str] | None) -> str:
    if not values:
        return ""
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return SECONDARY_OBJECTIVES_DELIMITER.join(cleaned)


def parse_secondary_objectives(value: object) -> list[str]:
    if _is_blank(value):
        return []
    return [item.strip() for item in str(value).split(SECONDARY_OBJECTIVES_DELIMITER) if item.strip()]


def _field_value(row: Mapping[str, object] | pd.Series, field: str) -> object:
    if isinstance(row, pd.Series):
        return row.get(field)
    if isinstance(row, Mapping):
        return row.get(field)
    return getattr(row, field, None)


def missing_profile_fields(row: Mapping[str, object] | pd.Series) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_PROFILE_FIELDS:
        if _is_blank(_field_value(row, field)):
            missing.append(FIELD_LABELS.get(field, field))
    return missing


def is_profile_complete(row: Mapping[str, object] | pd.Series) -> bool:
    return not missing_profile_fields(row)


def _athlete_count(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "Athlete" not in df.columns:
        return 0
    names = df["Athlete"].astype(str).str.strip().replace("", pd.NA).dropna()
    return int(names.nunique())


def get_comparison_cohort(
    athlete: str,
    jump_df: pd.DataFrame | None,
    profile_df: pd.DataFrame | None,
    min_cohort_size: int = 3,
) -> dict[str, object]:
    """Resolve which peer group to compare `athlete` against for internal z-scores.

    Tries Deporte+Nivel first, falls back to Nivel only, then to the full
    dataset if neither reaches `min_cohort_size` athletes with evaluations.
    Never raises: missing/empty inputs resolve to a "general" fallback.
    """
    athlete_name = str(athlete).strip() if athlete is not None else ""
    safe_jump_df = jump_df if jump_df is not None else pd.DataFrame()

    if (
        safe_jump_df.empty
        or profile_df is None
        or profile_df.empty
        or "Athlete" not in profile_df.columns
        or "Athlete" not in safe_jump_df.columns
    ):
        return {
            "cohort_df": safe_jump_df,
            "cohort_level": "general",
            "cohort_label": "Comparación general — perfil incompleto",
            "cohort_size": _athlete_count(safe_jump_df),
            "is_fallback": True,
        }

    profile_rows = profile_df[profile_df["Athlete"].astype(str).str.strip() == athlete_name]
    if profile_rows.empty:
        return {
            "cohort_df": safe_jump_df,
            "cohort_level": "general",
            "cohort_label": "Comparación general — perfil incompleto",
            "cohort_size": _athlete_count(safe_jump_df),
            "is_fallback": True,
        }

    profile_row = profile_rows.iloc[-1]
    deporte = str(profile_row.get("Deporte") or "").strip()
    nivel = str(profile_row.get("Nivel") or "").strip()

    if not deporte or not nivel:
        return {
            "cohort_df": safe_jump_df,
            "cohort_level": "general",
            "cohort_label": "Comparación general — perfil incompleto",
            "cohort_size": _athlete_count(safe_jump_df),
            "is_fallback": True,
        }

    def _cohort_from_profile_athletes(candidate_athletes: Iterable[object]) -> tuple[pd.DataFrame, int]:
        candidate_set = {str(name).strip() for name in candidate_athletes if str(name).strip()}
        if not candidate_set:
            return safe_jump_df.iloc[0:0], 0
        jump_athletes = safe_jump_df["Athlete"].astype(str).str.strip()
        mask = jump_athletes.isin(candidate_set)
        matched_df = safe_jump_df.loc[mask]
        matched_size = _athlete_count(matched_df)
        return matched_df, matched_size

    deporte_nivel_athletes = profile_df.loc[
        (profile_df["Deporte"].astype(str).str.strip() == deporte)
        & (profile_df["Nivel"].astype(str).str.strip() == nivel),
        "Athlete",
    ]
    deporte_nivel_df, deporte_nivel_size = _cohort_from_profile_athletes(deporte_nivel_athletes)
    if deporte_nivel_size >= min_cohort_size:
        return {
            "cohort_df": deporte_nivel_df,
            "cohort_level": "deporte_nivel",
            "cohort_label": f"{deporte} · {nivel} ({deporte_nivel_size} atletas)",
            "cohort_size": deporte_nivel_size,
            "is_fallback": False,
        }

    nivel_athletes = profile_df.loc[profile_df["Nivel"].astype(str).str.strip() == nivel, "Athlete"]
    nivel_df, nivel_size = _cohort_from_profile_athletes(nivel_athletes)
    if nivel_size >= min_cohort_size:
        return {
            "cohort_df": nivel_df,
            "cohort_level": "nivel",
            "cohort_label": (
                f"Nivel {nivel} — muestra insuficiente para filtrar por deporte ({nivel_size} atletas)"
            ),
            "cohort_size": nivel_size,
            "is_fallback": True,
        }

    return {
        "cohort_df": safe_jump_df,
        "cohort_level": "general",
        "cohort_label": f"Muestra insuficiente ({nivel_size} atletas) — comparación general",
        "cohort_size": nivel_size,
        "is_fallback": True,
    }


def validate_profile_fields(profile: Mapping[str, object]) -> list[str]:
    """Minimal validation before saving a profile. Returns a list of error messages."""
    errors: list[str] = []
    if _is_blank(profile.get("Athlete")):
        errors.append("El nombre del atleta es obligatorio.")
    if _is_blank(profile.get("Contexto")):
        errors.append("Contexto es obligatorio.")
    if _is_blank(profile.get("Nivel")):
        errors.append("Nivel es obligatorio.")
    if _is_blank(profile.get("Objetivo_primario")):
        errors.append("Objetivo primario es obligatorio.")
    return errors
