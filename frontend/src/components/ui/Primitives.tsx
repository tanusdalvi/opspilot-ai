import type { ReactNode } from "react";
import {
  AlertTriangle,
  CircleAlert,
  Info,
  Check,
  Minus,
} from "lucide-react";
import type { Tone } from "../../lib/severity";
import { Panel } from "./Panel";

const TONE_CLASSES: Record<Tone, string> = {
  danger: "border-danger/35 bg-danger/10 text-danger",
  warn: "border-warn/35 bg-warn/10 text-warn",
  info: "border-accent/35 bg-accent/10 text-[#9db9ff]",
  ok: "border-ok/35 bg-ok/10 text-ok",
  muted: "border-line-strong bg-white/5 text-text-2",
};

const TONE_ICONS: Record<Tone, ReactNode> = {
  danger: <CircleAlert size={11} aria-hidden />,
  warn: <AlertTriangle size={11} aria-hidden />,
  info: <Info size={11} aria-hidden />,
  ok: <Check size={11} aria-hidden />,
  muted: <Minus size={11} aria-hidden />,
};

export function Badge({
  children,
  tone = "muted",
  withIcon = true,
}: {
  children: ReactNode;
  tone?: Tone;
  withIcon?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-[3px] text-[11px] font-semibold uppercase tracking-wider ${TONE_CLASSES[tone]}`}
    >
      {withIcon && TONE_ICONS[tone]}
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled = false,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger" | "subtle";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const variants = {
    primary:
      "bg-gradient-to-b from-accent to-[#4a76e6] text-white shadow-lg shadow-accent/25 hover:brightness-110",
    ghost:
      "border border-line-strong bg-transparent text-text-2 hover:text-text hover:border-accent/50",
    subtle:
      "bg-white/[0.06] border border-line text-text hover:bg-white/[0.09]",
    danger:
      "bg-danger/15 border border-danger/40 text-danger hover:bg-danger/25",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong bg-white/[0.02] px-8 py-14 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-line bg-white/[0.04] text-accent">
        {icon}
      </div>
      <h3 className="text-sm font-semibold uppercase tracking-wider text-text">
        {title}
      </h3>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-text-2">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function SkeletonPanel({ lines = 3 }: { lines?: number }) {
  return (
    <Panel className="p-5">
      <Skeleton className="h-3 w-28" />
      <div className="mt-4 space-y-3">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={`h-3 ${i % 2 ? "w-4/5" : "w-full"}`} />
        ))}
      </div>
    </Panel>
  );
}

export function StrengthMeter({
  value,
  maximum = 10,
  label,
}: {
  value: number;
  maximum?: number;
  label?: string;
}) {
  const segments = 13;
  const filled = Math.max(
    0,
    Math.min(segments, Math.round((value / maximum) * segments)),
  );
  const tone =
    filled / segments > 0.66
      ? "bg-ok"
      : filled / segments > 0.33
        ? "bg-warn"
        : "bg-danger";
  return (
    <div aria-label={label ?? `Strength ${value} of ${maximum}`}>
      <div className="flex gap-[3px]" role="presentation">
        {Array.from({ length: segments }).map((_, i) => (
          <span
            key={i}
            className={`h-2 w-full rounded-[2px] ${
              i < filled ? tone : "bg-white/[0.07]"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
