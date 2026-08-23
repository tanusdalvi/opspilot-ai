"""Reusable presentation components for OpsPilot pages (Phase 11).

Every helper renders directly through Streamlit and is presentation
only. Dynamic values are HTML-escaped before being embedded in markup;
lifecycle decisions always come from ``app.state`` session helpers, so
these components can never fabricate analysis results.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import streamlit as st

from app.state import (
    ANALYSIS_ERROR,
    ANALYSIS_READY,
    ANALYSIS_RUNNING,
    get_analysis_status,
)
from app.ui.icons import escape_label, icon_html
from app.ui.theme import apply_theme, severity_color

__all__ = [
    "apply_theme",
    "hero",
    "section",
    "metric_card",
    "metric_row",
    "badge",
    "severity_badge",
    "chip",
    "chips_row",
    "card",
    "empty_state",
    "loading_panel",
    "skeleton_lines",
    "skeleton_cards",
    "strength_meter",
    "kv_grid",
    "status_dot",
    "timeline_item",
    "timeline",
    "stepper",
    "stage_checklist",
    "brand_header",
    "dataset_chip",
    "workflow_rail",
    "workflow_stepper",
    "sidebar_footer",
]

_TONE_CLASSES = {
    "muted": "",
    "accent": "ops-tone-accent",
    "success": "ops-tone-success",
    "warning": "ops-tone-warning",
    "danger": "ops-tone-danger",
    "info": "ops-tone-info",
    "ai": "ops-tone-ai",
}


def _md(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)


# --- page scaffolding ------------------------------------------------------------------------


def hero(icon: str, eyebrow: str, title: str, description: str | None = None,
         chips: Sequence[tuple[str, str]] = ()) -> None:
    """Render the premium page header band."""
    chip_html = "".join(
        f'<span class="ops-chip {_TONE_CLASSES.get(tone, "")}">{escape_label(text)}</span>'
        for text, tone in chips
    )
    chips_html = f'<div class="ops-hero-chips">{chip_html}</div>' if chip_html else ""
    sub_html = (
        f'<p class="ops-hero-sub">{escape_label(description)}</p>' if description else ""
    )
    _md(
        "<div class='ops-hero'>"
        "<div class='ops-hero-row'>"
        f"<div class='ops-hero-icon'>{icon_html(icon, size=24)}</div>"
        "<div>"
        f"<p class='ops-eyebrow'>{escape_label(eyebrow)}</p>"
        f"<h1 class='ops-hero-title'>{escape_label(title)}</h1>"
        f"{sub_html}"
        "</div></div>"
        f"{chips_html}"
        "</div>"
    )


def section(title: str, icon: str | None = None,
            caption: str | None = None) -> None:
    """A labeled section header with a hairline rule."""
    icon_part = icon_html(icon, size=16) if icon else ""
    cap_part = (
        f'<span class="ops-card-sub" style="margin-left:8px">{escape_label(caption)}</span>'
        if caption
        else ""
    )
    _md(
        "<div style='display:flex;align-items:center;gap:8px;margin:1.15rem 0 .55rem'>"
        f"{icon_part}<span style='font-weight:650;color:var(--ops-text);font-size:.98rem'>"
        f"{escape_label(title)}</span>{cap_part}"
        "<span style='flex:1;height:1px;background:var(--ops-line)'></span>"
        "</div>"
    )


# --- cards / metrics -------------------------------------------------------------------------


def card(content_html: str, *, hover: bool = False,
         severity: object | None = None) -> None:
    """One standalone surface card."""
    hover_cls = " ops-hover" if hover else ""
    stripe = (
        f" style=\"--ops-sev:{severity_color(severity)}\" class='ops-sev-stripe'"
        if severity is not None
        else ""
    )
    _md(f"<div class='ops-card{hover_cls}'{stripe}>{content_html}</div>")


def metric_card(label: str, value: object, *, delta: str | None = None,
                delta_tone: str = "neutral", icon: str | None = None,
                caption: str | None = None) -> None:
    """A single KPI tile rendered as HTML (tabular numerals, semantic delta)."""
    icon_part = f"{icon_html(icon, size=14)}" if icon else ""
    delta_html = ""
    if delta:
        arrows = {"good": "&#9650;", "bad": "&#9660;"}
        arrow = arrows.get(delta_tone, "&#9644;")
        delta_html = (
            f"<div class='ops-metric-delta ops-{delta_tone}'>"
            f"<span>{arrow}</span><span>{escape_label(delta)}</span></div>"
        )
    caption_html = (
        f"<div class='ops-metric-caption'>{escape_label(caption)}</div>" if caption else ""
    )
    _md(
        "<div class='ops-card ops-hover'>"
        f"<div class='ops-metric-label'>{icon_part}<span>{escape_label(label)}</span></div>"
        f"<div class='ops-metric-value'>{escape_label(value)}</div>"
        f"{delta_html}{caption_html}"
        "</div>",
    )


def metric_row(items: Iterable[dict], columns: int | None = None) -> None:
    """Lay out a responsive grid of :func:`metric_card` kwargs dicts."""
    items = list(items)
    if not items:
        return
    per_row = columns or min(len(items), 4)
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(per_row)
        for col, item in zip(cols, chunk):
            with col:
                metric_card(**item)


def badge(text: object, tone: str = "muted") -> str:
    """Return pill-badge markup (does not render by itself)."""
    return (
        f'<span class="ops-chip {_TONE_CLASSES.get(tone, "")}">'
        f"{escape_label(text)}</span>"
    )


def severity_badge(severity: object) -> str:
    """Badge colored by CRITICAL/HIGH/MEDIUM/LOW."""
    sev = str(severity or "").upper()
    tones = {
        "CRITICAL": "danger",
        "HIGH": "warning",
        "MEDIUM": "info",
        "LOW": "muted",
    }
    return badge(sev or "—", tones.get(sev, "muted"))


def chip(text: object, tone: str = "muted") -> str:
    """Alias of :func:`badge` for inline composition."""
    return badge(text, tone)


def chips_row(chips: Sequence[str]) -> None:
    """Render pre-composed badges in one flex row."""
    _md(
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>"
        + "".join(chips)
        + "</div>"
    )


# --- states -----------------------------------------------------------------------------------


def empty_state(icon: str, title: str, body: str,
                cta_label: str | None = None,
                cta_page: str | None = None) -> None:
    """Deliberate empty-state panel with an optional call to action."""
    _md(
        "<div class='ops-empty'>"
        f"<div class='ops-empty-icon'>{icon_html(icon, size=26)}</div>"
        f"<div class='ops-empty-title'>{escape_label(title)}</div>"
        f"<div class='ops-empty-body'>{escape_label(body)}</div>"
        "</div>"
    )
    if cta_label and cta_page:
        st.page_link(cta_page, label=cta_label, icon=":material/arrow_forward:")


def loading_panel(message: str, sub: str | None = None) -> None:
    """Indeterminate progress surface used while work is running."""
    sub_html = f"<div class='ops-metric-caption'>{escape_label(sub)}</div>" if sub else ""
    _md(
        "<div class='ops-card'>"
        f"<div class='ops-metric-label'>{icon_html('clock', size=14)}"
        f"<span>Working</span></div>"
        f"<div style='color:var(--ops-text);font-weight:600'>{escape_label(message)}</div>"
        "<div class='ops-loading-bar'><div></div></div>"
        f"{sub_html}"
        "</div>"
    )


def skeleton_lines(count: int = 3, *, title: bool = True) -> None:
    """Content-shaped shimmer placeholders for text that is loading."""
    blocks = ["<div class='ops-skeleton ops-skeleton-title'></div>"] if title else []
    blocks += [
        "<div class='ops-skeleton ops-skeleton-text'></div>" for _ in range(max(0, count))
    ]
    _md("".join(blocks))


def skeleton_cards(count: int = 3) -> None:
    """Row of shimmering card placeholders (KPI grids while computing)."""
    count = max(1, count)
    inner = (
        "<div class='ops-card'>"
        "<div class='ops-skeleton ops-skeleton-text' style='width:40%;margin-top:0'></div>"
        "<div class='ops-skeleton ops-skeleton-title' style='width:62%'></div>"
        "<div class='ops-skeleton ops-skeleton-text' style='width:78%'></div>"
        "</div>"
    )
    for col in st.columns(count):
        with col:
            _md(inner)


def strength_meter(value: float, maximum: float = 10.0) -> str:
    """Markup for a 0..maximum strength bar."""
    pct = max(0.0, min(100.0, 100.0 * float(value) / max(1e-9, maximum)))
    return (
        "<div style='display:flex;align-items:center;gap:8px'>"
        f"<div class='ops-meter' style='flex:1'><div style='width:{pct:.0f}%'></div></div>"
        f"<span class='ops-mono' style='color:var(--ops-text-2)'>{value:.1f}</span></div>"
    )


# --- workflow / audit visualization --------------------------------------------------------------


def status_dot(tone: str = "muted") -> str:
    """Small live-status dot markup (semantic tone, subtle glow)."""
    return f'<span class="ops-status-dot {_TONE_CLASSES.get(tone, "")}"></span>'


def timeline_item(*, when: object, badges: Sequence[str] = (),
                  body: object | None = None,
                  tone: str | None = None) -> str:
    """One audit-timeline entry; ``tone`` colors the connecting dot."""
    tone_cls = f" {_TONE_CLASSES.get(tone, '')}" if tone else ""
    badge_html = "".join(badges)
    body_html = (
        f"<div style='font-size:.85rem;margin-top:3px'>{escape_label(body)}</div>"
        if body
        else ""
    )
    return (
        "<div class='ops-timeline-item'>"
        f"<div class='ops-timeline-dot{tone_cls}'></div>"
        "<div>"
        "<div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center'>"
        f"<span class='ops-mono' style='color:var(--ops-text-3)'>"
        f"{escape_label(when)}</span>{badge_html}</div>"
        f"{body_html}</div></div>"
    )


def timeline(items: Sequence[str]) -> None:
    """Render pre-composed :func:`timeline_item` entries as one rail."""
    if not items:
        return
    _md(f"<div class='ops-timeline'>{''.join(items)}</div>")


_STEPPER_STATES = {
    "todo": "",
    "done": "ops-done",
    "active": "ops-active",
    "available": "ops-available",
    "blocked": "ops-blocked",
}


def stepper(steps: Sequence[tuple[object, str]]) -> None:
    """Horizontal progress stepper (label + todo/done/active/blocked)."""
    parts: list[str] = []
    for index, (label, state) in enumerate(steps):
        cls = _STEPPER_STATES.get(state, "")
        glyph = icon_html("check", size=11) if state == "done" else escape_label(index + 1)
        connector = "<span class='ops-stepper-connector'></span>" if index else ""
        parts.append(
            f"{connector}"
            f"<span class='ops-stepper-step {cls}'>"
            f"<span class='ops-stepper-glyph'>{glyph}</span>"
            f"{escape_label(label)}</span>"
        )
    _md(f"<div class='ops-stepper'>{''.join(parts)}</div>")


def kv_grid(pairs: Sequence[tuple[object, object]]) -> str:
    """Definition-list markup for label/value pairs."""
    rows = "".join(
        f"<dt>{escape_label(k)}</dt><dd>{escape_label(v)}</dd>" for k, v in pairs
    )
    return f"<dl class='ops-kv'>{rows}</dl>"


# --- sidebar -----------------------------------------------------------------------------------


def brand_header(app_name: str, tagline: str) -> None:
    """Sidebar brand block: gradient mark, wordmark, tagline."""
    mark = (
        "<div class='ops-brand-mark'>"
        + icon_html("sparkle", size=20)
        + "</div>"
    )
    _md(
        "<div class='ops-brand'>"
        f"{mark}"
        "<div>"
        f"<div class='ops-brand-name'>{escape_label(app_name)}</div>"
        f"<div class='ops-brand-tagline'>{escape_label(tagline)}</div>"
        "</div></div>"
    )


def dataset_chip() -> None:
    """Active-dataset summary card for the sidebar (never fabricates data)."""
    df = st.session_state.get("df")
    name = st.session_state.get("dataset_name")
    status = get_analysis_status()
    if df is not None and name:
        status_tone, status_text = {
            ANALYSIS_READY: ("success", "READY"),
            ANALYSIS_RUNNING: ("accent", "ANALYZING"),
            ANALYSIS_ERROR: ("danger", "ERROR"),
        }.get(status, ("warning", "NOT ANALYZED"))
        body = (
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"gap:8px'><span class='ops-mono' style='color:var(--ops-text);"
            f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
            f"{escape_label(name)}</span>{badge(status_text, status_tone)}</div>"
            f"<div class='ops-card-sub'>{len(df):,} rows &#183; {df.shape[1]} columns</div>"
        )
    elif status == "RECOVERY_AVAILABLE":
        body = (
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"gap:8px'><span style='color:var(--ops-text)'>Previous run found</span>"
            f"{badge('RECOVERABLE', 'ai')}</div>"
            "<div class='ops-card-sub'>Open Data to restore it.</div>"
        )
    else:
        body = (
            "<div style='display:flex;justify-content:space-between;align-items:center;"
            f"gap:8px'><span style='color:var(--ops-text-3)'>No dataset loaded</span>"
            f"{badge('EMPTY', 'muted')}</div><div class='ops-card-sub'>Start on the "
            "Data page.</div>"
        )
    _md(
        "<div class='ops-sidebar-card'>"
        f"<div class='ops-metric-label'>{icon_html('database', size=13)}"
        "<span>Active dataset</span></div>"
        f"{body}</div>"
    )


# Seven-stage product lifecycle (Phase 11B): the sidebar rail, the
# in-page stepper and every loading checklist share this one definition.
# States: done / active / available / todo / blocked — always derived
# from real session state, never fabricated progress.
_WORKFLOW_STEPS = (
    ("Observe", "Load and validate a dataset", "Observe"),
    ("Understand", "Deterministic analysis run", "Understand"),
    ("Detect", "Anomaly detectors executed", "Detect"),
    ("Investigate", "Evidence pack prepared", "Investigate"),
    ("Recommend", "Prioritized action plan", "Recommend"),
    ("Human decision", "Review + state machine", "Decide"),
    ("Audit", "Append-only event trail", "Audit"),
)


def _workflow_states() -> list[str]:
    """Derive per-step lifecycle states from real session state.

    Mapping (honest by construction — the pipeline is one atomic run,
    so Understand/Detect/Investigate complete together):

    * Observe      done once a dataset is loaded; otherwise todo.
    * Understand   active while ANALYZING, blocked on ERROR, done on
                   READY, available when data is loaded but unanalyzed.
    * Detect /
      Investigate  follow Understand exactly (same pipeline run).
    * Recommend    done when a plan exists, available once artifacts
                   exist without one.
    * Human dec.   done when any record left PENDING via the state
                   machine, available while PENDING records await.
    * Audit        done when a persisted plan produced decisions,
                   available once a persisted plan exists.
    """
    status = get_analysis_status()
    df_loaded = st.session_state.get("df") is not None
    plan = st.session_state.get("plan") or {}
    recs = plan.get("recommendations") or []
    reviewed = [r for r in recs if r.get("status") in {"APPROVED", "REJECTED",
                                                       "CHANGES_REQUESTED"}]
    pending = [r for r in recs if r.get("status") == "PENDING"]
    persisted = bool(st.session_state.get("plan_id"))

    steps = ["todo"] * len(_WORKFLOW_STEPS)
    if df_loaded:
        steps[0] = "done"

    if status == ANALYSIS_RUNNING:
        steps[1] = steps[2] = steps[3] = "active"
    elif status == ANALYSIS_ERROR:
        steps[1] = steps[2] = steps[3] = "blocked"
    elif status == ANALYSIS_READY:
        steps[1] = steps[2] = steps[3] = "done"
    elif df_loaded:
        steps[1] = steps[2] = steps[3] = "available"

    if recs:
        steps[4] = "done"
    elif steps[3] == "done":
        steps[4] = "available"

    if reviewed:
        steps[5] = "done"
    elif pending:
        steps[5] = "available"

    if persisted and reviewed:
        steps[6] = "done"
    elif persisted:
        steps[6] = "available"
    return steps


def workflow_rail() -> None:
    """Seven-stage lifecycle rail driven only by real session state."""
    parts = []
    for index, ((label, hint, _short), state) in enumerate(
            zip(_WORKFLOW_STEPS, _workflow_states())):
        cls = {"todo": "", "done": "ops-done", "active": "ops-active",
               "available": "ops-available",
               "blocked": "ops-blocked"}[state]
        glyph = {0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "7"}[index]
        hint_html = f"<div class='ops-rail-hint'>{escape_label(hint)}</div>"
        parts.append(
            f"<div class='ops-rail-step {cls}'>"
            f"<div class='ops-rail-dot'>{glyph}</div>"
            f"<div class='ops-rail-label'>{escape_label(label)}{hint_html}</div>"
            "</div>"
        )
    _md(
        "<div class='ops-sidebar-card'><div class='ops-metric-label'>"
        f"{icon_html('cpu', size=13)}<span>Lifecycle</span></div>"
        f"<div class='ops-rail'>{''.join(parts)}</div></div>"
    )


def workflow_stepper(compact_labels: bool = False) -> None:
    """Horizontal in-page version of the seven-stage lifecycle rail."""
    labels = (
        tuple(short for _, _, short in _WORKFLOW_STEPS)
        if compact_labels
        else tuple(name for name, _, _ in _WORKFLOW_STEPS)
    )
    stepper(list(zip(labels, _workflow_states())))


def stage_checklist(title: str, stages: list[tuple[str, str]],
                    sub: str | None = None) -> None:
    """Contextual loading checklist for one expensive operation.

    ``stages`` are ``(label, done|active|todo)`` pairs supplied by the
    caller from facts it actually knows; this component never invents
    progress of its own.
    """
    parts = []
    for label, state in stages:
        cls = {"done": "ops-done", "active": "ops-active"}.get(state, "")
        glyph = (
            icon_html("check", size=11) if state == "done"
            else "<span class='ops-stage-pulse'></span>" if state == "active"
            else ""
        )
        parts.append(
            f"<span class='ops-stepper-step {cls}'>"
            f"<span class='ops-stepper-glyph'>{glyph}</span>"
            f"{escape_label(label)}</span>"
        )
    sub_html = f"<div class='ops-card-sub'>{escape_label(sub)}</div>" if sub else ""
    _md(
        "<div class='ops-card'>"
        f"<div class='ops-metric-label'>{icon_html('clock', size=14)}"
        f"<span>{escape_label(title)}</span></div>"
        "<div class='ops-loading-bar'><div></div></div>"
        f"<div class='ops-stepper'>{''.join(parts)}</div>"
        f"{sub_html}"
        "</div>"
    )


def sidebar_footer(environment: str, gemini_configured: bool) -> None:
    """Environment + AI availability footer."""
    ai_tone = "ai" if gemini_configured else "muted"
    ai_text = "AI available" if gemini_configured else "AI off"
    dot = status_dot("ai") if gemini_configured else ""
    _md(
        "<div style='margin-top:.6rem;display:flex;flex-wrap:wrap;gap:6px'>"
        f"{chip(environment.upper(), 'muted')}"
        f"<span class='ops-chip {_TONE_CLASSES[ai_tone]}'>{dot}{ai_text}</span>"
        "</div>"
    )
