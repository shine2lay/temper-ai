/**
 * Derived state selectors for the execution store.
 */
import type { StageExecution, StageConfig } from '@/types';
import { useExecutionStore } from './executionStore';

/** Group stage executions by stage_name (for collapsed DAG with iteration badges). */
export function selectStageGroups(
  stages: Map<string, StageExecution>,
): Map<string, StageExecution[]> {
  const groups = new Map<string, StageExecution[]>();
  for (const [, stage] of stages) {
    if (!stage.id) continue;
    const name = stage.stage_name ?? stage.name ?? stage.id;
    const group = groups.get(name);
    if (group) {
      group.push(stage);
    } else {
      groups.set(name, [stage]);
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

/** Extract depends_on, loops_back_to, and max_loops from workflow config. */
export function selectDagInfo(): DagInfo {
  const workflow = useExecutionStore.getState().workflow;
  const result: DagInfo = {
    depMap: new Map(),
    loopsBackTo: new Map(),
    maxLoops: new Map(),
    hasDeps: false,
  };
  if (!workflow) return result;

  const configSnap = workflow.workflow_config ?? workflow.workflow_config_snapshot;
  if (!configSnap) return result;

  const wfConfig =
    'workflow' in configSnap ? configSnap.workflow : configSnap;
  const configStages: StageConfig[] =
    (wfConfig as { stages?: StageConfig[] })?.stages ?? [];

  for (const cs of configStages) {
    const name = cs.name;
    if (!name) continue;
    const deps = cs.depends_on ?? [];
    result.depMap.set(name, deps);
    if (deps.length > 0) result.hasDeps = true;
    if (cs.loops_back_to) {
      result.loopsBackTo.set(name, cs.loops_back_to);
    }
    if (cs.max_loops != null) {
      result.maxLoops.set(name, cs.max_loops);
    }
  }

  return result;
}
