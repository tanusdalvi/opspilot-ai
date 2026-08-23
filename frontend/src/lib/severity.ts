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

/** Human title for a KPI/metric key ("total_revenue" -> "Total Revenue"). */
export function metricTitle(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
