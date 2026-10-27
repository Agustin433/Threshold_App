"""Shared Supabase config and request helpers for persistence flows."""

from __future__ import annotations

import json
from collections import Counter
import os
import hashlib
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import streamlit as st

from local_store import DATASET_SPECS, normalize_athlete_name
from modules.data_loader import EVALUATION_DB_COLUMN_MAP, EVALUATION_PERSIST_COLUMNS, SUPABASE_EVALUATIONS_TABLE
from modules.evaluation_sources import normalize_source
from modules.jump_analysis import (
    _prepare_jump_df,
    build_dj_drop_height_backfill_candidates,
    dj_drop_height_backfill_mask,
    resolve_dj_drop_height_series,
)

SUPABASE_DATASETS_TABLE = "dataset_rows"
REMOTE_DATASET_KEYS = [
    "rpe_df",
    "wellness_df",
    "completion_df",
    "rep_load_df",
    "raw_df",
    "maxes_df",
    "session_notes_df",
    "athlete_profile_df",
]
_JUMP_DJ_CONTEXT_FIELDS = ("DJ_cm", "DJ_tc_ms", "DJ_RSI", "DJ_drop_height_cm")
_JUMP_DJ_CLEAR_FIELDS = ("DJ_drop_height_cm",)


def _get_secret_or_env(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


# Sin fallback a SUPABASE_ANON_KEY a proposito: anon no tiene grants ni
# policies sobre evaluations/dataset_rows, asi que con esa key la app leeria
# tablas vacias sin error y los guardados fallarian. Mejor "sin persistencia"
# explicito que una persistencia que no persiste.
def _supabase_dataset_store_config() -> tuple[str | None, str | None, str]:
    url = _get_secret_or_env("SUPABASE_URL") or _get_secret_or_env("THRESHOLD_SUPABASE_URL")
    key = (
        _get_secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
        or _get_secret_or_env("SUPABASE_KEY")
        or _get_secret_or_env("THRESHOLD_SUPABASE_KEY")
    )
    table = _get_secret_or_env("SUPABASE_DATASETS_TABLE") or SUPABASE_DATASETS_TABLE
    return url, key, table


def _supabase_evaluations_config() -> tuple[str | None, str | None, str]:
    url = _get_secret_or_env("SUPABASE_URL") or _get_secret_or_env("THRESHOLD_SUPABASE_URL")
    key = (
        _get_secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
        or _get_secret_or_env("SUPABASE_KEY")
        or _get_secret_or_env("THRESHOLD_SUPABASE_KEY")
    )
    table = _get_secret_or_env("SUPABASE_EVALUATIONS_TABLE") or SUPABASE_EVALUATIONS_TABLE
    return url, key, table


def supabase_dataset_store_enabled() -> bool:
    url, key, table = _supabase_dataset_store_config()
    return bool(url and key and table)


def supabase_evaluations_enabled() -> bool:
    url, key, table = _supabase_evaluations_config()
    return bool(url and key and table)


class SupabaseHTTPError(RuntimeError):
    """Respuesta HTTP de error de PostgREST. Conserva status y cuerpo."""

    def __init__(self, status: int, reason: str, body: str):
        self.status = int(status)
        self.reason = reason
        self.body = body
        super().__init__(f"{status} {reason}: {body}")


class RemoteSaveError(RuntimeError):
    """Un guardado en Supabase no se completo. Dice cuantas filas quedaron afuera."""

    def __init__(self, *, saved: int, total: int, detail: str):
        self.saved = int(saved)
        self.total = int(total)
        self.failed = max(self.total - self.saved, 0)
        self.detail = detail
        super().__init__(
            f"Supabase NO guardo {self.failed} de {self.total} fila(s) "
            f"({self.saved} confirmadas). Detalle: {detail}"
        )


def _supabase_request(
    method: str,
    table: str,
    query: dict | None = None,
    payload: list[dict] | dict | None = None,
    prefer: str | None = None,
    *,
    evaluations: bool = False,
):
    url, key, _ = _supabase_evaluations_config() if evaluations else _supabase_dataset_store_config()
    if not url or not key:
        raise RuntimeError("Supabase no configurado")

    endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
    if query:
        qs = urllib.parse.urlencode(query, doseq=True, safe="*,():")
        endpoint = f"{endpoint}?{qs}"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise SupabaseHTTPError(exc.code, exc.reason, detail) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar a Supabase: {exc.reason}") from exc


def _json_safe_value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).date().isoformat()
    # bool va antes que int: en Python `bool` es subclase de `int`
    # (isinstance(True, int) es True), asi que si el chequeo de int fuera
    # primero, todo booleano se serializaria como 0/1 en vez de true/false.
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    return value


