import type { ReactNode } from "react";
import { motion } from "framer-motion";

export function Panel({
  children,
  className = "",
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}) {
  return (
    <div className={`panel ${hover ? "panel-hover" : ""} ${className}`}>
      {children}
    </div>
  );
}

export function SectionHeading({
  icon,
  title,
  caption,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  caption?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-wide text-text">
          {icon}
          {title}
        </h2>
        {caption && <p className="mt-1 text-xs text-text-muted">{caption}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="mb-6"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent">
        {eyebrow}
      </p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight text-text">
        {title}
      </h1>
      {description && (
        <p className="mt-2 max-w-2xl text-sm text-text-2">{description}</p>
      )}
    </motion.header>
  );
}
