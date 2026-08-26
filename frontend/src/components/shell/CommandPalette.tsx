import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import {
  Activity,
  Archive,
  BarChart3,
  CheckCircle2,
  Compass,
  Database,
  Eye,
  FileSearch,
  Lightbulb,
  Monitor,
  Moon,
  Play,
  Sparkles,
  Sun,
  Upload,
} from "lucide-react";
import { useWorkspace } from "../../state/workspace";
import { useTheme, type ThemePreference } from "../../state/theme";

interface CommandItem {
  id: string;
  group: string;
  label: string;
  icon: typeof Eye;
  keywords?: string;
  run: () => void;
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { system, artifacts, runAnalysis, loadDemo, startInvestigation } =
    useWorkspace();
  const { setPreference } = useTheme();
  const inputRef = useRef<HTMLInputElement>(null);

  const themeCommands: CommandItem[] = (
    [
      { value: "light", label: "Set Light Theme", icon: Sun },
      { value: "dark", label: "Set Dark Theme", icon: Moon },
      { value: "system", label: "Follow System Theme", icon: Monitor },
    ] as { value: ThemePreference; label: string; icon: typeof Eye }[]
  ).map(({ value, label, icon }) => ({
    id: `theme-${value}`,
    group: "Theme",
    label,
    icon,
    keywords: "appearance color mode",
    run: () => setPreference(value),
  }));

  const commands: CommandItem[] = [
    ...themeCommands,
    ...[
      { path: "/", label: "Open Overview", icon: Eye },
      { path: "/data", label: "Open Data", icon: Database },
      { path: "/explorer", label: "Open Data Explorer", icon: Compass },
      { path: "/analytics", label: "Open Analytics", icon: BarChart3 },
      { path: "/anomalies", label: "Open Anomalies", icon: Activity },
      { path: "/insights", label: "Open Insights", icon: Lightbulb },
      { path: "/evidence", label: "Open Evidence", icon: FileSearch },
      { path: "/recommendations", label: "Open Recommendations", icon: Sparkles },
      { path: "/review", label: "Open Human Review", icon: CheckCircle2 },
      { path: "/history", label: "Open History", icon: Archive },
    ].map(({ path, label, icon }) => ({
      id: `nav-${path}`,
      group: "Navigation",
      label,
      icon,
      run: () => navigate(path),
    })),
    ...(system?.artifacts_ready
      ? [
          {
            id: "action-rerun",
            group: "Actions",
            label: "Run / Refresh Analysis",
            icon: Play,
            keywords: "execute pipeline",
            run: () => {
              const sensitivity =
                String(artifacts?.pack?.parameters?.sensitivity ?? "medium");
              void runAnalysis(sensitivity).then(() => navigate("/analytics"));
            },
          },
        ]
      : []),
    ...(!system?.artifacts_ready && system?.dataset
      ? [
          {
            id: "action-run-first",
            group: "Actions",
            label: "Run Analysis",
            icon: Play,
            keywords: "execute pipeline",
            run: () => {
              void runAnalysis("medium").then(() => navigate("/analytics"));
            },
          },
        ]
      : []),
    ...(system?.dataset
      ? [
          {
            id: "action-open-data",
            group: "Actions",
            label: `Inspect dataset ${system.dataset.name}`,
            icon: Database,
            keywords: "dataset identity validation",
            run: () => navigate("/data"),
          },
        ]
      : []),
    {
      id: "action-load-demo",
      group: "Actions",
      label: "Load demo dataset",
      icon: Database,
      keywords: "sample operational data csv",
      run: () => {
        void loadDemo("demo_operational_data.csv").then(() => navigate("/data"));
      },
    },
    {
      id: "action-upload",
      group: "Actions",
      label: "Upload dataset",
      icon: Upload,
      keywords: "csv import file drag drop",
      run: () => navigate("/data"),
    },
    ...(system?.ai_available && system?.artifacts_ready
      ? [
          {
            id: "action-investigate",
            group: "Actions",
            label: "Run AI investigation",
            icon: Sparkles,
            keywords: "ai narrative grounded findings",
            run: () => {
              void startInvestigation().then(() => navigate("/evidence"));
            },
          },
        ]
      : []),
  ];

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 20);
  }, [open]);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      loop
      className="fixed inset-0 z-[70]"
      overlayClassName="fixed inset-0 bg-scrim backdrop-blur-[2px]"
      contentClassName="mx-auto mt-[14vh] w-[min(92vw,560px)] overflow-hidden rounded-xl border border-line-strong bg-bg-soft shadow-2xl shadow-black/60"
      shouldFilter
      aria-label="Command palette"
    >
      <Command.Input
        ref={inputRef}
        placeholder="Type a command or search…"
        className="w-full border-b border-line bg-transparent px-5 py-4 text-sm text-text outline-none placeholder:text-text-muted"
      />
      <Command.List className="max-h-[52vh] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-text-muted">
          No matching commands.
        </Command.Empty>
        {["Navigation", "Actions", "Theme"].map((group) => (
          <Command.Group
            key={group}
            heading={group}
            className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-bold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.18em] [&_[cmdk-group-heading]]:text-text-muted"
          >
            {commands
              .filter((c) => c.group === group)
              .map((command) => (
                <Command.Item
                  key={command.id}
                  value={`${command.label} ${command.keywords ?? ""}`}
                  onSelect={() => {
                    command.run();
                    onOpenChange(false);
                  }}
                  className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-text-2 data-[selected=true]:bg-accent/[0.12] data-[selected=true]:text-text"
                >
                  <command.icon size={15} aria-hidden />
                  {command.label}
                </Command.Item>
              ))}
          </Command.Group>
        ))}
      </Command.List>
      <div className="flex items-center justify-between border-t border-line px-4 py-2 text-[10px] uppercase tracking-wider text-text-muted">
        <span>OpsPilot Command</span>
        <span className="kbd">esc close</span>
      </div>
    </Command.Dialog>
  );
}

/** Global Ctrl/Cmd+K binding. */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  return { open, setOpen };
}
