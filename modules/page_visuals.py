"""Shared visual helpers for secondary Streamlit pages."""

from __future__ import annotations

import streamlit as st


PAGE_COLORS = {
    "navy": "#0D3C5E",
    "steel": "#708C9F",
    "blue": "#4A9FD4",
    "green": "#6F8F78",
    "yellow": "#C4A464",
    "orange": "#C88759",
    "red": "#B56B73",
    "muted": "#5E6A74",
    "bg": "#F5F4F0",
    "card": "#FEFEFE",
    "white": "#221F20",
    "gray": "#4B5560",
    "border": "#D8DEE4",
}


def build_page_theme() -> dict:
    return {
        "colors": PAGE_COLORS,
        "layout": dict(
            template="plotly_white",
            paper_bgcolor=PAGE_COLORS["bg"],
            plot_bgcolor=PAGE_COLORS["card"],
            font=dict(family="Barlow, sans-serif", color=PAGE_COLORS["white"], size=11),
            margin=dict(l=44, r=32, t=68, b=48),
        ),
        "grid": "rgba(34, 31, 32, 0.08)",
        "grid_soft": "rgba(34, 31, 32, 0.05)",
        "reference_line": "rgba(34, 31, 32, 0.18)",
        "reference_fill": "rgba(13, 60, 94, 0.06)",
        "legend": dict(
            orientation="h",
            y=-0.18,
            bgcolor="rgba(254, 254, 254, 0.92)",
            bordercolor=PAGE_COLORS["border"],
            borderwidth=1,
            font=dict(size=9, color=PAGE_COLORS["gray"]),
        ),
        "monotony_high": 2.0,
    }


def render_insight_block(payload: dict[str, object] | None, *, fallback_title: str = "Lectura") -> None:
    if not payload:
        return

    title = str(payload.get("title") or fallback_title)
    summary = str(payload.get("summary") or "").strip()
    focuses = [str(item).strip() for item in payload.get("focuses", []) if str(item).strip()]

    st.markdown(f"### {title}")
    if summary:
        st.info(summary)
    if focuses:
        st.caption("Focos sugeridos")
        for item in focuses:
            st.markdown(f"- {item}")
