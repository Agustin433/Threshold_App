"""Fuente de medicion de una evaluacion: plataforma vs no-plataforma.

Una plataforma de fuerza estima la altura de salto por impulso-momento
(integra la curva de fuerza hasta la velocidad de despegue). MyJump2 y las
alfombras de contacto la derivan del tiempo de vuelo (`h = g*t^2/8`), que se
contamina con la postura de despegue y aterrizaje. El sesgo entre ambos
metodos no es constante: varia por atleta y por sesion.

Por eso `Source` no es metadato decorativo. Es una clave de particion:
- entra en `dedupe_cols` de `jump_df`, para que dos mediciones del mismo dia
  con distinto dispositivo no se fusionen pisandose entre si;
- separa los z-scores intra-atleta, las cohortes y los baselines;
- habilita o bloquea los benchmarks externos, que estan derivados de
  plataforma y no aplican a datos de tiempo de vuelo.

`Device` es metadato libre para trazabilidad. No participa de la particion:
MyJump2 y alfombra comparten el mismo metodo de estimacion, asi que el
usuario los trata como equivalentes.
"""

from __future__ import annotations

import math


SOURCE_PLATFORM = "platform"
SOURCE_NONPLATFORM = "nonplatform"

DEFAULT_SOURCE = SOURCE_PLATFORM

SOURCE_ORDER: tuple[str, ...] = (SOURCE_PLATFORM, SOURCE_NONPLATFORM)

SOURCE_LABELS: dict[str, str] = {
    SOURCE_PLATFORM: "Plataforma",
    SOURCE_NONPLATFORM: "No-Plataforma",
}

SOURCE_VIEW_LABELS: dict[str, str] = {
    SOURCE_PLATFORM: "Análisis Plataforma",
    SOURCE_NONPLATFORM: "Análisis No-Plataforma",
}

SOURCE_DESCRIPTIONS: dict[str, str] = {
    SOURCE_PLATFORM: "Plataforma de fuerza (altura por impulso-momento).",
    SOURCE_NONPLATFORM: "MyJump2 / alfombra de contacto (altura por tiempo de vuelo).",
}

# Dispositivos conocidos por fuente. Solo trazabilidad: no particiona.
SOURCE_DEVICES: dict[str, tuple[str, ...]] = {
    SOURCE_PLATFORM: ("Involution", "Otra plataforma"),
    SOURCE_NONPLATFORM: ("MyJump2", "Alfombra de contacto", "Otro"),
}

# Aliases tolerados al leer historial viejo o entradas escritas a mano.
_SOURCE_ALIASES: dict[str, str] = {
    "": DEFAULT_SOURCE,
    "platform": SOURCE_PLATFORM,
    "plataforma": SOURCE_PLATFORM,
    "forceplate": SOURCE_PLATFORM,
    "force_plate": SOURCE_PLATFORM,
    "forcedecks": SOURCE_PLATFORM,
    "involution": SOURCE_PLATFORM,
    "nonplatform": SOURCE_NONPLATFORM,
    "non_platform": SOURCE_NONPLATFORM,
    "no-plataforma": SOURCE_NONPLATFORM,
    "no_plataforma": SOURCE_NONPLATFORM,
    "noplataforma": SOURCE_NONPLATFORM,
    "myjump": SOURCE_NONPLATFORM,
    "myjump2": SOURCE_NONPLATFORM,
    "alfombra": SOURCE_NONPLATFORM,
    "contact_mat": SOURCE_NONPLATFORM,
    "mat": SOURCE_NONPLATFORM,
}

EARTH_GRAVITY = 9.81


def normalize_source(value: object) -> str:
    """Resolve any stored/typed source value to a canonical partition key.

    Unknown values fall back to `DEFAULT_SOURCE` on purpose: historical rows
    predate this column and all of them came from the force platform.
    """
    text = str(value or "").strip().lower()
    if not text or text in {"nan", "none", "<na>"}:
        return DEFAULT_SOURCE
    return _SOURCE_ALIASES.get(text, DEFAULT_SOURCE)


def source_label(value: object) -> str:
    return SOURCE_LABELS.get(normalize_source(value), SOURCE_LABELS[DEFAULT_SOURCE])


def is_platform(value: object) -> bool:
    return normalize_source(value) == SOURCE_PLATFORM


def flight_time_to_height_cm(flight_ms: object) -> float | None:
    """Altura de salto (cm) desde tiempo de vuelo (ms), `h = g*t^2/8`.

    Es la formula que ya usan internamente MyJump2 y las alfombras de
    contacto. Se expone para poder cargar a mano lo que esos dispositivos
    entregan de forma nativa, sin obligar al usuario a convertir.
    """
    try:
        flight_s = float(flight_ms) / 1000.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(flight_s) or flight_s <= 0:
        return None
    return round((EARTH_GRAVITY * flight_s * flight_s / 8.0) * 100.0, 2)
