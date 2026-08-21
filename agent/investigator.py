"""Phase 4B: evidence-grounded agentic investigation engine.

``investigate`` turns a canonical DataFrame (or an existing Phase 4A
evidence pack) into a narrated investigation using Gemini while keeping
the deterministic Python services as the only source of operational
truth:

    DataFrame/context -> evidence pack -> prompt -> Gemini -> JSON
        -> grounding validation -> complete | retry -> narrative_rejected

Gemini may narrate and hypothesize, but every factual claim must cite an
existing evidence id, every number must come verbatim from the evidence
pack, causal language is rejected, and malformed responses are rejected.
Nothing raw (no DataFrames, no rows, no CSV text) ever reaches Gemini,
and dataset strings embedded in the evidence pack are treated as
untrusted data by the prompt layer.

Determinism applies to the evidence pack, schemas, validation reports,
retry decisions, and evidence ids — never to natural-language Gemini
output.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from agent.gemini_client import GeminiNarratorClient
from agent.prompts import build_investigation_prompt, build_retry_prompt
from agent.schemas import (
    CONTEXT_SCHEMA_VERSION,
    EXPECTED_CITATION_KEYS,
    EXPECTED_CONTEXT_KEYS,
    EXPECTED_FINDING_KEYS,
    EXPECTED_GROUNDING_REPORT_KEYS,
    EXPECTED_HYPOTHESIS_KEYS,
    EXPECTED_NARRATIVE_KEYS,
    EXPECTED_RESULT_KEYS,
    FALLBACK_NARRATIVE,
    INVESTIGATION_CONTEXT_TYPE,
)
from core.exceptions import DataValidationError

# --- Numeric/date/causal scanning constants --------------------------------------

# Comma-grouped numbers first so "1,022,835" parses wholly; plain numbers
# second. Signs are captured for negatives such as "-0.04".
_NUMBER_RE: re.Pattern[str] = re.compile(
    r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
)

_ISO_DATE_RE: re.Pattern[str] = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_EVIDENCE_ID_TOKEN_RE: re.Pattern[str] = re.compile(r"\bE\d+\b")

# Unsupported causal phrasing scanned in prose only (never in structured
# factor labels). Word boundaries prevent matches inside words such as
# "because"; factor labels like "volume_driven" live in a dedicated
# metadata field that is excluded from the prose scan.
_CAUSAL_RE: re.Pattern[str] = re.compile(
    r"\bdirectly\s+caused\b"
    r"|\bcaused\b"
    r"|\bcauses\b"
    r"|\bcause\b"
    r"|\bbecause\s+of\b"
    r"|\bdue\s+to\b"
    r"|\bresult(?:ed|s)?\s+in\b"
    r"|\bresulting\s+from\b"
    r"|\bled\s+to\b"
    r"|\bdriven\s+by\b"
    r"|\bresponsible\s+for\b",
    re.IGNORECASE,
)

_EMPTY_GROUNDING_REPORT: dict[str, object] = {
    "valid": False,
    "citation_errors": [],
    "numeric_errors": [],
    "causation_errors": [],
    "schema_errors": [],
    "unsupported_claims": [],
}


# --- Plain-type conversion ---------------------------------------------------------


def _plain(value: Any) -> Any:
    """Recursively convert ``value`` into JSON-safe plain Python types."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = [_plain(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, set) else items
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (str, type(None))):
        return value
    return str(value)


# --- Input resolution ---------------------------------------------------------------


def _validate_retries(max_grounding_retries: object) -> int:
    """Validate the retry budget; negative/non-int values are rejected."""
    if isinstance(max_grounding_retries, bool) or not isinstance(
        max_grounding_retries, int
    ):
        raise DataValidationError(
            "max_grounding_retries must be an integer; got "
            f"{type(max_grounding_retries).__name__}"
        )
    if max_grounding_retries < 0:
        raise DataValidationError(
            "max_grounding_retries must be >= 0; got "
            f"{max_grounding_retries}"
        )
    return int(max_grounding_retries)


