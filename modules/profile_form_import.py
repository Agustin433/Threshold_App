"""Importador de perfiles desde el Google Form "THRESHOLD S&C — Perfil de Cliente".

Privacidad: la planilla de respuestas tiene telefonos, contactos de
emergencia y datos de salud de terceros. Este modulo lee SOLO las columnas de
`FORM_COLUMNS`: en Google Sheets pide unicamente esos rangos de columna (el
resto nunca se descarga) y en el CSV de respaldo usa `usecols`, asi que las
otras columnas no llegan a ningun DataFrame ni a Supabase.

Validacion: falla fuerte, nunca adivina. Cada respuesta termina en uno de tres
grupos (`ImportPlan`): lista para importar, requiere confirmacion (con el
motivo) o rechazada (con el motivo). Nada se guarda sin pasar por la UI.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import pandas as pd

from modules.athlete_names import normalize_athlete_name
from modules.athlete_profile import (
    ATHLETE_PROFILE_COLUMNS,
    NIVEL_OPTIONS,
    OBJETIVO_OPTIONS,
    normalize_deporte,
    normalize_sexo,
)

# ── Columnas permitidas ─────────────────────────────────────────────────────
# clave interna -> encabezado de la planilla (texto exacto del formulario).
FORM_COLUMNS: dict[str, str] = {
    "timestamp": "Marca temporal",
    "nombre": "Nombre y apellido",
    "nacimiento": "Fecha de nacimiento",
    "altura": "Altura (cm) - Coloca el numero sin comas o puntos. Ejm: 170",
    "peso": "Peso (kg) - Coloca la cantidad redondeada",
    "sexo": "Sexo biológico",
    "email": "Email",
    "objetivo": "¿Cuál es tu objetivo principal hoy?",
    "objetivo_texto": "Contanos tu objetivo en tus palabras (opcional)",
    "deporte": "¿Practicás algún deporte? ¿Cuál?",
    "anios_fuerza": "Años de entrenamiento de fuerza estructurado",
    "nivel": "¿Cómo describirías tu nivel actual?",
    "rtp": "¿Estás en tratamiento o rehabilitación actualmente?",
    "modalidad": "¿Qué modalidad buscás?",
    "autorizacion": "Autorizo a usar estos datos para diseñar mi entrenamiento y darme de alta en sus plataformas.",
}
REQUIRED_FORM_KEYS = ("timestamp", "nombre", "nacimiento", "altura", "peso", "sexo", "objetivo",
                      "nivel", "rtp", "modalidad", "autorizacion")
# Email y años de entrenamiento se pueden leer, pero no existen en el esquema
# de athlete_profile_df: no se guardan.

AUTHORIZED_ANSWER = "Sí, autorizo"

MIN_AGE, MAX_AGE = 10, 90
MIN_HEIGHT_CM, MAX_HEIGHT_CM = 120.0, 220.0
MIN_WEIGHT_KG, MAX_WEIGHT_KG = 30.0, 200.0

RTP_OPTION = "Rehabilitación y retorno deportivo (RTP)"
OTRO_OBJETIVO = "Otro"
CONTEXTO_GIMNASIO = "Gimnasio"
CONTEXTO_ONLINE = "Online"


def _key(text: object) -> str:
    """Comparacion de textos de opciones: sin tildes, minusculas, espacios simples."""
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())


def _header_key(text: object) -> str:
    return _key(text).rstrip(" .:")


# Opciones exactas conocidas -> vocabulario de la app. Se comparan con _key.
# Incluye el vocabulario propio y las grafias del formulario anterior. Si el
# formulario nuevo usa otro texto, agregarlo aca (no se adivina: cae en
# "requiere confirmacion" por palabra clave, o en Otro / rechazo).
_OBJETIVO_EXACT: dict[str, str] = {
    **{_key(option): option for option in OBJETIVO_OPTIONS if option != OTRO_OBJETIVO},
    _key("Rehabilitación y retorno deportivo"): RTP_OPTION,
    _key("Mejorar rendimiento deportivo específico"): "Rendimiento deportivo específico",
    _key("Aumentar fuerza máxima"): "Fuerza máxima",
    _key("Mejorar composición corporal (hipertrofia)"): "Hipertrofia",
    _key("Perder grasa corporal"): "Recomposición corporal",
    _key("Mejorar resistencia física"): "Resistencia física",
    _key("Mejorar salud general y calidad de vida"): "Salud general y calidad de vida",
}
_OBJETIVO_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("rehabilit", RTP_OPTION),
    ("retorno", RTP_OPTION),
    ("lesion", "Prevención de lesiones"),
    ("hipertrof", "Hipertrofia"),
    ("masa muscular", "Hipertrofia"),
    ("grasa", "Recomposición corporal"),
    ("composicion", "Recomposición corporal"),
    ("bajar de peso", "Recomposición corporal"),
    ("fuerza", "Fuerza máxima"),
    ("resistencia", "Resistencia física"),
    ("salud", "Salud general y calidad de vida"),
    ("calidad de vida", "Salud general y calidad de vida"),
    ("rendimiento", "Rendimiento deportivo específico"),
)

_NIVEL_EXACT: dict[str, str] = {
    **{_key(option): option for option in NIVEL_OPTIONS},
    _key("Recreativo / amateur"): "Recreativo",
    _key("Competitivo local / provincial"): "Competitivo",
    _key("Nacional"): "Alto rendimiento",
}
_NIVEL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("alto rendimiento", "Alto rendimiento"),
    ("profesional", "Alto rendimiento"),
    ("internacional", "Alto rendimiento"),
    ("nacional", "Alto rendimiento"),
    ("competitiv", "Competitivo"),
    ("federad", "Competitivo"),
    ("recreativ", "Recreativo"),
    ("amateur", "Recreativo"),
    ("principiante", "Población general"),
    ("poblacion general", "Población general"),
    ("no entreno", "Población general"),
)

_MODALIDAD_EXACT: dict[str, str] = {
    _key("Presencial"): CONTEXTO_GIMNASIO,
    _key("Online"): CONTEXTO_ONLINE,
}
_MODALIDAD_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("presencial", CONTEXTO_GIMNASIO),
    ("online", CONTEXTO_ONLINE),
    ("virtual", CONTEXTO_ONLINE),
    ("a distancia", CONTEXTO_ONLINE),
)


@dataclass
class FieldMapping:
    value: object
    certain: bool  # False = se mapeo por palabra clave: requiere confirmacion
    note: str = ""


def _map_option(raw: object, exact: Mapping[str, str], keywords: Iterable[tuple[str, str]]) -> FieldMapping | None:
    key = _key(raw)
    if not key:
        return None
    if key in exact:
        return FieldMapping(exact[key], True)
    hits = {target for word, target in keywords if word in key}
    if len(hits) == 1:
        target = hits.pop()
        return FieldMapping(target, False, f"'{raw}' → {target} (por palabra clave)")
    return None


# ── Lectura ────────────────────────────────────────────────────────────────


class FormColumnsError(ValueError):
    """La planilla no tiene alguna columna obligatoria del formulario."""


def match_form_headers(headers: Iterable[object]) -> dict[str, int]:
    """Posicion de cada columna permitida dentro de `headers` (por clave interna).

    Compara sin tildes ni mayusculas y tolera espacios/puntos finales. Falla si
    falta una columna obligatoria.
    """
    wanted = {_header_key(text): key for key, text in FORM_COLUMNS.items()}
    positions: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = wanted.get(_header_key(header))
        if key and key not in positions:
            positions[key] = index
    missing = [FORM_COLUMNS[key] for key in REQUIRED_FORM_KEYS if key not in positions]
    if missing:
        raise FormColumnsError(
            "La planilla no tiene estas columnas del formulario: " + "; ".join(f"'{text}'" for text in missing)
        )
    return positions


def read_form_csv(file) -> pd.DataFrame:
    """CSV exportado a mano desde la planilla. Solo se parsean las columnas permitidas."""
    raw = file.getvalue() if hasattr(file, "getvalue") else file.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            header = pd.read_csv(io.BytesIO(raw), nrows=0, encoding=encoding, dtype=str)
            positions = match_form_headers(header.columns)
            frame = pd.read_csv(
                io.BytesIO(raw),
                usecols=sorted(positions.values()),
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
            )
            by_position = {position: key for key, position in positions.items()}
            ordered = sorted(positions.values())
            frame.columns = [by_position[position] for position in ordered]
            return frame
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError("No se pudo leer el CSV de respuestas (probe UTF-8 y Windows-1252).") from last_error


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _sheets_get_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def service_account_token(credentials_info: Mapping[str, object]) -> str:
    """Token OAuth de solo lectura para la service account (google-auth)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(
        dict(credentials_info), scopes=[SHEETS_SCOPE]
    )
    credentials.refresh(Request())
    return credentials.token


