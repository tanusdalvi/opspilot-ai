import { useEffect, useRef, useState } from "react";
import { motion, useInView } from "framer-motion";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Sparkline } from "../charts/Sparkline";
import { formatKpiValue, formatPct } from "../../lib/format";
import { kpiMeta } from "../../lib/labels";

/** Animated numeric counter (respects reduced-motion). */
function useCountUp(target: number, active: boolean): number {
  const [display, setDisplay] = useState(active ? 0 : target);
  const frame = useRef<number>(0);
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      setDisplay(target);
      return;
    }
    if (!active) {
      setDisplay(target);
      return;
    }
    const start = performance.now();
    const duration = 700;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(target * eased);
      if (progress < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [target, active]);
  return display;
}

export function StatTile({
  label,
  value,
  changePct,
  spark,
  index = 0,
}: {
  label: string;
  value: number;
  changePct?: number | null;
  spark?: number[];
  index?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const display = useCountUp(value, inView);
  const meta = kpiMeta(label);

  const tone =
    changePct === null || changePct === undefined
      ? "text-text-muted"
      : changePct >= 0
        ? "text-ok"
        : "text-danger";

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 14 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.4, delay: index * 0.05, ease: [0.22, 1, 0.36, 1] }}
      title={meta.description}
    >
      <div className="panel panel-hover h-full p-4">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
          {meta.title}
        </p>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="num text-2xl font-bold text-text">
            {formatKpiValue(display, meta.kind)}
          </span>
          {changePct !== null && changePct !== undefined && (
            <span className={`flex items-center gap-0.5 text-xs font-semibold ${tone}`}>
              {changePct >= 0 ? (
                <ArrowUpRight size={12} aria-hidden />
              ) : (
                <ArrowDownRight size={12} aria-hidden />
              )}
              {formatPct(changePct)}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[10px] uppercase tracking-wider text-text-muted">
          vs previous period
        </p>
        {spark && spark.length > 1 && (
          <div className="mt-2 opacity-80">
            <Sparkline values={spark} tone={(changePct ?? 0) < 0 ? "#ff5d6c" : "#5b8cff"} />
          </div>
        )}
      </div>
    </motion.div>
  );
}
