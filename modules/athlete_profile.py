"""Domain helpers for athlete profiles: options, keyword suggestions and validation."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from enum import StrEnum

import pandas as pd

from modules.evaluation_sources import MIN_COHORT_SIZE, normalize_source


class Sexo(StrEnum):
    """Sexo del atleta como enum cerrado.

    Se modela como enum y no como booleano ni string libre a proposito: el
    valor selecciona la tabla de referencia contra la que se calcula un
    z-score, asi que un valor inesperado no puede degradar en algo "verdadero"
    (el clasico `bool("False") is True`) ni inventar una poblacion. Lo que no
    se reconoce se declara desconocido y bloquea el camino de literatura.
    """

    MASCULINO = "M"
    FEMENINO = "F"
    NO_ESPECIFICADO = "no_especificado"


SEXO_LABELS: dict[str, str] = {
    Sexo.MASCULINO: "Masculino",
    Sexo.FEMENINO: "Femenino",
    Sexo.NO_ESPECIFICADO: "No especificado",
}

# Solo grafias inequivocas. Cualquier otra cosa cae en NO_ESPECIFICADO.
_SEXO_ALIASES: dict[str, Sexo] = {
    "m": Sexo.MASCULINO,
    "masculino": Sexo.MASCULINO,
    "hombre": Sexo.MASCULINO,
    "varon": Sexo.MASCULINO,
    "f": Sexo.FEMENINO,
    "femenino": Sexo.FEMENINO,
    "mujer": Sexo.FEMENINO,
    "no_especificado": Sexo.NO_ESPECIFICADO,
    "no especificado": Sexo.NO_ESPECIFICADO,
}


def normalize_sexo(value: object) -> Sexo:
    """Resuelve cualquier valor almacenado o tipeado al enum canonico.

    Los booleanos se rechazan explicitamente: si el campo llegara como `True`
    o `False` (por una migracion mal hecha o un CSV con la columna corrida),
    convertirlo a texto produciria "True"/"False", que no son sexos. Antes de
    inventar una poblacion se prefiere declarar desconocido.
    """
    if isinstance(value, bool):
        return Sexo.NO_ESPECIFICADO
    if isinstance(value, Sexo):
        return value
    text = str(value or "").strip().lower()
    if not text or text in {"nan", "none", "<na>", "true", "false"}:
        return Sexo.NO_ESPECIFICADO
    return _SEXO_ALIASES.get(text, Sexo.NO_ESPECIFICADO)


def sexo_label(value: object) -> str:
    return SEXO_LABELS[normalize_sexo(value)]


class ClaseAtleta(StrEnum):
    """Clase poblacional del atleta, derivada del nivel.

    Es la particion mas gruesa y la mas defendible con planteles chicos: la
    diferencia entre poblacion general y alguien que entrena para competir es
    mayor que la que hay entre dos deportes distintos al mismo nivel. Se usa
    como identidad de cohorte junto al sexo.
    """

    DEPORTISTA = "deportista"
    POBLACION_GENERAL = "poblacion_general"


CLASE_ATLETA_LABELS: dict[str, str] = {
    ClaseAtleta.DEPORTISTA: "Deportistas",
    ClaseAtleta.POBLACION_GENERAL: "Población general",
}


def clase_atleta_from_nivel(nivel: object) -> ClaseAtleta | None:
    """Deriva la clase del nivel cargado. `None` si el nivel falta.

    No se infiere nada: sin nivel no hay clase, y sin clase el atleta no puede
    recibir un z de cohorte.
    """
    text = _strip_accents(str(nivel or "").strip()).lower()
    if not text or text in {"nan", "none", "<na>"}:
        return None
    if text.startswith("poblacion"):
        return ClaseAtleta.POBLACION_GENERAL
    return ClaseAtleta.DEPORTISTA


CONTEXTO_OPTIONS: tuple[str, ...] = ("Club", "Gimnasio")

NIVEL_OPTIONS: tuple[str, ...] = (
    "Población general",
    "Recreativo",
    "Competitivo",
    "Alto rendimiento",
)

# Deportes mas practicados en Tucuman, para cargar desde lista y no a mano.
# El campo libre producia grafias divergentes del mismo deporte ("Futbol",
# "Futboll", "Futbo"), que fragmentaban cualquier agrupacion por deporte.
# `OTRO_DEPORTE_OPTION` habilita un campo de texto para lo que no este listado.
DEPORTE_OPTIONS: tuple[str, ...] = (
    "Fútbol",
    "Rugby",
    "Hockey sobre césped",
    "Básquet",
    "Vóley",
    "Handball",
    "Tenis",
    "Natación",
    "Atletismo",
    "Ciclismo",
)

OTRO_DEPORTE_OPTION = "Otro"

DEPORTE_SELECT_OPTIONS: tuple[str, ...] = (*DEPORTE_OPTIONS, OTRO_DEPORTE_OPTION)

# Grafias observadas en el historial que corresponden al mismo deporte. La
# clave se compara sin acentos ni mayusculas, asi que basta con listar las
# variantes de escritura reales.
_DEPORTE_ALIASES: dict[str, str] = {
    "futbol": "Fútbol",
    "futboll": "Fútbol",
    "futbo": "Fútbol",
    "fulbo": "Fútbol",
    "football": "Fútbol",
    "soccer": "Fútbol",
    "handbal": "Handball",
    "handboll": "Handball",
    "balonmano": "Handball",
    "basquet": "Básquet",
    "basket": "Básquet",
    "basquetbol": "Básquet",
    "voley": "Vóley",
    "volley": "Vóley",
    "voleibol": "Vóley",
    "hockey": "Hockey sobre césped",
    "natacion": "Natación",
    "ciclismo": "Ciclismo",
    "atletismo": "Atletismo",
    "tenis": "Tenis",
    "rugby": "Rugby",
}


def _strip_accents(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def normalize_deporte(value: object) -> str | None:
    """Unifica grafias de un mismo deporte a su forma canonica.

    Devuelve `None` cuando no hay dato. Lo que no se reconoce se conserva tal
    cual y solo se le limpia el espaciado: un deporte cargado por el campo
    "Otro" es informacion valida, no un error de tipeo que haya que descartar.
    """
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    key = _strip_accents(text).lower()
    if key in _DEPORTE_ALIASES:
        return _DEPORTE_ALIASES[key]
    for option in DEPORTE_OPTIONS:
        if _strip_accents(option).lower() == key:
            return option
    return text

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
    "Sexo",
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

REQUIRED_PROFILE_FIELDS: tuple[str, ...] = ("Contexto", "Nivel", "Sexo", "Objetivo_primario")

FIELD_LABELS: dict[str, str] = {
    "Athlete": "Nombre del atleta",
    "Contexto": "Contexto",
    "Nivel": "Nivel",
    "Sexo": "Sexo",
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
        value = _field_value(row, field)
        # "no_especificado" es un valor valido del enum Sexo, no un string
        # vacio, asi que `_is_blank` no lo detecta. Para completitud de perfil
        # cuenta como faltante igual: sin sexo no hay z de literatura ni de
        # cohorte posible.
        if field == "Sexo":
            if normalize_sexo(value) is Sexo.NO_ESPECIFICADO:
                missing.append(FIELD_LABELS.get(field, field))
            continue
        if _is_blank(value):
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
    min_cohort_size: int = MIN_COHORT_SIZE,
    source: str | None = None,
) -> dict[str, object]:
    """Resolve which peer group to compare `athlete` against for internal z-scores.

    Tries Deporte+Nivel first, falls back to Nivel only, then to the full
    dataset if neither reaches `min_cohort_size` athletes with evaluations.
    Never raises: missing/empty inputs resolve to a "general" fallback.

    `source` restringe la cohorte a un unico metodo de medicion. El tamano de
    cohorte se cuenta despues de ese filtro, asi que una muestra que solo
    alcanza el minimo mezclando dispositivos cae al fallback en vez de
    producir una comparacion invalida.
    """
    athlete_name = str(athlete).strip() if athlete is not None else ""
    safe_jump_df = jump_df if jump_df is not None else pd.DataFrame()
    if (
        source is not None
        and not safe_jump_df.empty
        and "Source" in safe_jump_df.columns
    ):
        safe_jump_df = safe_jump_df[
            safe_jump_df["Source"].map(normalize_source) == normalize_source(source)
        ]

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
    clase = clase_atleta_from_nivel(profile_row.get("Nivel"))
    sexo = normalize_sexo(profile_row.get("Sexo"))

    # Sin clase no hay poblacion, y sin sexo la comparacion mezclaria varones
    # con mujeres, que es la menos defendible de todas. Cualquiera de las dos
    # ausencias deja al atleta sin cohorte en vez de darle una aproximada.
    if clase is None or sexo is Sexo.NO_ESPECIFICADO:
        faltante = "nivel" if clase is None else "sexo"
        return {
            "cohort_df": safe_jump_df.iloc[0:0],
            "cohort_level": "sin_cohorte",
            "cohort_label": f"Sin cohorte — falta {faltante} en el perfil",
            "cohort_size": 0,
            "is_fallback": True,
        }

    def _cohort_from_profile_athletes(candidate_athletes: Iterable[object]) -> tuple[pd.DataFrame, int]:
        """Recorta el frame de evaluaciones a los atletas candidatos."""
        candidate_set = {str(name).strip() for name in candidate_athletes if str(name).strip()}
        if not candidate_set:
            return safe_jump_df.iloc[0:0], 0
        jump_athletes = safe_jump_df["Athlete"].astype(str).str.strip()
        matched_df = safe_jump_df.loc[jump_athletes.isin(candidate_set)]
        return matched_df, _athlete_count(matched_df)

    # `Deporte` quedo fuera de la identidad de cohorte a proposito. Con match
    # exacto por deporte el mejor grupo del plantel llegaba a 4 atletas y
    # ninguno alcanzaba el minimo, asi que nadie recibia z. Agrupar por clase y
    # sexo pierde especificidad de deporte pero produce una muestra que existe.
    # El deporte se conserva en el perfil y en los reportes, y puede volver a
    # la clave cuando un deporte reuna el minimo por su cuenta.
    peers = profile_df.copy()
    peers_clase = peers["Nivel"].map(clase_atleta_from_nivel) if "Nivel" in peers.columns else None
    peers_sexo = peers["Sexo"].map(normalize_sexo) if "Sexo" in peers.columns else None
    if peers_clase is None or peers_sexo is None:
        return {
            "cohort_df": safe_jump_df.iloc[0:0],
            "cohort_level": "sin_cohorte",
            "cohort_label": "Sin cohorte — el perfil no tiene nivel ni sexo",
            "cohort_size": 0,
            "is_fallback": True,
        }

    cohort_athletes = peers.loc[(peers_clase == clase) & (peers_sexo == sexo), "Athlete"]
    cohort_df, cohort_size = _cohort_from_profile_athletes(cohort_athletes)
    clase_label = CLASE_ATLETA_LABELS[clase]
    sexo_text = "masculino" if sexo is Sexo.MASCULINO else "femenino"

    if cohort_size >= min_cohort_size:
        return {
            "cohort_df": cohort_df,
            "cohort_level": "clase_sexo",
            "cohort_label": f"{clase_label} · {sexo_text} ({cohort_size} atletas)",
            "cohort_size": cohort_size,
            "is_fallback": False,
        }

    # Muestra insuficiente. Se devuelve el tamano real para que el resolutor
    # decida entre rango y banda, pero nunca un cohort_df que habilite un z.
    return {
        "cohort_df": cohort_df,
        "cohort_level": "muestra_insuficiente",
        "cohort_label": (
            f"{clase_label} · {sexo_text} — muestra insuficiente "
            f"({cohort_size} de {min_cohort_size} atletas)"
        ),
        "cohort_size": cohort_size,
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
