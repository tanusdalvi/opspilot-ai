import { useMemo } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  Database,
  Play,
  Radar,
  ShieldCheck,
  Sparkles,
  FileSearch,
  AlertTriangle,
  ChevronRight,
  Activity,
  CheckCircle2,
} from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  Skeleton,
} from "../components/ui/Primitives";
import { formatDateShort, formatPct } from "../lib/format";
import { metricLabel, periodChangeLabel } from "../lib/labels";
import {
  presentPosture,
} from "../lib/signals";
import { severity } from "../lib/severity";
import type { AnomalyRecord, Finding } from "../lib/types";

export default function Overview() {
  const { system, artifacts } = useWorkspace();
  const ready = system?.artifacts_ready === true;
  const anomalies: AnomalyRecord[] = useMemo(
    () => artifacts?.anomaly_result?.anomalies ?? [],
    [artifacts],
  );
  const findings: Finding[] = useMemo(
    () => artifacts?.findings ?? [],
    [artifacts],
  );
  const posture = presentPosture(artifacts?.posture, anomalies);

  const topFinding = findings.length > 0 ? findings[0] : null;
  const restFindings = findings.slice(1, 5);

  return (
    <div>
      {/* ── 1. Hero Section — Operational Posture ── */}
      <OperationalPosture
        ready={ready}
        system={system}
        posture={posture}
        findingCount={findings.length}
        anomalyCount={anomalies.length}
      />

      {/* ── 2. Top Finding ── */}
      {ready && topFinding && (
        <section aria-label="Top finding" className="mt-6">
          <TopFindingCard finding={topFinding} totalFindings={findings.length} />
        </section>
      )}

      {/* ── 3. Key Findings Summary ── */}
      {ready && restFindings.length > 0 && (
        <section aria-label="Key findings" className="mt-5">
          <SectionHeading
            icon={<AlertTriangle size={15} className="text-accent" aria-hidden />}
            title="Key findings"
            caption={`${findings.length} total ${findings.length === 1 ? "issue" : "issues"} detected across ${anomalies.length} signals.`}
            actions={
              <Link to="/anomalies">
                <Button variant="ghost">
                  View all findings <ArrowRight size={14} />
                </Button>
              </Link>
            }
          />
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {restFindings.map((finding, i) => (
              <CompactFindingCard key={finding.finding_id} finding={finding} index={i} />
            ))}
          </div>
        </section>
      )}

      {ready && !topFindingsExist(findings) && (
        <section aria-label="Findings" className="mt-6">
          <Panel className="p-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 size={18} className="text-ok" aria-hidden />
              <div>
                <p className="text-sm font-semibold text-text">No issues detected</p>
                <p className="text-xs text-text-muted">
                  The latest analysis found no operational issues requiring attention.
                </p>
              </div>
              <div className="ml-auto">
                <Link to="/analytics">
                  <Button variant="ghost">
                    View Analytics <ArrowRight size={13} />
                  </Button>
                </Link>
              </div>
            </div>
          </Panel>
        </section>
      )}

      {/* ── 4. What Changed + Recommended Actions ── */}
      {ready && (
        <section
          aria-label="Changes and actions"
          className="mt-6 grid gap-4 lg:grid-cols-[1fr_1fr]"
        >
          <WhatChanged />
          <RecommendedActions findings={findings} />
        </section>
      )}

      {/* ── 5. Next Step (contextual CTA) ── */}
      <NextStep findingCount={findings.filter((f) => f.severity === "CRITICAL" || f.severity === "HIGH").length} />

      {/* ── 6. Data Context Footer ── */}
      {ready && (
        <section aria-label="Data context" className="mt-6 mb-8">
          <DataFooter system={system} artifacts={artifacts} />
        </section>
      )}
    </div>
  );
}

// ─── 1. Operational Posture Hero ──────────────────────────────────────────────

