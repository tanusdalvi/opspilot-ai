import { Menu, Monitor, Moon, Search, Sun } from "lucide-react";
import { useWorkspace } from "../../state/workspace";
import { useTheme, type ThemePreference } from "../../state/theme";
import { Badge } from "../ui/Primitives";

const TITLES: [RegExp, string, string][] = [
  [/^\/$/, "Command Center", "Operational overview"],
  [/^\/data/, "Data", "Dataset workspace"],
  [/^\/explorer/, "Data Explorer", "Visual dataset exploration"],
  [/^\/analytics/, "Analytics", "Analytical workspace"],
  [/^\/anomalies/, "Anomalies", "Signal wall"],
  [/^\/insights/, "Insights", "Interpreted signals"],
  [/^\/evidence/, "Evidence", "Investigation workspace"],
  [/^\/recommendations/, "Recommendations", "Actionable decisions"],
  [/^\/review/, "Human Review", "Decision console"],
  [/^\/history/, "History", "Audit timeline"],
];

export function Topbar({
  onMenu,
  onPalette,
}: {
  onMenu: () => void;
  onPalette: () => void;
}) {
  const { system } = useWorkspace();
  const match = TITLES.find(([pattern]) => pattern.test(window.location.pathname));
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

      <div className="ml-auto flex items-center gap-2">
        {system?.analysis_running && (
          <Badge tone="info" withIcon={false}>
            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            Analyzing
          </Badge>
        )}
        <Badge tone={system?.ai_available ? "ok" : "muted"} withIcon={false}>
          AI {system?.ai_available ? "Ready" : "Offline"}
        </Badge>
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
      className="hidden overflow-hidden rounded-lg border border-line md:flex"
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
