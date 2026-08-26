"""Deterministic recommendation & action engine for OpsPilot AI (Phase 5).

Turns the aggregate-only evidence pack (and optionally a Phase 4B
investigation result for provenance metadata) into a ranked, deduplicated
plan of proposed operational actions. Fully deterministic: identical
inputs always yield an identical plan; recommendation ids are assigned
``R1..Rn`` only after the final stable sort. No LLM, no ML, no
randomness, no wall-clock time, no network.

Policies
--------
* **Structured inputs only**: accepted inputs are a canonical DataFrame,
  a Phase 4A evidence pack, or a Phase 4B investigation result (whose
  embedded ``evidence_pack`` is used). Malformed containers raise
  ``DataValidationError``. Free-form narrative text is never parsed;
  investigation results contribute only their ``status`` and the set of
  structured ``evidence_ids`` they cite, and never influence scores.
* **Playbooks**: factor/profile labels map onto a closed action
  vocabulary (see ``agent.recommendation_playbooks``). Unknown future
  labels fall back to ``manual_investigation`` instead of failing.
* **Scoring**: additive, explainable points from severity base,
  primary factor strength, corroboration, and concentration (localization
  verdict or peer ratio). No trend term exists by approved design.
* **Deduplication**: candidates sharing ``(action_type, target_entity,
  target_metric)`` merge; source/evidence sets union; the highest-scoring
  member supplies presentation fields.
* **Immutability**: caller inputs are never mutated; every returned
  container is freshly built.
* **Human review**: every recommendation is emitted with
  ``requires_human_review=True`` and ``status=PENDING`` (the reserved
  constant from ``core.constants``). Nothing is ever executed.
"""

from __future__ import annotations

import copy
import math

import pandas as pd

from agent import recommendation_playbooks as playbooks
from agent.investigator import resolve_investigation_context
from agent.recommendation_playbooks import (
    CONCENTRATION_BONUS_POINTS,
    CORROBORATION_BONUS_WEIGHT,
    EVIDENCE_STRENGTH_CONCENTRATION_WEIGHT,
    EVIDENCE_STRENGTH_CORROBORATION_WEIGHT,
    EVIDENCE_STRENGTH_FACTOR_WEIGHT,
    EVIDENCE_STRENGTH_SCORE_WEIGHT,
    FACTOR_ACTION_MAP,
    FACTOR_STRENGTH_BONUS_WEIGHT,
    MAX_CANDIDATES_PER_INSIGHT,
    MAX_CORROBORATION_STEPS,
    PEER_CONCENTRATION_BONUS_POINTS,
    PEER_RATIO_CONCENTRATION_THRESHOLD,
    PRIORITY_BASE_POINTS,
    PROFILE_ACTION_MAP,
    UNKNOWN_FACTOR_FALLBACK_ACTION,
    action_phrase,
    metric_label,
)
from agent.schemas import (
    EXPECTED_PLAN_KEYS,
    EXPECTED_RESULT_KEYS,
    EXPECTED_SOURCE_KEYS,
    EXPECTED_SUMMARY_KEYS,
    INVESTIGATION_STATUSES,
    PRIORITY_CRITICAL_MIN_SCORE,
    PRIORITY_HIGH_MIN_SCORE,
    PRIORITY_MEDIUM_MIN_SCORE,
    RECOMMENDATION_KEYS,
    RECOMMENDATION_PLAN_TYPE,
    RECOMMENDATION_SCHEMA_VERSION,
)
from core.constants import RECOMMENDATION_PENDING
from core.exceptions import DataValidationError
from services.anomaly_service import SEVERITY_PRIORITY, VALID_SEVERITIES

# --- Small shared helpers -----------------------------------------------------


def _clamp01(value: float) -> float:
    """Clamp a numeric value into the closed interval [0, 1]."""
    return max(0.0, min(1.0, float(value)))


def _round2(value: float) -> float:
    """Round a presentation value to two decimal places."""
    return round(float(value), 2)


def _plain(value: object) -> object:
    """Recursively convert nested containers into JSON-safe plain types."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _evidence_sort_key(evidence_id: str) -> tuple[int, str]:
    """Numeric-aware ordering for ``E<id>`` strings."""
    suffix = evidence_id[1:] if evidence_id.startswith("E") else evidence_id
    try:
        return int(suffix), ""
    except ValueError:
        return 10**9, evidence_id


# --- Input resolution -----------------------------------------------------------


def _validate_max_recommendations(value: object) -> int | None:
    """Validate the optional cap; ``None`` means unlimited."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataValidationError(
            "max_recommendations must be an integer or None; got "
            f"{type(value).__name__}"
        )
    if value < 0:
        raise DataValidationError(
            f"max_recommendations must be >= 0; got {value}"
        )
    return int(value)


