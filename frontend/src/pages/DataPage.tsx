import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CalendarRange,
  CheckCircle2,
  Database,
  Play,
  Upload,
} from "lucide-react";
import { api } from "../lib/api";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
} from "../components/ui/Primitives";
import { AnalysisProgress } from "../components/ui/AnalysisProgress";
import { ValidationSummary } from "../components/ui/ValidationSummary";
import { formatBytes, formatNumber } from "../lib/format";
import type { DemoDataset } from "../lib/types";

/** Must mirror core.constants.MAX_UPLOAD_BYTES (20 MiB). */
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".csv"];

type UploadPhase = "idle" | "uploading" | "success" | "error";

interface UploadState {
  phase: UploadPhase;
  fileName?: string;
  fileSize?: number;
  message?: string;
}

export default function DataPage() {
  const { system, artifacts, loadDemo, uploadDataset, runAnalysis } =
    useWorkspace();
  const [sensitivity, setSensitivity] = useState("medium");
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [upload, setUpload] = useState<UploadState>({ phase: "idle" });
  const dataset = system?.dataset;
  const report = (artifacts?.validation_report ?? null) as Record<
    string,
    unknown
  > | null;

  const demoQuery = useQuery({
    queryKey: ["demo-datasets"],
    queryFn: () => api<{ datasets: DemoDataset[] }>("/api/demo-datasets"),
    staleTime: Infinity,
  });

  // Honest client-side clock around the polled analysis lifecycle.
  const [analysisStartedAt, setAnalysisStartedAt] = useState<number | null>(null);
  const wasRunning = useRef(false);
  const [lastRunDurationMs, setLastRunDurationMs] = useState<number | null>(null);
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  const running = system?.analysis_running === true;

  useEffect(() => {
    if (running && !wasRunning.current) {
      setAnalysisStartedAt(Date.now());
      setLastRunDurationMs(null);
    }
    if (!running && wasRunning.current && analysisStartedAt !== null) {
      setLastRunDurationMs(Date.now() - analysisStartedAt);
      setCompletedAt(new Date().toISOString());
    }
    wasRunning.current = running;
  }, [running, analysisStartedAt]);

  function validateFile(file: File): string | null {
    const extension = file.name
      .slice(file.name.lastIndexOf("."))
      .toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      return `${file.name} is not a supported format. Only CSV files can be analyzed${
        /\.(xlsx|xls|zip)$/i.test(file.name)
          ? " — please export your Excel or ZIP data as CSV first"
          : ""
      }.`;
    }
    if (file.size === 0) return `${file.name} appears to be empty.`;
    if (file.size > MAX_UPLOAD_BYTES) {
      return "File is too large. Maximum supported size is 20 MB.";
    }
    return null;
  }

  async function handleFile(file: File) {
    const problem = validateFile(file);
    if (problem) {
      setUpload({
        phase: "error",
        fileName: file.name,
        fileSize: file.size,
        message: problem,
      });
      return;
    }
    setUpload({ phase: "uploading", fileName: file.name, fileSize: file.size });
    try {
      await uploadDataset(file);
      setUpload({ phase: "success", fileName: file.name, fileSize: file.size });
    } catch (error) {
      setUpload({
        phase: "error",
        fileName: file.name,
        fileSize: file.size,
        message:
          error instanceof Error
            ? error.message
            : "The upload could not be completed.",
      });
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Data"
        title="Dataset Workspace"
        description="Load the operational dataset, inspect its identity and profile, then run the deterministic analysis."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        {/* LOAD */}
        <Panel className="p-5">
          <SectionHeading
            icon={<Database size={15} className="text-accent" aria-hidden />}
            title="Load dataset"
            caption="Bundled demo data or your own CSV upload."
          />
          <div className="space-y-3">
            {demoQuery.isLoading &&
              Array.from({ length: 1 }).map((_, i) => (
                <div
                  key={i}
                  className="skeleton h-[58px] w-full rounded-xl"
                  aria-hidden
                />
              ))}
            {(demoQuery.data?.datasets ?? []).map((entry) => (
              <button
                key={entry.name}
                onClick={() => void loadDemo(entry.name)}
                className="panel panel-hover flex w-full items-center justify-between px-4 py-3 text-left"
              >
                <span>
                  <span className="block text-sm font-semibold text-text">
                    {entry.name}
                  </span>
                  <span className="text-xs text-text-muted">
                    Bundled demo dataset
                    {typeof entry.rows === "number"
                      ? ` · ${formatNumber(entry.rows)} rows`
                      : entry.description
                        ? ` · ${entry.description}`
                        : ""}
                  </span>
                </span>
                <Badge tone="info" withIcon={false}>
                  Demo
                </Badge>
              </button>
            ))}
            {!demoQuery.isLoading &&
              (demoQuery.data?.datasets.length ?? 0) === 0 && (
                <p className="text-xs text-text-muted">
                  No bundled demo datasets are available.
                </p>
              )}

            {/* Drop zone */}
            <div
              role="button"
              tabIndex={0}
              aria-label="Upload a CSV dataset: drag and drop or press Enter to browse"
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                if (!e.currentTarget.contains(e.relatedTarget as Node))
                  setDragActive(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setDragActive(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void handleFile(file);
              }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-8 text-center transition ${
                dragActive
                  ? "border-accent bg-accent/[0.08]"
                  : "border-line-strong bg-white/[0.02] hover:border-accent/50"
              }`}
            >
              <Upload
                size={18}
                className={`mb-2 ${dragActive ? "text-accent" : "text-text-2"}`}
                aria-hidden
              />
              <p className="text-sm font-medium text-text-2">
                {dragActive
                  ? "Release to upload your CSV"
                  : "Drag & drop a CSV here, or click to browse"}
              </p>
              <p className="mt-1 text-xs text-text-muted">
                Up to 20 MB · validated before anything runs · ZIP/Excel must be
                exported as CSV first
              </p>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                aria-label="Upload CSV file"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleFile(file);
                  e.target.value = "";
                }}
              />
            </div>

            {/* Upload result / progress */}
            {upload.phase !== "idle" && (
              <div
                role="status"
                aria-live="polite"
                className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-3 ${
                  upload.phase === "uploading"
                    ? "border-accent/35 bg-accent/[0.07]"
                    : upload.phase === "success"
                      ? "border-ok/35 bg-ok/[0.07]"
                      : "border-danger/40 bg-danger/[0.08]"
                }`}
              >
                {upload.phase === "uploading" ? (
                  <span
                    className="mt-0.5 inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
                    aria-hidden
                  />
                ) : upload.phase === "success" ? (
                  <CheckCircle2
                    size={16}
                    className="mt-0.5 shrink-0 text-ok"
                    aria-hidden
                  />
                ) : (
                  <AlertCircle
                    size={16}
                    className="mt-0.5 shrink-0 text-danger"
                    aria-hidden
                  />
                )}
                <div className="min-w-0 text-sm">
                  <p className="font-semibold text-text">
                    {upload.fileName}
                    {upload.fileSize !== undefined && (
                      <span className="num ml-2 text-xs font-normal text-text-muted">
                        {formatBytes(upload.fileSize)}
                      </span>
                    )}
                  </p>
                  {upload.phase === "uploading" && (
                    <p className="text-xs text-text-2">
                      Uploading and validating…
                    </p>
                  )}
                  {upload.phase === "success" && (
                    <p className="text-xs text-ok">
                      Uploaded — it is now the active dataset. Run the analysis
                      when ready.
                    </p>
                  )}
                  {upload.phase === "error" && (
                    <p className="text-xs text-danger">{upload.message}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </Panel>

        {/* IDENTITY */}
        <Panel className="p-5">
          <SectionHeading
            title="Active dataset"
            caption="The currently loaded working copy for this session."
          />
          {!dataset ? (
            <EmptyState
              icon={<Database size={20} />}
              title="No dataset loaded"
              body="Load the bundled demo or upload a CSV to begin. Analysis stays unavailable until a dataset passes validation."
            />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm">
                <Identity label="File" value={dataset.name} wide mono />
                <Identity label="Rows" value={formatNumber(dataset.rows)} mono />
                <Identity label="Columns" value={formatNumber(dataset.columns)} mono />
                <Identity label="Memory" value={formatBytes(dataset.memory_bytes)} mono />
                {dataset.date_coverage && (
                  <Identity
                    label="Coverage"
                    value={`${dataset.date_coverage.first} → ${dataset.date_coverage.last}`}
                    wide
                    mono
                  />
                )}
              </dl>
              <div className="col-span-2 mt-4 flex items-center gap-2 rounded-lg border border-ok/30 bg-ok/[0.07] px-3 py-2">
                <CalendarRange size={14} className="shrink-0 text-ok" aria-hidden />
                <span className="text-xs font-semibold text-ok">
                  Validation passed — ready for analysis
                  {report &&
                  typeof report.warning_count === "number" &&
                  report.warning_count > 0
                    ? ` · ${report.warning_count} data warning${report.warning_count === 1 ? "" : "s"} noted`
                    : " · no data issues detected"}
                </span>
              </div>
              <Link
                to="/explorer"
                className="mt-3 inline-block text-xs font-semibold text-accent hover:underline"
              >
                Explore this dataset with charts and tables →
              </Link>
            </>
          )}
        </Panel>

        {/* RUN */}
        <Panel className="p-5 lg:col-span-2">
          <SectionHeading
            icon={<Play size={15} className="text-accent" aria-hidden />}
            title="Run analysis"
            caption="One deterministic pipeline pass: KPIs, comparison, anomalies, insights, evidence."
          />
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-text-2">
              Sensitivity
              <select
                value={sensitivity}
                onChange={(e) => setSensitivity(e.target.value)}
                className="rounded-lg border border-line-strong bg-bg-soft px-3 py-2 text-sm text-text"
              >
                {["low", "medium", "high"].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </label>
            <Button
              disabled={!dataset || running}
              onClick={() => void runAnalysis(sensitivity)}
            >
              <Play size={14} /> Run / Refresh Analysis
            </Button>
            {system?.artifacts_ready && !running && (
              <Link to="/analytics" className="ml-auto">
                <Button variant="ghost">Go to Analytics</Button>
              </Link>
            )}
          </div>

          {(running || lastRunDurationMs !== null) && (
            <AnalysisProgress
              running={running}
              datasetReady={dataset != null}
              startedAt={analysisStartedAt}
              durationMs={lastRunDurationMs}
              completedAt={completedAt}
            />
          )}

          {system?.analysis_status === "ERROR" && system?.analysis_error && (
            <div className="mt-3 rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-sm">
              <p className="font-semibold text-danger">
                Analysis could not be completed.
              </p>
              <p className="mt-0.5 text-xs text-danger/85">
                Reason: {system.analysis_error}
              </p>
            </div>
          )}

          {report && !running && (
            <details className="mt-4 rounded-xl border border-line bg-white/[0.02] px-4 py-3">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-text-muted">
                Validation detail
              </summary>
              <ValidationSummary report={report} />
            </details>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Identity({
  label,
  value,
  mono = false,
  wide = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <dt className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
        {label}
      </dt>
      <dd
        className={`mt-0.5 truncate text-sm font-semibold text-text ${mono ? "num" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}
