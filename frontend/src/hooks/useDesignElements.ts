/**
 * Derives React Flow nodes and edges from the design store.
 * Analogous to useDagElements but for the Studio editor.
 */
import { useMemo } from 'react';
import { useDesignStore, type DesignStage, type ResolvedAgentSummary } from '@/store/designStore';
import { computeDepthsFromDepMap } from '@/lib/dagLayout';
import { STAGE_PALETTE, EDGE_COLORS } from '@/lib/constants';
import type { Node, Edge } from '@xyflow/react';

export interface DesignNodeData extends Record<string, unknown> {
  stageName: string;
  stageRef: string | null;
  dependsOn: string[];
  loopsBackTo: string | null;
  maxLoops: number | null;
  condition: string | null;
  stageColor: string;
  inputCount: number;
  agentCount: number;
  agents: string[];
  agentMode: string;
  collaborationStrategy: string;
  inputNames: string[];
  isRef: boolean;
  // Enriched fields
  inputs: Record<string, { source: string }>;
  description: string;
  timeoutSeconds: number | null;
  safetyMode: string | null;
  outputs: { name: string; type: string; description: string }[];
  errorHandling: {
    onAgentFailure: string;
    minSuccessfulAgents: number | null;
    retryFailedAgents: boolean;
    maxAgentRetries: number | null;
  } | null;
  leaderAgent: string | null;
  agentSummaries: ResolvedAgentSummary[];
  agentDetailsLoaded: boolean;
  workflowOutputSources: string[];
  // --- Expanded fields for inline node editing ---
  version: string;
  safetyDryRunFirst: boolean;
  safetyRequireApproval: boolean;
  errorMinSuccessful: number;
  errorRetryFailed: boolean;
  errorMaxRetries: number;
  qualityGatesEnabled: boolean;
  qualityGatesMinConfidence: number;
  qualityGatesMinFindings: number;
  qualityGatesRequireCitations: boolean;
  qualityGatesOnFailure: string;
  qualityGatesMaxRetries: number;
  convergenceEnabled: boolean;
  convergenceMaxIterations: number;
  convergenceSimilarityThreshold: number;
  convergenceMethod: string;
  collaborationMaxRounds: number;
  collaborationConvergenceThreshold: number;
  collaborationDialogueMode: boolean;
  collaborationRoundBudget: number | null;
  collaborationContextWindowRounds: number;
  conflictStrategy: string;
  conflictMetrics: string[];
  conflictAutoResolveThreshold: number;
}

const STAGE_NODE_WIDTH = 380;
const AGENT_NODE_WIDTH = 380;
const GAP_X = 100;
const GAP_Y = 50;
const START_X = 40;

/** Estimate node height based on agent count + input count — avoids overlap before DOM measurement. */
function estimateNodeHeight(stage: DesignStage): number {
  const agentCount = stage.agents.length;
  const inputCount = Object.keys(stage.inputs).length;
  const ioExtra = inputCount * 30; // ~30px per input row
  if (agentCount <= 1 && !stage.stage_ref) {
    return 470 + ioExtra;
  }
  return 460 + agentCount * 80 + ioExtra;
}

/**
 * Build React Flow nodes + edges from the design store.
 * Prefers manual nodePositions; falls back to auto-layout via depth computation.
 */
