import { Component, type ReactNode, type ErrorInfo } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ExecutionView } from '@/pages/ExecutionView';
import { WorkflowList } from '@/pages/WorkflowList';
import ComparisonView from '@/pages/ComparisonView';
import { StudioView } from '@/pages/StudioView';
import { LibraryView } from '@/pages/LibraryView';
import { EditorView } from '@/pages/EditorView';
// Deferred pages (uncomment when backend endpoints are ready):
// import { LoginPage } from '@/pages/LoginPage';
// import { DocsPage } from '@/pages/DocsPage';
// import { AppLayout } from '@/components/layout/AppLayout';
import { Toaster } from '@/components/ui/sonner';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled render error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full bg-temper-bg text-temper-text gap-4 p-8">
          <h1 className="text-2xl font-semibold">Something went wrong</h1>
          <p className="text-temper-muted text-sm max-w-md text-center">
            {this.state.error?.message || 'An unexpected error occurred.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 bg-temper-accent text-white rounded hover:opacity-90 text-sm"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-full bg-temper-bg text-temper-text gap-4">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <a href="/app/" className="text-temper-accent hover:underline text-sm">
        Back to workflows
      </a>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<WorkflowList />} />
          <Route path="/workflow/:workflowId" element={<ExecutionView />} />
          <Route path="/compare" element={<ComparisonView />} />
          <Route path="/studio" element={<StudioView />} />
          <Route path="/studio/:name" element={<StudioView />} />
          <Route path="/library" element={<LibraryView />} />
          <Route path="/library/:configType/:name" element={<EditorView />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </ErrorBoundary>
      <Toaster position="bottom-right" richColors />
    </BrowserRouter>
  );
}
