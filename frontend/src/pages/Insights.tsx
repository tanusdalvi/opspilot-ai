import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Lightbulb } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { Accordion, SegmentedControl } from "../components/ui/Controls";
import {
  countBySeverity,
  filterBySeverity,
  groupByMetric,
  prioritySignals,
  SEVERITIES,
  sortSignals,
  type SeverityFilter,
  type SignalSortKey,
} from "../lib/signals";
import {
  scopeLabel,
  signalTitle,
} from "../lib/labels";
import { formatDateShort } from "../lib/format";
import { severity } from "../lib/severity";
import type { AnomalyRecord } from "../lib/types";

const FILTER_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "CRITICAL", label: "Critical" },
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
];

const SORT_OPTIONS: { value: SignalSortKey; label: string }[] = [
  { value: "severity", label: "Severity" },
  { value: "date", label: "Date" },
  { value: "metric", label: "Metric" },
];

export default function Insights() {
  const { system, artifacts } = useWorkspace();
  const [filter, setFilter] = useState<SeverityFilter>("ALL");
  const [sortKey, setSortKey] = useState<SignalSortKey>("severity");
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  const anomalies: AnomalyRecord[] =
    artifacts?.anomaly_result?.anomalies ?? [];
  const counts = useMemo(() => countBySeverity(anomalies), [anomalies]);
  const priority = useMemo(() => prioritySignals(anomalies), [anomalies]);
  const groups = useMemo(
    () => (filter === "ALL" ? groupByMetric(anomalies) : groupByMetric(anomalies)),
    [anomalies, filter],
  );

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Insights" />
        <EmptyState
          icon={<Lightbulb size={20} />}
          title="No analysis available"
          body="Deterministic signals appear here after a pipeline run. Load a dataset and run the analysis to begin."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  if (!artifacts) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Insights" />
        <SkeletonPanel lines={6} />
      </div>
    );
  }

  const filtered = sortSignals(filterBySeverity(anomalies, filter), sortKey);

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Signal Intelligence"
        description="A prioritized reading of every deterministic signal from the latest analysis run."
      />

      {/* LEVEL 1 — Executive summary */}
      <Panel className="p-5">
        <SectionHeading
          title="Executive summary"
          caption="Computed live from detected anomalies — never fabricated."
        />
        <p className="text-lg font-semibold leading-snug text-text">
          <span className="num text-accent">{anomalies.length}</span>{" "}
          operational signal{anomalies.length === 1 ? "" : "s"} detected across
          the analysis period.
        </p>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
          {SEVERITIES.map((key) =>
            counts[key] > 0 ? (
              <span key={key} className="flex items-center gap-2 text-sm">
                <span
                  className={`h-2 w-2 rounded-full ${
                    key === "CRITICAL"
                      ? "bg-danger"
                      : key === "HIGH"
                        ? "bg-danger/70"
                        : key === "MEDIUM"
                          ? "bg-warn"
                          : "bg-accent"
                  }`}
                  aria-hidden
                />
                <span className="text-text-2">{severity(key).label}:</span>
                <span className="num font-bold text-text">{counts[key]}</span>
              </span>
            ) : null,
          )}
          {anomalies.length === 0 && (
            <span className="text-sm text-text-2">
              No signals beyond detection thresholds.
            </span>
          )}
        </div>
      </Panel>

      {/* Priority signals */}
      {priority.length > 0 && (
        <section aria-label="Priority signals" className="mt-8">
          <SectionHeading
            title="Priority signals"
            caption="Highest-severity deviations first — investigate these before anything else."
          />
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {priority.map((record, index) => (
              <PriorityCard key={recordKey(record)} record={record} index={index} />
            ))}
          </div>
        </section>
      )}

      {/* LEVEL 2 — Grouped intelligence */}
      {groups.length > 0 && filter === "ALL" && (
        <section aria-label="Signals by metric" className="mt-8">
          <SectionHeading
            title="Signals by metric"
            caption="Related detections consolidated per metric. Expand a group for individual evidence."
          />
          <div className="space-y-3">
            {groups.map((group) => (
              <Accordion
                key={group.metric}
                open={openGroup === group.metric}
                onToggle={() =>
                  setOpenGroup(openGroup === group.metric ? null : group.metric)
                }
                title={
                  <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-sm font-semibold text-text">
                      {group.label}
                    </span>
                    <span className="num text-xs text-text-muted">
                      {group.total} signal{group.total === 1 ? "" : "s"}
                    </span>
                  </span>
                }
                meta={
                  <span className="num text-[11px] text-text-2">
                    {SEVERITIES.filter((s) => group.counts[s] > 0)
                      .map(
                        (s) =>
                          `${group.counts[s]} ${severity(s).label.toLowerCase()}`,
                      )
                      .join(" · ")}
                  </span>
                }
                badge={
                  <Badge tone={severity(group.topSeverity).tone}>
                    {severity(group.topSeverity).label}
                  </Badge>
                }
              >
                <ul className="divide-y divide-line">
                  {group.members.map((member) => (
                    <li
                      key={recordKey(member)}
                      className="flex flex-wrap items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0"
                    >
                      <span className="min-w-0">
                        <span className="text-sm font-medium text-text">
                          {signalTitle(member)}
                        </span>
                        {member.date ? (
                          <span className="ml-2 text-xs text-text-muted">
                            {formatDateShort(String(member.date))}
                          </span>
                        ) : member.entity ? (
                          <span className="ml-2 text-xs text-text-muted">
                            {String(member.entity)}
                          </span>
                        ) : null}
                      </span>
                      <span className="flex items-center gap-3">
                        <Badge tone={severity(member.severity).tone}>
                          {severity(member.severity).label}
                        </Badge>
                        <span className="num w-16 text-right text-sm font-bold text-danger">
                          {Number(member.deviation_pct ?? 0) >= 0 ? "+" : ""}
                          {Math.abs(Number(member.deviation_pct ?? 0)).toFixed(1)}
                          %
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Accordion>
            ))}
          </div>
        </section>
      )}

      {/* LEVEL 3 — Detailed evidence */}
      <section aria-label="All signals" className="mt-8">
        <SectionHeading
          title="Detailed signals"
          caption="Full deterministic record set with filtering and sorting."
          actions={
            <SegmentedControl
              ariaLabel="Sort signals"
              options={SORT_OPTIONS}
              value={sortKey}
              onChange={setSortKey}
            />
          }
        />
        <div className="mb-4">
          <SegmentedControl
            ariaLabel="Filter by severity"
            options={FILTER_OPTIONS}
            value={filter}
            onChange={setFilter}
          />
        </div>

        {filtered.length === 0 ? (
          <Panel className="p-6 text-center text-sm text-text-2">
            No signals at this severity.{" "}
            {filter !== "ALL" && (
              <button
                onClick={() => setFilter("ALL")}
                className="font-semibold text-accent underline-offset-2 hover:underline"
              >
                Show all signals
              </button>
            )}
          </Panel>
        ) : filtered.length <= 12 ? (
          <SignalTable records={filtered} />
        ) : (
          <>
            <SignalTable records={filtered.slice(0, 12)} />
            <p className="mt-3 text-xs text-text-muted">
              Showing 12 of {filtered.length} — refine with the filters above.
            </p>
          </>
        )}
      </section>
    </div>
  );
}

function recordKey(record: AnomalyRecord): string {
  return JSON.stringify([
    record.type,
    record.metric,
    record.entity,
    record.date,
    record.deviation_pct,
    record.severity,
  ]);
}

function PriorityCard({
  record,
  index,
}: {
  record: AnomalyRecord;
  index: number;
}) {
  const style = severity(record.severity);
  const deviation = Number(record.deviation_pct ?? 0);
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
    >
      <Link to="/anomalies" className="panel panel-hover block p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-bold leading-snug text-text">
            {signalTitle(record)}
          </h3>
          <Badge tone={style.tone}>{style.label}</Badge>
        </div>
        <p className="mt-1 text-xs text-text-muted">
          {record.date
            ? formatDateShort(String(record.date))
            : String(record.entity ?? "Dataset-wide")}
        </p>
        <p className="num mt-2 text-lg font-bold text-danger">
          {deviation >= 0 ? "+" : ""}
          {deviation.toFixed(1)}%
          <span className="ml-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
            vs expected
          </span>
        </p>
      </Link>
    </motion.div>
  );
}

