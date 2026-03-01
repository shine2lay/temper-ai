/**
 * Information-dense stage node for the Studio canvas.
 * Primary information surface — shows stage config, agent details, I/O wiring,
 * collaboration patterns, and execution strategy at a glance.
 */
import { useState, type ReactNode } from 'react';
import { Handle, Position, useStore } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { useDesignStore, type ResolvedAgentSummary } from '@/store/designStore';
import type { DesignNodeData } from '@/hooks/useDesignElements';
import { InlineEdit, InlineSelect, InlineToggle } from './InlineEdit';

/* ---------- Shared constants ---------- */

const MAX_TOOL_NAMES_SHOWN = 3;
const DEFAULT_TEMPERATURE = 0.7;
const MAX_PROMPT_INPUTS_SHOWN = 4;

/** Parse numeric value — returns `def` only for null/empty/NaN, NOT for 0. */
function numOrDefault(v: string | number | null, def: number): number {
  if (v == null || v === '') return def;
  const n = Number(v);
  return isNaN(n) ? def : n;
}

/* ---------- Inline-edit option constants ---------- */

const SAFETY_MODE_OPTIONS = [
  { value: 'execute', label: 'execute' },
  { value: 'monitor', label: 'monitor' },
  { value: 'audit', label: 'audit' },
];

const AGENT_FAILURE_OPTIONS = [
  { value: 'continue_with_remaining', label: 'continue' },
  { value: 'halt', label: 'halt' },
  { value: 'retry', label: 'retry' },
];

const GATE_FAILURE_OPTIONS = [
  { value: 'retry_stage', label: 'retry' },
  { value: 'halt', label: 'halt' },
  { value: 'skip', label: 'skip' },
  { value: 'continue', label: 'continue' },
];

const CONVERGENCE_METHOD_OPTIONS = [
  { value: 'exact_hash', label: 'exact_hash' },
  { value: 'cosine_similarity', label: 'cosine' },
  { value: 'levenshtein', label: 'levenshtein' },
];

/* ---------- NodeField — stopPropagation wrapper for inline edits ---------- */

function NodeField({ children, label }: { children: ReactNode; label?: string }) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <div className="flex items-center gap-1.5 min-w-0" onClick={stop} onKeyDown={stop}>
      {label && (
        <span className="text-[8px] text-temper-text-dim shrink-0 w-14">{label}</span>
      )}
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

/* ---------- NodeSection — lightweight collapsible ---------- */

function NodeSection({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-t border-temper-border/50">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className="w-full px-3 py-1.5 flex items-center gap-1.5 text-left hover:bg-white/[0.02] transition-colors"
      >
        <span className="text-[10px] text-temper-text-dim w-3">
          {open ? '\u25BC' : '\u25B6'}
        </span>
        <span className="text-[10px] font-semibold text-temper-text-muted flex-1">
          {title}
        </span>
        {badge && (
          <span className="text-[9px] text-temper-text-dim">{badge}</span>
        )}
      </button>
      {open && <div className="px-3 pb-2">{children}</div>}
    </div>
  );
}

/* ---------- CapabilityChips ---------- */

function CapabilityChips({
  summary,
  compact,
}: {
  summary: ResolvedAgentSummary;
  compact?: boolean;
}) {
  const chips: { label: string; color: string }[] = [];

  if (summary.memoryEnabled) {
    const label = compact ? 'mem' : `memory${summary.memoryType ? ':' + summary.memoryType : ''}`;
    chips.push({ label, color: 'bg-cyan-900/30 text-cyan-400' });
  }
  if (summary.reasoningEnabled) {
    chips.push({ label: compact ? 'rsn' : 'reasoning', color: 'bg-indigo-900/30 text-indigo-400' });
  }
  if (summary.persistent) {
    chips.push({ label: compact ? 'pers' : 'persistent', color: 'bg-teal-900/30 text-teal-400' });
  }
  if (summary.hasPreCommands) {
    const label = compact ? `pre:${summary.preCommandCount}` : `${summary.preCommandCount} pre-cmd`;
    chips.push({ label, color: 'bg-orange-900/30 text-orange-400' });
  }
  if (summary.hasOutputSchema) {
    chips.push({ label: compact ? 'sch' : 'schema', color: 'bg-emerald-900/30 text-emerald-400' });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex items-center gap-0.5 flex-wrap">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className={`text-[7px] px-0.5 py-px rounded ${chip.color} shrink-0`}
        >
          {chip.label}
        </span>
      ))}
    </div>
  );
}

/* ---------- AgentIOSection ---------- */

