"""OpsPilot AI presentation layer (Phase 11).

Design-system primitives shared by the app shell and every page:

* ``theme``      — color/typography tokens and the global stylesheet.
* ``icons``      — inline SVG icon registry (no emoji, no network fetch).
* ``components`` — cards, badges, hero headers, empty/loading states,
                   the sidebar brand/dataset/workflow rail.
* ``charts``     — Altair chart builders with the OpsPilot dark theme.
* ``shell``      — navigation structure and sidebar composition.

Presentation only: nothing here implements business rules or touches
services, the orchestrator contract, or persistence.
"""
