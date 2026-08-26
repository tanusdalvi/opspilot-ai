import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Loader2 } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import { Button, EmptyState, SkeletonPanel } from "../components/ui/Primitives";
import { SegmentedControl } from "../components/ui/Controls";
import { DivergingBars, GroupedBars, TrendArea } from "../components/charts/Charts";
import { metricLabel, periodChangeLabel } from "../lib/labels";

export default function Analytics() {
  const { system, artifacts } = useWorkspace();

  const trends = useMemo(
    () => (artifacts?.daily_trends ?? []) as Record<string, unknown>[],
    [artifacts],
  );

  /** Dynamically derive available numeric metric columns from daily_trends. */
  const availableMetrics = useMemo(() => {
    if (!trends.length) return [] as string[];
    const keys = Object.keys(trends[0]);
    const dateKey =
      keys.find((k) => k.toLowerCase() === "date") ?? keys[0];
    return keys.filter((k) => {
      if (k === dateKey) return false;
      const sample = trends.find((r) => r[k] !== undefined && r[k] !== null);
      return sample !== undefined && Number.isFinite(Number(sample[k]));
    });
  }, [trends]);

  const [metric, setMetric] = useState<string>("");

  /** Snap to first available metric when the list changes. */
  const activeMetric = useMemo(() => {
    if (availableMetrics.length === 0) return null;
    if (availableMetrics.includes(metric)) return metric;
    return availableMetrics[0];
  }, [availableMetrics, metric]);

  const metricOptions = useMemo(
    () => availableMetrics.map((m) => ({ value: m, label: metricLabel(m) })),
    [availableMetrics],
  );

  /** Exact-match column resolution against real daily_trends columns. */
  const { dateKey, valueKey } = useMemo(() => {
    if (!trends.length || !activeMetric) return { dateKey: "date", valueKey: null as string | null };
    const keys = Object.keys(trends[0]);
    const date =
      keys.find((k) => k.toLowerCase() === "date") ?? keys[0];
    const value =
      keys.find((k) => k !== date && k === activeMetric) ??
      keys.find((k) => k !== date && k.startsWith(activeMetric)) ??
      null;
    return { dateKey: date, valueKey: value };
  }, [trends, activeMetric]);

  const { dates, values } = useMemo(() => {
    if (!valueKey) return { dates: [] as string[], values: [] as number[] };
    const outDates: string[] = [];
    const outValues: number[] = [];
    for (const row of trends) {
      const numeric = Number(row[valueKey]);
      if (!Number.isFinite(numeric)) continue;
      outDates.push(String(row[dateKey] ?? ""));
      outValues.push(numeric);
    }
    return { dates: outDates, values: outValues };
  }, [trends, dateKey, valueKey]);

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

  const hasRegion = Boolean(artifacts?.region_performance?.length);
  const hasProduct = Boolean(artifacts?.product_performance?.length);

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
          title={valueKey ? `${metricLabel(valueKey)} · daily trend` : "Daily trend"}
          caption="Brush or scroll-zoom to focus a window; amber markers are detected anomaly dates."
          actions={
            metricOptions.length > 0 ? (
              <SegmentedControl
                ariaLabel="Trend metric"
                options={metricOptions}
                value={activeMetric ?? ""}
                onChange={(next) => setMetric(next)}
              />
            ) : undefined
          }
        />
        {running ? (
          <div className="flex items-center gap-2 py-10 text-sm text-text-2">
            <Loader2 size={15} className="animate-spin text-accent" aria-hidden />
            Analysis running — charts appear the moment artifacts are ready.
          </div>
        ) : !artifacts ? (
          <SkeletonPanel lines={5} />
        ) : trends.length === 0 ? (
          <p className="py-10 text-center text-sm text-text-2">
            This dataset does not have daily trend data for charting.
          </p>
        ) : availableMetrics.length === 0 ? (
          <p className="py-10 text-center text-sm text-text-2">
            Daily trend rows exist but contain no numeric metric columns — the
            trend chart requires at least one numeric field besides the date.
          </p>
        ) : dates.length === 0 ? (
          <p className="py-10 text-center text-sm text-text-2">
            This dataset has no dated daily history for{" "}
            {metricLabel(activeMetric)} — the trend chart needs a date column
            plus that metric. The period comparison below still applies.
          </p>
        ) : (
          <TrendArea
            dates={dates}
            values={values}
            metricLabel={metricLabel(valueKey ?? activeMetric)}
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

        {hasRegion && (
          <DimensionDrillDown
            title="Region drill-down"
            caption="Deterministic per-region aggregates from the same pipeline pass."
            rows={artifacts!.region_performance}
            nameField="region"
          />
        )}

        {hasProduct && (
          <DimensionDrillDown
            title="Product drill-down"
            caption="Deterministic per-product aggregates from the same pipeline pass."
            rows={artifacts!.product_performance}
            nameField="product"
          />
        )}
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
  rows: Record<string, unknown>[];
  nameField: string;
}) {
  const series = useMemo(() => {
    if (!rows.length) return null;
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
    const valueKey = valueKeys[0];
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
      {rows.length === 0 || !series ? (
        <p className="py-8 text-center text-sm text-text-2">
          No per-{nameField} breakdown is available for this dataset — the
          pipeline did not produce a numeric {nameField} aggregation.
        </p>
      ) : (
        <GroupedBars
          categories={series.categories}
          series={[{ name: series.name, values: series.values }]}
        />
      )}
    </Panel>
  );
}