def _validate_context_contract(context: object) -> None:
    """Reject dictionaries that do not satisfy the Phase 4A contract."""
    if not isinstance(context, dict):
        raise DataValidationError(
            "investigate() accepts a canonical DataFrame or an "
            f"investigation context dictionary; got {type(context).__name__}"
        )
    missing = sorted(EXPECTED_CONTEXT_KEYS - set(context))
    unexpected = sorted(set(context) - EXPECTED_CONTEXT_KEYS)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing key(s): {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected key(s): {', '.join(unexpected)}")
        raise DataValidationError(
            "Malformed investigation context: " + "; ".join(details)
        )
    if context.get("type") != INVESTIGATION_CONTEXT_TYPE:
        raise DataValidationError(
            f"context['type'] must be {INVESTIGATION_CONTEXT_TYPE!r}; got "
            f"{context.get('type')!r}"
        )
    if context.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise DataValidationError(
            f"context['schema_version'] must be {CONTEXT_SCHEMA_VERSION!r}; "
            f"got {context.get('schema_version')!r}"
        )
    evidence_index = context.get("evidence_index")
    if not isinstance(evidence_index, dict) or not evidence_index:
        raise DataValidationError(
            "context['evidence_index'] must be a non-empty dictionary of "
            "E<id> entries"
        )
    for evidence_id, entry in evidence_index.items():
        if not isinstance(evidence_id, str) or not _EVIDENCE_ID_TOKEN_RE.fullmatch(
            evidence_id
        ):
            raise DataValidationError(
                f"evidence_index contains invalid evidence id {evidence_id!r}"
            )
        if not isinstance(entry, dict):
            raise DataValidationError(
                f"evidence_index[{evidence_id!r}] must be a dictionary"
            )


def resolve_investigation_context(df_or_context: object) -> dict[str, object]:
    """Normalize DataFrame/context input into a fresh evidence pack.

    A DataFrame runs through ``build_investigation_context``; a valid
    context dictionary is validated, deep-copied, and returned unchanged
    (never recomputed).
    """
    if isinstance(df_or_context, pd.DataFrame):
        from agent.evidence import build_investigation_context

        return build_investigation_context(df_or_context)
    _validate_context_contract(df_or_context)
    return copy.deepcopy(df_or_context)


# --- Grounded-value collection -------------------------------------------------------


def _collect_grounded_values(context: dict) -> tuple[set[float], set[str]]:
    """Extract every legitimate number and ISO date from the pack.

    Walks all leaves of the aggregate-only context: numeric leaves become
    normalized floats; string leaves contribute ISO dates only. Numbers
    embedded in free-text strings deliberately do NOT become grounded:
    dataset strings (region/product names) are untrusted, and every
    citable statistic in the pack also exists as a numeric leaf.
    Deterministic and order-independent.
    """
    numbers: set[float] = set()
    dates: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)
            return
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            if math.isfinite(float(node)):
                numbers.add(round(float(node), 2))
            return
        if isinstance(node, str):
            for match in _ISO_DATE_RE.findall(node):
                dates.add(match)

    walk(context)
    return numbers, dates


def _extract_claims(text: str) -> tuple[list[float], list[str]]:
    """Extract candidate factual numbers and ISO dates from LLM prose."""
    claimed_dates = _ISO_DATE_RE.findall(text)
    scrubbed = _ISO_DATE_RE.sub(" ", text)
    scrubbed = _EVIDENCE_ID_TOKEN_RE.sub(" ", scrubbed)
    values = [
        round(float(token.replace(",", "")), 2)
        for token in _NUMBER_RE.findall(scrubbed)
    ]
    return values, claimed_dates


# --- Response parsing and schema checking ---------------------------------------------


def _parse_response_json(text: str) -> tuple[object, list[str]]:
    """Parse the model response, returning ``(payload, schema_errors)``."""
    try:
        return json.loads(text), []
    except (json.JSONDecodeError, TypeError):
        return None, ["Response was not valid JSON."]


def _check_string_field(container: dict, field: str, where: str, errors: list[str]) -> None:
    if field in container and not isinstance(container[field], str):
        errors.append(f"{where}.{field} must be a string")