def _is_investigation_result(candidate: object) -> bool:
    """True when a mapping exposes exactly the Phase 4B result contract."""
    return isinstance(candidate, dict) and set(candidate) == set(EXPECTED_RESULT_KEYS)


def _extract_investigation_meta(result: dict) -> dict[str, object]:
    """Pull provenance metadata out of a validated investigation result.

    Only structured fields are consumed: ``status`` plus every
    ``evidence_ids``/``evidence_id`` string appearing in findings,
    hypotheses, and citations. Narrative prose is never parsed.
    """
    status = result.get("status")
    if not isinstance(status, str) or status not in INVESTIGATION_STATUSES:
        expected = ", ".join(sorted(INVESTIGATION_STATUSES))
        raise DataValidationError(
            f"investigation['status'] must be one of: {expected}; got {status!r}"
        )

    cited: set[str] = set()
    narrative = result.get("narrative")
    if isinstance(narrative, dict):
        sections = narrative.get("key_findings"), narrative.get("operational_interpretation")
    else:
        raise DataValidationError(
            f"investigation['narrative'] must be a dictionary; got {type(narrative).__name__}"
        )
    for section in sections:
        if not isinstance(section, list):
            raise DataValidationError(
                "investigation['narrative'] finding sections must be lists"
            )
        for item in section:
            if not isinstance(item, dict):
                raise DataValidationError("investigation finding entries must be dictionaries")
            ids = item.get("evidence_ids")
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                raise DataValidationError(
                    "investigation finding evidence_ids must be lists of strings"
                )
            cited.update(ids)

    hypotheses = result.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise DataValidationError(
            f"investigation['hypotheses'] must be a list; got {type(hypotheses).__name__}"
        )
    for item in hypotheses:
        if not isinstance(item, dict):
            raise DataValidationError("investigation hypothesis entries must be dictionaries")
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            raise DataValidationError(
                "investigation hypothesis evidence_ids must be lists of strings"
            )
        cited.update(ids)

    citations = result.get("citations")
    if not isinstance(citations, list):
        raise DataValidationError(
            f"investigation['citations'] must be a list; got {type(citations).__name__}"
        )
    for item in citations:
        if not isinstance(item, dict):
            raise DataValidationError("investigation citation entries must be dictionaries")
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str):
            raise DataValidationError("investigation citation evidence_id must be a string")
        cited.add(evidence_id)

    return {"status": status, "cited_evidence_ids": sorted(cited)}


def _resolve_plan_input(df_or_context: object) -> tuple[dict, dict | None]:
    """Normalize any supported input into ``(pack, investigation_meta)``."""
    if isinstance(df_or_context, pd.DataFrame):
        return resolve_investigation_context(df_or_context), None
    if isinstance(df_or_context, dict):
        if _is_investigation_result(df_or_context):
            meta = _extract_investigation_meta(df_or_context)
            pack = resolve_investigation_context(df_or_context.get("evidence_pack"))
            return pack, meta
        return resolve_investigation_context(df_or_context), None
    raise DataValidationError(
        "generate_recommendations accepts a canonical DataFrame, an "
        f"evidence pack dictionary, or an investigation result; got "
        f"{type(df_or_context).__name__}"
    )


def _resolve_investigation_parameter(investigation: object) -> dict | None:
    """Validate the optional explicit ``investigation`` argument."""
    if investigation is None:
        return None
    if not isinstance(investigation, dict) or set(investigation) != set(EXPECTED_RESULT_KEYS):
        missing = sorted(set(EXPECTED_RESULT_KEYS)) if not isinstance(investigation, dict) else None
        raise DataValidationError(
            "investigation must be an investigation result dictionary with "
            f"keys {sorted(EXPECTED_RESULT_KEYS)}; got "
            f"{type(investigation).__name__}"
        )
    return _extract_investigation_meta(investigation)


# --- Structural checks -------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataValidationError(message)


