"""Normalizacion unica del nombre de atleta.

El nombre se usa como clave en todos los datasets (dedupe, row_key en
Supabase, cruces entre cargas y perfiles), asi que tiene que normalizarse en
un solo lugar. Antes habia mas de 20 `.str.title()` sueltos, y `.title()`:

- rompe nombres con mayusculas internas: "McDonald" -> "Mcdonald";
- convierte el caracter de reemplazo U+FFFD en un separador de palabra:
  "CASTA�O" -> "Casta�O" (asi aparecio "Gaston Casta�O").

Regla de mayusculas, por cada parte del nombre (separada por espacio,
guion o apostrofo):
- toda en minuscula o toda en mayuscula -> primera letra mayuscula, resto
  minuscula ("GASTON" -> "Gaston", "d'andrea" -> "D'Andrea");
- con mayusculas mezcladas que ya empieza en mayuscula -> se respeta tal
  cual ("McDonald", "DeLuca");
- con mayusculas mezcladas que empieza en minuscula -> se corrige como el
  primer caso ("gASTON" -> "Gaston").

Para todo nombre que hoy esta guardado (salida de `.title()`, siempre
"Xxxx Yyyy"), el resultado es identico: no cambia ninguna clave existente.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

REPLACEMENT_CHAR = "�"
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "﻿​‌‍⁠"), None)
_PART_SEPARATORS = re.compile(r"([\-'’])")


class AthleteNameEncodingError(ValueError):
    """Un nombre de atleta llego con U+FFFD: el archivo se leyo con el encoding equivocado."""


def _fix_part_case(part: str) -> str:
    if not part:
        return part
    first_cased = next((char for char in part if char.isupper() or char.islower()), None)
    if first_cased is None:
        return part
    if part.islower() or part.isupper() or first_cased.islower():
        return part[:1].upper() + part[1:].lower()
    return part


def _fix_word_case(word: str) -> str:
    return "".join(
        piece if _PART_SEPARATORS.fullmatch(piece) else _fix_part_case(piece)
        for piece in _PART_SEPARATORS.split(word)
    )


def normalize_athlete_name(value: object) -> str:
    """Forma canonica de un nombre de atleta. Vacio ("") si no hay nombre."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = unicodedata.normalize("NFC", str(value)).translate(_INVISIBLE_CHARS)
    words = text.split()
    if not words:
        return ""
    return " ".join(_fix_word_case(word) for word in words)


def contains_replacement_char(value: object) -> bool:
    return isinstance(value, str) and REPLACEMENT_CHAR in value


def normalize_athlete_series(
    series: pd.Series,
    *,
    source_label: str | None = None,
    reject_replacement_char: bool = True,
) -> pd.Series:
    """Normaliza una columna de atletas. Faltantes -> pd.NA.

    Con `reject_replacement_char` (parsers de archivos), si algun nombre trae
    U+FFFD lanza AthleteNameEncodingError: guardarlo crearia un atleta
    fantasma ("Casta�O") que no cruza con nada.
    """
    normalized = series.map(normalize_athlete_name)
    if reject_replacement_char:
        broken = sorted({name for name in normalized if contains_replacement_char(name)})
        if broken:
            label = f"{source_label}: " if source_label else ""
            preview = ", ".join(broken[:5]) + (f" y {len(broken) - 5} mas" if len(broken) > 5 else "")
            raise AthleteNameEncodingError(
                f"{label}{len(broken)} nombre(s) de atleta con caracteres ilegibles "
                f"(U+FFFD): {preview}. El archivo no se guardo. Suele pasar cuando "
                "el export viene en Latin-1/Windows-1252 y se leyo como UTF-8: "
                "volve a exportarlo desde TeamBuildr o avisa para revisarlo."
            )
    return normalized.mask(normalized.eq(""), pd.NA)
