/** Human-readable rendering of the dataset validation report. */

import { AlertTriangle, CheckCircle2, CircleAlert } from "lucide-react";

interface ValidationReport {
  valid?: boolean;
  row_count?: number;
  column_count?: number;
  error_count?: number;
  warning_count?: number;
  errors?: unknown[];
  warnings?: unknown[];
}

export function ValidationSummary({
  report,
}: {
  report: Record<string, unknown>;
}) {
  const r = report as ValidationReport;
  const clean = (r.error_count ?? 0) === 0 && (r.warning_count ?? 0) === 0;

  return (
    <div className="mt-3 space-y-3 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-text-2">
        <span>
          Rows:{" "}
          <span className="num font-semibold text-text">
            {(r.row_count ?? 0).toLocaleString()}
          </span>
        </span>
        <span>
          Columns:{" "}
          <span className="num font-semibold text-text">
            {r.column_count ?? "—"}
          </span>
        </span>
        <span
          className={`flex items-center gap-1.5 font-semibold ${
            clean ? "text-ok" : "text-warn"
          }`}
        >
          {clean ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          {clean
            ? "No data issues detected"
            : `${r.error_count ?? 0} error${r.error_count === 1 ? "" : "s"} · ${
                r.warning_count ?? 0
              } warning${r.warning_count === 1 ? "" : "s"}`}
        </span>
      </div>

      {(r.errors ?? []).length > 0 && (
        <MessageList label="Errors" items={r.errors ?? []} tone="danger" />
      )}
      {(r.warnings ?? []).length > 0 && (
        <MessageList label="Warnings" items={r.warnings ?? []} tone="warn" />
      )}
    </div>
  );
}

function MessageList({
  label,
  items,
  tone,
}: {
  label: string;
  items: unknown[];
  tone: "danger" | "warn";
}) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
        {tone === "danger" ? (
          <CircleAlert size={11} aria-hidden />
        ) : (
          <AlertTriangle size={11} aria-hidden />
        )}
        {label}
      </p>
      <ul
        className={`mt-1.5 space-y-1 rounded-lg border px-3 py-2 text-xs leading-relaxed ${
          tone === "danger"
            ? "border-danger/30 bg-danger/[0.06] text-danger"
            : "border-warn/30 bg-warn/[0.06] text-warn"
        }`}
      >
        {items.map((item, i) => (
          <li key={i}>· {String(item)}</li>
        ))}
      </ul>
    </div>
  );
}
