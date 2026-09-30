/**
 * Derived state selectors for the execution store.
 * Adapted for v1 composable graph model.
 */
import { useMemo } from 'react';
import type { NodeExecution } from '@/types';
import { useExecutionStore } from './executionStore';

/**
 * Every node of the run by id: the ones the graph draws plus the ones that
 * sit inside another node.
 *
 * The graph draws the top level (and the rounds a dispatcher added, lifted
 * out), so `stages` has no key for a stage inside a stage and its panel read
 * "Stage not found". Panels look here instead; the header counts and the
 * graph keep reading `stages` alone, so they stay top-level.
 */
export function useStageLookup(): Map<string, NodeExecution> {
  const stages = useExecutionStore((s) => s.stages);
  const nested = useExecutionStore((s) => s.nestedStages);
  return useMemo(
    // A drawn node wins over a nested one of the same id, which cannot
    // happen today: the store never puts a node in both.
    () => (nested.size === 0 ? stages : new Map([...nested, ...stages])),
    [stages, nested],
  );
}

/** One node by id, wherever it sits. Undefined while the page has no record. */
export function useStage(stageId: string | null | undefined): NodeExecution | undefined {
  return useExecutionStore((s) =>
    stageId ? s.stages.get(stageId) ?? s.nestedStages.get(stageId) : undefined,
  );
}

/** Group node executions by name (for collapsed DAG with iteration badges). */
export function selectStageGroups(
  stages: Map<string, NodeExecution>,
): Map<string, NodeExecution[]> {
  const groups = new Map<string, NodeExecution[]>();
  for (const [, node] of stages) {
    if (!node.id) continue;
    const name = node.name ?? node.id;
    const group = groups.get(name);
    if (group) {
      group.push(node);
    } else {
      groups.set(name, [node]);
    }
  }
  // Sort each group by start_time
  for (const [, execs] of groups) {
    execs.sort((a, b) => {
      const at = a.start_time ?? '';
      const bt = b.start_time ?? '';
      return at < bt ? -1 : at > bt ? 1 : 0;
    });
  }
  return groups;
}

export interface DagInfo {
  depMap: Map<string, string[]>;
  loopsBackTo: Map<string, string>;
  maxLoops: Map<string, number>;
  hasDeps: boolean;
}

/** Extract DAG info from workflow execution nodes.
 * v1 includes depends_on, loop_to, max_loops in each node's execution data.
 */
export function selectDagInfo(): DagInfo {
  const workflow = useExecutionStore.getState().workflow;
  const stages = useExecutionStore.getState().stages;
  const result: DagInfo = {
    depMap: new Map(),
    loopsBackTo: new Map(),
    maxLoops: new Map(),
    hasDeps: false,
  };
  if (!workflow) return result;

  for (const [, node] of stages) {
    const name = node.name ?? node.id;
    const deps = node.depends_on ?? [];
    result.depMap.set(name, deps);
    if (deps.length > 0) result.hasDeps = true;

    if (node.loop_to) {
      result.loopsBackTo.set(name, node.loop_to);
    }
    if (node.max_loops != null) {
      result.maxLoops.set(name, node.max_loops);
    }
  }

  return result;
}
