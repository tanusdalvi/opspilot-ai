/**
 * Signal Posture — command-center status built on the CANONICAL backend
 * posture (score + band from `app.ui.posture`, delivered by the API) and
 * the real severity distribution. No second scoring algorithm lives here.
 */

import { motion } from "framer-motion";
import { Activity, Info } from "lucide-react";
import { useState } from "react";
import { POSTURE_SCALE, SEVERITIES } from "../../lib/signals";
import type { PostureDriver, PosturePresentation } from "../../lib/signals";
import { severity } from "../../lib/severity";

const BAR_MIN_FRACTION = 0.04;
const GAUGE_RADIUS = 26;
const GAUGE_CIRCUMFERENCE = 2 * Math.PI * GAUGE_RADIUS;

const RECOMMENDATIONS: Record<string, string> = {
  Steady: "No immediate action needed. Continue routine monitoring.",
  "Moderate Attention":
    "Review the flagged signals to identify any emerging patterns.",
  "Needs Attention":
    "Critical signals require immediate review. See the top concerns below.",
};

function recommendation(band: string): string {
  return (
    RECOMMENDATIONS[band] ??
    "Review the flagged signals to identify any emerging patterns."
  );
}

/** Severity label + color for an individual driver. */
function driverDotColor(_count: number, topSeverity: string): string {
  if (topSeverity === "CRITICAL") return "bg-danger";
  if (topSeverity === "HIGH") return "bg-danger/70";
  if (topSeverity === "MEDIUM") return "bg-warn";
  return "bg-accent";
}

export function SignalPosture({
  posture,
  drivers = [],
  compact = false,
}: {
  posture: PosturePresentation;
  /** Metrics contributing most to the current posture (presentation-only aggregation). */
  drivers?: PostureDriver[];
  compact?: boolean;
}) {
  const attentionTone = posture.attentionNeeded ? "text-danger" : "text-ok";
  const [showWhy, setShowWhy] = useState(false);
  // The canonical score runs 100 (steady) → low (attention); the gauge
  // shows "operational pressure", so it fills inversely.
  const pressure = Math.max(0, Math.min(100, 100 - posture.score));

  return (
    <div className="flex flex-col gap-4">
      {/* Header — band + summary + gauge */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`text-2xl font-bold leading-none ${attentionTone}`}>
            {posture.band}
          </p>
          <p className="mt-1.5 text-xs text-text-2">{posture.summary}</p>
        </div>
        {/* Score gauge — premium ring with glow */}
        <div
          className="relative h-16 w-16 shrink-0"
          role="img"
          aria-label={`Operational posture score ${posture.score} out of 100`}
        >
          <svg viewBox="0 0 64 64" className="h-full w-full -rotate-90">
            <defs>
              <filter id="gauge-glow" x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="2" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            {/* Track */}
            <circle
              cx="32"
              cy="32"
              r={GAUGE_RADIUS}
              fill="none"
              strokeWidth="6"
              className="stroke-surface-2"
            />
            {/* Fill with glow */}
            <motion.circle
              cx="32"
              cy="32"
              r={GAUGE_RADIUS}
              fill="none"
              strokeWidth="6"
              strokeLinecap="round"
              className={posture.attentionNeeded ? "stroke-danger" : "stroke-ok"}
              strokeDasharray={GAUGE_CIRCUMFERENCE}
              filter={posture.attentionNeeded ? "url(#gauge-glow)" : undefined}
              initial={{ strokeDashoffset: GAUGE_CIRCUMFERENCE }}
              animate={{
                strokeDashoffset:
                  GAUGE_CIRCUMFERENCE * (1 - pressure / 100),
              }}
              transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            />
          </svg>
          <motion.span
            aria-hidden
            className={`num absolute inset-0 flex items-center justify-center text-sm font-bold text-text ${
              posture.attentionNeeded
                ? "animate-pulse"
                : ""
            }`}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.3 }}
          >
            {posture.score}
          </motion.span>
        </div>
      </div>

      {/* Contextual explanation — what this means */}
      {!compact && (
        <div className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
          <p className="text-xs leading-relaxed text-text-2">{posture.why}</p>
          <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
            {recommendation(posture.band)}
          </p>
        </div>
      )}

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

      {/* Top posture drivers — compact list with severity dots */}
      {!compact && drivers.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted">
            Top concerns
          </p>
          <ul className="mt-2 space-y-1.5">
            {drivers.map((driver, index) => {
              // Determine dot color by the driver's relative weight contribution.
              // Higher weight = more critical impact on posture.
              const relativeSeverity =
                driver.weight >= 25
                  ? "CRITICAL"
                  : driver.weight >= 12
                    ? "HIGH"
                    : driver.weight >= 5
                      ? "MEDIUM"
                      : "LOW";
              return (
                <motion.li
                  key={driver.metric}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.28, delay: 0.15 + index * 0.07 }}
                  className="flex items-center gap-2 text-xs"
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${driverDotColor(driver.count, relativeSeverity)}`}
                    aria-hidden
                  />
                  <span className="font-semibold text-text">{driver.label}</span>
                  <span className="num text-text-muted">
                    {driver.count} signal{driver.count === 1 ? "" : "s"}
                  </span>
                </motion.li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Expandable detailed explanation */}
      {!compact && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setShowWhy((open) => !open)}
            aria-expanded={showWhy}
            className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted transition-colors hover:text-text-2"
          >
            <Info size={11} aria-hidden />
            Why this status?
          </button>
          {showWhy && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <p className="rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-xs leading-relaxed text-text-2">
                {posture.why}
              </p>
              <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] uppercase tracking-wider text-text-muted">
                <Activity size={11} aria-hidden />
                posture score {posture.score}/100 ·
                {POSTURE_SCALE.map((step) => (
                  <span key={step.label}>
                    {step.min}+ {step.label}
                  </span>
                ))}
              </p>
            </motion.div>
          )}
        </div>
      )}
    </div>
  );
}