def _check_insight_structure(index: int, insight: object, anomaly: object) -> None:
    """Validate one aligned insight/anomaly pair before matching."""
    _require(isinstance(insight, dict), f"insight at position {index} is not a dictionary")
    _require(isinstance(anomaly, dict), f"anomaly at position {index} is not a dictionary")
    for field in ("scope", "metric", "severity", "factors"):
        _require(field in insight, f"insight at position {index} is missing '{field}'")
    severity = anomaly.get("severity", insight.get("severity"))
    _require(
        isinstance(severity, str) and severity in VALID_SEVERITIES,
        f"anomaly at position {index} has unsupported severity {severity!r}",
    )
    score = anomaly.get("score")
    _require(
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and math.isfinite(float(score)),
        f"anomaly at position {index} has invalid score {score!r}",
    )
    deviation = anomaly.get("deviation_pct")
    _require(
        isinstance(deviation, (int, float))
        and not isinstance(deviation, bool)
        and math.isfinite(float(deviation)),
        f"anomaly at position {index} has invalid deviation_pct {deviation!r}",
    )
    factors = insight["factors"]
    _require(isinstance(factors, list), f"insight at position {index} has non-list factors")
    if str(insight["scope"]) == "daily":
        _require(len(factors) > 0, f"daily insight at position {index} has empty factors")
    for position, entry in enumerate(factors):
        _require(isinstance(entry, dict), f"factor {position} of insight {index} is not a dictionary")
        label = entry.get("factor")
        _require(
            isinstance(label, str) and label != "",
            f"factor {position} of insight {index} has invalid 'factor' label {label!r}",
        )
        strength = entry.get("strength")
        _require(
            isinstance(strength, (int, float))
            and not isinstance(strength, bool)
            and math.isfinite(float(strength)),
            f"factor {position} of insight {index} has non-finite strength",
        )


# --- Playbook matching ---------------------------------------------------------------


def match_playbook_candidates(insight: dict, anomaly: dict) -> list[dict]:
    """Match deterministic playbooks for one aligned insight/anomaly pair.

    Args:
        insight: One record from ``pack['insights']``.
        anomaly: The paired record from ``pack['anomalies']``.

    Returns:
        Between one and :data:`MAX_CANDIDATES_PER_INSIGHT` raw candidate
        dictionaries carrying scoring inputs. Pure function: inputs are
        only read.
    """
    scope = str(insight.get("scope"))
    metric = str(insight.get("metric"))
    severity = str(anomaly.get("severity", insight.get("severity")))
    detector_score = _round2(min(100.0, max(0.0, float(anomaly.get("score", 0.0)))))
    deviation_pct = float(anomaly.get("deviation_pct", 0.0))
    entity = insight.get("entity")
    iso_date = anomaly.get("date")
    date_window = {"start": str(iso_date), "end": str(iso_date)} if iso_date else None
    related = insight.get("related_anomaly_indices")
    related_ids = {int(j) for j in related} if isinstance(related, list) else set()

    def base_candidate() -> dict:
        return {
            "scope": scope,
            "target_metric": metric,
            "target_entity": None,
            "date_window": copy.deepcopy(date_window),
            "severity": severity,
            "detector_score": detector_score,
            "deviation_pct": deviation_pct,
            "concentration_flag": False,
            "corroboration_count": len(related_ids | {int(anomaly.get("_index", -1))})
            if "_index" in anomaly
            else len(related_ids) + 1,
            "localization_note": None,
            "profile_note": None,
            "anomaly_value": anomaly.get("value"),
            "anomaly_expected_value": anomaly.get("expected_value"),
            "anomaly_date": iso_date,
        }

    candidates: list[dict] = []

    if scope in ("region", "product"):
        profile_block = insight.get("peer_profile")
        if isinstance(profile_block, dict) and profile_block.get("profile"):
            profile = str(profile_block["profile"])
            action = PROFILE_ACTION_MAP.get(profile, UNKNOWN_FACTOR_FALLBACK_ACTION)
            candidate = base_candidate()
            candidate.update(
                {
                    "action_type": action,
                    "origin": "profile",
                    "source_factors": [profile],
                    "primary_factor_strength": 0.0,
                    "target_entity": str(entity) if entity is not None else None,
                }
            )
            ratios = profile_block.get("ratios")
            ratio_value = None
            if isinstance(ratios, dict):
                raw_ratio = ratios.get("metric_vs_peer_median")
                if isinstance(raw_ratio, (int, float)) and not isinstance(raw_ratio, bool):
                    ratio_value = float(raw_ratio)
            if ratio_value is not None and ratio_value >= PEER_RATIO_CONCENTRATION_THRESHOLD:
                candidate["concentration_flag"] = True
                candidate["profile_note"] = (
                    f"peer ratio {ratio_value:.2f}x meets or exceeds the "
                    f"{PEER_RATIO_CONCENTRATION_THRESHOLD:.1f}x concentration threshold"
                )
            candidates.append(candidate)
        else:
            candidate = base_candidate()
            candidate.update(
                {
                    "action_type": UNKNOWN_FACTOR_FALLBACK_ACTION,
                    "origin": "fallback",
                    "source_factors": [],
                    "primary_factor_strength": 0.0,
                    "target_entity": str(entity) if entity is not None else None,
                    "profile_note": "peer comparison unavailable for this outlier",
                }
            )
            candidates.append(candidate)
        return candidates[:MAX_CANDIDATES_PER_INSIGHT]

    factors = insight.get("factors")
    primary = factors[0]
    label = str(primary["factor"])
    action = FACTOR_ACTION_MAP.get(label, UNKNOWN_FACTOR_FALLBACK_ACTION)
    candidate = base_candidate()
    candidate.update(
        {
            "action_type": action,
            "origin": "factor",
            "source_factors": [label],
            "primary_factor_strength": _clamp01(primary.get("strength", 0.0)),
        }
    )

    localization = insight.get("localization")
    if isinstance(localization, dict):
        verdict = localization.get("verdict")
        contributors = localization.get("contributors")
        if isinstance(verdict, str) and verdict in CONCENTRATION_BONUS_POINTS:
            candidate["concentration_flag"] = True
        if (
            isinstance(verdict, str)
            and verdict in ("localized", "concentrated")
            and isinstance(contributors, list)
            and contributors
            and isinstance(contributors[0], dict)
        ):
            lead = contributors[0]
            dimension = str(localization.get("dimension", scope))
            candidate["target_entity"] = str(lead.get("entity"))
            candidate["scope"] = dimension
            share = lead.get("share_pct")
            share_text = (
                f"{float(share):.2f}% share" if isinstance(share, (int, float)) else "leading share"
            )
            candidate["localization_note"] = (
                f"{verdict} in {dimension} {lead.get('entity')} ({share_text})"
            )
    if candidate.get("target_entity") is None:
        # Untargeted daily signals describe the whole dataset.
        candidate["scope"] = "dataset"
    candidates.append(candidate)
    return candidates[:MAX_CANDIDATES_PER_INSIGHT]


