import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Brain,
  ChevronRight,
  Search,
  Sparkles,
  Zap,
  CheckCircle2,
  AlertTriangle,
  BarChart3,
  TrendingUp,
  ArrowRight,
  Play,
  RotateCcw,
} from "lucide-react";
import { useWorkspace } from "../state/workspace";
import { api } from "../lib/api";
import { PageHeader, Panel, SectionHeading } from "../components/ui/Panel";
import { Badge, Button } from "../components/ui/Primitives";

interface ToolResult {
  tool: string;
  status: "success" | "error";
  data?: Record<string, unknown>;
  error?: string;
}

interface InvestigationPlan {
  question: string;
  selected_tools: { name: string; description: string }[];
  available_tools: { name: string; description: string; category: string }[];
}

interface InvestigationResponse {
  status: string;
  plan: InvestigationPlan;
  evidence: ToolResult[];
  conclusion: string;
  tools_available: number;
  tools_executed: number;
}

const EXAMPLE_QUESTIONS = [
  "Why are operations deteriorating?",
  "Which region has the worst lead times?",
  "How is cost trending across products?",
  "What is driving the recent demand spike?",
  "Are there anomalies in revenue this quarter?",
];

const TOOL_ICONS: Record<string, typeof Brain> = {
  summary: BarChart3,
  trend: TrendingUp,
  comparison: TrendingUp,
  anomaly: AlertTriangle,
  segment: BarChart3,
};

function toolCategoryIcon(category: string) {
  const Icon = TOOL_ICONS[category] || Brain;
  return <Icon size={14} className="text-accent" />;
}

