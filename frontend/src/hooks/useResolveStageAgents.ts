/**
 * Fetches stage configs for all stage_ref stages in the current workflow
 * and populates resolvedStageInfo + resolvedAgentSummaries in the design store.
 * Call once from StudioPage.
 */
import { useEffect, useRef } from 'react';
import { useDesignStore } from '@/store/designStore';

const STUDIO_BASE = '/api/studio';

/** Framework-internal template variables that should not appear as agent inputs. */
const INTERNAL_VARS = new Set([
  'command_results', 'memory_context', 'dialogue_context', 'stage_outputs',
  'reasoning_plan', 'team_outputs', 'agent_outputs', 'interaction_mode',
  'mode_instruction', 'debate_framing',
]);

/** Extract {{ variable }} names from a Jinja2 prompt template, filtering framework internals. */
function extractPromptInputs(template: string): string[] {
  // Collect local {% set var = ... %} assignments so we can exclude them
  const localVars = new Set<string>();
  const setRe = /\{%[-\s]*set\s+([a-zA-Z_]\w*)\s*=/g;
  let setMatch: RegExpExecArray | null;
  while ((setMatch = setRe.exec(template)) !== null) {
    localVars.add(setMatch[1]);
  }

  const seen = new Set<string>();
  const results: string[] = [];
  // Match {{ var }}, {{ var | filter }}, and {{ var.attr }}
  const re = /\{\{[\s]*([a-zA-Z_][a-zA-Z0-9_.]*?)[\s]*[|}]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(template)) !== null) {
    const name = m[1].split('.')[0]; // top-level variable only
    if (!seen.has(name) && !INTERNAL_VARS.has(name) && !localVars.has(name)) {
      seen.add(name);
      results.push(name);
    }
  }
  return results.sort();
}

/** Extract field names and types from an agent's output_schema. */
function extractOutputSchemaFields(
  outputSchema: unknown,
): { name: string; type: string }[] {
  if (!outputSchema || typeof outputSchema !== 'object') return [];
  const schema = outputSchema as Record<string, unknown>;
  const jsonSchema = schema.json_schema as Record<string, unknown> | undefined;
  const target = jsonSchema ?? schema;
  const props = target.properties as Record<string, unknown> | undefined;
  if (!props || typeof props !== 'object') return [];
  return Object.entries(props).map(([name, val]) => {
    const propDef = val as Record<string, unknown> | undefined;
    return { name, type: (propDef?.type as string) ?? 'string' };
  });
}

/** Normalize tool entries — handles both plain strings and {name, config} objects. */
function normalizeToolNames(tools: unknown): string[] {
  if (!Array.isArray(tools)) return [];
  return tools.map((t) => {
    if (typeof t === 'string') return t;
    if (typeof t === 'object' && t !== null) {
      return (t as Record<string, unknown>).name as string ?? 'unknown';
    }
    return String(t);
  });
}

/** Extract outputs array from stage config. Handles both array-of-objects and record formats. */
function extractOutputs(
  raw: unknown,
): { name: string; type: string; description: string }[] {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map((item) => {
      if (typeof item === 'string') return { name: item, type: 'string', description: '' };
      const obj = item as Record<string, unknown>;
      return {
        name: (obj.name as string) ?? '',
        type: (obj.type as string) ?? 'string',
        description: (obj.description as string) ?? '',
      };
    });
  }
  // Record<name, {type, description}>
  if (typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([name, val]) => {
      if (typeof val === 'string') return { name, type: val, description: '' };
      const obj = val as Record<string, unknown>;
      return {
        name,
        type: (obj.type as string) ?? 'string',
        description: (obj.description as string) ?? '',
      };
    });
  }
  return [];
}

