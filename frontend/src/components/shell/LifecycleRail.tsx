import { Check } from "lucide-react";

export const LIFECYCLE_STAGES: readonly string[] = [
  "OBSERVE",
  "UNDERSTAND",
  "DETECT",
  "INVESTIGATE",
  "RECOMMEND",
  "HUMAN DECISION",
  "AUDIT",
];

/**
 * Honest seven-stage rail: `current` is the stage label derived from real
 * workspace state (backend/api serializers), never fabricated progress.
 */
export function LifecycleRail({
  current,
  compact = false,
}: {
  current: string | undefined;
  compact?: boolean;
}) {
  const currentIndex = current
    ? LIFECYCLE_STAGES.indexOf(current)
    : -1;
  return (
    <ol className="flex items-center gap-0" aria-label="Analysis lifecycle">
      {LIFECYCLE_STAGES.map((stage, index) => {
        const done = currentIndex > index;
        const active = currentIndex === index;
        const blocked = currentIndex === -1 && index > 0;
        const reachable = !blocked || index === 1;
        return (
          <li key={stage} className="flex min-w-0 flex-1 items-center">
            <div className="flex min-w-0 flex-col items-center gap-1.5">
              <span
                aria-current={active ? "step" : undefined}
                className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-bold transition-colors ${
                  done
                    ? "border-ok/50 bg-ok/15 text-ok"
                    : active
                      ? "border-accent bg-accent/20 text-text shadow-[0_0_14px_rgba(91,140,255,0.5)]"
                      : "border-line bg-white/[0.03] text-text-muted"
                } ${blocked && !reachable ? "opacity-45" : ""}`}
              >
                {done ? (
                  <Check size={11} strokeWidth={3} aria-hidden />
                ) : (
                  index + 1
                )}
              </span>
              {!compact && (
                <span
                  className={`max-w-full truncate text-center text-[9px] font-semibold uppercase tracking-wider ${
                    active ? "text-text" : "text-text-muted"
                  }`}
                >
                  {stage}
                </span>
              )}
            </div>
            {index < LIFECYCLE_STAGES.length - 1 && (
              <span
                className={`mx-1 mb-0 h-px flex-1 lg:mb-4 ${
                  done ? "bg-ok/40" : "bg-line-strong"
                }`}
                aria-hidden
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
