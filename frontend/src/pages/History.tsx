import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { History as HistoryIcon } from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
} from "../components/ui/Primitives";
import { dayBucket, formatDateTime } from "../lib/format";
import { statusTone } from "../lib/severity";
import type { HistoryPayload } from "../lib/types";

const BUCKET_ORDER = ["Today", "Yesterday", "Earlier"] as const;

export default function History() {
  const { system } = useWorkspace();
  const [payload, setPayload] = useState<HistoryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<HistoryPayload>("/api/history")
      .then((body) => {
        if (!cancelled) setPayload(body);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [system?.artifacts_ready]);

  const events = [
    ...(payload?.plans ?? []).map((plan) => ({
      at: plan.recorded_at,
      kind: "PLAN",
      title: `Plan #${plan.plan_id} · ${plan.plan_type}`,
      detail: `${plan.recommendation_count} recommendations · schema ${plan.schema_version}`,
    })),
    ...(payload?.recommendation_snapshots ?? []).map((rec) => ({
      at: rec.recorded_at ?? "",
      kind: "SNAPSHOT",
      title: rec.title,
      detail: `${rec.status} · priority ${String(rec.priority).toLowerCase()}`,
    })),
    ...(payload?.review_events ?? []).map((event) => ({
      at: event.occurred_at,
      kind: "REVIEW",
      title: `${event.decision.replace(/_/g, " ")} — ${event.recommendation_id}`,
      detail: `${event.previous_status} → ${event.new_status} · by ${event.reviewer_id}${event.comment ? ` · "${event.comment}"` : ""}`,
    })),
  ].sort((a, b) => (a.at < b.at ? 1 : -1));

  const buckets: Record<string, typeof events> = {};
  for (const event of events) {
    const bucket = dayBucket(event.at);
    (buckets[bucket] ??= []).push(event);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Governance"
        title="Audit Timeline"
        description="Append-only record of plans, recommendation snapshots, and human decisions. Entries are never edited or removed."
      />

      {error ? (
        <p className="rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : !payload ? (
        <Panel className="p-6 text-center text-sm text-text-2">Loading…</Panel>
      ) : events.length === 0 ? (
        <EmptyState
          icon={<HistoryIcon size={20} />}
          title="No history yet"
          body="Plans and review decisions appear here the moment they are persisted. Nothing is written without an explicit action."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-4 flex gap-2">
            <Badge tone="info" withIcon={false}>
              {payload.counts.plans} plans
            </Badge>
            <Badge tone="info" withIcon={false}>
              {payload.counts.recommendations} snapshots
            </Badge>
            <Badge tone="ok" withIcon={false}>
              {payload.counts.review_events} reviews
            </Badge>
          </div>

          {BUCKET_ORDER.filter((bucket) => buckets[bucket]?.length).map(
            (bucket) => (
              <section key={bucket} className="mb-6" aria-label={bucket}>
                <SectionHeading title={bucket} />
                <ol className="relative ml-3 space-y-3 border-l border-line-strong pl-5">
                  {buckets[bucket].map((event, index) => (
                    <li key={`${event.at}-${index}`} className="relative">
                      <span
                        className={`absolute -left-[27px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-bg ${
                          event.kind === "REVIEW"
                            ? "bg-ok"
                            : event.kind === "PLAN"
                              ? "bg-accent"
                              : "bg-line-strong"
                        }`}
                        aria-hidden
                      />
                      <Panel className="p-3.5">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-text">
                            {event.title}
                          </p>
                          <span className="num text-[11px] text-text-muted">
                            {formatDateTime(event.at)}
                          </span>
                        </div>
                        <p className="mt-1 break-words text-xs leading-relaxed text-text-2">
                          {event.detail}
                        </p>
                        {event.kind === "REVIEW" && (
                          <div className="mt-1.5">
                            <Badge tone={statusTone(decisionStatus(event))} withIcon={false}>
                              {decisionStatus(event)}
                            </Badge>
                          </div>
                        )}
                      </Panel>
                    </li>
                  ))}
                </ol>
              </section>
            ),
          )}
        </>
      )}
    </div>
  );
}

function decisionStatus(event: {
  title: string;
}): string {
  return event.title.split(" — ")[0].replace(/\b\w/g, (c) => c.toUpperCase());
}