export function useResolveStageAgents() {
  const stages = useDesignStore((s) => s.stages);
  const resolvedStageInfo = useDesignStore((s) => s.resolvedStageInfo);
  const setResolvedStageInfo = useDesignStore((s) => s.setResolvedStageInfo);
  const setResolvedAgentSummary = useDesignStore((s) => s.setResolvedAgentSummary);
  const stageInflightRef = useRef(new Set<string>());
  const agentInflightRef = useRef(new Set<string>());

  // Reset inflight tracking when stages array reference changes (e.g. loadFromConfig)
  useEffect(() => {
    stageInflightRef.current.clear();
    agentInflightRef.current.clear();
  }, [stages]);

  // Phase 1: Fetch stage configs and extract enriched info
  useEffect(() => {
    for (const stage of stages) {
      if (!stage.stage_ref) continue;
      if (resolvedStageInfo[stage.name]) continue;
      if (stageInflightRef.current.has(stage.name)) continue;

      const configName = stage.stage_ref.replace(/^.*\//, '').replace(/\.yaml$/, '');
      stageInflightRef.current.add(stage.name);

      fetch(`${STUDIO_BASE}/configs/stages/${configName}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!data) return;
          const stageData = (data as { stage?: Record<string, unknown> }).stage ?? data;
          const inner = stageData as Record<string, unknown>;
          const agents = (inner.agents as string[]) ?? [];
          const execution = inner.execution as Record<string, unknown> | undefined;
          const collaboration = inner.collaboration as Record<string, unknown> | undefined;
          const collabConfig = collaboration?.config as Record<string, unknown> | undefined;
          const safety = inner.safety as Record<string, unknown> | undefined;
          const errorHandling = inner.error_handling as Record<string, unknown> | undefined;
          const conflictRes = inner.conflict_resolution as Record<string, unknown> | undefined;
          const qualityGates = inner.quality_gates as Record<string, unknown> | undefined;
          const convergence = inner.convergence as Record<string, unknown> | undefined;

          // Extract stage-level inputs (Record<name, {source, required, ...}>)
          const rawInputs = inner.inputs as Record<string, unknown> | undefined;
          const resolvedInputs: Record<string, { source: string }> = {};
          if (rawInputs && typeof rawInputs === 'object') {
            for (const [key, val] of Object.entries(rawInputs)) {
              if (typeof val === 'object' && val !== null) {
                const inputDef = val as Record<string, unknown>;
                resolvedInputs[key] = { source: (inputDef.source as string) ?? '' };
              } else if (typeof val === 'string') {
                resolvedInputs[key] = { source: val };
              }
            }
          }

          setResolvedStageInfo(stage.name, {
            agents,
            agentMode: (execution?.agent_mode as string) ?? 'sequential',
            collaborationStrategy: (collaboration?.strategy as string) ?? 'independent',
            description: (inner.description as string) ?? '',
            timeoutSeconds: (execution?.timeout_seconds as number) ?? null,
            safetyMode: (safety?.mode as string) ?? null,
            inputs: resolvedInputs,
            outputs: extractOutputs(inner.outputs),
            errorHandling: errorHandling
              ? {
                  onAgentFailure: (errorHandling.on_agent_failure as string) ?? 'continue',
                  minSuccessfulAgents: (errorHandling.min_successful_agents as number) ?? null,
                  retryFailedAgents: (errorHandling.retry_failed_agents as boolean) ?? false,
                  maxAgentRetries: (errorHandling.max_agent_retries as number) ?? null,
                }
              : null,
            leaderAgent: (collabConfig?.leader_agent as string) ?? null,
            // Expanded config details
            version: (inner.version as string) ?? null,
            collaborationMaxRounds: (collabConfig?.max_rounds as number) ?? null,
            collaborationConvergenceThreshold: (collabConfig?.convergence_threshold as number) ?? null,
            collaborationDialogueMode: (collabConfig?.dialogue_mode as boolean) ?? null,
            collaborationRoles: (collabConfig?.roles as Record<string, string>) ?? {},
            conflictResolution: conflictRes
              ? {
                  strategy: (conflictRes.strategy as string) ?? '',
                  metrics: (conflictRes.metrics as string[]) ?? [],
                  metricWeights: (conflictRes.metric_weights as Record<string, string>) ?? {},
                  autoResolveThreshold: (conflictRes.auto_resolve_threshold as number) ?? 0.85,
                  escalationThreshold: (conflictRes.escalation_threshold as number) ?? 0.5,
                }
              : null,
            safetyDryRunFirst: (safety?.dry_run_first as boolean) ?? null,
            safetyRequireApproval: (safety?.require_approval as boolean) ?? null,
            qualityGates: qualityGates
              ? {
                  enabled: (qualityGates.enabled as boolean) ?? false,
                  minConfidence: (qualityGates.min_confidence as number) ?? 0.7,
                  minFindings: (qualityGates.min_findings as number) ?? 5,
                  requireCitations: (qualityGates.require_citations as boolean) ?? true,
                  onFailure: (qualityGates.on_failure as string) ?? 'retry_stage',
                  maxRetries: (qualityGates.max_retries as number) ?? 2,
                }
              : null,
            convergence: convergence
              ? {
                  enabled: (convergence.enabled as boolean) ?? false,
                  maxIterations: (convergence.max_iterations as number) ?? 5,
                  similarityThreshold: (convergence.similarity_threshold as number) ?? 0.95,
                  method: (convergence.method as string) ?? 'exact_hash',
                }
              : null,
          });
        })
        .catch(() => {
          // Silently ignore fetch errors
        })
        .finally(() => {
          stageInflightRef.current.delete(stage.name);
        });
    }
  }, [stages, resolvedStageInfo, setResolvedStageInfo]);

  // Phase 2: Fetch agent configs for all resolved agents
  useEffect(() => {
    // Collect all agent names from resolved stage info + inline stages
    const allAgentNames = new Set<string>();
    for (const stage of stages) {
      const resolved = resolvedStageInfo[stage.name];
      const agents = resolved ? resolved.agents : stage.agents;
      for (const name of agents) allAgentNames.add(name);
    }

    for (const agentName of allAgentNames) {
      // Guard via store snapshot (not reactive) + inflight ref to avoid O(n^2) re-runs
      if (useDesignStore.getState().resolvedAgentSummaries[agentName]) continue;
      if (agentInflightRef.current.has(agentName)) continue;

      agentInflightRef.current.add(agentName);

      fetch(`${STUDIO_BASE}/configs/agents/${agentName}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!data) return;
          const agentData = (data as { agent?: Record<string, unknown> }).agent ?? data;
          const inner = agentData as Record<string, unknown>;
          const inference = inner.inference as Record<string, unknown> | undefined;
          const safety = inner.safety as Record<string, unknown> | undefined;
          const memory = inner.memory as Record<string, unknown> | undefined;
          const reasoning = inner.reasoning as Record<string, unknown> | undefined;
          const errorHandling = inner.error_handling as Record<string, unknown> | undefined;
          const prompt = inner.prompt as Record<string, unknown> | undefined;
          const preCommands = inner.pre_commands as unknown[] | undefined;
          const outputSchema = inner.output_schema;

          const toolNames = normalizeToolNames(inner.tools);
          const promptTemplate = (prompt?.inline as string) ?? '';

          setResolvedAgentSummary(agentName, {
            name: agentName,
            model: (inference?.model as string) ?? 'unknown',
            provider: (inference?.provider as string) ?? 'unknown',
            type: (inner.type as string) ?? 'standard',
            toolCount: toolNames.length,
            toolNames,
            temperature: (inference?.temperature as number) ?? 0.7,
            safetyMode: (safety?.mode as string) ?? 'execute',

            description: (inner.description as string) ?? '',
            version: (inner.version as string) ?? '',

            maxTokens: (inference?.max_tokens as number) ?? 0,
            topP: (inference?.top_p as number) ?? 1,
            timeoutSeconds: (inference?.timeout_seconds as number) ?? 0,

            memoryEnabled: (memory?.enabled as boolean) ?? false,
            memoryType: (memory?.type as string) ?? null,
            reasoningEnabled: (reasoning?.enabled as boolean) ?? false,
            persistent: (inner.persistent as boolean) ?? false,
            hasOutputSchema: outputSchema != null,
            hasPreCommands: Array.isArray(preCommands) && preCommands.length > 0,
            preCommandCount: Array.isArray(preCommands) ? preCommands.length : 0,

            riskLevel: (safety?.risk_level as string) ?? '',
            maxToolCalls: (safety?.max_tool_calls_per_execution as number) ?? 0,

            retryStrategy: (errorHandling?.retry_strategy as string) ?? '',
            maxRetries: (errorHandling?.max_retries as number) ?? 0,

            promptInputs: extractPromptInputs(promptTemplate),
            outputSchemaFields: extractOutputSchemaFields(outputSchema),
          });
        })
        .catch(() => {
          // Silently ignore fetch errors
        })
        .finally(() => {
          agentInflightRef.current.delete(agentName);
        });
    }
  }, [stages, resolvedStageInfo, setResolvedAgentSummary]);
}