export function useDesignElements(): { nodes: Node[]; edges: Edge[] } {
  const stages = useDesignStore((s) => s.stages);
  const nodePositions = useDesignStore((s) => s.nodePositions);
  const resolvedStageInfo = useDesignStore((s) => s.resolvedStageInfo);
  const resolvedAgentSummaries = useDesignStore((s) => s.resolvedAgentSummaries);
  const meta = useDesignStore((s) => s.meta);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const showDepEdges = useDesignStore((s) => s.showDepEdges);
  const showWireEdges = useDesignStore((s) => s.showWireEdges);

  return useMemo(() => {
    if (stages.length === 0) return { nodes: [], edges: [] };

    // Build dep map for auto-layout
    const depMap = new Map<string, string[]>();
    for (const s of stages) {
      depMap.set(s.name, s.depends_on);
    }

    const depths = computeDepthsFromDepMap(depMap);
    const hasDeps = stages.some((s) => s.depends_on.length > 0);

    // Group by depth for fallback layout
    const depthGroups = new Map<number, string[]>();
    for (const s of stages) {
      const d = depths.get(s.name) ?? 0;
      const group = depthGroups.get(d);
      if (group) group.push(s.name);
      else depthGroups.set(d, [s.name]);
    }

    // Build stage lookup for height estimation
    const stageLookup = new Map<string, DesignStage>();
    for (const s of stages) stageLookup.set(s.name, s);

    // Compute auto-layout positions using actual estimated heights
    const autoPositions = new Map<string, { x: number; y: number }>();
    if (hasDeps) {
      const maxDepth = Math.max(...Array.from(depthGroups.keys()), 0);
      let xCursor = START_X;
      for (let d = 0; d <= maxDepth; d++) {
        const names = depthGroups.get(d) ?? [];
        // Compute total column height using per-node estimates
        let totalH = 0;
        for (const name of names) {
          const st = stageLookup.get(name);
          totalH += st ? estimateNodeHeight(st) : 70;
        }
        totalH += (names.length - 1) * GAP_Y;

        let yCursor = -totalH / 2;
        let maxW = 0;
        for (const name of names) {
          autoPositions.set(name, { x: xCursor, y: yCursor });
          const st = stageLookup.get(name);
          const h = st ? estimateNodeHeight(st) : 70;
          const w = st && st.agents.length > 1 ? STAGE_NODE_WIDTH : AGENT_NODE_WIDTH;
          maxW = Math.max(maxW, w);
          yCursor += h + GAP_Y;
        }
        xCursor += (maxW || STAGE_NODE_WIDTH) + GAP_X;
      }
    } else {
      // Sequential layout
      let xCursor = START_X;
      for (const s of stages) {
        autoPositions.set(s.name, { x: xCursor, y: 0 });
        const w = s.agents.length > 1 ? STAGE_NODE_WIDTH : AGENT_NODE_WIDTH;
        xCursor += w + GAP_X;
      }
    }

    // Pre-compute workflow output source names (output names that feed workflow outputs)
    const workflowOutputSourceSet = new Set<string>();
    for (const wo of meta.outputs) {
      if (wo.source) workflowOutputSourceSet.add(wo.source);
    }

    const nodes: Node[] = [];
    const edges: Edge[] = [];

    const stageMap = new Map<string, DesignStage>();
    for (const s of stages) stageMap.set(s.name, s);

    // Pre-compute loop-back target counts so we can assign distinct handle indices
    // when multiple stages loop back to the same target (avoids overlapping edges)
    const loopTargetCounters = new Map<string, number>();

    let colorIndex = 0;
    for (const s of stages) {
      const manual = nodePositions[s.name];
      const auto = autoPositions.get(s.name) ?? { x: 0, y: 0 };
      const pos = manual ?? auto;
      const stageColor = STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];
      colorIndex++;

      // Use resolved info from stage config, fall back to inline stage data
      const resolved = resolvedStageInfo[s.name];
      const agents = resolved ? resolved.agents : s.agents;
      const agentMode = resolved ? resolved.agentMode : s.agent_mode;
      const collaborationStrategy = resolved
        ? resolved.collaborationStrategy
        : s.collaboration_strategy;

      // Build agent summaries array
      const agentSummaries: ResolvedAgentSummary[] = [];
      let agentDetailsLoaded = agents.length === 0;
      if (agents.length > 0) {
        let loadedCount = 0;
        for (const agentName of agents) {
          const summary = resolvedAgentSummaries[agentName];
          if (summary) {
            agentSummaries.push(summary);
            loadedCount++;
          }
        }
        agentDetailsLoaded = loadedCount === agents.length;
      }

      // Build input-source map for this stage (merge inline + resolved)
      // Resolved inputs from stage YAML provide the base; workflow-level overrides on top
      const stageInputs: Record<string, { source: string }> = {};
      if (resolved?.inputs) {
        for (const [k, v] of Object.entries(resolved.inputs)) stageInputs[k] = v;
      }
      for (const [k, v] of Object.entries(s.inputs)) stageInputs[k] = v;

      // Compute which stage outputs feed workflow-level outputs
      const stageOutputNames = resolved ? resolved.outputs.map((o) => o.name) : [];
      const workflowOutputSources: string[] = [];
      for (const wo of meta.outputs) {
        // source format: "stage_name.output_name" or just "output_name"
        const src = wo.source;
        if (!src) continue;
        const dotIdx = src.lastIndexOf('.');
        if (dotIdx >= 0) {
          const srcStage = src.slice(0, dotIdx);
          const srcOutput = src.slice(dotIdx + 1);
          if (srcStage === s.name && stageOutputNames.includes(srcOutput)) {
            workflowOutputSources.push(srcOutput);
          }
        } else if (stageOutputNames.includes(src)) {
          // Bare source name (no stage prefix)
          workflowOutputSources.push(src);
        }
      }

      const data: DesignNodeData = {
        stageName: s.name,
        stageRef: s.stage_ref,
        dependsOn: s.depends_on,
        loopsBackTo: s.loops_back_to,
        maxLoops: s.max_loops,
        condition: s.condition,
        stageColor,
        inputCount: Object.keys(stageInputs).length,
        agentCount: agents.length,
        agents,
        agentMode,
        collaborationStrategy,
        inputNames: Object.keys(stageInputs),
        isRef: s.stage_ref != null,
        // Enriched fields — use merged inputs (resolved + workflow overrides)
        inputs: stageInputs,
        description: resolved?.description ?? s.description,
        timeoutSeconds: resolved?.timeoutSeconds ?? null,
        safetyMode: resolved?.safetyMode ?? null,
        outputs: resolved?.outputs
          ?? Object.entries(s.outputs).map(([name, type]) => ({ name, type, description: '' })),
        errorHandling: resolved?.errorHandling ?? null,
        leaderAgent: resolved?.leaderAgent ?? null,
        agentSummaries,
        agentDetailsLoaded,
        workflowOutputSources,
        // Expanded config — inline stages read from DesignStage, refs from resolvedStageInfo
        version: s.stage_ref == null ? s.version : (resolved?.version ?? ''),
        safetyDryRunFirst: s.stage_ref == null
          ? s.safety_dry_run_first : (resolved?.safetyDryRunFirst ?? false),
        safetyRequireApproval: s.stage_ref == null
          ? s.safety_require_approval : (resolved?.safetyRequireApproval ?? false),
        errorMinSuccessful: s.stage_ref == null
          ? s.error_min_successful_agents
          : (resolved?.errorHandling?.minSuccessfulAgents ?? 1),
        errorRetryFailed: s.stage_ref == null
          ? s.error_retry_failed_agents
          : (resolved?.errorHandling?.retryFailedAgents ?? false),
        errorMaxRetries: s.stage_ref == null
          ? s.error_max_agent_retries
          : (resolved?.errorHandling?.maxAgentRetries ?? 0),
        qualityGatesEnabled: s.stage_ref == null
          ? s.quality_gates_enabled : (resolved?.qualityGates?.enabled ?? false),
        qualityGatesMinConfidence: s.stage_ref == null
          ? s.quality_gates_min_confidence
          : (resolved?.qualityGates?.minConfidence ?? 0.7),
        qualityGatesMinFindings: s.stage_ref == null
          ? s.quality_gates_min_findings
          : (resolved?.qualityGates?.minFindings ?? 5),
        qualityGatesRequireCitations: s.stage_ref == null
          ? s.quality_gates_require_citations
          : (resolved?.qualityGates?.requireCitations ?? true),
        qualityGatesOnFailure: s.stage_ref == null
          ? s.quality_gates_on_failure
          : (resolved?.qualityGates?.onFailure ?? 'retry_stage'),
        qualityGatesMaxRetries: s.stage_ref == null
          ? s.quality_gates_max_retries
          : (resolved?.qualityGates?.maxRetries ?? 2),
        convergenceEnabled: s.stage_ref == null
          ? s.convergence_enabled : (resolved?.convergence?.enabled ?? false),
        convergenceMaxIterations: s.stage_ref == null
          ? s.convergence_max_iterations
          : (resolved?.convergence?.maxIterations ?? 5),
        convergenceSimilarityThreshold: s.stage_ref == null
          ? s.convergence_similarity_threshold
          : (resolved?.convergence?.similarityThreshold ?? 0.95),
        convergenceMethod: s.stage_ref == null
          ? s.convergence_method : (resolved?.convergence?.method ?? 'exact_hash'),
        collaborationMaxRounds: s.stage_ref == null
          ? s.collaboration_max_rounds
          : (resolved?.collaborationMaxRounds ?? 3),
        collaborationConvergenceThreshold: s.stage_ref == null
          ? s.collaboration_convergence_threshold
          : (resolved?.collaborationConvergenceThreshold ?? 0.8),
        collaborationDialogueMode: s.stage_ref == null
          ? s.collaboration_dialogue_mode
          : (resolved?.collaborationDialogueMode ?? false),
        // Note: ResolvedStageInfo does not carry round_budget or context_window_rounds;
        // fallback to defaults for referenced stages.
        collaborationRoundBudget: s.stage_ref == null
          ? s.collaboration_round_budget_usd : null,
        collaborationContextWindowRounds: s.stage_ref == null
          ? s.collaboration_context_window_rounds : 2,
        conflictStrategy: s.stage_ref == null
          ? s.conflict_strategy
          : (resolved?.conflictResolution?.strategy ?? ''),
        conflictMetrics: s.stage_ref == null
          ? s.conflict_metrics
          : (resolved?.conflictResolution?.metrics ?? ['confidence']),
        conflictAutoResolveThreshold: s.stage_ref == null
          ? s.conflict_auto_resolve_threshold
          : (resolved?.conflictResolution?.autoResolveThreshold ?? 0.85),
      };

      nodes.push({
        id: s.name,
        type: 'designStage',
        position: { x: pos.x, y: pos.y },
        data,
      });

      // Dependency edges (source → target) with data flow labels
      for (const dep of s.depends_on) {
        if (!stageMap.has(dep)) continue;

        // Find which inputs of this stage source from the dependency stage
        const dataKeys: string[] = [];
        for (const [inputKey, inputDef] of Object.entries(stageInputs)) {
          const src = inputDef.source;
          if (!src) continue;
          const dotIdx = src.indexOf('.');
          if (dotIdx >= 0) {
            const srcStage = src.slice(0, dotIdx);
            if (srcStage === dep) dataKeys.push(inputKey);
          }
        }

        const depConnected = !selectedStageName
          || dep === selectedStageName || s.name === selectedStageName;
        if (showDepEdges) edges.push({
          id: `dep|${dep}|${s.name}`,
          source: dep,
          target: s.name,
          sourceHandle: 'right',
          targetHandle: 'left',
          type: 'dataFlow',
          data: { dataKeys, isLoop: false, loopLabel: null },
          style: {
            stroke: EDGE_COLORS.dataFlow,
            strokeWidth: 2,
            opacity: depConnected ? 1 : 0.15,
          },
        });
      }

      // Loop-back edge: source always uses bottom-0 (each node has at most one loop-back),
      // target uses indexed handles when multiple loops arrive at the same node.
      if (s.loops_back_to && stageMap.has(s.loops_back_to)) {
        const loopLabel = s.max_loops ? `max ${s.max_loops}` : 'loop';
        const idx = loopTargetCounters.get(s.loops_back_to) ?? 0;
        loopTargetCounters.set(s.loops_back_to, idx + 1);
        const loopConnected = !selectedStageName
          || s.name === selectedStageName || s.loops_back_to === selectedStageName;
        edges.push({
          id: `loop|${s.name}|${s.loops_back_to}`,
          source: s.name,
          target: s.loops_back_to,
          sourceHandle: 'bottom-0',
          targetHandle: `top-${idx}`,
          type: 'dataFlow',
          data: { dataKeys: [], isLoop: true, loopLabel },
          style: {
            stroke: EDGE_COLORS.loopBack,
            strokeWidth: 2.5,
            strokeDasharray: '8 4',
            opacity: loopConnected ? 1 : 0.15,
          },
        });
      }
    }

    // --- Data wire edges ---
    // Always show wires so the data flow is visible on first load.
    for (const s of stages) {
      const resolved = resolvedStageInfo[s.name];
      const mergedInputs: Record<string, { source: string }> = {};
      if (resolved?.inputs) {
        for (const [k, v] of Object.entries(resolved.inputs)) mergedInputs[k] = v;
      }
      for (const [k, v] of Object.entries(s.inputs)) mergedInputs[k] = v;

      for (const [inputName, inputDef] of Object.entries(mergedInputs)) {
        const src = inputDef.source;
        if (!src) continue;
        const dotIdx = src.indexOf('.');
        if (dotIdx < 0) continue;
        const srcStage = src.slice(0, dotIdx);
        if (srcStage === 'workflow' || !stageMap.has(srcStage)) continue;

        const remainder = src.slice(dotIdx + 1);
        const srcField = remainder.startsWith('structured.')
          ? remainder.slice('structured.'.length)
          : remainder;

        if (showWireEdges) edges.push({
          id: `wire|${srcStage}|${srcField}|${s.name}|${inputName}`,
          source: srcStage,
          target: s.name,
          sourceHandle: `out:${srcField}`,
          targetHandle: `in:${inputName}`,
          type: 'dataWire',
          style: { stroke: EDGE_COLORS.dataWire, strokeWidth: 1.5 },
        });
      }
    }

    return { nodes, edges };
  }, [stages, nodePositions, resolvedStageInfo, resolvedAgentSummaries, meta, selectedStageName, showDepEdges, showWireEdges]);
}

