/**
 * Signal intelligence transformations (presentation-only).
 *
 * Everything here is a pure, deterministic reshaping of backend
 * artifacts — anomaly records, severity counts, and the canonical
 * posture calculation reused from the backend (`app.ui.posture` via the
 * API serializer). No new business logic, no fabricated values.
 */

import { METRIC_LABELS, metricLabel } from "./labels";
import type { AnomalyRecord } from "./types";

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export const SEVERITIES: readonly Severity[] = [
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
];

export interface SeverityCounts {
  CRITICAL: number;
  HIGH: number;
  MEDIUM: number;
  LOW: number;
}

function normalizeSeverity(raw: unknown): Severity {
  const value = String(raw ?? "").toUpperCase() as Severity;
  return SEVERITIES.includes(value) ? value : "LOW";
}

export function countBySeverity(anomalies: AnomalyRecord[]): SeverityCounts {
  const counts: SeverityCounts = {
    CRITICAL: 0,
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };
  for (const record of anomalies) counts[normalizeSeverity(record.severity)] += 1;
  return counts;
}

/** Severity weight used only for presentation ordering (matches backend rank). */
const WEIGHT: Record<Severity, number> = {
  CRITICAL: 4,
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
};

// --- Priority signals ---------------------------------------------------------------------------------

export function sortForPriority(
  anomalies: AnomalyRecord[],
): AnomalyRecord[] {
  return [...anomalies].sort((a, b) => {
    const bySeverity =
      WEIGHT[normalizeSeverity(b.severity)] - WEIGHT[normalizeSeverity(a.severity)];
    if (bySeverity !== 0) return bySeverity;
    // Stronger deviation first; dated signals before undated (newest date first).
    const deviation =
      Math.abs(Number(b.deviation_pct ?? 0)) - Math.abs(Number(a.deviation_pct ?? 0));
    if (deviation !== 0) return deviation;
    return String(b.date ?? "").localeCompare(String(a.date ?? ""));
  });
}

export function prioritySignals(
  anomalies: AnomalyRecord[],
  limit = 5,
): AnomalyRecord[] {
  return sortForPriority(anomalies).slice(0, limit);
}

/**
 * The single most important signal for the executive summary: highest
 * severity first, then strongest deviation, then most recent date.
 */
export function topConcernSignal(
  anomalies: AnomalyRecord[],
): AnomalyRecord | null {
  if (anomalies.length === 0) return null;
  return sortForPriority(anomalies)[0];
}

/** Observed date span across a set of signals ("Jun–Sep 2025" style). */
export function signalPeriodRange(
  anomalies: AnomalyRecord[],
): string | null {
  const dates = anomalies
    .map((record) => String(record.date ?? ""))
    .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    .sort();
  if (dates.length === 0) return null;
  const monthYear = (iso: string) => {
    const [year, month] = iso.split("-");
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    const index = Number(month) - 1;
    return index >= 0 && index < 12 ? `${months[index]} ${year}` : iso;
  };
  const first = monthYear(dates[0]);
  const last = monthYear(dates[dates.length - 1]);
  return first === last ? first : `${first} – ${last}`;
}

// --- Posture drivers ------------------------------------------------------------------------------------

export interface PostureDriver {
  metric: string;
  label: string;
  count: number;
  /** Σ severity weights — drives the ordering only. */
  weight: number;
}

/**
 * The metrics that contribute most to the current posture, derived from
 * the same deterministic records that feed the severity counts. Pure
 * presentation aggregation — no new scoring semantics.
 */
export function postureDrivers(
  anomalies: AnomalyRecord[],
  limit = 3,
): PostureDriver[] {
  const map = new Map<string, { count: number; weight: number }>();
  for (const record of anomalies) {
    const key = String(record.metric ?? "other");
    const entry = map.get(key) ?? { count: 0, weight: 0 };
    entry.count += 1;
    entry.weight += WEIGHT[normalizeSeverity(record.severity)];
    map.set(key, entry);
  }
  return [...map.entries()]
    .map(([metric, agg]) => ({
      metric,
      label: metricLabel(metric),
      count: agg.count,
      weight: agg.weight,
    }))
    .sort((a, b) => b.weight - a.weight || b.count - a.count)
    .slice(0, limit);
}

// --- Deviation semantics --------------------------------------------------------------------------------

/**
 * Metrics where running ABOVE expectation is the adverse direction
 * (cost pressure, fulfilment delay). All other tracked metrics are
 * revenue-like: falling short of expectation is what hurts.
 */
export const HIGHER_IS_ADVERSE = new Set(["cost", "lead_time_days"]);

export type DeviationDirection = "up" | "down";

export function deviationDirection(deviation: number): DeviationDirection {
  return deviation >= 0 ? "up" : "down";
}

/**
 * Whether a deviation moves the metric in its operationally adverse
 * direction. Deterministic from the metric identity — used only for
 * presentation tone, never for scoring.
 */
export function deviationIsAdverse(
  metric: unknown,
  deviation: number,
): boolean {
  if (!Number.isFinite(deviation) || deviation === 0) return false;
  const key = String(metric ?? "");
  if (HIGHER_IS_ADVERSE.has(key)) return deviation > 0;
  if (METRIC_LABELS[key]) return deviation < 0;
  return false;
}