def read_form_sheet(
    spreadsheet_id: str,
    worksheet: str,
    token: str,
    *,
    get_json: Callable[[str, str], dict] = _sheets_get_json,
) -> pd.DataFrame:
    """Lee la planilla con la API de Sheets pidiendo SOLO las columnas permitidas.

    1. Pide la fila 1 (encabezados).
    2. Pide con batchGet unicamente los rangos de columna permitidos. Las
       columnas de telefono, contacto de emergencia y salud nunca se
       descargan.
    """
    sheet = _quote_sheet(worksheet)
    base = f"{SHEETS_API}/{urllib.parse.quote(spreadsheet_id, safe='')}"
    header_url = f"{base}/values/{urllib.parse.quote(f'{sheet}!1:1', safe='')}"
    header_values = get_json(header_url, token).get("values") or [[]]
    positions = match_form_headers(header_values[0])

    ordered = sorted(positions.items(), key=lambda item: item[1])
    ranges = [f"{sheet}!{_column_letter(pos)}2:{_column_letter(pos)}" for _, pos in ordered]
    query = urllib.parse.urlencode(
        [("ranges", item) for item in ranges] + [("majorDimension", "COLUMNS")]
    )
    payload = get_json(f"{base}/values:batchGet?{query}", token)
    columns: dict[str, list[str]] = {}
    for (key, _), value_range in zip(ordered, payload.get("valueRanges") or []):
        values = value_range.get("values") or [[]]
        columns[key] = [str(item) for item in values[0]]
    length = max((len(values) for values in columns.values()), default=0)
    return pd.DataFrame(
        {key: values + [""] * (length - len(values)) for key, values in columns.items()}
    )


