import { lazy } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { ExecutionView } from '@/pages/ExecutionView';
import { WorkflowList } from '@/pages/WorkflowList';
import { StudioView } from '@/pages/StudioView';
import { LibraryView } from '@/pages/LibraryView';
import { EditorView } from '@/pages/EditorView';
import { DocsPage } from '@/pages/DocsPage';
import { CompareView } from '@/pages/CompareView';
import { SettingsPage } from '@/pages/SettingsPage';
import { AppLayout } from '@/components/layout/AppLayout';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { NotFound } from '@/components/shared/NotFound';
import { TeamGate } from '@/components/team/TeamGate';
import { Toaster } from '@/components/ui/sonner';

// The Team pages load on demand, and only while the Team switch is on.
const TeamPage = lazy(() => import('@/pages/team/TeamPage'));
const TeamNewTrial = lazy(() => import('@/pages/team/TeamNewTrial'));
const TeamRunView = lazy(() => import('@/pages/team/TeamRunView'));

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
        { path: '/compare', element: <CompareView /> },
        { path: '/settings', element: <SettingsPage /> },
        { path: '/team', element: <TeamGate><TeamPage tab="trials" /></TeamGate> },
        { path: '/team/roles', element: <TeamGate><TeamPage tab="roles" /></TeamGate> },
        { path: '/team/new', element: <TeamGate><TeamNewTrial /></TeamGate> },
        { path: '/team/runs/:executionId', element: <TeamGate><TeamRunView /></TeamGate> },
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
      <Toaster />
    </ErrorBoundary>
  );
}
