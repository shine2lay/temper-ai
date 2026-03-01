/**
 * Top header bar for the Studio editor.
 * Contains: back arrow, undo/redo, workflow name, dirty indicator, action buttons.
 */
import { useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useDesignStore } from '@/store/designStore';
import { useSaveWorkflowDB, useValidateWorkflow, useRunWorkflow } from '@/hooks/useStudioAPI';
import { Button } from '@/components/ui/button';

interface StudioHeaderProps {
  onOpenLoadDialog: () => void;
}

export function StudioHeader({ onOpenLoadDialog }: StudioHeaderProps) {
  const navigate = useNavigate();
  const isDirty = useDesignStore((s) => s.isDirty);
  const meta = useDesignStore((s) => s.meta);
  const setMeta = useDesignStore((s) => s.setMeta);
  const setValidation = useDesignStore((s) => s.setValidation);
  const toWorkflowConfig = useDesignStore((s) => s.toWorkflowConfig);
  const undo = useDesignStore((s) => s.undo);
  const redo = useDesignStore((s) => s.redo);
  const canUndo = useDesignStore((s) => s.canUndo);
  const canRedo = useDesignStore((s) => s.canRedo);

  const saveMutation = useSaveWorkflowDB();
  const validateMutation = useValidateWorkflow();
  const runMutation = useRunWorkflow();

  const handleValidate = useCallback(async () => {
    setValidation({ status: 'validating', errors: [] });
    try {
      const config = toWorkflowConfig();
      const result = await validateMutation.mutateAsync(config);
      setValidation({
        status: result.valid ? 'valid' : 'invalid',
        errors: result.errors,
      });
      if (result.valid) toast.success('Configuration is valid');
      else toast.error(`${result.errors.length} validation error(s)`);
    } catch (err) {
      setValidation({ status: 'invalid', errors: [(err as Error).message] });
      toast.error('Validation failed');
    }
  }, [toWorkflowConfig, validateMutation, setValidation]);

  const handleSave = useCallback(async () => {
    const { configName: currentName, meta: currentMeta, toWorkflowConfig: buildConfig } =
      useDesignStore.getState();
    const name = currentName ?? currentMeta.name;
    if (!name) {
      toast.error('Please enter a workflow name first');
      return;
    }
    try {
      const config = buildConfig();
      const isNew = !currentName;
      await saveMutation.mutateAsync({ name, data: config, isNew });
      useDesignStore.getState().markSaved(name);
      toast.success(`Saved workflow "${name}"`);
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`);
    }
  }, [saveMutation]);

  const handleRun = useCallback(async () => {
    const { configName: currentName, meta: currentMeta, isDirty: currentDirty, toWorkflowConfig: buildConfig } =
      useDesignStore.getState();
    const name = currentName ?? currentMeta.name;
    if (!name) {
      toast.error('Please enter a workflow name first');
      return;
    }

    // Save first if dirty
    if (currentDirty || !currentName) {
      try {
        const config = buildConfig();
        const isNew = !currentName;
        await saveMutation.mutateAsync({ name, data: config, isNew });
        useDesignStore.getState().markSaved(name);
      } catch (err) {
        toast.error(`Save failed: ${(err as Error).message}`);
        return;
      }
    }

    const workflowPath = `configs/workflows/${name}.yaml`;
    try {
      const result = await runMutation.mutateAsync({ workflow: workflowPath });
      toast.success('Workflow started');
      navigate(`/workflow/${result.execution_id}`);
    } catch (err) {
      toast.error(`Run failed: ${(err as Error).message}`);
    }
  }, [saveMutation, runMutation, navigate]);

  // Ctrl+S / Ctrl+Z / Ctrl+Shift+Z keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key === 's') {
        e.preventDefault();
        handleSave();
      } else if (ctrl && !e.shiftKey && e.key === 'z') {
        e.preventDefault();
        useDesignStore.getState().undo();
      } else if (ctrl && e.shiftKey && e.key === 'z') {
        e.preventDefault();
        useDesignStore.getState().redo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleSave]);

  const isRunning = saveMutation.isPending || runMutation.isPending;

  return (
    <header className="flex items-center gap-3 bg-temper-panel px-4 py-2.5 border-b border-temper-border shrink-0 relative z-30">
      {/* Back arrow */}
      <button
        onClick={() => navigate('/')}
        className="text-temper-text-muted hover:text-temper-text transition-colors text-sm"
        aria-label="Back to workflow list"
      >
        &larr;
      </button>

      {/* Undo / Redo */}
      <div className="flex items-center gap-1">
        <button
          onClick={undo}
          disabled={!canUndo}
          title="Undo (Ctrl+Z)"
          aria-label="Undo"
          className="w-7 h-7 flex items-center justify-center rounded text-sm text-temper-text-muted hover:text-temper-text hover:bg-temper-surface disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          &#8630;
        </button>
        <button
          onClick={redo}
          disabled={!canRedo}
          title="Redo (Ctrl+Shift+Z)"
          aria-label="Redo"
          className="w-7 h-7 flex items-center justify-center rounded text-sm text-temper-text-muted hover:text-temper-text hover:bg-temper-surface disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          &#8631;
        </button>
      </div>

      {/* Workflow name — inline editable */}
      <input
        type="text"
        value={meta.name}
        onChange={(e) => setMeta({ name: e.target.value })}
        placeholder="Untitled Workflow"
        aria-label="Workflow name"
        className="text-sm font-semibold text-temper-text bg-transparent border-none outline-none focus:ring-0 w-48"
      />

      {/* Dirty indicator */}
      {isDirty && (
        <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" title="Unsaved changes" />
      )}

      <div className="flex-1" />

      {/* Action buttons */}
      <Button variant="ghost" size="sm" onClick={onOpenLoadDialog}>
        Load
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={handleValidate}
        disabled={validateMutation.isPending}
      >
        Validate
      </Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={handleSave}
        disabled={saveMutation.isPending}
      >
        Save
      </Button>
      <Button
        variant="default"
        size="sm"
        onClick={handleRun}
        disabled={isRunning}
      >
        Run
      </Button>
    </header>
  );
}
