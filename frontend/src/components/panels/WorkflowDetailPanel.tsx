import { useMemo } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { CollapsibleSection } from '@/components/shared/Collapsible';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { MetricCell } from '@/components/shared/MetricCell';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Download } from 'lucide-react';
import { formatDuration, formatTimestamp, formatTokens, formatCost, formatBytes, categorizeError } from '@/lib/utils';

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function handleExportJSON() {
  const state = useExecutionStore.getState();
  const data = {
    workflow: state.workflow,
    stages: Object.fromEntries(state.stages),
    agents: Object.fromEntries(state.agents),
    llmCalls: Object.fromEntries(state.llmCalls),
    toolCalls: Object.fromEntries(state.toolCalls),
  };
  downloadFile(
    JSON.stringify(data, null, 2),
    `workflow-${state.workflow?.id ?? 'export'}.json`,
    'application/json',
  );
}

function handleExportCSV() {
  const state = useExecutionStore.getState();
  const rows = ['Stage,Status,Duration(s),Agents,Tokens,Cost'];
  for (const [, stage] of state.stages) {
    rows.push([
      stage.stage_name ?? stage.name ?? stage.id,
      stage.status,
      String(stage.duration_seconds ?? 0),
      String(stage.agents?.length ?? 0),
      String(stage.agents?.reduce((sum, a) => sum + (a.total_tokens ?? 0), 0) ?? 0),
      String(stage.agents?.reduce((sum, a) => sum + (a.estimated_cost_usd ?? 0), 0) ?? 0),
    ].join(','));
  }
  downloadFile(
    rows.join('\n'),
    `workflow-${state.workflow?.id ?? 'export'}.csv`,
    'text/csv',
  );
}

function handleExportMarkdown() {
  const state = useExecutionStore.getState();
  const wf = state.workflow;
  if (!wf) return;
  const lines = [
    `# ${wf.workflow_name}`,
    `**Status:** ${wf.status}`,
    `**Duration:** ${formatDuration(wf.duration_seconds)}`,
    `**Tokens:** ${formatTokens(wf.total_tokens)}`,
    `**Cost:** ${formatCost(wf.total_cost_usd)}`,
    '', '## Stages', '',
    '| Stage | Status | Duration | Agents |',
    '|-------|--------|----------|--------|',
  ];
  for (const [, stage] of state.stages) {
    lines.push(`| ${stage.stage_name ?? stage.id} | ${stage.status} | ${formatDuration(stage.duration_seconds)} | ${stage.agents?.length ?? 0} |`);
  }
  downloadFile(
    lines.join('\n'),
    `workflow-${wf.id}.md`,
    'text/markdown',
  );
}

