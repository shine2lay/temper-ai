/**
 * Everything `buildShape` may read, taken from the run-page store.
 *
 * It is a plain bag of maps so that the shape builder stays a pure function
 * a unit test can call with fakes. The one piece of work done here is
 * merging the drawn stages with the ones nested inside them: the store keeps
 * those apart on purpose (a nested node must not exist twice, or a live
 * update lands on one copy and leaves the other stale), but the big view
 * looks a stage up by id and should find either.
 */
import { useMemo } from 'react';
import type { NodeExecution } from '@/types';
import { useExecutionStore } from '@/store/executionStore';
import type { ShapeSources } from './shape';

export function useShapeSources(): ShapeSources {
  const workflow = useExecutionStore((s) => s.workflow);
  const stages = useExecutionStore((s) => s.stages);
  const nestedStages = useExecutionStore((s) => s.nestedStages);
  const agents = useExecutionStore((s) => s.agents);
  const llmCalls = useExecutionStore((s) => s.llmCalls);
  const toolCalls = useExecutionStore((s) => s.toolCalls);
  const streamingContent = useExecutionStore((s) => s.streamingContent);
  const select = useExecutionStore((s) => s.select);

  const allStages = useMemo(() => {
    if (nestedStages.size === 0) return stages;
    const merged = new Map<string, NodeExecution>(stages);
    for (const [id, node] of nestedStages) if (!merged.has(id)) merged.set(id, node);
    return merged;
  }, [stages, nestedStages]);

  return useMemo(
    () => ({
      workflow,
      stages: allStages,
      agents,
      llmCalls,
      toolCalls,
      hasStream: (agentId: string) => streamingContent.has(agentId),
      select,
    }),
    [workflow, allStages, agents, llmCalls, toolCalls, streamingContent, select],
  );
}
