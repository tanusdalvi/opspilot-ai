import { describe, expect, it } from "vitest";
import { severity, statusTone, metricTitle } from "./severity";

describe("severity", () => {
  it("maps every detector severity to tone + label + weight", () => {
    expect(severity("CRITICAL")).toEqual({
      tone: "danger",
      label: "Critical",
      weight: 4,
    });
    expect(severity("medium")?.tone).toBe("warn");
  });

  it("is never color-only: unknown severities keep their raw label", () => {
    const style = severity("SIGNAL_LOSS");
    expect(style.label).toBe("SIGNAL_LOSS");
    expect(style.tone).toBe("muted");
  });

  it("treats missing severity conservatively as Low", () => {
    expect(severity(undefined).label).toBe("Low");
    expect(severity(null).label).toBe("Low");
  });
});

describe("statusTone", () => {
  it("covers the review state machine statuses", () => {
    expect(statusTone("APPROVED")).toBe("ok");
    expect(statusTone("REJECTED")).toBe("danger");
    expect(statusTone("CHANGES_REQUESTED")).toBe("warn");
    expect(statusTone("PENDING")).toBe("info");
    expect(statusTone("EXPIRED")).toBe("muted");
  });
});

describe("metricTitle", () => {
  it("humanizes snake_case keys", () => {
    expect(metricTitle("total_revenue")).toBe("Total Revenue");
    expect(metricTitle("profit_margin_pct")).toBe("Profit Margin Pct");
  });
});
