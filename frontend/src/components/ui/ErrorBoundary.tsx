import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";
import { Panel } from "./Panel";
import { Button } from "./Primitives";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackBody?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[ErrorBoundary] Caught rendering error:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <Panel className="p-6">
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-danger/30 bg-danger/10 text-danger">
              <AlertTriangle size={20} aria-hidden />
            </div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-text">
              {this.props.fallbackTitle ?? "Something went wrong"}
            </h3>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-text-2">
              {this.props.fallbackBody ??
                "The evidence could not be rendered. This may indicate malformed data. You can retry or navigate to another page."}
            </p>
            {this.state.error && (
              <p className="mt-2 max-w-lg break-all text-[11px] text-text-muted">
                {this.state.error.message}
              </p>
            )}
            <Button variant="ghost" className="mt-4" onClick={this.handleRetry}>
              <RefreshCcw size={14} aria-hidden />
              Retry
            </Button>
          </div>
        </Panel>
      );
    }

    return this.props.children;
  }
}
