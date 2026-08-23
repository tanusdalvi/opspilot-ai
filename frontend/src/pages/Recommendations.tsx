import { useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardList, Sparkles } from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import {
  Badge,
  Button,
  EmptyState,
} from "../components/ui/Primitives";
import { metricTitle } from "../lib/severity";
import type { RecommendationRecord } from "../lib/types";

export default function Recommendations() {
  const { system, artifacts, ensurePlan } = useWorkspace();
  const [plan, setPlan] = useState<RecommendationRecord[] | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!system?.artifacts_ready && !system?.analysis_running) {
    return (
      <div>
        <PageHeader eyebrow="Intelligence" title="Recommendations" />
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="No analysis available"
          body="A recommendation plan is generated deterministically from the evidence pack. Load data and run analysis first."
          action={
            <Link to="/data">
              <Button>Open Data Workspace</Button>
            </Link>
          }
        />
      </div>
    );
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const payload = await ensurePlan();
      setPlan(payload.plan.recommendations);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  const recommendations =
    plan ??
    (artifacts
      ? ((artifacts as unknown as { plan?: { recommendations?: RecommendationRecord[] } }).plan?.recommendations ?? null)
      : null);

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Recommendations"
        description="Deterministic action candidates derived from the evidence pack. Decisions are recorded in Human Review."
      />

      <Panel className="mb-4 flex flex-wrap items-center justify-between gap-3 p-5">
        <SectionHeading
          title="Actionable plan"
          caption="Generate or refresh the deterministic recommendation plan."
        />
        <Button onClick={() => void handleGenerate()} disabled={generating}>
          <Sparkles size={14} />
          {generating ? "Generating…" : recommendations ? "Refresh Plan" : "Generate Plan"}
        </Button>
      </Panel>

      {error && (
        <p className="mb-4 rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {!recommendations ? (
        <Panel className="p-6 text-center text-sm text-text-2">
          No plan yet for this session. Generate one — it is persisted to the
          audit store exactly once per evidence state.
        </Panel>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {[...recommendations]
            .sort((a, b) => Number(b.priority_score ?? 0) - Number(a.priority_score ?? 0))
            .map((rec) => (
              <Panel key={rec.recommendation_id} className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-bold leading-snug text-text">
                    {rec.title}
                  </h3>
                  <Badge tone={priorityTone(rec.priority)}>{String(rec.priority)}</Badge>
                </div>
                <p className="mt-1.5 text-xs uppercase tracking-wider text-text-muted">
                  {metricTitle(String(rec.action_type ?? ""))}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <Badge tone="muted" withIcon={false}>
                    {String(rec.status)}
                  </Badge>
                  {rec.evidence_ids.length > 0 && (
                    <span className="num text-[11px] text-accent">
                      [{rec.evidence_ids.slice(0, 4).join(", ")}
                      {rec.evidence_ids.length > 4 ? ", …" : ""}]
                    </span>
                  )}
                </div>
              </Panel>
            ))}
          <Link
            to="/review"
            className="panel panel-hover col-span-full flex items-center justify-center p-3 text-sm font-semibold text-accent"
          >
            Open Human Review →
          </Link>
        </div>
      )}
    </div>
  );
}

function priorityTone(priority: string): "danger" | "warn" | "info" | "muted" {
  switch (String(priority).toUpperCase()) {
    case "CRITICAL":
      return "danger";
    case "HIGH":
      return "warn";
    case "MEDIUM":
      return "info";
    default:
      return "muted";
  }
}
