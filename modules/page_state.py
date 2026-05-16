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
    if FULL_HISTORY_LOAD_STATE_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_KEY] = None
    if FULL_HISTORY_LOAD_STATE_VERSION_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_VERSION_KEY] = None
    if FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY not in st.session_state:
        st.session_state[FULL_HISTORY_LOAD_STATE_LAST_BUILD_TS_KEY] = None


def current_local_store_version(keys: list[str] | None = None) -> tuple[tuple[str, bool, int, int], ...]:
    return get_local_store_version(keys=keys)


def current_load_state_version(keys: list[str] | None = None) -> tuple[tuple[str, bool, int, int], ...]:
    return current_local_store_version(keys=keys or LOAD_DATASET_KEYS)


def current_raw_df_version() -> tuple[tuple[str, bool, int, int], ...]:
    return current_local_store_version(keys=["raw_df"])


def _has_valid_weekly_summaries(value: object) -> bool:
    return isinstance(value, dict) and WEEKLY_SUMMARY_KEYS.issubset(value.keys())


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
    if clear_load_state:
        invalidate_load_state_cache(clear_recent=True, clear_full=True)
    if clear_full_history:
        st.session_state.pop(FULL_HISTORY_STATE_KEY, None)
        st.session_state.pop(FULL_HISTORY_STATE_VERSION_KEY, None)
        st.session_state.pop(FULL_HISTORY_STATE_KEYS_KEY, None)


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

    if ensure_base_state:
        ensure_page_state(load_models=False, force_reload=force_reload, weeks=weeks)

    if force_reload:
        st.session_state[PREPARED_RAW_DF_KEY] = None
        st.session_state[PREPARED_RAW_DF_VERSION_KEY] = None
        st.session_state[PREPARED_RAW_DF_LAST_BUILD_TS_KEY] = None

    raw_version = current_raw_df_version()
    if not prepared_raw_workouts_needs_rebuild(raw_version=raw_version):
        return st.session_state.get(PREPARED_RAW_DF_KEY)

    prepared_raw_df = prepare_raw_workouts_df(st.session_state.get("raw_df"))
    st.session_state[PREPARED_RAW_DF_KEY] = prepared_raw_df
    mark_prepared_raw_workouts_built(raw_version=raw_version)
    return prepared_raw_df


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

    if ensure_base_state:
        ensure_page_state(load_models=False, force_reload=force_reload, weeks=weeks)

    if force_reload:
        invalidate_load_state_cache(clear_recent=True, clear_full=False)

    store_version = current_load_state_version()
    if not load_state_needs_rebuild(store_version=store_version):
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
    return True


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
