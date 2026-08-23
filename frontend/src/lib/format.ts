/** Deterministic display formatters (no fabricated precision). */

import type { KpiMeta } from "./labels";

export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${trim(value / 1e9)}B`;
  if (abs >= 1e6) return `${trim(value / 1e6)}M`;
  if (abs >= 1e3) return `${trim(value / 1e3)}K`;
  return trim(value);
}

function trim(value: number): string {
  const fixed = Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1);
  return fixed.replace(/\.0$/, "");
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
    value,
  );
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export function formatDateTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "2025-12-15" -> "15 Dec 2025"; returns input untouched when not a date. */
export function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatKpiValue(value: number, kind: KpiMeta["kind"]): string {
  if (!Number.isFinite(value)) return "—";
  switch (kind) {
    case "percent":
      return `${trim(value)}%`;
    case "days":
      return `${trim(value)} d`;
    case "count":
      return Number.isInteger(value)
        ? new Intl.NumberFormat("en-US").format(value)
        : formatCompact(value);
    case "money-like":
      return formatCompact(value);
  }
}

export function dayBucket(iso: string, today = new Date()): "Today" | "Yesterday" | "Earlier" {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Earlier";
  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round(
    (startOfDay(today) - startOfDay(date)) / 86_400_000,
  );
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return "Earlier";
}
