import { useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardList, Sparkles, ChevronRight, Info, Target, TrendingUp } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { priorityLabel, priorityTone, statusLabel, statusTone } from "../lib/severity";
import type { RecommendationRecord, Finding } from "../lib/types";

export default function Recommendations() {
  const { system, artifacts, ensurePlan } = useWorkspace();
  const [plan, setPlan] = useState<RecommendationRecord[] | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const findings: Finding[] = artifacts?.findings ?? [];

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Decide & Act" title="Recommendations" />
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="No analysis available"
          body="Recommendations are generated from the evidence pack after analysis. Load data first."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const payload = await ensurePlan();
      setPlan(payload.plan.recommendations);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  const recommendations =
    plan ??
    (artifacts
      ? (
          artifacts as unknown as {
            plan?: { recommendations?: RecommendationRecord[] };
          }
        ).plan?.recommendations ??
        null
      : null);

  return (
    <div>
      <PageHeader
        eyebrow="Decide & Act"
        title="Recommended Actions"
        description="AI-generated operational actions based on detected findings. Each recommendation targets a specific problem and cites its supporting evidence."
      />

      <Panel className="mb-4 flex flex-wrap items-center justify-between gap-3 p-5">
        <SectionHeading
          title="Action plan"
          caption={
            recommendations
              ? `${recommendations.length} recommendations from ${findings.length} findings.`
              : "Generate a plan from the current findings."
          }
        />
        <Button onClick={() => void handleGenerate()} disabled={generating}>
          <Sparkles size={14} />
          {generating
            ? "Generating…"
            : recommendations
              ? "Regenerate Plan"
              : "Generate Plan"}
        </Button>
      </Panel>

      {error && (
        <p className="mb-4 rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {!recommendations && generating ? (
        <div className="grid gap-3 md:grid-cols-2">
          <SkeletonPanel lines={3} />
          <SkeletonPanel lines={3} />
        </div>
      ) : !recommendations ? (
        <Panel className="p-6 text-center text-sm text-text-2">
          No plan yet for this session. Generate one to see recommended actions
          for the detected findings.
        </Panel>
      ) : (
        <div className="space-y-3">
          {[...recommendations]
            .sort(
              (a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0),
            )
            .map((rec, i) => (
              <RecommendationCard
                key={rec.recommendation_id}
                rec={rec}
                index={i}
                findings={findings}
              />
            ))}
          <Link
            to="/review"
            className="panel panel-hover flex items-center justify-center p-3 text-sm font-semibold text-accent"
          >
            Review all recommendations <ChevronRight size={14} />
          </Link>
        </div>
      )}
    </div>
  );
}

function RecommendationCard({
  rec,
  index: _index,
  findings,
}: {
  rec: RecommendationRecord;
  index: number;
  findings: Finding[];
}) {
  const targetMetric = String(rec.target_metric ?? "");
  const targetEntity = rec.target_entity as string | null;
  const linkedFinding = findings.find(
    (f) => f.metric === targetMetric && (!targetEntity || f.entities.includes(targetEntity)),
  );

  return (
    <Panel className="p-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge tone={statusTone(String(rec.status))}>
              {statusLabel(rec.status)}
            </Badge>
            <Badge tone={priorityTone(rec.priority)}>
              {priorityLabel(rec.priority)}
            </Badge>
          </div>
          <h3 className="mt-2 text-sm font-bold leading-snug text-text">
            {rec.title}
          </h3>
        </div>
        <span className="num text-xs text-text-muted">
          {rec.recommendation_id}
        </span>
      </div>

      {/* Problem Statement */}
      {rec.problem_statement && (
        <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Info size={12} className="text-accent" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-accent">
              What OpsPilot Detected
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.problem_statement}
          </p>
        </div>
      )}

      {/* Why It Matters */}
      {rec.why_it_matters && (
        <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Target size={12} className="text-warn" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-warn">
              Why This Matters
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.why_it_matters}
          </p>
        </div>
      )}

      {/* Likely Drivers */}
      {rec.likely_drivers && rec.likely_drivers.length > 0 && (
        <div className="mt-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Likely Drivers
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {rec.likely_drivers.map((driver, i) => (
              <span
                key={i}
                className="rounded border border-line px-2 py-0.5 text-[11px] text-text-2"
              >
                {driver}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Linked Finding Context */}
      {linkedFinding && (
        <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Related Finding
          </p>
          <p className="mt-0.5 text-xs text-text-2">
            {linkedFinding.headline}
          </p>
        </div>
      )}

      {/* Expected Benefit */}
      {rec.expected_benefit && (
        <div className="mt-3 rounded-lg border border-ok/30 bg-ok/[0.05] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <TrendingUp size={12} className="text-ok" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-ok">
              Expected Benefit
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.expected_benefit}
          </p>
        </div>
      )}

      {/* Evidence & Metadata */}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-text-muted">
        {targetEntity && (
          <span className="rounded border border-line px-1.5 py-0.5">
            {targetEntity}
          </span>
        )}
        {targetMetric && (
          <span className="rounded border border-line px-1.5 py-0.5">
            {targetMetric}
          </span>
        )}
        {typeof rec.evidence_strength === "number" && (
          <span>
            Evidence strength: {(rec.evidence_strength * 100).toFixed(0)}%
          </span>
        )}
        {rec.evidence_ids.length > 0 && (
          <span
            title={`Cites evidence ${rec.evidence_ids.join(", ")}`}
            className="text-accent"
          >
            {rec.evidence_ids.length} evidence ref{rec.evidence_ids.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </Panel>
  );
}
