"""Database package: SQLite persistence via SQLAlchemy (connection, models, repository).

Implemented in Phase 7 as an append-only audit store for Phase 5
recommendation plans/records and Phase 6 review events. See
``database.connection`` (URL resolution and schema bootstrap),
``database.models`` (table definitions), and ``database.repository``
(validated writes and deterministic queries).
"""