def _check_evidence_ids_list(
    container: dict, where: str, errors: list[str]
) -> list[str] | None:
    """Validate an ``evidence_ids`` field; returns it when well-formed."""
    if "evidence_ids" not in container:
        errors.append(f"{where} is missing required field 'evidence_ids'")
        return None
    value = container["evidence_ids"]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{where}.evidence_ids must be a list of strings")
        return None
    return value


def _check_exact_keys(
    container: object, expected: frozenset[str], where: str, errors: list[str]
) -> bool:
    if not isinstance(container, dict):
        errors.append(f"{where} must be an object")
        return False
    unexpected = sorted(set(map(str, container)) - expected)
    for key in unexpected:
        errors.append(f"{where} has unsupported field '{key}'")
    return True


def _schema_errors(payload: object) -> list[str]:
    """Structural validation of the expected Gemini JSON shape."""
    errors: list[str] = []
    if payload is None or not isinstance(payload, dict):
        return ["Response root must be a JSON object."]
    _check_exact_keys(payload, frozenset({"narrative", "hypotheses", "citations"}), "Response root", errors)

    narrative = payload.get("narrative")
    if narrative is None:
        errors.append("Response root is missing required field 'narrative'")
    elif _check_exact_keys(narrative, EXPECTED_NARRATIVE_KEYS, "narrative", errors):
        summary = narrative.get("executive_summary")
        if summary is None:
            errors.append("narrative is missing required field 'executive_summary'")
        else:
            _check_string_field(narrative, "executive_summary", "narrative", errors)
        findings_lists = (
            ("key_findings", "key_findings"),
            ("operational_interpretation", "operational_interpretation"),
        )
        for field, label in findings_lists:
            section = narrative.get(field)
            if section is None:
                errors.append(f"narrative is missing required field '{field}'")
                continue
            if not isinstance(section, list):
                errors.append(f"narrative.{field} must be a list")
                continue
            for position, finding in enumerate(section):
                where = f"narrative.{label}[{position}]"
                if not _check_exact_keys(finding, EXPECTED_FINDING_KEYS, where, errors):
                    continue
                _check_string_field(finding, "claim", where, errors)
                if "claim" not in finding:
                    errors.append(f"{where} is missing required field 'claim'")
                _check_evidence_ids_list(finding, where, errors)

    hypotheses = payload.get("hypotheses")
    if hypotheses is None:
        errors.append("Response root is missing required field 'hypotheses'")
    elif not isinstance(hypotheses, list):
        errors.append("hypotheses must be a list")
    else:
        for position, hypothesis in enumerate(hypotheses):
            where = f"hypotheses[{position}]"
            if not _check_exact_keys(hypothesis, EXPECTED_HYPOTHESIS_KEYS, where, errors):
                continue
            for field in ("hypothesis",):
                if field not in hypothesis:
                    errors.append(f"{where} is missing required field '{field}'")
            _check_string_field(hypothesis, "hypothesis", where, errors)
            factor = hypothesis.get("factor")
            if "factor" in hypothesis and factor is not None and not isinstance(factor, str):
                errors.append(f"{where}.factor must be a string or null")
            confidence = hypothesis.get("confidence")
            if "confidence" in hypothesis:
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    errors.append(f"{where}.confidence must be a number")
                elif not math.isfinite(float(confidence)):
                    errors.append(f"{where}.confidence must be a finite number")
            else:
                errors.append(f"{where} is missing required field 'confidence'")
            _check_evidence_ids_list(hypothesis, where, errors)

    citations = payload.get("citations")
    if citations is None:
        errors.append("Response root is missing required field 'citations'")
    elif not isinstance(citations, list):
        errors.append("citations must be a list")
    else:
        for position, citation in enumerate(citations):
            where = f"citations[{position}]"
            if not _check_exact_keys(citation, EXPECTED_CITATION_KEYS, where, errors):
                continue
            if "evidence_id" not in citation:
                errors.append(f"{where} is missing required field 'evidence_id'")
            _check_string_field(citation, "evidence_id", where, errors)
            if "claim" not in citation:
                errors.append(f"{where} is missing required field 'claim'")
            _check_string_field(citation, "claim", where, errors)

    return errors


# --- Prose collection ------------------------------------------------------------------


