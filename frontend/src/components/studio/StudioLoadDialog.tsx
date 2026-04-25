/**
 * Modal dialog to load an existing workflow config into the Studio editor.
 */
import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useConfigs } from '@/hooks/useConfigAPI';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';

interface StudioLoadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function StudioLoadDialog({ open, onOpenChange }: StudioLoadDialogProps) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useConfigs('workflow');

  const handleSelect = useCallback(
    (name: string) => {
      onOpenChange(false);
      navigate(`/studio/${name}`);
    },
    [navigate, onOpenChange],
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[540px]">
        <SheetHeader>
          <SheetTitle className="text-temper-text">Load Workflow</SheetTitle>
          <SheetDescription>
            Select a workflow to open in the Studio editor
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex flex-col gap-2 overflow-y-auto max-h-[70vh]">
          {isLoading && (
            <p className="text-xs text-temper-text-muted p-4">Loading workflows...</p>
          )}

          {error && (
            <p className="text-xs text-red-600 dark:text-red-400 p-4">
              Failed to load workflows: {(error as Error).message}
            </p>
          )}

          {data?.configs?.map((cfg) => (
            <button
              key={cfg.name}
              onClick={() => handleSelect(cfg.name)}
              className="flex flex-col gap-0.5 px-4 py-3 rounded-lg bg-temper-panel border border-temper-border hover:bg-temper-surface hover:border-temper-accent/30 transition-colors text-left"
            >
              <span className="text-sm font-medium text-temper-text">
                {cfg.name}
              </span>
              {cfg.description && (
                <span className="text-xs text-temper-text-muted truncate">
                  {cfg.description}
                </span>
              )}
            </button>
          ))}

          {data && data.configs.length === 0 && (
            <p className="text-xs text-temper-text-muted p-4">
              No workflow configs found. Create one from scratch!
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
