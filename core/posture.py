"""Signal Posture — pure presentation logic (no Streamlit dependency).

Extracted from ``app.ui.posture`` so that the backend API serializers
can compute posture scores without pulling in Streamlit imports.

    posture = 100 - min(100, sum(severity_weight * count))

The weights are fixed presentation constants (not tuned to any
dataset); they only translate existing severity counts into a 0-100
attention scale.
"""

from __future__ import annotations

# Fixed presentation weights per anomaly severity.
SEVERITY_WEIGHTS: dict[str, int] = {
    "CRITICAL": 25,
    "HIGH": 12,
    "MEDIUM": 5,
    "LOW": 2,
}

_BANDS: tuple[tuple[int, str, str], ...] = (
    (80, "STEADY", "success"),
    (60, "MODERATE ATTENTION", "warning"),
    (0, "NEEDS ATTENTION", "danger"),
)


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
