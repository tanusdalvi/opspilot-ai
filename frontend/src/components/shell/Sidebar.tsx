import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  Archive,
  BarChart3,
  Brain,
  CheckCircle2,
  ChevronLeft,
  ClipboardList,
  Compass,
  Database,
  Eye,
  FileSearch,
  PanelLeftClose,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useWorkspace } from "../../state/workspace";
import { Badge } from "../ui/Primitives";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Eye;
}

/** Grouped per the product journey: Command Center → Intelligence → Investigate → Data → Governance. */
const GROUPS: { name: string; items: NavItem[] }[] = [
  {
    name: "Command Center",
    items: [
      { to: "/", label: "Overview", icon: Eye },
      { to: "/action-center", label: "Action Center", icon: ClipboardList },
    ],
  },
  {
    name: "Intelligence",
    items: [
      { to: "/investigate", label: "Investigate", icon: Brain },
      { to: "/anomalies", label: "Findings", icon: Activity },
      { to: "/evidence", label: "Evidence", icon: FileSearch },
    ],
  },
  {
    name: "Data",
    items: [
      { to: "/data", label: "Data Workspace", icon: Database },
      { to: "/explorer", label: "Explorer", icon: Compass },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    name: "Decide & Act",
    items: [
      { to: "/recommendations", label: "Recommendations", icon: Sparkles },
      { to: "/review", label: "Review Decisions", icon: CheckCircle2 },
    ],
  },
  {
    name: "Governance",
    items: [
      { to: "/history", label: "History", icon: Archive },
    ],
  },
];

const COLLAPSE_KEY = "opspilot.sidebar.collapsed";

export function Sidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { system } = useWorkspace();
  const location = useLocation();
  // Collapse applies to the desktop rail only; the mobile drawer is always full.
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  });

  useEffect(() => {
    window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  const content = (
    <div className="flex h-full flex-col">
      <div
        className={`flex items-center gap-2.5 pb-5 pt-6 ${
          collapsed ? "justify-center px-2" : "px-5"
        }`}
      >
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-2 text-[13px] font-extrabold text-white shadow-lg shadow-accent/30"
          aria-hidden
        >
          OP
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-bold tracking-tight text-text">
              OpsPilot AI
            </p>
            <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
              Operations Intelligence
            </p>
          </div>
        )}
      </div>

      <nav
        aria-label="Primary"
        className={`flex-1 px-3 ${
          // Collapsed rails don't clip — flyout labels must be able to escape.
          collapsed ? "overflow-visible" : "overflow-y-auto"
        }`}
      >
        {GROUPS.map((group) => (
          <div key={group.name} className="mb-4">
            {!collapsed && (
              <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-text-muted/80">
                {group.name}
              </p>
            )}
            {collapsed && <div className="mx-auto mb-1.5 h-px w-6 bg-line" aria-hidden />}
            {group.items.map(({ to, label, icon: Icon }) => {
              const active =
                to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(to);
              return (
                <NavLink
                  key={to}
                  to={to}
                  onClick={onClose}
                  aria-current={active ? "page" : undefined}
                  title={collapsed ? label : undefined}
                  className={`group/nav-item relative flex items-center gap-2.5 rounded-lg py-2 text-[13px] font-medium transition-colors duration-150 ${
                    collapsed ? "justify-center px-0" : "px-2.5"
                  } ${
                    active
                      ? "text-text"
                      : "text-text-2 hover:bg-hover hover:text-text"
                  }`}
                >
                  {active && (
                    <motion.span
                      layoutId="nav-active"
                      className="absolute inset-0 rounded-lg border border-accent/25 bg-accent/[0.12]"
                      transition={{ type: "spring", stiffness: 500, damping: 40 }}
                    />
                  )}
                  <Icon
                    size={15}
                    className={`relative z-10 shrink-0 ${active ? "text-accent" : ""}`}
                    aria-hidden
                  />
                  {!collapsed && (
                    <span className="relative z-10 truncate">{label}</span>
                  )}
                  {/* Flyout label when the rail is collapsed */}
                  {collapsed && (
                    <span
                      role="tooltip"
                      className="pointer-events-none absolute left-full z-50 ml-3 whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-text opacity-0 shadow-xl transition-opacity duration-150 group-hover/nav-item:opacity-100"
                    >
                      {label}
                    </span>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div
        className={`border-t border-line py-4 text-xs ${
          collapsed ? "px-2" : "px-5"
        }`}
      >
        {collapsed ? (
          <div role="status" aria-label="System status" className="flex flex-col items-center gap-2">
            <span
              title={`Dataset: ${system?.dataset?.name ?? "none loaded"}`}
              className="flex h-7 w-7 items-center justify-center rounded-md border border-line bg-hover text-text-muted"
            >
              <Database size={13} aria-hidden />
            </span>
            <Badge tone={statusTone(system?.analysis_status)} withIcon={false}>
              {(system?.analysis_status ?? "…").slice(0, 4)}
            </Badge>
            <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
          </div>
        ) : (
          <>
            <div className="space-y-1.5 text-text-muted">
              <p className="flex items-center justify-between gap-2">
                Dataset
                <span
                  className="max-w-[120px] truncate font-medium text-text-2"
                  title={system?.dataset?.name}
                >
                  {system?.dataset?.name ?? "none"}
                </span>
              </p>
              <p className="flex items-center justify-between">
                Analysis
                <Badge tone={statusTone(system?.analysis_status)} withIcon={false}>
                  {system?.analysis_status ?? "…"}
                </Badge>
              </p>
              <p className="flex items-center justify-between">
                AI
                <Badge tone={system?.ai_available ? "ok" : "muted"} withIcon={false}>
                  {system?.ai_available ? "Ready" : "Offline"}
                </Badge>
              </p>
            </div>
            <CollapseToggle
              collapsed={collapsed}
              onToggle={() => setCollapsed((c) => !c)}
            />
          </>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop rail */}
      <aside
        className={`hidden shrink-0 border-r border-line bg-bg-soft/70 backdrop-blur-md transition-[width] duration-200 ease-out lg:block ${
          collapsed ? "w-[68px]" : "w-60"
        }`}
      >
        <div className="sticky top-0 h-screen">{content}</div>
      </aside>
      {/* Mobile drawer */}
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-scrim lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={onClose}
            />
            <motion.aside
              className="fixed inset-y-0 left-0 z-50 w-64 border-r border-line bg-bg-soft lg:hidden"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
              role="dialog"
              aria-label="Navigation"
            >
              {content}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

function CollapseToggle({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      className={`mt-3 flex items-center gap-2 rounded-lg border border-line py-1.5 text-text-muted transition hover:border-line-strong hover:text-text-2 ${
        collapsed ? "justify-center px-0" : "w-full justify-center px-2"
      }`}
    >
      {collapsed ? (
        <ChevronLeft size={14} className="rotate-180" aria-hidden />
      ) : (
        <>
          <PanelLeftClose size={14} aria-hidden />
          <span className="text-[11px] font-semibold">Collapse</span>
        </>
      )}
    </button>
  );
}

function statusTone(status?: string) {
  switch (status) {
    case "READY":
      return "ok";
    case "ANALYZING":
      return "info";
    case "ERROR":
      return "danger";
    default:
      return "muted";
  }
}
