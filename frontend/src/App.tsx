import { Suspense, lazy, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { WorkspaceProvider } from "./state/workspace";
import { Sidebar } from "./components/shell/Sidebar";
import { Topbar } from "./components/shell/Topbar";
import { Toaster } from "./components/shell/Toaster";
import {
  CommandPalette,
  useCommandPalette,
} from "./components/shell/CommandPalette";
import Overview from "./pages/Overview";
import DataPage from "./pages/DataPage";
import Anomalies from "./pages/Anomalies";
import Insights from "./pages/Insights";
import Evidence from "./pages/Evidence";
import Review from "./pages/Review";

/** Chart-heavy routes are split so ECharts only loads when visited. */
const Analytics = lazy(() => import("./pages/Analytics"));
const Explorer = lazy(() => import("./pages/Explorer"));
const Recommendations = lazy(() => import("./pages/Recommendations"));
const History = lazy(() => import("./pages/History"));

function RouteFallback() {
  return (
    <div className="flex items-center gap-2 py-16 text-sm text-text-2">
      <span className="skeleton h-4 w-4 rounded-full" aria-hidden />
      Loading workspace…
    </div>
  );
}

export default function App() {
  const [navOpen, setNavOpen] = useState(false);
  const palette = useCommandPalette();
  const location = useLocation();

  return (
    <MotionConfig reducedMotion="user">
      <WorkspaceProvider>
      <div className="flex min-h-screen">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[90] focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
        >
          Skip to content
        </a>
        <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar
            onMenu={() => setNavOpen(true)}
            onPalette={() => palette.setOpen(true)}
          />
          <main id="main" className="min-w-0 flex-1 px-4 py-6 lg:px-8">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
                className="mx-auto max-w-[1440px]"
              >
                <Routes location={location}>
                  <Route path="/" element={<Overview />} />
                  <Route path="/data" element={<DataPage />} />
                  <Route
                    path="/explorer"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <Explorer />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/analytics"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <Analytics />
                      </Suspense>
                    }
                  />
                  <Route path="/anomalies" element={<Anomalies />} />
                  <Route path="/insights" element={<Insights />} />
                  <Route path="/evidence" element={<Evidence />} />
                  <Route
                    path="/recommendations"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <Recommendations />
                      </Suspense>
                    }
                  />
                  <Route path="/review" element={<Review />} />
                  <Route
                    path="/history"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <History />
                      </Suspense>
                    }
                  />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
        <Toaster />
        <CommandPalette open={palette.open} onOpenChange={palette.setOpen} />
      </div>
      </WorkspaceProvider>
    </MotionConfig>
  );
}
