import { describe, expect, it } from "vitest";
import {
  aggregateByCategory,
  allowedChartTypes,
  histogram,
  recommendConfig,
  scatterPoints,
  seriesOverTime,
} from "./explorer";
import type { DatasetPreview, PreviewColumn } from "./types";

function col(name: string, kind: PreviewColumn["kind"]): PreviewColumn {
  return { name, kind };
}

describe("recommendConfig", () => {
  it("recommends an area trend for date + numeric datasets", () => {
    const preview: DatasetPreview = {
      columns: [col("date", "date"), col("revenue", "numeric")],
      rows: [],
      total_rows: 0,
    };
    const config = recommendConfig(preview);
    expect(config.chartType).toBe("area");
    expect(config.x).toBe("date");
    expect(config.y).toBe("revenue");
  });

  it("recommends a bar chart for category + numeric datasets", () => {
    const preview: DatasetPreview = {
      columns: [col("region", "categorical"), col("cost", "numeric")],
      rows: [],
      total_rows: 0,
    };
    expect(recommendConfig(preview).chartType).toBe("bar");
  });

  it("recommends scatter for two numeric columns without dates", () => {
    const preview: DatasetPreview = {
      columns: [col("a", "numeric"), col("b", "numeric")],
      rows: [],
      total_rows: 0,
    };
    const config = recommendConfig(preview);
    expect(config.chartType).toBe("scatter");
    expect(config.y).toBe("b");
  });

  it("recommends histogram when only one numeric column exists", () => {
    const preview: DatasetPreview = {
      columns: [col("v", "numeric"), col("note", "text")],
      rows: [],
      total_rows: 0,
    };
    expect(recommendConfig(preview).chartType).toBe("histogram");
  });

  it("falls back to donut for category-only datasets", () => {
    const preview: DatasetPreview = {
      columns: [col("region", "categorical")],
      rows: [],
      total_rows: 0,
    };
    expect(recommendConfig(preview).chartType).toBe("donut");
  });
});

describe("allowedChartTypes", () => {
  const columns = [
    col("date", "date"),
    col("region", "categorical"),
    col("revenue", "numeric"),
    col("units", "numeric"),
  ];

  it("offers time-series charts for date + numeric", () => {
    expect(allowedChartTypes(columns, "date", "revenue")).toEqual([
      "line",
      "area",
      "bar",
    ]);
  });

  it("restricts to scatter for two numeric axes", () => {
    expect(allowedChartTypes(columns, "revenue", "units")).toEqual(["scatter"]);
  });

  it("offers histogram for a single numeric axis", () => {
    expect(allowedChartTypes(columns, "revenue", null)).toEqual(["histogram"]);
  });

  it("never offers charts without any axis selection", () => {
    expect(allowedChartTypes(columns, null, null)).toEqual(["table"]);
  });
});

describe("aggregateByCategory", () => {
  const rows = [
    { region: "East", revenue: 100 },
    { region: "East", revenue: 50 },
    { region: "West", revenue: 30 },
  ];

  it("sums numeric values per category", () => {
    const points = aggregateByCategory(rows, "region", "revenue", "sum");
    expect(points).toEqual([
      { label: "East", value: 150 },
      { label: "West", value: 30 },
    ]);
  });

  it("averages per category", () => {
    const points = aggregateByCategory(rows, "region", "revenue", "average");
    expect(points[0]).toEqual({ label: "East", value: 75 });
  });

  it("counts rows when aggregating by count", () => {
    const points = aggregateByCategory(rows, "region", null, "count");
    expect(points).toEqual([
      { label: "East", value: 2 },
      { label: "West", value: 1 },
    ]);
  });

  it("folds overflow categories into Other instead of dropping them", () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      region: `R${i}`,
      revenue: i + 1,
    }));
    const points = aggregateByCategory(many, "region", "revenue", "sum", 5);
    expect(points.length).toBe(5);
    expect(points[points.length - 1].label).toBe("Other");
    const keptTotal = points
      .slice(0, -1)
      .reduce((a, p) => a + p.value, 0);
    expect(keptTotal + points[points.length - 1].value).toBe(78);
  });
});

describe("seriesOverTime", () => {
  it("sorts chronologically and aggregates per day", () => {
    const rows = [
      { date: "2025-01-02T00:00:00", v: 10 },
      { date: "2025-01-01T00:00:00", v: 5 },
      { date: "2025-01-01T00:00:00", v: 7 },
    ];
    const series = seriesOverTime(rows, "date", "v", "sum");
    expect(series.dates).toEqual(["2025-01-01", "2025-01-02"]);
    expect(series.values).toEqual([12, 10]);
  });
});

describe("scatterPoints", () => {
  it("drops rows where either coordinate is not finite", () => {
    const points = scatterPoints(
      [
        { x: 1, y: 2 },
        { x: Number.NaN, y: 3 },
        { x: 4, y: "nope" },
        { x: 5, y: 6 },
      ],
      "x",
      "y",
    );
    expect(points).toEqual([
      { x: 1, y: 2 },
      { x: 5, y: 6 },
    ]);
  });
});

describe("histogram", () => {
  it("buckets values across the full range", () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({ v: i }));
    const buckets = histogram(rows, "v", 5);
    expect(buckets.length).toBe(5);
    const total = buckets.reduce((a, b) => a + b.value, 0);
    expect(total).toBe(10);
  });

  it("handles a constant column as one bucket", () => {
    const rows = [{ v: 3 }, { v: 3 }, { v: 3 }];
    const buckets = histogram(rows, "v");
    expect(buckets).toEqual([{ label: "3", value: 3 }]);
  });

  it("returns nothing when no numeric values exist", () => {
    expect(histogram([{ v: "x" }], "v")).toEqual([]);
  });
});
