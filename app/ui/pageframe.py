"""Standalone page-frame renderer (no dependency on ``app.state``).

Kept free of lifecycle imports so ``app.state.run_page`` can use it
without creating an import cycle: this module only touches Streamlit,
the token theme, and the SVG icon registry.
"""

from __future__ import annotations

import streamlit as st

from app.ui.icons import escape_label, icon_html


def render_page_frame(icon: str, eyebrow: str, title: str,
                      subtitle: str | None) -> None:
    """Render the premium hero header for a page (replaces st.title)."""
    sub_html = (
        f"<p class='ops-hero-sub'>{escape_label(subtitle)}</p>" if subtitle else ""
    )
    st.markdown(
        "<div class='ops-hero'>"
        "<div class='ops-hero-row'>"
        f"<div class='ops-hero-icon'>{icon_html(icon, size=24)}</div>"
        "<div>"
        f"<p class='ops-eyebrow'>{escape_label(eyebrow)}</p>"
        f"<h1 class='ops-hero-title'>{escape_label(title)}</h1>"
        f"{sub_html}"
        "</div></div></div>",
        unsafe_allow_html=True,
    )
