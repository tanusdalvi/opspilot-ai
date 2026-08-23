"""OpsPilot AI backend API adapters (Phase 12).

This package is a thin transport boundary over the existing
intelligence engine. It contains NO business rules: every analytical,
recommendation, review, audit, and investigation decision is delegated
to ``app.orchestrator`` and the services behind it, exactly as the
Streamlit application does.
"""
