/** Dependency-free SVG sparkline — keeps ECharts out of the initial bundle. */

import { memo, useId } from "react";

export const Sparkline = memo(function Sparkline({
  values,
  tone = "var(--accent)",
  height = 34,
}: {
  values: number[];
  /** Any CSS color; defaults to the semantic accent token. */
  tone?: string;
  height?: number;
}) {
  const gradientId = useId();
  if (values.length < 2) return null;

  const width = 120;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - 3 - ((v - min) / span) * (height - 6);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden
      className="h-[34px] w-full"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.27" />
          <stop offset="100%" stopColor={tone} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,${height} ${points.join(" ")} ${width},${height}`}
        fill={`url(#${gradientId})`}
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={tone}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
});
