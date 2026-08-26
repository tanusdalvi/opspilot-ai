/**
 * Semantic display-mapping layer — the ONLY place internal field names,
 * evidence kinds, anomaly types, and metric identifiers are translated
 * into human-readable language.
 *
 * Source of truth for every mapping below:
 *   - services/analytics_service.py  (KPI keys)
 *   - services/anomaly_service.py    (SUPPORTED_METRICS, record types/scopes)
 *   - agent/schemas.py               (evidence entry kinds / change fields)
 *   - services/insight_service.py    (LOCALIZATION_DIMENSIONS)
 */

import { metricTitle } from "./severity";

// --- Metrics ----------------------------------------------------------------------------------------

export const METRIC_LABELS: Record<string, string> = {
  units_sold: "Units Sold",
  revenue: "Revenue",
  cost: "Cost",
  lead_time_days: "Lead Time",
  profit: "Profit",
  profit_margin_pct: "Profit Margin %",
};

export function metricLabel(raw: unknown): string {
  const key = String(raw ?? "");
  return METRIC_LABELS[key] ?? metricTitle(key);
}

/** Derive available trend metrics from daily_trends columns. */
export function availableTrendMetrics(dailyTrends: Record<string, unknown>[] | null | undefined): string[] {
  if (!dailyTrends || dailyTrends.length === 0) return [];
  const metricColumns = Object.keys(dailyTrends[0]).filter(k => k !== "date");
  return metricColumns;
}

// --- KPI cards ---------------------------------------------------------------------------------------

export interface KpiMeta {
  title: string;
  description: string;
  /** percent values render with one decimal; counts use compact integers */
  kind: "percent" | "count" | "days" | "money-like";
}

export const KPI_META: Record<string, KpiMeta> = {
  total_units_sold: {
    title: "Total Units Sold",
    description: "Units across the full analysis window.",
    kind: "count",
  },
  total_revenue: {
    title: "Total Revenue",
    description: "Revenue across the full analysis window.",
    kind: "money-like",
  },
  total_cost: {
    title: "Total Cost",
    description: "Direct cost across the full analysis window.",
    kind: "money-like",
  },
  total_profit: {
    title: "Total Profit",
    description: "Revenue minus cost over the full window.",
    kind: "money-like",
  },
  profit_margin_pct: {
    title: "Profit Margin",
    description: "Profit as a share of revenue.",
    kind: "percent",
  },
  average_daily_units_sold: {
    title: "Avg Daily Units",
    description: "Units sold per active day.",
    kind: "count",
  },
  average_daily_revenue: {
    title: "Avg Daily Revenue",
    description: "Revenue per active day.",
    kind: "money-like",
  },
  average_daily_cost: {
    title: "Avg Daily Cost",
    description: "Cost per active day.",
    kind: "money-like",
  },
  average_daily_profit: {
    title: "Avg Daily Profit",
    description: "Profit per active day.",
    kind: "money-like",
  },
  average_lead_time_days: {
    title: "Avg Lead Time",
    description: "Mean fulfillment lead time.",
    kind: "days",
  },
  unique_regions: {
    title: "Regions",
    description: "Distinct regions represented in the dataset.",
    kind: "count",
  },
  unique_products: {
    title: "Products",
    description: "Distinct products represented in the dataset.",
    kind: "count",
  },
};

export function kpiMeta(key: string): KpiMeta {
  return (
    KPI_META[key] ?? {
      title: metricTitle(key),
      description: "",
      kind: key.includes("pct") ? "percent" : key.includes("days") ? "days" : key.includes("count") || key.startsWith("total") || key.startsWith("unique") || key.startsWith("average_daily") ? "count" : "money-like",
    }
  );
}

// --- Period comparison -------------------------------------------------------------------------------

const PERIOD_CHANGE_LABELS: Record<string, string> = {
  units_change_pct: "Units Sold",
  revenue_change_pct: "Revenue",
  cost_change_pct: "Cost",
  profit_change_pct: "Profit",
  margin_change_pct: "Profit Margin",
  lead_time_change_pct: "Lead Time",
};

export function periodChangeLabel(key: string): string {
  return PERIOD_CHANGE_LABELS[key] ?? metricTitle(key);
}

// --- Anomaly records ----------------------------------------------------------------------------------

