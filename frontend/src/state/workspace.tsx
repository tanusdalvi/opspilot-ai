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
  startInvestigation: () => Promise<void>;
  investigation: {
    status: string;
    error: string | null;
    result: InvestigationResult | null;
  };
  ensurePlan: (maxRecommendations?: number) => Promise<PlanPayload>;
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

  const system = useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemPayload>("/api/system"),
    refetchInterval: (query) =>
      query.state.data?.analysis_running ||
      query.state.data?.investigation_status === "running"
        ? ANALYSIS_POLL_MS
        : false,
  });

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
    onSuccess: () => {
      void queryClient.invalidateQueries();
      pushToast({ tone: "ok", title: "Dataset loaded" });
    },
    onError: (error: Error) =>
      pushToast({ tone: "danger", title: "Load failed", body: error.message }),
  }).mutateAsync;

  const uploadDataset = useMutation({
    mutationFn: (file: File) =>
      apiUpload<{ dataset: { name: string; rows: number } }>(
        "/api/datasets/upload",
        file,
      ),
    onSuccess: (body) => {
      void queryClient.invalidateQueries();
      pushToast({
        tone: "ok",
        title: "Dataset uploaded",
        body: `${body.dataset.name} · ${body.dataset.rows} rows`,
      });
    },
    onError: (error: Error) =>
      pushToast({ tone: "danger", title: "Upload failed", body: error.message }),
  }).mutateAsync;

  const runAnalysis = useMutation({
    mutationFn: ({ sensitivity }: { sensitivity: string }) =>
      api("/api/analysis/run", {
        method: "POST",
        json: { sensitivity, wait: false },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      pushToast({ tone: "info", title: "Analysis started" });
    },
    onError: (error: Error) =>
      pushToast({ tone: "danger", title: "Run failed", body: error.message }),
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
    }),
    [
      system.data,
      artifacts.data,
      toasts,
      pushToast,
      dismissToast,
      loadDemo,
      uploadDataset,
      runAnalysis,
      startInvestigation,
      investigation.data,
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
