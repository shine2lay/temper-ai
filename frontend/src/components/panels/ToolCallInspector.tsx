import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { CopyButton } from '@/components/shared/CopyButton';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { formatDuration, formatTimestamp, categorizeError } from '@/lib/utils';

interface ToolCallInspectorProps {
  toolCallId: string;
}

export function ToolCallInspector({ toolCallId }: ToolCallInspectorProps) {
  const toolCall = useExecutionStore((s) => s.toolCalls.get(toolCallId));
  const select = useExecutionStore((s) => s.select);
  const agents = useExecutionStore((s) => s.agents);
  const stages = useExecutionStore((s) => s.stages);

  if (!toolCall) {
    return (
      <div className="p-4 text-sm text-temper-text-muted">
        Tool call not found.
      </div>
    );
  }

  const parentAgent = toolCall.agent_execution_id ? agents.get(toolCall.agent_execution_id) : undefined;
  const parentStageId = parentAgent?.stage_execution_id ?? parentAgent?.stage_id;
  const parentStage = parentStageId ? stages.get(parentStageId) : undefined;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-xs flex-wrap">
        {parentStage && (
          <>
            <button
              onClick={() => select('stage', parentStageId!)}
              className="text-temper-accent hover:underline"
            >
              {parentStage.stage_name ?? parentStage.name ?? parentStageId}
            </button>
            <span className="text-temper-text-dim">&gt;</span>
          </>
        )}
        {toolCall.agent_execution_id && (
          <>
            <button
              onClick={() => select('agent', toolCall.agent_execution_id!)}
              className="text-temper-accent hover:underline"
            >
              {parentAgent?.agent_name ?? parentAgent?.name ?? toolCall.agent_execution_id}
            </button>
            <span className="text-temper-text-dim">&gt;</span>
          </>
        )}
        <span className="text-temper-text-muted">{toolCall.tool_name}</span>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {toolCall.tool_name}
        </h3>
        <StatusBadge status={toolCall.status} />
        {toolCall.safety_checks_applied != null && (
          <Badge
            variant="outline"
            className="text-xs bg-temper-panel text-temper-text-muted"
          >
            safety checked
          </Badge>
        )}
        {toolCall.approval_required && (
          <Badge
            variant="outline"
            className="text-xs bg-amber-950/30 text-amber-400 border-amber-900/50"
          >
            Approval Required
          </Badge>
        )}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCell label="Duration" value={formatDuration(toolCall.duration_seconds)} />
        <MetricCell label="Start Time" value={formatTimestamp(toolCall.start_time)} />
        <MetricCell label="End Time" value={formatTimestamp(toolCall.end_time)} />
      </div>

      {/* Error */}
      {toolCall.status === 'failed' && toolCall.error_message && (() => {
        const { type, retryable } = categorizeError(toolCall.error_message);
        return (
          <div className="rounded-md bg-temper-bg-failed p-3 text-sm text-temper-failed">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-950 border border-red-900/50">{type}</span>
              {retryable && <span className="text-xs text-amber-400">Retryable</span>}
            </div>
            {toolCall.error_message}
          </div>
        );
      })()}

      <Separator />

      {/* Input Parameters */}
      <CollapsibleSection title="Input Parameters" defaultOpen>
        {(toolCall.input_data ?? toolCall.input_params) ? (
          <>
            <JsonViewer data={toolCall.input_data ?? toolCall.input_params} />
            <CopyButton text={JSON.stringify(toolCall.input_data ?? toolCall.input_params, null, 2)} className="mt-1" />
          </>
        ) : (
          <p className="mt-1 text-xs text-temper-text-dim">No input parameters</p>
        )}
      </CollapsibleSection>

      {/* Output */}
      <CollapsibleSection title="Output" defaultOpen>
        {toolCall.output_data != null ? (
          <>
            <JsonViewer data={toolCall.output_data} />
            <CopyButton
              text={
                typeof toolCall.output_data === 'string'
                  ? toolCall.output_data
                  : JSON.stringify(toolCall.output_data, null, 2)
              }
              className="mt-1"
            />
          </>
        ) : (
          <p className="mt-1 text-xs text-temper-text-dim">No output data</p>
        )}
      </CollapsibleSection>

      {/* Safety checks */}
      {toolCall.safety_checks_applied != null && (
        <CollapsibleSection title="Safety Checks">
          <JsonViewer data={toolCall.safety_checks_applied} />
        </CollapsibleSection>
      )}
    </div>
  );
}
