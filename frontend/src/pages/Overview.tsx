import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Database, Radar, ShieldCheck } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { SignalPosture } from "../components/charts/SignalPosture";
import { LifecycleRail } from "../components/shell/LifecycleRail";
import { formatDateTime, formatDateShort } from "../lib/format";
import { signalTitle } from "../lib/labels";
import { StatTile } from "../components/ui/StatTile";
import { presentPosture } from "../lib/signals";
import { severity } from "../lib/severity";
import type { AnomalyRecord } from "../lib/types";

/** Headline KPIs shown first; remaining verified KPIs live in Evidence. */
const HEADLINE_KPIS = [
  "total_revenue",
  "total_profit",
  "profit_margin_pct",
  "total_units_sold",
  "average_lead_time_days",
] as const;

export default function Overview() {
  const { system, artifacts } = useWorkspace();
  const ready = system?.artifacts_ready === true;
  const anomalies: AnomalyRecord[] =
    artifacts?.anomaly_result?.anomalies ?? [];
  const posture = presentPosture(artifacts?.posture, anomalies);
  const criticalFirst = [...anomalies]
    .sort(
      (a, b) =>
        severity(b.severity).weight - severity(a.severity).weight,
    )
    .slice(0, 4);

  /** Daily series for a headline KPI from real trend data (empty when absent). */
  const trendFor = (kpiKey: string): number[] | undefined => {
    const field =
      kpiKey === "total_units_sold"
        ? "units_sold"
        : kpiKey === "profit_margin_pct"
          ? "profit_margin_pct"
          : kpiKey === "average_lead_time_days"
            ? "average_lead_time_days"
            : kpiKey.replace("total_", "");
    const rows = artifacts?.daily_trends ?? [];
    const values = rows
      .map((row) => Number(row[field]))
      .filter((n) => Number.isFinite(n));
    return values.length > 1 ? values.slice(-90) : undefined;
  };

  return (
    <div>
      <PageHeader
        eyebrow="Command Center"
        title="Operations Overview"
        description="Live operational posture, business pulse, and the signals that need attention first."
      />

      {/* OPERATIONS STATUS */}
      <section aria-label="Operations status" className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <Panel className="p-5">
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck size={15} className="text-accent" aria-hidden />
            <h2 className="text-[11px] font-bold uppercase tracking-[0.2em] text-text-2">
              Signal Posture
            </h2>
          </div>
          {!ready ? (
            <Skeleton className="h-[190px] w-full" />
          ) : posture ? (
            <SignalPosture posture={posture} />
          ) : null}
        </Panel>

        <div className="grid gap-4">
          <Panel className="p-5">
            <SectionHeading
              icon={<Radar size={15} className="text-accent" aria-hidden />}
              title="Workspace status"
              caption="Derived live from the analysis lifecycle — never fabricated."
            />
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
              <StatusCell
                label="Dataset"
                value={system?.dataset?.name ?? "none"}
                tone={system?.dataset ? undefined : "muted"}
              />
              <StatusCell label="Analysis" value={system?.analysis_status ?? "…"} />
              <StatusCell
                label="Freshness"
                value={
                  system?.recovery_context?.completed_at
                    ? formatDateTime(system.recovery_context.completed_at)
                    : system?.artifacts_ready
                      ? "current session"
                      : "—"
                }
              />
              <StatusCell
                label="AI investigation"
                value={system?.ai_available ? "Available" : "Not configured"}
                tone={system?.ai_available ? undefined : "muted"}
              />
            </dl>
          </Panel>

          <Panel className="p-5">
            <SectionHeading
              title="Lifecycle"
              caption="Where this workspace sits in the seven-stage operational loop."
            />
            <LifecycleRail current={system?.lifecycle_stage} />
          </Panel>
        </div>
      </section>

      {/* BUSINESS PULSE */}
      <section aria-label="Business pulse" className="mt-8">
        <SectionHeading
          title="Business pulse"
          caption="Verified headline KPIs with period-over-period movement."
          actions={
            artifacts ? (
              <Link to="/evidence">
                <Button variant="ghost">
                  All {Object.keys(artifacts.kpis).length} KPIs{" "}
                  <ArrowRight size={14} />
                </Button>
              </Link>
            ) : null
          }
        />
        {!ready ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonPanel key={i} lines={2} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {HEADLINE_KPIS.filter((k) => k in (artifacts?.kpis ?? {})).map(
              (key, i) => (
                <StatTile
                  key={key}
                  index={i}
                  label={key}
                  value={Number(artifacts?.kpis[key] ?? 0)}
                  changePct={
                    artifacts?.period_comparison?.changes_pct?.[
                      changeKeyFor(key)
                    ] ?? null
                  }
                  spark={trendFor(key)}
                />
              ),
            )}
            {anomalies.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 5 * 0.05 }}
              >
                <Link to="/anomalies" className="panel panel-hover block h-full p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                    Active Signals
                  </p>
                  <span className="num mt-2 block text-2xl font-bold text-danger">
                    {anomalies.length}
                  </span>
                  <p className="mt-0.5 text-[10px] uppercase tracking-wider text-text-muted">
                    detected deviations
                  </p>
                </Link>
              </motion.div>
            )}
          </div>
        )}
      </section>

      {/* SIGNAL WALL PREVIEW */}
      <section aria-label="Priority signals" className="mt-8">
        <SectionHeading
          title="Signals needing attention"
          caption="Highest-severity detected deviations. Open Anomalies for the full signal wall."
          actions={
            <Link to="/anomalies">
              <Button variant="ghost">
                Full wall <ArrowRight size={14} />
              </Button>
            </Link>
          }
        />
        {!ready ? (
          <SkeletonPanel lines={4} />
        ) : anomalies.length === 0 ? (
          <EmptyState
            icon={<Database size={20} />}
            title="No analysis available"
            body="Load a dataset and run analysis to populate operational signals."
            action={
              <Link to="/data">
                <Button>Open Data Workspace</Button>
              </Link>
            }
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {criticalFirst.map((signal) => (
              <SignalPreview key={recordKey(signal)} signal={signal} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/** Maps a total KPI to its period-comparison change field (backend naming). */
function changeKeyFor(kpiKey: string): string {
  switch (kpiKey) {
    case "total_units_sold":
      return "units_change_pct";
    case "total_revenue":
      return "revenue_change_pct";
    case "total_cost":
      return "cost_change_pct";
    case "total_profit":
      return "profit_change_pct";
    case "profit_margin_pct":
      return "margin_change_pct";
    case "average_lead_time_days":
      return "lead_time_change_pct";
    default:
      return `${kpiKey}_change_pct`;
  }
}

function recordKey(record: AnomalyRecord): string {
  return JSON.stringify([
    record.type,
    record.metric,
    record.entity,
    record.date,
    record.severity,
  ]);
}

function StatusCell({
  label,
  value,
  tone,
}: {
  label: string;
  value?: string | null;
  tone?: "muted";
}) {
  return (
    <div>
      <dt className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
        {label}
      </dt>
      <dd
        className={`num mt-0.5 truncate text-sm font-semibold ${
          tone === "muted" || !value || value === "none"
            ? "text-text-muted"
            : "text-text"
        }`}
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}

export function SignalPreview({ signal }: { signal: AnomalyRecord }) {
  const style = severity(signal.severity);
  const deviation = Math.abs(Number(signal.deviation_pct ?? 0));
  return (
    <Link
      to="/anomalies"
      className="panel panel-hover block p-4 focus-visible:outline-accent"
    >
      <div className="flex items-center justify-between gap-2">
        <Badge tone={style.tone}>{style.label}</Badge>
        <span className="num text-sm font-bold text-danger">
          +{deviation.toFixed(1)}% vs expected
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-text">
        {signalTitle(signal)}
      </p>
      <p className="mt-0.5 truncate text-xs text-text-2">
        {[signal.entity, signal.date ? formatDateShort(String(signal.date)) : ""]
          .filter(Boolean)
          .join(" · ") || scopeLabelOf(signal)}
      </p>
    </Link>
  );
}

function scopeLabelOf(signal: AnomalyRecord): string {
  const scope = String(signal.scope ?? "");
  if (scope === "daily") return "Dataset-wide · daily totals";
  if (scope === "region") return "Region level";
  if (scope === "product") return "Product level";
  return scope;
}
