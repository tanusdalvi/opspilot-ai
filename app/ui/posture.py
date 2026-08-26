"""Signal Posture — Streamlit-rendered donut ring (Phase 11B).

The pure scoring logic lives in ``core.posture``. This module adds
Streamlit-specific HTML rendering helpers (donut ring, icon markup).
"""

from __future__ import annotations

from app.ui.icons import escape_label, icon_html
from app.ui.theme import severity_color

# Re-export pure logic so existing Streamlit page imports keep working.
from core.posture import SEVERITY_WEIGHTS, posture_band, posture_score  # noqa: F401

_TONE_HEX = {
    "success": "var(--ops-success)",
    "warning": "var(--ops-warning)",
    "danger": "var(--ops-danger)",
    "accent": "var(--ops-accent)",
}


def posture_ring(score: int, label: str, tone: str) -> str:
    """Donut-ring markup for the score (conic gradient, semantic color)."""
    color = _TONE_HEX.get(tone, "var(--ops-accent)")
    pct = max(0, min(100, int(score)))
    return (
        "<div class='ops-posture'>"
        "<div class='ops-posture-ring' style='"
        f"background:conic-gradient({color} {pct * 3.6:.1f}deg,"
        "rgba(148,163,184,.14) 0deg)'>"
        "<div class='ops-posture-hole'>"
        f"<span class='ops-posture-score'>{escape_label(pct)}</span>"
        f"<span class='ops-posture-caption'>{icon_html('activity', size=11)}"
        "<span>POSTURE</span></span>"
        "</div></div>"
        "<div class='ops-posture-side'>"
        f"<div class='ops-metric-label'>{icon_html('shield-check', size=14)}"
        "<span>SIGNAL POSTURE</span></div>"
        f"<div class='ops-posture-band' style='color:{color}'>"
        f"{escape_label(label)}</div>"
        "<div class='ops-card-sub'>Presentation scale over detected "
        "anomaly severities — not a business KPI.</div>"
        "</div></div>"
    )


def severity_color_for(severity: object) -> str:
    """Public alias so pages keep one import path for stripe colors."""
    return severity_color(severity)
