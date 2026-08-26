/** Analysis run progress: honest stages mapped to the real polled lifecycle. */

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { formatDateTime } from "../../lib/format";

/**
 * Stage list shown during/after a pipeline run.
 *
 * Only the first stage reflects an independently verifiable fact
 * (the dataset passed validation at load time). The remaining rows are
 * the pipeline's real phases presented as one collective in-flight
 * state - no fabricated percentages or fake per-stage completion.
 */
export function AnalysisProgress({
  running,
  datasetReady,
  startedAt,
  durationMs,
  completedAt,
}: {
  running: boolean;
  datasetReady: boolean;
  startedAt: number | null;
  durationMs: number | null;
  completedAt: string | null;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running || startedAt === null) return;
    setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  const phases = [
    "Profiling data",
    "Detecting anomalies",
    "Building trends",
    "Preparing insights",
  ];

  return (
    <div className="mt-4 rounded-xl border border-line bg-faint px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-text">
          {running ? (
            <Loader2 size={15} className="animate-spin text-accent" aria-hidden />
          ) : (
            <CheckCircle2 size={15} className="text-ok" aria-hidden />
          )}
          {running ? "Analyzing dataset…" : "Analysis complete"}
        </p>
        <span className="num text-xs text-text-muted">
          {running && startedAt !== null
            ? `${elapsed}s elapsed`
            : durationMs !== null
              ? `completed in ${Math.max(1, Math.round(durationMs / 1000))}s${
                  completedAt ? ` · ${formatDateTime(completedAt)}` : ""
                }`
              : ""}
        </span>
      </div>

      <ul className="mt-3 space-y-1.5">
        <StageRow
          label="Dataset validated"
          done={datasetReady}
          active={false}
        />
        {phases.map((label) => (
          <StageRow key={label} label={label} done={!running} active={running} />
        ))}
      </ul>
      {running && (
        <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
          Running one deterministic pipeline pass over the full dataset — this
          page updates automatically when it finishes.
        </p>
      )}
    </div>
  );
}

function StageRow({
  label,
  done,
  active,
}: {
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <li className="flex items-center gap-2.5 text-sm">
      {done ? (
        <CheckCircle2 size={14} className="shrink-0 text-ok" aria-hidden />
      ) : (
        <span
          className={`inline-block h-[9px] w-[9px] shrink-0 rounded-full ${
            active ? "animate-pulse bg-accent" : "border border-line-strong bg-transparent"
          }`}
          aria-hidden
        />
      )}
      <span className={done ? "text-text-2" : active ? "text-text" : "text-text-muted"}>
        {label}
        {!done && !active && <span className="ml-2 text-xs text-text-muted">queued</span>}
      </span>
    </li>
  );
}
