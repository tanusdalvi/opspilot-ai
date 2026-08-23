"""Application shell: grouped navigation spec and sidebar composition.

The navigation table below is plain data so tests can assert on the
information architecture without executing the Streamlit runtime:
five intent-based groups, Material icon names only (never emoji).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.config import get_environment, has_gemini_api_key

# group label -> [(page title, file stem, material icon name)]
NAV_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("COMMAND CENTER", [
        ("Overview", "overview", "space_dashboard"),
    ]),
    ("DATA", [
        ("Data", "data", "database"),
    ]),
    ("INTELLIGENCE", [
        ("Analytics", "analytics", "monitoring"),
        ("Anomalies", "anomalies", "crisis_alert"),
        ("Insights", "insights", "lightbulb"),
        ("Evidence", "evidence", "fact_check"),
    ]),
    ("DECISION", [
        ("Recommendations", "recommendations", "route"),
        ("Human Review", "review", "task_alt"),
    ]),
    ("AUDIT", [
        ("History", "history", "history"),
    ]),
]

FLAT_PAGES: dict[str, tuple[str, str]] = {
    title: (stem, icon)
    for _, entries in NAV_SECTIONS
    for title, stem, icon in entries
}


def build_pages(pages_dir: Path) -> dict[str, list[st.Page]]:
    """Materialize the grouped ``st.Page`` structure for ``st.navigation``."""
    return {
        group: [
            st.Page(
                str(pages_dir / f"{stem}.py"),
                title=title,
                icon=f":material/{icon}:",
            )
            for title, stem, icon in entries
        ]
        for group, entries in NAV_SECTIONS
    }

def render_sidebar(app_name: str, tagline: str) -> None:
    """Compose the premium sidebar: brand, dataset chip, workflow rail, meta."""
    from app.ui.components import (
        brand_header,
        dataset_chip,
        sidebar_footer,
        workflow_rail,
    )

    brand_header(app_name, tagline)
    dataset_chip()
    workflow_rail()
    gemini_configured = has_gemini_api_key()
    if not gemini_configured:
        st.caption(
            "No GEMINI_API_KEY set: the AI investigation is disabled; all "
            "deterministic analysis remains available."
        )
    sidebar_footer(get_environment(), gemini_configured)
