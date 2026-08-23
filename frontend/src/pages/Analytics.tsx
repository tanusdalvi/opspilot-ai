import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Loader2 } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import { Button, EmptyState, SkeletonPanel } from "../components/ui/Primitives";
import { SegmentedControl } from "../components/ui/Controls";
import { DivergingBars, GroupedBars, TrendArea } from "../components/charts/Charts";
import { metricLabel, periodChangeLabel, TREND_METRICS } from "../lib/labels";

type TrendMetric = (typeof TREND_METRICS)[number];

const METRIC_OPTIONS = TREND_METRICS.map((m) => ({
  value: m,
  label: metricLabel(m),
}));

export default function Analytics() {
  const { system, artifacts } = useWorkspace();
  const [metric, setMetric] = useState<TrendMetric>("revenue");
  const trends = (artifacts?.daily_trends ?? []) as Record<string, unknown>[];

  /** Exact-match column resolution against real daily_trends columns. */
  const { dateKey, valueKey } = useMemo(() => {
    if (!trends.length) return { dateKey: "date", valueKey: metric };
    const keys = Object.keys(trends[0]);
    const date =
      keys.find((k) => k.toLowerCase() === "date") ?? keys[0];
    const value =
      keys.find((k) => k !== date && k === metric) ??
      keys.find((k) => k !== date && k.startsWith(metric)) ??
      metric;
    return { dateKey: date, valueKey: value };
  }, [trends, metric]);

  const dates = trends.map((row) => String(row[dateKey] ?? ""));
  const values = trends.map((row) => Number(row[valueKey] ?? 0));
  const anomalyDates = useMemo(
    () => [
      ...new Set(
        (artifacts?.anomaly_result?.anomalies ?? [])
          .map((a) => String(a.date ?? ""))
          .filter(Boolean),
      ),
    ],
    [artifacts],
  );

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Analytics" />
        <EmptyState
          icon={<BarChart3 size={20} />}
          title="No analysis available"
          body="Load a dataset and run the deterministic analysis; every chart here is generated from its artifacts."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  const running = system?.analysis_running === true && !artifacts;

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Analytical Workspace"
        description="Interactive exploration of daily performance, period comparison, and dimension drill-down."
      />

      <Panel className="p-5">
        <SectionHeading
          title={`${metricLabel(valueKey)} · daily trend`}
          caption="Brush or scroll-zoom to focus a window; amber markers are detected anomaly dates."
          actions={
            <SegmentedControl
              ariaLabel="Trend metric"
              options={METRIC_OPTIONS}
              value={metric}
              onChange={(next) => setMetric(next)}
            />
          }
        />
        {running ? (
          <div className="flex items-center gap-2 py-10 text-sm text-text-2">
            <Loader2 size={15} className="animate-spin text-accent" aria-hidden />
            Analysis running — charts appear the moment artifacts are ready.
          </div>
        ) : !artifacts ? (
          <SkeletonPanel lines={5} />
        ) : (
          <TrendArea
            dates={dates}
            values={values}
            metricLabel={metricLabel(valueKey)}
            overlayDates={anomalyDates}
          />
        )}
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel className="p-5">
          <SectionHeading
            title="Period comparison"
            caption="Change % between the first and second half of the covered window."
          />
          {artifacts ? (
            <DivergingBars
              entries={Object.entries(
                artifacts.period_comparison.changes_pct,
              ).map(([key, value]) => [periodChangeLabel(key), value])}
            />
          ) : (
            <SkeletonPanel lines={4} />
          )}
        </Panel>

        <DimensionDrillDown
          title="Region drill-down"
          caption="Deterministic per-region aggregates from the same pipeline pass."
          rows={artifacts?.region_performance}
          nameField="region"
        />

        <DimensionDrillDown
          title="Product drill-down"
          caption="Deterministic per-product aggregates from the same pipeline pass."
          rows={artifacts?.product_performance}
          nameField="product"
        />
      </div>
    </div>
  );
}

function DimensionDrillDown({
  title,
  caption,
  rows,
  nameField,
}: {
  title: string;
  caption: string;
  rows?: Record<string, unknown>[];
  nameField: string;
}) {
  const series = useMemo(() => {
    if (!rows?.length) return null;
    const keys = Object.keys(rows[0]);
    const nameKey =
      keys.find((k) => k.toLowerCase() === nameField) ??
      keys.find((k) => k.toLowerCase().includes(nameField)) ??
      keys[0];
    const valueKeys = keys.filter(
      (k) =>
        k !== nameKey &&
        rows.some((r) => Number.isFinite(Number(r[k]))),
    );
    const valueKey =
      valueKeys.find((k) => k === "total_revenue") ??
      valueKeys.find((k) => k.includes("revenue")) ??
      valueKeys[0];
    if (!valueKey) return null;
    return {
      categories: rows.map((r) => String(r[nameKey] ?? "")),
      name: metricLabel(valueKey),
      values: rows.map((r) => Number(r[valueKey] ?? 0)),
    };
  }, [rows, nameField]);

  return (
    <Panel className="p-5">
      <SectionHeading title={title} caption={caption} />
      {series ? (
        <GroupedBars
          categories={series.categories}
          series={[{ name: series.name, values: series.values }]}
        />
      ) : (
        <SkeletonPanel lines={4} />
      )}
    </Panel>
  );
}
