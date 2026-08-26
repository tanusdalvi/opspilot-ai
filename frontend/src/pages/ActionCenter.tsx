import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  ClipboardList,
  Clock,
  ExternalLink,
  XCircle,
} from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { priorityLabel, statusLabel, statusTone } from "../lib/severity";
import type { RecommendationRecord } from "../lib/types";

export default function ActionCenter() {
  const { system, ensurePlan } = useWorkspace();
  const [items, setItems] = useState<RecommendationRecord[]>([]);
  const [planLoading, setPlanLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = system?.artifacts_ready === true;

  useEffect(() => {
    if (!ready || items.length > 0 || planLoading) return;
    let cancelled = false;
    setPlanLoading(true);
    void ensurePlan()
      .then((payload) => {
        if (!cancelled) setItems(payload.plan.recommendations);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setPlanLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, items.length, ensurePlan]);

  const total = items.length;
  const pending = items.filter((r) => r.status === "PENDING");
  const approved = items.filter((r) => r.status === "APPROVED");
  const rejected = items.filter((r) => r.status === "REJECTED");
  const reviewed = items.filter((r) => r.status !== "PENDING");

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Command Center" title="Action Center" />
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="No analysis available"
          body="The Action Center consolidates recommendations and review decisions after analysis. Load data first."
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
        eyebrow="Command Center"
        title="Action Center"
        description="Recommended actions from the analysis, with review state and links to make your decision."
      />

      {/* Summary Stats */}
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Panel className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-faint">
              <ClipboardList size={18} className="text-text-muted" aria-hidden />
            </div>
            <div>
              <p className="text-2xl font-bold text-text">{total}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                Total
              </p>
            </div>
          </div>
        </Panel>
        <Panel className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-warn/30 bg-warn/10">
              <Clock size={18} className="text-warn" aria-hidden />
            </div>
            <div>
              <p className="text-2xl font-bold text-text">{pending.length}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                Pending Review
              </p>
            </div>
          </div>
        </Panel>
        <Panel className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-ok/30 bg-ok/10">
              <CheckCircle2 size={18} className="text-ok" aria-hidden />
            </div>
            <div>
              <p className="text-2xl font-bold text-text">{approved.length}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                Approved
              </p>
            </div>
          </div>
        </Panel>
        <Panel className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-danger/30 bg-danger/10">
              <XCircle size={18} className="text-danger" aria-hidden />
            </div>
            <div>
              <p className="text-2xl font-bold text-text">{rejected.length}</p>
              <p className="text-[10px] uppercase tracking-wider text-text-muted">
                Rejected
              </p>
            </div>
          </div>
        </Panel>
      </div>

      {/* Pending Recommendations */}
      <section aria-label="Pending recommendations" className="mb-8">
        <SectionHeading
          icon={<Clock size={15} className="text-warn" aria-hidden />}
          title="Needs Your Attention"
          caption={
            pending.length > 0
              ? `${pending.length} recommendation${pending.length === 1 ? "" : "s"} awaiting your decision.`
              : "No pending recommendations."
          }
        />
        {planLoading ? (
          <div className="grid gap-3 md:grid-cols-2">
            <SkeletonPanel lines={3} />
            <SkeletonPanel lines={3} />
          </div>
        ) : pending.length === 0 ? (
          <Panel className="p-5 text-center text-sm text-text-2">
            {items.length > 0
              ? "All recommendations have been reviewed."
              : "No recommended actions yet. Run analysis to generate recommendations."}
          </Panel>
        ) : (
          <div className="space-y-3">
            {[...pending]
              .sort((a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0))
              .map((rec) => (
                <ActionCard key={rec.recommendation_id} rec={rec} />
              ))}
          </div>
        )}
      </section>

      {/* Decision History */}
      {reviewed.length > 0 && (
        <section aria-label="Decision history">
          <SectionHeading
            icon={<CheckCircle2 size={15} className="text-ok" aria-hidden />}
            title="Your Decisions"
            caption={`${reviewed.length} recommendation${reviewed.length === 1 ? "" : "s"} reviewed.`}
          />
          <div className="space-y-2">
            {reviewed.map((rec) => (
              <Panel key={rec.recommendation_id} className="flex items-center gap-3 p-3">
                <Badge tone={statusTone(rec.status)} withIcon={false}>
                  {statusLabel(rec.status)}
                </Badge>
                <span className="min-w-0 flex-1 truncate text-sm text-text">
                  {rec.title}
                </span>
                <Link
                  to={`/review/${rec.recommendation_id}`}
                  className="text-xs font-semibold text-accent hover:underline"
                >
                  View
                </Link>
              </Panel>
            ))}
          </div>
        </section>
      )}

      {error && (
        <p className="mt-4 rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function ActionCard({ rec }: { rec: RecommendationRecord }) {
  const hasEvidence = rec.evidence_ids.length > 0;

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge tone={priorityTone(rec.priority)}>
              {priorityLabel(rec.priority)}
            </Badge>
            <Badge tone={statusTone(rec.status)}>
              {statusLabel(rec.status)}
            </Badge>
          </div>
          <h3 className="mt-1.5 text-sm font-semibold leading-snug text-text">
            {rec.title}
          </h3>
        </div>
      </div>

      {/* Problem detected */}
      {rec.problem_statement && (
        <div className="mt-2.5 rounded-lg border border-line bg-faint px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Problem Detected
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-text-2">
            {rec.problem_statement}
          </p>
        </div>
      )}

      {/* Recommended action */}
      {rec.description && (
        <div className="mt-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Recommended Action
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-text-2">
            {rec.description}
          </p>
        </div>
      )}

      {/* Evidence summary */}
      {hasEvidence && (
        <p className="mt-2 text-[11px] text-text-muted">
          {rec.evidence_ids.length} evidence ref{rec.evidence_ids.length !== 1 ? "s" : ""}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Link to={`/review/${rec.recommendation_id}`}>
          <Button variant="subtle" className="text-xs">
            <ExternalLink size={12} className="mr-1" aria-hidden />
            Review & Decide
          </Button>
        </Link>
      </div>
    </Panel>
  );
}

function priorityTone(priority: string): "danger" | "warn" | "info" | "muted" {
  switch (String(priority).toUpperCase()) {
    case "CRITICAL":
      return "danger";
    case "HIGH":
      return "warn";
    case "MEDIUM":
      return "info";
    default:
      return "muted";
  }
}
