import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  FileSearch,
  Loader2,
  Play,
  RotateCcw,
  ShieldAlert,
  AlertTriangle,
} from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
  StrengthMeter,
} from "../components/ui/Primitives";
import { Tabs, type TabItem } from "../components/ui/Controls";
import { ErrorBoundary } from "../components/ui/ErrorBoundary";
import { formatDateTime, formatKpiValue } from "../lib/format";
import {
  evidenceEntryTitle,
  evidenceKind,
  kpiMeta,
  periodChangeLabel,
} from "../lib/labels";
import { severity } from "../lib/severity";
import type { EvidenceEntry, Pack } from "../lib/types";

type PackTab = "kpis" | "signals" | "correlations" | "clusters" | "index";

function safeParsePack(raw: unknown): Pack | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (!obj.evidence_index || typeof obj.evidence_index !== "object") return null;
  if (!obj.kpis || typeof obj.kpis !== "object") return null;
  return raw as Pack;
}

function safeGroupEntries(pack: Pack | null): Buckets {
  const buckets: Buckets = {
    kpis: [],
    anomalies: [],
    correlations: [],
    clusters: [],
    other: [],
  };
  if (!pack?.evidence_index) return buckets;

  try {
    const entries = Object.entries(pack.evidence_index);
    for (const pair of entries) {
      const entry = pair[1];
      if (!entry || typeof entry !== "object") continue;
      if (!entry.kind || typeof entry.kind !== "string") {
        buckets.other.push(pair as [string, EvidenceEntry]);
        continue;
      }
      const group = evidenceKind(entry.kind).group;
      if (group in buckets) {
        buckets[group].push(pair as [string, EvidenceEntry]);
      } else {
        buckets.other.push(pair as [string, EvidenceEntry]);
      }
    }
  } catch {
    console.warn("[Evidence] Failed to group evidence entries");
  }
  return buckets;
}

interface EvidenceGroup {
  findingKey: string;
  entries: [string, EvidenceEntry][];
  metric: string;
  entity: string;
  direction: string;
  maxSeverity: string;
  totalCount: number;
}

function groupByFinding(pairs: [string, EvidenceEntry][]): EvidenceGroup[] {
  const map = new Map<string, [string, EvidenceEntry][]>();

  for (const pair of pairs) {
    const [, entry] = pair;
    const metric = String(entry.field ?? entry.metric ?? "").toLowerCase();
    const entity = String(entry.entity ?? "").toLowerCase();
    const deviation = Number(entry.deviation_pct ?? 0);
    const direction = deviation >= 0 ? "up" : "down";
    const findingKey = `${metric}::${entity}::${direction}`;

    if (!map.has(findingKey)) {
      map.set(findingKey, []);
    }
    map.get(findingKey)!.push(pair);
  }

  const groups: EvidenceGroup[] = [];
  for (const [findingKey, entries] of map) {
    const [, firstEntry] = entries[0];
    const metric = String(firstEntry.field ?? firstEntry.metric ?? "");
    const entity = String(firstEntry.entity ?? "");
    const deviation = Number(firstEntry.deviation_pct ?? 0);
    const direction = deviation >= 0 ? "up" : "down";

    let maxSeverity = "LOW";
    let maxWeight = 0;
    for (const [, e] of entries) {
      const s = severity(String(e.severity ?? ""));
      if (s.weight > maxWeight) {
        maxWeight = s.weight;
        maxSeverity = String(e.severity ?? "LOW");
      }
    }

    groups.push({
      findingKey,
      entries,
      metric,
      entity,
      direction,
      maxSeverity,
      totalCount: entries.length,
    });
  }

  return groups.sort((a, b) => {
    const sa = severity(a.maxSeverity).weight;
    const sb = severity(b.maxSeverity).weight;
    if (sb !== sa) return sb - sa;
    return b.totalCount - a.totalCount;
  });
}

