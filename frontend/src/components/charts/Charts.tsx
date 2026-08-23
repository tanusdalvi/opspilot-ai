import ReactECharts from "echarts-for-react";
import { useChartTheme } from "./chartTheme";

/** Diverging % change bars (period comparison). */
export function DivergingBars({
  entries,
}: {
  entries: [string, number | null][];
}) {
  const theme = useChartTheme();
  const data = entries.map(([name, value]) => ({
    name,
    value: value ?? 0,
    itemStyle: { color: (value ?? 0) >= 0 ? theme.ok : theme.danger },
  }));
  const option = {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: "value",
      axisLabel: {
        formatter: "{value}%",
        color: theme.textMuted,
        fontSize: 10,
        fontFamily: theme.fontFamily,
      },
      splitLine: { lineStyle: { color: theme.splitLine } },
    },
    yAxis: {
      type: "category",
      data: entries.map(([name]) =>
        name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      ),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.text, fontSize: 11 },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
      valueFormatter: (v: number) => `${Number(v).toFixed(1)}%`,
    },
    series: [
      {
        type: "bar",
        data,
        barWidth: 14,
        itemStyle: { borderRadius: [4, 4, 4, 4] },
        label: {
          show: true,
          position: "right",
          fontFamily: theme.fontFamily,
          fontSize: 10,
          color: theme.textMuted,
          formatter: (p: { value: number }) =>
            `${p.value >= 0 ? "+" : ""}${p.value.toFixed(1)}%`,
        },
      },
    ],
  } as const;
  return <ReactECharts option={option} style={{ height: 240 }} notMerge />;
}

/** Daily trend area with optional anomaly overlay + brush. */
export function TrendArea({
  dates,
  values,
  metricLabel,
  overlayDates = [],
}: {
  dates: string[];
  values: number[];
  metricLabel: string;
  overlayDates?: string[];
}) {
  const theme = useChartTheme();
  const overlaySet = new Set(overlayDates);
  const option = {
    grid: { left: 12, right: 16, top: 28, bottom: 42, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
    },
    legend: {
      show: overlayDates.length > 0,
      top: 0,
      textStyle: { color: theme.text, fontSize: 10 },
      data: [metricLabel, "Anomaly"],
    },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 6 }],
    xAxis: {
      type: "category",
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: { color: theme.textMuted, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: {
        color: theme.textMuted,
        fontSize: 10,
        fontFamily: theme.fontFamily,
      },
    },
    series: [
      {
        name: metricLabel,
        type: "line",
        data: values,
        symbol: "none",
        smooth: true,
        lineStyle: { width: 2, color: theme.accent },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${theme.accent}38` },
              { offset: 1, color: `${theme.accent}03` },
            ],
          },
        },
      },
      ...(overlayDates.length
        ? [
            {
              name: "Anomaly",
              type: "scatter",
              symbolSize: 9,
              itemStyle: { color: theme.warn },
              data: values.map((v, i) => ({
                value: [dates[i], v],
                itemStyle: overlaySet.has(dates[i])
                  ? { color: theme.warn }
                  : { opacity: 0 },
              })),
            },
          ]
        : []),
    ],
  } as const;
  return (
    <ReactECharts option={option} style={{ height: 360 }} notMerge lazyUpdate />
  );
}

export function GroupedBars({
  categories,
  series,
}: {
  categories: string[];
  series: { name: string; values: number[] }[];
}) {
  const theme = useChartTheme();
  const palette = [theme.accent, "#7c5cff", theme.ok, theme.warn];
  const option = {
    grid: { left: 8, right: 12, top: 30, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
    },
    legend: {
      top: 0,
      textStyle: { color: theme.text, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: { color: theme.textMuted, fontSize: 10, fontFamily: theme.fontFamily },
    },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.text, fontSize: 10 },
    },
    series: series.map((s, i) => ({
      name: s.name,
      type: "bar",
      data: s.values,
      barMaxWidth: 18,
      itemStyle: {
        borderRadius: [4, 4, 0, 0],
        color: palette[i % palette.length],
      },
    })),
  } as const;
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />;
}

/** XY scatter for two numeric columns. */
export function ScatterPlot({
  points,
  xLabel,
  yLabel,
}: {
  points: { x: number; y: number }[];
  xLabel: string;
  yLabel: string;
}) {
  const theme = useChartTheme();
  const option = {
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (p: { value: [number, number] }) =>
        `${xLabel}: ${p.value[0].toLocaleString()}<br/>${yLabel}: ${p.value[1].toLocaleString()}`,
    },
    xAxis: {
      type: "value",
      scale: true,
      name: xLabel,
      nameTextStyle: { color: theme.textMuted, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: { color: theme.textMuted, fontSize: 10, fontFamily: theme.fontFamily },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: yLabel,
      nameTextStyle: { color: theme.textMuted, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: { color: theme.textMuted, fontSize: 10, fontFamily: theme.fontFamily },
    },
    series: [
      {
        type: "scatter",
        symbolSize: 7,
        data: points.map((p) => [p.x, p.y]),
        itemStyle: {
          color: `${theme.accent}b0`,
          borderColor: theme.accent,
          borderWidth: 1,
        },
      },
    ],
  } as const;
  return <ReactECharts option={option} style={{ height: 340 }} notMerge />;
}

/** Value distribution buckets for a single numeric column. */
export function HistogramChart({
  buckets,
  valueLabel,
}: {
  buckets: { label: string; value: number }[];
  valueLabel: string;
}) {
  const theme = useChartTheme();
  const option = {
    grid: { left: 8, right: 12, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
    },
    xAxis: {
      type: "category",
      name: valueLabel,
      nameTextStyle: { color: theme.textMuted, fontSize: 10 },
      data: buckets.map((b) => b.label),
      axisLabel: { color: theme.textMuted, fontSize: 9, rotate: 35 },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      name: "Rows",
      nameTextStyle: { color: theme.textMuted, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.splitLine } },
      axisLabel: { color: theme.textMuted, fontSize: 10, fontFamily: theme.fontFamily },
    },
    series: [
      {
        type: "bar",
        data: buckets.map((b) => b.value),
        barCategoryGap: "8%",
        itemStyle: {
          borderRadius: [3, 3, 0, 0],
          color: `${theme.accent}cc`,
        },
      },
    ],
  } as const;
  return <ReactECharts option={option} style={{ height: 340 }} notMerge />;
}

/** Category share donut — only rendered when a category column is chosen. */
export function DonutChart({
  slices,
}: {
  slices: { label: string; value: number }[];
}) {
  const theme = useChartTheme();
  const palette = [
    theme.accent,
    "#7c5cff",
    theme.ok,
    theme.warn,
    "#e879a0",
    "#38bdf8",
    "#f97350",
    "#94a3b8",
  ];
  const option = {
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.line,
      textStyle: { color: theme.text, fontSize: 11 },
    },
    legend: {
      orient: "vertical" as const,
      right: 4,
      top: "middle",
      textStyle: { color: theme.text, fontSize: 10 },
      type: "scroll",
    },
    series: [
      {
        type: "pie",
        radius: ["52%", "78%"],
        center: ["40%", "50%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: theme.surface, borderWidth: 2 },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            formatter: "{b}",
            color: theme.text,
            fontSize: 11,
          },
        },
        data: slices.map((s, i) => ({
          name: s.label,
          value: s.value,
          itemStyle: { color: palette[i % palette.length] },
        })),
      },
    ],
  } as const;
  return <ReactECharts option={option} style={{ height: 320 }} notMerge />;
}
