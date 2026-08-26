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
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import Overview from "./pages/Overview";
import DataPage from "./pages/DataPage";
import Evidence from "./pages/Evidence";
import Review from "./pages/Review";
import ActionCenter from "./pages/ActionCenter";

/** Heavy chart/analysis routes are lazy-loaded. */
const Analytics = lazy(() => import("./pages/Analytics"));
const Explorer = lazy(() => import("./pages/Explorer"));
const Recommendations = lazy(() => import("./pages/Recommendations"));
const Anomalies = lazy(() => import("./pages/Anomalies"));
const History = lazy(() => import("./pages/History"));

function RouteFallback() {
  return (
    <div className="flex items-center gap-2 py-16 text-sm text-text-2">
      <span className="skeleton h-4 w-4 rounded-full" aria-hidden />
      Loading workspace…
    </div>
  );
}

/** Wraps a page component in an ErrorBoundary with a page-specific fallback. */
function PageBoundary({
  name,
  children,
}: {
  name: string;
  children: React.ReactNode;
}) {
  return (
    <ErrorBoundary
      fallbackTitle={`${name} could not load`}
      fallbackBody={`An error occurred while rendering the ${name} page. You can retry or navigate to another page.`}
    >
      {children}
    </ErrorBoundary>
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
                  <Route
                    path="/"
                    element={
                      <PageBoundary name="Overview">
                        <Overview />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/action-center"
                    element={
                      <PageBoundary name="Action Center">
                        <ActionCenter />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/data"
                    element={
                      <PageBoundary name="Data">
                        <DataPage />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/explorer"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <PageBoundary name="Explorer">
                          <Explorer />
                        </PageBoundary>
                      </Suspense>
                    }
                  />
                  <Route
                    path="/analytics"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <PageBoundary name="Analytics">
                          <Analytics />
                        </PageBoundary>
                      </Suspense>
                    }
                  />
                  <Route
                    path="/anomalies"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <PageBoundary name="Findings & Signals">
                          <Anomalies />
                        </PageBoundary>
                      </Suspense>
                    }
                  />
                  <Route
                    path="/insights"
                    element={<Navigate to="/anomalies" replace />}
                  />
                  <Route
                    path="/evidence"
                    element={
                      <PageBoundary name="Evidence">
                        <Evidence />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/recommendations"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <PageBoundary name="Recommendations">
                          <Recommendations />
                        </PageBoundary>
                      </Suspense>
                    }
                  />
                  <Route
                    path="/review/:recommendationId"
                    element={
                      <PageBoundary name="Review">
                        <Review />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/review"
                    element={
                      <PageBoundary name="Review">
                        <Review />
                      </PageBoundary>
                    }
                  />
                  <Route
                    path="/history"
                    element={
                      <Suspense fallback={<RouteFallback />}>
                        <PageBoundary name="History">
                          <History />
                        </PageBoundary>
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