# ── Validacion y mapeo ──────────────────────────────────────────────────────


def _parse_form_date(value: object) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt))
        except (ValueError, TypeError):
            continue
    return None


def _parse_form_timestamp(value: object) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt))
        except (ValueError, TypeError):
            continue
    return None


def _parse_number(value: object) -> float | None:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d+,\d+", text):
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_height(value: object) -> tuple[float | None, str | None, str | None]:
    """(altura_cm, aviso, error)."""
    number = _parse_number(value)
    if number is None:
        return None, None, f"altura ilegible: '{value}'"
    warning = None
    if 1.0 <= number < 3.0:
        converted = round(number * 100, 1)
        warning = f"altura '{value}' parece en metros: se guarda {converted:g} cm"
        number = converted
    if not MIN_HEIGHT_CM <= number <= MAX_HEIGHT_CM:
        return None, None, f"altura fuera de rango ({MIN_HEIGHT_CM:g}-{MAX_HEIGHT_CM:g} cm): '{value}'"
    return number, warning, None


def _parse_weight(value: object) -> tuple[float | None, str | None]:
    number = _parse_number(value)
    if number is None:
        return None, f"peso ilegible: '{value}'"
    if not MIN_WEIGHT_KG <= number <= MAX_WEIGHT_KG:
        return None, f"peso fuera de rango ({MIN_WEIGHT_KG:g}-{MAX_WEIGHT_KG:g} kg): '{value}'"
    return number, None


def _age_on(birth: pd.Timestamp, today: pd.Timestamp) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _parse_deporte(value: object) -> str | None:
    text = str(value or "").strip()
    key = _key(text)
    if not key or key in {"no", "ninguno", "ninguna", "nada", "-"}:
        return None
    text = re.sub(r"^(s[ií])\s*[,.:;-]?\s*", "", text, flags=re.IGNORECASE).strip()
    return normalize_deporte(text) if text else None


# ── Resolucion de nombre ────────────────────────────────────────────────────


