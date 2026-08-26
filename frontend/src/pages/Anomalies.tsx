import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowUpRight,
  Radar,
} from "lucide-react";
import { useWorkspace } from "../state/workspace";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { Accordion } from "../components/ui/Controls";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import { Drawer } from "../components/ui/Drawer";
import { SEVERITY_ORDER, severity } from "../lib/severity";
import {
  anomalyTypeLabel,
  metricLabel,
  signalInterpretation,
  scopeLabel,
  signalTitle,
} from "../lib/labels";
import {
  deviationDirection,
  deviationIsAdverse,
  formatDeviation,
  groupByMetric,
  topConcernSignal,
  signalPeriodRange,
  sortForPriority,
  type SeverityCounts,
} from "../lib/signals";
import { formatDateShort } from "../lib/format";
import type { AnomalyRecord } from "../lib/types";

type Filter = "ALL" | "CRITICAL_HIGH" | string;

/** Top signals shown before "Show all" engages (progressive disclosure). */
const TOP_COUNT = 6;

export default function Anomalies() {
  const { system, artifacts } = useWorkspace();
  const [filter, setFilter] = useState<Filter>("CRITICAL_HIGH");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  const anomalies: AnomalyRecord[] = useMemo(
    () => artifacts?.anomaly_result?.anomalies ?? [],
    [artifacts],
  );

  // A new filter resets the disclosed window.
  useEffect(() => setShowAll(false), [filter]);

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const a of anomalies) {
      const key = String(a.severity ?? "UNKNOWN").toUpperCase();
      map[key] = (map[key] ?? 0) + 1;
    }
    return map;
  }, [anomalies]);

  const filtered = useMemo(
    () =>
      anomalies
        .filter(
          (a) =>
            filter === "ALL" ||
            filter === "CRITICAL_HIGH" ||
            String(a.severity).toUpperCase() === filter,
        )
        .filter(
          (a) =>
            filter !== "CRITICAL_HIGH" ||
            ["CRITICAL", "HIGH"].includes(
              String(a.severity).toUpperCase(),
            ),
        )
        .sort(
          (x, y) =>
            severity(y.severity).weight - severity(x.severity).weight ||
            Math.abs(Number(y.deviation_pct ?? 0)) -
              Math.abs(Number(x.deviation_pct ?? 0)),
        ),
    [anomalies, filter],
  );

  const groups = useMemo(() => groupByMetric(filtered), [filtered]);
  const concern = useMemo(() => topConcernSignal(anomalies), [anomalies]);
  const topSignals = useMemo(
    () => sortForPriority(filtered).slice(0, TOP_COUNT),
    [filtered],
  );

  const selected =
    selectedKey !== null
      ? anomalies.find((a) => recordKey(a) === selectedKey) ?? null
      : null;

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Findings" />
        <EmptyState
          icon={<Radar size={20} />}
          title="No analysis available"
          body="Run the deterministic analysis to detect operational issues. Every finding cites its evidence."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Findings"
        description="Detected operational issues compressed from raw signals. Each finding groups related anomalies by metric and severity."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FilterChip
          label="Critical + High"
          count={(counts["CRITICAL"] ?? 0) + (counts["HIGH"] ?? 0)}
          active={filter === "CRITICAL_HIGH"}
          onClick={() => setFilter("CRITICAL_HIGH")}
        />
        <FilterChip
          label="All signals"
          count={anomalies.length}
          active={filter === "ALL"}
          onClick={() => setFilter("ALL")}
        />
        {SEVERITY_ORDER.filter((level) => counts[level]).map((level) => (
          <FilterChip
            key={level}
            label={severity(level).label}
            count={counts[level]}
            tone={severity(level).tone}
            active={filter === level}
            onClick={() => setFilter(level)}
          />
        ))}
      </div>

      {!artifacts ? (
        <SkeletonPanel lines={6} />
      ) : filtered.length === 0 ? (
        <Panel className="p-6 text-center text-sm text-text-2">
          No signals at this severity. The deterministic detector found nothing
          beyond threshold.
        </Panel>
      ) : (
        <>
          {concern && (
            <Panel className="mb-6 p-5">
              <SectionHeading
                title="Top concern"
                caption="The most important signal to review first."
              />
              <button
                onClick={() => setSelectedKey(recordKey(concern))}
                className="w-full text-left"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-text">
                      {signalTitle(concern)}
                      <span className="num ml-2 font-bold text-danger">
                        {formatDeviation(Number(concern.deviation_pct ?? 0))}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-text-muted">
                      {[
                        concern.entity ?? scopeLabel(concern.scope),
                        concern.date
                          ? formatDateShort(String(concern.date))
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <p className="mt-1.5 text-xs leading-relaxed text-text-2">
                      {signalInterpretation(concern)}
                    </p>
                  </div>
                  <Badge tone={severity(concern.severity).tone}>
                    {severity(concern.severity).label}
                  </Badge>
                </div>
              </button>
            </Panel>
          )}

          {groups.length > 0 && (
            <section aria-label="Signals by metric" className="mb-6">
              <SectionHeading
                title="Signals by metric"
                caption="Related detections grouped per metric. Expand a group to investigate."
              />
              <div className="space-y-3">
                {groups.map((group) => (
                  <Accordion
                    key={group.metric}
                    open={openGroup === group.metric}
                    onToggle={() =>
                      setOpenGroup(
                        openGroup === group.metric ? null : group.metric,
                      )
                    }
                    title={
                      <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <span className="text-sm font-semibold text-text">
                          {group.label}
                        </span>
                        <span className="num text-xs text-text-muted">
                          {group.total} signal
                          {group.total === 1 ? "" : "s"}
                        </span>
                      </span>
                    }
                    meta={
                      <span className="num text-[11px] text-text-2">
                        {SEVERITY_ORDER.filter((s) => group.counts[s as keyof SeverityCounts] > 0)
                          .map(
                            (s) =>
                              `${group.counts[s as keyof SeverityCounts]} ${severity(s).label.toLowerCase()}`,
                          )
                          .join(" · ")}
                        {signalPeriodRange(group.members)
                          ? ` · ${signalPeriodRange(group.members)}`
                          : ""}
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
                          <button
                            onClick={() =>
                              setSelectedKey(recordKey(member))
                            }
                            className="min-w-0 text-left"
                          >
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
                          </button>
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
                              {formatDeviation(
                                Number(member.deviation_pct ?? 0),
                              )}
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

          <section aria-label="All signals">
            <SectionHeading
              title={showAll ? "All signals" : `Top ${TOP_COUNT} signals`}
              caption={
                showAll
                  ? `Showing all ${filtered.length} signals matching current filter.`
                  : `Showing ${Math.min(TOP_COUNT, filtered.length)} of ${filtered.length} signals — most severe first.`
              }
            />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(showAll ? filtered : topSignals).map((record) => (
                <SignalCard
                  key={recordKey(record)}
                  record={record}
                  onOpen={() => setSelectedKey(recordKey(record))}
                />
              ))}
            </div>
            {!showAll && filtered.length > TOP_COUNT && (
              <div className="mt-5 flex justify-center">
                <Button
                  variant="ghost"
                  onClick={() => setShowAll(true)}
                >
                  Show all {filtered.length} signals
                </Button>
              </div>
            )}
          </section>
        </>
      )}

      <Drawer
        open={selected !== null}
        onClose={() => setSelectedKey(null)}
        title="Signal detail"
      >
        {selected && <SignalDetail record={selected} />}
      </Drawer>
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

const TONE_DOT: Record<string, string> = {
  danger: "bg-danger",
  warn: "bg-warn",
  info: "bg-accent",
  ok: "bg-ok",
  muted: "bg-line-strong",
};

function FilterChip({
  label,
  count,
  active,
  onClick,
  tone,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  tone?: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "border-accent/60 bg-accent/10 text-text"
          : "border-line-strong text-text-2 hover:text-text"
      }`}
    >
      {tone && (
        <span className={`h-2 w-2 rounded-full ${TONE_DOT[tone] ?? "bg-line-strong"}`} aria-hidden />
      )}
      {label}
      <span className="num text-text-muted">{count}</span>
    </button>
  );
}

function SignalCard({
  record,
  onOpen,
}: {
  record: AnomalyRecord;
  onOpen: () => void;
}) {
  const style = severity(record.severity);
  const deviation = Number(record.deviation_pct ?? 0);
  const adverse = deviationIsAdverse(record.metric, deviation);
  const up = deviationDirection(deviation) === "up";
  return (
    <button onClick={onOpen} className="panel panel-hover p-4 text-left">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={style.tone}>{style.label}</Badge>
        <span
          className={`num flex items-center gap-1 text-sm font-bold ${
            deviation === 0 ? "text-text-2" : adverse ? "text-danger" : "text-ok"
          }`}
        >
          {up ? (
            <ArrowUpRight size={13} aria-hidden />
          ) : (
            <ArrowDownRight size={13} aria-hidden />
          )}
          {formatDeviation(deviation)}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold leading-snug text-text">
        {signalTitle(record)}
      </p>
      <p className="mt-0.5 truncate text-xs text-text-2">
        {record.entity ? String(record.entity) : scopeLabel(record.scope)}
      </p>
      {record.date && (
        <p className="num mt-1 text-[11px] text-text-muted">
          {formatDateShort(String(record.date))}
        </p>
      )}
    </button>
  );
}

/** Curated, human-labeled fields — never a raw dump of internal keys. */
function SignalDetail({ record }: { record: AnomalyRecord }) {
  const style = severity(record.severity);
  const deviation = Number(record.deviation_pct ?? 0);
  const adverse = deviationIsAdverse(record.metric, deviation);

  const observed = Number((record as Record<string, unknown>).value);
  const expected = Number((record as Record<string, unknown>).expected_value);

  // Derived meta rows (skip the visual bars we render separately).
  const rows: [string, string][] = [];
  rows.push(["Detection", anomalyTypeLabel(record.type)]);
  rows.push(["Metric", metricLabel(record.metric)]);
  rows.push(["Scope", scopeLabel(record.scope)]);
  if (record.entity) rows.push(["Entity", String(record.entity)]);
  if (record.date) rows.push(["Date", formatDateShort(String(record.date))]);

  const seen = new Set([
    "type",
    "metric",
    "scope",
    "entity",
    "date",
    "value",
    "expected_value",
    "deviation_pct",
    "severity",
    "evidence",
    "details",
  ]);
  for (const [key, value] of Object.entries(record)) {
    if (seen.has(key) || typeof value === "object") continue;
    rows.push([humanize(key), stringifyScalar(value)]);
  }
  const details = record.details;
  if (details && typeof details === "object") {
    for (const [key, value] of Object.entries(
      details as Record<string, unknown>,
    )) {
      if (typeof value === "object") continue;
      rows.push([humanize(key), stringifyScalar(value)]);
    }
  }

  // Bars for visual comparison (scale relative to the larger value).
  const hasBars = Number.isFinite(observed) && Number.isFinite(expected);
  const barMax = hasBars ? Math.max(observed, expected, 1) : 1;
  const observedPct = hasBars ? (observed / barMax) * 100 : 0;
  const expectedPct = hasBars ? (expected / barMax) * 100 : 0;

  return (
    <div>
      {/* ── Prominent severity badge ── */}
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ${
            style.tone === "danger"
              ? "bg-danger/15 text-danger"
              : style.tone === "warn"
                ? "bg-warn/15 text-warn"
                : "bg-accent/15 text-accent"
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              style.tone === "danger"
                ? "bg-danger"
                : style.tone === "warn"
                  ? "bg-warn"
                  : "bg-accent"
            }`}
            aria-hidden
          />
          {style.label}
        </span>
        <span
          className={`num text-sm font-bold ${
            deviation === 0 ? "text-text-2" : adverse ? "text-danger" : "text-ok"
          }`}
        >
          {formatDeviation(deviation)}
        </span>
      </div>

      <h3 className="mt-3 text-lg font-bold leading-snug text-text">
        {signalTitle(record)}
      </h3>
      <p className="mt-1.5 text-sm leading-relaxed text-text-2">
        {signalInterpretation(record)}
      </p>

      {/* ── Why it was flagged ── */}
      <div className="mt-5 rounded-xl border border-line bg-surface-2/50 px-4 py-3">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
          Why it was flagged
        </p>
        <p className="mt-1.5 text-sm leading-relaxed text-text-2">
          {signalInterpretation(record)}
        </p>
        {Number.isFinite(deviation) && (
          <p
            className={`mt-1.5 text-sm font-semibold ${
              adverse ? "text-danger" : "text-ok"
            }`}
          >
            {adverse ? "Adverse" : "Positive"} deviation of{" "}
            {formatDeviation(deviation)} from the expected baseline — this is a
            {adverse ? " deterioration" : " improvement"} relative to the
            expected value for{" "}
            <span className="font-semibold">{metricLabel(record.metric)}</span>.
          </p>
        )}
      </div>

      {/* ── Observed vs Expected visual comparison ── */}
      {hasBars && (
        <div className="mt-5">
          <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
            Observed vs Expected
          </p>
          <div className="space-y-2.5">
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs font-semibold text-text">
                  Observed
                </span>
                <span className="num text-xs font-bold text-text">
                  {observed.toLocaleString()}
                </span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-full bg-line">
                <div
                  className={`h-full rounded-full transition-all ${
                    adverse ? "bg-danger" : "bg-ok"
                  }`}
                  style={{ width: `${observedPct}%` }}
                />
              </div>
            </div>
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs font-semibold text-text-muted">
                  Expected baseline
                </span>
                <span className="num text-xs text-text-muted">
                  {expected.toLocaleString()}
                </span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-accent/50 transition-all"
                  style={{ width: `${expectedPct}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      <dl className="mt-5 space-y-3">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex justify-between gap-4 border-b border-line pb-2"
          >
            <dt className="text-xs uppercase tracking-wider text-text-muted">
              {label}
            </dt>
            <dd className="num max-w-[60%] break-words text-right text-sm text-text">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-5 rounded-lg border border-line bg-faint px-3 py-2 text-xs leading-relaxed text-text-2">
        Values are deterministic pipeline output. Cross-check this signal in the
        Evidence workspace before acting on it.
      </p>
    </div>
  );
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function stringifyScalar(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value ?? "—");
}