export function WorkflowDetailPanel() {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const toolCalls = useExecutionStore((s) => s.toolCalls);
  const select = useExecutionStore((s) => s.select);

  const toolAnalytics = useMemo(() => {
    const stats = new Map<string, { count: number; failed: number; totalDuration: number; approvalCount: number }>();
    for (const [, tc] of toolCalls) {
      const name = tc.tool_name;
      const existing = stats.get(name) ?? { count: 0, failed: 0, totalDuration: 0, approvalCount: 0 };
      existing.count++;
      if (tc.status === 'failed') existing.failed++;
      existing.totalDuration += tc.duration_seconds ?? 0;
      if (tc.approval_required) existing.approvalCount++;
      stats.set(name, existing);
    }
    return Array.from(stats.entries())
      .map(([name, s]) => ({ name, ...s, avgDuration: s.totalDuration / s.count }))
      .sort((a, b) => b.count - a.count);
  }, [toolCalls]);

  if (!workflow) {
    return (
      <div className="p-4 text-sm text-temper-text-muted">No workflow data.</div>
    );
  }

  const inputSize = workflow.input_data ? formatBytes(new Blob([JSON.stringify(workflow.input_data)]).size) : null;
  const outputSize = workflow.output_data ? formatBytes(new Blob([JSON.stringify(workflow.output_data)]).size) : null;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-3 sticky top-0 z-10 bg-temper-bg pb-2">
        <h3 className="text-lg font-semibold text-temper-text">
          {workflow.workflow_name}
        </h3>
        <StatusBadge status={workflow.status} />
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={handleExportJSON}>
            <Download className="mr-1.5 size-3.5" />
            JSON
          </Button>
          <Button variant="ghost" size="sm" onClick={handleExportCSV}>
            <Download className="mr-1.5 size-3.5" />
            CSV
          </Button>
          <Button variant="ghost" size="sm" onClick={handleExportMarkdown}>
            <Download className="mr-1.5 size-3.5" />
            MD
          </Button>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCell label="Start Time" value={formatTimestamp(workflow.start_time)} />
        <MetricCell label="End Time" value={formatTimestamp(workflow.end_time)} />
        <MetricCell label="Total Tokens" value={formatTokens(workflow.total_tokens)} />
        <MetricCell label="Total Cost" value={formatCost(workflow.total_cost_usd)} />
        <MetricCell label="LLM Calls" value={String(workflow.total_llm_calls ?? 0)} />
        <MetricCell label="Tool Calls" value={String(workflow.total_tool_calls ?? 0)} />
      </div>

      {/* Error */}
      {workflow.status === 'failed' && workflow.error_message && (() => {
        const { type, retryable } = categorizeError(workflow.error_message);
        return (
          <div className="rounded-md bg-temper-bg-failed p-3 text-sm text-temper-failed">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-950 border border-red-900/50">{type}</span>
              {retryable && <span className="text-xs text-amber-400">Retryable</span>}
            </div>
            {workflow.error_message}
          </div>
        );
      })()}

      {/* Stage breakdown */}
      {stages.size > 0 && (
        <>
          <Separator />
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-temper-text-muted">Stage Breakdown</span>
            <div className="flex flex-col gap-1">
              {Array.from(stages.values()).map((stage) => (
                <button
                  key={stage.id}
                  onClick={() => select('stage', stage.id)}
                  className="flex items-center justify-between rounded-md bg-temper-panel p-2 text-xs hover:bg-temper-surface transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <StatusBadge status={stage.status} />
                    <span className="text-temper-text font-medium">
                      {stage.stage_name ?? stage.name ?? stage.id}
                    </span>
                  </span>
                  <span className="flex items-center gap-3 text-temper-text-muted">
                    <span>{formatDuration(stage.duration_seconds)}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Tool Analytics */}
      {toolAnalytics.length > 0 && (
        <CollapsibleSection title="Tool Analytics">
          <div className="flex flex-col gap-1 mt-1">
            {toolAnalytics.map(t => (
              <div key={t.name} className="flex items-center justify-between rounded-md bg-temper-panel p-2 text-xs">
                <span className="text-temper-text font-medium">{t.name}</span>
                <div className="flex items-center gap-3 text-temper-text-muted">
                  <span>{t.count} calls</span>
                  {t.failed > 0 && <span className="text-red-400">{t.failed} failed</span>}
                  <span>avg {formatDuration(t.avgDuration)}</span>
                  {t.approvalCount > 0 && <span className="text-amber-400">{t.approvalCount} approval</span>}
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      <Separator />

      {/* Collapsible sections */}
      <CollapsibleSection title={`Input Data${inputSize ? ` (${inputSize})` : ''}`}>
        <JsonViewer data={workflow.input_data} />
      </CollapsibleSection>

      <CollapsibleSection title={`Output Data${outputSize ? ` (${outputSize})` : ''}`}>
        <JsonViewer data={workflow.output_data} />
      </CollapsibleSection>

      {/* Workflow Config */}
      {(workflow.workflow_config ?? workflow.workflow_config_snapshot) && (
        <CollapsibleSection title="Workflow Config">
          <JsonViewer data={workflow.workflow_config ?? workflow.workflow_config_snapshot} />
        </CollapsibleSection>
      )}
    </div>
  );
}
