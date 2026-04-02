import { useExecutionStore } from '@/store/executionStore';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { StageDetailPanel } from '@/components/panels/StageDetailPanel';
import { AgentDetailPanel } from '@/components/panels/AgentDetailPanel';
import { LLMCallInspector } from '@/components/panels/LLMCallInspector';
import { ToolCallInspector } from '@/components/panels/ToolCallInspector';
import { WorkflowDetailPanel } from '@/components/panels/WorkflowDetailPanel';

const SHEET_TITLES: Record<string, string> = {
  workflow: 'Workflow Details',
  stage: 'Stage Details',
  agent: 'Agent Details',
  llmCall: 'LLM Call Inspector',
  toolCall: 'Tool Call Inspector',
};

export function DetailSheet() {
  const selection = useExecutionStore((s) => s.selection);
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const open = selection !== null;

  return (
    <Sheet open={open} onOpenChange={(isOpen) => !isOpen && clearSelection()}>
      <SheetContent
        side="right"
        className="w-full sm:w-[70vw] overflow-y-auto sm:max-w-[70vw]"
        onOpenAutoFocus={(e) => {
          // Focus inside the sheet, not the trigger
          const firstButton = (e.target as HTMLElement).querySelector('button, [tabindex]');
          if (firstButton) (firstButton as HTMLElement).focus();
        }}
        onCloseAutoFocus={(e) => {
          // Prevent Radix from restoring focus to the trigger element,
          // which can interfere with Tabs focus management and reset the active tab.
          e.preventDefault();
        }}
      >
        <SheetHeader>
          <SheetTitle>
            {selection ? SHEET_TITLES[selection.type] ?? 'Details' : 'Details'}
          </SheetTitle>
          <SheetDescription className="sr-only">
            Detailed view of the selected {selection?.type ?? 'item'}
          </SheetDescription>
        </SheetHeader>

        {selection?.type === 'workflow' && (
          <ErrorBoundary>
            <WorkflowDetailPanel />
          </ErrorBoundary>
        )}
        {selection?.type === 'toolCall' && (
          <ErrorBoundary>
            <ToolCallInspector toolCallId={selection.id} />
          </ErrorBoundary>
        )}
        {selection?.type === 'llmCall' && (
          <ErrorBoundary>
            <LLMCallInspector llmCallId={selection.id} />
          </ErrorBoundary>
        )}
        {selection?.type === 'agent' && (
          <ErrorBoundary>
            <AgentDetailPanel agentId={selection.id} />
          </ErrorBoundary>
        )}
        {selection?.type === 'stage' && (
          <ErrorBoundary>
            <StageDetailPanel stageId={selection.id} />
          </ErrorBoundary>
        )}
      </SheetContent>
    </Sheet>
  );
}
