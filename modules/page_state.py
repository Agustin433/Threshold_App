"""Shared Streamlit page bootstrap helpers."""

from __future__ import annotations

import streamlit as st

from local_store import build_load_models, load_recent_state

SESSION_KEYS = [
    "rpe_df",
    "wellness_df",
    "completion_df",
    "rep_load_df",
    "raw_df",
    "maxes_df",
    "jump_df",
    "acwr_dict",
    "mono_dict",
]


def ensure_page_state(load_models: bool = True) -> None:
    for key in SESSION_KEYS:
        if key not in st.session_state:
            st.session_state[key] = None

    stored_state = load_recent_state()
    for key in SESSION_KEYS:
        if st.session_state[key] is None:
            st.session_state[key] = stored_state.get(key)

    if (
        load_models
        and st.session_state.rpe_df is not None
        and (st.session_state.acwr_dict is None or st.session_state.mono_dict is None)
    ):
        acwr_dict, mono_dict = build_load_models(st.session_state.rpe_df)
        st.session_state.acwr_dict = acwr_dict or None
        st.session_state.mono_dict = mono_dict or None


def collect_state_athletes(dataset_keys: list[str] | None = None) -> list[str]:
    keys = dataset_keys or ["rpe_df", "wellness_df", "completion_df", "rep_load_df", "raw_df", "maxes_df", "jump_df"]
    athletes: set[str] = set()
    for key in keys:
        frame = st.session_state.get(key)
        if frame is None or frame.empty or "Athlete" not in frame.columns:
            continue
        athletes.update(frame["Athlete"].dropna().astype(str).str.strip().tolist())
    return sorted(athletes)
