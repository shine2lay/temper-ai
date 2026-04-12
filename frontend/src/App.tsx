import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { ExecutionView } from '@/pages/ExecutionView';
import { WorkflowList } from '@/pages/WorkflowList';
import { StudioView } from '@/pages/StudioView';
import { LibraryView } from '@/pages/LibraryView';
import { EditorView } from '@/pages/EditorView';
import { DocsPage } from '@/pages/DocsPage';
import { AppLayout } from '@/components/layout/AppLayout';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { Toaster } from '@/components/ui/sonner';

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

const router = createBrowserRouter(
  [
    {
      element: <AppLayout />,
      children: [
        { path: '/', element: <WorkflowList /> },
        { path: '/workflow/:workflowId', element: <ExecutionView /> },
        { path: '/studio', element: <StudioView /> },
        { path: '/studio/:name', element: <StudioView /> },
        { path: '/library', element: <LibraryView /> },
        { path: '/library/:configType/:name', element: <EditorView /> },
        { path: '/docs', element: <DocsPage /> },
        { path: '*', element: <NotFound /> },
      ],
    },
  ],
  { basename: '/app' },
);

export default function App() {
  return (
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors />
    </ErrorBoundary>
  );
}
