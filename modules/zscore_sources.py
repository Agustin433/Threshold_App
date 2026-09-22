"""Procedencia del z-score: de donde sale el desvio con el que se compara.

Un z-score solo significa algo si el desvio contra el que se calcula
corresponde a la poblacion del atleta y al instrumento con el que se midio.
La app derivaba el desvio como `excellent - mean`, que no es un desvio sino
aproximadamente dos o tres, y lo aplicaba a cualquiera sin mirar sexo,
deporte, nivel ni dispositivo. Medido contra la muestra real, ese desvio
sintetico quedaba inflado entre 1.9x y 2.3x, con el efecto de que ningun
atleta podia alcanzar z >= 1 en las metricas que lo usaban.

Este modulo concentra la decision en un unico punto. `resolve_z_source`
devuelve que clase de lectura corresponde y por que:

- `LITERATURE_Z`      hay tabla publicada para deporte x nivel x sexo y el
                      instrumento coincide con el de la literatura;
- `COHORT_Z`          la cohorte de pares llega al minimo operativo;
- `INTRA_INDIVIDUAL`  no hay poblacion, pero el atleta tiene serie propia;
- `REFERENCE_BAND`    no hay nada de lo anterior: se muestra el valor contra
                      una banda de criterio, sin z.

Reglas duras, en este orden:

1. Ningun z se calcula con un desvio prestado de otra poblacion.
2. El gate de cohorte no es un interruptor separado: una cohorte por debajo
   del minimo resuelve a otro miembro del enum, nunca a un z de cohorte.
3. Un sexo no especificado bloquea el camino de literatura, porque sin sexo
   no hay tabla que elegir.
4. Solo `LITERATURE_Z` expone un desvio: si el z sale de cohorte o de la
   serie propia, el desvio se calcula sobre los datos y no debe presentarse
   como si viniera de la literatura.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from modules.athlete_profile import Sexo, normalize_sexo
from modules.evaluation_sources import (
    MIN_COHORT_RANK_SIZE,
    MIN_COHORT_SIZE,
    SOURCE_PLATFORM,
    normalize_source,
)


class ZSource(StrEnum):
    LITERATURE_Z = "literature_z"
    COHORT_Z = "cohort_z"
    COHORT_RANK = "cohort_rank"
    INTRA_INDIVIDUAL = "intra_individual"
    REFERENCE_BAND = "reference_band"


Z_SOURCE_LABELS: dict[str, str] = {
    ZSource.LITERATURE_Z: "z vs referencia publicada",
    ZSource.COHORT_Z: "z vs cohorte propia",
    ZSource.COHORT_RANK: "posicion dentro de la cohorte",
    ZSource.INTRA_INDIVIDUAL: "cambio vs serie propia",
    ZSource.REFERENCE_BAND: "banda de criterio (sin z)",
}

# Miembros del enum que producen un z numerico comparable en un eje.
# `COHORT_RANK` queda afuera a proposito: una posicion no es una distancia y
# mapearla a un eje de z seria disfrazarla.
Z_SOURCES_WITH_NUMERIC_Z: frozenset[ZSource] = frozenset(
    {ZSource.LITERATURE_Z, ZSource.COHORT_Z, ZSource.INTRA_INDIVIDUAL}
)

# Con una sola toma no hay serie contra la cual comparar.
MIN_INTRA_MEASUREMENTS = 2

# Clase de instrumento de cada referencia. Las normas de altura de salto
# publicadas se obtienen en plataforma (altura por impulso-momento); un dato
# derivado de tiempo de vuelo no es comparable contra ellas.
INSTRUMENT_PLATFORM = SOURCE_PLATFORM


@dataclass(frozen=True)
class ZDecision:
    """Que clase de lectura corresponde a una metrica para un atleta."""

    z_source: ZSource
    label: str
    reason: str
    sd: float | None = None
    mean: float | None = None
    reference: dict[str, object] | None = None
    cohort_size: int = 0

    @property
    def produces_numeric_z(self) -> bool:
        """True si esta decision produce un z que se pueda graficar en un eje."""
        return self.z_source in Z_SOURCES_WITH_NUMERIC_Z


# ── Tabla de referencia ────────────────────────────────────────────────────
#
# Cada entrada declara su procedencia. Se agregan SOLO valores que se puedan
# atribuir a una fuente concreta: una poblacion sin tabla propia no hereda el
# desvio de otra, resuelve a banda de criterio.
#
# Para sumar una entrada hacen falta las cinco claves de identidad (metric,
# deporte, nivel, sexo, instrument_class) mas mean, sd, n y source.
REFERENCE_TABLES: tuple[dict[str, object], ...] = (
    {
        "metric": "CMJ_cm",
        "deporte": "Rugby League",
        "nivel": "Alto rendimiento",
        "sexo": Sexo.MASCULINO,
        "instrument_class": INSTRUMENT_PLATFORM,
        "subgroup": "forwards",
        "mean": 34.1,
        "sd": 4.2,
        "n": 66,
        "source": "McMahon et al. 2022, Sensors 22(22):8669 - rugby league profesional, Kistler 1000 Hz",
    },
    {
        "metric": "CMJ_cm",
        "deporte": "Rugby League",
        "nivel": "Alto rendimiento",
        "sexo": Sexo.MASCULINO,
        "instrument_class": INSTRUMENT_PLATFORM,
        "subgroup": "backs",
        "mean": 36.4,
        "sd": 4.5,
        "n": 55,
        "source": "McMahon et al. 2022, Sensors 22(22):8669 - rugby league profesional, Kistler 1000 Hz",
    },
    {
        "metric": "Jump_Momentum",
        "deporte": "Rugby League",
        "nivel": "Alto rendimiento",
        "sexo": Sexo.MASCULINO,
        "instrument_class": INSTRUMENT_PLATFORM,
        "subgroup": "forwards",
        "mean": 262.6,
        "sd": 25.5,
        "n": 66,
        "source": "McMahon et al. 2022, Sensors 22(22):8669 - rugby league profesional, Kistler 1000 Hz",
    },
    {
        "metric": "Jump_Momentum",
        "deporte": "Rugby League",
        "nivel": "Alto rendimiento",
        "sexo": Sexo.MASCULINO,
        "instrument_class": INSTRUMENT_PLATFORM,
        "subgroup": "backs",
        "mean": 240.3,
        "sd": 27.8,
        "n": 55,
        "source": "McMahon et al. 2022, Sensors 22(22):8669 - rugby league profesional, Kistler 1000 Hz",
    },
)


def _clean(value: object) -> str:
    # `value or ""` no alcanza para NaN: es truthy en Python, asi que un campo
    # de perfil genuinamente vacio (float NaN tras `Series.to_dict()`)
    # terminaria como el string "nan", que los checks `if not deporte:`
    # aguas abajo no detectan como faltante.
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def lookup_reference(
    metric: str,
    *,
    deporte: object,
    nivel: object,
    sexo: object,
    instrument_class: object | None = None,
) -> dict[str, object] | None:
    """Devuelve la referencia publicada para esa poblacion, o None.

    La coincidencia es exacta en las cinco claves de identidad. No hay
    aproximacion ni herencia entre poblaciones: si no hay tabla para ese
    deporte, nivel y sexo, no hay referencia.

    Cuando una poblacion tiene varios subgrupos (por ejemplo forwards y backs)
    se toma el de mayor `n`, porque sin dato posicional del atleta no se puede
    elegir mejor y el subgrupo mas numeroso es el mas representativo.
    """
    sexo_key = normalize_sexo(sexo)
    if sexo_key is Sexo.NO_ESPECIFICADO:
        return None

    deporte_key = _clean(deporte).lower()
    nivel_key = _clean(nivel).lower()
    if not deporte_key or not nivel_key:
        return None

    instrument_key = normalize_source(instrument_class) if instrument_class is not None else None

    matches = [
        entry
        for entry in REFERENCE_TABLES
        if entry["metric"] == metric
        and _clean(entry["deporte"]).lower() == deporte_key
        and _clean(entry["nivel"]).lower() == nivel_key
        and normalize_sexo(entry["sexo"]) is sexo_key
        and (instrument_key is None or normalize_source(entry["instrument_class"]) == instrument_key)
    ]
    if not matches:
        return None
    return dict(max(matches, key=lambda entry: int(entry.get("n") or 0)))


def resolve_z_source(
    metric: str,
    *,
    profile: dict[str, object] | None,
    source: object,
    cohort_size: int = 0,
    measurement_count: int = 0,
) -> ZDecision:
    """Decide con que se compara una metrica, y lo justifica.

    El orden de preferencia es literatura, z de cohorte, posicion en la
    cohorte, serie propia y banda. La literatura va primero porque descansa
    sobre muestras publicadas mucho mas grandes que cualquier cohorte que este
    plantel pueda reunir. La cohorte va antes que la serie propia porque
    responde "como esta respecto a sus pares", que es la pregunta que el
    cuadrante hace. Y el rango va entre las dos: con 5 a 7 pares no hay desvio
    estable para un z, pero el orden si es informativo.
    """
    profile = profile or {}
    sexo = normalize_sexo(profile.get("Sexo"))
    deporte = _clean(profile.get("Deporte"))
    nivel = _clean(profile.get("Nivel"))
    resolved_source = normalize_source(source)

    reference = lookup_reference(metric, deporte=deporte, nivel=nivel, sexo=sexo)

    if reference is not None:
        if normalize_source(reference["instrument_class"]) == resolved_source:
            return ZDecision(
                z_source=ZSource.LITERATURE_Z,
                label=Z_SOURCE_LABELS[ZSource.LITERATURE_Z],
                reason=(
                    f"Referencia publicada para {deporte} · {nivel} · "
                    f"{'varones' if sexo is Sexo.MASCULINO else 'mujeres'}."
                ),
                sd=float(reference["sd"]),
                mean=float(reference["mean"]),
                reference=reference,
            )
        # Hay tabla, pero se midio con otra clase de instrumento.
        if cohort_size < MIN_COHORT_SIZE and measurement_count < MIN_INTRA_MEASUREMENTS:
            return ZDecision(
                z_source=ZSource.REFERENCE_BAND,
                label=Z_SOURCE_LABELS[ZSource.REFERENCE_BAND],
                reason=(
                    "La referencia publicada corresponde a otra clase de instrumento "
                    "que la medicion cargada."
                ),
            )

    if cohort_size >= MIN_COHORT_SIZE:
        return ZDecision(
            z_source=ZSource.COHORT_Z,
            label=Z_SOURCE_LABELS[ZSource.COHORT_Z],
            reason=f"Cohorte de {cohort_size} atletas comparables.",
            cohort_size=cohort_size,
        )

    if cohort_size >= MIN_COHORT_RANK_SIZE:
        return ZDecision(
            z_source=ZSource.COHORT_RANK,
            label=Z_SOURCE_LABELS[ZSource.COHORT_RANK],
            reason=(
                f"Cohorte de {cohort_size} atletas: alcanza para informar posicion, "
                f"no para un desvio estable (minimo {MIN_COHORT_SIZE} para z)."
            ),
            cohort_size=cohort_size,
        )

    if measurement_count >= MIN_INTRA_MEASUREMENTS:
        return ZDecision(
            z_source=ZSource.INTRA_INDIVIDUAL,
            label=Z_SOURCE_LABELS[ZSource.INTRA_INDIVIDUAL],
            reason=(
                f"Sin poblacion de referencia aplicable; se lee contra las "
                f"{measurement_count} tomas propias del atleta."
            ),
        )

    missing: list[str] = []
    if sexo is Sexo.NO_ESPECIFICADO:
        missing.append("sexo sin especificar")
    if not deporte:
        missing.append("deporte sin cargar")
    if not nivel:
        missing.append("nivel sin cargar")
    if reference is None and not missing:
        missing.append(f"sin tabla publicada para {deporte} · {nivel}")
    if cohort_size:
        missing.append(f"cohorte de {cohort_size} (minimo {MIN_COHORT_SIZE})")
    else:
        missing.append("muestra insuficiente para comparacion entre pares")

    return ZDecision(
        z_source=ZSource.REFERENCE_BAND,
        label=Z_SOURCE_LABELS[ZSource.REFERENCE_BAND],
        reason="No hay z aplicable: " + ", ".join(missing) + ".",
    )