def _row_has_jump_dj_context(row: pd.Series | dict[str, object]) -> bool:
    row_series = row if isinstance(row, pd.Series) else pd.Series(row)
    for field in _JUMP_DJ_CONTEXT_FIELDS:
        if field not in row_series.index:
            continue
        numeric = pd.to_numeric(pd.Series([row_series.get(field)]), errors="coerce").iloc[0]
        if pd.notna(numeric):
            return True
    return False


def _dataset_event_date(value) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _canonical_key_value(value):
    # 1 y 1.0 son la misma serie/ID: sin esto el row_key dependia de si la
    # columna llego como int o como float (basta un NaN en el export).
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _dataset_row_signature(state_key: str, payload: dict[str, object]) -> str:
    spec = DATASET_SPECS.get(state_key, {})
    dedupe_cols = spec.get("dedupe_cols") or sorted(payload.keys())
    key_payload = {col: _canonical_key_value(payload.get(col)) for col in dedupe_cols if col in payload}
    if not key_payload:
        key_payload = payload
    serialized = json.dumps(key_payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def dataset_df_to_remote_records(state_key: str, df: pd.DataFrame) -> list[dict]:
    if state_key not in REMOTE_DATASET_KEYS or df is None or df.empty:
        return []

    spec = DATASET_SPECS.get(state_key, {})
    # event_date = fecha de analisis (Raw Workouts: Fecha_sesion, el dia en
    # que se hizo la serie). La identidad (row_key) sigue en dedupe_cols.
    date_col = spec.get("analysis_date_col") or spec.get("date_col")
    key_date_col = spec.get("date_col")
    athlete_col = spec.get("athlete_col")
    records: list[dict] = []

    for _, row in df.iterrows():
        payload: dict[str, object] = {}
        for col in df.columns:
            safe_value = _json_safe_value(row.get(col))
            if safe_value is not None:
                payload[col] = safe_value
        if not payload:
            continue

        if athlete_col and athlete_col in payload:
            payload[athlete_col] = normalize_athlete_name(payload[athlete_col])

        record = {
            "dataset_key": state_key,
            "row_key": _dataset_row_signature(state_key, payload),
            "payload": payload,
        }
        if athlete_col and payload.get(athlete_col):
            record["athlete"] = normalize_athlete_name(payload[athlete_col])
        if date_col:
            event_date = _dataset_event_date(payload.get(date_col))
            if not event_date and key_date_col:
                event_date = _dataset_event_date(payload.get(key_date_col))
            if event_date:
                record["event_date"] = event_date
        records.append(record)
    return records


class EvaluationColumnMappingError(ValueError):
    """Una columna de evaluacion a persistir no tiene columna destino en Supabase."""


def unmapped_evaluation_persist_columns(columns=None) -> list[str]:
    """Columnas de EVALUATION_PERSIST_COLUMNS sin mapeo a la base.

    Con `columns` se limita a las que estan presentes en ese conjunto (las que
    efectivamente se intentarian guardar).
    """
    present = None if columns is None else set(columns)
    return [
        col
        for col in EVALUATION_PERSIST_COLUMNS
        if col not in EVALUATION_DB_COLUMN_MAP and (present is None or col in present)
    ]


def jump_df_to_db_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []

    # Se valida antes de recorrer filas: un hueco en el mapeo antes era un
    # KeyError crudo a mitad del guardado y no decia que faltaba.
    unmapped = unmapped_evaluation_persist_columns(df.columns)
    if unmapped:
        raise EvaluationColumnMappingError(
            "No se puede guardar en Supabase: estas columnas de evaluacion no tienen "
            f"columna destino en la tabla evaluations: {', '.join(unmapped)}. "
            "Agregalas a EVALUATION_DB_COLUMN_MAP (modules/data_loader.py) y crea la "
            "migracion con su add column."
        )

    records: list[dict] = []
    for _, row in df.iterrows():
        record: dict[str, object] = {}
        has_dj_context = _row_has_jump_dj_context(row)
        for app_col in EVALUATION_PERSIST_COLUMNS:
            if app_col not in row.index:
                continue
            value = row[app_col]
            db_col = EVALUATION_DB_COLUMN_MAP[app_col]
            if has_dj_context and app_col in _JUMP_DJ_CLEAR_FIELDS and pd.isna(value):
                record[db_col] = None
                continue
            if pd.isna(value):
                continue
            if app_col == "Date":
                record[db_col] = pd.Timestamp(value).date().isoformat()
            elif app_col == "Athlete":
                record[db_col] = normalize_athlete_name(value)
            elif isinstance(value, (np.integer, int)):
                record[db_col] = int(value)
            elif isinstance(value, (np.floating, float)):
                record[db_col] = float(value)
            else:
                record[db_col] = value
        if record.get("athlete") and record.get("date"):
            records.append(record)
    return records


_DATASET_UPSERT_CHUNK_SIZE = 500


def _chunked_records(records: list[dict], chunk_size: int = _DATASET_UPSERT_CHUNK_SIZE) -> list[list[dict]]:
    return [records[i : i + chunk_size] for i in range(0, len(records), chunk_size)]


_CONFLICT_EXAMPLE_LIMIT = 3
_CHUNK_ERROR_DETAIL_LIMIT = 3


def _describe_dataset_record(record: dict) -> str:
    payload = record.get("payload") or {}
    athlete = record.get("athlete") or payload.get("Athlete") or "sin atleta"
    event_date = record.get("event_date") or "sin fecha"
    exercise = payload.get("Exercise Name") or payload.get("Exercise") or "-"
    return f"{athlete} · {event_date} · {exercise}"


def _upsert_dataset_records(table: str, records: list[dict]) -> int:
    """Upsert por lotes que nunca deja pasar un 500 crudo de PostgREST.

    - Filas con row_key repetido dentro del envio no se mandan: PostgreSQL
      rechaza el lote entero con 21000 ("ON CONFLICT DO UPDATE command cannot
      affect row a second time"). Se reportan con ejemplos.
    - Si un lote falla, se sigue con los demas y al final se informa el total
      no guardado. Solo cuenta lo que Supabase devuelve confirmado.
    Lanza RemoteSaveError si algo no se guardo. Devuelve filas confirmadas.
    """
    total = len(records)
    problems: list[str] = []
    key_counts = Counter(record["row_key"] for record in records)
    duplicated_keys = {key for key, count in key_counts.items() if count > 1}
    if duplicated_keys:
        duplicated = [record for record in records if record["row_key"] in duplicated_keys]
        examples: list[str] = []
        for key in sorted(duplicated_keys)[:_CONFLICT_EXAMPLE_LIMIT]:
            first = next(record for record in duplicated if record["row_key"] == key)
            examples.append(f"{_describe_dataset_record(first)} (x{key_counts[key]})")
        problems.append(
            f"{len(duplicated)} fila(s) en {len(duplicated_keys)} grupo(s) comparten la misma clave "
            f"y no se enviaron. Ejemplos (atleta · fecha · ejercicio): {'; '.join(examples)}"
        )
        records = [record for record in records if record["row_key"] not in duplicated_keys]

    saved = 0
    chunk_errors: list[str] = []
    for chunk in _chunked_records(records):
        try:
            rows = _supabase_request(
                "POST",
                table,
                query={"on_conflict": "dataset_key,row_key"},
                payload=chunk,
                prefer="resolution=merge-duplicates,return=representation",
            ) or []
        except Exception as exc:
            chunk_errors.append(f"lote de {len(chunk)} fila(s): {exc}")
            continue
        if not rows:
            chunk_errors.append(f"lote de {len(chunk)} fila(s): Supabase respondio sin filas")
            continue
        saved += len(rows)
    if chunk_errors:
        shown = chunk_errors[:_CHUNK_ERROR_DETAIL_LIMIT]
        more = len(chunk_errors) - len(shown)
        problems.append(
            f"{len(chunk_errors)} lote(s) fallaron: " + " | ".join(shown) + (f" | y {more} mas" if more else "")
        )
    if problems:
        raise RemoteSaveError(saved=saved, total=total, detail=" || ".join(problems))
    return saved


def save_remote_dataset(state_key: str, df: pd.DataFrame) -> dict[str, int | bool]:
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return {"enabled": False, "upserted": 0}

    payload = dataset_df_to_remote_records(state_key, df)
    if not payload:
        return {"enabled": True, "upserted": 0}

    _, _, table = _supabase_dataset_store_config()
    # En lotes: un solo POST con miles de filas (Raw Workouts) puede superar el
    # limite de tamano o el timeout de Supabase.
    upserted = _upsert_dataset_records(table, payload)
    return {"enabled": True, "upserted": upserted}


def replace_remote_dataset_span(
    state_key: str,
    df: pd.DataFrame,
    span: tuple[pd.Timestamp, pd.Timestamp, set[str]] | None,
) -> dict[str, int | bool]:
    """Version remota de `local_store.replace_dataset_span`.

    Upsert primero y delete despues (mismo criterio que el reemplazo total):
    si se corta a mitad, quedan a lo sumo filas viejas de mas, nunca datos
    borrados sin reponer. Solo borra filas de esos atletas dentro del rango
    que no vienen en el archivo; nunca reemplaza el dataset completo.
    """
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return {"enabled": False, "upserted": 0, "deleted": 0}
    stats = save_remote_dataset(state_key, df)
    if span is None:
        return {**stats, "deleted": 0}

    start, end, athletes = span
    desired_keys = {record["row_key"] for record in dataset_df_to_remote_records(state_key, df)}
    _, _, table = _supabase_dataset_store_config()
    deleted = 0
    for athlete in sorted(athletes):
        existing: list[dict] = []
        offset = 0
        while True:
            batch = _supabase_request(
                "GET",
                table,
                query={
                    "select": "row_key",
                    "dataset_key": f"eq.{state_key}",
                    "athlete": f"eq.{athlete}",
                    "event_date": [f"gte.{start.date().isoformat()}", f"lte.{end.date().isoformat()}"],
                    "limit": 1000,
                    "offset": offset,
                },
            ) or []
            existing.extend(batch)
            if len(batch) < 1000:
                break
            offset += 1000
        stale = sorted({row.get("row_key") for row in existing if row.get("row_key")} - desired_keys)
        for chunk in _chunked_records([{"k": key} for key in stale], chunk_size=100):
            keys = ",".join(item["k"] for item in chunk)
            rows = _supabase_request(
                "DELETE",
                table,
                query={"dataset_key": f"eq.{state_key}", "row_key": f"in.({keys})"},
                prefer="return=representation",
            ) or []
            deleted += len(rows) if rows else len(chunk)
    return {**stats, "deleted": deleted}


def load_remote_dataset(state_key: str) -> pd.DataFrame:
    if not supabase_dataset_store_enabled() or state_key not in REMOTE_DATASET_KEYS:
        return pd.DataFrame()

    _, _, table = _supabase_dataset_store_config()
    rows = []
    offset = 0
    page_size = 1000

    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={
                "select": "payload",
                "dataset_key": f"eq.{state_key}",
                "order": "event_date.asc.nullslast,row_key.asc",
                "limit": page_size,
                "offset": offset,
            },
        ) or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    payloads = [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]
    return pd.DataFrame(payloads) if payloads else pd.DataFrame()


