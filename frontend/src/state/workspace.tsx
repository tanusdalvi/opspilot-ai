/** Global workspace context: system polling, toasts, session bootstrap. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUpload } from "../lib/api";
import type {
  ArtifactsPayload,
  InvestigationResult,
  PlanPayload,
  SystemPayload,
} from "../lib/types";

export interface Toast {
  id: number;
  tone: "info" | "ok" | "warn" | "danger";
  title: string;
  body?: string;
}

interface WorkspaceValue {
  system: SystemPayload | undefined;
  artifacts: ArtifactsPayload | undefined;
  toasts: Toast[];
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
  loadDemo: (filename: string) => Promise<void>;
  uploadDataset: (file: File) => Promise<void>;
  runAnalysis: (sensitivity: string, wait?: boolean) => Promise<void>;
  /** True from click until a definitive READY/ERROR outcome arrives. */
  runPending: boolean;
  startInvestigation: () => Promise<void>;
  investigation: {
    status: string;
    error: string | null;
    result: InvestigationResult | null;
  };
  ensurePlan: (maxRecommendations?: number) => Promise<PlanPayload>;
  /** Tracks the current stage of a data-loading flow (null when idle). */
  loadingStage: string | null;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

const ANALYSIS_POLL_MS = 700;
const INVESTIGATION_POLL_MS = 900;

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);
  // Explicit-action latch: the AI call fires only when this is armed.
  const [investigationArmed, setInvestigationArmed] = useState(false);
  const [loadingStage, setLoadingStage] = useState<string | null>(null);

  const pushToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = ++toastId.current;
    setToasts((current) => [...current.slice(-3), { ...toast, id }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, 5200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  // Run latch: armed when the user starts an analysis and disarmed only
  // by a definitive backend outcome (READY / ERROR). Polling continues
  // while it is armed even if one poll misses the ANALYZING window.
  const [runPending, setRunPending] = useState(false);

  const system = useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemPayload>("/api/system"),
    refetchInterval: (query) =>
      runPending ||
      query.state.data?.analysis_running ||
      query.state.data?.investigation_status === "running"
        ? ANALYSIS_POLL_MS
        : false,
  });

  // Watch the polled lifecycle while the latch is armed.
  const lastSettledStatus = useRef<string | null>(null);
  useEffect(() => {
    if (!runPending) return;
    const status = system.data?.analysis_status ?? null;
    if (status === "ANALYZING") {
      lastSettledStatus.current = null;
      return;
    }
    if (status === "READY" || status === "ERROR") {
      if (lastSettledStatus.current === status) return;
      lastSettledStatus.current = status;
      setRunPending(false);
      void queryClient.invalidateQueries();
      if (status === "READY") {
        pushToast({
          tone: "ok",
          title: "Analysis complete",
          body: "Results are ready across Analytics, Signals, and Insights.",
        });
      } else {
        pushToast({
          tone: "danger",
          title: "Analysis failed",
          body:
            system.data?.analysis_error ??
            "The pipeline could not complete this run.",
        });
      }
    }
  }, [runPending, system.data, pushToast, queryClient]);

  const artifacts = useQuery({
    queryKey: ["artifacts"],
    queryFn: () =>
      api<{ artifacts: ArtifactsPayload }>("/api/analysis/artifacts").then(
        (r) => r.artifacts,
      ),
    enabled: system.data?.artifacts_ready === true,
    staleTime: Infinity,
  });

  const investigation = useQuery({
    queryKey: ["investigation"],
    queryFn: () =>
      api<{
        investigation_status: string;
        investigation_error: string | null;
        result: InvestigationResult | null;
      }>("/api/investigation/status"),
    enabled: investigationArmed || system.data?.ai_available === true,
    refetchInterval: investigationArmed ? INVESTIGATION_POLL_MS : false,
  });

  // Toast on investigation completion — exactly once per run.
  const lastInvestigationStatus = useRef<string>("idle");
  useEffect(() => {
    const current = investigation.data?.investigation_status;
    if (!current || current === lastInvestigationStatus.current) return;
    const previous = lastInvestigationStatus.current;
    lastInvestigationStatus.current = current;
    if (previous !== "running") return;
    if (current === "complete") {
      pushToast({
        tone: "ok",
        title: "AI investigation complete",
        body: "Grounded results are available in the Evidence workspace.",
      });
      setInvestigationArmed(false);
      void queryClient.invalidateQueries({ queryKey: ["system"] });
    } else if (current === "error") {
      pushToast({
        tone: "warn",
        title: "AI investigation unavailable",
        body: "Deterministic evidence remains fully available.",
      });
      setInvestigationArmed(false);
    }
  }, [investigation.data, pushToast, queryClient]);

  const loadDemo = useMutation({
    mutationFn: (filename: string) =>
      api("/api/datasets/load-demo", {
        method: "POST",
        json: { filename },
      }),
    onMutate: () => {
      setLoadingStage("loading");
    },
    onSuccess: () => {
      setLoadingStage(null);
      void queryClient.invalidateQueries();
      void queryClient.invalidateQueries({ queryKey: ["system"] });
      void queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      void queryClient.invalidateQueries({ queryKey: ["dataset-preview"] });
      pushToast({ tone: "ok", title: "Dataset loaded" });
    },
    onError: (error: Error) => {
      setLoadingStage(null);
      pushToast({ tone: "danger", title: "Load failed", body: error.message });
    },
  }).mutateAsync;

  const uploadDataset = useMutation({
    mutationFn: (file: File) =>
      apiUpload<{ dataset: { name: string; rows: number } }>(
        "/api/datasets/upload",
        file,
      ),
    onMutate: () => {
      setLoadingStage("uploading");
    },
    onSuccess: (body) => {
      setLoadingStage(null);
      void queryClient.invalidateQueries();
      void queryClient.invalidateQueries({ queryKey: ["system"] });
      void queryClient.invalidateQueries({ queryKey: ["artifacts"] });
      void queryClient.invalidateQueries({ queryKey: ["dataset-preview"] });
      pushToast({
        tone: "ok",
        title: "Dataset uploaded",
        body: `${body.dataset.name} · ${body.dataset.rows} rows`,
      });
    },
    onError: (error: Error) => {
      setLoadingStage(null);
      pushToast({ tone: "danger", title: "Upload failed", body: error.message });
    },
  }).mutateAsync;

  const runAnalysis = useMutation({
    mutationFn: ({ sensitivity }: { sensitivity: string }) =>
      api("/api/analysis/run", {
        method: "POST",
        json: { sensitivity, wait: false },
      }),
    onMutate: () => {
      // Arm the latch immediately: the button state and polling must not
      // depend on catching the transient ANALYZING window in a poll.
      lastSettledStatus.current = null;
      setRunPending(true);
      void queryClient.invalidateQueries({ queryKey: ["system"] });
    },
    onSuccess: () => {
      pushToast({ tone: "info", title: "Analysis started" });
    },
    onError: (error: Error) => {
      setRunPending(false);
      pushToast({ tone: "danger", title: "Run failed", body: error.message });
    },
  }).mutateAsync;

  const startInvestigation = useCallback(async () => {
    setInvestigationArmed(true);
    await api("/api/investigation/run", { method: "POST" });
    void queryClient.invalidateQueries({ queryKey: ["investigation"] });
  }, [queryClient]);

  async function ensurePlan(maxRecommendations?: number): Promise<PlanPayload> {
    return api<PlanPayload>("/api/plan/generate", {
      method: "POST",
      json: { max_recommendations: maxRecommendations ?? null },
    });
  }

  const value = useMemo<WorkspaceValue>(
    () => ({
      system: system.data,
      artifacts: artifacts.data,
      toasts,
      pushToast,
      dismissToast,
      runPending,
      loadDemo: async (filename: string) => {
        await loadDemo(filename);
      },
      uploadDataset: async (file: File) => {
        await uploadDataset(file);
      },
      runAnalysis: async (sensitivity) => {
        await runAnalysis({ sensitivity });
      },
      startInvestigation,
      investigation: {
        status: investigation.data?.investigation_status ?? "idle",
        error: investigation.data?.investigation_error ?? null,
        result: investigation.data?.result ?? null,
      },
      ensurePlan,
      loadingStage,
    }),
    [
      system.data,
      artifacts.data,
      toasts,
      pushToast,
      dismissToast,
      runPending,
      loadDemo,
      uploadDataset,
      runAnalysis,
      startInvestigation,
      investigation.data,
      loadingStage,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace requires WorkspaceProvider");
  return value;
}
