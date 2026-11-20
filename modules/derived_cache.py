"""Memo de calculos derivados puros, por sesion, con firma de datos.

Overview, Team y Profile recalculaban en cada rerun (cada click) resumenes,
alertas, insights y payloads que solo cambian cuando cambian los datos: ~10 s
por rerun con el volumen real (82.791 series raw). Este modulo guarda el
resultado en ``st.session_state`` y lo reutiliza mientras la firma no cambie.

La firma de cada llamada combina:

* el CONTENIDO de cada argumento (hash de pandas por fila + columnas + dtypes
  para DataFrames, recursivo en dicts/listas): cualquier dataset nuevo,
  reemplazado, filtrado o borrado cambia la firma aunque se reuse el objeto;
* la version del store en disco (mtime y tamano de cada archivo del
  directorio del store): cubre lo que las funciones leen por su cuenta
  (registro de atletas, metas del cuadrante);
* el dia de la app (``app_today``): las ventanas "semana actual" se mueven
  a medianoche.

Si algun argumento no se puede firmar (objeto opaco, celdas no hasheables)
la llamada se ejecuta sin cache: nunca se arriesga a devolver un resultado
de otros datos. El resultado se devuelve como copia profunda para que un
caller que lo modifique no contamine el cache.

Ademas cada entrada vence a los ``DERIVED_CACHE_TTL_S`` segundos como red de
seguridad para fuentes remotas (Supabase) que no dejan rastro en el store.
"""

from __future__ import annotations

import copy
import hashlib
import os
import time
from collections import OrderedDict
from typing import Any, Callable

import numpy as np
import pandas as pd

DERIVED_CACHE_KEY = "_derived_cache"
DERIVED_CACHE_STATS_KEY = "_derived_cache_stats"
DERIVED_CACHE_MAX_ENTRIES = 256
DERIVED_CACHE_TTL_S = 1800.0


class _Unsignable(Exception):
    """El argumento no admite una firma de contenido segura."""


def _session_state():
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:  # pragma: no cover - streamlit siempre esta en la app
        return None
    if get_script_run_ctx(suppress_warning=True) is None:
        return None
    return st.session_state


def _frame_content_hash(frame: pd.DataFrame | pd.Series) -> str:
    """Hash del contenido: bytes crudos para columnas numpy, hash de pandas para el resto.

    ``hash_pandas_object`` cuesta ~70 us por columna; el frame de evaluaciones
    tiene 115 columnas casi todas numericas. Los bloques numpy (float, int,
    bool, datetime) se hashean por sus bytes, agrupados por dtype: bytes
    iguales con el mismo dtype implican valores iguales, asi que nunca hay un
    falso acierto (a lo sumo un falso fallo, p. ej. -0.0 vs 0.0).
    """
    hasher = hashlib.blake2b(digest_size=16)
    try:
        hasher.update(np.ascontiguousarray(pd.util.hash_pandas_object(frame.index).to_numpy()).tobytes())
        if isinstance(frame, pd.Series):
            frame = frame.to_frame()
        numpy_groups: dict[str, list[int]] = {}
        masked_groups: dict[str, list[int]] = {}
        other_positions: list[int] = []
        for position, dtype in enumerate(frame.dtypes):
            if isinstance(dtype, np.dtype) and dtype.kind in "biufcmM":
                numpy_groups.setdefault(dtype.str, []).append(position)
            elif isinstance(getattr(dtype, "numpy_dtype", None), np.dtype) and dtype.numpy_dtype.kind in "biuf":
                # Int64 / Float64 / boolean de pandas: valores + mascara de nulos.
                masked_groups.setdefault(dtype.numpy_dtype.str, []).append(position)
            else:
                other_positions.append(position)
        for tag, groups in (("np", numpy_groups), ("masked", masked_groups)):
            for dtype_str, positions in sorted(groups.items()):
                hasher.update(f"{tag}{dtype_str}{positions}".encode("ascii"))
                block = frame.iloc[:, positions]
                if tag == "np":
                    values = block.to_numpy(dtype=np.dtype(dtype_str))
                else:
                    values = block.to_numpy(dtype=np.dtype(dtype_str), na_value=0)
                    hasher.update(np.ascontiguousarray(block.isna().to_numpy()).tobytes())
                hasher.update(np.ascontiguousarray(values).tobytes())
        if other_positions:
            hasher.update(f"obj{other_positions}".encode("ascii"))
            block = frame.iloc[:, other_positions]
            if len(block) <= 2000:
                # Pocas filas y muchas columnas: una sola pasada evita el costo fijo por columna.
                hashed = pd.util.hash_array(block.to_numpy(dtype=object).ravel())
            else:
                hashed = pd.util.hash_pandas_object(block, index=False).to_numpy()
            hasher.update(np.ascontiguousarray(hashed).tobytes())
    except Exception as exc:  # celdas con listas/dicts, etc.
        raise _Unsignable(str(exc)) from exc
    return hasher.hexdigest()