def _name_tokens(name: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", _key(name)).split()


def name_candidates(form_name: str, teambuildr_names: Iterable[str]) -> list[tuple[str, str]]:
    """Candidatos de TeamBuildr para un nombre sin match exacto: (nombre, motivo).

    Reglas (todas requieren confirmacion): mismo nombre sin tildes/mayusculas,
    mismas palabras en otro orden, y nombre completo vs corto (todas las
    palabras de uno estan en el otro, con al menos dos en comun).
    """
    form_tokens = _name_tokens(form_name)
    if not form_tokens:
        return []
    results: list[tuple[str, str]] = []
    for candidate in sorted(set(teambuildr_names)):
        tokens = _name_tokens(candidate)
        if not tokens:
            continue
        if tokens == form_tokens:
            results.append((candidate, "mismo nombre sin tildes/mayúsculas"))
        elif sorted(tokens) == sorted(form_tokens):
            results.append((candidate, "mismas palabras en otro orden"))
        else:
            shared = set(tokens) & set(form_tokens)
            if len(shared) >= 2 and (set(tokens) <= set(form_tokens) or set(form_tokens) <= set(tokens)):
                results.append((candidate, "nombre completo vs. nombre corto"))
    return results


# ── Plan de importacion ─────────────────────────────────────────────────────


@dataclass
class ImportItem:
    row_number: int  # fila de la planilla (encabezado = 1)
    form_name: str
    timestamp: pd.Timestamp | None = None
    profile: dict[str, object] = field(default_factory=dict)
    athlete: str | None = None  # nombre TeamBuildr resuelto
    candidates: list[tuple[str, str]] = field(default_factory=list)
    confirmations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    diff: list[tuple[str, object, object]] = field(default_factory=list)
    unchanged: bool = False  # ya tiene un perfil identico: no se reimporta

    @property
    def status(self) -> str:
        if self.errors:
            return "rechazado"
        if self.unchanged:
            return "sin_cambios"
        if self.confirmations or self.athlete is None or self.diff:
            return "requiere_confirmacion"
        return "listo"


@dataclass
class ImportPlan:
    items: list[ImportItem]
    warnings: list[str] = field(default_factory=list)

    def by_status(self, status: str) -> list[ImportItem]:
        return [item for item in self.items if item.status == status]


_DIFF_FIELDS = [col for col in ATHLETE_PROFILE_COLUMNS if col not in {"Athlete", "Fecha_actualizacion"}]


def _comparable(value: object) -> object:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return None
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        return round(float(text), 2)
    except ValueError:
        return text


def profile_diff(existing: Mapping[str, object], new: Mapping[str, object]) -> list[tuple[str, object, object]]:
    """Campos que cambian: (campo, valor actual, valor nuevo)."""
    changes: list[tuple[str, object, object]] = []
    for column in _DIFF_FIELDS:
        old, value = _comparable(existing.get(column)), _comparable(new.get(column))
        if old != value:
            changes.append((column, existing.get(column), new.get(column)))
    return changes


def _build_profile(row: Mapping[str, object], item: ImportItem, today: pd.Timestamp) -> None:
    birth = _parse_form_date(row.get("nacimiento"))
    if birth is None:
        item.errors.append(f"fecha de nacimiento ilegible (se espera d/m/aaaa): '{row.get('nacimiento')}'")
    elif birth > today:
        item.errors.append(f"fecha de nacimiento futura: '{row.get('nacimiento')}'")
    else:
        age = _age_on(birth, today)
        if not MIN_AGE <= age <= MAX_AGE:
            item.errors.append(f"edad fuera de rango ({MIN_AGE}-{MAX_AGE}): {age} años ('{row.get('nacimiento')}')")

    height, height_warning, height_error = _parse_height(row.get("altura"))
    if height_error:
        item.errors.append(height_error)
    if height_warning:
        item.warnings.append(height_warning)
    weight, weight_error = _parse_weight(row.get("peso"))
    if weight_error:
        item.errors.append(weight_error)

    nivel = _map_option(row.get("nivel"), _NIVEL_EXACT, _NIVEL_KEYWORDS)
    if nivel is None:
        item.errors.append(f"nivel no reconocido: '{row.get('nivel')}'")
    elif not nivel.certain:
        item.confirmations.append(f"Nivel: {nivel.note}")

    contexto = _map_option(row.get("modalidad"), _MODALIDAD_EXACT, _MODALIDAD_KEYWORDS)
    if contexto is None:
        item.errors.append(f"modalidad no reconocida: '{row.get('modalidad')}'")
    elif not contexto.certain:
        item.confirmations.append(f"Contexto: {contexto.note}")

    rtp_key = _key(row.get("rtp"))
    if rtp_key in {"si", "sí"}:
        es_rtp = True
    elif rtp_key == "no":
        es_rtp = False
    else:
        es_rtp = False
        item.errors.append(f"respuesta de tratamiento/rehabilitación no reconocida: '{row.get('rtp')}'")

    objetivo_texto = str(row.get("objetivo_texto") or "").strip()
    objetivo = _map_option(row.get("objetivo"), _OBJETIVO_EXACT, _OBJETIVO_KEYWORDS)
    otro_texto_parts: list[str] = []
    if objetivo is None:
        objetivo_primario = OTRO_OBJETIVO
        if str(row.get("objetivo") or "").strip():
            otro_texto_parts.append(str(row.get("objetivo")).strip())
    else:
        objetivo_primario = str(objetivo.value)
        if not objetivo.certain:
            item.confirmations.append(f"Objetivo: {objetivo.note}")
    if objetivo_texto:
        otro_texto_parts.append(objetivo_texto)

    item.profile = {
        "Fecha_nacimiento": birth.date().isoformat() if birth is not None else None,
        "Sexo": str(normalize_sexo(row.get("sexo"))),
        "Altura_cm": height,
        "Peso_kg": weight,
        "Contexto": contexto.value if contexto else None,
        "Deporte": _parse_deporte(row.get("deporte")),
        "Nivel": nivel.value if nivel else None,
        "Objetivo_primario": objetivo_primario,
        "Objetivos_secundarios": "",
        "Objetivo_otro_texto": " | ".join(otro_texto_parts) or None,
        "Es_RTP": es_rtp,
        "Fecha_actualizacion": item.timestamp,
    }


def _is_authorized(value: object) -> bool:
    return _key(value) == _key(AUTHORIZED_ANSWER)


def build_import_plan(
    responses: pd.DataFrame,
    teambuildr_names: Iterable[str],
    existing_profiles: pd.DataFrame | None = None,
    *,
    today: pd.Timestamp | None = None,
) -> ImportPlan:
    """Arma el plan sin guardar nada. `responses` viene de read_form_csv/read_form_sheet."""
    today = (today or pd.Timestamp.today()).normalize()
    tb_names = sorted({normalize_athlete_name(name) for name in teambuildr_names if normalize_athlete_name(name)})
    tb_set = set(tb_names)
    existing_by_name: dict[str, Mapping[str, object]] = {}
    if existing_profiles is not None and not existing_profiles.empty and "Athlete" in existing_profiles.columns:
        for _, existing_row in existing_profiles.iterrows():
            name = normalize_athlete_name(existing_row.get("Athlete"))
            if name:
                existing_by_name[name] = existing_row.to_dict()

    plan = ImportPlan(items=[])
    for position, (_, row) in enumerate(responses.iterrows()):
        values = row.to_dict()
        form_name = normalize_athlete_name(values.get("nombre"))
        item = ImportItem(row_number=position + 2, form_name=form_name or str(values.get("nombre") or ""))
        item.timestamp = _parse_form_timestamp(values.get("timestamp"))
        if not form_name:
            item.errors.append("sin nombre")
        if item.timestamp is None:
            item.errors.append(f"marca temporal ilegible: '{values.get('timestamp')}'")
        if not _is_authorized(values.get("autorizacion")):
            item.errors.insert(0, f"sin autorización ('{values.get('autorizacion') or 'vacío'}')")
            plan.items.append(item)
            continue
        _build_profile(values, item, today)
        if form_name in tb_set:
            item.athlete = form_name
        elif form_name:
            item.candidates = name_candidates(form_name, tb_names)
            item.confirmations.append(
                "El nombre del formulario no coincide exacto con TeamBuildr: elegí el atleta."
                if item.candidates
                else "Sin candidatos en TeamBuildr: elegí el atleta o no lo importes."
            )
        plan.items.append(item)

    _resolve_duplicates(plan)
    for item in plan.items:
        refresh_item_diff(item, existing_by_name)
    return plan


def refresh_item_diff(item: ImportItem, existing_by_name: Mapping[str, Mapping[str, object]]) -> None:
    """Recalcula el diff contra el perfil existente del atleta resuelto."""
    item.diff = []
    item.unchanged = False
    if item.athlete and item.athlete in existing_by_name and not item.errors:
        item.diff = profile_diff(existing_by_name[item.athlete], item.profile)
        item.unchanged = not item.diff


def _resolve_duplicates(plan: ImportPlan) -> None:
    """Si alguien respondio dos veces, vale la respuesta mas reciente."""
    groups: dict[str, list[ImportItem]] = {}
    for item in plan.items:
        key = item.athlete or item.form_name
        if key and item.timestamp is not None and not any(e.startswith("sin autorización") for e in item.errors):
            groups.setdefault(_key(key), []).append(item)
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        duplicates.sort(key=lambda item: item.timestamp)
        latest = duplicates[-1]
        for older in duplicates[:-1]:
            older.errors.append(
                f"respuesta duplicada: vale la más reciente (fila {latest.row_number}, "
                f"{latest.timestamp:%d/%m/%Y %H:%M})"
            )
        latest.warnings.append(
            f"respondió {len(duplicates)} veces: se usa esta, la más reciente "
            f"(se ignoran las filas {', '.join(str(item.row_number) for item in duplicates[:-1])})"
        )
        plan.warnings.append(f"{latest.form_name}: {len(duplicates)} respuestas, se usa la más reciente.")


def final_profile(item: ImportItem) -> dict[str, object]:
    """Perfil listo para upsert: SIEMPRE con el nombre de TeamBuildr."""
    if not item.athlete:
        raise ValueError(f"{item.form_name}: falta elegir el atleta de TeamBuildr.")
    profile = {column: item.profile.get(column) for column in ATHLETE_PROFILE_COLUMNS}
    profile["Athlete"] = item.athlete
    return profile