const ANOMALY_TYPE_LABELS: Record<string, string> = {
  daily_spike: "Daily Spike Detected",
  daily_drop: "Daily Drop Detected",
  entity_outlier_high: "Outlier Above Peers",
  entity_outlier_low: "Outlier Below Peers",
};

export function anomalyTypeLabel(type: unknown): string {
  return ANOMALY_TYPE_LABELS[String(type ?? "")] ?? "Detected Signal";
}

const SCOPE_LABELS: Record<string, string> = {
  daily: "Dataset-wide · daily totals",
  region: "Region level",
  product: "Product level",
};

export function scopeLabel(scope: unknown): string {
  return SCOPE_LABELS[String(scope ?? "")] ?? metricTitle(String(scope ?? ""));
}

/**
 * Human sentence for an anomaly record — assembled ONLY from its own
 * deterministic fields (type/metric/date/entity/deviation). No causal
 * language is ever invented here.
 */
export function signalTitle(record: {
  type?: unknown;
  metric?: unknown;
}): string {
  return `${anomalyTypeLabel(record.type)} · ${metricLabel(record.metric)}`;
}

const TYPE_DIRECTION: Record<string, "up" | "down"> = {
  daily_spike: "up",
  entity_outlier_high: "up",
  daily_drop: "down",
  entity_outlier_low: "down",
};

/** ISO date -> "15 Dec 2025"; returns the input when not parseable. */
function shortDate(value: unknown): string | null {
  const raw = String(value ?? "");
  const date = new Date(raw);
  if (!/^\d{4}-\d{2}-\d{2}/.test(raw) || Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * One-sentence factual reading of a signal: what moved, which way,
 * by how much, and against what comparison. Uses only record fields —
 * no diagnosis, no cause, no recommendation.
 */
export function signalInterpretation(
  record: AnomalyLike & { deviation_pct?: unknown },
): string {
  const type = String(record.type ?? "");
  const direction = TYPE_DIRECTION[type] ?? "up";
  const verb = direction === "up" ? "above" : "below";
  const moved = direction === "up" ? "rose" : "fell";
  const deviation = Math.abs(Number(record.deviation_pct ?? 0)).toFixed(1);
  const metric = metricLabel(record.metric);
  const subject = record.entity
    ? `${String(record.entity)}'s ${metric.toLowerCase()}`
    : `Daily ${metric.toLowerCase()}`;
  switch (type) {
    case "entity_outlier_high":
    case "entity_outlier_low":
      return `${subject} sits ${deviation}% ${verb} comparable peers for the same period.`;
    default:
      return `${subject} ${moved} ${deviation}% ${verb} its expected operating range${
        shortDate(record.date) ? ` on ${shortDate(record.date)}` : ""
      }.`;
  }
}

/** Minimal structural contract shared by anomaly records across pages. */
export interface AnomalyLike {
  type?: unknown;
  metric?: unknown;
  entity?: unknown;
  date?: unknown;
}

// --- Evidence pack ------------------------------------------------------------------------------------

export interface EvidenceKindMeta {
  label: string;
  group: "kpis" | "anomalies" | "correlations" | "groups" | "other";
}

const EVIDENCE_KINDS: Record<string, EvidenceKindMeta> = {
  kpi: { label: "Verified KPI", group: "kpis" },
  period_change: { label: "Period Change", group: "kpis" },
  performer: { label: "Performer", group: "kpis" },
  anomaly: { label: "Detected Anomaly", group: "anomalies" },
  correlation: { label: "Correlation", group: "correlations" },
  group: { label: "Signal Cluster", group: "groups" },
};

export function evidenceKind(kind: unknown): EvidenceKindMeta {
  return EVIDENCE_KINDS[String(kind ?? "")] ?? {
    label: metricTitle(String(kind ?? "Fact")),
    group: "other",
  };
}

/**
 * Display heading for an evidence entry. The citable id (E1, E33, …) is
 * development metadata and is never used as the user-facing label; it is
 * available separately via the returned `id` for grounding cross-refs.
 */
export function evidenceEntryTitle(entry: {
  label?: unknown;
  kind?: unknown;
  field?: unknown;
}): string {
  if (typeof entry.label === "string" && entry.label.trim()) {
    return entry.label;
  }
  const kind = String(entry.kind ?? "");
  if (kind === "kpi") return kpiMeta(String(entry.field ?? "")).title;
  if (kind === "period_change") {
    return periodChangeLabel(String(entry.field ?? ""));
  }
  return metricLabel(entry.field);
}
