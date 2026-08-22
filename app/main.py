"""OpsPilot AI — Streamlit application entry point (Phase 8).

Single-process architecture:

    Browser -> Streamlit -> app.orchestrator -> existing tested services
            -> database.repository -> SQLite

The deterministic pipeline (data -> validation -> analytics -> anomalies
-> insights -> evidence -> recommendations) is fully usable without any
AI configuration; the optional Gemini investigation lives only on the
Evidence page behind an explicit user action.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import get_environment, has_gemini_api_key  # noqa: E402
from core.constants import APPLICATION_NAME  # noqa: E402

st.set_page_config(
    page_title=f"{APPLICATION_NAME} — Operations Intelligence",
    page_icon="📊",
    layout="wide",
)

PAGES_DIR = Path(__file__).resolve().parent / "pages"

pages = [
    st.Page(str(PAGES_DIR / "overview.py"), title="Overview", icon="🏠", default=True),
    st.Page(str(PAGES_DIR / "data.py"), title="Data", icon="📥"),
    st.Page(str(PAGES_DIR / "analytics.py"), title="Analytics", icon="📈"),
    st.Page(str(PAGES_DIR / "insights.py"), title="Insights", icon="💡"),
    st.Page(str(PAGES_DIR / "anomalies.py"), title="Anomalies", icon="🚨"),
    st.Page(str(PAGES_DIR / "evidence.py"), title="Evidence", icon="🔎"),
    st.Page(str(PAGES_DIR / "recommendations.py"), title="Recommendations", icon="🧭"),
    st.Page(str(PAGES_DIR / "review.py"), title="Human Review", icon="✅"),
    st.Page(str(PAGES_DIR / "history.py"), title="Audit History", icon="🗂️"),
]

with st.sidebar:
    st.header(APPLICATION_NAME)
    st.markdown(
        "**DATA → INSIGHT → EVIDENCE**<br>**→ RECOMMENDATION**<br>"
        "**→ HUMAN DECISION → AUDIT**",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Environment: `{get_environment()}`  |  "
        f"Gemini key configured: `{has_gemini_api_key()}`"
    )
    if not has_gemini_api_key():
        st.caption(
            "No GEMINI_API_KEY set: the AI investigation is disabled; all "
            "deterministic analysis remains available."
        )

st.navigation(pages).run()
