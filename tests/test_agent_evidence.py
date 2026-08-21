"""Tests for the Phase 4A evidence-pack builder.

Covers ``agent.evidence.build_investigation_context`` and the schema
constants in ``agent.schemas`` against the documented Phase 4A policies:
exact pack structure, service-output parity, evidence-index alignment,
focus filtering semantics, validation errors, determinism, and
caller-input immutability. Synthetic frames with hand-computed anomaly
inventories are used for focus behavior; the demo dataset anchors
end-to-end parity with the Phase 2/3A/3B services.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evidence import build_investigation_context
from agent.schemas import (
    ANOMALY_ENTRY_FIELDS,
    CONTEXT_SCHEMA_VERSION,
    EVIDENCE_CHANGE_FIELDS,
    EVIDENCE_ID_PREFIX,
    EVIDENCE_KINDS,
    EVIDENCE_KPI_FIELDS,
    EXPECTED_CONTEXT_KEYS,
    EXPECTED_PARAMETERS_KEYS,
    FOCUS_KEYS,
    GROUP_ENTRY_FIELDS,
    INVESTIGATION_CONTEXT_TYPE,
    NARRATIVE_INSTRUCTIONS,
)
from core.exceptions import DataValidationError
from services.anomaly_service import detect_anomalies
from services.analytics_service import (
    calculate_bottom_performers,
    calculate_kpis,
    calculate_period_comparison,
    calculate_top_performers,
)
from services.data_service import load_dataset
from services.insight_service import (
    analyze_metric_contexts,
    explain_anomalies,
    group_related_anomalies,
)
from services.validation_service import REQUIRED_COLUMNS

# --- Shared fixtures ---------------------------------------------------------

_DEMO_FRAME_CACHE: pd.DataFrame | None = None


def demo_frame() -> pd.DataFrame:
    """Load the bundled demo dataset once per session."""
    global _DEMO_FRAME_CACHE
    if _DEMO_FRAME_CACHE is None:
        _DEMO_FRAME_CACHE = load_dataset("demo_operational_data.csv")
    return _DEMO_FRAME_CACHE


def date_at(offset: int, start: str = "2024-01-01") -> str:
    return (pd.Timestamp(start) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def make_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(REQUIRED_COLUMNS))


SPIKE_DAY_OFFSET: int = 11
SPIKE_DATE: str = date_at(SPIKE_DAY_OFFSET)
SPIKE_REGION: str = "North"
BASE_REGIONS: tuple[str, ...] = ("North", "South", "East", "West")
BASE_PRODUCT: str = "Widget Pro"


def make_spike_frame() -> pd.DataFrame:
    """Frame with one huge revenue spike (region North on the final day).

    Daily totals cycle through {400, 420, 440} so baseline windows have
    nonzero variance; the spike day produces daily anomalies for every
    mirrored metric and a full-period entity outlier for region North.
    """
    rows: list[dict[str, object]] = []
    for day in range(SPIKE_DAY_OFFSET + 1):
        base = 100.0 + 5.0 * (day % 3)
        for region in BASE_REGIONS:
            revenue = base
            if day == SPIKE_DAY_OFFSET and region == SPIKE_REGION:
                revenue = 10000.0
            rows.append(
                {
                    "date": date_at(day),
                    "region": region,
                    "product": BASE_PRODUCT,
                    "units_sold": int(revenue // 10),
                    "revenue": revenue,
                    "cost": round(revenue * 0.5, 2),
                    "lead_time_days": 7,
                }
            )
    return make_rows(rows)


def make_flat_frame() -> pd.DataFrame:
    """Constant frame producing zero anomalies across all detectors."""
    rows: list[dict[str, object]] = []
    for day in range(10):
        for region in BASE_REGIONS:
            for product in ("Widget Pro", "Gadget Plus"):
                rows.append(
                    {
                        "date": date_at(day),
                        "region": region,
                        "product": product,
                        "units_sold": 10,
                        "revenue": 100.0,
                        "cost": 50.0,
                        "lead_time_days": 7,
                    }
                )
    return make_rows(rows)


def make_single_row_frame() -> pd.DataFrame:
    """One-row frame: valid dataset with a single unique date."""
    return make_rows(
        [
            {
                "date": "2024-03-01",
                "region": "North",
                "product": "Widget Pro",
                "units_sold": 5,
                "revenue": 50.0,
                "cost": 20.0,
                "lead_time_days": 3,
            }
        ]
    )


# --- Fixture sanity ------------------------------------------------------------


def test_spike_fixture_produces_expected_inventory():
    detection = detect_anomalies(make_spike_frame())
    records = detection["anomalies"]
    assert len(records) == 6
    daily = [record for record in records if record["scope"] == "daily"]
    entity = [record for record in records if record["scope"] == "region"]
    assert len(daily) == 3
    assert len(entity) == 3
    assert all(record["severity"] == "CRITICAL" for record in records)
    assert all(record["entity"] == SPIKE_REGION for record in entity)


# --- Pack structure --------------------------------------------------------------


def test_top_level_keys_exact():
    pack = build_investigation_context(demo_frame())
    assert set(pack) == set(EXPECTED_CONTEXT_KEYS)


def test_type_and_schema_version():
    pack = build_investigation_context(demo_frame())
    assert pack["type"] == INVESTIGATION_CONTEXT_TYPE
    assert pack["schema_version"] == CONTEXT_SCHEMA_VERSION


def test_parameters_block_defaults():
    pack = build_investigation_context(demo_frame())
    assert set(pack["parameters"]) == set(EXPECTED_PARAMETERS_KEYS)
    assert pack["parameters"]["sensitivity"] == "medium"
    assert pack["parameters"]["focus"] == {}


def test_parameters_metrics_sorted():
    pack = build_investigation_context(demo_frame())
    metrics = pack["parameters"]["metrics"]
    assert metrics == sorted(metrics)
    assert len(metrics) > 0


def test_kpis_match_service():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    assert pack["kpis"] == calculate_kpis(frame)


def test_period_comparison_matches_service():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    assert pack["period_comparison"] == calculate_period_comparison(frame)


def test_performers_match_services():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    assert pack["top_performers"] == calculate_top_performers(frame)
    assert pack["bottom_performers"] == calculate_bottom_performers(frame)


def test_context_matches_service():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    assert pack["context"] == analyze_metric_contexts(frame)


def test_anomalies_match_detector():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    expected = detect_anomalies(frame)["anomalies"]
    assert pack["anomalies"] == expected


def test_insights_pair_with_anomalies():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    assert len(pack["insights"]) == len(pack["anomalies"])
    for position, insight in enumerate(pack["insights"]):
        assert insight["anomaly_index"] == position
        record = pack["anomalies"][position]
        assert insight["scope"] == record["scope"]
        assert insight["metric"] == record["metric"]
        assert insight["entity"] == record["entity"]
        assert insight["date"] == record["date"]
        assert insight["severity"] == record["severity"]


def test_groups_match_grouping_service():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    expected = group_related_anomalies(pack["anomalies"])
    assert pack["groups"] == expected


def test_sensitivity_passthrough():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, sensitivity="high")
    assert pack["parameters"]["sensitivity"] == "high"
    expected = detect_anomalies(frame, sensitivity="high")["anomalies"]
    assert pack["anomalies"] == expected


# --- Evidence index ---------------------------------------------------------------


def test_evidence_ids_contiguous_and_unique():
    pack = build_investigation_context(demo_frame())
    index = pack["evidence_index"]
    ids = list(index)
    expected_ids = [f"{EVIDENCE_ID_PREFIX}{position}" for position in range(1, len(ids) + 1)]
    assert ids == expected_ids
    assert len(set(ids)) == len(ids)


def test_entry_kinds_valid_with_expected_present():
    pack = build_investigation_context(demo_frame())
    kinds = {entry["kind"] for entry in pack["evidence_index"].values()}
    assert kinds <= set(EVIDENCE_KINDS)
    assert {"kpi", "period_change", "performer"} <= kinds


def test_kpi_entries_values_match_pack():
    pack = build_investigation_context(demo_frame())
    kpi_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "kpi"
    ]
    assert len(kpi_entries) == len(EVIDENCE_KPI_FIELDS)
    for entry in kpi_entries:
        assert entry["field"] in EVIDENCE_KPI_FIELDS
        assert entry["value"] == pack["kpis"][entry["field"]]


def test_change_entries_match_changes_pct():
    pack = build_investigation_context(demo_frame())
    change_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "period_change"
    ]
    changes = pack["period_comparison"]["changes_pct"]
    assert len(change_entries) == len(EVIDENCE_CHANGE_FIELDS)
    for entry in change_entries:
        assert entry["field"] in EVIDENCE_CHANGE_FIELDS
        assert entry["value"] == changes[entry["field"]]


def test_performer_entries_match_records():
    frame = demo_frame()
    pack = build_investigation_context(frame)
    sources = {
        "top_regions": (pack["top_performers"]["regions"], "region"),
        "top_products": (pack["top_performers"]["products"], "product"),
        "bottom_regions": (pack["bottom_performers"]["regions"], "region"),
        "bottom_products": (pack["bottom_performers"]["products"], "product"),
    }
    performer_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "performer"
    ]
    expected_count = sum(len(records) for records, _ in sources.values())
    assert len(performer_entries) == expected_count
    by_list: dict[str, list[dict[str, object]]] = {}
    for entry in performer_entries:
        by_list.setdefault(entry["list"], []).append(entry)
    for list_name, (records, dimension) in sources.items():
        entries = sorted(by_list[list_name], key=lambda item: int(item["rank"]))  # type: ignore[arg-type,return-value]
        assert [entry["rank"] for entry in entries] == [record["rank"] for record in records]
        assert [entry["entity"] for entry in entries] == [record[dimension] for record in records]
        assert [entry["value"] for entry in entries] == [record["revenue"] for record in records]


def test_correlation_entries_citable_only():
    pack = build_investigation_context(demo_frame())
    context_pairs = {
        (item["metric_a"], item["metric_b"]): item for item in pack["context"]["correlations"]
    }
    correlation_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "correlation"
    ]
    for entry in correlation_entries:
        assert entry["strength"] in {"moderate", "strong"}
        key = (min(entry["pair"]), max(entry["pair"]))
        source = context_pairs[key]
        assert entry["r"] == source["r"]
        assert entry["strength"] == source["strength"]


def test_anomaly_entries_index_aligned():
    pack = build_investigation_context(demo_frame())
    anomaly_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "anomaly"
    ]
    assert len(anomaly_entries) == len(pack["anomalies"])
    for entry in anomaly_entries:
        record = pack["anomalies"][entry["anomaly_index"]]
        for field in ANOMALY_ENTRY_FIELDS:
            assert entry[field] == record[field]


def test_group_entries_match_groups():
    pack = build_investigation_context(demo_frame())
    group_entries = [
        entry for entry in pack["evidence_index"].values() if entry["kind"] == "group"
    ]
    groups = pack["groups"]["groups"]
    assert len(group_entries) == len(groups)
    entries_by_id = {entry["group_id"]: entry for entry in group_entries}
    for group in groups:
        entry = entries_by_id[group["group_id"]]
        for field in GROUP_ENTRY_FIELDS:
            assert entry[field] == group[field]


# --- Focus filtering -----------------------------------------------------------------


def retained_metrics(pack: dict[str, object]) -> set[str]:
    return {str(record["metric"]) for record in pack["anomalies"]}  # type: ignore[index]


def test_focus_metrics_filter():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, focus={"metrics": ["revenue"]})
    assert retained_metrics(pack) == {"revenue"}
    assert len(pack["insights"]) == len(pack["anomalies"])
    assert detect_anomalies(frame)["total_count"] == 6


def test_focus_scopes_daily_filter():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, focus={"scopes": ["daily"]})
    assert all(record["scope"] == "daily" for record in pack["anomalies"])
    assert all(record["entity"] is None for record in pack["anomalies"])
    assert len(pack["anomalies"]) == 3


def test_focus_scopes_region_filter():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, focus={"scopes": ["region"]})
    assert all(record["scope"] == "region" for record in pack["anomalies"])
    assert all(record["entity"] is not None for record in pack["anomalies"])
    assert len(pack["anomalies"]) == 3


def test_focus_entities_matching_entity():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, focus={"entities": [SPIKE_REGION]})
    assert len(pack["anomalies"]) == 3
    assert all(record["entity"] == SPIKE_REGION for record in pack["anomalies"])


def test_focus_entities_excludes_undated_and_other_entities():
    frame = make_spike_frame()
    pack = build_investigation_context(frame, focus={"entities": ["South"]})
    assert pack["anomalies"] == []
    assert pack["insights"] == []
    assert pack["groups"] == {"groups": [], "ungrouped_count": 0}


def test_focus_date_window_inclusive_bounds():
    frame = make_spike_frame()
    pack = build_investigation_context(
        frame, focus={"date_start": SPIKE_DATE, "date_end": SPIKE_DATE}
    )
    dated = [record for record in pack["anomalies"] if record["date"] is not None]
    undated = [record for record in pack["anomalies"] if record["date"] is None]
    assert len(dated) == 3
    assert all(record["date"] == SPIKE_DATE for record in dated)
    assert len(undated) == 3


def test_focus_undated_pass_date_filter():
    frame = make_spike_frame()
    pack = build_investigation_context(
        frame, focus={"date_start": "2024-01-01", "date_end": "2024-01-05"}
    )
    assert len(pack["anomalies"]) == 3
    assert all(record["date"] is None for record in pack["anomalies"])


def test_focus_combined_filters():
    frame = make_spike_frame()
    pack = build_investigation_context(
        frame,
        focus={
            "metrics": ["revenue"],
            "scopes": ["daily"],
            "date_start": SPIKE_DATE,
            "date_end": SPIKE_DATE,
        },
    )
    assert len(pack["anomalies"]) == 1
    record = pack["anomalies"][0]
    assert record["metric"] == "revenue"
    assert record["scope"] == "daily"
    assert record["date"] == SPIKE_DATE
    assert pack["insights"][0]["anomaly_index"] == 0


def test_focus_empty_dict_equals_no_restriction():
    frame = make_spike_frame()
    unrestricted = build_investigation_context(frame)
    empty_focus = build_investigation_context(frame, focus={})
    assert unrestricted == empty_focus


def test_focus_echoed_in_parameters():
    frame = make_spike_frame()
    focus: dict[str, object] = {"metrics": ["revenue"], "scopes": ["daily"]}
    snapshot = copy.deepcopy(focus)
    pack = build_investigation_context(frame, focus=focus)
    assert pack["parameters"]["focus"] == {"metrics": ["revenue"], "scopes": ["daily"]}
    assert focus == snapshot


# --- Validation errors -------------------------------------------------------------


def test_rejects_non_dataframe():
    with pytest.raises(DataValidationError):
        build_investigation_context([1, 2, 3])  # type: ignore[arg-type]


def test_rejects_empty_dataset():
    empty = pd.DataFrame({column: [] for column in REQUIRED_COLUMNS})
    with pytest.raises(DataValidationError):
        build_investigation_context(empty)


def test_rejects_invalid_sensitivity():
    with pytest.raises(DataValidationError, match="sensitivity"):
        build_investigation_context(make_spike_frame(), sensitivity="extreme")


def test_rejects_focus_not_dict():
    with pytest.raises(DataValidationError):
        build_investigation_context(make_spike_frame(), focus="revenue")  # type: ignore[arg-type]


def test_rejects_unknown_focus_key():
    with pytest.raises(DataValidationError, match="Unknown focus key"):
        build_investigation_context(make_spike_frame(), focus={"severities": ["HIGH"]})


@pytest.mark.parametrize("key", ["metrics", "scopes", "entities"])
def test_rejects_empty_list_filters(key):
    with pytest.raises(DataValidationError):
        build_investigation_context(make_spike_frame(), focus={key: []})


def test_rejects_unsupported_metric_in_focus():
    with pytest.raises(DataValidationError, match="Unsupported focus metric"):
        build_investigation_context(make_spike_frame(), focus={"metrics": ["profit"]})


def test_rejects_unsupported_scope_in_focus():
    with pytest.raises(DataValidationError, match="Unsupported focus scope"):
        build_investigation_context(make_spike_frame(), focus={"scopes": ["weekly"]})


def test_rejects_non_string_entities():
    with pytest.raises(DataValidationError):
        build_investigation_context(make_spike_frame(), focus={"entities": [123]})


def test_rejects_bad_date_format():
    with pytest.raises(DataValidationError):
        build_investigation_context(make_spike_frame(), focus={"date_start": "01/2024"})


def test_rejects_inverted_date_range():
    with pytest.raises(DataValidationError):
        build_investigation_context(
            make_spike_frame(),
            focus={"date_start": "2024-01-10", "date_end": "2024-01-02"},
        )


# --- Determinism and immutability ----------------------------------------------------


def test_determinism_two_builds_equal():
    frame = make_spike_frame()
    first = build_investigation_context(frame)
    second = build_investigation_context(frame)
    assert first == second


def test_dataframe_not_mutated():
    frame = demo_frame()
    snapshot = frame.copy(deep=True)
    build_investigation_context(frame)
    assert frame.equals(snapshot)


def test_pack_snapshot_independent_of_later_df_changes():
    frame = make_spike_frame()
    pack = build_investigation_context(frame)
    before = pack["kpis"]["total_revenue"]
    frame.loc[frame.index[0], "revenue"] = 99999.0
    assert pack["kpis"]["total_revenue"] == before


def test_narrative_instructions_shape():
    pack = build_investigation_context(make_spike_frame())
    instructions = pack["narrative_instructions"]
    assert instructions == NARRATIVE_INSTRUCTIONS
    assert isinstance(instructions["rules"], tuple)
    assert len(instructions["rules"]) > 0
    assert all(isinstance(rule, str) and rule for rule in instructions["rules"])  # type: ignore[union-attr]


def test_pack_is_json_serializable():
    pack = build_investigation_context(demo_frame())
    encoded = json.dumps(pack)
    assert isinstance(encoded, str) and len(encoded) > 0


# --- Degenerate datasets ---------------------------------------------------------------


def test_single_date_dataset_yields_none_period_comparison():
    pack = build_investigation_context(make_single_row_frame())
    assert pack["period_comparison"] is None
    assert pack["anomalies"] == []
    assert pack["insights"] == []
    assert pack["groups"] == {"groups": [], "ungrouped_count": 0}
    kinds = {entry["kind"] for entry in pack["evidence_index"].values()}
    assert kinds == {"kpi", "performer"}


def test_flat_series_zero_anomalies_but_valid_pack():
    pack = build_investigation_context(make_flat_frame())
    assert pack["anomalies"] == []
    assert pack["insights"] == []
    assert pack["groups"] == {"groups": [], "ungrouped_count": 0}
    assert pack["period_comparison"] is not None
    kinds = {entry["kind"] for entry in pack["evidence_index"].values()}
    assert "anomaly" not in kinds
    assert "group" not in kinds
    assert "correlation" not in kinds
    assert {"kpi", "period_change", "performer"} <= kinds
