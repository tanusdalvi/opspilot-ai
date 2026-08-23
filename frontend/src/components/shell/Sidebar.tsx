import { NavLink, useLocation } from "react-router-dom";
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
  Sparkles,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useWorkspace } from "../../state/workspace";
import { Badge } from "../ui/Primitives";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Eye;
}

const GROUPS: { name: string; items: NavItem[] }[] = [
  {
    name: "Command Center",
    items: [{ to: "/", label: "Overview", icon: Eye }],
  },
  {
    name: "Data",
    items: [
      { to: "/data", label: "Data", icon: Database },
      { to: "/explorer", label: "Data Explorer", icon: Compass },
    ],
  },
  {
    name: "Intelligence",
    items: [
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
      { to: "/anomalies", label: "Anomalies", icon: Activity },
      { to: "/insights", label: "Insights", icon: Lightbulb },
      { to: "/evidence", label: "Evidence", icon: FileSearch },
    ],
  },
  {
    name: "Decision",
    items: [
      { to: "/recommendations", label: "Recommendations", icon: Sparkles },
      { to: "/review", label: "Human Review", icon: CheckCircle2 },
    ],
  },
  {
    name: "Audit",
    items: [{ to: "/history", label: "History", icon: Archive }],
  },
];

export function Sidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { system } = useWorkspace();
  const location = useLocation();

  const content = (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-5 pt-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-2 text-[13px] font-extrabold text-white shadow-lg shadow-accent/30">
            OP
          </div>
          <div>
            <p className="text-sm font-bold tracking-tight text-text">
              OpsPilot AI
            </p>
            <p className="text-[10px] uppercase tracking-[0.18em] text-text-muted">
              Operations Intelligence
            </p>
          </div>
        </div>
      </div>

      <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3">
        {GROUPS.map((group) => (
          <div key={group.name} className="mb-4">
            <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-text-muted/80">
              {group.name}
            </p>
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
                  className={`relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors duration-150 ${
                    active
                      ? "text-text"
                      : "text-text-2 hover:bg-white/[0.04] hover:text-text"
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
                    className={`relative z-10 ${active ? "text-accent" : ""}`}
                    aria-hidden
                  />
                  <span className="relative z-10">{label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-5 py-4 text-xs">
        <div className="space-y-1.5 text-text-muted">
          <p className="flex items-center justify-between">
            Dataset
            <span className="max-w-[120px] truncate font-medium text-text-2">
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
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop rail */}
      <aside className="hidden w-60 shrink-0 border-r border-line bg-bg-soft/70 backdrop-blur-md lg:block">
        <div className="sticky top-0 h-screen">{content}</div>
      </aside>
      {/* Mobile drawer */}
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/55 lg:hidden"
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
