import { Database, Menu, Monitor, Moon, Search, Sun } from "lucide-react";
import { useLocation } from "react-router-dom";
import { useWorkspace } from "../../state/workspace";
import { useTheme, type ThemePreference } from "../../state/theme";
import { Badge } from "../ui/Primitives";

const TITLES: [RegExp, string, string][] = [
  [/^\/$/, "Overview", "What needs your attention"],
  [/^\/data/, "Data Workspace", "Load and prepare datasets"],
  [/^\/explorer/, "Data Explorer", "Explore your dataset visually"],
  [/^\/analytics/, "Analytics", "Trends, comparisons, and drill-downs"],
  [/^\/anomalies/, "Findings & Signals", "Operational issues detected"],
  [/^\/insights/, "Insights", "Deep signal analysis"],
  [/^\/evidence/, "Evidence", "Supporting data and investigation"],
  [/^\/recommendations/, "Recommendations", "Suggested operational actions"],
  [/^\/review/, "Review Decisions", "Approve or reject recommendations"],
  [/^\/history/, "History", "Audit trail of all decisions"],
];

export function Topbar({
  onMenu,
  onPalette,
}: {
  onMenu: () => void;
  onPalette: () => void;
}) {
  const { system } = useWorkspace();
  const location = useLocation();
  const match = TITLES.find(([pattern]) => pattern.test(location.pathname));
  const [, title, caption] = match ?? ["", "OpsPilot AI", ""];

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md lg:px-6">
      <button
        onClick={onMenu}
        aria-label="Open navigation"
        className="rounded-lg border border-line p-2 text-text-2 transition hover:text-text lg:hidden"
      >
        <Menu size={16} />
      </button>

      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold text-text">{title}</h1>
        <p className="hidden text-[11px] text-text-muted sm:block">{caption}</p>
      </div>

      {/* Active dataset — always visible context for every number on screen */}
      {system?.dataset && (
        <div
          className="ml-2 hidden min-w-0 items-center gap-1.5 rounded-full border border-line bg-faint px-2.5 py-1 md:flex lg:ml-4"
          title={`Active dataset: ${system.dataset.name}`}
        >
          <Database size={11} className="shrink-0 text-accent" aria-hidden />
          <span className="max-w-[160px] truncate text-[11px] font-medium text-text-2">
            {system.dataset.name}
          </span>
        </div>
      )}

      <div className="ml-auto flex items-center gap-2">
        {system?.analysis_running && (
          <Badge tone="info" withIcon={false}>
            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            Analyzing
          </Badge>
        )}
        <span className="hidden sm:inline-flex">
          <Badge tone={system?.ai_available ? "ok" : "muted"} withIcon={false}>
            AI {system?.ai_available ? "Ready" : "Offline"}
          </Badge>
        </span>
        <ThemeSwitcher />
        <button
          onClick={onPalette}
          className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-xs text-text-muted transition hover:border-line-strong hover:text-text-2"
          aria-label="Open command palette (Ctrl+K)"
        >
          <Search size={13} />
          <span className="hidden sm:inline">Search…</span>
          <span className="kbd hidden sm:inline">Ctrl K</span>
        </button>
      </div>
    </header>
  );
}

const THEME_OPTIONS: {
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
}[] = [
  { value: "light", label: "Light theme", icon: Sun },
  { value: "dark", label: "Dark theme", icon: Moon },
  { value: "system", label: "Match system theme", icon: Monitor },
];

function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      className="flex overflow-hidden rounded-lg border border-line"
    >
      {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          role="radio"
          aria-checked={preference === value}
          aria-label={label}
          title={label}
          onClick={() => setPreference(value)}
          className={`p-2 transition ${
            preference === value
              ? "bg-accent/15 text-text"
              : "text-text-muted hover:text-text-2"
          }`}
        >
          <Icon size={14} aria-hidden />
        </button>
      ))}
    </div>
  );
}