# --- Scoring ---------------------------------------------------------------------------


def compute_priority(candidate: dict) -> tuple[str, float]:
    """Compute ``(priority_label, priority_score)`` for one candidate.

    Additive explainable model::

        base(severity) + 25 * top_factor_strength
        + 15 * min(corroboration_count - 1, 3) / 3
        + concentration bonus (localized 10 / concentrated 6 /
          peer-ratio 10 / otherwise 0)

    capped at 100 and banded with the same edges as anomaly severity.
    Pure function; the candidate is only read.
    """
    severity = str(candidate.get("severity"))
    base = PRIORITY_BASE_POINTS.get(severity, PRIORITY_BASE_POINTS["LOW"])
    strength_bonus = round(
        FACTOR_STRENGTH_BONUS_WEIGHT * _clamp01(candidate.get("primary_factor_strength", 0.0)), 2
    )
    steps = max(0, int(candidate.get("corroboration_count", 1)) - 1)
    corroboration_bonus = round(
        CORROBORATION_BONUS_WEIGHT * min(steps, MAX_CORROBORATION_STEPS) / MAX_CORROBORATION_STEPS, 2
    )
    concentration_bonus = 0.0
    if candidate.get("concentration_flag"):
        verdict = str(candidate.get("localization_verdict", ""))
        # Factor candidates carry a localization verdict; profile candidates
        # (entity outliers) default to the peer-ratio bonus.
        concentration_bonus = CONCENTRATION_BONUS_POINTS.get(
            verdict, PEER_CONCENTRATION_BONUS_POINTS
        )
    score = min(100.0, round(base + strength_bonus + corroboration_bonus + concentration_bonus, 2))
    if score >= PRIORITY_CRITICAL_MIN_SCORE:
        return "CRITICAL", score
    if score >= PRIORITY_HIGH_MIN_SCORE:
        return "HIGH", score
    if score >= PRIORITY_MEDIUM_MIN_SCORE:
        return "MEDIUM", score
    return "LOW", score


def compute_evidence_strength(candidate: dict) -> float:
    """Compute the deterministic support level in ``[0.0, 1.0]``.

    Blend (weights sum to 1)::

        0.50 * primary_factor_strength
        + 0.25 * detector_score / 100
        + 0.15 * min(corroboration_count - 1, 3) / 3
        + 0.10 * concentration flag

    This measures how strongly the evidence supports the proposal; it is
    never a probability of operational impact and never inherits an LLM
    confidence value.
    """
    steps = max(0, int(candidate.get("corroboration_count", 1)) - 1)
    corroboration_fraction = min(steps, MAX_CORROBORATION_STEPS) / MAX_CORROBORATION_STEPS
    detector_fraction = _clamp01(float(candidate.get("detector_score", 0.0)) / 100.0)
    strength = (
        EVIDENCE_STRENGTH_FACTOR_WEIGHT * _clamp01(candidate.get("primary_factor_strength", 0.0))
        + EVIDENCE_STRENGTH_SCORE_WEIGHT * detector_fraction
        + EVIDENCE_STRENGTH_CORROBORATION_WEIGHT * corroboration_fraction
        + EVIDENCE_STRENGTH_CONCENTRATION_WEIGHT * (1.0 if candidate.get("concentration_flag") else 0.0)
    )
    return _round2(_clamp01(strength))