def _prose_fields(payload: object) -> list[tuple[str, str]]:
    """Collect ``(location, prose)`` pairs subject to numeric/causal scans.

    Structured ``factor`` labels are intentionally excluded: they mirror
    Phase 3B metadata (for example ``volume_driven``) rather than
    natural-language claims.
    """
    fields: list[tuple[str, str]] = []
    if not isinstance(payload, dict):
        return fields
    narrative = payload.get("narrative")
    if isinstance(narrative, dict):
        summary = narrative.get("executive_summary")
        if isinstance(summary, str):
            fields.append(("narrative.executive_summary", summary))
        for label in ("key_findings", "operational_interpretation"):
            section = narrative.get(label)
            if not isinstance(section, list):
                continue
            for position, finding in enumerate(section):
                if isinstance(finding, dict) and isinstance(finding.get("claim"), str):
                    fields.append((f"narrative.{label}[{position}].claim", finding["claim"]))
    hypotheses = payload.get("hypotheses")
    if isinstance(hypotheses, list):
        for position, hypothesis in enumerate(hypotheses):
            if isinstance(hypothesis, dict) and isinstance(hypothesis.get("hypothesis"), str):
                fields.append(
                    (f"hypotheses[{position}].hypothesis", hypothesis["hypothesis"])
                )
    citations = payload.get("citations")
    if isinstance(citations, list):
        for position, citation in enumerate(citations):
            if isinstance(citation, dict) and isinstance(citation.get("claim"), str):
                fields.append((f"citations[{position}].claim", citation["claim"]))
    return fields


def _cited_ids(payload: object) -> list[tuple[str, str]]:
    """Collect ``(location, evidence_id)`` pairs from structured fields."""
    references: list[tuple[str, str]] = []
    if not isinstance(payload, dict):
        return references

    def from_container(label: str, container: object, field: str) -> None:
        if not isinstance(container, dict):
            return
        ids = container.get(field)
        if isinstance(ids, list):
            for item in ids:
                if isinstance(item, str):
                    references.append((label, item))

    narrative = payload.get("narrative")
    if isinstance(narrative, dict):
        for section_label in ("key_findings", "operational_interpretation"):
            section = narrative.get(section_label)
            if isinstance(section, list):
                for position, finding in enumerate(section):
                    from_container(
                        f"narrative.{section_label}[{position}]", finding, "evidence_ids"
                    )
    hypotheses = payload.get("hypotheses")
    if isinstance(hypotheses, list):
        for position, hypothesis in enumerate(hypotheses):
            from_container(f"hypotheses[{position}]", hypothesis, "evidence_ids")
    citations = payload.get("citations")
    if isinstance(citations, list):
        for position, citation in enumerate(citations):
            from_container(f"citations[{position}]", citation, "evidence_id")
    return references


