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
import { useConfigs } from '@/hooks/useConfigAPI';
import { useRegistry, toOptions } from '@/hooks/useRegistry';
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
// Options NOT backed by a registry (behavioral / semantic choices):

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

// Strategy / agent-mode options are populated from the runtime registry.
// See useRegistry() hook — the backend returns registered topology names.

/* ---------- NodeField — stopPropagation wrapper for inline edits ---------- */

function NodeField({ children, label }: { children: ReactNode; label?: string }) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  return (
    <div className="nopan nodrag flex items-center gap-1.5 min-w-0" onClick={stop} onKeyDown={stop}>
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
        className="nopan nodrag w-full px-3 py-1.5 flex items-center gap-1.5 text-left hover:bg-white/[0.02] transition-colors"
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
      {open && <div className="nopan nodrag px-3 pb-2">{children}</div>}
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
  onRemove,
}: {
  summary: ResolvedAgentSummary;
  isLeader: boolean;
  compact?: boolean;
  onSelect: () => void;
  onRemove?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleTools = summary.toolNames.slice(0, MAX_TOOL_NAMES_SHOWN);
  const showTemp = summary.temperature !== DEFAULT_TEMPERATURE;

  const removeBtn = onRemove && (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onRemove();
      }}
      className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-600 text-white text-[9px] flex items-center justify-center opacity-0 group-hover/card:opacity-100 transition-opacity z-10"
      title={`Remove ${summary.name}`}
    >
      &times;
    </button>
  );

  // Compact mode that can be expanded inline by clicking
  if (compact && !expanded) {
    return (
      <div className="relative group/card">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
          className="text-left rounded border border-temper-border/50 bg-temper-surface/50 hover:border-temper-accent/40 hover:bg-temper-accent/5 transition-all duration-150 hover:shadow-md px-1.5 py-1 min-w-0 w-full"
          title={`Click to expand · ${summary.provider}/${summary.model}`}
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
            <span className="text-[8px] text-temper-text-dim truncate ml-auto">
              {(summary.provider && summary.model) ? `${summary.provider}/${summary.model}` : (summary.provider || summary.model || 'default')}
              {summary.toolCount > 0 ? ` · ${summary.toolCount}t` : ''}
            </span>
          </div>
        </button>
        {removeBtn}
      </div>
    );
  }

  // Full expanded card — clicking the card body collapses it (if expandable),
  // the "edit" link opens the right panel.
  const handleCardClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (compact) {
      // Was compact, now expanded — click to collapse back
      setExpanded(false);
    } else {
      // Standalone full card (not inside a stage) — open right panel
      onSelect();
    }
  };

  return (
    <div className="relative group/card">
      <div
        onClick={handleCardClick}
        role="button"
        tabIndex={0}
        className="text-left rounded border border-temper-border/50 bg-temper-surface/50 hover:border-temper-accent/40 hover:bg-temper-accent/5 transition-all duration-150 hover:shadow-md p-1.5 min-w-0 w-full cursor-pointer"
      >
        {/* Row 1: Name + type badge + version + edit link */}
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
          {compact && (
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(); }}
              className="text-[8px] text-temper-accent hover:underline shrink-0 ml-0.5"
              title="Open in properties panel"
            >edit</button>
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
            {(summary.provider && summary.model) ? `${summary.provider}/${summary.model}` : (summary.provider || summary.model || 'default')}
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
      </div>
      {removeBtn}
    </div>
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
  onRemoveAgent,
}: {
  agents: string[];
  leaderAgent: string;
  agentSummaries: ResolvedAgentSummary[];
  isCompact?: boolean;
  selectAgent: (name: string) => void;
  onRemoveAgent?: (name: string) => void;
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
              onRemove={onRemoveAgent ? () => onRemoveAgent(name) : undefined}
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
            onRemove={onRemoveAgent ? () => onRemoveAgent(leaderAgent) : undefined}
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
  onRemoveAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  isCompact?: boolean;
  selectAgent: (name: string) => void;
  onRemoveAgent?: (name: string) => void;
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
                    onRemove={onRemoveAgent ? () => onRemoveAgent(name) : undefined}
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
  onRemoveAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  collaborationStrategy: string;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
  onRemoveAgent?: (name: string) => void;
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
                onRemove={onRemoveAgent ? () => onRemoveAgent(name) : undefined}
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
  onRemoveAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  agentMode: string;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
  onRemoveAgent?: (name: string) => void;
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
                onRemove={onRemoveAgent ? () => onRemoveAgent(name) : undefined}
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
  onRemoveAgent,
}: {
  agents: string[];
  agentSummaries: ResolvedAgentSummary[];
  agentDetailsLoaded: boolean;
  agentMode: string;
  collaborationStrategy: string;
  leaderAgent: string | null;
  isCompact?: boolean;
  selectAgent: (name: string) => void;
  onRemoveAgent?: (name: string) => void;
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
              onRemove={onRemoveAgent ? () => onRemoveAgent(name) : undefined}
            />
          ) : (
            <AgentSkeleton key={name} />
          );
        })}
      </div>
    );
  }

  // Leader strategy with a known leader
  if (leaderAgent && collaborationStrategy === 'leader') {
    return (
      <LeaderLayout
        agents={agents}
        leaderAgent={leaderAgent}
        agentSummaries={agentSummaries}
        isCompact={isCompact}
        selectAgent={selectAgent}
        onRemoveAgent={onRemoveAgent}
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
        onRemoveAgent={onRemoveAgent}
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
        onRemoveAgent={onRemoveAgent}
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
      onRemoveAgent={onRemoveAgent}
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
    workflowOutputSources: _workflowOutputSources,
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
  const autoFocusStageName = useDesignStore((s) => s.autoFocusStageName);
  const setAutoFocusStageName = useDesignStore((s) => s.setAutoFocusStageName);
  const isSelected = selectedStageName === stageName;
  const zoom = useStore((s) => s.transform[2]);
  const isCompact = zoom < 0.6;

  const shouldAutoFocus = autoFocusStageName === stageName;

  // Fetch available agent configs for the add-agent dropdown
  const { data: agentConfigs } = useConfigs('agent');
  const availableAgents = agentConfigs?.configs
    .map((c) => c.name)
    .filter((n) => !agents.includes(n)) ?? [];

  // Dynamic options from runtime registry
  const { data: registry } = useRegistry();
  const strategyOptions = toOptions(registry?.strategies);
  const agentTypeOptions = toOptions(registry?.agent_types);
  const providerOptions = toOptions(registry?.providers);

  const otherStageNames = allStages
    .filter((s) => s.name !== stageName)
    .map((s) => s.name);

  const inputEntries = Object.entries(inputs);

  const refLabel = stageRef
    ? stageRef.replace(/^.*\//, '').replace(/\.yaml$/, '')
    : null;

  // Single-agent nodes get a distinct, compact layout
  const isSingleAgent = agentCount === 1 && !isRef;
  const singleAgentSummary = isSingleAgent
    ? (agentSummaries as ResolvedAgentSummary[]).find((s) => s.name === agents[0]) ?? null
    : null;

  // Shared container for both single-agent and multi-agent nodes
  return (
    <div
      className={`rounded-lg cursor-pointer group relative ${isSelected ? 'ring-2 ring-temper-accent/40 shadow-lg shadow-temper-accent/10' : ''}`}
      style={{
        border: `2px solid ${isSelected ? stageColor : 'var(--color-temper-border)'}`,
        ...(isSingleAgent
          ? { borderLeftColor: stageColor, borderLeftWidth: '3px' }
          : { borderTopColor: stageColor, borderTopWidth: '3px' }),
        backgroundColor: 'var(--color-temper-panel)',
        width: '380px',
      }}
      role="button"
      tabIndex={0}
      aria-label={isSingleAgent ? `Agent: ${stageName}` : `Stage: ${stageName}`}
      onClick={() => selectStage(stageName)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectStage(stageName);
        }
      }}
    >
      {/* Target handle (left) — incoming dependency */}
      <div title="Drag here to create a dependency from another stage">
        <Handle
          type="target"
          position={Position.Left}
          id="left"
          className="!bg-temper-border !w-2.5 !h-2.5"
        />
      </div>

      {/* Delete button — visible on hover */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          removeStage(stageName);
        }}
        className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-600 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
        aria-label={`Remove ${stageName}`}
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
          {isSingleAgent ? (
            /* Single-agent: looks like a standalone agent, no stage abstraction visible */
            <div className="nopan nodrag flex-1 min-w-0" onClick={(e) => e.stopPropagation()}>
              <InlineEdit
                value={stageName}
                onChange={(v) => {
                  const newName = String(v ?? '').replace(/[^a-zA-Z0-9_-]/g, '');
                  if (newName && newName !== stageName) renameStage(stageName, newName);
                }}
                readOnly={isRef}
                className="text-sm font-bold"
                placeholder="agent_name"
                autoFocus={shouldAutoFocus}
                onAutoFocusConsumed={() => setAutoFocusStageName(null)}
              />
            </div>
          ) : (
            /* Multi-agent: show stage name as primary */
            <div className="nopan nodrag flex-1 min-w-0" onClick={(e) => e.stopPropagation()}>
              <InlineEdit
                value={stageName}
                onChange={(v) => {
                  const newName = String(v ?? '').replace(/[^a-zA-Z0-9_-]/g, '');
                  if (newName && newName !== stageName) renameStage(stageName, newName);
                }}
                readOnly={isRef}
                className="text-sm font-bold"
                placeholder="stage_name"
                autoFocus={shouldAutoFocus}
                onAutoFocusConsumed={() => setAutoFocusStageName(null)}
              />
            </div>
          )}
          {!isSingleAgent && (
            <span className="text-[8px] px-1.5 py-0.5 rounded shrink-0 font-medium bg-blue-900/30 text-blue-400">
              stage
            </span>
          )}
          {isRef && (
            <span className="text-[10px] text-temper-text-dim shrink-0" title={`Ref: ${stageRef}`}>
              [ref]
            </span>
          )}
          {version && (
            <span className="text-[9px] text-temper-text-dim shrink-0">v{version}</span>
          )}
        </div>

        {/* Single-agent: show compact provider/model + tools info */}
        {isSingleAgent && singleAgentSummary && (
          <div className="mt-0.5 text-[9px] text-temper-text-dim">
            {(singleAgentSummary.provider && singleAgentSummary.model)
              ? `${singleAgentSummary.provider}/${singleAgentSummary.model}`
              : (singleAgentSummary.provider || singleAgentSummary.model || '')}
            {singleAgentSummary.toolCount > 0 && ` · ${singleAgentSummary.toolCount} tools`}
          </div>
        )}

        {(description || isSelected) && (
          <div className="nopan nodrag mt-0.5" onClick={(e) => e.stopPropagation()}>
            <InlineEdit
              value={description}
              onChange={(v) => updateStage(stageName, { description: String(v ?? '') })}
              className="text-[10px] text-temper-text-muted w-full"
              emptyLabel="no description"
              placeholder="Description..."
            />
          </div>
        )}
        {refLabel && (
          <div className="text-[9px] text-temper-text-dim mt-0.5">ref: {refLabel}</div>
        )}
      </div>

      {/* ---- Agents section with collaboration layout (multi-agent only) ---- */}
      {!isSingleAgent && <NodeSection
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
            isCompact
            selectAgent={selectAgent}
            onRemoveAgent={!isRef ? (name) => updateStage(stageName, { agents: agents.filter((a) => a !== name) }) : undefined}
          />
        ) : (
          <div className="border border-dashed border-temper-border/50 rounded px-2 py-1.5 text-center">
            <span className="text-[10px] text-temper-text-dim">
              No agents assigned
            </span>
          </div>
        )}

        {/* Agent mode / strategy selectors (inline stages with 2+ agents) */}
        {!isRef && agents.length > 1 && (
          <div className="nopan nodrag flex items-center gap-2 mt-1.5">
            <NodeField label="mode">
              <InlineSelect
                value={agentMode}
                options={strategyOptions}
                onChange={(v) => updateStage(stageName, { agent_mode: v as 'sequential' | 'parallel' | 'adaptive' })}
              />
            </NodeField>
            <NodeField label="strategy">
              <InlineSelect
                value={collaborationStrategy}
                options={[{ value: 'independent', label: 'independent' }, ...strategyOptions]}
                onChange={(v) => updateStage(stageName, { collaboration_strategy: v as 'independent' | 'leader' | 'consensus' | 'debate' | 'round_robin' })}
              />
            </NodeField>
          </div>
        )}

        {/* Add agent dropdown (inline stages only) */}
        {!isRef && (
          <NodeField>
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) {
                  updateStage(stageName, { agents: [...agents, e.target.value] });
                }
              }}
              className="mt-1.5 w-full text-[10px] bg-temper-surface border border-temper-border/50 rounded px-1.5 py-1 text-temper-text-dim hover:border-temper-accent/40 transition-colors cursor-pointer"
            >
              <option value="">+ Add agent...</option>
              {availableAgents.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </NodeField>
        )}
      </NodeSection>}

      {/* ---- I/O section ---- */}
      {(inputEntries.length > 0 || outputs.length > 0 || !isRef) && (
        <NodeSection
          title="I/O"
          badge={`${inputEntries.length} in / ${outputs.length} out`}
          defaultOpen
        >
          {/* Inputs — each row has a Handle anchored to the left edge */}
          <div className="nopan nodrag" onClick={(e) => e.stopPropagation()}>
            <div className="text-[9px] text-temper-text-dim mb-1">Inputs (name : source)</div>
            <div className="flex flex-col gap-1 w-full">
              {inputEntries.map(([k, v]) => (
                <div key={k} className="relative flex items-center gap-1 p-1 bg-temper-surface/50 rounded border border-temper-border/50">
                  <Handle
                    type="target"
                    position={Position.Left}
                    id={`in:${k}`}
                    className="!absolute !w-2.5 !h-2.5 !bg-emerald-400 !border-emerald-600 !transform-none !min-w-0 !min-h-0 data-wire-handle"
                    style={{ left: '-13px', top: '50%', transform: 'translateY(-50%)' }}
                  />
                  <input
                    type="text" value={k} readOnly
                    className="w-24 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text opacity-60"
                    placeholder="name"
                  />
                  <input
                    type="text" value={v.source}
                    onChange={(e) => {
                      const newInputs: Record<string, { source: string }> = {};
                      for (const [ek, ev] of inputEntries) {
                        newInputs[ek] = ek === k ? { source: e.target.value } : ev;
                      }
                      updateStage(stageName, { inputs: newInputs });
                    }}
                    className="flex-1 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text"
                    placeholder="source"
                  />
                  <button
                    onClick={() => {
                      const newInputs: Record<string, { source: string }> = {};
                      for (const [ek, ev] of inputEntries) {
                        if (ek !== k) newInputs[ek] = ev;
                      }
                      updateStage(stageName, { inputs: newInputs });
                    }}
                    className="text-[10px] text-red-400 hover:text-red-300 px-0.5 shrink-0"
                  >&times;</button>
                </div>
              ))}
              <button
                onClick={() => {
                  const newInputs: Record<string, { source: string }> = {};
                  for (const [k, v] of inputEntries) newInputs[k] = v;
                  const newKey = `input_${inputEntries.length}`;
                  newInputs[newKey] = { source: '' };
                  updateStage(stageName, { inputs: newInputs });
                }}
                className="text-[9px] text-temper-accent hover:underline self-start"
              >+ Add</button>
            </div>
          </div>

          {/* Outputs — hidden when only the default output:text exists */}
          {/* Keep the Handle for edge connections even when output section is hidden */}
          <Handle
            type="source"
            position={Position.Right}
            id="out:output"
            className="!absolute !w-2.5 !h-2.5 !bg-emerald-400 !border-emerald-600 !transform-none !min-w-0 !min-h-0 data-wire-handle"
            style={{ right: '-5px', top: '50%', transform: 'translateY(-50%)', opacity: outputs.filter(o => o.name !== 'output').length > 0 ? 0 : 1 }}
          />
          {outputs.filter(o => o.name !== 'output').length > 0 && (
          <div className="nopan nodrag mt-2" onClick={(e) => e.stopPropagation()}>
            <div className="text-[9px] text-temper-text-dim mb-1">Outputs (name : type)</div>
            <div className="flex flex-col gap-1 w-full">
              {/* Main text output — always present */}
              <div className="relative flex items-center gap-1 p-1 bg-emerald-900/20 rounded border border-emerald-700/30">
                <Handle
                  type="source"
                  position={Position.Right}
                  id="out:output"
                  className="!absolute !w-2.5 !h-2.5 !bg-emerald-400 !border-emerald-600 !transform-none !min-w-0 !min-h-0 data-wire-handle"
                  style={{ right: '-13px', top: '50%', transform: 'translateY(-50%)' }}
                />
                <span className="px-1.5 py-0.5 text-[10px] text-emerald-400/80 italic">output</span>
                <span className="flex-1 px-1.5 py-0.5 text-[10px] text-temper-text-dim">text</span>
              </div>
              {/* Named structured outputs */}
              {outputs.filter((o) => o.name !== 'output').map((o) => (
                <div key={o.name} className="relative flex items-center gap-1 p-1 bg-temper-surface/50 rounded border border-temper-border/50">
                  <Handle
                    type="source"
                    position={Position.Right}
                    id={`out:${o.name}`}
                    className="!absolute !w-2.5 !h-2.5 !bg-emerald-400 !border-emerald-600 !transform-none !min-w-0 !min-h-0 data-wire-handle"
                    style={{ right: '-13px', top: '50%', transform: 'translateY(-50%)' }}
                  />
                  <input
                    type="text" value={o.name} readOnly
                    className="w-24 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text opacity-60"
                    placeholder="name"
                  />
                  <input
                    type="text" value={o.type}
                    onChange={(e) => {
                      const newOutputs: Record<string, string> = {};
                      for (const out of outputs) {
                        newOutputs[out.name] = out.name === o.name ? e.target.value : out.type;
                      }
                      updateStage(stageName, { outputs: newOutputs });
                    }}
                    className="flex-1 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text"
                    placeholder="type"
                  />
                  <button
                    onClick={() => {
                      const newOutputs: Record<string, string> = {};
                      for (const out of outputs) {
                        if (out.name !== o.name) newOutputs[out.name] = out.type;
                      }
                      updateStage(stageName, { outputs: newOutputs });
                    }}
                    className="text-[10px] text-red-400 hover:text-red-300 px-0.5 shrink-0"
                  >&times;</button>
                </div>
              ))}
              <button
                onClick={() => {
                  const newOutputs: Record<string, string> = {};
                  for (const o of outputs) newOutputs[o.name] = o.type;
                  newOutputs[`output_${outputs.length}`] = 'string';
                  updateStage(stageName, { outputs: newOutputs });
                }}
                className="text-[9px] text-temper-accent hover:underline self-start"
              >+ Add</button>
            </div>
          </div>
          )}
        </NodeSection>
      )}

      {/* Config, Quality Gates, Convergence, Collaboration, Conflict sections
         are intentionally omitted from the canvas node to keep it compact.
         Edit these via the right-side Stage Properties panel. */}

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
          <div className="nopan nodrag flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
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
          <div className="nopan nodrag flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
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

      {/* Source handle (right) — stage-level dependency, offset upward to avoid overlapping out:output */}
      <div title="Drag to create a dependency to another stage">
        <Handle
          type="source"
          position={Position.Right}
          id="right"
          className="!bg-temper-border !w-2.5 !h-2.5"
          style={{ top: '35%' }}
        />
      </div>

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