/** Sign-correct display text: "+18.4%", "−6.2%" (real minus, not hyphen). */
export function formatDeviation(deviation: number): string {
  if (!Number.isFinite(deviation)) return "—";
  const magnitude = Math.abs(deviation).toFixed(1);
  if (deviation > 0) return `+${magnitude}%`;
  if (deviation < 0) return `−${magnitude}%`;
  return "0.0%";
}

// --- Grouping ------------------------------------------------------------------------------------------

export interface MetricSignalGroup {
  metric: string;
  label: string;
  total: number;
  counts: SeverityCounts;
  /** Most severe member drives the group accent. */
  topSeverity: Severity;
  members: AnomalyRecord[];
}

export function groupByMetric(anomalies: AnomalyRecord[]): MetricSignalGroup[] {
  const map = new Map<string, AnomalyRecord[]>();
  for (const record of anomalies) {
    const key = String(record.metric ?? "other");
    const bucket = map.get(key);
    if (bucket) bucket.push(record);
    else map.set(key, [record]);
  }
  const groups: MetricSignalGroup[] = [];
  for (const [metric, members] of map) {
    const counts = countBySeverity(members);
    const topSeverity = SEVERITIES.find((s) => counts[s] > 0) ?? "LOW";
    groups.push({
      metric,
      label: metricLabel(metric),
      total: members.length,
      counts,
      topSeverity,
      members: sortForPriority(members),
    });
  }
  // Groups ordered by most severe member, then size, then name.
  groups.sort(
    (a, b) =>
      WEIGHT[b.topSeverity] - WEIGHT[a.topSeverity] ||
      b.total - a.total ||
      a.label.localeCompare(b.label),
  );
  return groups;
}

// --- Filtering / sorting -------------------------------------------------------------------------------

export type SeverityFilter = "ALL" | Severity;

export function filterBySeverity(
  anomalies: AnomalyRecord[],
  filter: SeverityFilter,
): AnomalyRecord[] {
  if (filter === "ALL") return anomalies;
  return anomalies.filter((a) => normalizeSeverity(a.severity) === filter);
}

export type SignalSortKey = "severity" | "date" | "metric";

export function sortSignals(
  anomalies: AnomalyRecord[],
  key: SignalSortKey,
): AnomalyRecord[] {
  const copy = [...anomalies];
  switch (key) {
    case "severity":
      return sortForPriority(copy);
    case "date":
      return copy.sort(
        (a, b) => String(b.date ?? "").localeCompare(String(a.date ?? "")),
      );
    case "metric":
      return copy.sort((a, b) =>
        metricLabel(a.metric).localeCompare(metricLabel(b.metric)),
      );
  }
}

// --- Posture presentation ------------------------------------------------------------------------------

/**
 * Presentation mapping over the CANONICAL backend posture
 * (`app.ui.posture`: score + band already computed from severity
 * counts). This adds no competing algorithm — it derives display facts:
 * the priority workload and the distribution that produced the band.
 */
export interface PosturePresentation {
  score: number;
  band: string;
  counts: SeverityCounts;
  totalSignals: number;
  prioritySignals: number;
  attentionNeeded: boolean;
  summary: string;
  /** One-sentence causal explanation naming the driving severities. */
  why: string;
}

/**
 * Canonical band edges mirrored from the backend formula
 * (`app.ui.posture`: score = 100 - min(100, Σ weight·count), weights
 * CRITICAL 25 / HIGH 12 / MEDIUM 5 / LOW 2). Display-only duplication,
 * kept in sync so the UI can explain the scale honestly.
 */
export const POSTURE_SCALE: { min: number; label: string }[] = [
  { min: 80, label: "Steady" },
  { min: 60, label: "Moderate Attention" },
  { min: 0, label: "Needs Attention" },
];

export function presentPosture(
  posture: { score: number; band: string } | null | undefined,
  anomalies: AnomalyRecord[],
): PosturePresentation | null {
  if (!posture) return null;
  const counts = countBySeverity(anomalies);
  const totalSignals = anomalies.length;
  const prioritySignals = counts.CRITICAL + counts.HIGH;
  const attentionNeeded = prioritySignals > 0;
  const summary = attentionNeeded
    ? `${prioritySignals} high-priority signal${prioritySignals === 1 ? "" : "s"} require review`
    : totalSignals > 0
      ? "No critical or high signals — routine monitoring applies"
      : "No operational signals detected";
  const drivers: string[] = [];
  if (counts.CRITICAL > 0)
    drivers.push(
      `${counts.CRITICAL} critical signal${counts.CRITICAL === 1 ? "" : "s"}`,
    );
  if (counts.HIGH > 0)
    drivers.push(`${counts.HIGH} high-severity signal${counts.HIGH === 1 ? "" : "s"}`);
  const why = drivers.length
    ? `Operational posture is elevated because ${drivers.join(" and ")} ${drivers.length === 1 ? "is" : "are"} active.`
    : totalSignals > 0
      ? "Only low and medium-severity signals were detected — nothing demands immediate action."
      : "No signals crossed the detection thresholds in the latest run.";
  return {
    score: posture.score,
    band: posture.band,
    counts,
    totalSignals,
    prioritySignals,
    attentionNeeded,
    summary,
    why,
  };
}
