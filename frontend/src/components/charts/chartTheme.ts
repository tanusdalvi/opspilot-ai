/** Chart palette bound to semantic CSS tokens; re-reads when theme flips. */

import { useMemo } from "react";
import { useTheme } from "../../state/theme";

export interface ChartTheme {
  text: string;
  textMuted: string;
  line: string;
  splitLine: string;
  surface: string;
  accent: string;
  /** Accent with alpha appended as hex — ECharts canvas cannot parse color-mix(). */
  accentSoft: string;
  accent2: string;
  ok: string;
  warn: string;
  danger: string;
  fontFamily: string;
  /** False when the user prefers reduced motion — charts then draw without animation. */
  motionOK: boolean;
}

function readVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

export function useChartTheme(): ChartTheme {
  const { resolved } = useTheme();
  return useMemo(() => {
    // resolved is a dependency: tokens change with the attribute.
    void resolved;
    const accent = readVar("--color-accent", "#5b8cff");
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    return {
      text: readVar("--color-text", "#e8edf7"),
      textMuted: readVar("--color-text-muted", "#66738c"),
      line: readVar("--color-line-strong", "rgba(148,163,199,0.28)"),
      splitLine: readVar("--color-line", "rgba(148,163,199,0.14)"),
      surface: readVar("--color-surface", "#111827"),
      accent,
      // Hex-alpha form is safe for both SVG and canvas rendering.
      accentSoft: `${accent}38`,
      accent2: readVar("--color-accent-2", "#7c5cff"),
      ok: readVar("--color-ok", "#34d399"),
      warn: readVar("--color-warn", "#ffb020"),
      danger: readVar("--color-danger", "#ff5d6c"),
      fontFamily:
        "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
      motionOK: !reduced,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);
}
