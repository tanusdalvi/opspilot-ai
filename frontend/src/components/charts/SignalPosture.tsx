/**
 * Signal Posture — command-center status built on the CANONICAL backend
 * posture (score + band from `app.ui.posture`, delivered by the API) and
 * the real severity distribution. No second scoring algorithm lives here.
 */

import { motion } from "framer-motion";
import { Activity, ShieldAlert, ShieldCheck } from "lucide-react";
import { SEVERITIES } from "../../lib/signals";
import type { PosturePresentation } from "../../lib/signals";
import { severity } from "../../lib/severity";

const BAR_MIN_FRACTION = 0.04;

export function SignalPosture({
  posture,
  compact = false,
}: {
  posture: PosturePresentation;
  compact?: boolean;
}) {
  const attentionTone = posture.attentionNeeded ? "text-danger" : "text-ok";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p
            className={`num text-2xl font-bold leading-none ${attentionTone}`}
          >
            {posture.band}
          </p>
          <p className="mt-1.5 text-xs text-text-2">{posture.summary}</p>
        </div>
        <div
          aria-hidden
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border ${
            posture.attentionNeeded
              ? "border-danger/35 bg-danger/10 text-danger"
              : "border-ok/35 bg-ok/10 text-ok"
          }`}
        >
          {posture.attentionNeeded ? (
            <ShieldAlert size={20} />
          ) : (
            <ShieldCheck size={20} />
          )}
        </div>
      </div>

      {/* Severity distribution — every segment is a real backend count */}
      <div>
        <div
          role="img"
          aria-label={`Severity distribution: ${posture.counts.CRITICAL} critical, ${posture.counts.HIGH} high, ${posture.counts.MEDIUM} medium, ${posture.counts.LOW} low`}
          className="flex h-2.5 w-full gap-[3px] overflow-hidden rounded-full bg-surface-2"
        >
          {SEVERITIES.map((key) => {
            const count = posture.counts[key];
            if (!count) return null;
            const style = severity(key);
            const fraction = Math.max(count / posture.totalSignals, BAR_MIN_FRACTION);
            return (
              <motion.span
                key={key}
                initial={{ scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                style={{ width: `${fraction * 100}%`, originX: 0 }}
                className={`h-full rounded-full ${
                  style.tone === "danger"
                    ? "bg-danger"
                    : style.tone === "warn"
                      ? "bg-warn"
                      : style.tone === "info"
                        ? "bg-accent"
                        : "bg-text-muted"
                }`}
              />
            );
          })}
        </div>

        {!compact && (
          <dl className="mt-3 grid grid-cols-4 gap-2">
            {SEVERITIES.map((key) => (
              <div key={key} className="rounded-lg border border-line bg-surface-2/60 px-2 py-1.5">
                <dt className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-muted">
                  {severity(key).label}
                </dt>
                <dd
                  className={`num mt-0.5 text-sm font-bold ${
                    posture.counts[key] > 0 && key === "CRITICAL"
                      ? "text-danger"
                      : "text-text"
                  }`}
                >
                  {posture.counts[key]}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      {!compact && (
        <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted">
          <Activity size={11} aria-hidden /> posture score {posture.score}/100 ·
          presentation scale over detected severities
        </p>
      )}
    </div>
  );
}