def _frame_digest(frame: pd.DataFrame | pd.Series) -> tuple[object, ...]:
    if isinstance(frame, pd.DataFrame):
        columns = tuple(str(col) for col in frame.columns)
        dtypes = tuple(str(dtype) for dtype in frame.dtypes)
    else:
        columns = (str(frame.name),)
        dtypes = (str(frame.dtype),)
    digest = _frame_content_hash(frame)
    attrs = _fingerprint(dict(frame.attrs)) if frame.attrs else None
    return (type(frame).__name__, frame.shape, columns, dtypes, digest, attrs)


def _fingerprint(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return (type(value).__name__, value)
    if isinstance(value, (np.generic,)):
        return (type(value).__name__, value.item())
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return (type(value).__name__, str(value))
    if value is pd.NaT:
        return ("NaT",)
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return _frame_digest(value)
    if isinstance(value, pd.Index):
        return ("Index", tuple(_fingerprint(item) for item in value.tolist()))
    if isinstance(value, dict):
        return ("dict", tuple((_fingerprint(key), _fingerprint(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_fingerprint(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted(repr(_fingerprint(item)) for item in value)))
    raise _Unsignable(type(value).__name__)


def _store_version() -> tuple[tuple[str, int, int], ...]:
    """mtime y tamano de cada archivo del store (datasets, registro, metas)."""
    try:
        import local_store

        store_dir = local_store.STORE_DIR
    except Exception:
        return ()
    parts: list[tuple[str, int, int]] = []
    try:
        with os.scandir(store_dir) as entries:
            for entry in entries:
                if entry.is_file():
                    stat = entry.stat()
                    parts.append((entry.name, int(stat.st_mtime_ns), int(stat.st_size)))
    except OSError:
        return (("<sin store>", 0, 0),)
    return (str(store_dir), *sorted(parts))  # type: ignore[return-value]


def _app_day() -> str:
    try:
        from modules.app_clock import app_today

        return str(app_today())
    except Exception:
        return ""


def build_signature(name: str, args: tuple, kwargs: dict) -> str:
    """Firma estable de una llamada. Lanza _Unsignable si no se puede firmar."""
    payload = (
        name,
        _fingerprint(list(args)),
        _fingerprint(dict(sorted(kwargs.items()))),
        _store_version(),
        _app_day(),
    )
    return hashlib.blake2b(repr(payload).encode("utf-8"), digest_size=20).hexdigest()


def _bump_stat(state, key: str) -> None:
    stats = dict(state.get(DERIVED_CACHE_STATS_KEY) or {})
    stats[key] = int(stats.get(key, 0)) + 1
    state[DERIVED_CACHE_STATS_KEY] = stats


def cached_call(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Ejecuta ``fn(*args, **kwargs)`` reutilizando el resultado si la firma coincide."""
    state = _session_state()
    if state is None:
        return fn(*args, **kwargs)
    try:
        signature = build_signature(name, args, kwargs)
    except _Unsignable:
        _bump_stat(state, "bypass")
        return fn(*args, **kwargs)

    cache = state.get(DERIVED_CACHE_KEY)
    if not isinstance(cache, OrderedDict):
        cache = OrderedDict()
    now = time.monotonic()
    entry = cache.get(signature)
    if entry is not None and now - entry[0] <= DERIVED_CACHE_TTL_S:
        cache.move_to_end(signature)
        state[DERIVED_CACHE_KEY] = cache
        _bump_stat(state, "hit")
        return copy.deepcopy(entry[1])

    result = fn(*args, **kwargs)
    cache[signature] = (now, copy.deepcopy(result))
    cache.move_to_end(signature)
    while len(cache) > DERIVED_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
    state[DERIVED_CACHE_KEY] = cache
    _bump_stat(state, "miss")
    return result


def prime(name: str, value: Any, *args: Any, **kwargs: Any) -> None:
    """Guarda `value` como resultado de `name(*args, **kwargs)` sin calcularlo.

    Solo para resultados que se probaron identicos por otro camino (ver
    tests/test_shared_profile.py): evita recalcular algo que ya esta.
    """
    state = _session_state()
    if state is None:
        return
    try:
        signature = build_signature(name, args, kwargs)
    except _Unsignable:
        return
    cache = state.get(DERIVED_CACHE_KEY)
    if not isinstance(cache, OrderedDict):
        cache = OrderedDict()
    if signature in cache:
        return
    cache[signature] = (time.monotonic(), copy.deepcopy(value))
    while len(cache) > DERIVED_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
    state[DERIVED_CACHE_KEY] = cache


def cached(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Version cacheada de ``fn`` con la misma firma de llamada."""

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        return cached_call(name, fn, *args, **kwargs)

    _wrapped.__name__ = getattr(fn, "__name__", name)
    _wrapped.__doc__ = getattr(fn, "__doc__", None)
    _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
    return _wrapped


def invalidate_derived_cache() -> None:
    """Descarta todo lo memoizado (carga, reemplazo o borrado de datos)."""
    state = _session_state()
    if state is None:
        return
    state[DERIVED_CACHE_KEY] = OrderedDict()