function AgentIOSection({ summary }: { summary: ResolvedAgentSummary }) {
  const hasInputs = summary.promptInputs.length > 0;
  const hasOutputs = summary.outputSchemaFields.length > 0;
  if (!hasInputs && !hasOutputs) return null;

  const visibleInputs = summary.promptInputs.slice(0, MAX_PROMPT_INPUTS_SHOWN);
  const extraInputCount = summary.promptInputs.length - MAX_PROMPT_INPUTS_SHOWN;

  return (
    <div className="border-t border-temper-border/30 pt-1 mt-1">
      {hasInputs && (
        <div className="text-[8px] text-temper-text-dim truncate">
          <span className="text-blue-400/70 font-medium">IN</span>{' '}
          <span className="text-temper-text-muted">
            {visibleInputs.join(', ')}
            {extraInputCount > 0 ? ` +${extraInputCount} more` : ''}
          </span>
        </div>
      )}
      <div className="text-[8px] text-temper-text-dim truncate">
        <span className="text-emerald-400/70 font-medium">OUT</span>{' '}
        <span className="text-temper-text-muted">
          {hasOutputs
            ? summary.outputSchemaFields.map((f) => `${f.name}:${f.type}`).join(', ')
            : 'text'}
        </span>
      </div>
    </div>
  );
}

/* ---------- AgentMiniCard ---------- */

function AgentMiniCard({
  summary,
  isLeader,
  compact,
  onSelect,
}: {
  summary: ResolvedAgentSummary;
  isLeader: boolean;
  compact?: boolean;
  onSelect: () => void;
}) {
  const visibleTools = summary.toolNames.slice(0, MAX_TOOL_NAMES_SHOWN);
  const showTemp = summary.temperature !== DEFAULT_TEMPERATURE;

  if (compact) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        className="text-left rounded border border-temper-border/50 bg-temper-surface/50 hover:border-temper-accent/40 hover:bg-temper-accent/5 transition-all duration-150 hover:shadow-md px-1.5 py-1 min-w-0"
        title={`${summary.name} — ${summary.provider}/${summary.model}`}
      >
        <div className="flex items-center gap-1 min-w-0">
          {isLeader && (
            <span className="text-[10px] text-yellow-400 shrink-0">★</span>
          )}
          <span className="text-[9px] font-medium text-temper-text truncate">
            {summary.name}
          </span>
          {summary.type !== 'standard' && (
            <span className="text-[7px] px-0.5 py-px rounded bg-violet-900/30 text-violet-400 shrink-0">
              {summary.type}
            </span>
          )}
        </div>
        <div className="text-[8px] text-temper-text-dim truncate mt-0.5">
          {summary.provider}/{summary.model}
          {showTemp ? ` T=${summary.temperature}` : ''}
          {summary.toolCount > 0 ? ` \u00B7 ${summary.toolCount}t` : ''}
        </div>
        <CapabilityChips summary={summary} compact />
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      className="text-left rounded border border-temper-border/50 bg-temper-surface/50 hover:border-temper-accent/40 hover:bg-temper-accent/5 transition-all duration-150 hover:shadow-md p-1.5 min-w-0"
      title={`Edit agent: ${summary.name}`}
    >
      {/* Row 1: Name + type badge + version */}
      <div className="flex items-center gap-1 min-w-0">
        {isLeader && (
          <span className="text-[10px] text-yellow-400 shrink-0" title="Leader agent">★</span>
        )}
        <span className="text-[10px] font-medium text-temper-text truncate flex-1">
          {summary.name}
        </span>
        {summary.type !== 'standard' && (
          <span className="text-[8px] px-1 py-px rounded bg-violet-900/30 text-violet-400 shrink-0">
            {summary.type}
          </span>
        )}
        {summary.version && (
          <span className="text-[8px] px-1 py-px rounded bg-temper-surface text-temper-text-dim shrink-0">
            v{summary.version}
          </span>
        )}
      </div>

      {/* Row 2: Description (1 line, truncated) */}
      {summary.description && (
        <div className="text-[8px] text-temper-text-dim truncate mt-0.5" title={summary.description}>
          {summary.description}
        </div>
      )}

      {/* Row 3: Provider/model + temp + max_tokens + timeout + risk */}
      <div className="flex items-center gap-1 mt-0.5 min-w-0 flex-wrap">
        <span className="text-[9px] text-temper-text-dim truncate">
          {summary.provider}/{summary.model}
        </span>
        {showTemp && (
          <span className="text-[9px] text-temper-text-dim shrink-0">T={summary.temperature}</span>
        )}
        {summary.maxTokens > 0 && (
          <span className="text-[9px] text-temper-text-dim shrink-0">{summary.maxTokens}tk</span>
        )}
        {summary.timeoutSeconds > 0 && (
          <span className="text-[9px] text-temper-text-dim shrink-0">{summary.timeoutSeconds}s</span>
        )}
        {summary.riskLevel && (
          <span className="text-[8px] px-0.5 py-px rounded bg-amber-900/30 text-amber-400 shrink-0">
            risk:{summary.riskLevel}
          </span>
        )}
      </div>

      {/* Row 4: Tools */}
      <div className="flex items-center gap-1 mt-0.5 min-w-0">
        <span className="text-[9px] text-temper-text-dim shrink-0">
          {summary.toolCount} tool{summary.toolCount !== 1 ? 's' : ''}
        </span>
        {visibleTools.length > 0 && (
          <span className="text-[8px] text-temper-text-dim truncate">
            {visibleTools.join(', ')}
            {summary.toolCount > MAX_TOOL_NAMES_SHOWN ? ', \u2026' : ''}
          </span>
        )}
      </div>

      {/* Row 5: Capability chips */}
      <CapabilityChips summary={summary} />

      {/* Row 6: Per-agent I/O */}
      <AgentIOSection summary={summary} />
    </button>
  );
}

