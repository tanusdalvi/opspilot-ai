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

export interface DatasetCompatibility {
  tier: "full" | "partial" | "unsupported";
  reasons: string[];
  mapping: Record<string, string>;
  synthesized: string[];
  positional_fallback: boolean;
  dropped_rows: number;
  affected_derived_kpis: string[];
}

export interface CapabilityProfile {
  dataset_class: "A" | "B" | "C" | "D" | "E";
  row_count: number;
  column_count: number;
  has_date: boolean;
  has_numeric: boolean;
  has_categorical: boolean;
  date_columns: string[];
  numeric_columns: string[];
  categorical_columns: string[];
  capabilities: {
    time_series_analysis: boolean;
    anomaly_detection: boolean;
    trend_analysis: boolean;
    period_comparison: boolean;
    distribution_analysis: boolean;
    segment_comparison: boolean;
    outlier_detection: boolean;
    correlation_analysis: boolean;
    category_frequency: boolean;
    visualization: boolean;
    finding_generation: boolean;
    recommendation_generation: boolean;
  };
  classification_reasons: string[];
  unavailable_capabilities: string[];
}

export interface DatasetInfo {
  name: string;
  source?: "demo" | "upload" | string;
  rows: number;
  columns: number;
  memory_bytes: number;
  date_coverage?: {
    column: string;
    first: string;
    last: string;
    days: number;
  } | null;
  compatibility?: DatasetCompatibility | null;
  capability_profile?: CapabilityProfile | null;
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

export interface Finding {
  finding_id: string;
  title: string;
  severity: string;
  score: number;
  metric: string;
  metric_label: string;
  entities: string[];
  scopes: string[];
  start_date: string | null;
  end_date: string | null;
  signal_count: number;
  max_deviation_pct: number;
  max_anomaly_score: number;
  headline: string;
  evidence_summary?: string;
  anomaly_indices: number[];
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
  findings: Finding[];
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
  description?: string;
  problem_statement?: string;
  why_it_matters?: string;
  likely_drivers?: string[];
  expected_benefit?: string;
  evidence_ids: string[];
  evidence_strength?: number;
  target_metric?: string;
  target_entity?: string | null;
  source_factors?: string[];
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
