# OpsPilot AI

## Description

OpsPilot AI is an **agentic AI-powered operations intelligence and decision-support platform**.
It is designed to help operations teams ingest business data, monitor operational KPIs,
detect unusual patterns, investigate issues with an AI agent, and make
**human-reviewed, evidence-backed decisions** — with every investigation and action
recorded for audit purposes.

## Current Status

**Phase 1 — Foundation**

Only the project structure, configuration system, constants, and exception
hierarchy exist today. No business features are implemented yet.

## Planned Architecture

The intended end-to-end flow of the platform:

```
Data
  → Validation
  → Analytics
  → Alerts
  → Anomaly Detection
  → Agent Investigation
  → Evidence
  → Recommendations
  → Human Review
  → Audit
```

## Technology Stack

- **Python** — core application language
- **Streamlit** — web application UI
- **Pandas** — data manipulation and analytics
- **Scikit-learn** — anomaly detection (planned)
- **SQLite + SQLAlchemy** — persistence (planned)
- **Gemini API** — AI agent reasoning (planned)
- **Git/GitHub** — version control

## Project Structure

```
opspilot-ai/
├── app/          # Streamlit application (entry point, pages, components)
├── core/         # Configuration, constants, exception hierarchy
├── services/     # Business logic services (data, analytics, alerts, reports)
├── ml/           # Machine learning modules (anomaly detection, features)
├── agent/        # Gemini-powered investigation agent (tools, schemas, prompts)
├── database/     # SQLite persistence (connection, models, repository)
├── tests/        # Automated tests (pytest)
├── scripts/      # Utility scripts (e.g. demo dataset generation)
└── data/         # Runtime data: raw/, processed/, demo/
```

## Running Locally

1. Create/activate the Python virtual environment (Windows PowerShell):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your own `GEMINI_API_KEY`
   (the key is not required until the AI agent phase; never commit `.env`).

4. Run the application:

   ```powershell
   streamlit run app/main.py
   ```

## Notes & Limitations

- The UI currently shows only a foundation status page — there are no KPIs,
  charts, alerts, or AI responses yet, by design.
- No data ingestion, validation, anomaly detection, agent, or database logic exists.
- Nothing in this repository claims production readiness.