def save_remote_evaluations(df: pd.DataFrame) -> dict[str, int | bool]:
    if not supabase_evaluations_enabled():
        return {"enabled": False, "inserted": 0, "updated": 0, "total": 0}

    try:
        payload = jump_df_to_db_records(df)
    except EvaluationColumnMappingError as exc:
        raise RemoteSaveError(saved=0, total=len(df), detail=str(exc)) from exc
    if not payload:
        return {"enabled": True, "inserted": 0, "updated": 0, "total": 0}

    _, _, table = _supabase_evaluations_config()
    inserted = 0
    updated = 0
    try:
        for record in payload:
            inserted_now, updated_now = _save_one_remote_evaluation(table, record)
            inserted += inserted_now
            updated += updated_now
    except Exception as exc:
        raise RemoteSaveError(saved=inserted + updated, total=len(payload), detail=str(exc)) from exc

    return {
        "enabled": True,
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
    }


def _save_one_remote_evaluation(table: str, record: dict) -> tuple[int, int]:
    """PATCH si existe la fila, POST si no. Devuelve (insertadas, actualizadas)."""
    # La fuente entra en el filtro del PATCH: sin ella, una evaluacion de
    # alfombra sobrescribiria la de plataforma del mismo atleta y fecha.
    record_source = normalize_source(record.get("source"))
    record["source"] = record_source
    filters = {
        "select": "athlete,date,source",
        "athlete": f"eq.{record['athlete']}",
        "date": f"eq.{record['date']}",
        "source": f"eq.{record_source}",
    }
    updated_rows = _supabase_request(
        "PATCH",
        table,
        query=filters,
        payload=record,
        prefer="return=representation",
        evaluations=True,
    )
    if updated_rows:
        return 0, len(updated_rows)

    inserted_rows = _supabase_request(
        "POST",
        table,
        payload=record,
        prefer="return=representation",
        evaluations=True,
    )
    if not inserted_rows:
        raise RuntimeError(
            f"Supabase no confirmo el alta de {record.get('athlete')} {record.get('date')} "
            "(respuesta vacia)."
        )
    return len(inserted_rows), 0


