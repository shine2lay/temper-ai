/**
 * Detail panel for script agents — shows execution info, script output,
 * and error details. No LLM-specific fields (tokens, prompts, etc.).
 */
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { MetricCell } from '@/components/shared/MetricCell';
import { ErrorDisplay } from '@/components/shared/ErrorDisplay';
import { EmptyState } from '@/components/shared/EmptyState';
import { SmartContent } from '@/components/shared/SmartContent';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { formatDuration, formatTimestamp } from '@/lib/utils';

interface ScriptAgentDetailPanelProps {
  agentId: string;
}

export function ScriptAgentDetailPanel({ agentId }: ScriptAgentDetailPanelProps) {
  const ag = useExecutionStore((s) => s.agents.get(agentId));
  const select = useExecutionStore((s) => s.select);
  const stages = useExecutionStore((s) => s.stages);

  if (!ag) {
    return <EmptyState title="Agent not found" />;
  }

  const configOuter = ag.agent_config_snapshot?.agent;
  // Config may be double-nested: agent.agent.script_template
  const config = (configOuter?.agent ?? configOuter) as Record<string, unknown> | undefined;
  const scriptTemplate = config?.script_template as string | undefined;
  const timeout = config?.timeout_seconds as number | undefined;

  // Find parent stage
  const resolvedStageId = ag.stage_execution_id ?? ag.stage_id ??
    (() => {
      for (const [stageId, stage] of Array.from(stages)) {
        if (stage.agents?.some((a) => a.id === agentId)) return stageId;
      }
      return undefined;
    })();

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Breadcrumb */}
      {resolvedStageId && (
        <button
          onClick={() => select('stage', resolvedStageId)}
          className="text-xs text-temper-accent hover:underline self-start"
        >
          &larr; Back to Stage
        </button>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {ag.agent_name ?? ag.name ?? agentId}
        </h3>
        <StatusBadge status={ag.status} />
        <Badge variant="secondary" className="text-xs bg-amber-500/15 text-amber-400 border-amber-500/30">
          script
        </Badge>
      </div>

      {/* Metrics — script-specific */}
      <div className="grid grid-cols-3 gap-2">
        <MetricCell label="Duration" value={formatDuration(ag.duration_seconds)} compact />
        <MetricCell
          label="Exit Status"
          value={ag.status === 'completed' ? 'Success (0)' : ag.status === 'failed' ? 'Failed' : ag.status}
          compact
        />
        {timeout && (
          <MetricCell label="Timeout" value={`${timeout}s`} compact />
        )}
      </div>

      {/* Timestamps */}
      <div className="grid grid-cols-2 gap-2">
        <MetricCell label="Start Time" value={formatTimestamp(ag.start_time)} compact />
        <MetricCell label="End Time" value={formatTimestamp(ag.end_time)} compact />
      </div>

      {/* Error */}
      {ag.error_message && <ErrorDisplay error={ag.error_message} />}

      <Separator />

      {/* Output (stdout) — show first since this is what matters most for scripts */}
      <CollapsibleSection title="Output (stdout)" defaultOpen>
        {ag.output ? (
          <SmartContent content={ag.output} maxHeight={500} />
        ) : (
          <span className="text-xs text-temper-text-dim">No output captured</span>
        )}
      </CollapsibleSection>

      {/* Script Template — the actual commands that were executed */}
      {scriptTemplate && (
        <CollapsibleSection title="Script (executed)" defaultOpen>
          <SmartContent content={scriptTemplate} maxHeight={400} />
        </CollapsibleSection>
      )}

      {/* Input Data (variables injected into the script template) */}
      <CollapsibleSection title="Input Variables">
        {ag.input_data && Object.keys(ag.input_data).length > 0 ? (
          <SmartContent content={JSON.stringify(ag.input_data, null, 2)} maxHeight={300} />
        ) : (
          <span className="text-xs text-temper-text-dim">No input data</span>
        )}
      </CollapsibleSection>

      {/* Structured Output (if script printed JSON) */}
      {ag.output_data && Object.keys(ag.output_data).length > 0 && (
        <CollapsibleSection title="Structured Output (parsed from stdout)">
          <SmartContent content={JSON.stringify(ag.output_data, null, 2)} maxHeight={300} />
        </CollapsibleSection>
      )}
    </div>
  );
}