def _dedupe(items: list[str]) -> list[str]:
    """Preserve first-seen order while dropping duplicates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


# --- Public grounding validator ----------------------------------------------------------


def validate_grounding(payload: object, context: dict) -> dict[str, object]:
    """Deterministically validate a Gemini response against the evidence pack.

    Checks performed:

    * **Schema** — the response matches the mandated JSON shape.
    * **Citation existence** — every cited id exists in ``evidence_index``
      and every factual finding carries at least one citation.
    * **Numeric grounding** — every number in the prose appears in the
      evidence pack (normalized comparison); unknown ISO dates are
      reported under ``unsupported_claims``.
    * **Causation scan** — unsupported causal phrases in prose are
      rejected; structured factor metadata is exempt.

    Args:
        payload: Parsed JSON response (or ``None`` when unparseable).
        context: The Phase 4A evidence pack used as the sole factual
            source. Never mutated.

    Returns:
        Grounding report with exactly the keys in
        ``agent.schemas.EXPECTED_GROUNDING_REPORT_KEYS``. Identical inputs
        always yield an identical report.
    """
    report: dict[str, object] = {
        "valid": False,
        "citation_errors": [],
        "numeric_errors": [],
        "causation_errors": [],
        "schema_errors": [],
        "unsupported_claims": [],
    }

    schema_errors = _schema_errors(payload)
    report["schema_errors"] = schema_errors

    evidence_index = context.get("evidence_index", {})
    known_ids: set[str] = {
        str(evidence_id) for evidence_id in evidence_index
        if isinstance(evidence_id, str)
    }
    grounded_numbers, grounded_dates = _collect_grounded_values(context)

    citation_errors: list[str] = []
    for location, evidence_id in _cited_ids(payload):
        if evidence_id not in known_ids:
            citation_errors.append(
                f"Unknown evidence id {evidence_id!r} cited in {location}"
            )
    for location, _finding in _findings_without_citations(payload):
        citation_errors.append(
            f"{location} has no evidence ids; every factual finding requires "
            "a citation"
        )
    report["citation_errors"] = _dedupe(citation_errors)

    numeric_errors: list[str] = []
    unsupported_claims: list[str] = []
    causation_errors: list[str] = []
    for location, prose in _prose_fields(payload):
        values, claimed_dates = _extract_claims(prose)
        for value in values:
            if value not in grounded_numbers:
                numeric_errors.append(
                    f"Numeric value {_format_number(value)} in {location} is "
                    "not present in the evidence pack"
                )
        for claimed_date in claimed_dates:
            if claimed_date not in grounded_dates:
                unsupported_claims.append(
                    f"Date {claimed_date!r} in {location} does not appear in "
                    "the evidence pack"
                )
        for match in _CAUSAL_RE.finditer(prose):
            causation_errors.append(
                f"Unsupported causal phrase {match.group(0)!r} in {location}; "
                "use associative language instead"
            )

    report["numeric_errors"] = _dedupe(numeric_errors)
    report["unsupported_claims"] = _dedupe(unsupported_claims)
    report["causation_errors"] = _dedupe(causation_errors)

    report["valid"] = not any(
        report[key] for key in (
            "citation_errors",
            "numeric_errors",
            "causation_errors",
            "schema_errors",
            "unsupported_claims",
        )
    )
    return {key: _plain(report[key]) for key in EXPECTED_GROUNDING_REPORT_KEYS}


def _format_number(value: float) -> str:
    """Render a normalized number without trailing ``.0`` noise."""
    if float(value).is_integer():
        return str(int(value))
    return repr(value)


def _findings_without_citations(payload: object) -> list[tuple[str, object]]:
    """Locate factual findings lacking any evidence ids."""
    missing: list[tuple[str, object]] = []
    if not isinstance(payload, dict):
        return missing
    narrative = payload.get("narrative")
    if isinstance(narrative, dict):
        for label in ("key_findings", "operational_interpretation"):
            section = narrative.get(label)
            if not isinstance(section, list):
                continue
            for position, finding in enumerate(section):
                if not isinstance(finding, dict):
                    continue
                ids = finding.get("evidence_ids")
                if not isinstance(ids, list) or not ids:
                    missing.append((f"narrative.{label}[{position}]", finding))
    hypotheses = payload.get("hypotheses")
    if isinstance(hypotheses, list):
        for position, hypothesis in enumerate(hypotheses):
            if not isinstance(hypothesis, dict):
                continue
            ids = hypothesis.get("evidence_ids")
            if not isinstance(ids, list) or not ids:
                missing.append((f"hypotheses[{position}]", hypothesis))
    return missing


# --- Response normalization -----------------------------------------------------------------


def _normalized_response(payload: dict) -> tuple[dict, list[dict], list[dict]]:
    """Project a validated response onto the exact public contracts."""
    narrative_payload = payload["narrative"]
    narrative = {
        "executive_summary": str(narrative_payload["executive_summary"]),
        "key_findings": [
            {
                "claim": str(finding["claim"]),
                "evidence_ids": [str(item) for item in finding["evidence_ids"]],
            }
            for finding in narrative_payload["key_findings"]
        ],
        "operational_interpretation": [
            {
                "claim": str(finding["claim"]),
                "evidence_ids": [str(item) for item in finding["evidence_ids"]],
            }
            for finding in narrative_payload["operational_interpretation"]
        ],
    }
    hypotheses = [
        {
            "hypothesis": str(hypothesis["hypothesis"]),
            "factor": None if hypothesis["factor"] is None else str(hypothesis["factor"]),
            "confidence": float(hypothesis["confidence"]),
            "evidence_ids": [str(item) for item in hypothesis["evidence_ids"]],
        }
        for hypothesis in payload["hypotheses"]
    ]
    citations = [
        {
            "evidence_id": str(citation["evidence_id"]),
            "claim": str(citation["claim"]),
        }
        for citation in payload["citations"]
    ]
    return narrative, hypotheses, citations


# --- Public API --------------------------------------------------------------------------------


def investigate(
    df_or_context: object,
    *,
    client: object | None = None,
    max_grounding_retries: int = 2,
) -> dict[str, object]:
    """Run one evidence-grounded agentic investigation.

    Args:
        df_or_context: Either a canonical operational DataFrame (run
            through ``build_investigation_context`` first) or an existing
            Phase 4A evidence-pack dictionary (validated and reused; the
            evidence pack is NOT rebuilt).
        client: Injectable Gemini-compatible client exposing
            ``generate_json(prompt) -> str``. When ``None``, a real
            :class:`GeminiNarratorClient` is constructed, which requires
            ``GEMINI_API_KEY`` configuration.
        max_grounding_retries: Number of corrective retries after the
            initial failed attempt (``0`` means a single attempt).
            Negative or non-integer values raise ``DataValidationError``.

    Returns:
        Dictionary with exactly the keys in
        ``agent.schemas.EXPECTED_RESULT_KEYS``::

            {
                "status": "complete" | "narrative_rejected",
                "evidence_pack": {...},
                "narrative": {...},
                "hypotheses": [...],
                "citations": [...],
                "grounding_report": {...},
            }

        On ``complete`` the narrative/hypotheses/citations passed every
        grounding check. On ``narrative_rejected`` the evidence pack and
        the final grounding report are still returned, while the
        narrative is a safe fallback containing no factual claims.

    Raises:
        DataValidationError: For invalid retry counts, unusable
            DataFrames, or malformed evidence contexts.
        ConfigurationError: When no injectable client is supplied and no
            Gemini API key is configured.
        AgentError: When the configured Gemini client fails to produce a
            response.
    """
    retries = _validate_retries(max_grounding_retries)
    context = resolve_investigation_context(df_or_context)
    narrator = client if client is not None else GeminiNarratorClient()

    base_prompt = build_investigation_prompt(context)
    previous_text: str | None = None
    previous_report: dict[str, object] | None = None

    attempts = retries + 1
    for attempt in range(attempts):
        if attempt == 0:
            prompt = base_prompt
        else:
            prompt = build_retry_prompt(context, previous_text or "", previous_report or {})
        response_text = narrator.generate_json(prompt)  # type: ignore[attr-defined]

        payload, parse_errors = _parse_response_json(response_text)
        report = validate_grounding(payload, context)
        if parse_errors:
            merged_schema_errors = parse_errors + list(report["schema_errors"])  # type: ignore[arg-type]
            report["schema_errors"] = merged_schema_errors  # type: ignore[assignment]
            report["valid"] = False

        if report["valid"]:
            narrative, hypotheses, citations = _normalized_response(payload)  # type: ignore[arg-type]
            return _build_result(
                status="complete",
                context=context,
                narrative=narrative,
                hypotheses=hypotheses,
                citations=citations,
                grounding_report=report,
            )
        previous_text = response_text
        previous_report = report

    assert previous_report is not None  # loop always runs at least once
    return _build_result(
        status="narrative_rejected",
        context=context,
        narrative=dict(FALLBACK_NARRATIVE),
        hypotheses=[],
        citations=[],
        grounding_report=previous_report,
    )


def _build_result(
    *,
    status: str,
    context: dict,
    narrative: dict,
    hypotheses: list[dict],
    citations: list[dict],
    grounding_report: dict,
) -> dict[str, object]:
    """Assemble the JSON-safe public result with its exact key set."""
    result: dict[str, object] = {
        "status": status,
        "evidence_pack": _plain(context),
        "narrative": _plain(narrative),
        "hypotheses": _plain(hypotheses),
        "citations": _plain(citations),
        "grounding_report": _plain(grounding_report),
    }
    assert set(result) == EXPECTED_RESULT_KEYS
    return result
