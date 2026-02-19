import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ExecutionView } from '@/pages/ExecutionView';
import { WorkflowList } from '@/pages/WorkflowList';
import { ComparisonView } from '@/pages/ComparisonView';
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

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/workflow/:workflowId" element={<ExecutionView />} />
        <Route path="/compare" element={<ComparisonView />} />
        <Route path="/" element={<WorkflowList />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}