/**
 * Re-derive auto-layout positions (ignoring manual positions).
 * Used by the "auto-layout" reset button.
 */
export function computeAutoPositions(
  stages: DesignStage[],
): Record<string, { x: number; y: number }> {
  const depMap = new Map<string, string[]>();
  for (const s of stages) depMap.set(s.name, s.depends_on);

  const depths = computeDepthsFromDepMap(depMap);
  const hasDeps = stages.some((s) => s.depends_on.length > 0);

  const depthGroups = new Map<number, string[]>();
  for (const s of stages) {
    const d = depths.get(s.name) ?? 0;
    const group = depthGroups.get(d);
    if (group) group.push(s.name);
    else depthGroups.set(d, [s.name]);
  }

  const result: Record<string, { x: number; y: number }> = {};

  const stageLookup = new Map<string, DesignStage>();
  for (const s of stages) stageLookup.set(s.name, s);

  if (hasDeps) {
    const maxDepth = Math.max(...Array.from(depthGroups.keys()), 0);
    let xCursor = START_X;
    for (let d = 0; d <= maxDepth; d++) {
      const names = depthGroups.get(d) ?? [];
      let totalH = 0;
      for (const name of names) {
        const st = stageLookup.get(name);
        totalH += st ? estimateNodeHeight(st) : 70;
      }
      totalH += (names.length - 1) * GAP_Y;
      let yCursor = -totalH / 2;
      let maxW = 0;
      for (const name of names) {
        result[name] = { x: xCursor, y: yCursor };
        const st = stageLookup.get(name);
        const h = st ? estimateNodeHeight(st) : 70;
        const w = st && st.agents.length > 1 ? STAGE_NODE_WIDTH : AGENT_NODE_WIDTH;
        maxW = Math.max(maxW, w);
        yCursor += h + GAP_Y;
      }
      xCursor += (maxW || STAGE_NODE_WIDTH) + GAP_X;
    }
  } else {
    let xCursor = START_X;
    for (const s of stages) {
      result[s.name] = { x: xCursor, y: 0 };
      const w = s.agents.length > 1 ? STAGE_NODE_WIDTH : AGENT_NODE_WIDTH;
      xCursor += w + GAP_X;
    }
  }

  return result;
}
