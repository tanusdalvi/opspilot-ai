# OpsPilot AI

Agentic AI-powered **operations intelligence and decision-support platform**.
OpsPilot ingests operational business data (CSV), validates it, computes
deterministic analytics, detects and explains anomalies, builds a citable
evidence pack, generates prioritized recommendations, and requires an explicit
**human decision** for every action — with the full trail recorded in an
append-only audit store.

## Problem statement

Operations teams drown in dashboards that show *what* happened but never tie
signals to decisions. Generic AI tools hallucinate causes and skip governance.
OpsPilot closes that gap:

- every number is computed by deterministic, tested Python services;
- the AI may only narrate and hypothesize about evidence it can cite;
- nothing consequential happens without a named human reviewer;
- every plan, snapshot, and decision is permanently auditable.

## Current status

**Phase 9 — Audit completeness, exports & data hardening** (in progress).

Completed phases: foundation, data loading/validation, deterministic
analytics, anomaly detection, insight engine, evidence pack,
evidence-grounded Gemini investigation, recommendation engine, human review
workflow, SQLite audit persistence, Streamlit application shell, and Phase 8A
pipeline/lifecycle stabilization.

## Architecture

Single-process Streamlit application over deterministic services:

```
Browser → Streamlit (app/) → app.orchestrator → services/ + agent/
                                              → database.repository → SQLite
```

The optional Gemini investigation is an explicit, user-triggered step on the
Evidence page. It can narrate and hypothesize, but it can never change scores,
statuses, persistence rules, or review transitions.

## Functional workflow

```
DATA → VALIDATION → ANALYTICS → ANOMALY DETECTION → INSIGHTS
     → EVIDENCE PACK → [OPTIONAL GEMINI INVESTIGATION]
     → RECOMMENDATIONS → HUMAN REVIEW → AUDIT / HISTORY
```

## Major components

| Component | Path | Responsibility |
|---|---|---|
| Configuration | `core/config.py` | `.env` loading, `GEMINI_API_KEY`, environment helpers |
| Constants | `core/constants.py` | Shared vocabularies, upload limits |
| Exceptions | `core/exceptions.py` | Typed error taxonomy (`OpsPilotError`) |
| Data service | `services/data_service.py` | Demo dataset discovery, safe CSV loading |
| Validation | `services/validation_service.py` | Schema/type/range/date/duplicate checks; errors block analysis |
| Analytics | `services/analytics_service.py` | KPIs, daily trends, period comparison, performer rankings |
| Anomalies | `services/anomaly_service.py` | Deterministic statistical detection + severity summaries |
| Insights | `services/insight_service.py` | Factor attribution, explanations, grouping |
| Evidence | `agent/evidence.py` | Canonical evidence pack (`E<id>` index) |
| Investigation | `agent/investigator.py` | Grounding validator, retry loop, safe fallback |
| Gemini client | `agent/gemini_client.py` | Thin SDK wrapper (temperature 0, JSON responses) |
| Recommendations | `agent/recommendation_service.py` | Deterministic ranking/deduplication; AI = provenance only |
| Human review | `agent/review_service.py` | Enforced status transitions with reviewer identity |
| Persistence | `database/repository.py` | Append-only plans/snapshots/events; plan provenance reads |
| Connection | `database/connection.py` | SQLite-only engine resolution, idempotent schema |
| Exports | `app/exports.py` | Deterministic JSON/CSV serializations |
| Orchestrator | `app/orchestrator.py` | Thin composition of the above; upload staging |
| Application | `app/main.py`, `app/state.py`, `app/pages/*.py` | Streamlit shell, lifecycle, nine pages |

## Repository structure

```
opspilot-ai/
├── app/          # Streamlit application (entry point, state, pages, exports)
├── core/         # Configuration, constants, exception hierarchy
├── services/     # Deterministic business logic (data, validation, analytics,
│                 #   anomalies, insights)
├── agent/        # Evidence pack, Gemini investigation, recommendations, review
├── database/     # SQLite persistence (connection, models, repository)
├── tests/        # Automated pytest suite
├── scripts/      # Demo dataset generator
└── data/         # Runtime data: raw/, processed/, demo/, uploads/ (gitignored)
```

The `ml/` package is an intentional placeholder; anomaly detection is fully
deterministic today and no machine-learning model ships with this product.

## Data flow

1. **Load** — pick a demo dataset or upload a CSV (`data/uploads/` staging;
   basename-only paths, `.csv` only, size-limited, duplicates replace).
2. **Validate** — read-only gate: missing columns, unexpected columns, nulls,
   bad types, out-of-range numerics, unparseable dates, duplicate rows.
   Errors block analysis; warnings do not. No rows are dropped or imputed.
3. **Analyze** — one deterministic pass produces KPIs, trends, period
   comparison, performer rankings, anomalies, insights, groups, and the
   evidence pack.
4. **Investigate (optional)** — Gemini narrates strictly grounded findings.
5. **Recommend** — deterministic plan generation with explainable priority.
6. **Review** — APPROVE / REJECT / REQUEST_CHANGES / RESUBMIT with a required
   reviewer identity.
7. **Audit** — plans, snapshots, and events are queryable forever.

## Analytics