export default function Evidence() {
  const { system, artifacts, investigation, startInvestigation } =
    useWorkspace();
  const [tab, setTab] = useState<PackTab>("kpis");
  const [visibleEntries, setVisibleEntries] = useState(24);
  const [packError, setPackError] = useState<string | null>(null);

  const rawPack = investigation.result?.evidence_pack ?? artifacts?.pack ?? null;

  const pack = useMemo(() => {
    setPackError(null);
    try {
      return safeParsePack(rawPack);
    } catch (err) {
      setPackError(
        err instanceof Error ? err.message : "Failed to parse evidence pack"
      );
      return null;
    }
  }, [rawPack]);

  const grouped = useMemo(() => safeGroupEntries(pack), [pack]);
  const signalGroups = useMemo(
    () => (grouped.anomalies.length > 0 ? groupByFinding(grouped.anomalies) : []),
    [grouped.anomalies],
  );

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Evidence" />
        <EmptyState
          icon={<FileSearch size={20} />}
          title="No analysis available"
          body="The evidence pack is generated deterministically with every analysis run. Load data first."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  const hasEvidence = pack && Object.keys(pack.evidence_index ?? {}).length > 0;

  const grounding = investigation.result?.grounding_report;
  const confidence = grounding?.valid ? 10 : grounding ? 4 : null;

  const tabItems: TabItem[] = [
    { id: "kpis", label: "KPIs & Movement", count: grouped.kpis.length },
    { id: "signals", label: "Signals", count: grouped.anomalies.length },
    {
      id: "correlations",
      label: "Correlations",
      count: grouped.correlations.length,
    },
    { id: "clusters", label: "Clusters", count: grouped.clusters.length },
    {
      id: "index",
      label: "Full Index",
      count: Object.keys(pack?.evidence_index ?? {}).length,
    },
  ];

  return (
    <ErrorBoundary
      fallbackTitle="Evidence page could not be rendered"
      fallbackBody="The evidence data appears to be malformed or missing. Try reloading the analysis, or navigate to another page."
    >
      <div>
        <PageHeader
          eyebrow="Intelligence"
          title="Evidence Workspace"
          description="Every number the product shows is traceable to this deterministic pack. Evidence is grouped by finding for focused investigation. AI narratives run only on your explicit action and never overwrite it."
        />

      <ErrorBoundary
        fallbackTitle="Evidence pack could not be rendered"
        fallbackBody="The evidence data appears to be malformed or incomplete. Try reloading the analysis, or navigate to another page."
      >
        {/* DETERMINISTIC EVIDENCE PACK */}
        <Panel className="p-5">
          <SectionHeading
            icon={<BadgeCheck size={15} className="text-accent" aria-hidden />}
            title="Deterministic evidence pack"
            caption={
              system.recovery_context
                ? `Frozen at ${formatDateTime(system.recovery_context.completed_at)} · sensitivity ${system.recovery_context.sensitivity}`
                : "Generated by the last pipeline run."
            }
          />
          {packError && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
              <AlertTriangle size={14} aria-hidden />
              <span>Pack parsing issue: {packError}</span>
            </div>
          )}

          {/* FINDINGS SUMMARY — grouped by metric/entity/direction */}
          {signalGroups.length > 0 && (
            <div className="mb-4">
              <SectionHeading
                title="Evidence by Finding"
                caption={`${signalGroups.length} finding group${signalGroups.length === 1 ? "" : "s"} identified from ${grouped.anomalies.length} signal evidence entries.`}
              />
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {signalGroups.map((group) => {
                  const style = severity(group.maxSeverity);
                  return (
                    <div
                      key={group.findingKey}
                      className="rounded-lg border border-line bg-faint p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge tone={style.tone}>
                          {group.maxSeverity}
                        </Badge>
                        <span className="text-[10px] text-text-muted">
                          {group.totalCount} {group.totalCount === 1 ? "entry" : "entries"}
                        </span>
                      </div>
                      <p className="mt-1.5 text-xs font-semibold text-text">
                        {group.metric}
                        {group.entity ? ` · ${group.entity}` : ""}
                      </p>
                      <p className="mt-0.5 text-[11px] text-text-2">
                        {group.direction === "up" ? "Increase" : "Decrease"} detected
                        {group.entries.length > 0 && ` · ${group.entries.length} supporting observations`}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {pack && !hasEvidence && (
            <EmptyState
              icon={<FileSearch size={20} />}
              title="No evidence available yet"
              body="Run analysis to generate findings."
              action={
                <Link to="/data">
                  <Button>Open Data Workspace</Button>
                </Link>
              }
            />
          )}

          {!pack ? (
            system.analysis_running ? (
              <div className="flex flex-col items-center py-8">
                <Loader2 size={24} className="animate-spin text-accent" />
                <p className="mt-3 text-sm text-text-2">
                  Evidence pack is being generated…
                </p>
                <p className="mt-1 text-xs text-text-muted">
                  This typically takes under a minute.
                </p>
              </div>
            ) : (
              <SkeletonPanel lines={4} />
            )
          ) : (
            <>
              <Tabs
                ariaLabel="Evidence sections"
                items={tabItems}
                active={tab}
                onChange={(id) => {
                  setTab(id as PackTab);
                  setVisibleEntries(24);
                }}
              />
              <div className="pt-4">
                {tab === "kpis" && <KpisTab buckets={grouped} pack={pack} />}
                {tab === "signals" && <SignalsTab buckets={grouped} />}
                {tab === "correlations" && (
                  <EntriesGrid
                    pairs={grouped.correlations}
                    emptyText="No correlation evidence in this run."
                  />
                )}
                {tab === "clusters" && (
                  <EntriesGrid
                    pairs={grouped.clusters}
                    emptyText="No signal clusters were formed in this run."
                  />
                )}
                {tab === "index" && (
                  <EntriesGrid
                    pairs={[
                      ...grouped.kpis,
                      ...grouped.anomalies,
                      ...grouped.correlations,
                      ...grouped.clusters,
                      ...grouped.other,
                    ]}
                    pageSize={visibleEntries}
                    onShowMore={() =>
                      setVisibleEntries((n) => n + 24)
                    }
                    emptyText="No evidence recorded."
                  />
                )}
              </div>
            </>
          )}
        </Panel>

        {/* AI INVESTIGATION CONSOLE */}
        <Panel className="mt-6 p-5">
          <SectionHeading
            icon={<BadgeCheck size={15} className="text-accent" aria-hidden />}
            title="AI investigation"
            caption="AI-assisted investigation reads the frozen evidence pack and returns a grounded narrative with citations. Deterministic evidence above is never modified."
          />
          <InvestigationConsole
            aiAvailable={system.ai_available === true}
            status={investigation.status}
            error={investigation.error}
            onRun={() => void startInvestigation()}
          />
          {system.ai_available && (
            <p className="mt-2 text-[10px] uppercase tracking-wider text-text-muted">
              Model: {system.gemini_model}
            </p>
          )}

          {grounding && (
            <div className="mt-4 grid gap-3 rounded-xl border border-line bg-faint p-4 md:grid-cols-[220px_1fr]">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                  Grounding verification
                </p>
                <div className="mt-2">
                  <Badge tone={grounding.valid ? "ok" : "danger"}>
                    {grounding.valid ? "All citations resolved" : "Verification issues"}
                  </Badge>
                </div>
                {confidence !== null && (
                  <div className="mt-3 max-w-[180px]">
                    <StrengthMeter
                      value={confidence}
                      maximum={10}
                      label="Grounding strength"
                    />
                  </div>
                )}
              </div>
              <ul className="space-y-1 text-xs leading-relaxed text-text-2">
                {(grounding.citation_errors ?? []).map((error, i) => (
                  <li key={`c${i}`}>· citation: {error}</li>
                ))}
                {(grounding.numeric_errors ?? []).map((error, i) => (
                  <li key={`n${i}`}>· numeric: {error}</li>
                ))}
                {(grounding.causation_errors ?? []).map((error, i) => (
                  <li key={`x${i}`}>· causation: {error}</li>
                ))}
                {(grounding.unsupported_claims ?? []).map((claim, i) => (
                  <li key={`u${i}`}>· unsupported: {claim}</li>
                ))}
                {grounding.valid && (
                  <li>
                    Every claim cites a deterministic evidence reference; all
                    numbers were verified against the frozen pack before display.
                  </li>
                )}
              </ul>
            </div>
          )}
        </Panel>

        {/* NARRATIVE REPORT */}
        {investigation.result && (
          <Panel className="mt-4 p-5">
            <SectionHeading
              title="AI investigation report"
              caption="AI-generated · grounded in the evidence pack · clearly separated from deterministic output."
            />
            <p className="text-sm leading-relaxed text-text-2">
              {investigation.result.narrative.executive_summary}
            </p>
            <div className="mt-4 grid gap-6 lg:grid-cols-2">
              <NarrativeList
                heading="Key findings"
                items={investigation.result.narrative.key_findings}
              />
              <NarrativeList
                heading="Operational interpretation"
                items={investigation.result.narrative.operational_interpretation}
              />
            </div>
            {investigation.result.hypotheses?.length > 0 && (
              <div className="mt-6">
                <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                  Hypotheses for human review
                </h3>
                <ul className="mt-2 space-y-2">
                  {investigation.result.hypotheses.map((h, i) => (
                    <li
                      key={`h${i}`}
                      className="rounded-lg border border-line bg-faint px-3 py-2.5"
                    >
                      <p className="text-sm text-text">{h.hypothesis}</p>
                      <p className="num mt-1 text-[11px] text-text-muted">
                        confidence {(h.confidence * 100).toFixed(0)}%
                        {h.factor ? ` · factor: ${h.factor}` : ""}
                        {h.evidence_ids.length > 0 &&
                          ` · refs ${h.evidence_ids.join(", ")}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        )}
      </ErrorBoundary>
    </div>
    </ErrorBoundary>
  );
}

// --- Investigation console -----------------------------------------------------------------------------

function InvestigationConsole({
  aiAvailable,
  status,
  error,
  onRun,
}: {
  aiAvailable: boolean;
  status: string;
  error: string | null;
  onRun: () => void;
}) {
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    if (status !== "running") {
      setElapsed(null);
      setStageIndex(0);
      return;
    }
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [status]);

  useEffect(() => {
    if (status !== "running") return;
    const timer = window.setInterval(
      () => setStageIndex((i) => Math.min(i + 1, INVESTIGATION_STAGES.length - 1)),
      25_000,
    );
    return () => window.clearInterval(timer);
  }, [status]);

  if (!aiAvailable) {
    return (
      <p className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/[0.08] px-3 py-2.5 text-sm text-warn">
        <ShieldAlert size={15} aria-hidden />
        AI investigation is not configured — deterministic evidence remains fully
        available above.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {status === "running" ? (
        <div className="flex flex-col gap-1">
          <span className="inline-flex items-center gap-2 text-sm font-semibold text-accent">
            <Loader2 size={15} className="animate-spin" aria-hidden />
            AI investigation running
            {elapsed !== null && (
              <span className="num text-xs text-text-muted">{elapsed}s</span>
            )}
          </span>
          <span aria-live="polite" className="text-xs text-text-2">
            {INVESTIGATION_STAGES[stageIndex]}
          </span>
        </div>
      ) : (
        <Button onClick={onRun}>
          {status === "error" || status === "complete" ? (
            <RotateCcw size={14} />
          ) : (
            <Play size={14} />
          )}
          {status === "error"
            ? "Retry Investigation"
            : status === "complete"
              ? "Re-run Investigation"
              : "Run AI Investigation"}
        </Button>
      )}
      {status === "complete" && <Badge tone="ok">Grounded narrative ready</Badge>}
      {status !== "running" && status !== "complete" && !error && (
        <span className="text-xs text-text-muted">
          Typical duration: under a minute.
        </span>
      )}
      {error && (
        <p role="alert" className="w-full text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

const INVESTIGATION_STAGES = [
  "Preparing the frozen evidence pack…",
  "Analyzing operational signals…",
  "Generating grounded findings…",
  "Composing the cited narrative…",
];

// --- Pack tabs ------------------------------------------------------------------------------------------

type Buckets = Record<string, [string, EvidenceEntry][]>;

function KpisTab({
  buckets,
  pack,
}: {
  buckets: Buckets;
  pack: Pack;
}) {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(pack.kpis ?? {}).map(([key, value]) => {
          const meta = kpiMeta(key);
          return (
            <div
              key={key}
              title={meta.description}
              className="rounded-xl border border-line bg-faint p-3.5"
            >
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                {meta.title}
              </p>
              <p className="num mt-1 text-lg font-bold text-text">
                {formatKpiValue(value, meta.kind)}
              </p>
            </div>
          );
        })}
      </div>

      {Object.keys(pack.period_comparison?.changes_pct ?? {}).length > 0 && (
        <div>
          <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
            Period-over-period movement
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(pack.period_comparison.changes_pct).map(
              ([key, pct]) => (
                <span
                  key={key}
                  className="flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-xs"
                >
                  <span className="text-text-2">{periodChangeLabel(key)}</span>
                  {pct === null ? (
                    <span className="num text-text-muted">—</span>
                  ) : (
                    <span
                      className={`num font-bold ${Number(pct) >= 0 ? "text-ok" : "text-danger"}`}
                    >
                      {Number(pct) >= 0 ? "+" : ""}
                      {Number(pct).toFixed(1)}%
                    </span>
                  )}
                </span>
              ),
            )}
          </div>
        </div>
      )}

      <EntriesGrid pairs={buckets.kpis.filter(([, e]) => e.kind === "performer")} />
    </div>
  );
}

function SignalsTab({
  buckets,
}: {
  buckets: Buckets;
}) {
  const groups = useMemo(
    () => groupByFinding(buckets.anomalies),
    [buckets.anomalies],
  );
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  if (groups.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-text-2">
        No anomaly evidence recorded in this run.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const key = group.findingKey;
        const isExpanded = expandedGroup === key;
        const firstEntry = group.entries[0][1];
        const strongestEntry = group.entries.reduce((best, [, e]) => {
          const sw = severity(String(e.severity ?? "")).weight;
          const bw = severity(String(best.severity ?? "")).weight;
          return sw > bw ? e : best;
        }, firstEntry);

        const dates = group.entries
          .map(([, e]) => String(e.date ?? ""))
          .filter(Boolean)
          .sort();
        const dateRange =
          dates.length > 1
            ? `${dates[0]} – ${dates[dates.length - 1]}`
            : dates[0] ?? "";

        const directionLabel =
          group.direction === "up" ? "Increase detected" : "Decrease detected";
        const severityBadge = severity(group.maxSeverity);

        return (
          <div
            key={key}
            className="rounded-xl border border-line bg-faint"
          >
            <button
              type="button"
              className="flex w-full items-start gap-3 p-4 text-left"
              onClick={() =>
                setExpandedGroup(isExpanded ? null : key)
              }
            >
              <Badge tone={severityBadge.tone}>
                {group.maxSeverity}
              </Badge>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-text">
                  {group.metric}
                  {group.entity ? ` · ${group.entity}` : ""}
                </p>
                <p className="mt-0.5 text-xs text-text-2">
                  {directionLabel}
                  {dateRange ? ` · ${dateRange}` : ""}
                  {group.totalCount > 1
                    ? ` · ${group.totalCount} observations`
                    : ""}
                </p>
              </div>
              {typeof strongestEntry.deviation_pct === "number" && (
                <span className="num shrink-0 text-xs font-bold text-danger">
                  {strongestEntry.deviation_pct >= 0 ? "+" : ""}
                  {Math.abs(strongestEntry.deviation_pct).toFixed(1)}%
                </span>
              )}
            </button>
            {isExpanded && (
              <div className="border-t border-line px-4 pb-4 pt-3">
                <div className="grid gap-3 text-xs md:grid-cols-2">
                  <div>
                    <span className="font-bold uppercase tracking-wider text-text-muted">
                      Metric
                    </span>
                    <span className="ml-2 text-text-2">{group.metric}</span>
                  </div>
                  {group.entity && (
                    <div>
                      <span className="font-bold uppercase tracking-wider text-text-muted">
                        Entity
                      </span>
                      <span className="ml-2 text-text-2">{group.entity}</span>
                    </div>
                  )}
                  <div>
                    <span className="font-bold uppercase tracking-wider text-text-muted">
                      Direction
                    </span>
                    <span className="ml-2 text-text-2">{group.direction === "up" ? "Above baseline" : "Below baseline"}</span>
                  </div>
                  <div>
                    <span className="font-bold uppercase tracking-wider text-text-muted">
                      Observations
                    </span>
                    <span className="ml-2 text-text-2">{group.totalCount}</span>
                  </div>
                  {dateRange && (
                    <div>
                      <span className="font-bold uppercase tracking-wider text-text-muted">
                        Date range
                      </span>
                      <span className="ml-2 text-text-2">{dateRange}</span>
                    </div>
                  )}
                  {strongestEntry.observed !== undefined &&
                    strongestEntry.observed !== null && (
                      <div>
                        <span className="font-bold uppercase tracking-wider text-text-muted">
                          Observed
                        </span>
                        <span className="ml-2 text-text-2">
                          {typeof strongestEntry.observed === "number"
                            ? strongestEntry.observed.toLocaleString()
                            : String(strongestEntry.observed)}
                        </span>
                      </div>
                    )}
                  {strongestEntry.expected !== undefined &&
                    strongestEntry.expected !== null && (
                      <div>
                        <span className="font-bold uppercase tracking-wider text-text-muted">
                          Expected
                        </span>
                        <span className="ml-2 text-text-2">
                          {typeof strongestEntry.expected === "number"
                            ? strongestEntry.expected.toLocaleString()
                            : String(strongestEntry.expected)}
                        </span>
                      </div>
                    )}
                  {(() => {
                    const deviations = group.entries
                      .map(([, e]) => e.deviation_pct)
                      .filter((d): d is number => typeof d === "number");
                    if (deviations.length === 0) return null;
                    const min = Math.min(...deviations);
                    const max = Math.max(...deviations);
                    const rangeLabel =
                      min === max
                        ? `${min >= 0 ? "+" : ""}${Math.abs(min).toFixed(1)}%`
                        : `${min >= 0 ? "+" : ""}${Math.abs(min).toFixed(1)}% — ${max >= 0 ? "+" : ""}${Math.abs(max).toFixed(1)}%`;
                    return (
                      <div>
                        <span className="font-bold uppercase tracking-wider text-text-muted">
                          Deviation range
                        </span>
                        <span className="ml-2 font-bold text-danger">
                          {rangeLabel}
                        </span>
                      </div>
                    );
                  })()}
                </div>
                {group.entries.length > 0 && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs font-bold uppercase tracking-wider text-text-muted">
                      Supporting observations ({group.entries.length})
                    </summary>
                    <div className="mt-2 overflow-x-auto rounded-lg border border-line">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-line bg-faint/50 text-left text-[10px] uppercase tracking-wider text-text-muted">
                            <th className="px-2.5 py-1.5">Ref</th>
                            <th className="px-2.5 py-1.5">Observation</th>
                            <th className="px-2.5 py-1.5">Date</th>
                            <th className="px-2.5 py-1.5 text-right">Deviation</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-line">
                          {group.entries.map(([id, e]) => (
                            <tr key={id} className="text-text-2">
                              <td className="px-2.5 py-1.5">
                                <RefChip id={id} />
                              </td>
                              <td className="px-2.5 py-1.5 text-text">
                                {String(e.label ?? evidenceEntryTitle(e))}
                              </td>
                              <td className="px-2.5 py-1.5 text-text-muted">
                                {e.date ? String(e.date) : "—"}
                              </td>
                              <td className="px-2.5 py-1.5 text-right">
                                {typeof e.deviation_pct === "number" ? (
                                  <span className="num font-bold text-danger">
                                    {e.deviation_pct >= 0 ? "+" : ""}
                                    {Math.abs(e.deviation_pct).toFixed(1)}%
                                  </span>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EntriesGrid({
  pairs,
  pageSize,
  onShowMore,
  emptyText = "No entries.",
}: {
  pairs: [string, EvidenceEntry][];
  pageSize?: number;
  onShowMore?: () => void;
  emptyText?: string;
}) {
  if (pairs.length === 0) {
    return <p className="py-6 text-center text-sm text-text-2">{emptyText}</p>;
  }
  const shown = pageSize ? pairs.slice(0, pageSize) : pairs;
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {shown.map(([id, entry]) => {
          const kind = evidenceKind(entry.kind);
          return (
            <div
              key={id}
              className="rounded-xl border border-line bg-faint p-3.5"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-semibold leading-snug text-text">
                  {evidenceEntryTitle(entry)}
                </p>
                <Badge tone="muted" withIcon={false}>
                  {kind.label}
                </Badge>
              </div>
              {entry.value !== undefined && entry.value !== null && (
                <p className="num mt-1 text-sm text-text-2">
                  {typeof entry.value === "number"
                    ? entry.value.toLocaleString()
                    : String(entry.value)}
                </p>
              )}
              {typeof entry.deviation_pct === "number" && (
                <p className="num mt-0.5 text-xs font-bold text-danger">
                  +{Math.abs(entry.deviation_pct).toFixed(1)}% vs baseline
                </p>
              )}
              <RefChip id={id} />
            </div>
          );
        })}
      </div>
      {pageSize && pairs.length > shown.length && (
        <div className="mt-4 text-center">
          <Button variant="ghost" onClick={onShowMore}>
            Show more ({pairs.length - shown.length} remaining)
          </Button>
        </div>
      )}
    </div>
  );
}

function RefChip({ id }: { id: string }) {
  return (
    <span
      title={`Citation reference ${id}`}
      className="num mt-2 inline-block rounded border border-line px-1.5 py-0.5 text-[10px] text-text-muted"
    >
      ref {id}
    </span>
  );
}

// --- Narrative -------------------------------------------------------------------------------------------

function NarrativeList({
  heading,
  items,
}: {
  heading: string;
  items: { claim: string; evidence_ids: string[] }[];
}) {
  return (
    <section aria-label={heading}>
      <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
        {heading}
      </h3>
      <ul className="mt-2 space-y-2.5">
        {(items ?? []).map((item, index) => (
          <li key={index} className="border-l-2 border-accent/50 pl-3">
            <p className="text-sm leading-relaxed text-text-2">{item.claim}</p>
            {item.evidence_ids?.length > 0 && (
              <p className="num mt-1 text-[11px] text-accent">
                [{item.evidence_ids.join(", ")}]
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
