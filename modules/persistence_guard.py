"""Avisos de persistencia que no se pueden ignorar.

Hasta octubre 2026 los fallos de guardado se mostraban como avisos amarillos
que se borraban en el siguiente rerun, y la app siguio "funcionando" meses sin
guardar evaluaciones. Este modulo junta todo lo que significa "lo que cargas
no esta en Supabase" y lo muestra como st.error en cada corrida hasta que se
resuelva:

- Sin secrets de Supabase: modo sin persistencia.
- Key anon/publishable configurada: no tiene permisos, nada se guarda.
- Esquema real desfasado: columnas que la app guarda y la base no tiene.
- Guardados remotos que fallaron en esta sesion (por dataset).
- Evaluaciones en la cola que todavia no se guardaron.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import streamlit as st

from modules.remote_store import (
    RemoteSaveError,
    check_remote_schema,
    supabase_dataset_store_enabled,
    supabase_evaluations_enabled,
)

SCHEMA_CHECK_STATE_KEY = "remote_schema_check"
SAVE_FAILURES_STATE_KEY = "remote_save_failures"
PENDING_EVALUATIONS_STATE_KEY = "eval_records"

NO_PERSISTENCE_MESSAGE = (
    "Modo sin persistencia: nada se guarda. No hay secrets de Supabase configurados "
    "(SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY). Lo que cargues vive solo en esta "
    "instancia y se pierde cuando la app se reinicia."
)


def get_remote_schema_check(
    state: Mapping | None = None,
    checker: Callable[[], dict] = check_remote_schema,
    *,
    force: bool = False,
) -> dict:
    """Corre check_remote_schema una vez por sesion y lo guarda en session_state."""
    session = st.session_state if state is None else state
    cached = session.get(SCHEMA_CHECK_STATE_KEY)
    if cached is not None and not force:
        return cached
    try:
        result = checker()
    except Exception as exc:  # el chequeo nunca debe tumbar la app
        result = {
            "enabled": True,
            "ok": False,
            "key_role": None,
            "tables": [{"table": "?", "ok": False, "missing": [], "detail": str(exc)}],
        }
    session[SCHEMA_CHECK_STATE_KEY] = result
    return result


def describe_remote_save_failure(label: str, exc: Exception, total_hint: int | None = None) -> str:
    if isinstance(exc, RemoteSaveError):
        counts = f"Supabase NO guardo {exc.failed} de {exc.total} fila(s)"
        detail = exc.detail
    else:
        counts = (
            f"Supabase NO guardo {total_hint} fila(s)"
            if total_hint is not None
            else "Supabase NO confirmo el guardado"
        )
        detail = str(exc)
    return (
        f"{label}: {counts}. Quedaron solo en local y se pierden cuando la app se "
        f"reinicia. Detalle: {detail}"
    )


def record_remote_save_failure(
    key: str, label: str, exc: Exception, total_hint: int | None = None, state: Mapping | None = None
) -> str:
    session = st.session_state if state is None else state
    message = describe_remote_save_failure(label, exc, total_hint)
    failures = dict(session.get(SAVE_FAILURES_STATE_KEY) or {})
    failures[key] = message
    session[SAVE_FAILURES_STATE_KEY] = failures
    return message


def clear_remote_save_failure(key: str, state: Mapping | None = None) -> None:
    session = st.session_state if state is None else state
    failures = dict(session.get(SAVE_FAILURES_STATE_KEY) or {})
    if failures.pop(key, None) is not None:
        session[SAVE_FAILURES_STATE_KEY] = failures


def _schema_messages(schema: Mapping | None) -> list[str]:
    if not schema or not schema.get("enabled"):
        return []
    messages: list[str] = []
    if schema.get("key_role") == "anon":
        messages.append(
            "La key de Supabase configurada es anon/publishable: no tiene permisos sobre "
            "evaluations ni dataset_rows y nada se guarda. Configura SUPABASE_SERVICE_ROLE_KEY."
        )
    for table in schema.get("tables") or []:
        if table.get("ok"):
            continue
        missing = table.get("missing") or []
        if missing:
            messages.append(
                f"Esquema de Supabase desfasado: la tabla {table.get('table')} no tiene "
                f"{len(missing)} columna(s) que la app guarda: {', '.join(missing)}. "
                "Los guardados van a fallar hasta aplicar la migracion que las crea."
            )
        else:
            messages.append(
                f"No se pudo verificar la tabla {table.get('table')} en Supabase: "
                f"{table.get('detail') or 'error desconocido'}."
            )
    return messages


def persistence_banner_messages(
    *,
    persistence_enabled: bool,
    schema: Mapping | None,
    save_failures: Mapping[str, str] | None,
    pending_evaluations: int,
) -> list[str]:
    """Mensajes de error a mostrar, en orden de gravedad. Funcion pura (testeable)."""
    messages: list[str] = []
    if not persistence_enabled:
        messages.append(NO_PERSISTENCE_MESSAGE)
    else:
        messages.extend(_schema_messages(schema))
    messages.extend((save_failures or {}).values())
    if pending_evaluations > 0:
        messages.append(
            f"Tenés {pending_evaluations} evaluación(es) SIN GUARDAR en la cola. "
            "Presioná ▶ PROCESAR TODO antes de cerrar la pestaña: la cola vive solo "
            "en memoria y se pierde."
        )
    return messages


def render_persistence_banners(container=None) -> list[str]:
    """Pinta los st.error en `container` (o arriba de la pagina). Llamar en cada corrida."""
    enabled = supabase_evaluations_enabled() or supabase_dataset_store_enabled()
    schema = get_remote_schema_check() if enabled else None
    pending = st.session_state.get(PENDING_EVALUATIONS_STATE_KEY) or []
    messages = persistence_banner_messages(
        persistence_enabled=enabled,
        schema=schema,
        save_failures=st.session_state.get(SAVE_FAILURES_STATE_KEY),
        pending_evaluations=len(pending),
    )
    target = container if container is not None else st
    for message in messages:
        target.error(message, icon="🛑")
    return messages
