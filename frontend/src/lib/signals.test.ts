import { describe, expect, it } from "vitest";
import {
  countBySeverity,
  filterBySeverity,
  groupByMetric,
  presentPosture,
  prioritySignals,
  sortSignals,
} from "./signals";
import type { AnomalyRecord, Posture } from "./types";

function record(overrides: Partial<AnomalyRecord>): AnomalyRecord {
  return { ...overrides };
}

const SAMPLE: AnomalyRecord[] = [
  record({ type: "daily_spike", metric: "revenue", severity: "CRITICAL", date: "2025-03-14", deviation_pct: 41.2 }),
  record({ type: "daily_spike", metric: "revenue", severity: "HIGH", date: "2025-04-02", deviation_pct: 22.5 }),
  record({ type: "entity_outlier_high", metric: "cost", severity: "MEDIUM", entity: "North", scope: "region", deviation_pct: 12.0 }),
  record({ type: "entity_outlier_low", metric: "units_sold", severity: "HIGH", entity: "SKU-9", scope: "product", deviation_pct: -18.4 }),
];

describe("countBySeverity", () => {
  it("counts real detections per severity", () => {
    const counts = countBySeverity(SAMPLE);
    expect(counts).toEqual({ CRITICAL: 1, HIGH: 2, MEDIUM: 1, LOW: 0 });
    expect(countBySeverity([])).toEqual({
      CRITICAL: 0,
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
    });
  });
});

describe("prioritySignals", () => {
  it("returns highest-severity records first", () => {
    const priority = prioritySignals(SAMPLE);
    expect(priority[0].severity).toBe("CRITICAL");
    expect(priority.length).toBeLessThanOrEqual(SAMPLE.length);
  });

  it("is empty when nothing was detected", () => {
    expect(prioritySignals([])).toEqual([]);
  });
});

describe("groupByMetric", () => {
  it("consolidates related detections per metric with counts", () => {
    const groups = groupByMetric(SAMPLE);
    const revenue = groups.find((g) => g.metric === "revenue");
    expect(revenue?.total).toBe(2);
    expect(revenue?.counts.CRITICAL).toBe(1);
    expect(revenue?.topSeverity).toBe("CRITICAL");
  });
});

describe("filter + sort", () => {
  it("filters by severity exactly", () => {
    expect(filterBySeverity(SAMPLE, "HIGH").length).toBe(2);
    expect(filterBySeverity(SAMPLE, "ALL").length).toBe(4);
  });

  it("sorts by date and metric deterministically", () => {
    const byDate = sortSignals(SAMPLE, "date").map((r) => r.date ?? null);
    expect(byDate).toEqual(["2025-04-02", "2025-03-14", null, null]);
    const byMetric = sortSignals(SAMPLE, "metric").map((r) => r.metric);
    expect(byMetric).toEqual([...byMetric].sort());
  });
});

describe("presentPosture", () => {
  it("passes the canonical backend score/band through untouched", () => {
    const backend: Posture = { score: 42, band: "NEEDS ATTENTION", tone: "danger" };
    const presentation = presentPosture(backend, SAMPLE);
    expect(presentation?.score).toBe(42);
    expect(presentation?.band).toBe("NEEDS ATTENTION");
    expect(presentation?.counts.HIGH).toBe(2);
    expect(presentation?.attentionNeeded).toBe(true);
  });

  it("recomputes the band presentation only when posture is absent", () => {
    const presentation = presentPosture(null, SAMPLE);
    // Backend is the single source of truth — without it there is no posture.
    expect(presentation).toBeNull();
  });
});
