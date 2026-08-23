import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check, GitPullRequestArrow, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
} from "../components/ui/Primitives";
import { metricTitle, statusTone } from "../lib/severity";import type { RecommendationRecord } from "../lib/types";

const DECISIONS = [
  { value: "approve", label: "Approve", variant: "primary" as const },
  { value: "request_changes", label: "Request changes", variant: "subtle" as const },
  { value: "reject", label: "Reject", variant: "danger" as const },
];

export default function Review() {
  const { system, ensurePlan, pushToast } = useWorkspace();
  const [items, setItems] = useState<RecommendationRecord[]>([]);
  const [reviewerId, setReviewerId] = useState("");
  const [comment, setComment] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!system?.artifacts_ready || items.length > 0) return;
    let cancelled = false;
    void ensurePlan()
      .then((payload) => {
        if (!cancelled) setItems(payload.plan.recommendations);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
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
        body: `${decision.replace(/_/g, " ")} · appended to the audit trail`,
      });
      const payload = await ensurePlan();
      setItems(payload.plan.recommendations);
      setComment("");
      setSelectedId(null);
    } catch (err) {
      pushToast({
        tone: "danger",
        title: "Review failed",
        body: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Governance" title="Human Review" />
        <EmptyState
          icon={<GitPullRequestArrow size={20} />}
          title="Nothing to review"
          body="Recommendations become reviewable after a pipeline run. The state machine enforces one authoritative status per recommendation."
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
        eyebrow="Governance"
        title="Human Decision Console"
        description="Every AI suggestion requires an explicit human decision. Decisions append immutable review events to the audit store."
      />

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

      <div className="space-y-3">
        {items.length === 0 && (
          <Panel className="p-6 text-center text-sm text-text-2">
            No recommendations available for review yet.
          </Panel>
        )}
        {[...items]
          .sort((a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0))
          .map((rec) => {
            const selected = selectedId === rec.recommendation_id;
            return (
              <Panel key={rec.recommendation_id} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-bold text-text">{rec.title}</h3>
                    <p className="mt-1 text-xs uppercase tracking-wider text-text-muted">
                      {metricTitle(String(rec.action_type ?? ""))} ·{" "}
                      <span className="num">{rec.recommendation_id}</span>
                    </p>
                  </div>
                  <Badge tone={statusTone(String(rec.status))}>
                    {String(rec.status).replace(/_/g, " ")}
                  </Badge>
                </div>

                {!selected ? (
                  <Button
                    variant="ghost"
                    className="mt-3"
                    onClick={() => setSelectedId(rec.recommendation_id)}
                  >
                    Record a decision
                  </Button>
                ) : (
                  <div className="mt-4 rounded-xl border border-line bg-white/[0.02] p-4">
                    <textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      rows={2}
                      placeholder="Optional decision comment (stored in the audit trail)"
                      aria-label="Decision comment"
                      className="w-full resize-none rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm text-text placeholder:text-text-muted"
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      {DECISIONS.map((option) => (
                        <Button
                          key={option.value}
                          variant={option.variant}
                          disabled={busy}
                          onClick={() =>
                            void decide(rec.recommendation_id, option.value)
                          }
                        >
                          {option.value === "approve" && (
                            <Check size={14} aria-hidden />
                          )}
                          {option.label}
                        </Button>
                      ))}
                      <Button variant="subtle" onClick={() => setSelectedId(null)}>
                        Cancel
                      </Button>
                    </div>
                    <p className="mt-2 text-[11px] text-text-muted">
                      Appends an immutable review event; the recommendation's
                      status transitions follow the existing state machine.
                    </p>
                  </div>
                )}
              </Panel>
            );
          })}
      </div>
    </div>
  );
}
