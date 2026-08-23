/** Wire-format types mirroring backend/api serializers (Phase 12). */

export type AnalysisStatus =
  | "IDLE"
  | "ANALYZING"
  | "READY"
  | "ERROR"
  | "RECOVERY_AVAILABLE";

export type InvestigationStatus =
  | "idle"
  | "running"
  | "complete"
  | "error";

export type LifecycleStage =
  | "OBSERVE"
  | "UNDERSTAND"
  | "DETECT"
  | "INVESTIGATE"
  | "RECOMMEND"
  | "HUMAN DECISION"
  | "AUDIT";

export interface DatasetInfo {
  name: string;
  rows: number;
  columns: number;
  memory_bytes: number;
  date_coverage?: {
    column: string;
    first: string;
    last: string;
    days: number;
  } | null;
}

export interface SystemPayload {
  session_token?: string;
  analysis_status: AnalysisStatus;
  analysis_error: string | null;
  analysis_running: boolean;
  artifacts_ready: boolean;
  dataset: DatasetInfo | null;
  ai_available: boolean;
  gemini_model: string;
  investigation_status: InvestigationStatus;
  recovery_context: RecoveryContext | null;
  lifecycle_stage: LifecycleStage;
  environment: string;
}

export interface RecoveryContext {
  dataset_name: string;
  sensitivity: string;
  completed_at: string;
}

export interface DemoDataset {
  name: string;
  rows?: number;
  description?: string;
}

export type ColumnKind = "date" | "numeric" | "categorical" | "text";

export interface PreviewColumn {
  name: string;
  kind: ColumnKind;
}

export interface DatasetPreview {
  columns: PreviewColumn[];
  rows: Record<string, unknown>[];
  total_rows: number;
}

export interface EvidenceEntry {
  kind: string;
  label: string;
  value?: unknown;
  field?: string;
  deviation_pct?: number;
  [key: string]: unknown;
}

export interface AnomalyRecord {
  [key: string]: unknown;
  severity?: string;
  metric?: string;
  entity?: string;
  scope?: string;
  deviation_pct?: number;
  date?: string;
}

export interface Pack {
  type: string;
  schema_version: number | string;
  parameters: Record<string, unknown>;
  kpis: Record<string, number>;
  period_comparison: { changes_pct: Record<string, number | null> };
  evidence_index: Record<string, EvidenceEntry>;
  anomalies: AnomalyRecord[];
  insights?: unknown[];
  groups?: unknown[];
  [key: string]: unknown;
}

export interface Posture {
  score: number;
  band: string;
  tone: string;
}

export interface ArtifactsPayload {
  dataset_name: string;
  validation_report: Record<string, unknown>;
  kpis: Record<string, number>;
  period_comparison: { changes_pct: Record<string, number | null> };
  top_performers: Record<string, unknown>;
  bottom_performers: Record<string, unknown>;
  anomaly_result: {
    anomalies: AnomalyRecord[];
    total_count: number;
    by_severity: Record<string, number>;
    sensitivity: string;
    metrics_analyzed: string[];
  };
  anomaly_summary: Record<string, unknown>;
  insights: InsightRecord[];
  grouping: { groups?: GroupRecord[] };
  pack: Pack;
  region_performance: Record<string, unknown>[];
  product_performance: Record<string, unknown>[];
  daily_trends: Record<string, unknown>[];
  row_count: number | null;
  posture: Posture | null;
}

export interface InsightRecord {
  insight_id?: string;
  title?: string;
  narrative?: string;
  severity?: string;
  dimension?: string;
  [key: string]: unknown;
}

export interface GroupRecord {
  group_id?: string;
  headline?: string;
  body?: string;
  members?: unknown[];
  [key: string]: unknown;
}

export interface NarrativeFinding {
  claim: string;
  evidence_ids: string[];
}

export interface InvestigationResult {
  status: "complete" | "narrative_rejected";
  evidence_pack: Pack;
  narrative: {
    executive_summary: string;
    key_findings: NarrativeFinding[];
    operational_interpretation: NarrativeFinding[];
  };
  hypotheses: {
    hypothesis: string;
    factor: string | null;
    confidence: number;
    evidence_ids: string[];
  }[];
  citations: { evidence_id: string; claim: string }[];
  grounding_report: {
    valid: boolean;
    citation_errors: string[];
    numeric_errors: string[];
    causation_errors: string[];
    schema_errors: string[];
    unsupported_claims: string[];
  };
}

export interface RecommendationRecord {
  recommendation_id: string;
  title: string;
  priority: string;
  priority_score?: number;
  action_type: string;
  status: string;
  evidence_ids: string[];
  [key: string]: unknown;
}

export interface PlanPayload {
  plan: {
    recommendations: RecommendationRecord[];
    parameters?: Record<string, unknown>;
    source?: Record<string, unknown>;
    summary?: Record<string, unknown>;
    type?: string;
    schema_version?: string | number;
    [key: string]: unknown;
  };
  plan_persisted_id: number | null;
}

export interface ReviewEvent {
  event_id?: number;
  recommendation_id: string;
  decision: string;
  previous_status: string;
  new_status: string;
  reviewer_id: string;
  comment?: string | null;
  occurred_at: string;
}

export interface HistoryPayload {
  counts: { plans: number; recommendations: number; review_events: number };
  plans: {
    plan_id: number;
    recorded_at: string;
    plan_type: string;
    schema_version: string;
    recommendation_count: number;
    source: Record<string, unknown>;
    parameters: Record<string, unknown>;
    summary: Record<string, unknown>;
  }[];
  recommendation_snapshots: (RecommendationRecord & { recorded_at?: string })[];
  review_events: ReviewEvent[];
}
