"""OpsPilot AI — Streamlit application entry point.

Phase 1 (Foundation): this file only proves that the application shell
starts and renders. Business features (data ingestion, analytics, alerts,
anomaly detection, AI investigation, database, reports) are implemented
in later phases.
"""

import streamlit as st

from core.config import get_environment, has_gemini_api_key
from core.constants import APPLICATION_NAME

st.set_page_config(
    page_title=f"{APPLICATION_NAME} — Operations Intelligence",
    page_icon="📊",
    layout="wide",
)

st.title(APPLICATION_NAME)
st.subheader(
    "Agentic AI-Powered Operations Intelligence and Decision Support Platform"
)

st.markdown(
    """
    OpsPilot AI helps operations teams ingest business data, monitor KPIs,
    detect unusual patterns, investigate operational issues with an AI agent,
    and make **human-reviewed, evidence-backed decisions**.
    """
)

st.success("Project foundation is ready: package structure and configuration are in place.")

with st.expander("Current project phase", expanded=True):
    st.markdown("**Phase 1 — Foundation**")
    st.markdown(
        """
        Currently implemented:

        - Project/package structure (`app`, `core`, `services`, `ml`, `agent`, `database`)
        - Environment-based configuration (`core/config.py`)
        - Shared constants (`core/constants.py`) and exception hierarchy (`core/exceptions.py`)

        Not yet implemented (planned for later phases):

        - Demo data generation and CSV upload
        - Data validation, analytics, and KPI dashboard
        - Operational alerts and Isolation Forest anomaly detection
        - Gemini-powered agentic investigation and recommendations
        - SQLite persistence, audit logs, and the executive report
        """
    )

st.sidebar.header(APPLICATION_NAME)
st.sidebar.markdown(
    f"Environment: `{get_environment()}`  |  "
    f"Gemini API key configured: `{has_gemini_api_key()}`"
)
st.sidebar.caption("Phase 1 — Foundation")
