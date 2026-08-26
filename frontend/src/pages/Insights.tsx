import { useEffect, useMemo, useState } from "react";
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
  deviationDirection,
  deviationIsAdverse,
  filterBySeverity,
  formatDeviation,
  groupByMetric,
  prioritySignals,
  signalPeriodRange,
  topConcernSignal,
  SEVERITIES,
  sortSignals,
  type SeverityFilter,
  type SignalSortKey,
} from "../lib/signals";
import {
  metricLabel,
  scopeLabel,
  signalInterpretation,
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

/** Rows disclosed per page in the detailed table. */
const TABLE_PAGE = 12;

export default function Insights() {
  const { system, artifacts } = useWorkspace();
  const [filter, setFilter] = useState<SeverityFilter>("ALL");
  const [sortKey, setSortKey] = useState<SignalSortKey>("severity");
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [tableLimit, setTableLimit] = useState(TABLE_PAGE);
  const [evidenceVisible, setEvidenceVisible] = useState(false);
  const [textSearch, setTextSearch] = useState("");

  const anomalies: AnomalyRecord[] = useMemo(
    () => artifacts?.anomaly_result?.anomalies ?? [],
    [artifacts],
  );
  const counts = useMemo(() => countBySeverity(anomalies), [anomalies]);
  const priority = useMemo(() => prioritySignals(anomalies), [anomalies]);
  const concern = useMemo(() => topConcernSignal(anomalies), [anomalies]);
  const groups = useMemo(() => groupByMetric(anomalies), [anomalies]);

  const searchQuery = textSearch.trim().toLowerCase();

  const searchFiltered = useMemo(() => {
    if (!searchQuery) return anomalies;
    return anomalies.filter((a) =>
      signalTitle(a).toLowerCase().includes(searchQuery),
    );
  }, [anomalies, searchQuery]);

  // Filter or sort changes rewind the detailed table to its first page.
  useEffect(() => setTableLimit(TABLE_PAGE), [filter, sortKey, textSearch]);

  // Auto-expand the first (most severe) group on mount.
  useEffect(() => {
    if (groups.length > 0 && openGroup === null) {
      setOpenGroup(groups[0].metric);
    }
  }, [groups]);

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
        <p className="text-xl font-bold leading-snug text-text">
          <span className="num text-accent">{anomalies.length}</span>{" "}
          operational signal{anomalies.length === 1 ? "" : "s"} detected across
          the analysis period.
        </p>

        {/* Severity distribution — horizontal stacked bar */}
        <div className="mt-4">
          <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
            Severity distribution
          </p>
          {anomalies.length > 0 ? (
            <>
              <div
                className="flex h-3 w-full overflow-hidden rounded-full"
                role="img"
                aria-label={`Severity breakdown: ${SEVERITIES.filter((k) => counts[k] > 0).map((k) => `${counts[k]} ${severity(k).label.toLowerCase()}`).join(", ")}`}
              >
                {SEVERITIES.map((key) =>
                  counts[key] > 0 ? (
                    <span
                      key={key}
                      className={`h-full ${
                        key === "CRITICAL"
                          ? "bg-danger"
                          : key === "HIGH"
                            ? "bg-danger/70"
                            : key === "MEDIUM"
                              ? "bg-warn"
                              : "bg-accent"
                      }`}
                      style={{
                        width: `${(counts[key] / anomalies.length) * 100}%`,
                      }}
                      title={`${severity(key).label}: ${counts[key]}`}
                    />
                  ) : null,
                )}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                {SEVERITIES.map((key) =>
                  counts[key] > 0 ? (
                    <span key={key} className="flex items-center gap-1.5 text-xs">
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
                      <span className="text-text-2">{severity(key).label}</span>
                      <span className="num font-bold text-text">{counts[key]}</span>
                    </span>
                  ) : null,
                )}
              </div>
            </>
          ) : (
            <p className="text-sm text-text-2">
              No signals beyond detection thresholds.
            </p>
          )}
        </div>

        {concern && (
          <div className="mt-5 rounded-xl border border-danger/30 bg-danger/5 px-5 py-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-danger">
              Top concern
            </p>
            <p className="mt-1.5 text-base font-bold text-text">
              {signalTitle(concern)}
              <span className="num ml-2 font-bold text-danger">
                {formatDeviation(Number(concern.deviation_pct ?? 0))}
              </span>
            </p>
            <p className="mt-1 text-xs text-text-muted">
              {[
                concern.entity ?? scopeLabel(concern.scope),
                concern.date ? formatDateShort(String(concern.date)) : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-text-2">
              {signalInterpretation(concern)}
            </p>
            <p className="mt-2.5 text-xs font-semibold text-danger/80">
              {concern.severity === "CRITICAL"
                ? "Immediate investigation recommended — review the underlying data and confirm or dismiss this signal today."
                : concern.severity === "HIGH"
                  ? "Investigate soon — check whether the underlying cause is ongoing or a one-time event."
                  : "Review when convenient — monitor for escalation in the next analysis run."}
            </p>
          </div>
        )}
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

      {/* LEVEL 2 — Key Findings */}
      {groups.length > 0 && filter === "ALL" && (
        <section aria-label="Key Findings" className="mt-8">
          <SectionHeading
            title="Key Findings"
            caption={`Related detections consolidated per metric. Expand a group for individual evidence.`}
            actions={
              <span className="num text-xs text-text-muted">
                {anomalies.length} of {anomalies.length} signals shown
              </span>
            }
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
                    {[
                      SEVERITIES.filter((s) => group.counts[s] > 0)
                        .map(
                          (s) =>
                            `${group.counts[s]} ${severity(s).label.toLowerCase()}`,
                        )
                        .join(" · "),
                      signalPeriodRange(group.members),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                }
                badge={
                  <Badge tone={severity(group.topSeverity).tone}>
                    {severity(group.topSeverity).label}
                  </Badge>
                }
              >
                <p className="mb-3 text-xs leading-relaxed text-text-2">
                  {(() => {
                    const sevCounts = SEVERITIES.filter(
                      (s) => group.counts[s] > 0,
                    )
                      .map(
                        (s) =>
                          `${group.counts[s]} ${severity(s).label.toLowerCase()}`,
                      )
                      .join(" and ");
                    return `${sevCounts} signal${group.total === 1 ? "" : "s"} detected in ${group.label}${group.total === 1 ? "" : " across the analysis period"}.`;
                  })()}
                </p>
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
                        <span
                          className={`num w-16 text-right text-sm font-bold ${
                            deviationIsAdverse(
                              member.metric,
                              Number(member.deviation_pct ?? 0),
                            )
                              ? "text-danger"
                              : "text-ok"
                          }`}
                        >
                          {formatDeviation(Number(member.deviation_pct ?? 0))}
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

      {/* Progressive disclosure toggle */}
      <div className="mt-8 text-center">
        <button
          onClick={() => setEvidenceVisible((v) => !v)}
          className="text-sm font-semibold text-accent underline-offset-2 hover:underline"
          aria-expanded={evidenceVisible}
        >
          {evidenceVisible ? "Hide detailed evidence" : "Show detailed evidence"}
        </button>
      </div>

      {/* LEVEL 3 — All Evidence */}
      {evidenceVisible && (
        <section aria-label="All Evidence" className="mt-4">
          <SectionHeading
            title="All Evidence"
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
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <SegmentedControl
              ariaLabel="Filter by severity"
              options={FILTER_OPTIONS}
              value={filter}
              onChange={setFilter}
            />
            <div className="relative w-full sm:max-w-xs">
              <input
                type="text"
                placeholder="Search signals…"
                value={textSearch}
                onChange={(e) => setTextSearch(e.target.value)}
                className="w-full rounded-lg border border-line-strong bg-transparent px-3 py-1.5 pl-8 text-xs text-text placeholder:text-text-muted focus:border-accent/50 focus:outline-none"
              />
              <svg
                className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden
              >
                <circle cx="11" cy="11" r="8" />
                <path d="M21 21l-4.35-4.35" />
              </svg>
            </div>
          </div>

          {(() => {
            const visible = sortSignals(
              filterBySeverity(searchFiltered, filter),
              sortKey,
            );
            if (visible.length === 0) {
              return (
                <Panel className="p-6 text-center text-sm text-text-2">
                  No signals match your filters.{" "}
                  {(filter !== "ALL" || textSearch) && (
                    <button
                      onClick={() => {
                        setFilter("ALL");
                        setTextSearch("");
                      }}
                      className="font-semibold text-accent underline-offset-2 hover:underline"
                    >
                      Clear filters
                    </button>
                  )}
                </Panel>
              );
            }
            return (
              <>
                <p className="mb-2 text-xs text-text-muted">
                  Showing {Math.min(tableLimit, visible.length)} of{" "}
                  {visible.length} signal{visible.length === 1 ? "" : "s"}
                </p>
                <SignalTable records={visible.slice(0, tableLimit)} />
                {visible.length > tableLimit && (
                  <div className="mt-4 flex items-center justify-between">
                    <p className="text-xs text-text-muted">
                      Showing {tableLimit} of {visible.length}
                    </p>
                    <Button
                      variant="ghost"
                      onClick={() => setTableLimit((n) => n + TABLE_PAGE)}
                    >
                      Show more
                    </Button>
                  </div>
                )}
              </>
            );
          })()}
        </section>
      )}
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
  const adverse = deviationIsAdverse(record.metric, deviation);
  const up = deviationDirection(deviation) === "up";
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
        <p className="mt-1.5 text-xs leading-relaxed text-text-2">
          {signalInterpretation(record)}
        </p>
        <p className="mt-1.5 text-[11px] text-text-muted">
          {metricLabel(record.metric)} ·{" "}
          {record.entity ? scopeLabel(record.scope) : "Dataset-wide daily totals"}
        </p>
        <div className="mt-2 flex items-end justify-end gap-2">
          <p
            className={`num text-lg font-bold ${
              deviation === 0 ? "text-text-2" : adverse ? "text-danger" : "text-ok"
            }`}
          >
            {up ? "▲" : "▼"} {formatDeviation(deviation)}
            <span className="ml-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
              vs expected
            </span>
          </p>
        </div>
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
                className="border-b border-line/60 last:border-0 transition-colors hover:bg-faint"
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
                <td className="num px-4 py-2.5 text-right font-bold">
                  {formatDeviation(Number(record.deviation_pct ?? 0))}
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

