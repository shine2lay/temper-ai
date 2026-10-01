import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  /** What broke, in the user's words: "the run's picture", "the live panel". */
  label?: string;
  /**
   * Change this and the box clears itself. Pass the run id: a crash belongs
   * to the run that caused it, and the next one starts clean.
   */
  resetKey?: unknown;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * React error boundary that catches render errors in child components.
 * Displays a fallback UI instead of crashing the entire app.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary]', this.props.label ?? '', error, errorInfo);
  }

  componentDidUpdate(prev: ErrorBoundaryProps): void {
    if (this.state.hasError && prev.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, error: null });
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      // Small, and only over the part that broke: the rest of the run page
      // keeps working, which is the whole point of having several of these.
      return (
        <div
          role="alert"
          className="m-3 max-w-md rounded border border-temper-failed/40 bg-temper-panel/90 p-3 text-left"
        >
          <p className="text-sm font-medium text-temper-failed">
            {this.props.label ? `${this.props.label} stopped drawing` : 'Something went wrong'}
          </p>
          <p className="mt-1 text-xs text-temper-text-muted break-words">
            {this.state.error?.message ?? 'Unknown error'} — the rest of the page still works.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-3 py-1.5 rounded text-xs bg-temper-surface text-temper-text hover:bg-temper-panel-light transition-colors"
            >
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-3 py-1.5 rounded text-xs bg-temper-surface text-temper-text hover:bg-temper-panel-light transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