function AgentSkeleton() {
  return (
    <div className="rounded border border-temper-border/30 bg-temper-surface/30 p-1.5 animate-pulse">
      <div className="h-2.5 bg-temper-border/30 rounded w-3/4 mb-1" />
      <div className="h-2 bg-temper-border/20 rounded w-1/2" />
    </div>
  );
}

/* ---------- Collaboration Layouts ---------- */

/** SVG arrow connector line */
function ArrowLine({ className }: { className?: string }) {
  return (
    <span className={`text-[10px] text-temper-text-dim shrink-0 ${className ?? ''}`}>
      {'\u2192'}
    </span>
  );
}

/** SVG down-arrow for leader convergence */
function DownArrow() {
  return (
    <div className="flex justify-center py-0.5">
      <svg width="40" height="14" viewBox="0 0 40 14" className="text-yellow-400/60">
        <path d="M8 0 L20 10 L32 0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="12" r="2" fill="currentColor" />
      </svg>
    </div>
  );
}

/**
 * Leader strategy layout:
 * Perspective agents in a row at top → convergence arrows → leader card at bottom
 */
function LeaderLayout({
  agents,
  leaderAgent,
  agentSummaries,
  isCompact,
  selectAgent,
}: {
  agents: string[];
  leaderAgent: string;
  agentSummaries: ResolvedAgentSummary[];
  isCompact?: boolean;
  selectAgent: (name: string) => void;
}) {
  const perspectives = agents.filter((n) => n !== leaderAgent);
  const leader = agentSummaries.find((s) => s.name === leaderAgent);
  const perspectiveSummaries = perspectives.map((n) => agentSummaries.find((s) => s.name === n));

  return (
    <div className="flex flex-col gap-0">
      {/* Mode label */}
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[8px] px-1 py-px rounded bg-blue-900/30 text-blue-400">
          leader
        </span>
        <span className="text-[8px] text-temper-text-dim">
          {perspectives.length} perspective{perspectives.length !== 1 ? 's' : ''} {'\u2192'} 1 decider
        </span>
      </div>

      {/* Perspective agents */}
      <div className="flex flex-col gap-1">
        {perspectives.map((name) => {
          const summary = perspectiveSummaries.find((s) => s?.name === name);
          return summary ? (
            <AgentMiniCard
              key={name}
              summary={summary}
              isLeader={false}
              compact={isCompact}
              onSelect={() => selectAgent(name)}
            />
          ) : (
            <AgentSkeleton key={name} />
          );
        })}
      </div>

      {/* Convergence arrows */}
      <DownArrow />

      {/* Leader card — full width, highlighted */}
      {leader ? (
        <div className="border border-yellow-400/30 rounded bg-yellow-900/10">
          <AgentMiniCard
            summary={leader}
            isLeader
            compact={isCompact}
            onSelect={() => selectAgent(leaderAgent)}
          />
        </div>
      ) : (
        <AgentSkeleton />
      )}
    </div>
  );
}

/**
 * Sequential strategy layout:
 * Agents chained left-to-right with arrows between them
 */