function OperationalPosture({
  ready,
  system,
  posture,
  findingCount,
  anomalyCount,
}: {
  ready: boolean;
  system: ReturnType<typeof useWorkspace>["system"];
  posture: ReturnType<typeof presentPosture>;
  findingCount: number;
  anomalyCount: number;
}) {
  if (!system?.dataset) {
    return (
      <PageHeader
        eyebrow="Operations Overview"
        title="No data loaded"
        description="Load a dataset to bring your operations into view."
      />
    );
  }

  if (!ready) {
    return (
      <div>
        <PageHeader
          eyebrow="Operations Overview"
          title={greeting()}
          description="Run the analysis to see what needs your attention."
        />
      </div>
    );
  }

  const needsAttention = posture?.attentionNeeded ?? false;
  const score = posture?.score ?? 100;
  const band = posture?.band ?? "Steady";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <Panel className="p-5">
        <div className="flex flex-wrap items-start gap-5">
          {/* Status indicator */}
          <div className="flex items-center gap-3">
            <span
              className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                needsAttention
                  ? "border-danger/30 bg-danger/10 text-danger"
                  : "border-ok/30 bg-ok/10 text-ok"
              }`}
            >
              {needsAttention ? (
                <Activity size={20} />
              ) : (
                <ShieldCheck size={20} />
              )}
            </span>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-text-muted">
                Operational Posture
              </p>
              <h1
                className={`text-xl font-bold tracking-tight ${
                  needsAttention ? "text-danger" : "text-ok"
                }`}
              >
                {needsAttention
                  ? "Operations need attention"
                  : "Operations are stable"}
              </h1>
              {posture && (
                <p className="mt-0.5 text-xs text-text-2">{posture.summary}</p>
              )}
            </div>
          </div>

          {/* Score gauge */}
          <div className="ml-auto flex items-center gap-4">
            <div className="text-right">
              <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
                Posture Score
              </p>
              <p className="num mt-0.5 text-2xl font-bold text-text">
                {score}
              </p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                {band}
              </p>
            </div>
            <div className="h-14 w-1.5 rounded-full bg-surface-2 overflow-hidden">
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: `${Math.max(score, 5)}%` }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                className={`w-full rounded-full ${
                  score >= 80 ? "bg-ok" : score >= 60 ? "bg-warn" : "bg-danger"
                }`}
              />
            </div>
          </div>

          {/* Quick counts */}
          <div className="flex gap-5 border-l border-border pl-5">
            <div>
              <p className="num text-lg font-bold text-text">{findingCount}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                {findingCount === 1 ? "Finding" : "Findings"}
              </p>
            </div>
            <div>
              <p className="num text-lg font-bold text-text">{anomalyCount}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                Signals
              </p>
            </div>
          </div>
        </div>
      </Panel>
    </motion.div>
  );
}

// ─── 2. Top Finding ──────────────────────────────────────────────────────────

function TopFindingCard({
  finding,
  totalFindings,
}: {
  finding: Finding;
  totalFindings: number;
}) {
  const style = severity(finding.severity);
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <SectionHeading
        icon={<AlertTriangle size={15} className="text-danger" aria-hidden />}
        title="Top finding"
        caption="The most severe issue requiring your attention."
      />
      <Link
        to="/anomalies"
        className="panel panel-hover block p-5 focus-visible:outline-accent"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge tone={style.tone}>{style.label}</Badge>
              <span className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
                {finding.signal_count} signal{finding.signal_count !== 1 ? "s" : ""}
              </span>
              {finding.entities.length > 0 && (
                <>
                  <span className="text-text-muted">·</span>
                  <span className="text-[10px] text-text-muted">
                    {finding.entities.length === 1
                      ? finding.entities[0]
                      : `${finding.entities.length} regions`}
                  </span>
                </>
              )}
            </div>

            <h2 className="mt-3 text-base font-bold leading-snug text-text">
              {finding.title}
            </h2>
            <p className="mt-1.5 text-sm leading-relaxed text-text-2">
              {finding.headline}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-text-muted">
              <span>
                Metric: <span className="font-medium text-text-2">{metricLabel(finding.metric)}</span>
              </span>
              {finding.start_date && (
                <span>
                  {finding.start_date === finding.end_date
                    ? formatDateShort(finding.start_date)
                    : `${formatDateShort(finding.start_date)} – ${formatDateShort(finding.end_date!)}`}
                </span>
              )}
            </div>
          </div>

          <div className="shrink-0 flex flex-col items-end gap-2">
            <span className="num text-lg font-bold text-danger">
              {formatPct(finding.max_deviation_pct)}
            </span>
            <span className="text-[10px] text-text-muted">max deviation</span>
            <div className="mt-2 flex items-center gap-1 text-[11px] font-medium text-accent">
              View details <ChevronRight size={12} />
            </div>
          </div>
        </div>
      </Link>

      {totalFindings > 1 && (
        <div className="mt-2 text-center">
          <Link
            to="/anomalies"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
          >
            {totalFindings - 1} more {totalFindings - 1 === 1 ? "finding" : "findings"}
            <ChevronRight size={13} />
          </Link>
        </div>
      )}
    </motion.div>
  );
}

// ─── 3. Compact Finding Cards ────────────────────────────────────────────────

function CompactFindingCard({ finding, index }: { finding: Finding; index: number }) {
  const style = severity(finding.severity);
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.06 }}
    >
      <Link
        to="/anomalies"
        className="panel panel-hover block h-full p-4 focus-visible:outline-accent"
      >
        <div className="flex items-center justify-between gap-2">
          <Badge tone={style.tone}>{style.label}</Badge>
          <span className="num text-xs font-bold text-danger">
            {formatPct(finding.max_deviation_pct)}
          </span>
        </div>
        <p className="mt-2 text-sm font-semibold leading-snug text-text line-clamp-2">
          {finding.title}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-text-2 line-clamp-2">
          {finding.headline}
        </p>
        <div className="mt-2.5 flex items-center gap-1 text-[11px] font-medium text-accent">
          View details <ChevronRight size={12} />
        </div>
      </Link>
    </motion.div>
  );
}

// ─── 4. What Changed ─────────────────────────────────────────────────────────

function WhatChanged() {
  const { artifacts, system } = useWorkspace();
  const changes = artifacts?.period_comparison?.changes_pct ?? {};
  const entries = Object.entries(changes)
    .filter(([, value]) => typeof value === "number" && value !== null)
    .sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))
    .slice(0, 4);

  return (
    <Panel className="p-5">
      <SectionHeading
        icon={<Radar size={15} className="text-accent" aria-hidden />}
        title="What changed"
        caption="Largest period-over-period movements across tracked metrics."
      />
      {!artifacts ? (
        <div className="mt-3 space-y-2.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className={`h-8 ${i % 2 ? "w-4/5" : "w-full"}`} />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <p className="mt-3 text-xs text-text-muted">
          Not enough history for a comparison window.
          {system?.dataset ? "" : " Load a dataset to begin."}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map(([key, value], i) => {
            const numeric = Number(value);
            const positive = numeric >= 0;
            return (
              <motion.li
                key={key}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.28, delay: i * 0.06 }}
                className="flex items-center gap-3 text-sm"
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border ${
                    positive
                      ? "border-ok/30 bg-ok/10 text-ok"
                      : "border-danger/30 bg-danger/10 text-danger"
                  }`}
                  aria-hidden
                >
                  {positive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                </span>
                <span className="min-w-0 flex-1 truncate text-text-2">
                  {periodChangeLabel(key)}
                </span>
                <span
                  className={`num text-sm font-bold ${
                    positive ? "text-ok" : "text-danger"
                  }`}
                >
                  {formatPct(numeric)}
                </span>
              </motion.li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

// ─── 5. Recommended Actions ──────────────────────────────────────────────────

function RecommendedActions({ findings }: { findings: Finding[] }) {
  const { system } = useWorkspace();
  const hasDataset = system?.dataset != null;
  const ready = system?.artifacts_ready === true;

  if (!hasDataset || !ready) return null;

  const priorityFindings = findings.filter(
    (f) => f.severity === "CRITICAL" || f.severity === "HIGH",
  );
  const actions: { icon: React.ReactNode; title: string; body: string; to: string; cta: string }[] = [];

  if (priorityFindings.length > 0) {
    actions.push({
      icon: <Sparkles size={15} className="text-accent" aria-hidden />,
      title: "Review priority issues",
      body: `${priorityFindings.length} high-priority ${priorityFindings.length === 1 ? "issue needs" : "issues need"} review.`,
      to: "/action-center",
      cta: "Open Action Center",
    });
  }

  if ((system?.ai_available ?? false) && system?.investigation_status !== "complete") {
    actions.push({
      icon: <FileSearch size={15} className="text-accent" aria-hidden />,
      title: "Run AI investigation",
      body: "Get grounded explanations for detected signals.",
      to: "/evidence",
      cta: "Investigate",
    });
  }

  if (actions.length === 0) {
    actions.push({
      icon: <ShieldCheck size={15} className="text-ok" aria-hidden />,
      title: "All clear",
      body: "No pending actions. Monitor for changes.",
      to: "/analytics",
      cta: "View Analytics",
    });
  }

  return (
    <Panel className="p-5">
      <SectionHeading
        icon={<Sparkles size={15} className="text-accent" aria-hidden />}
        title="Recommended actions"
        caption="Suggested next steps based on current findings."
      />
      <ul className="mt-2 space-y-3">
        {actions.slice(0, 3).map((action) => (
          <li key={action.to + action.title}>
            <Link
              to={action.to}
              className="flex items-center gap-3 rounded-lg border border-border/50 p-3 transition-colors hover:border-accent/40 hover:bg-accent/5"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-accent/20 bg-accent/10">
                {action.icon}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-text">{action.title}</p>
                <p className="text-xs text-text-muted">{action.body}</p>
              </div>
              <span className="text-[11px] font-medium text-accent">{action.cta}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ─── Next Step (contextual CTA) ──────────────────────────────────────────────

function NextStep({ findingCount }: { findingCount: number }) {
  const { system } = useWorkspace();
  const hasDataset = system?.dataset != null;
  const ready = system?.artifacts_ready === true;
  const running = system?.analysis_running === true;

  let icon = <Database size={16} aria-hidden />;
  let title = "Load a dataset";
  let body = "Start with the bundled demo data or upload your own CSV.";
  let action = (
    <Link to="/data">
      <Button>Open Data Workspace</Button>
    </Link>
  );

  if (hasDataset && !ready && !running) {
    icon = <Play size={16} aria-hidden />;
    title = "Run your first analysis";
    body = "Your dataset is ready. Run the analysis to detect operational patterns.";
    action = (
      <Link to="/data">
        <Button>Run Analysis</Button>
      </Link>
    );
  } else if (ready) {
    if (
      (system?.ai_available ?? false) &&
      system?.investigation_status !== "complete"
    ) {
      icon = <FileSearch size={16} aria-hidden />;
      title = "Deepen the investigation";
      body = "Run an AI investigation to get grounded explanations for the detected signals.";
      action = (
        <Link to="/evidence">
          <Button variant="subtle">Investigate</Button>
        </Link>
      );
    } else if (findingCount > 0) {
      icon = <Sparkles size={16} aria-hidden />;
      title = "Review recommended actions";
      body = `${findingCount} high-priority ${findingCount === 1 ? "issue needs" : "issues need"} attention.`;
      action = (
        <Link to="/action-center">
          <Button variant="subtle">Open Action Center</Button>
        </Link>
      );
    } else {
      return null;
    }
  }

  return (
    <section aria-label="Recommended next step" className="mt-6">
      <Panel className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-accent/30 bg-accent/10 text-accent">
            {icon}
          </span>
          <div>
            <p className="text-sm font-semibold text-text">{title}</p>
            <p className="text-xs text-text-2">{body}</p>
          </div>
        </div>
        <div className="ml-auto">{action}</div>
      </Panel>
    </section>
  );
}

// ─── 6. Data Context Footer ──────────────────────────────────────────────────

function DataFooter({
  system,
  artifacts,
}: {
  system: ReturnType<typeof useWorkspace>["system"];
  artifacts: ReturnType<typeof useWorkspace>["artifacts"];
}) {
  const dataset = system?.dataset;
  if (!dataset) return null;

  const profile = dataset.capability_profile;
  const dateCoverage = dataset.date_coverage;
  const capabilityCount = profile
    ? Object.values(profile.capabilities).filter(Boolean).length
    : null;
  const totalCapabilities = profile
    ? Object.values(profile.capabilities).length
    : null;

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] text-text-muted">
        <span className="flex items-center gap-1.5">
          <Database size={12} aria-hidden />
          <span className="font-medium text-text-2">{dataset.name}</span>
        </span>
        <span>{artifacts?.row_count ?? dataset.rows} rows</span>
        {dataset.columns && <span>{dataset.columns} columns</span>}
        {dateCoverage && (
          <span>
            {formatDateShort(dateCoverage.first)} – {formatDateShort(dateCoverage.last)}
            <span className="ml-1">({dateCoverage.days} days)</span>
          </span>
        )}
        {capabilityCount !== null && totalCapabilities !== null && (
          <span>
            <span className="font-medium text-text-2">{capabilityCount}</span>
            /{totalCapabilities} capabilities enabled
          </span>
        )}
        {profile?.dataset_class && (
          <span>
            Class <span className="font-medium text-text-2">{profile.dataset_class}</span>
          </span>
        )}
      </div>
    </Panel>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function topFindingsExist(findings: Finding[]): boolean {
  return findings.length > 0;
}