# --- Deduplication ------------------------------------------------------------------------


def _dedup_key(candidate: dict) -> tuple[str, str | None, str]:
    return (
        str(candidate["action_type"]),
        candidate.get("target_entity"),
        str(candidate["target_metric"]),
    )


def _merge_date_windows(members: list[dict]) -> dict | None:
    starts = [
        str(member["date_window"]["start"])
        for member in members
        if isinstance(member.get("date_window"), dict)
    ]
    ends = [
        str(member["date_window"]["end"])
        for member in members
        if isinstance(member.get("date_window"), dict)
    ]
    if not starts or not ends:
        return None
    return {"start": min(starts), "end": max(ends)}


def deduplicate_recommendations(candidates: list[dict]) -> list[dict]:
    """Merge candidates sharing ``(action_type, target_entity, metric)``.

    Union semantics: ``source_factors``, ``source_anomaly_indices``, and
    ``evidence_ids`` merge into sorted unique lists; the date window spans
    all dated members; the highest-scoring member (first on ties, in input
    order) supplies severity, strengths, notes, and later presentation
    fields. Input order and contents are never mutated.
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for candidate in candidates:
        key = _dedup_key(candidate)
        if key not in merged:
            merged[key] = {
                "members": [candidate],
                "priority_score": float(candidate["priority_score"]),
            }
            order.append(key)
            continue
        merged[key]["members"].append(candidate)

    results: list[dict] = []
    for key in order:
        bundle = merged[key]
        members = bundle["members"]
        # max() keeps the first maximal element, so ties preserve input order.
        leader = max(members, key=lambda m: float(m["priority_score"]))

        factor_set: set[str] = set()
        anomaly_indices: set[int] = set()
        group_ids: set[int] = set()
        evidence_ids: set[str] = set()
        corroboration = 1
        for member in members:
            factor_set.update(str(f) for f in member.get("source_factors", []))
            anomaly_indices.update(int(i) for i in member.get("source_anomaly_indices", []))
            group_ids.update(int(g) for g in member.get("source_group_ids", []))
            evidence_ids.update(str(e) for e in member.get("evidence_ids", []))
            corroboration = max(corroboration, int(member.get("corroboration_count", 1)))
        # Cross-member corroboration: distinct merged anomalies count too.
        corroboration = max(corroboration, len(anomaly_indices))

        combined = dict(leader)
        combined.update(
            {
                "source_factors": sorted(factor_set),
                "source_anomaly_indices": sorted(anomaly_indices),
                "source_group_ids": sorted(group_ids),
                "evidence_ids": sorted(evidence_ids, key=_evidence_sort_key),
                "date_window": _merge_date_windows(members),
                "corroboration_count": corroboration,
                "priority_score": bundle["priority_score"],
            }
        )
        results.append(combined)
    return results


# --- Presentation ------------------------------------------------------------------------------


def _render_title(candidate: dict) -> str:
    phrase = action_phrase(str(candidate["action_type"]))
    label = metric_label(candidate.get("target_metric"))
    target = candidate.get("target_entity")
    if target:
        return f"{phrase.capitalize()} for {target} ({label})"
    return f"{phrase.capitalize()} for {label}"


def _render_window_text(date_window: dict | None) -> str:
    if not isinstance(date_window, dict):
        return "across the full period"
    start = str(date_window.get("start"))
    end = str(date_window.get("end"))
    if start == end:
        return f"observed on {start}"
    return f"observed between {start} and {end}"


def _render_description(candidate: dict) -> str:
    parts: list[str] = []
    label = metric_label(candidate.get("target_metric"))
    parts.append(
        f"{candidate.get('severity')} {candidate.get('scope')} {label} signal "
        f"{_render_window_text(candidate.get('date_window'))} "
        f"deviating {float(candidate.get('deviation_pct', 0.0)):+.2f}% versus expected"
    )
    origin = candidate.get("origin")
    if origin == "factor":
        parts.append(
            f"primary factor '{candidate.get('source_factors', [''])[0]}' "
            f"(strength {float(candidate.get('primary_factor_strength', 0.0)):.2f})"
        )
    elif origin == "profile" and candidate.get("source_factors"):
        parts.append(f"peer profile '{candidate['source_factors'][0]}'")
    if candidate.get("localization_note"):
        parts.append(str(candidate["localization_note"]))
    if candidate.get("profile_note"):
        parts.append(str(candidate["profile_note"]))
    count = int(candidate.get("corroboration_count", 1))
    if count > 1:
        parts.append(f"corroborated by {count} related anomaly record(s)")
    parts.append("proposed for human review; no automated action is taken")
    return "; ".join(parts) + "."


def _render_problem_statement(candidate: dict) -> str:
    """Generate a concise, data-grounded problem statement from the candidate."""
    label = metric_label(candidate.get("target_metric"))
    entity = candidate.get("target_entity")
    severity = str(candidate.get("severity", "LOW"))
    deviation = float(candidate.get("deviation_pct", 0.0))
    scope = str(candidate.get("scope", "dataset"))
    date_window = candidate.get("date_window")
    window_text = _render_window_text(date_window)

    value = candidate.get("anomaly_value")
    expected = candidate.get("anomaly_expected_value")
    has_values = (
        isinstance(value, (int, float))
        and isinstance(expected, (int, float))
        and not isinstance(value, bool)
        and not isinstance(expected, bool)
    )

    if entity:
        location = f"{entity} ({scope} level)"
    elif scope == "dataset":
        location = "the full dataset"
    else:
        location = f"{scope} level"

    direction = "increased" if deviation > 0 else "decreased"
    magnitude = f"{abs(deviation):.1f}%"

    if has_values:
        return (
            f"A {severity.lower()}-severity {label.lower()} signal was detected in "
            f"{location} {window_text}, where the metric {direction} by {magnitude} "
            f"(observed {float(value):.2f}, expected {float(expected):.2f}) "
            f"versus the expected baseline."
        )
    return (
        f"A {severity.lower()}-severity {label.lower()} signal was detected in "
        f"{location} {window_text}, where the metric {direction} by {magnitude} "
        f"versus the expected baseline."
    )


def _render_why_it_matters(candidate: dict) -> str:
    """Explain why this recommendation matters in concrete business terms."""
    label = metric_label(candidate.get("target_metric"))
    severity = str(candidate.get("severity", "LOW"))
    deviation = float(candidate.get("deviation_pct", 0.0))
    entity = candidate.get("target_entity")
    deviation_mag = abs(deviation)

    higher_is_adverse = candidate.get("target_metric") in ("cost", "lead_time_days")
    is_adverse = (deviation > 0 and higher_is_adverse) or (deviation < 0 and not higher_is_adverse)

    if entity:
        subject = f"{entity}'s {label.lower()}"
    else:
        subject = f"The {label.lower()} signal"

    if is_adverse:
        impact = (
            f"{subject} deviated {deviation_mag:.1f}% from the expected baseline, "
            f"which could indicate deteriorating performance"
        )
    else:
        impact = (
            f"{subject} moved {deviation_mag:.1f}% from the expected baseline, "
            f"which represents a positive movement"
        )

    urgency = {
        "CRITICAL": "This requires immediate attention as the deviation is significant and may signal a systemic issue.",
        "HIGH": "This warrants prompt investigation before the trend worsens.",
        "MEDIUM": "This should be reviewed within the current operational cycle.",
        "LOW": "This is worth monitoring but does not require immediate action.",
    }.get(severity, "This should be reviewed when convenient.")

    return f"{impact}. {urgency}"


_FACTOR_DRIVER_MAP: dict[str, str] = {
    "volume": "the data suggests elevated or unusual demand volume may be contributing",
    "monetary": "the data suggests the shift is primarily driven by revenue or pricing changes",
    "cost": "the data suggests unusual cost fluctuations may be a contributing factor",
    "supply": "the data suggests supply-side constraints or longer lead times may be a contributing factor",
    "price_margin": "the data suggests pricing pressure or margin compression may be involved",
    "unattributed": "the data does not yet isolate a single primary factor",
}


def _render_likely_drivers(candidate: dict) -> list[str]:
    """Extract likely drivers with cautious language grounded in the data."""
    drivers: list[str] = []
    source_factors = candidate.get("source_factors", [])

    for factor in source_factors:
        factor_str = str(factor)
        mapped = _FACTOR_DRIVER_MAP.get(factor_str)
        if mapped:
            drivers.append(mapped)
        elif factor_str:
            drivers.append(f"the data suggests '{factor_str.replace('_', ' ')}' may be a contributing factor")

    localization_note = candidate.get("localization_note")
    if localization_note:
        drivers.append(
            f"a likely contributing factor is the localization pattern: {localization_note}"
        )

    profile_note = candidate.get("profile_note")
    if profile_note:
        drivers.append(
            f"a likely contributing factor is the peer comparison: {profile_note}"
        )

    if not drivers:
        drivers.append("further investigation is needed to identify contributing factors")

    return drivers


_ACTION_BENEFIT_MAP: dict[str, str] = {
    "demand_capacity_review": "Aligning {label} planning with actual demand patterns could prevent future shortfalls or overcapacity for {target}.",
    "revenue_operations_review": "Reviewing revenue operations for {label} could identify opportunities to recover or stabilize {target} revenue.",
    "cost_variance_review": "Investigating cost drivers for {label} may reveal reducible expenses or process inefficiencies affecting {target}.",
    "supplier_escalation_review": "Engaging with suppliers on {label} could resolve upstream bottlenecks affecting {target} delivery.",
    "fulfillment_bottleneck_review": "Addressing the fulfillment bottleneck in {label} could improve {target} delivery times and customer satisfaction.",
    "pricing_margin_review": "Reviewing pricing strategy for {label} may help restore or protect {target} margins.",
    "entity_performance_review": "Targeted performance review for {target_entity} on {label} could isolate and address root causes.",
    "manual_investigation": "Investigating the {label} signal further will help determine whether corrective action is needed for {target}.",
}


def _render_expected_benefit(candidate: dict) -> str:
    """Describe a concrete expected benefit of addressing this recommendation."""
    label = metric_label(candidate.get("target_metric"))
    entity = candidate.get("target_entity")
    action = str(candidate.get("action_type", "manual_investigation"))

    target_text = entity if entity else "the affected scope"
    template = _ACTION_BENEFIT_MAP.get(
        action, "Addressing this {label} signal could help stabilize {target} operations."
    )
    return template.format(
        label=label, target=target_text, target_entity=entity or "the affected entity"
    )


def _finalize_recommendation(
    candidate: dict, recommendation_id: str
) -> dict[str, object]:
    """Project an internal candidate onto the exact public record."""
    priority, score = compute_priority(candidate)
    record: dict[str, object] = {
        "recommendation_id": recommendation_id,
        "priority": priority,
        "priority_score": score,
        "action_type": str(candidate["action_type"]),
        "title": _render_title(candidate),
        "description": _render_description(candidate),
        "problem_statement": _render_problem_statement(candidate),
        "why_it_matters": _render_why_it_matters(candidate),
        "likely_drivers": _render_likely_drivers(candidate),
        "expected_benefit": _render_expected_benefit(candidate),
        "scope": str(candidate["scope"]),
        "target_entity": candidate.get("target_entity"),
        "target_metric": str(candidate["target_metric"]),
        "date_window": _plain(copy.deepcopy(candidate.get("date_window"))),
        "source_factors": [str(f) for f in candidate.get("source_factors", [])],
        "source_anomaly_indices": [int(i) for i in candidate.get("source_anomaly_indices", [])],
        "source_group_ids": [int(g) for g in candidate.get("source_group_ids", [])],
        "evidence_ids": [str(e) for e in candidate.get("evidence_ids", [])],
        "evidence_strength": compute_evidence_strength(candidate),
        "requires_human_review": True,
        "status": RECOMMENDATION_PENDING,
    }
    assert set(record) == set(RECOMMENDATION_KEYS)
    return record


def _recommendation_sort_key(record: dict) -> tuple:
    severity_rank = SEVERITY_PRIORITY.get(str(record["priority"]), len(SEVERITY_PRIORITY))
    window = record.get("date_window")
    start = str(window.get("start")) if isinstance(window, dict) else ""
    first_index = int(record["source_anomaly_indices"][0]) if record["source_anomaly_indices"] else 10**9
    return (
        -float(record["priority_score"]),
        severity_rank,
        str(record["action_type"]),
        str(record.get("target_entity") or ""),
        str(record["target_metric"]),
        start,
        first_index,
    )


# --- Evidence/group lookups ------------------------------------------------------------------------


def _build_evidence_lookups(pack: dict) -> tuple[dict[int, str], dict[int, str]]:
    """Map ``anomaly_index``/``group_id`` onto their citable evidence ids."""
    anomaly_map: dict[int, str] = {}
    group_map: dict[int, str] = {}
    for evidence_id, entry in pack["evidence_index"].items():
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "anomaly" and "anomaly_index" in entry:
            anomaly_map[int(entry["anomaly_index"])] = str(evidence_id)  # type: ignore[arg-type]
        elif kind == "group" and "group_id" in entry:
            group_map[int(entry["group_id"])] = str(evidence_id)  # type: ignore[arg-type]
    return anomaly_map, group_map


def _owning_group_ids(groups: list[dict], anomaly_index: int) -> list[int]:
    return [
        int(group["group_id"])
        for group in groups
        if int(group["group_id"]) >= 0
        and anomaly_index in [int(m) for m in group.get("member_indices", [])]
    ]


# --- Public orchestrator ------------------------------------------------------------------------------


def generate_recommendations(
    df_or_context: object,
    *,
    investigation: object | None = None,
    max_recommendations: int | None = None,
) -> dict[str, object]:
    """Build the deterministic recommendation plan for one investigation.

    Args:
        df_or_context: A canonical operational DataFrame, a Phase 4A
            evidence-pack dictionary, or a Phase 4B investigation result
            whose embedded ``evidence_pack`` is used. Inputs are never
            mutated.
        investigation: Optional Phase 4B investigation result supplying
            provenance metadata only. Required to be ``None`` when the
            primary input already is an investigation result.
        max_recommendations: Optional cap applied after final ranking;
            ``None`` keeps every recommendation. Non-positive-negative
            or non-integer values raise ``DataValidationError``.

    Returns:
        Plan dictionary with exactly the keys in
        ``agent.schemas.EXPECTED_PLAN_KEYS``. Identical inputs produce
        an identical plan.

    Raises:
        DataValidationError: On unsupported input types, malformed
            packs/results, structurally broken insights, invalid
            severities, or non-finite numerics.
    """
    limit = _validate_max_recommendations(max_recommendations)

    pack, primary_meta = _resolve_plan_input(df_or_context)
    if primary_meta is not None and investigation is not None:
        raise DataValidationError(
            "pass the investigation result either as the primary input or "
            "via investigation=, not both"
        )
    meta = primary_meta if primary_meta is not None else _resolve_investigation_parameter(investigation)

    anomalies = pack["anomalies"]
    insights = pack["insights"]
    _require(
        isinstance(anomalies, list) and isinstance(insights, list),
        "evidence pack 'anomalies' and 'insights' must be lists",
    )
    _require(
        len(anomalies) == len(insights),
        f"evidence pack alignment broken: {len(anomalies)} anomalies vs "
        f"{len(insights)} insights",
    )
    groups = pack["groups"].get("groups", [])
    _require(isinstance(groups, list), "evidence pack 'groups' must be a list")

    anomaly_evidence, group_evidence = _build_evidence_lookups(pack)

    scored_candidates: list[dict] = []
    for index, insight in enumerate(insights):
        anomaly = anomalies[index]
        _check_insight_structure(index, insight, anomaly)
        if index not in anomaly_evidence:
            raise DataValidationError(
                f"no anomaly evidence entry exists for anomaly_index {index}"
            )
        working_anomaly = dict(anomaly)
        working_anomaly["_index"] = index
        for candidate in match_playbook_candidates(insight, working_anomaly):
            candidate["anomaly_index"] = index
            candidate["source_anomaly_indices"] = [index]
            owning = _owning_group_ids(groups, index)
            candidate["source_group_ids"] = owning
            evidence = {anomaly_evidence[index]}
            for group_id in owning:
                if group_id in group_evidence:
                    evidence.add(group_evidence[group_id])
            candidate["evidence_ids"] = sorted(evidence, key=_evidence_sort_key)
            if candidate.get("origin") == "factor":
                candidate["localization_verdict"] = str(
                    (insight.get("localization") or {}).get("verdict", "")
                )
            priority_label, priority_score = compute_priority(candidate)
            candidate["priority"] = priority_label
            candidate["priority_score"] = priority_score
            scored_candidates.append(candidate)

    merged = deduplicate_recommendations(scored_candidates)
    finalized = [_finalize_recommendation(candidate, f"R{i}") for i, candidate in enumerate(merged, start=1)]
    finalized.sort(key=_recommendation_sort_key)
    # Reassign ids AFTER sorting so R1..Rn follow the published order.
    for position, record in enumerate(finalized, start=1):
        record["recommendation_id"] = f"R{position}"
    if limit is not None:
        finalized = finalized[:limit]

    cited_raw = sorted({str(i) for i in (meta or {}).get("cited_evidence_ids", [])})
    known_ids = {str(k) for k in pack["evidence_index"]}
    cited_filtered = sorted(
        (i for i in cited_raw if i in known_ids), key=_evidence_sort_key
    )

    by_priority = {label: 0 for label in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    by_action: dict[str, int] = {}
    for record in finalized:
        by_priority[str(record["priority"])] += 1
        action = str(record["action_type"])
        by_action[action] = by_action.get(action, 0) + 1

    plan: dict[str, object] = {
        "type": RECOMMENDATION_PLAN_TYPE,
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "parameters": _plain(copy.deepcopy(pack["parameters"])),
        "source": {
            "anomaly_count": len(anomalies),
            "group_count": len(groups),
            "investigation_status": (meta or {}).get("status"),
            "cited_evidence_ids": cited_filtered,
        },
        "recommendations": [_plain(record) for record in finalized],
        "summary": {
            "total_count": len(finalized),
            "by_priority": by_priority,
            "by_action_type": dict(sorted(by_action.items())),
        },
    }
    assert set(plan) == set(EXPECTED_PLAN_KEYS)
    assert set(plan["source"]) == set(EXPECTED_SOURCE_KEYS)  # type: ignore[arg-type]
    assert set(plan["summary"]) == set(EXPECTED_SUMMARY_KEYS)  # type: ignore[arg-type]
    return plan
