import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useWorkspace } from "../../state/workspace";
import type { Toast } from "../../state/workspace";

const ICONS = {
  ok: <CheckCircle2 size={15} className="text-ok" aria-hidden />,
  info: <Info size={15} className="text-accent" aria-hidden />,
  warn: <AlertTriangle size={15} className="text-warn" aria-hidden />,
  danger: <AlertTriangle size={15} className="text-danger" aria-hidden />,
};

export function Toaster() {
  const { toasts, dismissToast } = useWorkspace();
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-5 right-5 z-[80] flex w-[min(92vw,360px)] flex-col gap-2"
    >
      <AnimatePresence>
        {toasts.map((toast: Toast) => (
          <motion.div
            key={toast.id}
            layout
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, x: 40 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="panel pointer-events-auto flex items-start gap-3 p-3.5"
            role="status"
          >
            <span className="mt-0.5">{ICONS[toast.tone]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-text">{toast.title}</p>
              {toast.body && (
                <p className="mt-0.5 text-xs leading-relaxed text-text-2">
                  {toast.body}
                </p>
              )}
            </div>
            <button
              onClick={() => dismissToast(toast.id)}
              aria-label="Dismiss notification"
              className="text-text-muted transition hover:text-text"
            >
              <X size={14} />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
