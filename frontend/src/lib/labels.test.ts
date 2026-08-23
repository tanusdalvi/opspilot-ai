import { describe, expect, it } from "vitest";
import {
  anomalyTypeLabel,
  evidenceEntryTitle,
  evidenceKind,
  kpiMeta,
  metricLabel,
  periodChangeLabel,
  scopeLabel,
  signalTitle,
} from "./labels";

describe("labels — metrics", () => {
  it("maps every detector metric to human language", () => {
    expect(metricLabel("units_sold")).toBe("Units Sold");
    expect(metricLabel("lead_time_days")).toBe("Lead Time");
    expect(metricLabel("profit_margin_pct")).toBe("Profit Margin %");
  });

  it("falls back to humanized text for unknown keys", () => {
    expect(metricLabel("mystery_field")).toBe("Mystery Field");
  });
});

describe("labels — anomaly records", () => {
  it("translates detector types without inventing causes", () => {
    expect(anomalyTypeLabel("daily_spike")).toBe("Daily Spike Detected");
    expect(anomalyTypeLabel("entity_outlier_low")).toBe(
      "Outlier Below Peers",
    );
    expect(anomalyTypeLabel(undefined)).toBe("Detected Signal");
  });

  it("builds signal titles only from the record's own fields", () => {
    expect(signalTitle({ type: "daily_spike", metric: "revenue" })).toBe(
      "Daily Spike Detected · Revenue",
    );
  });

  it("maps scopes to operational language", () => {
    expect(scopeLabel("daily")).toContain("daily totals");
    expect(scopeLabel("region")).toBe("Region level");
  });
});

describe("labels — KPIs", () => {
  it("covers all canonical analytics_service KPI keys", () => {
    for (const key of [
      "total_units_sold",
      "total_revenue",
      "total_cost",
      "total_profit",
      "profit_margin_pct",
      "average_daily_units_sold",
      "average_daily_revenue",
      "average_daily_cost",
      "average_daily_profit",
      "average_lead_time_days",
      "unique_regions",
      "unique_products",
      "date_range",
    ]) {
      expect(kpiMeta(key).title).not.toMatch(/_/);
    }
  });

  it("marks margin as percent and lead time as days", () => {
    expect(kpiMeta("profit_margin_pct").kind).toBe("percent");
    expect(kpiMeta("average_lead_time_days").kind).toBe("days");
  });
});

describe("labels — period comparison", () => {
  it("uses backend change field names", () => {
    expect(periodChangeLabel("units_change_pct")).toBe("Units Sold");
    expect(periodChangeLabel("margin_change_pct")).toBe("Profit Margin");
  });
});

describe("labels — evidence pack", () => {
  it("groups every known kind into a tab bucket", () => {
    expect(evidenceKind("kpi").group).toBe("kpis");
    expect(evidenceKind("anomaly").group).toBe("anomalies");
    expect(evidenceKind("correlation").group).toBe("correlations");
    expect(evidenceKind("group").group).toBe("groups");
  });

  it("never exposes the raw id as the entry title", () => {
    const title = evidenceEntryTitle({
      label: "Revenue on 2025-03-14",
      kind: "anomaly",
    });
    expect(title).not.toMatch(/^E\d+/);
    expect(title).toBe("Revenue on 2025-03-14");
  });

  it("derives a title from kind + field when label is missing", () => {
    expect(
      evidenceEntryTitle({ kind: "kpi", field: "total_revenue" }),
    ).toBe("Total Revenue");
    expect(
      evidenceEntryTitle({ kind: "period_change", field: "revenue_change_pct" }),
    ).toBe("Revenue");
  });
});