export default function InvestigationCenter() {
  const { system } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<InvestigationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hasDataset = !!system?.dataset;
  const hasAnalysis = system?.artifacts_ready === true;

  async function handleInvestigate(q: string) {
    if (!q.trim()) return;
    setQuestion(q.trim());
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await api<InvestigationResponse>("/api/investigate", {
        method: "POST",
        json: { question: q.trim() },
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Intelligence"
        title="Investigation Center"
        description="Ask a question about your operational data. The system selects relevant analytical tools, gathers evidence, and presents grounded findings."
      />

      {/* QUESTION INPUT */}
      <Panel className="p-6">
        <div className="mx-auto max-w-2xl">
          <div className="relative">
            <Search
              size={18}
              className="absolute left-4 top-1/2 -translate-y-1/2 text-text-muted"
              aria-hidden
            />
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !loading) handleInvestigate(question);
              }}
              placeholder="Ask a question about your operations..."
              disabled={!hasAnalysis || loading}
              className="w-full rounded-xl border border-line bg-surface py-3.5 pl-11 pr-28 text-sm text-text placeholder:text-text-muted/60 transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30 disabled:opacity-50"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1.5">
              {result && (
                <button
                  type="button"
                  onClick={() => {
                    setResult(null);
                    setQuestion("");
                  }}
                  className="rounded-lg border border-line bg-faint p-2 text-text-muted hover:text-text transition-colors"
                  title="Reset"
                >
                  <RotateCcw size={14} />
                </button>
              )}
              <button
                type="button"
                onClick={() => handleInvestigate(question)}
                disabled={!hasAnalysis || loading || !question.trim()}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent-2 transition-colors disabled:opacity-40 flex items-center gap-1.5"
              >
                {loading ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    Investigating
                  </>
                ) : (
                  <>
                    <Play size={12} />
                    Investigate
                  </>
                )}
              </button>
            </div>
          </div>

          {!hasAnalysis && hasDataset && (
            <p className="mt-2 text-xs text-text-muted">
              Run analysis first before investigating.
            </p>
          )}
          {!hasDataset && (
            <p className="mt-2 text-xs text-text-muted">
              Load a dataset to begin.{" "}
              <Link to="/data" className="text-accent hover:underline">
                Open Data Workspace
              </Link>
            </p>
          )}
        </div>
      </Panel>

      {/* EXAMPLE QUESTIONS (shown when no result yet) */}
      {!result && !loading && (
        <Panel className="mt-4 p-5">
          <SectionHeading
            icon={<Sparkles size={15} className="text-accent" aria-hidden />}
            title="Example questions"
            caption="Click an example or type your own."
          />
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((eq) => (
              <button
                key={eq}
                type="button"
                onClick={() => handleInvestigate(eq)}
                disabled={!hasAnalysis}
                className="rounded-lg border border-line bg-faint px-3 py-2 text-xs text-text-2 hover:border-accent/40 hover:bg-accent/[0.06] transition-colors disabled:opacity-40"
              >
                {eq}
              </button>
            ))}
          </div>
        </Panel>
      )}

      {/* LOADING STATE */}
      {loading && (
        <Panel className="mt-4 p-8">
          <div className="flex flex-col items-center gap-4">
            <div className="relative">
              <div className="h-16 w-16 animate-spin rounded-full border-4 border-line border-t-accent" />
              <Brain
                size={24}
                className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-accent"
              />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-text">Running investigation</p>
              <p className="mt-1 text-xs text-text-muted">
                Selecting tools, gathering evidence, synthesizing findings...
              </p>
            </div>
          </div>
        </Panel>
      )}

      {/* ERROR */}
      {error && (
        <Panel className="mt-4 p-5">
          <div className="flex items-center gap-3 rounded-lg border border-danger/20 bg-danger/[0.06] p-4">
            <AlertTriangle size={16} className="shrink-0 text-danger" />
            <div>
              <p className="text-sm font-medium text-danger">Investigation failed</p>
              <p className="mt-0.5 text-xs text-text-muted">{error}</p>
            </div>
          </div>
        </Panel>
      )}

      {/* RESULTS */}
      {result && (
        <div className="mt-4 space-y-4">
          {/* Investigation Plan */}
          <Panel className="p-5">
            <SectionHeading
              icon={<Brain size={15} className="text-accent" aria-hidden />}
              title="Investigation plan"
              caption={`Question: "${result.plan.question}"`}
            />
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {result.plan.selected_tools.map((tool) => (
                <div
                  key={tool.name}
                  className="flex items-start gap-2.5 rounded-lg border border-accent/20 bg-accent/[0.04] p-3"
                >
                  <CheckCircle2
                    size={14}
                    className="mt-0.5 shrink-0 text-accent"
                  />
                  <div>
                    <p className="text-xs font-semibold text-text">{tool.name}</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                      {tool.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[10px] uppercase tracking-wider text-text-muted">
              {result.tools_executed} of {result.tools_available} available tools executed
            </p>
          </Panel>

          {/* Evidence */}
          <Panel className="p-5">
            <SectionHeading
              icon={<Zap size={15} className="text-accent" aria-hidden />}
              title="Evidence gathered"
              caption="Results from each analytical tool applied to the active dataset."
            />
            <div className="mt-3 space-y-3">
              {result.evidence.map((item, idx) => (
                <EvidenceCard key={`${item.tool}-${idx}`} item={item} />
              ))}
            </div>
          </Panel>

          {/* Conclusion */}
          <Panel className="p-5">
            <SectionHeading
              icon={<Sparkles size={15} className="text-accent" aria-hidden />}
              title="Investigation conclusion"
              caption="Grounded synthesis of the evidence. No claims are made beyond what the data supports."
            />
            <div className="mt-3 whitespace-pre-line rounded-lg border border-line bg-faint p-4 text-sm leading-relaxed text-text-2">
              {result.conclusion}
            </div>
          </Panel>

          {/* Next Steps */}
          <Panel className="p-5">
            <SectionHeading
              title="Next steps"
              caption="Actions you can take based on this investigation."
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/anomalies">
                <Button variant="subtle" className="text-xs">
                  View Findings <ChevronRight size={12} />
                </Button>
              </Link>
              <Link to="/recommendations">
                <Button variant="subtle" className="text-xs">
                  Generate Recommendations <ArrowRight size={12} />
                </Button>
              </Link>
              <Link to="/evidence">
                <Button variant="subtle" className="text-xs">
                  Full Evidence Pack <ChevronRight size={12} />
                </Button>
              </Link>
            </div>
          </Panel>
        </div>
      )}

      {/* AVAILABLE TOOLS (shown when no result yet) */}
      {!result && !loading && hasAnalysis && (
        <Panel className="mt-4 p-5">
          <SectionHeading
            icon={<Zap size={15} className="text-accent" aria-hidden />}
            title="Available analytical tools"
            caption="These tools are available for investigation based on the active dataset."
          />
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {[
              { name: "get_sales_summary", desc: "Aggregate sales metrics", cat: "summary" },
              { name: "get_product_performance", desc: "Breakdown by product", cat: "segment" },
              { name: "get_region_performance", desc: "Breakdown by region", cat: "segment" },
              { name: "get_period_comparison", desc: "Period-over-period changes", cat: "comparison" },
              { name: "detect_anomalies", desc: "Statistical anomaly detection", cat: "anomaly" },
              { name: "get_trend_analysis", desc: "Trend direction and magnitude", cat: "trend" },
              { name: "get_cost_ratio_analysis", desc: "Cost-to-revenue ratio trends", cat: "trend" },
              { name: "get_lead_time_analysis", desc: "Lead time trends and distribution", cat: "trend" },
            ].map((tool) => (
              <div
                key={tool.name}
                className="flex items-center gap-2.5 rounded-lg border border-line bg-faint px-3 py-2.5"
              >
                {toolCategoryIcon(tool.cat)}
                <div>
                  <p className="text-xs font-medium text-text">{tool.name}</p>
                  <p className="text-[11px] text-text-muted">{tool.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

function EvidenceCard({ item }: { item: ToolResult }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-line bg-faint">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          {item.status === "success" ? (
            <CheckCircle2 size={14} className="text-ok" />
          ) : (
            <AlertTriangle size={14} className="text-danger" />
          )}
          <span className="text-xs font-semibold text-text">{item.tool}</span>
          <Badge tone={item.status === "success" ? "ok" : "danger"} withIcon={false}>
            {item.status}
          </Badge>
        </div>
        <ChevronRight
          size={14}
          className={`text-text-muted transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      {expanded && (
        <div className="border-t border-line px-4 py-3">
          {item.status === "success" && item.data ? (
            <pre className="max-h-64 overflow-auto text-[11px] leading-relaxed text-text-2">
              {JSON.stringify(item.data, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-danger">{item.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
