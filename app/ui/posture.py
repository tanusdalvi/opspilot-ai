"""Signal Posture — the Overview command-center score (Phase 11B).

OpsPilot has no business "health score" service, so none is invented
here. Instead this module defines ONE explicit presentation
transformation over deterministic detector output:

    posture = 100 - min(100, sum(severity_weight * count))

The weights are fixed presentation constants (not tuned to any
dataset); they only translate existing severity counts into a 0-100
attention scale. Every input comes from ``artifacts.anomaly_summary``
— with no artifacts there is no score at all.
"""

from __future__ import annotations

from app.ui.icons import escape_label, icon_html
from app.ui.theme import severity_color

# Fixed presentation weights per anomaly severity. They encode how much
# one detected signal of each class should pull the attention scale down;
# they are never derived from, or tuned against, the data itself.
SEVERITY_WEIGHTS: dict[str, int] = {
    "CRITICAL": 25,
    "HIGH": 12,
    "MEDIUM": 5,
    "LOW": 2,
}

_BANDS: tuple[tuple[int, str, str], ...] = (
    # minimum score -> (label, tone)
    (80, "STEADY", "success"),
    (60, "MODERATE ATTENTION", "warning"),
    (0, "NEEDS ATTENTION", "danger"),
)

_TONE_HEX = {
    "success": "var(--ops-success)",
    "warning": "var(--ops-warning)",
    "danger": "var(--ops-danger)",
    "accent": "var(--ops-accent)",
}


def posture_score(by_severity: dict) -> int:
    """Deterministic 0-100 attention scale from severity counts."""
    penalty = sum(
        SEVERITY_WEIGHTS.get(str(severity).upper(), 2) * int(count or 0)
        for severity, count in (by_severity or {}).items()
    )
    return max(0, 100 - min(100, penalty))


def posture_band(score: int) -> tuple[str, str]:
    """Map a posture score to its ``(label, tone)`` band."""
    for minimum, label, tone in _BANDS:
        if score >= minimum:
            return label, tone
    return _BANDS[-1][1], _BANDS[-1][2]


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