Daily totals and trends across units sold, revenue, cost, profit, margin, and
lead time; first-half versus second-half period comparison with percentage
changes; region and product performer rankings.

## Anomaly detection

Deterministic statistical detection (z-score style deviation rules) across
configured metrics with sensitivity levels, severity classification
(CRITICAL/HIGH/MEDIUM/LOW), scoring, grouping of related records, and
per-record explanations (observed vs expected, deviation, rule, z-score).

## Evidence system

`agent/evidence.py` builds a canonical pack containing KPIs, period changes,
performer rankings, correlations, anomalies, and groups — every fact addressable
as `E<id>`. The pack is the single factual source for both the AI investigation
and the recommendation layer. No raw rows or CSV text ever leave the process.

## Gemini investigation

Triggered only by an explicit button press on the Evidence page. The response
must be valid JSON matching the mandated schema, cite existing evidence ids for
every factual finding, use numbers that appear verbatim in the evidence pack,
avoid causal language, and avoid unsupported dates. Failures trigger up to two
corrective retries; exhausted retries return a safe fallback narrative marked
`narrative_rejected`. The AI never influences scoring, priorities, statuses, or
persistence — its output contributes only provenance metadata.

## Recommendations

The deterministic engine converts grouped anomalies into deduplicated,
prioritized actions with source factors, linked anomaly indices, group ids, and
cited evidence ids. Priority scoring depends solely on deterministic inputs.

## Human review

Every recommendation starts `PENDING`. Transitions are enforced exactly:
`PENDING+APPROVE→APPROVED`, `PENDING+REJECT→REJECTED`,
`PENDING+REQUEST_CHANGES→CHANGES_REQUESTED`,
`CHANGES_REQUESTED+RESUBMIT→PENDING`. Terminal states accept no further
actions. Reviewer id is mandatory; comments are recorded verbatim.

## SQLite audit persistence

Append-only store (`database/models.py`): `recommendation_plans`,
`recommendations` (immutable snapshots), `review_events`. Writes validate the
full structural contract first; reviews persist snapshot + event atomically.
Read APIs cover latest/latest-per-id snapshots, event listing, counts, and
Phase 9 plan provenance reads (`list_plans`, `get_plan`). No update or delete
path exists anywhere in the package.

## Exports

Deterministic downloads built by `app/exports.py` (Overview and History
pages):

- **Analysis Summary JSON** — dataset metadata, validation summary, KPIs,
  period comparison, trend bounds, anomaly summary, insight headlines,
  performer rankings.
- **Anomalies CSV** — stable column order, pipeline row order.
- **Plans + Audit JSON** — full plan provenance, parameters, snapshots with
  evidence ids and statuses, and every recorded review event.

Identical inputs always produce byte-identical files.

## CSV upload

Staged under gitignored `data/uploads/` with basename sanitization,
path-traversal protection, `.csv`-only restriction, empty-file rejection, a
20 MiB hard limit enforced before parsing, friendly typed messages for binary
or malformed files, and an advisory warning above 500,000 rows. Re-uploading
an identical basename deterministically replaces the staged copy. Uploads are
never persisted to the audit store.

## Streamlit application

Run with the commands below; the sidebar shows environment and database
status. The analysis lifecycle is `IDLE → ANALYZING → READY | ERROR`, so
results can never silently go stale mid-run, and duplicate executions are
prevented.

## Environment configuration

Copy `.env.example` to `.env`:

```
GEMINI_API_KEY=your_api_key_here
DATABASE_URL=sqlite:///opspilot.db
APP_ENV=development
```

`GEMINI_API_KEY` behavior: when absent, the AI investigation reports
*Disabled* and the deterministic pipeline remains fully usable. When present,
investigations run through `agent/gemini_client.py`; the key is read from the
environment only and is never logged, displayed, or embedded in errors.

Only SQLite URLs are accepted; anything else fails closed at startup.

## Running locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # add your own GEMINI_API_KEY if desired
streamlit run app/main.py
```

Regenerate the bundled demo dataset (seeded, deterministic):

```powershell
python scripts/generate_demo_data.py
```

## Running tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers every service, the agent layer (with injected fake clients —
no network calls), the repository contract, the orchestrator, and the
Streamlit pages via `streamlit.testing.v1.AppTest`.

## Known limitations

- Single-user local application; no authentication or multi-tenancy.
- SQLite only; not intended for production deployment as shipped.
- Session artifacts live in memory; after a restart, re-run the analysis
  (the audit store persists regardless).
- The optional AI investigation requires network access and a valid key;
  without them the app degrades gracefully.
- Large datasets work but analysis time grows with row count (advisory at
  500k rows).

## Security notes

- Secrets are read exclusively from the environment; `.env` is gitignored.
- Error boundaries display typed messages, never tracebacks; database errors
  are rendered with a static sanitized string (no SQL, paths, or driver
  details).
- Uploads are confined to `data/uploads/` via basename-only staging.
- Exports exclude secrets, raw data rows, and internal diagnostics.

## Audit model

Everything decision-relevant is stored once and never rewritten: the plan
(with parameters, provenance, summary), one immutable snapshot per
recommendation at creation, and one immutable snapshot plus structured event
per review. History reconstructs the complete story of any plan; exports make
the same story portable.