def backfill_remote_evaluations_drop_height(default_drop_height_cm: float = 30.0) -> dict[str, int | float | bool]:
    default_value = float(default_drop_height_cm)
    if default_value <= 0:
        raise ValueError("La altura de caida por defecto debe ser mayor a 0.")
    if not supabase_evaluations_enabled():
        return {
            "enabled": False,
            "updated_rows": 0,
            "athletes": 0,
            "remote_writes": 0,
            "default_drop_height_cm": default_value,
        }

    frame = load_remote_evaluations_frame()
    candidates = build_dj_drop_height_backfill_candidates(frame)
    if candidates.empty:
        return {
            "enabled": True,
            "updated_rows": 0,
            "athletes": 0,
            "remote_writes": 0,
            "default_drop_height_cm": default_value,
        }

    updates = frame.loc[dj_drop_height_backfill_mask(frame)].copy()
    if "Athlete" in updates.columns:
        updates["DJ_drop_height_cm"] = resolve_dj_drop_height_series(updates["Athlete"], default_value)
    else:
        updates["DJ_drop_height_cm"] = default_value
    sync_stats = save_remote_evaluations(updates)
    athletes = int(candidates["Athlete"].dropna().nunique()) if "Athlete" in candidates.columns else 0
    return {
        "enabled": True,
        "updated_rows": int(len(candidates)),
        "athletes": athletes,
        "remote_writes": int(sync_stats.get("total", 0)),
        "default_drop_height_cm": default_value,
    }


