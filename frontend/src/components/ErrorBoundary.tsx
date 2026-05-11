import { Component, ErrorInfo, ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render errors in the wrapped subtree so a single broken page (a
 * malformed visualization config, an unhandled exception inside a chart
 * component, etc.) shows a recoverable error screen instead of unmounting the
 * entire app to a blank document.
 *
 * Class component is the only way React supports `componentDidCatch`. Place
 * one near the route boundary; nested boundaries can wrap risky widgets that
 * shouldn't take their parent route down with them.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught error:", error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="min-h-screen flex items-center justify-center px-6">
          <div className="max-w-md text-center space-y-4">
            <h1 className="text-2xl font-semibold">Something went wrong</h1>
            <p className="text-sm text-muted-foreground">
              The page hit an unexpected error. You can try again, or reload the
              app if the problem persists.
            </p>
            <pre className="text-xs text-muted-foreground bg-muted/50 rounded px-3 py-2 overflow-x-auto text-left">
              {this.state.error.message}
            </pre>
            <div className="flex gap-2 justify-center">
              <Button onClick={this.reset} variant="outline">Try again</Button>
              <Button onClick={() => window.location.reload()}>Reload app</Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
