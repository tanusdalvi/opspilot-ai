/**
 * Data Explorer presentation logic (pure, deterministic).
 *
 * Recommends sensible chart configurations from the preview column
 * kinds and reshapes preview rows into chart-ready series. No business
 * values are computed here - every number comes from the dataset.
 */

import type { ColumnKind, DatasetPreview, PreviewColumn } from "./types";

export type ChartType =
  | "table"
  | "line"
  | "area"
  | "bar"
  | "scatter"
  | "histogram"
  | "donut";

export type Aggregation = "sum" | "average" | "count";

export const AGGREGATION_LABELS: Record<Aggregation, string> = {
  sum: "Sum",
  average: "Average",
  count: "Count",
};

export interface ExplorerConfig {
  chartType: ChartType;
  x: string | null;
  y: string | null;
  aggregation: Aggregation;
}

// --- Column helpers -----------------------------------------------------------------------------------

export function columnsOfKind(
  columns: PreviewColumn[],
  kind: ColumnKind,
): PreviewColumn[] {
  return columns.filter((c) => c.kind === kind);
}

/**
 * Sensible default configuration for a dataset. Priority:
 * date + numeric -> area trend; category + numeric -> bar;
 * two numerics -> scatter; single numeric -> histogram;
 * category-only -> donut; otherwise table.
 */
export function recommendConfig(
  preview: DatasetPreview,
): ExplorerConfig {
  const dates = columnsOfKind(preview.columns, "date");
  const numerics = columnsOfKind(preview.columns, "numeric");
  const categoricals = columnsOfKind(preview.columns, "categorical");

  if (dates.length > 0 && numerics.length > 0) {
    return {
      chartType: "area",
      x: dates[0].name,
      y: numerics[0].name,
      aggregation: "sum",
    };
  }
  if (categoricals.length > 0 && numerics.length > 0) {
    return {
      chartType: "bar",
      x: categoricals[0].name,
      y: numerics[0].name,
      aggregation: "sum",
    };
  }
  if (numerics.length >= 2) {
    return {
      chartType: "scatter",
      x: numerics[0].name,
      y: numerics[1].name,
      aggregation: "sum",
    };
  }
  if (numerics.length === 1) {
    return {
      chartType: "histogram",
      x: numerics[0].name,
      y: null,
      aggregation: "count",
    };
  }
  if (categoricals.length > 0) {
    return {
      chartType: "donut",
      x: categoricals[0].name,
      y: null,
      aggregation: "count",
    };
  }
  return { chartType: "table", x: null, y: null, aggregation: "sum" };
}

/** Chart types that make sense for the current axis selection. */
export function allowedChartTypes(
  columns: PreviewColumn[],
  x: string | null,
  y: string | null,
): ChartType[] {
  const kindOf = (name: string | null): ColumnKind | null =>
    columns.find((c) => c.name === name)?.kind ?? null;
  const xKind = kindOf(x);
  const yKind = kindOf(y);

  if (xKind === "date" && yKind === "numeric") return ["line", "area", "bar"];
  if (xKind === "categorical" && yKind === "numeric")
    return ["bar", "line", "donut"];
  if (xKind === "numeric" && yKind === "numeric") return ["scatter"];
  if ((xKind === "numeric" || xKind === "date") && y === null)
    return ["histogram"];
  if (xKind === "categorical" && y === null) return ["donut", "bar"];
  return ["table"];
}

// --- Reshaping ------------------------------------------------------------------------------------------

export interface SeriesPoint {
  label: string;
  value: number;
}

function numericValue(row: Record<string, unknown>, key: string | null): number {
  if (!key) return 0;
  const n = Number(row[key]);
  return Number.isFinite(n) ? n : 0;
}

function labelValue(row: Record<string, unknown>, key: string | null): string {
  if (!key) return "";
  const raw = row[key];
  return raw === null || raw === undefined ? "-" : String(raw);
}

/**
 * Aggregate rows into category/value pairs. Counting ignores Y entirely;
 * sum/average use the numeric Y column. Sorted by magnitude descending,
 * with long tails folded into an explicit "Other" slice.
 */
export function aggregateByCategory(
  rows: Record<string, unknown>[],
  x: string,
  y: string | null,
  aggregation: Aggregation,
  cap = 30,
): SeriesPoint[] {
  const buckets = new Map<string, number[]>();
  for (const row of rows) {
    const label = labelValue(row, x);
    const list = buckets.get(label);
    if (list) list.push(numericValue(row, y));
    else buckets.set(label, [numericValue(row, y)]);
  }
  const points: SeriesPoint[] = [...buckets.entries()].map(([label, values]) => ({
    label,
    value:
      aggregation === "count"
        ? values.length
        : aggregation === "average"
          ? values.reduce((a, b) => a + b, 0) / values.length
          : values.reduce((a, b) => a + b, 0),
  }));
  points.sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  if (points.length <= cap) return points;
  const kept = points.slice(0, cap - 1);
  const restValue =
    aggregation === "average"
      ? points.slice(cap - 1).reduce((a, p) => a + p.value, 0) /
        points.slice(cap - 1).length
      : points.slice(cap - 1).reduce((a, p) => a + p.value, 0);
  kept.push({ label: "Other", value: restValue });
  return kept;
}

/** Time-ordered series for a date X axis (dates ISO strings from the API). */
export function seriesOverTime(
  rows: Record<string, unknown>[],
  dateColumn: string,
  y: string | null,
  aggregation: Aggregation,
): { dates: string[]; values: number[] } {
  const buckets = new Map<string, number[]>();
  for (const row of rows) {
    const label = String(row[dateColumn] ?? "").slice(0, 10);
    const list = buckets.get(label);
    if (list) list.push(numericValue(row, y));
    else buckets.set(label, [numericValue(row, y)]);
  }
  const entries = [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b));
  return {
    dates: entries.map(([label]) => label),
    values: entries.map(([, values]) =>
      aggregation === "count"
        ? values.length
        : aggregation === "average"
          ? values.reduce((a, b) => a + b, 0) / values.length
          : values.reduce((a, b) => a + b, 0),
    ),
  };
}

export interface ScatterPoint {
  x: number;
  y: number;
}

export function scatterPoints(
  rows: Record<string, unknown>[],
  x: string,
  y: string,
): ScatterPoint[] {
  const points: ScatterPoint[] = [];
  for (const row of rows) {
    const px = Number(row[x]);
    const py = Number(row[y]);
    if (Number.isFinite(px) && Number.isFinite(py)) points.push({ x: px, y: py });
  }
  return points;
}

/** Fixed-count histogram buckets over the finite values of one column. */
export function histogram(
  rows: Record<string, unknown>[],
  column: string,
  binCount = 20,
): SeriesPoint[] {
  const values: number[] = [];
  for (const row of rows) {
    const n = Number(row[column]);
    if (Number.isFinite(n)) values.push(n);
  }
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ label: `${formatTick(min)}`, value: values.length }];
  const bins = Math.max(2, Math.min(binCount, 50));
  const width = (max - min) / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of values) {
    const index = Math.min(bins - 1, Math.floor((v - min) / width));
    counts[index] += 1;
  }
  return counts.map((count, i) => ({
    label: `${formatTick(min + i * width)}`,
    value: count,
  }));
}

function formatTick(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString();
  return Number(value.toPrecision(3)).toLocaleString();
}