def load_remote_evaluations_frame() -> pd.DataFrame:
    if not supabase_evaluations_enabled():
        return pd.DataFrame()

    _, _, table = _supabase_evaluations_config()
    rows = []
    offset = 0
    page_size = 1000

    while True:
        batch = _supabase_request(
            "GET",
            table,
            query={
                "select": "*",
                "order": "date.asc,athlete.asc",
                "limit": page_size,
                "offset": offset,
            },
            evaluations=True,
        ) or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if not rows:
        return pd.DataFrame()

    rename_map = {db_col: app_col for app_col, db_col in EVALUATION_DB_COLUMN_MAP.items()}
    return pd.DataFrame(rows).rename(columns=rename_map)


def load_remote_evaluations() -> pd.DataFrame:
    frame = load_remote_evaluations_frame()
    if frame.empty:
        return pd.DataFrame()

    keep_cols = [app_col for app_col in EVALUATION_DB_COLUMN_MAP if app_col in frame.columns]
    return _prepare_jump_df(frame[keep_cols])


# ── Chequeo de esquema contra la base real ─────────────────────────────────

DATASET_ROWS_REQUIRED_COLUMNS = (
    "dataset_key",
    "row_key",
    "event_date",
    "athlete",
    "payload",
)


def supabase_key_role(key: str | None) -> str | None:
    """Rol de la key configurada: 'anon', 'service_role', o None si no se sabe.

    Las keys legacy son JWT con el claim `role`. Las nuevas publishable
    (sb_publishable_...) equivalen a anon; las secret (sb_secret_...) a
    service_role. No valida firma: solo detecta una key equivocada.
    """
    if not key:
        return None
    key = str(key).strip()
    if key.startswith("sb_publishable_"):
        return "anon"
    if key.startswith("sb_secret_"):
        return "service_role"
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        import base64

        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    role = claims.get("role") if isinstance(claims, dict) else None
    return str(role) if role else None