function SignalTable({ records }: { records: AnomalyRecord[] }) {
  return (
    <Panel className="overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-[10px] uppercase tracking-[0.16em] text-text-muted">
            <th className="px-4 py-2.5 font-bold">Signal</th>
            <th className="hidden px-4 py-2.5 font-bold md:table-cell">Scope</th>
            <th className="hidden px-4 py-2.5 font-bold sm:table-cell">Date</th>
            <th className="px-4 py-2.5 text-right font-bold">Deviation</th>
            <th className="px-4 py-2.5 font-bold">Severity</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const style = severity(record.severity);
            return (
              <tr
                key={recordKey(record)}
                className="border-b border-line/60 last:border-0 transition-colors hover:bg-white/[0.02]"
              >
                <td className="px-4 py-2.5 font-medium text-text">
                  {signalTitle(record)}
                </td>
                <td className="hidden px-4 py-2.5 text-xs text-text-2 md:table-cell">
                  {scopeLabel(record.scope)}
                </td>
                <td className="num hidden px-4 py-2.5 text-xs text-text-2 sm:table-cell">
                  {record.date ? formatDateShort(String(record.date)) : "—"}
                </td>
                <td className="num px-4 py-2.5 text-right font-bold text-danger">
                  {Number(record.deviation_pct ?? 0) >= 0 ? "+" : ""}
                  {Math.abs(Number(record.deviation_pct ?? 0)).toFixed(1)}%
                </td>
                <td className="px-4 py-2.5">
                  <Badge tone={style.tone}>{style.label}</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
