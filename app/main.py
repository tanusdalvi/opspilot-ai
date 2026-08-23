"""OpsPilot AI — Streamlit application entry point (Phase 11).

Single-process architecture:

    Browser -> Streamlit -> app.orchestrator -> existing tested services
            -> database.repository -> SQLite

The deterministic pipeline (data -> validation -> analytics -> anomalies
-> insights -> evidence -> recommendations) is fully usable without any
AI configuration; the optional Gemini investigation lives only on the
Evidence page behind an explicit user action.

Phase 11 keeps every functional contract from earlier phases and wraps
it in the premium dark design system defined under ``app.ui``: grouped
navigation, Material icons, and a sidebar that reflects real workflow
state (dataset, analysis lifecycle, recovery availability).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui import components, shell  # noqa: E402
from core.constants import APPLICATION_NAME  # noqa: E402

st.set_page_config(
    page_title=f"{APPLICATION_NAME} — Operations Intelligence",
    page_icon=":material/monitoring:",
    layout="wide",
    # Navigation must be visible immediately after startup at any viewport
    # width; "auto" would auto-collapse the sidebar on narrow windows.
    initial_sidebar_state="expanded",
)

components.apply_theme()

PAGES_DIR = Path(__file__).resolve().parent / "pages"

with st.sidebar:
    shell.render_sidebar(APPLICATION_NAME, "Operations Intelligence")

st.navigation(shell.build_pages(PAGES_DIR)).run()