def _missing_columns_from_probe(
    table: str, columns: list[str], *, evaluations: bool
) -> list[str]:
    """PostgREST solo nombra la primera columna inexistente: se prueba una por una."""
    missing: list[str] = []
    for column in columns:
        try:
            _supabase_request(
                "GET", table, query={"select": column, "limit": 0}, evaluations=evaluations
            )
        except SupabaseHTTPError as exc:
            if exc.status == 400:
                missing.append(column)
            else:
                raise
    return missing


def _check_table_columns(table: str, columns: list[str], *, evaluations: bool) -> dict:
    try:
        _supabase_request(
            "GET",
            table,
            query={"select": ",".join(columns), "limit": 0},
            evaluations=evaluations,
        )
        return {"table": table, "ok": True, "missing": [], "detail": ""}
    except SupabaseHTTPError as exc:
        if exc.status != 400:
            return {"table": table, "ok": False, "missing": [], "detail": str(exc)}
        try:
            missing = _missing_columns_from_probe(table, columns, evaluations=evaluations)
        except Exception as probe_exc:
            return {"table": table, "ok": False, "missing": [], "detail": f"{exc} | {probe_exc}"}
        return {"table": table, "ok": False, "missing": missing, "detail": str(exc)}
    except Exception as exc:
        return {"table": table, "ok": False, "missing": [], "detail": str(exc)}


def check_remote_schema() -> dict:
    """Unica verificacion contra la base real: ¿existen las columnas que la app guarda?

    GET /rest/v1/<tabla>?select=<columnas>&limit=0 no trae datos. Si PostgREST
    responde 400 es porque falta alguna columna y se identifica cual.
    Devuelve {"enabled", "ok", "key_role", "tables": [...]}.
    """
    if not (supabase_evaluations_enabled() or supabase_dataset_store_enabled()):
        return {"enabled": False, "ok": False, "key_role": None, "tables": []}

    _, key, _ = _supabase_evaluations_config()
    role = supabase_key_role(key)
    tables: list[dict] = []
    if supabase_evaluations_enabled():
        _, _, eval_table = _supabase_evaluations_config()
        eval_columns = list(dict.fromkeys(EVALUATION_DB_COLUMN_MAP.values()))
        tables.append(_check_table_columns(eval_table, eval_columns, evaluations=True))
    if supabase_dataset_store_enabled():
        _, _, dataset_table = _supabase_dataset_store_config()
        tables.append(
            _check_table_columns(
                dataset_table, list(DATASET_ROWS_REQUIRED_COLUMNS), evaluations=False
            )
        )
    ok = role != "anon" and all(item["ok"] for item in tables)
    return {"enabled": True, "ok": ok, "key_role": role, "tables": tables}
