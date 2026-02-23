/**
 * Route entry point for /studio and /studio/:name.
 * Loads a workflow config by name param if provided, then renders StudioPage.
 */
import { useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useDesignStore } from '@/store/designStore';
import { useStudioConfig } from '@/hooks/useStudioAPI';
import { StudioPage } from '@/components/studio/StudioPage';

export function StudioView() {
  const { name } = useParams<{ name?: string }>();
  const { data, isLoading, error } = useStudioConfig('workflows', name ?? null);
  const loadFromConfig = useDesignStore((s) => s.loadFromConfig);
  const reset = useDesignStore((s) => s.reset);
  const configName = useDesignStore((s) => s.configName);

  // Load config when data arrives
  useEffect(() => {
    if (name && data) {
      loadFromConfig(name, data);
    }
  }, [name, data, loadFromConfig]);

  // Reset store when navigating to /studio (new workflow) and no name
  useEffect(() => {
    if (!name && configName !== null) {
      reset();
    }
  }, [name, configName, reset]);

  if (name && isLoading) {
    return (
      <div className="flex items-center justify-center h-full bg-temper-bg">
        <p className="text-sm text-temper-text-muted">Loading workflow...</p>
      </div>
    );
  }

  if (name && error) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-temper-bg gap-2">
        <p className="text-sm text-red-400">
          Failed to load workflow: {(error as Error).message}
        </p>
        <Link to="/studio" className="text-xs text-temper-accent hover:underline">
          Create new workflow
        </Link>
      </div>
    );
  }

  return <StudioPage />;
}
