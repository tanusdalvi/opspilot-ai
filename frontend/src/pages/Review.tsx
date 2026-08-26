import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Check,
  ChevronLeft,
  GitPullRequestArrow,
  Info,
  Loader2,
  MessageSquare,
  ShieldCheck,
  Target,
  ThumbsDown,
  TrendingUp,
} from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { ConfirmDialog } from "../components/ui/Controls";
import { priorityLabel, priorityTone, statusLabel, statusTone } from "../lib/severity";
import type { RecommendationRecord, Finding } from "../lib/types";

const DECISIONS = [
  {
    value: "APPROVE",
    label: "Approve",
    description: "Proceed with this action. Appended to the immutable audit trail.",
    icon: <Check size={14} />,
    variant: "primary" as const,
  },
  {
    value: "REQUEST_CHANGES",
    label: "Request Changes",
    description: "Flag this for further review or modification before proceeding.",
    icon: <MessageSquare size={14} />,
    variant: "subtle" as const,
  },
  {
    value: "REJECT",
    label: "Reject",
    description: "Do not proceed with this action. Recorded permanently in the audit log.",
    icon: <ThumbsDown size={14} />,
    variant: "danger" as const,
  },
];

export default function Review() {
  const { recommendationId } = useParams<{ recommendationId?: string }>();
  const { system, ensurePlan, pushToast } = useWorkspace();
  const [items, setItems] = useState<RecommendationRecord[]>([]);
  const [planLoading, setPlanLoading] = useState(false);
  const [reviewerId, setReviewerId] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmingReject, setConfirmingReject] = useState(false);

  const findings: Finding[] =
    (system as unknown as { artifacts?: { findings?: Finding[] } })?.artifacts
      ?.findings ?? [];

  const activeRec = recommendationId
    ? items.find((r) => r.recommendation_id === recommendationId)
    : null;

  // The list view shows only PENDING items (or all if viewing a specific one)
  const listItems = activeRec
    ? []
    : [...items]
        .sort((a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0));

  useEffect(() => {
    if (!system?.artifacts_ready || items.length > 0 || planLoading) return;
    let cancelled = false;
    setPlanLoading(true);
    void ensurePlan()
      .then((payload) => {
        if (!cancelled) setItems(payload.plan.recommendations);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setPlanLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [system?.artifacts_ready, items.length, ensurePlan]);

  async function decide(recommendationId: string, decision: string) {
    setBusy(true);
    try {
      await api("/api/review", {
        method: "POST",
        json: {
          recommendation_id: recommendationId,
          decision,
          reviewer_id: reviewerId.trim() || "anonymous",
          comment: comment.trim() ? comment.trim() : null,
        },
      });
      pushToast({
        tone: "ok",
        title: "Decision recorded",
        body: `${decision.replace(/_/g, " ").toLowerCase()} · appended to the audit trail`,
      });
      const payload = await ensurePlan();
      setItems(payload.plan.recommendations);
      setComment("");
    } catch (err) {
      pushToast({
        tone: "danger",
        title: "Review failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
      setConfirmingReject(false);
    }
  }

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Decide & Act" title="Human Review" />
        <EmptyState
          icon={<GitPullRequestArrow size={20} />}
          title="Nothing to review"
          body="Recommendations become reviewable after analysis. Each decision is recorded permanently in the audit trail."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  // Single recommendation view
  if (recommendationId) {
    if (planLoading) {
      return (
        <div>
          <PageHeader eyebrow="Decide & Act" title="Review & Decide" />
          <SkeletonPanel lines={6} />
        </div>
      );
    }

    if (!activeRec) {
      return (
        <div>
          <PageHeader eyebrow="Decide & Act" title="Review & Decide" />
          <EmptyState
            icon={<GitPullRequestArrow size={20} />}
            title="Recommendation not found"
            body={`No recommendation with ID "${recommendationId}" exists. It may have been removed.`}
            action={
              <Link to="/action-center">
                <Button>Back to Action Center</Button>
              </Link>
            }
          />
        </div>
      );
    }

    if (activeRec.status !== "PENDING") {
      return (
        <div>
          <PageHeader eyebrow="Decide & Act" title="Review & Decide" />
          <Panel className="p-6 text-center">
            <p className="text-sm text-text-2">
              This recommendation has already been{" "}
              <Badge tone={statusTone(activeRec.status)}>
                {statusLabel(activeRec.status)}
              </Badge>
              .
            </p>
            <Link
              to="/action-center"
              className="mt-3 inline-block text-xs font-semibold text-accent hover:underline"
            >
              Back to Action Center
            </Link>
          </Panel>
        </div>
      );
    }

    return (
      <div>
        <PageHeader
          eyebrow="Decide & Act"
          title="Review & Decide"
          description="Review this recommendation, then record your verdict."
        />

        <Link
          to="/action-center"
          className="mb-4 inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
        >
          <ChevronLeft size={14} />
          Back to Action Center
        </Link>

        {/* Reviewer identity */}
        <Panel className="mb-4 p-5">
          <SectionHeading
            icon={<ShieldCheck size={15} className="text-accent" aria-hidden />}
            title="Reviewer identity"
            caption="Recorded verbatim on every review event."
          />
          <input
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            placeholder="e.g. tanishka.ops"
            aria-label="Reviewer ID"
            className="num w-full max-w-sm rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm text-text placeholder:text-text-muted"
          />
        </Panel>

        {/* Single recommendation detail */}
        <ReviewDetail rec={activeRec} findings={findings} />

        {/* Decision controls */}
        <Panel className="mt-4 p-5">
          <SectionHeading
            icon={<Target size={15} className="text-warn" aria-hidden />}
            title="Your decision"
            caption="All decisions are recorded permanently in the audit trail."
          />
          <label className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Decision comment (optional)
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Add context for this decision — stored permanently in the audit trail."
            aria-label="Decision comment"
            className="mt-1 w-full resize-none rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm text-text placeholder:text-text-muted"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {DECISIONS.map((option) => (
              <Button
                key={option.value}
                variant={option.variant}
                disabled={busy}
                onClick={() => {
                  if (option.value === "REJECT") {
                    setConfirmingReject(true);
                  } else {
                    void decide(activeRec.recommendation_id, option.value);
                  }
                }}
              >
                {busy ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden />
                ) : (
                  option.icon
                )}
                {option.label}
              </Button>
            ))}
          </div>
        </Panel>

        <ConfirmDialog
          open={confirmingReject}
          title="Reject this recommendation?"
          body="The recommendation will be marked Rejected and the decision appended to the immutable audit trail. This cannot be undone."
          confirmLabel="Reject"
          tone="danger"
          onConfirm={() => void decide(activeRec.recommendation_id, "REJECT")}
          onCancel={() => setConfirmingReject(false)}
        />
      </div>
    );
  }

  // List view: show all pending recommendations
  return (
    <div>
      <PageHeader
        eyebrow="Decide & Act"
        title="Review & Decide"
        description="Every recommendation requires an explicit human decision. Review the problem, supporting evidence, and action, then record your verdict."
      />

      {/* Reviewer identity */}
      <Panel className="mb-4 p-5">
        <SectionHeading
          icon={<ShieldCheck size={15} className="text-accent" aria-hidden />}
          title="Reviewer identity"
          caption="Recorded verbatim on every review event."
        />
        <input
          value={reviewerId}
          onChange={(e) => setReviewerId(e.target.value)}
          placeholder="e.g. tanishka.ops"
          aria-label="Reviewer ID"
          className="num w-full max-w-sm rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm text-text placeholder:text-text-muted"
        />
      </Panel>

      <div className="space-y-4">
        {listItems.length === 0 && planLoading && (
          <>
            <SkeletonPanel lines={4} />
            <SkeletonPanel lines={4} />
          </>
        )}
        {listItems.length === 0 && !planLoading && (
          <Panel className="p-6 text-center text-sm text-text-2">
            Nothing requires your attention right now.
          </Panel>
        )}
        {listItems.map((rec) => (
          <Panel key={rec.recommendation_id} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge tone={priorityTone(rec.priority)}>
                    {priorityLabel(rec.priority)}
                  </Badge>
                </div>
                <h3 className="mt-1.5 text-sm font-semibold leading-snug text-text">
                  {rec.title}
                </h3>
              </div>
            </div>
            {rec.problem_statement && (
              <p className="mt-1.5 text-xs leading-relaxed text-text-2 line-clamp-2">
                {rec.problem_statement}
              </p>
            )}
            <Link
              to={`/review/${rec.recommendation_id}`}
              className="mt-2.5 inline-block"
            >
              <Button variant="subtle" className="text-xs">
                Review & Decide
              </Button>
            </Link>
          </Panel>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ReviewDetail: full single-rec view used in the parameterised route */
/* ------------------------------------------------------------------ */

function ReviewDetail({
  rec,
  findings,
}: {
  rec: RecommendationRecord;
  findings: Finding[];
}) {
  const targetMetric = String(rec.target_metric ?? "");
  const targetEntity = rec.target_entity as string | null;
  const linkedFinding = findings.find(
    (f) =>
      f.metric === targetMetric && (!targetEntity || f.entities.includes(targetEntity)),
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

      {/* What needs your decision? */}
      {rec.problem_statement && (
        <div className="mt-4 rounded-lg border border-line bg-faint px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Info size={12} className="text-accent" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-accent">
              Problem Detected
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.problem_statement}
          </p>
        </div>
      )}

      {/* Recommended action */}
      {rec.description && (
        <div className="mt-3 rounded-lg border border-warn/30 bg-warn/[0.05] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Target size={12} className="text-warn" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-warn">
              Recommended Action
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.description}
          </p>
        </div>
      )}

      {/* Why OpsPilot recommends this */}
      {rec.why_it_matters && (
        <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Info size={12} className="text-accent" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-accent">
              Why OpsPilot Recommends This
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.why_it_matters}
          </p>
        </div>
      )}

      {/* Likely drivers */}
      {rec.likely_drivers && rec.likely_drivers.length > 0 && (
        <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Likely Drivers
          </p>
          <ul className="mt-1 list-disc pl-4 text-xs leading-relaxed text-text-2">
            {rec.likely_drivers.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Supporting evidence */}
      <div className="mt-3 rounded-lg border border-line bg-faint px-3 py-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
          Supporting Evidence
        </p>
        {linkedFinding ? (
          <div className="mt-1">
            <p className="text-xs font-medium text-text">
              {linkedFinding.headline}
            </p>
            {linkedFinding.evidence_summary && (
              <p className="mt-1 text-[11px] leading-relaxed text-text-2">
                {linkedFinding.evidence_summary}
              </p>
            )}
          </div>
        ) : rec.evidence_ids.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {rec.evidence_ids.slice(0, 8).map((id) => (
              <span
                key={id}
                className="num inline-block rounded border border-line px-1.5 py-0.5 text-[10px] text-text-muted"
              >
                {id}
              </span>
            ))}
            {rec.evidence_ids.length > 8 && (
              <span className="text-[10px] text-text-muted">
                +{rec.evidence_ids.length - 8} more
              </span>
            )}
          </div>
        ) : (
          <p className="mt-1 text-[11px] text-text-muted">No evidence references available.</p>
        )}
      </div>

      {/* Expected outcome */}
      {rec.expected_benefit && (
        <div className="mt-3 rounded-lg border border-ok/30 bg-ok/[0.05] px-3 py-2">
          <div className="flex items-center gap-1.5">
            <TrendingUp size={12} className="text-ok" aria-hidden />
            <p className="text-[10px] font-bold uppercase tracking-wider text-ok">
              Expected Outcome
            </p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-2">
            {rec.expected_benefit}
          </p>
        </div>
      )}
    </Panel>
  );
}
