/** Severity semantics: never color-only (icon + label + tone). */

export type Tone = "danger" | "warn" | "info" | "ok" | "muted";

export interface SeverityStyle {
  tone: Tone;
  label: string;
  weight: number;
}

const SEVERITY: Record<string, SeverityStyle> = {
  CRITICAL: { tone: "danger", label: "Critical", weight: 4 },
  HIGH: { tone: "danger", label: "High", weight: 3 },
  MEDIUM: { tone: "warn", label: "Medium", weight: 2 },
  LOW: { tone: "info", label: "Low", weight: 1 },
};

export function severity(raw: string | undefined | null): SeverityStyle {
  if (!raw) return SEVERITY.LOW;
  return (
    SEVERITY[String(raw).toUpperCase()] ?? {
      tone: "muted",
      label: String(raw),
      weight: 0,
    }
  );
}

export const SEVERITY_ORDER: readonly string[] = [
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
];

/** Status bands for recommendation lifecycle. */
export function statusTone(status: string): Tone {
  switch (String(status).toUpperCase()) {
    case "APPROVED":
      return "ok";
    case "REJECTED":
      return "danger";
    case "CHANGES_REQUESTED":
      return "warn";
    case "PENDING":
      return "info";
    case "EXPIRED":
      return "muted";
    default:
      return "muted";
  }
}

const STATUS_LABELS: Record<string, string> = {
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CHANGES_REQUESTED: "Changes Requested",
  PENDING: "Pending",
  EXPIRED: "Expired",
};

/** Human label for a recommendation/review lifecycle status. */
export function statusLabel(status: unknown): string {
  const key = String(status ?? "").toUpperCase();
  return STATUS_LABELS[key] ?? metricTitle(String(status ?? ""));
}

const PRIORITY_LABELS: Record<string, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
};

/** Human label for a recommendation priority band. */
export function priorityLabel(priority: unknown): string {
  const key = String(priority ?? "").toUpperCase();
  return PRIORITY_LABELS[key] ?? metricTitle(String(priority ?? ""));
}

/** Human title for a KPI/metric key ("total_revenue" -> "Total Revenue"). */
export function metricTitle(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
