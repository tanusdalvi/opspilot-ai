import { describe, expect, it } from "vitest";
import { formatCompact, formatPct, dayBucket, formatBytes } from "./format";

describe("formatCompact", () => {
  it("abbreviates large magnitudes", () => {
    expect(formatCompact(1_250_000)).toBe("1.3M");
    expect(formatCompact(980)).toBe("980");
    expect(formatCompact(42_300)).toBe("42.3K");
    expect(formatCompact(-7_400_000_000)).toBe("-7.4B");
  });

  it("drops trailing .0", () => {
    expect(formatCompact(1000)).toBe("1K");
  });
});

describe("formatPct", () => {
  it("adds an explicit sign and one decimal", () => {
    expect(formatPct(4.25)).toBe("+4.3%");
    expect(formatPct(-2.11)).toBe("-2.1%");
    expect(formatPct(0)).toBe("0.0%");
  });

  it("renders a dash for missing values instead of fabricating one", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(undefined)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });
});

describe("formatBytes", () => {
  it("scales units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 ** 2)).toBe("5.0 MB");
  });
});

describe("dayBucket", () => {
  it("buckets relative to today without timezone drift", () => {
    const today = new Date(2026, 7, 23, 15, 0);
    expect(dayBucket(new Date(2026, 7, 23, 8, 0).toISOString(), today)).toBe("Today");
    expect(dayBucket(new Date(2026, 7, 22, 23, 30).toISOString(), today)).toBe(
      "Yesterday",
    );
    expect(dayBucket(new Date(2026, 6, 1).toISOString(), today)).toBe("Earlier");
  });

  it("falls back to Earlier for unparseable input", () => {
    expect(dayBucket("not-a-date")).toBe("Earlier");
  });
});
