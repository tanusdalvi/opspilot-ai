/**
 * Signal intelligence transformations (presentation-only).
 *
 * Everything here is a pure, deterministic reshaping of backend
 * artifacts — anomaly records, severity counts, and the canonical
 * posture calculation reused from the backend (`app.ui.posture` via the
 * API serializer). No new business logic, no fabricated values.
 */

import { metricLabel } from "./labels";
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
}

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
  return {
    score: posture.score,
    band: posture.band,
    counts,
    totalSignals,
    prioritySignals,
    attentionNeeded,
    summary,
  };
}
