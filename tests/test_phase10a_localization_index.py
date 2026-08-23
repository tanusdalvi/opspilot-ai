"""Phase 10A regression tests: localization index optimization.

Guards the ``_localization_for`` precomputation added to
``_ContextTables`` (``localization_index``) against semantic drift:

* differential comparison of the optimized localization against a
  verbatim copy of the original per-anomaly algorithm across dates,
  metrics, and directions;
* hand-computed multi-entity expectations on frames where entities have
  irregular observed-date coverage (per-entity observed positions differ
  from global frame positions);
* boundary dates (too early, unknown, entity without history);
* empty-anomaly and single-date degenerate safety;
* determinism across repeated calls;
* a structural performance guard asserting date formatting work is done
  once per dataset instead of once per anomaly.
"""

from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constants import SEVERITY_HIGH
from services.anomaly_service import MIN_HISTORY_DAYS, SUPPORTED_METRICS
from services.analytics_service import _prepare_operational_data, _round
from services.insight_service import (
    CONCENTRATED_CUMULATIVE_SHARE_PCT,
    LOCALIZATION_DIMENSIONS,
    LOCALIZED_SHARE_PCT,
    MAX_CONTRIBUTORS,
    _ContextTables,
    _localization_for,
    explain_anomalies,
)

METRICS_SORTED: list[str] = sorted(SUPPORTED_METRICS)
CANDIDATE_DATE: str = _date(2024, 1, 1).isoformat()


