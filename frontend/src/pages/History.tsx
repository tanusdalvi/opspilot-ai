import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { History as HistoryIcon } from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
} from "../components/ui/Primitives";
import { dayBucket, formatDateTime } from "../lib/format";
import { statusLabel } from "../lib/severity";
import type { HistoryPayload } from "../lib/types";

const BUCKET_ORDER = ["Today", "Yesterday", "Earlier"] as const;

/** Events disclosed before "Show older" engages. */
const PAGE_SIZE = 25;

export default function History() {
  const { system } = useWorkspace();
  const [payload, setPayload] = useState<HistoryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<HistoryPayload>("/api/history")
      .then((body) => {
        if (!cancelled) {
          setPayload(body);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("The audit timeline could not be loaded right now.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [system?.artifacts_ready, reloadKey]);

  const events = useMemo(() => {
    if (!payload) return [];
    return [
      ...(payload.plans ?? []).map((plan) => ({
        at: plan.recorded_at,
        kind: "PLAN",
        title: `Plan #${plan.plan_id} · ${plan.plan_type}`,
        detail: `${plan.recommendation_count} recommendations · schema ${plan.schema_version}`,
      })),
      ...(payload.recommendation_snapshots ?? []).map((rec) => ({
        at: rec.recorded_at ?? "",
        kind: "SNAPSHOT",
        title: rec.title,
        detail: `${statusLabel(rec.status)} · priority ${String(rec.priority).toLowerCase()}`,
      })),
      ...(payload.review_events ?? []).map((event) => ({
        at: event.occurred_at,
        kind: "REVIEW",
        title: `${statusLabel(event.decision)} — recommendation ${event.recommendation_id}`,
        detail: [
          `${statusLabel(event.previous_status)} → ${statusLabel(event.new_status)}`,
          `by ${event.reviewer_id}`,
          event.comment ? `"${event.comment}"` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      })),
    ].sort((a, b) => (a.at < b.at ? 1 : -1));
  }, [payload]);

  const buckets = useMemo(() => {
    const map: Record<string, typeof events> = {};
    for (const event of events) {
      const bucket = dayBucket(event.at);
      (map[bucket] ??= []).push(event);
    }
    return map;
  }, [events]);

  return (
    <div>
      <PageHeader
        eyebrow="Governance"
        title="Audit Timeline"
        description="Append-only record of plans, recommendation snapshots, and human decisions. Entries are never edited or removed."
      />

      {error ? (
        <EmptyState
          icon={<HistoryIcon size={20} />}
          title="History unavailable"
          body={error}
          action={<Button onClick={() => setReloadKey((k) => k + 1)}>Retry</Button>}
        />
      ) : loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Panel key={i} className="p-4">
              <Skeleton className={`h-3.5 ${i % 2 ? "w-2/5" : "w-1/3"}`} />
              <Skeleton className="mt-3 h-3 w-full" />
              <Skeleton className="mt-2 h-3 w-3/4" />
            </Panel>
          ))}
        </div>
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
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge tone="info" withIcon={false}>
              {payload?.counts.plans} plans
            </Badge>
            <Badge tone="info" withIcon={false}>
              {payload?.counts.recommendations} snapshots
            </Badge>
            <Badge tone="ok" withIcon={false}>
              {payload?.counts.review_events} reviews
            </Badge>
          </div>

          {(() => {
            let shown = 0;
            return BUCKET_ORDER.filter((bucket) => buckets[bucket]?.length).map(
              (bucket) => {
                const bucketEvents = buckets[bucket];
                if (shown >= visibleCount) return null;
                const slice = bucketEvents.slice(0, visibleCount - shown);
                shown += slice.length;
                const remainingInBucket =
                  bucketEvents.length - slice.length > 0;
                return (
                  <section key={bucket} className="mb-6" aria-label={bucket}>
                    <SectionHeading
                      title={bucket}
                      caption={
                        remainingInBucket
                          ? undefined
                          : `${bucketEvents.length} event${bucketEvents.length === 1 ? "" : "s"}`
                      }
                    />
                    <ol className="relative ml-3 space-y-3 border-l border-line-strong pl-5">
                      {slice.map((event, index) => (
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
                          </Panel>
                        </li>
                      ))}
                    </ol>
                  </section>
                );
              },
            );
          })()}

          {events.length > visibleCount && (
            <div className="flex justify-center">
              <Button
                variant="ghost"
                onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
              >
                Show older events ({events.length - visibleCount} remaining)
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
