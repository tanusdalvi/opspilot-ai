/** Interactive UI controls: tabs, segmented control, accordion, confirm dialog. */

import { type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { Button } from "./Primitives";

// --- Tabs ---------------------------------------------------------------------------------------------

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

export function Tabs({
  items,
  active,
  onChange,
  ariaLabel,
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="flex flex-wrap gap-1 border-b border-line"
    >
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={`relative px-3.5 py-2.5 text-[13px] font-medium transition-colors ${
              selected ? "text-text" : "text-text-2 hover:text-text"
            }`}
          >
            <span className="flex items-center gap-1.5">
              {item.label}
              {item.count !== undefined && (
                <span className="num text-[11px] text-text-muted">
                  {item.count}
                </span>
              )}
            </span>
            {selected && (
              <motion.span
                layoutId={`tab-underline-${ariaLabel}`}
                className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

// --- Segmented control -----------------------------------------------------------------------------------

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex overflow-hidden rounded-lg border border-line-strong"
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={`px-3 py-1.5 text-xs font-semibold transition ${
              selected
                ? "bg-accent/15 text-text"
                : "text-text-muted hover:text-text-2"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

// --- Accordion -------------------------------------------------------------------------------------------

export function Accordion({
  title,
  meta,
  badge,
  open,
  onToggle,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode;
  badge?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface-2/40">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-faint"
      >
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="text-text-muted"
        >
          <ChevronDown size={16} aria-hidden />
        </motion.span>
        <span className="min-w-0 flex-1">{title}</span>
        {meta && <span className="hidden shrink-0 sm:block">{meta}</span>}
        {badge}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="border-t border-line px-4 py-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// --- Confirm dialog ---------------------------------------------------------------------------------------

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  tone = "primary",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  tone?: "primary" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-[60] bg-scrim backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onCancel}
          />
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-label={title}
            className="fixed left-1/2 top-1/2 z-[61] w-[min(420px,92vw)] -translate-x-1/2 -translate-y-1/2"
            initial={{ opacity: 0, scale: 0.94, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="panel p-5">
              <h3 className="text-sm font-bold uppercase tracking-wider text-text">
                {title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-text-2">{body}</p>
              <div className="mt-5 flex justify-end gap-2">
                <Button variant="ghost" onClick={onCancel}>
                  Cancel
                </Button>
                <Button
                  variant={tone === "danger" ? "danger" : "primary"}
                  onClick={onConfirm}
                >
                  {confirmLabel}
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
