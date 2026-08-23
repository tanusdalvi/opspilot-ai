import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Radar } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonPanel,
} from "../components/ui/Primitives";
import { PageHeader, Panel } from "../components/ui/Panel";
import { Drawer } from "../components/ui/Drawer";
import { SEVERITY_ORDER, severity } from "../lib/severity";
import {
  anomalyTypeLabel,
  metricLabel,
  scopeLabel,
  signalTitle,
} from "../lib/labels";
import { formatDateShort } from "../lib/format";
import type { AnomalyRecord } from "../lib/types";

type Filter = "ALL" | string;

export default function Anomalies() {
  const { system, artifacts } = useWorkspace();
  const [filter, setFilter] = useState<Filter>("ALL");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const anomalies: AnomalyRecord[] = artifacts?.anomaly_result?.anomalies ?? [];

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const a of anomalies) {
      const key = String(a.severity ?? "UNKNOWN").toUpperCase();
      map[key] = (map[key] ?? 0) + 1;
    }
    return map;
  }, [anomalies]);

  const visible = useMemo(
    () =>
      anomalies
        .filter(
          (a) =>
            filter === "ALL" ||
            String(a.severity).toUpperCase() === filter,
        )
        .sort(
          (x, y) =>
            severity(y.severity).weight - severity(x.severity).weight ||
            Math.abs(Number(y.deviation_pct ?? 0)) -
              Math.abs(Number(x.deviation_pct ?? 0)),
        ),
    [anomalies, filter],
  );

  const selected =
    selectedKey !== null
      ? anomalies.find((a) => recordKey(a) === selectedKey) ?? null
      : null;

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Signal Wall" />
        <EmptyState
          icon={<Radar size={20} />}
          title="No analysis available"
          body="Run the deterministic analysis to populate the signal wall. Every entry cites its evidence."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Signal Wall"
        description="Every detected deviation, ranked by severity and magnitude. Select any card to open its detail drawer."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FilterChip
          label="All signals"
          count={anomalies.length}
          active={filter === "ALL"}
          onClick={() => setFilter("ALL")}
        />
        {SEVERITY_ORDER.filter((level) => counts[level]).map((level) => (
          <FilterChip
            key={level}
            label={severity(level).label}
            count={counts[level]}
            tone={severity(level).tone}
            active={filter === level}
            onClick={() => setFilter(level)}
          />
        ))}
      </div>

      {!artifacts ? (
        <SkeletonPanel lines={6} />
      ) : visible.length === 0 ? (
        <Panel className="p-6 text-center text-sm text-text-2">
          No signals at this severity. The deterministic detector found nothing
          beyond threshold.
        </Panel>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((record) => (
            <SignalCard
              key={recordKey(record)}
              record={record}
              onOpen={() => setSelectedKey(recordKey(record))}
            />
          ))}
        </div>
      )}

      <Drawer
        open={selected !== null}
        onClose={() => setSelectedKey(null)}
        title="Signal detail"
      >
        {selected && <SignalDetail record={selected} />}
      </Drawer>
    </div>
  );
}

function recordKey(record: AnomalyRecord): string {
  return JSON.stringify([
    record.type,
    record.metric,
    record.entity,
    record.date,
    record.deviation_pct,
    record.severity,
  ]);
}

const TONE_DOT: Record<string, string> = {
  danger: "bg-danger",
  warn: "bg-warn",
  info: "bg-accent",
  ok: "bg-ok",
  muted: "bg-line-strong",
};

function FilterChip({
  label,
  count,
  active,
  onClick,
  tone,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  tone?: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "border-accent/60 bg-accent/10 text-text"
          : "border-line-strong text-text-2 hover:text-text"
      }`}
    >
      {tone && (
        <span className={`h-2 w-2 rounded-full ${TONE_DOT[tone] ?? "bg-line-strong"}`} aria-hidden />
      )}
      {label}
      <span className="num text-text-muted">{count}</span>
    </button>
  );
}

function SignalCard({
  record,
  onOpen,
}: {
  record: AnomalyRecord;
  onOpen: () => void;
}) {
  const style = severity(record.severity);
  const deviation = Number(record.deviation_pct ?? 0);
  return (
    <button onClick={onOpen} className="panel panel-hover p-4 text-left">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={style.tone}>{style.label}</Badge>
        <span className="num text-sm font-bold text-danger">
          {deviation >= 0 ? "+" : ""}
          {deviation.toFixed(1)}%
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold leading-snug text-text">
        {signalTitle(record)}
      </p>
      <p className="mt-0.5 truncate text-xs text-text-2">
        {record.entity ? String(record.entity) : scopeLabel(record.scope)}
      </p>
      {record.date && (
        <p className="num mt-1 text-[11px] text-text-muted">
          {formatDateShort(String(record.date))}
        </p>
      )}
    </button>
  );
}

/** Curated, human-labeled fields — never a raw dump of internal keys. */
function SignalDetail({ record }: { record: AnomalyRecord }) {
  const style = severity(record.severity);
  const deviation = Number(record.deviation_pct ?? 0);

  const rows: [string, string][] = [];
  rows.push(["Detection", anomalyTypeLabel(record.type)]);
  rows.push(["Metric", metricLabel(record.metric)]);
  rows.push(["Scope", scopeLabel(record.scope)]);
  if (record.entity) rows.push(["Entity", String(record.entity)]);
  if (record.date) rows.push(["Date", formatDateShort(String(record.date))]);
  rows.push([
    "Deviation vs expected",
    `${deviation >= 0 ? "+" : ""}${deviation.toFixed(1)}%`,
  ]);

  // Remaining scalar fields from the deterministic record (humanized keys),
  // then nested scalars from `details` — objects are never stringified raw.
  const seen = new Set([
    "type",
    "metric",
    "scope",
    "entity",
    "date",
    "deviation_pct",
    "severity",
    "evidence",
    "details",
  ]);
  for (const [key, value] of Object.entries(record)) {
    if (seen.has(key) || typeof value === "object") continue;
    rows.push([humanize(key), stringifyScalar(value)]);
  }
  const details = record.details;
  if (details && typeof details === "object") {
    for (const [key, value] of Object.entries(details as Record<string, unknown>)) {
      if (typeof value === "object") continue;
      rows.push([humanize(key), stringifyScalar(value)]);
    }
  }

  return (
    <div>
      <Badge tone={style.tone}>{style.label}</Badge>
      <h3 className="mt-3 text-lg font-bold leading-snug text-text">
        {signalTitle(record)}
      </h3>

      <dl className="mt-5 space-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4 border-b border-line pb-2">
            <dt className="text-xs uppercase tracking-wider text-text-muted">
              {label}
            </dt>
            <dd className="num max-w-[60%] break-words text-right text-sm text-text">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-5 rounded-lg border border-line bg-white/[0.03] px-3 py-2 text-xs leading-relaxed text-text-2">
        Values are deterministic pipeline output. Cross-check this signal in the
        Evidence workspace before acting on it.
      </p>
    </div>
  );
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function stringifyScalar(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value ?? "—");
}
