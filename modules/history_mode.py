"""Shared UI helpers for switching between recent and full history views."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from local_store import (
    HISTORY_MODE_FULL,
    HISTORY_MODE_RECENT,
    RECENT_WEEKS,
    get_available_week_range,
)


HISTORY_MODE_LABELS = {
    HISTORY_MODE_RECENT: f"Ultimas {RECENT_WEEKS} semanas disponibles",
    HISTORY_MODE_FULL: "Historial completo",
}


def history_mode_label(mode: str) -> str:
    return HISTORY_MODE_LABELS.get(mode, HISTORY_MODE_LABELS[HISTORY_MODE_RECENT])


def render_history_mode_selector(
    *,
    key: str,
    label: str = "Rango visible",
) -> str:
    options = [HISTORY_MODE_RECENT, HISTORY_MODE_FULL]
    if st.session_state.get(key) not in options:
        st.session_state[key] = HISTORY_MODE_RECENT
    return st.radio(
        label,
        options,
        format_func=history_mode_label,
        horizontal=True,
        key=key,
    )


def history_mode_caption(
    df: pd.DataFrame | None,
    *,
    mode: str,
    date_col: str | None = None,
    week_col: str = "week_start",
) -> str:
    weeks = None if mode == HISTORY_MODE_FULL else RECENT_WEEKS
    range_start, range_end = get_available_week_range(
        df,
        date_col=date_col,
        week_col=week_col,
        weeks=weeks,
    )
    label = history_mode_label(mode)
    if range_start is None or range_end is None:
        return f"Vista: {label}."
    return f"Vista: {label} ({pd.Timestamp(range_start):%d/%m/%Y} - {pd.Timestamp(range_end):%d/%m/%Y})."
