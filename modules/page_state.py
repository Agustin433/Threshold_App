"""Shared Streamlit page bootstrap helpers."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from modules.data_loader import prepare_raw_workouts_df
from local_store import (
    DATASET_SPECS,
    HISTORY_MODE_FULL,
    RECENT_WEEKS,
    build_load_models,
    build_weekly_summaries,
    get_local_store_version,
    load_full_history_state,
    load_recent_state,
)

DATASET_SESSION_KEYS = list(DATASET_SPECS.keys())
LOAD_DATASET_KEYS = ["rpe_df", "wellness_df", "raw_df"]
REPORT_DATASET_KEYS = [
    "rpe_df",
    "wellness_df",
    "completion_df",
    "rep_load_df",
    "raw_df",
    "session_notes_df",
    "maxes_df",
    "jump_df",
    "athlete_profile_df",
]
MODEL_SESSION_KEYS = ["acwr_dict", "mono_dict"]
SESSION_KEYS = [*DATASET_SESSION_KEYS, *MODEL_SESSION_KEYS]
WEEKLY_SUMMARY_KEYS = {"weekly_load", "weekly_wellness", "weekly_external", "weekly_team"}

LOCAL_STORE_HYDRATED_KEY = "local_store_hydrated"
LOCAL_STORE_VERSION_KEY = "local_store_version"
LOCAL_STORE_LAST_HYDRATION_TS_KEY = "last_hydration_ts"
PREPARED_RAW_DF_KEY = "prepared_raw_df"
PREPARED_RAW_DF_VERSION_KEY = "prepared_raw_df_version"
PREPARED_RAW_DF_LAST_BUILD_TS_KEY = "prepared_raw_df_last_build_ts"
LOAD_STATE_VERSION_KEY = "load_state_version"
LOAD_STATE_LAST_BUILD_TS_KEY = "load_state_last_build_ts"
REPORT_PREVIEW_PAYLOAD_KEY = "report_preview_payload"
REPORT_PREVIEW_SIGNATURE_KEY = "report_preview_signature"
REPORT_PREVIEW_LAST_BUILD_TS_KEY = "report_preview_last_build_ts"
PERFORMANCE_DEBUG_TIMINGS_KEY = "performance_debug_timings"
PERFORMANCE_DEBUG_ARTIFACTS_KEY = "performance_debug_artifacts"
FULL_HISTORY_LOAD_STATE_KEY = "full_history_load_state"
FULL_HISTORY_LOAD_STATE_VERSION_KEY = "full_history_load_state_version"
FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY = "full_history_load_state_last_build_ts"
FULL_HISTORY_STATE_KEY = "full_history_state"
FULL_HISTORY_STATE_VERSION_KEY = "full_history_state_version"
FULL_HISTORY_STATE_KEYS_KEY = "full_history_state_keys"


def _ensure_session_defaults() -> None:
    for key in SESSION_KEYS:
        if key not in st.session_state:
            st.session_state[key] = None
    if LOCAL_STORE_HYDRATED_KEY not in st.session_state:
        st.session_state[LOCAL_STORE_HYDRATED_KEY] = False
    if LOCAL_STORE_VERSION_KEY not in st.session_state:
        st.session_state[LOCAL_STORE_VERSION_KEY] = None
    if LOCAL_STORE_LAST_HYDRATION_TS_KEY not in st.session_state:
        st.session_state[LOCAL_STORE_LAST_HYDRATION_TS_KEY] = None
    if PREPARED_RAW_DF_KEY not in st.session_state:
        st.session_state[PREPARED_RAW_DF_KEY] = None
    if PREPARED_RAW_DF_VERSION_KEY not in st.session_state:
        st.session_state[PREPARED_RAW_DF_VERSION_KEY] = None
    if PREPARED_RAW_DF_LAST_BUILD_TS_KEY not in st.session_state:
        st.session_state[PREPARED_RAW_DF_LAST_BUILD_TS_KEY] = None
    if "weekly_summaries" not in st.session_state:
        st.session_state["weekly_summaries"] = {}
    if LOAD_STATE_VERSION_KEY not in st.session_state:
        st.session_state[LOAD_STATE_VERSION_KEY] = None
    if LOAD_STATE_LAST_BUILD_TS_KEY not in st.session_state:
        st.session_state[LOAD_STATE_LAST_BUILD_TS_KEY] = None
    if REPORT_PREVIEW_PAYLOAD_KEY not in st.session_state:
        st.session_state[REPORT_PREVIEW_PAYLOAD_KEY] = None
    if REPORT_PREVIEW_SIGNATURE_KEY not in st.session_state:
        st.session_state[REPORT_PREVIEW_SIGNATURE_KEY] = None
    if REPORT_PREVIEW_LAST_BUILD_TS_KEY not in st.session_state:
        st.session_state[REPORT_PREVIEW_LAST_BUILD_TS_KEY] = None
    if PERFORMANCE_DEBUG_TIMINGS_KEY not in st.session_state:
        st.session_state[PERFORMANCE_DEBUG_TIMINGS_KEY] = {}
    if PERFORMANCE_DEBUG_ARTIFACTS_KEY not in st.session_state:
        st.session_state[PERFORMANCE_DEBUG_ARTIFACTS_KEY] = {}
    if FULL_HISTORY_LOAD_STATE_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_KEY] = None
    if FULL_HISTORY_LOAD_STATE_VERSION_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_VERSION_KEY] = None
    if FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY] = None


def _performance_defaults() -> tuple[dict[str, float | None], dict[str, str]]:
    timings = {
        "active_view_render_s": None,
        "ensure_local_store_hydrated_s": None,
        "ensure_prepared_raw_workouts_s": None,
        "ensure_load_state_s": None,
        "report_preview_build_s": None,
        "report_exportables_build_s": None,
    }
    artifacts = {
        "local_store_hydration": "no ejecutado",
        "prepared_raw_df": "no ejecutado",
        "load_state": "no ejecutado",
        "report_preview": "no ejecutado",
        "report_exportables": "no ejecutado",
    }
    return timings, artifacts


def reset_performance_debug_cycle() -> None:
    _ensure_session_defaults()
    timings, artifacts = _performance_defaults()
    st.session_state[PERFORMANCE_DEBUG_TIMINGS_KEY] = timings
    st.session_state[PERFORMANCE_DEBUG_ARTIFACTS_KEY] = artifacts


def _merge_performance_debug_status(existing: str | None, incoming: str) -> str:
    priority = {
        "no ejecutado": 0,
        "no disponible": 1,
        "reutilizado": 2,
        "reconstruido": 3,
        "ejecutado": 4,
    }
    current = existing or "no ejecutado"
    return incoming if priority.get(incoming, 0) >= priority.get(current, 0) else current


def record_performance_debug_timing(key: str, elapsed_s: float, *, accumulate: bool = True) -> None:
    _ensure_session_defaults()
    timings = dict(st.session_state.get(PERFORMANCE_DEBUG_TIMINGS_KEY) or {})
    current = timings.get(key)
    timings[key] = float(elapsed_s) if not accumulate or current is None else float(current) + float(elapsed_s)
    st.session_state[PERFORMANCE_DEBUG_TIMINGS_KEY] = timings


def record_performance_debug_artifact(key: str, status: str) -> None:
    _ensure_session_defaults()
    artifacts = dict(st.session_state.get(PERFORMANCE_DEBUG_ARTIFACTS_KEY) or {})
    artifacts[key] = _merge_performance_debug_status(artifacts.get(key), status)
    st.session_state[PERFORMANCE_DEBUG_ARTIFACTS_KEY] = artifacts


def current_local_store_version(keys: list[str] | None = None) -> tuple[tuple[str, bool, int, int], ...]:
    return get_local_store_version(keys=keys)


def current_load_state_version(keys: list[str] | None = None) -> tuple[tuple[str, bool, int, int], ...]:
    return current_local_store_version(keys=keys or LOAD_DATASET_KEYS)


def current_raw_df_version() -> tuple[tuple[str, bool, int, int], ...]:
    return current_local_store_version(keys=["raw_df"])


def current_report_state_version(keys: list[str] | None = None) -> tuple[tuple[str, bool, int, int], ...]:
    return current_local_store_version(keys=keys or REPORT_DATASET_KEYS)


def _has_valid_weekly_summaries(value: object) -> bool:
    return isinstance(value, dict) and WEEKLY_SUMMARY_KEYS.issubset(value.keys())


def clear_report_preview_cache() -> None:
    _ensure_session_defaults()
    st.session_state[REPORT_PREVIEW_PAYLOAD_KEY] = None
    st.session_state[REPORT_PREVIEW_SIGNATURE_KEY] = None
    st.session_state[REPORT_PREVIEW_LAST_BUILD_TS_KEY] = None


def invalidate_load_state_cache(*, clear_recent: bool = True, clear_full: bool = True) -> None:
    _ensure_session_defaults()
    if clear_recent:
        st.session_state[PREPARED_RAW_DF_KEY] = None
        st.session_state[PREPARED_RAW_DF_VERSION_KEY] = None
        st.session_state[PREPARED_RAW_DF_LAST_BUILD_TS_KEY] = None
        st.session_state["acwr_dict"] = None
        st.session_state["mono_dict"] = None
        st.session_state["weekly_summaries"] = {}
        st.session_state[LOAD_STATE_VERSION_KEY] = None
        st.session_state[LOAD_STATE_LAST_BUILD_TS_KEY] = None
    if clear_full:
        st.session_state[FULL_HISTORY_LOAD_STATE_KEY] = None
        st.session_state[FULL_HISTORY_LOAD_STATE_VERSION_KEY] = None
        st.session_state[FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY] = None


def invalidate_local_store_hydration(
    *,
    clear_full_history: bool = True,
    clear_load_state: bool = True,
) -> None:
    _ensure_session_defaults()
    st.session_state[LOCAL_STORE_HYDRATED_KEY] = False
    st.session_state[LOCAL_STORE_VERSION_KEY] = None
    st.session_state[LOCAL_STORE_LAST_HYDRATION_TS_KEY] = None
    clear_report_preview_cache()
    if clear_load_state:
        invalidate_load_state_cache(clear_recent=True, clear_full=True)
    if clear_full_history:
        st.session_state.pop(FULL_HISTORY_STATE_KEY, None)
        st.session_state.pop(FULL_HISTORY_STATE_VERSION_KEY, None)
        st.session_state.pop(FULL_HISTORY_STATE_KEYS_KEY, None)


def build_report_preview_signature(
    *,
    report_audience: str,
    report_athlete: str,
    effective_report_athlete: str | None,
    report_options: dict[str, object] | None = None,
    date_window: str | None = None,
    store_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> tuple[object, ...]:
    normalized_options = tuple(sorted((report_options or {}).items()))
    effective_version = current_report_state_version() if store_version is None else store_version
    return (
        "report_preview",
        str(report_audience).strip().lower(),
        str(report_athlete).strip(),
        None if effective_report_athlete is None else str(effective_report_athlete).strip(),
        None if date_window is None else str(date_window).strip(),
        normalized_options,
        effective_version,
    )


def report_preview_needs_refresh(*, signature: tuple[object, ...]) -> bool:
    _ensure_session_defaults()
    return (
        st.session_state.get(REPORT_PREVIEW_SIGNATURE_KEY) != signature
        or not isinstance(st.session_state.get(REPORT_PREVIEW_PAYLOAD_KEY), dict)
    )


def store_report_preview(
    *,
    payload: dict[str, object],
    signature: tuple[object, ...],
) -> None:
    _ensure_session_defaults()
    st.session_state[REPORT_PREVIEW_PAYLOAD_KEY] = payload
    st.session_state[REPORT_PREVIEW_SIGNATURE_KEY] = signature
    st.session_state[REPORT_PREVIEW_LAST_BUILD_TS_KEY] = time.time()


def local_store_needs_hydration(
    *,
    force: bool = False,
    store_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> bool:
    _ensure_session_defaults()
    effective_version = current_local_store_version() if store_version is None else store_version
    return (
        force
        or not bool(st.session_state.get(LOCAL_STORE_HYDRATED_KEY))
        or st.session_state.get(LOCAL_STORE_VERSION_KEY) != effective_version
    )


def mark_local_store_hydrated(
    *,
    store_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> tuple[tuple[str, bool, int, int], ...]:
    _ensure_session_defaults()
    effective_version = current_local_store_version() if store_version is None else store_version
    st.session_state[LOCAL_STORE_HYDRATED_KEY] = True
    st.session_state[LOCAL_STORE_VERSION_KEY] = effective_version
    st.session_state[LOCAL_STORE_LAST_HYDRATION_TS_KEY] = time.time()
    return effective_version


def prepared_raw_workouts_needs_rebuild(
    *,
    force: bool = False,
    raw_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> bool:
    _ensure_session_defaults()
    effective_version = current_raw_df_version() if raw_version is None else raw_version
    return (
        force
        or st.session_state.get(PREPARED_RAW_DF_VERSION_KEY) != effective_version
        or st.session_state.get(PREPARED_RAW_DF_KEY) is None
    )


def mark_prepared_raw_workouts_built(
    *,
    raw_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> tuple[tuple[str, bool, int, int], ...]:
    _ensure_session_defaults()
    effective_version = current_raw_df_version() if raw_version is None else raw_version
    st.session_state[PREPARED_RAW_DF_VERSION_KEY] = effective_version
    st.session_state[PREPARED_RAW_DF_LAST_BUILD_TS_KEY] = time.time()
    return effective_version


def ensure_prepared_raw_workouts(
    *,
    force_reload: bool = False,
    ensure_base_state: bool = True,
    weeks: int = RECENT_WEEKS,
) -> pd.DataFrame | None:
    _ensure_session_defaults()
    started_at = time.perf_counter()

    try:
        if ensure_base_state:
            ensure_page_state(load_models=False, force_reload=force_reload, weeks=weeks)

        if force_reload:
            st.session_state[PREPARED_RAW_DF_KEY] = None
            st.session_state[PREPARED_RAW_DF_VERSION_KEY] = None
            st.session_state[PREPARED_RAW_DF_LAST_BUILD_TS_KEY] = None

        if st.session_state.get("raw_df") is None:
            record_performance_debug_artifact("prepared_raw_df", "no disponible")
            return None

        raw_version = current_raw_df_version()
        if not prepared_raw_workouts_needs_rebuild(raw_version=raw_version):
            record_performance_debug_artifact("prepared_raw_df", "reutilizado")
            return st.session_state.get(PREPARED_RAW_DF_KEY)

        prepared_raw_df = prepare_raw_workouts_df(st.session_state.get("raw_df"))
        st.session_state[PREPARED_RAW_DF_KEY] = prepared_raw_df
        mark_prepared_raw_workouts_built(raw_version=raw_version)
        record_performance_debug_artifact("prepared_raw_df", "reconstruido")
        return prepared_raw_df
    finally:
        record_performance_debug_timing("ensure_prepared_raw_workouts_s", time.perf_counter() - started_at)


def load_state_needs_rebuild(
    *,
    force: bool = False,
    store_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> bool:
    _ensure_session_defaults()
    effective_version = current_load_state_version() if store_version is None else store_version
    return (
        force
        or st.session_state.get(LOAD_STATE_VERSION_KEY) != effective_version
        or not _has_valid_weekly_summaries(st.session_state.get("weekly_summaries"))
    )


def mark_load_state_built(
    *,
    store_version: tuple[tuple[str, bool, int, int], ...] | None = None,
) -> tuple[tuple[str, bool, int, int], ...]:
    _ensure_session_defaults()
    effective_version = current_load_state_version() if store_version is None else store_version
    st.session_state[LOAD_STATE_VERSION_KEY] = effective_version
    st.session_state[LOAD_STATE_LAST_BUILD_TS_KEY] = time.time()
    return effective_version


def ensure_page_state(
    load_models: bool = True,
    *,
    force_reload: bool = False,
    weeks: int = RECENT_WEEKS,
) -> bool:
    _ensure_session_defaults()
    store_version = current_local_store_version()
    hydrated = False

    if force_reload:
        invalidate_local_store_hydration(clear_full_history=True)

    if local_store_needs_hydration(store_version=store_version):
        stored_state = load_recent_state(weeks=weeks)
        for key in DATASET_SESSION_KEYS:
            st.session_state[key] = stored_state.get(key)
        mark_local_store_hydrated(store_version=store_version)
        hydrated = True

    if load_models:
        ensure_load_state(ensure_base_state=False)

    return hydrated


def ensure_load_state(
    *,
    force_reload: bool = False,
    ensure_base_state: bool = True,
    weeks: int = RECENT_WEEKS,
) -> bool:
    _ensure_session_defaults()
    started_at = time.perf_counter()

    try:
        if ensure_base_state:
            ensure_page_state(load_models=False, force_reload=force_reload, weeks=weeks)

        if force_reload:
            invalidate_load_state_cache(clear_recent=True, clear_full=False)

        load_inputs_available = any(st.session_state.get(key) is not None for key in LOAD_DATASET_KEYS)
        store_version = current_load_state_version()
        if not load_state_needs_rebuild(store_version=store_version):
            record_performance_debug_artifact("load_state", "reutilizado" if load_inputs_available else "no disponible")
            return False

        prepared_raw_df = ensure_prepared_raw_workouts(ensure_base_state=False)
        acwr_dict, mono_dict = build_load_models(st.session_state.get("rpe_df"))
        st.session_state["acwr_dict"] = acwr_dict or None
        st.session_state["mono_dict"] = mono_dict or None
        st.session_state["weekly_summaries"] = build_weekly_summaries(
            st.session_state.get("rpe_df"),
            st.session_state.get("wellness_df"),
            st.session_state.get("raw_df"),
            acwr_dict=acwr_dict or {},
            prepared_raw_df=prepared_raw_df,
        )
        mark_load_state_built(store_version=store_version)
        record_performance_debug_artifact("load_state", "reconstruido" if load_inputs_available else "no disponible")
        return True
    finally:
        record_performance_debug_timing("ensure_load_state_s", time.perf_counter() - started_at)


def ensure_history_mode_load_state(
    mode: str,
    *,
    force_reload: bool = False,
    weeks: int = RECENT_WEEKS,
) -> dict[str, object]:
    _ensure_session_defaults()

    if mode != HISTORY_MODE_FULL:
        ensure_load_state(force_reload=force_reload, ensure_base_state=True, weeks=weeks)
        return {
            "rpe_df": st.session_state.get("rpe_df"),
            "wellness_df": st.session_state.get("wellness_df"),
            "raw_df": st.session_state.get("raw_df"),
            "prepared_raw_df": st.session_state.get(PREPARED_RAW_DF_KEY),
            "acwr_dict": st.session_state.get("acwr_dict") or {},
            "mono_dict": st.session_state.get("mono_dict") or {},
            "weekly_summaries": st.session_state.get("weekly_summaries") or {},
        }

    if force_reload:
        invalidate_load_state_cache(clear_recent=False, clear_full=True)

    store_version = current_load_state_version()
    cached_state = st.session_state.get(FULL_HISTORY_LOAD_STATE_KEY)
    cached_version = st.session_state.get(FULL_HISTORY_LOAD_STATE_VERSION_KEY)
    if (
        not isinstance(cached_state, dict)
        or cached_version != store_version
        or not _has_valid_weekly_summaries(cached_state.get("weekly_summaries"))
    ):
        full_state = ensure_full_history_state(keys=LOAD_DATASET_KEYS, force_reload=force_reload)
        rpe_df = full_state.get("rpe_df")
        wellness_df = full_state.get("wellness_df")
        raw_df = full_state.get("raw_df")
        prepared_raw_df = prepare_raw_workouts_df(raw_df)
        acwr_dict, mono_dict = build_load_models(rpe_df, weeks=None)
        cached_state = {
            "rpe_df": rpe_df,
            "wellness_df": wellness_df,
            "raw_df": raw_df,
            "prepared_raw_df": prepared_raw_df,
            "acwr_dict": acwr_dict or {},
            "mono_dict": mono_dict or {},
            "weekly_summaries": build_weekly_summaries(
                rpe_df,
                wellness_df,
                raw_df,
                acwr_dict=acwr_dict or {},
                prepared_raw_df=prepared_raw_df,
            ),
        }
        st.session_state[FULL_HISTORY_LOAD_STATE_KEY] = cached_state
        st.session_state[FULL_HISTORY_LOAD_STATE_VERSION_KEY] = store_version
        st.session_state[FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY] = time.time()

    return st.session_state[FULL_HISTORY_LOAD_STATE_KEY]


def ensure_full_history_state(
    *,
    keys: list[str] | None = None,
    force_reload: bool = False,
) -> dict[str, object]:
    _ensure_session_defaults()
    selected_keys = keys or list(DATASET_SPECS.keys())
    store_version = current_local_store_version(keys=selected_keys)
    cached_state = st.session_state.get(FULL_HISTORY_STATE_KEY)
    cached_version = st.session_state.get(FULL_HISTORY_STATE_VERSION_KEY)
    cached_keys = tuple(st.session_state.get(FULL_HISTORY_STATE_KEYS_KEY) or ())
    effective_keys = tuple(selected_keys)

    if force_reload or cached_state is None or cached_version != store_version or cached_keys != effective_keys:
        full_state = load_full_history_state(keys=list(effective_keys))
        st.session_state[FULL_HISTORY_STATE_KEY] = full_state
        st.session_state[FULL_HISTORY_STATE_VERSION_KEY] = store_version
        st.session_state[FULL_HISTORY_STATE_KEYS_KEY] = effective_keys

    return st.session_state[FULL_HISTORY_STATE_KEY]


def collect_state_athletes(dataset_keys: list[str] | None = None) -> list[str]:
    keys = dataset_keys or DATASET_SESSION_KEYS
    athletes: set[str] = set()
    for key in keys:
        frame = st.session_state.get(key)
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        athletes.update(frame["Athlete"].dropna().astype(str).str.strip().tolist())
    return sorted(athletes)