function SequentialLayout({
  agents,
  agentSummaries,
  isCompact,
  selectAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  isCompact?: boolean;
  selectAgent: (name: string) => void;
}) {
  return (
    <div className="flex flex-col gap-0">
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[8px] px-1 py-px rounded bg-amber-900/30 text-amber-400">
          sequential
        </span>
        <span className="text-[8px] text-temper-text-dim">
          {agents.length} agents in chain
        </span>
      </div>

      <div className="flex flex-col gap-1">
        {agents.map((name, i) => {
          const summary = agentSummaries.find((s) => s.name === name);
          return (
            <div key={name} className="flex items-center gap-1 min-w-0">
              {i > 0 && <ArrowLine />}
              <div className="flex-1 min-w-0">
                {summary ? (
                  <AgentMiniCard
                    summary={summary}
                    isLeader={false}
                    compact={isCompact}
                    onSelect={() => selectAgent(name)}
                  />
                ) : (
                  <AgentSkeleton />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Consensus / debate / round_robin layout:
 * Agents in a ring-style layout with bidirectional indicators
 */
function ConsensusLayout({
  agents,
  agentSummaries,
  collaborationStrategy,
  isCompact,
  selectAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  collaborationStrategy: string;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
}) {
  // Determine the display label
  let label = collaborationStrategy;
  let description = '';
  if (collaborationStrategy === 'consensus') {
    description = 'vote to converge';
  } else if (collaborationStrategy === 'debate' || collaborationStrategy === 'multi_round') {
    label = collaborationStrategy === 'multi_round' ? 'dialogue' : 'debate';
    description = 'multi-round exchange';
  } else if (collaborationStrategy === 'round_robin') {
    description = 'rotate turns';
  }

  return (
    <div className="flex flex-col gap-0">
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[8px] px-1 py-px rounded bg-purple-900/30 text-purple-400">
          {label}
        </span>
        {description && (
          <span className="text-[8px] text-temper-text-dim">{description}</span>
        )}
      </div>

      {/* Agents in a ring-suggestive layout: grid with connecting lines */}
      <div className="relative">
        <div className="grid grid-cols-2 gap-1">
          {agents.map((name) => {
            const summary = agentSummaries.find((s) => s.name === name);
            return summary ? (
              <AgentMiniCard
                key={name}
                summary={summary}
                isLeader={false}
                compact={isCompact}
                onSelect={() => selectAgent(name)}
              />
            ) : (
              <AgentSkeleton key={name} />
            );
          })}
        </div>

        {/* Circular exchange indicator overlay */}
        {agents.length >= 2 && (
          <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
            <svg width="36" height="36" viewBox="0 0 36 36" className="text-purple-400/30">
              <circle cx="18" cy="18" r="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
              {/* Rotation arrows */}
              <path d="M28 12 L32 16 L28 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M8 24 L4 20 L8 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Parallel / independent layout:
 * Fan-out → agents in parallel → fan-in
 */
function ParallelLayout({
  agents,
  agentSummaries,
  agentMode,
  isCompact,
  selectAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  agentMode: string;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
}) {
  const isParallel = agentMode === 'parallel';

  return (
    <div className="flex flex-col gap-0">
      {isParallel && (
        <div className="flex items-center gap-1 mb-1">
          <span className="text-[8px] px-1 py-px rounded bg-amber-900/30 text-amber-400">
            parallel
          </span>
          <span className="text-[8px] text-temper-text-dim">
            {agents.length} agents concurrent
          </span>
        </div>
      )}

      <div className="flex items-stretch gap-0">
        {/* Fan-out bar */}
        {isParallel && agents.length > 1 && (
          <div className="flex items-center shrink-0 mr-1">
            <svg width="8" height={agents.length * 32} viewBox={`0 0 8 ${agents.length * 32}`} className="text-amber-400/40">
              <line x1="2" y1="0" x2="2" y2={agents.length * 32} stroke="currentColor" strokeWidth="1.5" />
              {agents.map((_, i) => (
                <line key={i} x1="2" y1={i * 32 + 16} x2="8" y2={i * 32 + 16} stroke="currentColor" strokeWidth="1" />
              ))}
            </svg>
          </div>
        )}

        {/* Agent cards stacked vertically */}
        <div className="flex-1 flex flex-col gap-1 min-w-0">
          {agents.map((name) => {
            const summary = agentSummaries.find((s) => s.name === name);
            return summary ? (
              <AgentMiniCard
                key={name}
                summary={summary}
                isLeader={false}
                compact={isCompact}
                onSelect={() => selectAgent(name)}
              />
            ) : (
              <AgentSkeleton key={name} />
            );
          })}
        </div>

        {/* Fan-in bar */}
        {isParallel && agents.length > 1 && (
          <div className="flex items-center shrink-0 ml-1">
            <svg width="8" height={agents.length * 32} viewBox={`0 0 8 ${agents.length * 32}`} className="text-amber-400/40">
              <line x1="6" y1="0" x2="6" y2={agents.length * 32} stroke="currentColor" strokeWidth="1.5" />
              {agents.map((_, i) => (
                <line key={i} x1="0" y1={i * 32 + 16} x2="6" y2={i * 32 + 16} stroke="currentColor" strokeWidth="1" />
              ))}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Picks the right collaboration layout based on strategy + mode + leader.
 */
function CollaborationLayout({
  agents,
  agentSummaries,
  agentDetailsLoaded,
  agentMode,
  collaborationStrategy,
  leaderAgent,
  isCompact,
  selectAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  agentDetailsLoaded: boolean;
  agentMode: string;
  collaborationStrategy: string;
  leaderAgent: string | null;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
}) {
  // If agent details haven't loaded, show skeletons in a grid
  if (!agentDetailsLoaded) {
    return (
      <div className="flex flex-col gap-1">
        {agents.map((name) => {
          const summary = agentSummaries.find((s) => s.name === name);
          return summary ? (
            <AgentMiniCard
              key={name}
              summary={summary}
              isLeader={name === leaderAgent}
              compact={isCompact}
              onSelect={() => selectAgent(name)}
            />
          ) : (
            <AgentSkeleton key={name} />
          );
        })}
      </div>
    );
  }

  // Leader strategy with a known leader
  if (leaderAgent && (collaborationStrategy === 'leader' || agents.includes(leaderAgent))) {
    return (
      <LeaderLayout
        agents={agents}
        leaderAgent={leaderAgent}
        agentSummaries={agentSummaries}
        isCompact={isCompact}
        selectAgent={selectAgent}
      />
    );
  }

  // Sequential mode or strategy
  if (agentMode === 'sequential' && collaborationStrategy === 'sequential') {
    return (
      <SequentialLayout
        agents={agents}
        agentSummaries={agentSummaries}
        isCompact={isCompact}
        selectAgent={selectAgent}
      />
    );
  }

  // Consensus / debate / multi_round / round_robin
  if (['consensus', 'debate', 'multi_round', 'round_robin'].includes(collaborationStrategy)) {
    return (
      <ConsensusLayout
        agents={agents}
        agentSummaries={agentSummaries}
        collaborationStrategy={collaborationStrategy}
        isCompact={isCompact}
        selectAgent={selectAgent}
      />
    );
  }

  // Parallel mode (no special collab) or independent — fan-out/fan-in
  return (
    <ParallelLayout
      agents={agents}
      agentSummaries={agentSummaries}
      agentMode={agentMode}
      isCompact={isCompact}
      selectAgent={selectAgent}
    />
  );
}

/* ---------- Main node component ---------- */

export function DesignStageNode({ data }: NodeProps) {
  const {
    stageName,
    stageRef,
    dependsOn,
    loopsBackTo,
    maxLoops,
    stageColor,
    agentCount,
    agents,
    agentMode,
    collaborationStrategy,
    condition,
    isRef,
    inputs,
    description,
    timeoutSeconds,
    safetyMode,
    outputs,
    errorHandling,
    leaderAgent,
    agentSummaries,
    agentDetailsLoaded,
    workflowOutputSources,
    // Expanded config fields
    version,
    safetyDryRunFirst,
    safetyRequireApproval,
    errorMinSuccessful,
    errorRetryFailed,
    errorMaxRetries,
    qualityGatesEnabled,
    qualityGatesMinConfidence,
    qualityGatesMinFindings,
    qualityGatesRequireCitations,
    qualityGatesOnFailure,
    qualityGatesMaxRetries,
    convergenceEnabled,
    convergenceMaxIterations,
    convergenceSimilarityThreshold,
    convergenceMethod,
    collaborationMaxRounds,
    collaborationConvergenceThreshold,
    collaborationDialogueMode,
    collaborationRoundBudget,
    collaborationContextWindowRounds,
    conflictStrategy,
    conflictMetrics,
    conflictAutoResolveThreshold,
  } = data as DesignNodeData;

  const selectStage = useDesignStore((s) => s.selectStage);
  const selectAgent = useDesignStore((s) => s.selectAgent);
  const removeStage = useDesignStore((s) => s.removeStage);
  const updateStage = useDesignStore((s) => s.updateStage);
  const renameStage = useDesignStore((s) => s.renameStage);
  const allStages = useDesignStore((s) => s.stages);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const isSelected = selectedStageName === stageName;
  const zoom = useStore((s) => s.transform[2]);
  const isCompact = zoom < 0.6;

  const otherStageNames = allStages
    .filter((s) => s.name !== stageName)
    .map((s) => s.name);

  const inputEntries = Object.entries(inputs);

  const refLabel = stageRef
    ? stageRef.replace(/^.*\//, '').replace(/\.yaml$/, '')
    : null;

  return (
    <div
      className={`rounded-lg cursor-pointer group relative ${isSelected ? 'ring-2 ring-temper-accent/40 shadow-lg shadow-temper-accent/10' : ''}`}
      style={{
        border: `2px solid ${isSelected ? stageColor : 'var(--color-temper-border)'}`,
        borderTopColor: stageColor,
        borderTopWidth: '3px',
        borderTopStyle: 'solid',
        backgroundColor: 'var(--color-temper-panel)',
        width: '380px',
      }}
      role="button"
      tabIndex={0}
      aria-label={`Stage: ${stageName}`}
      onClick={() => selectStage(stageName)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectStage(stageName);
        }
      }}
    >
      {/* Target handle (left) */}
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        className="!bg-temper-border !w-2.5 !h-2.5"
      />

      {/* Delete button — visible on hover */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          removeStage(stageName);
        }}
        className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-600 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
        aria-label={`Remove stage ${stageName}`}
      >
        &times;
      </button>

      {/* ---- Header ---- */}
      <div className="px-3 pt-2 pb-1">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0"
            style={{ backgroundColor: stageColor }}
          />
          <div className="flex-1 min-w-0" onClick={(e) => e.stopPropagation()}>
            <InlineEdit
              value={stageName}
              onChange={(v) => {
                const newName = String(v ?? '').replace(/[^a-zA-Z0-9_-]/g, '');
                if (newName && newName !== stageName) renameStage(stageName, newName);
              }}
              readOnly={isRef}
              className="text-sm font-bold"
              placeholder="stage_name"
            />
          </div>
          <span
            className="text-[10px] text-temper-text-dim shrink-0"
            title={isRef ? `Ref: ${stageRef}` : 'Inline stage'}
          >
            {isRef ? '[ref]' : '[\u270E]'}
          </span>
          {version && (
            <span className="text-[9px] text-temper-text-dim shrink-0">
              v{version}
            </span>
          )}
        </div>
        <div className="mt-0.5" onClick={(e) => e.stopPropagation()}>
          <InlineEdit
            value={description}
            onChange={(v) => updateStage(stageName, { description: String(v ?? '') })}
            className="text-[10px] text-temper-text-muted w-full"
            emptyLabel="no description"
            placeholder="Stage description..."
          />
        </div>
        {refLabel && (
          <div className="text-[9px] text-temper-text-dim mt-0.5">
            ref: {refLabel}
          </div>
        )}
      </div>

      {/* ---- Agents section with collaboration layout ---- */}
      <NodeSection
        title="Agents"
        badge={agentCount > 0 ? `${agentCount}` : undefined}
        defaultOpen
      >
        {agentCount > 0 ? (
          <CollaborationLayout
            agents={agents}
            agentSummaries={agentSummaries}
            agentDetailsLoaded={agentDetailsLoaded}
            agentMode={agentMode}
            collaborationStrategy={collaborationStrategy}
            leaderAgent={leaderAgent}
            isCompact={isCompact}
            selectAgent={selectAgent}
          />
        ) : (
          <div className="border border-dashed border-temper-border/50 rounded px-2 py-1.5 text-center">
            <span className="text-[10px] text-temper-text-dim">
              No agents assigned — click to add
            </span>
          </div>
        )}
      </NodeSection>

      {/* ---- I/O section ---- */}
      {(inputEntries.length > 0 || outputs.length > 0) && (
        <NodeSection
          title="I/O"
          badge={`${inputEntries.length} in / ${outputs.length} out`}
          defaultOpen
        >
          {inputEntries.length > 0 && (
            <div className="flex flex-col gap-0.5">
              {inputEntries.map(([key, val]) => (
                <div
                  key={key}
                  className="text-[9px] text-temper-text-muted truncate"
                  title={`${key} \u2190 ${val.source}`}
                >
                  <span className="text-blue-400/70">IN</span>{' '}
                  <span className="text-temper-text">{key}</span>{' '}
                  <span className="text-temper-text-dim">&larr; {val.source}</span>
                </div>
              ))}
            </div>
          )}
          {outputs.length > 0 && (
            <div className="flex flex-col gap-0.5 mt-1">
              {outputs.map((out) => {
                const isWfOutput = workflowOutputSources.includes(out.name);
                return (
                  <div
                    key={out.name}
                    className="text-[9px] text-temper-text-muted truncate"
                    title={out.description || out.name}
                  >
                    <span className="text-emerald-400/70">OUT</span>{' '}
                    <span className="text-temper-text">{out.name}</span>{' '}
                    <span className="text-temper-text-dim">({out.type})</span>
                    {out.description && (
                      <span className="text-temper-text-dim"> &mdash; {out.description}</span>
                    )}
                    {isWfOutput && (
                      <span className="text-[8px] ml-1 px-1 py-px rounded bg-emerald-900/30 text-emerald-400">
                        WF
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </NodeSection>
      )}

      {/* ---- Config section (collapsed by default) — inline editable ---- */}
      <NodeSection title="Config" defaultOpen={false}>
        <div className="flex flex-col gap-1.5">
          {/* Row 1: timeout + safety mode */}
          <div className="flex items-center gap-3">
            <NodeField label="timeout">
              <InlineEdit
                value={timeoutSeconds}
                onChange={(v) => updateStage(stageName, { timeout_seconds: numOrDefault(v, 600) })}
                type="number"
                className="text-[10px] w-12"
                min={0}
              />
              <span className="text-[8px] text-temper-text-dim ml-0.5">s</span>
            </NodeField>
            <NodeField label="safety">
              <InlineSelect
                value={safetyMode ?? 'execute'}
                options={SAFETY_MODE_OPTIONS}
                onChange={(v) => updateStage(stageName, { safety_mode: v })}
                className="text-[10px]"
              />
            </NodeField>
          </div>
          {/* Row 2: dry-run + approval */}
          <div className="flex items-center gap-3">
            <NodeField label="dry-run">
              <InlineToggle
                value={safetyDryRunFirst}
                onChange={(v) => updateStage(stageName, { safety_dry_run_first: v })}
                className="text-[10px]"
              />
            </NodeField>
            <NodeField label="approval">
              <InlineToggle
                value={safetyRequireApproval}
                onChange={(v) => updateStage(stageName, { safety_require_approval: v })}
                className="text-[10px]"
              />
            </NodeField>
          </div>
          {/* Row 3: error handling */}
          <div className="flex items-center gap-3">
            <NodeField label="on_fail">
              <InlineSelect
                value={errorHandling?.onAgentFailure ?? 'continue_with_remaining'}
                options={AGENT_FAILURE_OPTIONS}
                onChange={(v) => updateStage(stageName, { error_on_agent_failure: v })}
                className="text-[10px]"
              />
            </NodeField>
            <NodeField label="min ok">
              <InlineEdit
                value={errorMinSuccessful}
                onChange={(v) => updateStage(stageName, { error_min_successful_agents: numOrDefault(v, 1) })}
                type="number"
                className="text-[10px] w-8"
                min={0}
              />
            </NodeField>
          </div>
          <div className="flex items-center gap-3">
            <NodeField label="retry">
              <InlineToggle
                value={errorRetryFailed}
                onChange={(v) => updateStage(stageName, { error_retry_failed_agents: v })}
                className="text-[10px]"
              />
            </NodeField>
            {errorRetryFailed && (
              <NodeField label="x">
                <InlineEdit
                  value={errorMaxRetries}
                  onChange={(v) => updateStage(stageName, { error_max_agent_retries: numOrDefault(v, 0) })}
                  type="number"
                  className="text-[10px] w-8"
                  min={0}
                />
              </NodeField>
            )}
          </div>
        </div>
      </NodeSection>

      {/* ---- Quality Gates (collapsed, conditional) ---- */}
      {(qualityGatesEnabled || !isRef) && (
        <NodeSection
          title="Quality Gates"
          badge={qualityGatesEnabled ? '\u2713' : undefined}
          defaultOpen={false}
        >
          <div className="flex flex-col gap-1.5">
            {!isRef && (
              <NodeField label="enabled">
                <InlineToggle
                  value={qualityGatesEnabled}
                  onChange={(v) => updateStage(stageName, { quality_gates_enabled: v })}
                  className="text-[10px]"
                />
              </NodeField>
            )}
            {qualityGatesEnabled && (
              <>
                <div className="flex items-center gap-3">
                  <NodeField label="conf \u2265">
                    <InlineEdit
                      value={qualityGatesMinConfidence}
                      onChange={(v) => updateStage(stageName, { quality_gates_min_confidence: numOrDefault(v, 0.7) })}
                      type="number"
                      className="text-[10px] w-10"
                      min={0} max={1} step={0.05}
                    />
                  </NodeField>
                  <NodeField label="finds \u2265">
                    <InlineEdit
                      value={qualityGatesMinFindings}
                      onChange={(v) => updateStage(stageName, { quality_gates_min_findings: numOrDefault(v, 0) })}
                      type="number"
                      className="text-[10px] w-8"
                      min={0}
                    />
                  </NodeField>
                </div>
                <div className="flex items-center gap-3">
                  <NodeField label="citations">
                    <InlineToggle
                      value={qualityGatesRequireCitations}
                      onChange={(v) => updateStage(stageName, { quality_gates_require_citations: v })}
                      className="text-[10px]"
                    />
                  </NodeField>
                  <NodeField label="on_fail">
                    <InlineSelect
                      value={qualityGatesOnFailure}
                      options={GATE_FAILURE_OPTIONS}
                      onChange={(v) => updateStage(stageName, { quality_gates_on_failure: v })}
                      className="text-[10px]"
                    />
                  </NodeField>
                </div>
                <NodeField label="retries">
                  <InlineEdit
                    value={qualityGatesMaxRetries}
                    onChange={(v) => updateStage(stageName, { quality_gates_max_retries: numOrDefault(v, 0) })}
                    type="number"
                    className="text-[10px] w-8"
                    min={0}
                  />
                </NodeField>
              </>
            )}
          </div>
        </NodeSection>
      )}

      {/* ---- Convergence (collapsed, conditional) ---- */}
      {(convergenceEnabled || !isRef) && (
        <NodeSection
          title="Convergence"
          badge={convergenceEnabled ? '\u2713' : undefined}
          defaultOpen={false}
        >
          <div className="flex flex-col gap-1.5">
            {!isRef && (
              <NodeField label="enabled">
                <InlineToggle
                  value={convergenceEnabled}
                  onChange={(v) => updateStage(stageName, { convergence_enabled: v })}
                  className="text-[10px]"
                />
              </NodeField>
            )}
            {convergenceEnabled && (
              <>
                <div className="flex items-center gap-3">
                  <NodeField label="method">
                    <InlineSelect
                      value={convergenceMethod}
                      options={CONVERGENCE_METHOD_OPTIONS}
                      onChange={(v) => updateStage(stageName, { convergence_method: v })}
                      className="text-[10px]"
                    />
                  </NodeField>
                  <NodeField label="max iter">
                    <InlineEdit
                      value={convergenceMaxIterations}
                      onChange={(v) => updateStage(stageName, { convergence_max_iterations: numOrDefault(v, 5) })}
                      type="number"
                      className="text-[10px] w-8"
                      min={1}
                    />
                  </NodeField>
                </div>
                <NodeField label="sim \u2265">
                  <InlineEdit
                    value={convergenceSimilarityThreshold}
                    onChange={(v) => updateStage(stageName, { convergence_similarity_threshold: numOrDefault(v, 0.95) })}
                    type="number"
                    className="text-[10px] w-10"
                    min={0} max={1} step={0.01}
                  />
                </NodeField>
              </>
            )}
          </div>
        </NodeSection>
      )}

      {/* ---- Collaboration Details (collapsed, multi-agent only) ---- */}
      {agentCount > 1 && (
        <NodeSection title="Collaboration" defaultOpen={false}>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-3">
              <NodeField label="rounds">
                <InlineEdit
                  value={collaborationMaxRounds}
                  onChange={(v) => updateStage(stageName, { collaboration_max_rounds: numOrDefault(v, 3) })}
                  type="number"
                  className="text-[10px] w-8"
                  min={1}
                />
              </NodeField>
              <NodeField label="conv thr">
                <InlineEdit
                  value={collaborationConvergenceThreshold}
                  onChange={(v) => updateStage(stageName, { collaboration_convergence_threshold: numOrDefault(v, 0.8) })}
                  type="number"
                  className="text-[10px] w-10"
                  min={0} max={1} step={0.05}
                />
              </NodeField>
            </div>
            <div className="flex items-center gap-3">
              <NodeField label="dialogue">
                <InlineToggle
                  value={collaborationDialogueMode}
                  onChange={(v) => updateStage(stageName, { collaboration_dialogue_mode: v })}
                  className="text-[10px]"
                />
              </NodeField>
              <NodeField label="ctx rnds">
                <InlineEdit
                  value={collaborationContextWindowRounds}
                  onChange={(v) => updateStage(stageName, { collaboration_context_window_rounds: numOrDefault(v, 2) })}
                  type="number"
                  className="text-[10px] w-8"
                  min={0}
                />
              </NodeField>
            </div>
            <NodeField label="budget $">
              <InlineEdit
                value={collaborationRoundBudget}
                onChange={(v) => updateStage(stageName, { collaboration_round_budget_usd: v != null && v !== '' ? Number(v) : null })}
                type="number"
                emptyLabel="none"
                className="text-[10px] w-14"
                min={0} step={0.01}
              />
            </NodeField>
          </div>
        </NodeSection>
      )}

      {/* ---- Conflict Resolution (collapsed, conditional) ---- */}
      {(conflictStrategy || !isRef) && (
        <NodeSection title="Conflict" defaultOpen={false}>
          <div className="flex flex-col gap-1.5">
            <NodeField label="strategy">
              <InlineEdit
                value={conflictStrategy}
                onChange={(v) => updateStage(stageName, { conflict_strategy: String(v ?? '') })}
                emptyLabel="default"
                className="text-[10px]"
              />
            </NodeField>
            <NodeField label="auto \u2265">
              <InlineEdit
                value={conflictAutoResolveThreshold}
                onChange={(v) => updateStage(stageName, { conflict_auto_resolve_threshold: numOrDefault(v, 0.85) })}
                type="number"
                className="text-[10px] w-10"
                min={0} max={1} step={0.05}
              />
            </NodeField>
            {conflictMetrics.length > 0 && (
              <div className="text-[9px] text-temper-text-dim truncate">
                metrics: {conflictMetrics.join(', ')}
              </div>
            )}
          </div>
        </NodeSection>
      )}

      {/* ---- Footer: dependencies + condition + loop ---- */}
      {(dependsOn.length > 0 || condition != null || loopsBackTo || !isRef) && (
        <div className="border-t border-temper-border/50 px-3 py-1.5 flex flex-col gap-1">
          {dependsOn.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              {dependsOn.map((dep) => (
                <span
                  key={dep}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-muted"
                >
                  &larr; {dep}
                </span>
              ))}
            </div>
          )}
          {/* Editable condition */}
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <span className="text-[9px] text-yellow-400 shrink-0">if:</span>
            <InlineEdit
              value={condition}
              onChange={(v) => updateStage(stageName, { condition: v != null && String(v) !== '' ? String(v) : null })}
              emptyLabel="always run"
              placeholder="{{ condition }}"
              className="text-[9px] text-yellow-400 flex-1"
            />
          </div>
          {/* Editable loop */}
          <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            <span className="text-[9px] text-amber-400 shrink-0">loop &rarr;</span>
            <InlineSelect
              value={loopsBackTo ?? ''}
              options={[
                { value: '', label: 'none' },
                ...otherStageNames.map((n) => ({ value: n, label: n })),
              ]}
              onChange={(v) => updateStage(stageName, { loops_back_to: v || null })}
              className="text-[9px] text-amber-400"
            />
            {loopsBackTo && (
              <>
                <span className="text-[8px] text-temper-text-dim shrink-0">max</span>
                <InlineEdit
                  value={maxLoops}
                  onChange={(v) => updateStage(stageName, { max_loops: v != null && v !== '' ? Number(v) : null })}
                  type="number"
                  emptyLabel="\u221E"
                  className="text-[9px] text-amber-400 w-8"
                  min={1}
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* Source handle (right) */}
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!bg-temper-border !w-2.5 !h-2.5"
      />
      {/* Loop source handles (bottom) — multiple for distinct loop-back edges */}
      {[0, 1, 2].map((i) => (
        <Handle
          key={`bottom-${i}`}
          type="source"
          position={Position.Bottom}
          id={`bottom-${i}`}
          className="!bg-temper-border !w-2 !h-2"
          style={{ left: `${30 + i * 20}%` }}
        />
      ))}
      {/* Loop target handles (top) — multiple for distinct loop-back edges */}
      {[0, 1, 2].map((i) => (
        <Handle
          key={`top-${i}`}
          type="target"
          position={Position.Top}
          id={`top-${i}`}
          className="!bg-temper-border !w-2 !h-2"
          style={{ left: `${30 + i * 20}%` }}
        />
      ))}
    </div>
  );
}
