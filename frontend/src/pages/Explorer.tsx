import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Compass, Table2 } from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { SegmentedControl } from "../components/ui/Controls";
import {
  DonutChart,
  GroupedBars,
  HistogramChart,
  ScatterPlot,
  TrendArea,
} from "../components/charts/Charts";
import {
  AGGREGATION_LABELS,
  aggregateByCategory,
  allowedChartTypes,
  histogram,
  recommendConfig,
  scatterPoints,
  seriesOverTime,
  type Aggregation,
  type ChartType,
} from "../lib/explorer";
import { formatNumber } from "../lib/format";
import type { ColumnKind, DatasetPreview } from "../lib/types";

const PAGE_SIZE = 25;

const CHART_TYPE_LABELS: Record<Exclude<ChartType, "table">, string> = {
  line: "Line",
  area: "Area",
  bar: "Bars",
  scatter: "Scatter",
  histogram: "Histogram",
  donut: "Share",
};

export default function Explorer() {
  const { system } = useWorkspace();
  const datasetLoaded = system?.dataset != null;

  const preview = useQuery({
    queryKey: ["dataset-preview"],
    queryFn: () => api<DatasetPreview>("/api/datasets/preview?rows=1000"),
    enabled: datasetLoaded,
    staleTime: 60_000,
  });

  const [recommendedMode, setRecommendedMode] = useState(true);
  const [chartType, setChartType] = useState<ChartType>("table");
  const [x, setX] = useState<string | null>(null);
  const [y, setY] = useState<string | null>(null);
  const [aggregation, setAggregation] = useState<Aggregation>("sum");

  const recommended = useMemo(
    () => (preview.data ? recommendConfig(preview.data) : null),
    [preview.data],
  );
  const allowed = useMemo(
    () =>
      preview.data
        ? allowedChartTypes(preview.data.columns, x, y)
        : (["table"] as ChartType[]),
    [preview.data, x, y],
  );

  // Adopt the recommendation as soon as a preview arrives.
  useEffect(() => {
    if (!recommended || !recommendedMode) return;
    setChartType(recommended.chartType);
    setX(recommended.x);
    setY(recommended.y);
    setAggregation(recommended.aggregation);
  }, [recommended, recommendedMode]);

  if (!datasetLoaded) {
    return (
      <div>
        <PageHeader eyebrow="Data" title="Data Explorer" />
        <EmptyState
          icon={<Compass size={20} />}
          title="No dataset to explore"
          body="Load the bundled demo or upload your own CSV first — every table and chart here is generated directly from the active dataset."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  if (preview.isError) {
    return (
      <div>
        <PageHeader eyebrow="Data" title="Data Explorer" />
        <EmptyState
          icon={<Compass size={20} />}
          title="Could not load the dataset preview"
          body="The explorer could not read a preview of the active dataset. The dataset itself is still loaded — retry, or return to the Data workspace."
          action={
            <div className="flex gap-2">
              <Button onClick={() => preview.refetch()}>Retry</Button>
              <Link to="/data">
                <Button variant="ghost">Open Data Workspace</Button>
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  if (preview.isLoading || !preview.data) {
    return (
      <div>
        <PageHeader eyebrow="Data" title="Data Explorer" />
        <SkeletonPanel lines={6} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Data"
        title="Data Explorer"
        description="Explore the active dataset directly — tables and charts built from its own rows, independent of analysis artifacts."
      />

      <DatasetSummary preview={preview.data} />

      <Panel className="mt-4 p-5">
        <SectionHeading
          icon={<Compass size={15} className="text-accent" aria-hidden />}
          title={recommendedMode ? "Recommended view" : "Custom view"}
          caption={
            recommendedMode
              ? "Chosen automatically from this dataset's column types."
              : "Pick any axes that fit — chart choices adapt to column types."
          }
          actions={
            <SegmentedControl
              ariaLabel="View mode"
              options={[
                { value: "recommended", label: "Recommended" },
                { value: "custom", label: "Custom" },
              ]}
              value={recommendedMode ? "recommended" : "custom"}
              onChange={(mode) => setRecommendedMode(mode === "recommended")}
            />
          }
        />
        {!recommendedMode && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted">
                Chart
              </span>
              <SegmentedControl
                ariaLabel="Chart type"
                options={allowed.map((t) => ({
                  value: t,
                  label:
                    t === "table"
                      ? "Table"
                      : CHART_TYPE_LABELS[t as Exclude<ChartType, "table">],
                }))}
                value={allowed.includes(chartType) ? chartType : allowed[0]}
                onChange={(next) => setChartType(next)}
              />
            </div>
            <AxisSelect
              label="X axis"
              value={x}
              onChange={(next) => {
                setX(next);
                syncChartType(preview.data!, next, y, setChartType);
              }}
              columns={orderedChoices(preview.data)}
            />
            {(chartType === "line" ||
              chartType === "area" ||
              chartType === "bar" ||
              chartType === "scatter") && (
              <AxisSelect
                label="Y axis"
                value={y}
                onChange={(next) => {
                  setY(next);
                  syncChartType(preview.data!, x, next, setChartType);
                }}
                columns={orderedChoices(preview.data)}
              />
            )}
            {chartType !== "histogram" && chartType !== "donut" && (
              <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                Aggregate
                <select
                  value={aggregation}
                  onChange={(e) =>
                    setAggregation(e.target.value as Aggregation)
                  }
                  className="rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm font-medium normal-case tracking-normal text-text"
                >
                  {(Object.keys(AGGREGATION_LABELS) as Aggregation[]).map(
                    (key) => (
                      <option key={key} value={key}>
                        {AGGREGATION_LABELS[key]}
                      </option>
                    ),
                  )}
                </select>
              </label>
            )}
          </div>
        )}

        {recommendedMode ? (
          <RecommendedBody
            preview={preview.data}
            config={recommended!}
          />
        ) : (
          <CustomBody
            preview={preview.data}
            chartType={allowed.includes(chartType) ? chartType : allowed[0]}
            x={x}
            y={y}
            aggregation={aggregation}
          />
        )}
      </Panel>
    </div>
  );
}

// --- Summary ---------------------------------------------------------------------------------------------

function DatasetSummary({ preview }: { preview: DatasetPreview }) {
  const kinds = preview.columns.map((c) => c.kind);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <SummaryCard label="Rows" value={formatNumber(preview.total_rows)} />
      <SummaryCard label="Columns" value={formatNumber(preview.columns.length)} />
      <SummaryCard
        label="Numeric fields"
        value={formatNumber(kinds.filter((k) => k === "numeric").length)}
      />
      <SummaryCard
        label="Category fields"
        value={formatNumber(kinds.filter((k) => k === "categorical").length)}
      />
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-4 py-3">
      <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
        {label}
      </p>
      <p className="num mt-1 text-lg font-bold text-text">{value}</p>
    </div>
  );
}

// --- Recommended ------------------------------------------------------------------------------------------

function RecommendedBody({
  preview,
  config,
}: {
  preview: DatasetPreview;
  config: NonNullable<ReturnType<typeof recommendConfig>>;
}) {
  if (config.chartType === "table") {
    return <PreviewTable preview={preview} />;
  }
  if (config.chartType === "area" && config.x && config.y) {
    const series = seriesOverTime(preview.rows, config.x, config.y, config.aggregation);
    return (
      <div className="pt-4">
        <TrendArea
          dates={series.dates}
          values={series.values}
          metricLabel={`${AGGREGATION_LABELS[config.aggregation]} of ${config.y}`}
        />
      </div>
    );
  }
  if (config.chartType === "bar" && config.x) {
    const points = aggregateByCategory(
      preview.rows,
      config.x,
      config.y,
      config.aggregation,
    );
    return (
      <div className="pt-4">
        <GroupedBars
          categories={points.map((p) => p.label)}
          series={[{ name: config.y ?? "Count", values: points.map((p) => p.value) }]}
        />
      </div>
    );
  }
  if (config.chartType === "scatter" && config.x && config.y) {
    return (
      <div className="pt-4">
        <ScatterPlot
          points={scatterPoints(preview.rows, config.x, config.y)}
          xLabel={config.x}
          yLabel={config.y}
        />
      </div>
    );
  }
  if (config.chartType === "histogram" && config.x) {
    return (
      <div className="pt-4">
        <HistogramChart
          buckets={histogram(preview.rows, config.x)}
          valueLabel={config.x}
        />
      </div>
    );
  }
  if (config.chartType === "donut" && config.x) {
    const slices = aggregateByCategory(preview.rows, config.x, null, "count", 12);
    return (
      <div className="pt-4">
        <DonutChart slices={slices} />
      </div>
    );
  }
  return <PreviewTable preview={preview} />;
}

// --- Custom -----------------------------------------------------------------------------------------------

function CustomBody({
  preview,
  chartType,
  x,
  y,
  aggregation,
}: {
  preview: DatasetPreview;
  chartType: ChartType;
  x: string | null;
  y: string | null;
  aggregation: Aggregation;
}) {
  const allowed = allowedChartTypes(preview.columns, x, y);
  if (!allowed.includes(chartType)) {
    return (
      <Panel className="mt-4 border-dashed p-6 text-center text-sm text-text-2">
        This combination does not support that chart style.{" "}
        {allowed.includes("table") && "Try the Table view below."}
      </Panel>
    );
  }

  if (chartType === "table" || !x) return <PreviewTable preview={preview} />;
  if ((chartType === "line" || chartType === "area") && x && y) {
    const series = seriesOverTime(preview.rows, x, y, aggregation);
    return (
      <div className="pt-4">
        <TrendArea
          dates={series.dates}
          values={series.values}
          metricLabel={`${AGGREGATION_LABELS[aggregation]} of ${y}`}
        />
      </div>
    );
  }
  if (chartType === "bar") {
    const points = aggregateByCategory(preview.rows, x, y, aggregation);
    return (
      <div className="pt-4">
        <GroupedBars
          categories={points.map((p) => p.label)}
          series={[{ name: y ?? "Count", values: points.map((p) => p.value) }]}
        />
      </div>
    );
  }
  if (chartType === "scatter" && y) {
    return (
      <div className="pt-4">
        <ScatterPlot
          points={scatterPoints(preview.rows, x, y)}
          xLabel={x}
          yLabel={y}
        />
      </div>
    );
  }
  if (chartType === "histogram") {
    return (
      <div className="pt-4">
        <HistogramChart buckets={histogram(preview.rows, x)} valueLabel={x} />
      </div>
    );
  }
  if (chartType === "donut") {
    return (
      <div className="pt-4">
        <DonutChart slices={aggregateByCategory(preview.rows, x, null, "count", 12)} />
      </div>
    );
  }
  return <PreviewTable preview={preview} />;
}

// --- Table --------------------------------------------------------------------------------------------------

function PreviewTable({ preview }: { preview: DatasetPreview }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(preview.rows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const slice = preview.rows.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE,
  );

  return (
    <div className="pt-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs text-text-muted">
          <Table2 size={13} aria-hidden />
          Showing{" "}
          <span className="num text-text-2">
            {safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, preview.rows.length)}
          </span>{" "}
          of <span className="num text-text-2">{formatNumber(preview.rows.length)}</span>{" "}
          sampled rows ({formatNumber(preview.total_rows)} in the full dataset)
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
          >
            Previous
          </Button>
          <Badge tone="muted" withIcon={false}>
            Page {safePage + 1} / {pageCount}
          </Badge>
          <Button
            variant="ghost"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage(safePage + 1)}
          >
            Next
          </Button>
        </div>
      </div>
      <div className="max-h-[480px] overflow-auto rounded-xl border border-line">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr className="border-b border-line text-[10px] uppercase tracking-[0.14em] text-text-muted">
              {preview.columns.map((column) => (
                <th key={column.name} className="whitespace-nowrap px-3 py-2.5 font-bold">
                  {column.name}
                  <span className="ml-1.5 font-medium normal-case tracking-normal text-text-muted/70">
                    {kindLabel(column.kind)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((row, i) => (
              <tr
                key={i}
                className="border-b border-line/50 transition-colors last:border-0 hover:bg-faint"
              >
                {preview.columns.map((column) => (
                  <td
                    key={column.name}
                    className={`max-w-[260px] truncate whitespace-nowrap px-3 py-2 ${
                      column.kind === "numeric" ? "num text-right" : "text-text-2"
                    }`}
                    title={String(row[column.name] ?? "")}
                  >
                    {formatCell(row[column.name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toPrecision(6).replace(/\.?0+$/, "");
  return String(value).slice(0, 10);
}

function kindLabel(kind: ColumnKind): string {
  switch (kind) {
    case "date":
      return "date";
    case "numeric":
      return "num";
    case "categorical":
      return "category";
    default:
      return "text";
  }
}

// --- Selects -----------------------------------------------------------------------------------------------

/** Date and category columns first — they make the friendliest X axes. */
function orderedChoices(preview: DatasetPreview): { name: string; kind: ColumnKind }[] {
  const rank: Record<ColumnKind, number> = {
    date: 0,
    categorical: 1,
    numeric: 2,
    text: 3,
  };
  return [...preview.columns].sort((a, b) => rank[a.kind] - rank[b.kind]);
}

function AxisSelect({
  label,
  value,
  onChange,
  columns,
}: {
  label: string;
  value: string | null;
  onChange: (next: string | null) => void;
  columns: { name: string; kind: ColumnKind }[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
      {label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="min-w-[140px] rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm font-medium normal-case tracking-normal text-text"
      >
        <option value="">None</option>
        {columns.map((column) => (
          <option key={column.name} value={column.name}>
            {column.name} ({kindLabel(column.kind)})
          </option>
        ))}
      </select>
    </label>
  );
}

function syncChartType(
  preview: DatasetPreview,
  x: string | null,
  y: string | null,
  setChartType: (type: ChartType) => void,
): void {
  const allowed = allowedChartTypes(preview.columns, x, y);
  setChartType(allowed[0]);
}