def date_at(offset: int) -> str:
    return (_date(2024, 1, 1) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def make_record(**overrides: object) -> dict[str, object]:
    """Schema-complete daily-scope anomaly record (mirrors Phase 3B tests)."""
    record: dict[str, object] = {
        "type": "daily_spike",
        "scope": "daily",
        "metric": "revenue",
        "entity": None,
        "date": CANDIDATE_DATE,
        "value": 115.0,
        "expected_value": 100.0,
        "deviation_pct": 15.0,
        "score": 77.16,
        "severity": SEVERITY_HIGH,
        "rule": "zscore_rolling",
        "details": {"z": 4.63, "baseline_std": 2.16, "threshold": 3.0},
    }
    record.update(overrides)
    return record


def make_gap_frame() -> pd.DataFrame:
    """12-day frame where region ``West`` has irregular observed coverage.

    ``North`` appears every day (revenue 100); ``West`` appears only on
    days 0-5 (revenue 50) and days 9-11 (revenue 60, then 300 on the
    final day). West's observed-position of the final day is 8 while its
    global position is 11, so any implementation that confuses the two
    produces different trailing windows.
    """
    rows: list[dict[str, object]] = []
    for offset in range(12):
        rows.append(
            {
                "date": date_at(offset),
                "region": "North",
                "product": "P",
                "units_sold": 10,
                "revenue": 100.0,
                "cost": 5.0,
                "lead_time_days": 5,
            }
        )
        if offset <= 5 or offset >= 9:
            west_revenue = 50.0 if offset <= 5 else (60.0 if offset == 9 or offset == 10 else 300.0)
            rows.append(
                {
                    "date": date_at(offset),
                    "region": "West",
                    "product": "P",
                    "units_sold": 4,
                    "revenue": west_revenue,
                    "cost": 2.0,
                    "lead_time_days": 7,
                }
            )
    return pd.DataFrame(rows)


# --- Reference implementation: verbatim original slow path --------------------


def _reference_localization_for(
    entity_daily: dict[tuple[str, str], pd.DataFrame],
    date_positions: dict[str, int],
    metric: str,
    iso_date: str,
    direction: int,
) -> dict[str, object] | None:
    """The pre-optimization algorithm, kept byte-for-byte in behavior."""
    position = date_positions.get(iso_date)
    if position is None or position < MIN_HISTORY_DAYS:
        return None
    if direction not in (-1, 1):
        direction = 1 if direction >= 0 else -1

    best: tuple[float, int, dict[str, object]] | None = None

    for dimension in LOCALIZATION_DIMENSIONS:
        frame = entity_daily[(dimension, metric)]
        if iso_date not in [stamp.strftime("%Y-%m-%d") for stamp in frame.index]:
            continue
        contributions: list[tuple[str, float]] = []
        for entity in sorted(map(str, frame.columns)):
            column = frame[entity]
            observed = column.dropna()
            stamps = [
                _date.fromisoformat(stamp.strftime("%Y-%m-%d"))
                for stamp in observed.index
            ]
            target = _date.fromisoformat(iso_date)
            if target not in stamps:
                continue
            entity_position = stamps.index(target)
            if entity_position < MIN_HISTORY_DAYS:
                continue
            window = observed.iloc[
                entity_position - MIN_HISTORY_DAYS : entity_position
            ].to_numpy(dtype=float)
            deviation = float(observed.iloc[entity_position]) - float(np.mean(window))
            contributions.append((entity, deviation))

        deviations = [deviation for _, deviation in contributions]
        total_abs = sum(abs(deviation) for deviation in deviations)
        if total_abs == 0.0 or len(contributions) < 2:
            continue

        same_direction_total = sum(
            deviation * direction for deviation in deviations if deviation * direction > 0
        )
        contributors_all: list[dict[str, object]] = []
        for entity, deviation in sorted(
            contributions, key=lambda item: (-abs(item[1]), item[0])
        ):
            share_pct = deviation / total_abs * 100.0
            contributors_all.append(
                {
                    "scope": dimension,
                    "entity": entity,
                    "share_pct": _round(share_pct),
                    "directional_share_pct": (
                        _round(deviation * direction / same_direction_total * 100.0)
                        if same_direction_total > 0
                        else 0.0
                    ),
                }
            )

        top_abs = abs(contributors_all[0]["share_pct"])
        cumulative_two = sum(
            abs(contributors_all[index]["share_pct"])
            for index in range(min(2, len(contributors_all)))
        )
        if top_abs >= LOCALIZED_SHARE_PCT:
            verdict = "localized"
        elif cumulative_two >= CONCENTRATED_CUMULATIVE_SHARE_PCT:
            verdict = "concentrated"
        else:
            verdict = "distributed"

        block = {
            "dimension": dimension,
            "verdict": verdict,
            "contributors": [
                {key: item[key] for key in ("entity", "share_pct")}
                for item in contributors_all[:MAX_CONTRIBUTORS]
            ],
        }
        rank_key = (-top_abs, LOCALIZATION_DIMENSIONS.index(dimension))
        if best is None or rank_key < (-best[0], best[1]):
            best = (top_abs, LOCALIZATION_DIMENSIONS.index(dimension), block)

    return None if best is None else best[2]


# --- Fixtures -----------------------------------------------------------------


def build_gap_tables() -> _ContextTables:
    return _ContextTables(_prepare_operational_data(make_gap_frame()))


# --- A. Differential equivalence ----------------------------------------------


def test_optimized_matches_reference_across_dates_metrics_directions():
    tables = build_gap_tables()
    directions = [-3, -1, 0, 1, 5]
    checked = 0
    for iso_offset in range(12):
        iso_date = date_at(iso_offset)
        for metric in METRICS_SORTED:
            for direction in directions:
                expected = _reference_localization_for(
                    tables.entity_daily, tables.date_positions, metric, iso_date, direction
                )
                actual = _localization_for(tables, metric, iso_date, direction)
                assert actual == expected, (
                    f"mismatch at {iso_date}/{metric}/direction={direction}: "
                    f"{actual!r} != {expected!r}"
                )
                checked += 1
    assert checked > 0


def test_index_positions_match_entity_daily_frames():
    tables = build_gap_tables()
    for dimension in LOCALIZATION_DIMENSIONS:
        for metric in METRICS_SORTED:
            frame = tables.entity_daily[(dimension, metric)]
            frame_positions, entities = tables.localization_index[(dimension, metric)]
            assert set(frame_positions) == {
                stamp.strftime("%Y-%m-%d") for stamp in frame.index
            }
            assert [entity for entity, _, _ in entities] == sorted(
                map(str, frame.columns)
            )
            for entity, values, observed_positions in entities:
                observed = frame[entity].dropna()
                assert list(observed_positions) == [
                    stamp.strftime("%Y-%m-%d") for stamp in observed.index
                ]
                np.testing.assert_array_equal(values, observed.to_numpy(dtype=float))


# --- B/C. Multi-entity and multi-date behavior --------------------------------


def test_multi_entity_gap_frame_localizes_with_expected_shares():
    tables = build_gap_tables()
    last_day = date_at(11)
    # North: flat 100 -> zero deviation; West: window mean 52.5 vs value 300.
    block = _localization_for(tables, "revenue", last_day, 1)
    assert block is not None
    assert block["dimension"] == "region"
    assert block["verdict"] == "localized"
    assert block["contributors"] == [
        {"entity": "West", "share_pct": 100.0},
        {"entity": "North", "share_pct": 0.0},
    ]


def test_each_anomaly_date_receives_independent_localization():
    frame = make_gap_frame()
    records = [
        make_record(date=date_at(10)),
        make_record(date=date_at(11)),
    ]
    insights = explain_anomalies(frame, records)["insights"]  # type: ignore[index]
    assert [insight["date"] for insight in insights] == [date_at(10), date_at(11)]
    first_block = insights[0]["localization"]
    second_block = insights[1]["localization"]
    assert first_block is not None and second_block is not None
    assert first_block["dimension"] == "region" == second_block["dimension"]
    assert first_block["verdict"] == "localized" == second_block["verdict"]
    # Day 10: West window mean 360/7 vs value 60 -> still the sole driver.
    assert first_block["contributors"][0]["entity"] == "West"
    assert first_block["contributors"][0]["share_pct"] == 100.0
    assert second_block["contributors"][0]["entity"] == "West"


# --- D. Boundary dates ---------------------------------------------------------


def test_dates_before_minimum_history_return_none():
    tables = build_gap_tables()
    for iso_offset in range(MIN_HISTORY_DAYS):
        assert (
            _localization_for(tables, "revenue", date_at(iso_offset), 1) is None
        ), date_at(iso_offset)


def test_unknown_date_returns_none():
    tables = build_gap_tables()
    assert _localization_for(tables, "revenue", "2030-01-01", 1) is None


def test_entity_without_history_on_target_date_is_skipped():
    # Day 8 exists globally (North) but West has no observation; North's
    # flat series yields zero total deviation, so no dimension qualifies.
    tables = build_gap_tables()
    assert _localization_for(tables, "revenue", date_at(8), 1) is None


def test_first_and_last_dataset_dates_behave_identically_to_reference():
    tables = build_gap_tables()
    all_dates = [stamp.strftime("%Y-%m-%d") for stamp in tables.dates]
    for iso_date in (all_dates[0], all_dates[-1], all_dates[len(all_dates) // 2]):
        for metric in METRICS_SORTED:
            expected = _reference_localization_for(
                tables.entity_daily, tables.date_positions, metric, iso_date, 1
            )
            assert _localization_for(tables, metric, iso_date, 1) == expected


# --- E/F. Empty and degenerate datasets ----------------------------------------


def test_empty_anomaly_list_remains_safe():
    frame = make_gap_frame()
    assert explain_anomalies(frame, []) == {"insights": []}


def test_single_date_dataset_builds_tables_and_returns_none():
    row = {
        "date": date_at(0),
        "region": "North",
        "product": "P",
        "units_sold": 10,
        "revenue": 100.0,
        "cost": 5.0,
        "lead_time_days": 5,
    }
    frame = pd.DataFrame([row])
    result = explain_anomalies(frame, [make_record(date=date_at(0))])  # type: ignore[list-item]
    insight = result["insights"][0]  # type: ignore[index]
    assert insight["localization"] is None
    assert insight["trend"] is None


# --- G. Determinism -------------------------------------------------------------


def test_repeated_explanations_are_identical():
    frame = make_gap_frame()
    records = [make_record(date=date_at(offset)) for offset in (8, 10, 11)]
    first = explain_anomalies(frame, records)
    second = explain_anomalies(frame, records)
    assert first == second


# --- H. Structural performance guard --------------------------------------------


def test_date_formatting_work_is_constant_across_anomaly_counts():
    """Precomputation happens once per dataset, not once per anomaly.

    Counts ``Timestamp.strftime`` invocations inside ``explain_anomalies``
    for one versus many anomalies on the same frame. The optimized path
    formats each dataset date exactly once during table construction;
    the pre-optimization path re-formatted the whole index per anomaly,
    so this count would grow with the anomaly list.
    """
    frame = make_gap_frame()
    records = [make_record(date=date_at(offset)) for offset in (8, 9, 10, 11)]

    def run_counting(anomaly_slice: list[dict[str, object]]) -> int:
        counter = {"strftime_calls": 0}
        original = pd.Timestamp.strftime

        def counting(self: pd.Timestamp, *args: object, **kwargs: object) -> object:
            counter["strftime_calls"] += 1
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        pd.Timestamp.strftime = counting  # type: ignore[method-assign, assignment]
        try:
            explain_anomalies(frame, anomaly_slice)
        finally:
            pd.Timestamp.strftime = original  # type: ignore[method-assign, assignment]
        return counter["strftime_calls"]

    baseline_count = run_counting(records[:1])
    full_count = run_counting(records)
    assert baseline_count > 0, "instrumentation did not intercept date formatting"
    assert full_count == baseline_count, (
        "date formatting scaled with anomaly count; per-anomaly "
        f"precomputation was reintroduced ({baseline_count} -> {full_count})"
    )
