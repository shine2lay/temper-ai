/**
 * What each kind of thing puts in the big view.
 *
 * This is the only module that knows the difference between a run, a stage,
 * an agent, a script agent, a model call and a tool call. It turns the one
 * the reader clicked into a `ViewShape`; the frame renders that shape and
 * knows nothing else. Being a plain function over plain data, it is also
 * where the unit tests ask "what does a tool call show?" without rendering
 * anything.
 *
 * It never formats a long value: an agent's output, a prompt, a tool's
 * return all stay in their native form inside a `ContentValue`, so opening
 * a run of 126 agents costs a few small objects and no stringifying.
 */
import type {
  AgentExecution,
  ExecutionStatus,
  LLMCall,
  NodeExecution,
  Selection,
  SelectionType,
  ToolCall,
  WorkflowExecution,
} from '@/types';
import {
  ensureUTC,
  formatCost,
  formatDuration,
  formatTimestamp,
  formatTokens,
} from '@/lib/utils';
import { toolNames } from '@/lib/toolLabels';
import { agentDisplayName, UNNAMED_AGENT } from '@/lib/liveAgents';
import type {
  ContentValue,
  CoreBlock,
  Fact,
  ShapeLink,
  TimelineRow,
  ViewShape,
} from './types';

/** Everything the builder may read. A plain bag, so tests can fake it. */
export interface ShapeSources {
  workflow: WorkflowExecution | null;
  /** Every node by id — the drawn ones and the ones nested inside them. */
  stages: Map<string, NodeExecution>;
  agents: Map<string, AgentExecution>;
  llmCalls: Map<string, LLMCall>;
  toolCalls: Map<string, ToolCall>;
  /** True when the page is holding streamed output for this agent. */
  hasStream: (agentId: string) => boolean;
  select: (type: SelectionType, id: string) => void;
}

/** A run's timeline could be every call it ever made; keep it sane. */
export const MAX_TIMELINE_ROWS = 2000;

/* ---------- small helpers ---------- */

function epoch(ts: string | null | undefined): number {
  if (!ts) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(ensureUTC(ts));
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
}

function text(value: string | null | undefined): ContentValue {
  return value ? { kind: 'auto', text: value } : { kind: 'empty', note: 'Nothing here' };
}

function json(data: unknown, note = 'Nothing here'): ContentValue {
  if (data == null) return { kind: 'empty', note };
  if (typeof data === 'object' && Object.keys(data as object).length === 0) {
    return { kind: 'empty', note };
  }
  return { kind: 'json', data };
}

function group(parts: { label?: string; value: ContentValue }[], note: string): ContentValue {
  const kept = parts.filter((p) => p.value.kind !== 'empty');
  if (kept.length === 0) return { kind: 'empty', note };
  if (kept.length === 1 && !kept[0].label) return kept[0].value;
  return { kind: 'group', parts: kept };
}

function nameOf(node: NodeExecution | undefined): string {
  return node?.stage_name ?? node?.name ?? node?.id ?? '';
}

/** The same rule the old sheet used to tell a script agent from a model one. */
export function isScriptAgent(agent: AgentExecution | undefined): boolean {
  if (!agent) return false;
  const config = agent.agent_config_snapshot?.agent;
  if (config?.type === 'script') return true;
  return (
    !config?.model &&
    !config?.provider &&
    (agent.total_tokens ?? 0) === 0 &&
    (agent.total_llm_calls ?? 0) === 0 &&
    (agent.duration_seconds ?? 0) > 0 &&
    agent.status !== 'running'
  );
}

/** The node an agent belongs to, by its own ids or by searching the tree. */
export function stageIdOfAgent(
  agentId: string,
  agent: AgentExecution | undefined,
  stages: Map<string, NodeExecution>,
): string | undefined {
  const direct = agent?.stage_execution_id ?? agent?.stage_id;
  if (direct && stages.has(direct)) return direct;
  if (direct) return direct;
  for (const [stageId, stage] of stages) {
    if (stage.agents?.some((a) => a.id === agentId)) return stageId;
    if (stage.agent?.id === agentId) return stageId;
  }
  return undefined;
}

/** The node that holds this one, for a stage nested inside another stage. */
export function parentStageId(
  stageId: string,
  stages: Map<string, NodeExecution>,
): string | undefined {
  for (const [id, node] of stages) {
    if (id === stageId) continue;
    if (node.child_nodes?.some((c) => c.id === stageId)) return id;
  }
  return undefined;
}

/* ---------- the merged stream ---------- */

function llmRow(call: LLMCall): TimelineRow {
  const chips: string[] = [];
  if (call.total_tokens) chips.push(`${formatTokens(call.total_tokens)} tok`);
  if ((call.estimated_cost_usd ?? 0) > 0) chips.push(formatCost(call.estimated_cost_usd));
  if (call.duration_seconds != null) chips.push(formatDuration(call.duration_seconds));
  else if (call.latency_ms != null) chips.push(`${call.latency_ms}ms`);
  const asked = call.tool_calls?.length ?? 0;
  if (asked > 0) chips.push(`${asked} tool${asked > 1 ? 's' : ''}`);
  return {
    id: call.id,
    type: 'llm',
    at: epoch(call.start_time),
    title: call.model ?? 'model call',
    status: call.status,
    chips,
    thinking: !!call.thinking,
    source: call,
    error: call.error_message,
  };
}

function toolRow(call: ToolCall): TimelineRow {
  const chips: string[] = [];
  if (call.duration_seconds != null) chips.push(formatDuration(call.duration_seconds));
  if (call.approval_required) chips.push('approval');
  return {
    id: call.id,
    type: 'tool',
    at: epoch(call.start_time),
    title: call.tool_name,
    status: call.status,
    chips,
    thinking: false,
    origin: { transport: call.transport, server: call.server, executed_by: call.executed_by },
    source: call,
    error: call.error_message,
  };
}

/** Model calls and tool calls of one agent, in the order they happened. */
export function agentTimeline(agent: AgentExecution | undefined): TimelineRow[] {
  if (!agent) return [];
  const rows: TimelineRow[] = [];
  for (const call of agent.llm_calls ?? []) rows.push(llmRow(call));
  for (const call of agent.tool_calls ?? []) rows.push(toolRow(call));
  return sortRows(rows);
}

function sortRows(rows: TimelineRow[]): TimelineRow[] {
  // A stable sort keeps calls with no start time in the order they arrived,
  // which for a running agent is the order they happened.
  return rows
    .map((row, i) => ({ row, i }))
    .sort((a, b) => (a.row.at - b.row.at) || (a.i - b.i))
    .map(({ row }) => row)
    .slice(0, MAX_TIMELINE_ROWS);
}

/** What one timeline row shows when it opens: what went in, what came out. */
export function rowPanes(row: TimelineRow): {
  in: { label: string; value: ContentValue };
  out: { label: string; value: ContentValue };
  thinking?: string;
} {
  if (row.type === 'llm') {
    const call = row.source as LLMCall;
    const asked = call.tool_calls ?? [];
    // An answer can be prose, JSON or code: let the renderer tell which.
    const out: ContentValue = call.response
      ? { kind: 'auto', text: call.response }
      : asked.length > 0
        ? { kind: 'json', data: asked }
        : { kind: 'empty', note: 'No answer' };
    return {
      in: { label: 'Conversation sent', value: messagesOrText(call.prompt) },
      out: { label: 'Answer', value: out },
      thinking: call.thinking,
    };
  }
  const call = row.source as ToolCall;
  return {
    in: { label: 'Arguments', value: json(call.input_data ?? call.input_params, 'No arguments') },
    out: { label: 'Returned', value: returned(call.output_data) },
  };
}

function messagesOrText(prompt: unknown): ContentValue {
  if (prompt == null) return { kind: 'empty', note: 'No conversation recorded' };
  if (Array.isArray(prompt)) return { kind: 'messages', messages: prompt };
  if (typeof prompt === 'string') return { kind: 'auto', text: prompt };
  return { kind: 'json', data: prompt };
}

function returned(value: unknown): ContentValue {
  if (value == null) return { kind: 'empty', note: 'Nothing returned' };
  if (typeof value === 'string') return { kind: 'auto', text: value };
  return { kind: 'json', data: value };
}

/* ---------- per-kind shapes ---------- */

function workflowShape(src: ShapeSources): ViewShape | null {
  const wf = src.workflow;
  if (!wf) return null;

  const rows: TimelineRow[] = [];
  for (const [, call] of src.llmCalls) rows.push(llmRow(call));
  for (const [, call] of src.toolCalls) rows.push(toolRow(call));

  const stageLinks: ShapeLink[] = Array.from(src.stages.values())
    .filter((node) => !parentStageId(node.id, src.stages))
    .map((node) => ({
      id: node.id,
      label: nameOf(node),
      status: node.status,
      meta: formatDuration(node.duration_seconds),
      open: () => src.select('stage', node.id),
    }));

  return {
    kind: 'workflow',
    id: wf.id,
    title: wf.workflow_name,
    status: wf.status,
    kindLabel: 'Run',
    facts: [
      { label: 'status', value: wf.status, tone: 'status' },
      { label: 'took', value: formatDuration(wf.duration_seconds) },
      { label: 'tokens', value: formatTokens(wf.total_tokens) },
      { label: 'cost', value: formatCost(wf.total_cost_usd), tone: 'money' },
      { label: 'model calls', value: String(wf.total_llm_calls ?? 0) },
      { label: 'tool calls', value: String(wf.total_tool_calls ?? 0) },
      { label: 'started', value: formatTimestamp(wf.start_time) },
      { label: 'ended', value: formatTimestamp(wf.end_time) },
    ],
    siblings: [],
    children: { label: 'Stages', items: stageLinks },
    core: [
      { key: 'cost', title: 'Cost and tokens', value: { kind: 'widget', name: 'cost-breakdown' } },
      {
        key: 'config',
        title: 'Workflow config',
        value: json(wf.workflow_config ?? wf.workflow_config_snapshot, 'No config recorded'),
      },
    ],
    in: { label: 'What the run was given', value: json(wf.input_data, 'No inputs') },
    out: { label: 'What the run produced', value: json(wf.output_data, 'No outputs') },
    timeline: sortRows(rows),
    error: wf.status === 'failed' ? wf.error_message : undefined,
  };
}

function stageShape(stageId: string, src: ShapeSources): ViewShape | null {
  const stage = src.stages.get(stageId);
  if (!stage) return null;

  const executed = stage.num_agents_executed ?? stage.agents?.length ?? 0;
  const succeeded = stage.num_agents_succeeded ?? 0;
  const failed = stage.num_agents_failed ?? 0;
  const baseName = nameOf(stage);

  const siblings: ShapeLink[] = Array.from(src.stages.values())
    .filter((s) => nameOf(s) === baseName)
    .sort((a, b) => epoch(a.start_time) - epoch(b.start_time))
    .map((s, i) => ({
      id: s.id,
      label: `#${i + 1}`,
      status: s.status,
      active: s.id === stageId,
      open: () => src.select('stage', s.id),
    }));

  const agents = stage.agents ?? (stage.agent ? [stage.agent] : []);
  const rows: TimelineRow[] = [];
  for (const a of agents) {
    const full = src.agents.get(a.id) ?? a;
    for (const call of full.llm_calls ?? []) rows.push(llmRow(call));
    for (const call of full.tool_calls ?? []) rows.push(toolRow(call));
  }

  const parentId = parentStageId(stageId, src.stages);
  const facts: Fact[] = [
    { label: 'status', value: stage.status, tone: 'status' },
    { label: 'agents', value: String(executed) },
    { label: 'ok', value: String(succeeded), tone: 'accent' },
    { label: 'failed', value: String(failed), tone: failed > 0 ? 'danger' : 'muted' },
    { label: 'took', value: formatDuration(stage.duration_seconds) },
    { label: 'started', value: formatTimestamp(stage.start_time) },
  ];
  if (stage.stage_type) facts.splice(1, 0, { label: 'kind', value: stage.stage_type });
  if (stage.strategy) facts.push({ label: 'strategy', value: stage.strategy });

  const core: CoreBlock[] = [];
  const childStages = stage.child_nodes ?? [];
  if (childStages.length > 0) {
    core.push({
      key: 'inner',
      title: 'Stages inside',
      badge: String(childStages.length),
      value: {
        kind: 'widget',
        name: 'links',
        data: childStages.map((c) => ({
          id: c.id,
          label: nameOf(c),
          status: c.status,
          meta: formatDuration(c.duration_seconds),
          open: () => src.select('stage', c.id),
        })) satisfies ShapeLink[],
      },
    });
  }
  if (stage.collaboration_events && stage.collaboration_events.length > 0) {
    core.push({
      key: 'collab',
      title: 'Collaboration',
      badge: String(stage.collaboration_events.length),
      value: { kind: 'widget', name: 'collaboration', data: stage.collaboration_events },
    });
  }
  if (stage.stage_config_snapshot) {
    core.push({ key: 'config', title: 'Stage config', value: json(stage.stage_config_snapshot) });
  }
  if (stage.unresolved_inputs && stage.unresolved_inputs.length > 0) {
    core.push({
      key: 'unresolved',
      title: 'Inputs that did not resolve',
      badge: String(stage.unresolved_inputs.length),
      value: { kind: 'json', data: stage.unresolved_inputs },
      defaultOpen: true,
    });
  }

  return {
    kind: 'stage',
    id: stageId,
    title: baseName || stageId,
    status: stage.status,
    kindLabel: 'Stage',
    facts,
    parent: parentId
      ? {
          id: parentId,
          label: nameOf(src.stages.get(parentId)) || 'parent stage',
          open: () => src.select('stage', parentId),
        }
      : undefined,
    siblings: siblings.length > 1 ? siblings : [],
    children: {
      label: 'Agents',
      items: agents.map((a) => ({
        id: a.id,
        label: agentDisplayName(src.agents.get(a.id) ?? a) ?? UNNAMED_AGENT,
        status: a.status,
        meta: formatDuration(a.duration_seconds),
        open: () => src.select('agent', a.id),
      })),
    },
    core,
    in: { label: 'What fed this stage', value: json(stage.input_data, 'No inputs') },
    out: { label: 'What it produced', value: json(stage.output_data, 'No outputs') },
    timeline: sortRows(rows),
    error: stage.error_message,
  };
}

function agentRounds(
  agentId: string,
  agent: AgentExecution,
  stageId: string | undefined,
  src: ShapeSources,
): ShapeLink[] {
  const parent = stageId ? src.stages.get(stageId) : undefined;
  if (!parent) return [];
  const stageName = nameOf(parent);
  if (!stageName) return [];
  const agentName = agent.agent_name ?? agent.name;

  const found: { id: string; status: ExecutionStatus; at: number }[] = [];
  for (const [, stage] of src.stages) {
    if (nameOf(stage) !== stageName) continue;
    const pool = stage.agents ?? (stage.agent ? [stage.agent] : []);
    const match = pool.find((a) => (a.agent_name ?? a.name) === agentName);
    if (match) found.push({ id: match.id, status: match.status, at: epoch(stage.start_time) });
  }
  found.sort((a, b) => a.at - b.at);
  if (found.length < 2) return [];
  return found.map((f, i) => ({
    id: f.id,
    label: `#${i + 1}`,
    status: f.status,
    active: f.id === agentId,
    open: () => src.select('agent', f.id),
  }));
}

function agentShape(agentId: string, src: ShapeSources): ViewShape | null {
  const ag = src.agents.get(agentId);
  if (!ag) return null;

  const script = isScriptAgent(ag);
  const outer = ag.agent_config_snapshot?.agent as Record<string, unknown> | undefined;
  // A script agent's config arrives double-nested: agent.agent.script_template.
  const config = ((outer?.agent as Record<string, unknown> | undefined) ?? outer) ?? undefined;
  const stageId = stageIdOfAgent(agentId, ag, src.stages);
  const stage = stageId ? src.stages.get(stageId) : undefined;

  const cost =
    ag.estimated_cost_usd > 0
      ? ag.estimated_cost_usd
      : (ag.llm_calls ?? []).reduce((sum, c) => sum + (c.estimated_cost_usd ?? 0), 0);

  const facts: Fact[] = [{ label: 'status', value: ag.status, tone: 'status' }];
  if (script) {
    facts.push({ label: 'kind', value: 'script' });
    const timeout = config?.timeout_seconds as number | undefined;
    if (timeout) facts.push({ label: 'timeout', value: `${timeout}s` });
  } else {
    const provider = config?.provider as string | undefined;
    const model = config?.model as string | undefined;
    if (provider && model) facts.push({ label: 'model', value: `${provider}/${model}`, tone: 'accent' });
    else if (model) facts.push({ label: 'model', value: model, tone: 'accent' });
    const type = config?.type as string | undefined;
    if (type && type !== 'standard') facts.push({ label: 'kind', value: type });
  }
  facts.push({ label: 'took', value: formatDuration(ag.duration_seconds) });
  if (!script) {
    facts.push({ label: 'tokens', value: formatTokens(ag.total_tokens) });
    facts.push({ label: 'cost', value: formatCost(cost), tone: 'money' });
    facts.push({
      label: 'calls',
      value: `${ag.total_llm_calls ?? 0} model · ${ag.total_tool_calls ?? 0} tool`,
    });
  }
  if (ag.role) facts.push({ label: 'role', value: ag.role });
  if ((ag.round ?? 1) > 1) facts.push({ label: 'round', value: String(ag.round) });
  if (stage) facts.push({ label: 'stage', value: nameOf(stage) });
  if (ag.confidence_score != null) {
    facts.push({ label: 'confidence', value: `${(ag.confidence_score * 100).toFixed(1)}%` });
  }
  facts.push({ label: 'started', value: formatTimestamp(ag.start_time) });

  const core: CoreBlock[] = [];
  if (src.hasStream(agentId)) {
    core.push({
      key: 'stream',
      title: ag.status === 'running' ? 'Streaming now' : 'What it streamed',
      value: { kind: 'stream', agentId },
      defaultOpen: ag.status === 'running',
    });
  }
  if (script) {
    const template = config?.script_template as string | undefined;
    if (template) {
      core.push({ key: 'script', title: 'The script it ran', value: { kind: 'code', text: template } });
    }
  } else {
    const systemPrompt = config?.system_prompt as string | undefined;
    if (systemPrompt) {
      core.push({ key: 'system', title: 'System prompt', value: { kind: 'auto', text: systemPrompt } });
    }
    const taskTemplate = config?.task_template as string | undefined;
    if (taskTemplate) {
      core.push({ key: 'task', title: 'Task template', value: { kind: 'auto', text: taskTemplate } });
    }
    const tools = toolNames(config?.tools);
    if (tools.length > 0) {
      core.push({
        key: 'tools',
        title: 'Tools it was given',
        badge: String(tools.length),
        value: { kind: 'widget', name: 'tool-names', data: tools },
      });
    }
    const thinking = (ag.llm_calls ?? [])
      .map((call, index) => ({ call, index }))
      .filter(({ call }) => !!call.thinking);
    if (thinking.length > 0) {
      core.push({
        key: 'thinking',
        title: 'Thinking',
        badge: `${thinking.length} call${thinking.length > 1 ? 's' : ''}`,
        value: {
          kind: 'group',
          parts: thinking.map(({ call, index }) => ({
            label: `#${index + 1} ${call.model ?? 'model'}`,
            value: { kind: 'thinking', text: call.thinking! } as ContentValue,
          })),
        },
      });
    }
    if (ag.reasoning) {
      core.push({ key: 'reasoning', title: 'Reasoning', value: { kind: 'markdown', text: ag.reasoning } });
    }
    if (config?.inputs || config?.outputs) {
      core.push({
        key: 'io',
        title: 'Declared in and out',
        value: {
          kind: 'widget',
          name: 'declared-io',
          data: { inputs: config?.inputs, outputs: config?.outputs },
        },
      });
    }
  }
  if (ag.agent_config_snapshot) {
    core.push({ key: 'config', title: 'Config', value: json(ag.agent_config_snapshot) });
  }

  return {
    kind: script ? 'scriptAgent' : 'agent',
    id: agentId,
    title: agentDisplayName(ag) ?? UNNAMED_AGENT,
    status: ag.status,
    kindLabel: script ? 'Script agent' : 'Agent',
    facts,
    parent: stageId
      ? { id: stageId, label: nameOf(stage) || 'its stage', open: () => src.select('stage', stageId) }
      : undefined,
    siblings: agentRounds(agentId, ag, stageId, src),
    children: { label: '', items: [] },
    core,
    in: {
      label: 'What it was handed',
      value: json(ag.input_data, script ? 'No variables' : 'Nothing handed in'),
    },
    out: {
      label: script ? 'What it printed' : 'Its result',
      value: group(
        [
          { value: text(ag.output) },
          { label: 'Structured output', value: json(ag.output_data, 'none') },
        ],
        'No result',
      ),
    },
    timeline: agentTimeline(ag),
    error: ag.error_message,
    note: ag.summary_only
      ? ag.agent_name
        ? 'The page has only a summary of this agent. A new agent\u2019s details arrive with the next update; an earlier loop round or retried attempt keeps just this summary and what it streamed.'
        : 'The server could not say which agent this is. Its streamed output is below.'
      : undefined,
  };
}

function llmCallShape(callId: string, src: ShapeSources): ViewShape | null {
  const call = src.llmCalls.get(callId);
  if (!call) return null;

  const agentId = call.agent_execution_id ?? call.agent_id;
  const agent = agentId ? src.agents.get(agentId) : undefined;

  let duration = call.duration_seconds;
  if (duration == null && call.start_time && call.end_time) {
    duration = (epoch(call.end_time) - epoch(call.start_time)) / 1000;
  } else if (duration == null && call.latency_ms != null) {
    duration = call.latency_ms / 1000;
  }
  const latency =
    call.latency_ms != null
      ? `${call.latency_ms}ms`
      : duration != null && Number.isFinite(duration)
        ? formatDuration(duration)
        : '-';

  const title = call.provider && call.model ? `${call.provider}/${call.model}` : call.model ?? 'Model call';
  const asked = call.tool_calls ?? [];

  const core: CoreBlock[] = [];
  if (call.thinking) {
    core.push({ key: 'thinking', title: 'Thinking', value: { kind: 'thinking', text: call.thinking } });
  }
  if (asked.length > 0) {
    core.push({
      key: 'asked',
      title: 'Tools it asked for',
      badge: String(asked.length),
      value: { kind: 'json', data: asked },
    });
  }

  return {
    kind: 'llmCall',
    id: callId,
    title,
    status: call.status,
    kindLabel: 'Model call',
    facts: [
      { label: 'status', value: call.status, tone: 'status' },
      { label: 'took', value: latency },
      { label: 'prompt', value: formatTokens(call.prompt_tokens) },
      { label: 'answer', value: formatTokens(call.completion_tokens) },
      { label: 'tokens', value: formatTokens(call.total_tokens) },
      { label: 'cost', value: formatCost(call.estimated_cost_usd), tone: 'money' },
      { label: 'started', value: formatTimestamp(call.start_time) },
    ],
    parent: agentId
      ? {
          id: agentId,
          label: agent ? agentDisplayName(agent) ?? UNNAMED_AGENT : 'its agent',
          open: () => src.select('agent', agentId),
        }
      : undefined,
    siblings: [],
    children: { label: '', items: [] },
    core,
    in: { label: 'Conversation sent', value: messagesOrText(call.prompt) },
    out: {
      label: 'What the model answered',
      // Structured answers are the common case now: a JSON answer has to be a
      // tree you can fold, not a paragraph of braces.
      value: call.response
        ? { kind: 'auto', text: call.response }
        : asked.length > 0
          ? { kind: 'json', data: asked }
          : { kind: 'empty', note: 'No answer recorded' },
    },
    error: call.status === 'failed' ? call.error_message : undefined,
  };
}

function toolCallShape(callId: string, src: ShapeSources): ViewShape | null {
  const call = src.toolCalls.get(callId);
  if (!call) return null;

  const agentId = call.agent_execution_id ?? call.agent_id;
  const agent = agentId ? src.agents.get(agentId) : undefined;

  const facts: Fact[] = [
    { label: 'status', value: call.status, tone: 'status' },
    { label: 'took', value: formatDuration(call.duration_seconds) },
  ];
  if (call.transport === 'mcp') {
    facts.push({ label: 'over', value: call.server ? `MCP · ${call.server}` : 'MCP', tone: 'accent' });
  }
  if (call.executed_by && call.executed_by !== 'temper') {
    facts.push({ label: 'ran in', value: call.executed_by });
  }
  if (call.approval_required) facts.push({ label: 'approval', value: 'required', tone: 'warn' });
  facts.push({ label: 'started', value: formatTimestamp(call.start_time) });
  facts.push({ label: 'ended', value: formatTimestamp(call.end_time) });

  const core: CoreBlock[] = [];
  if (call.safety_checks_applied != null) {
    core.push({ key: 'safety', title: 'Safety checks', value: json(call.safety_checks_applied) });
  }

  return {
    kind: 'toolCall',
    id: callId,
    title: call.tool_name,
    status: call.status,
    kindLabel: 'Tool call',
    facts,
    parent: agentId
      ? {
          id: agentId,
          label: agent ? agentDisplayName(agent) ?? UNNAMED_AGENT : 'its agent',
          open: () => src.select('agent', agentId),
        }
      : undefined,
    siblings: [],
    children: { label: '', items: [] },
    core,
    in: { label: 'Arguments', value: json(call.input_data ?? call.input_params, 'No arguments') },
    out: { label: 'What it returned', value: returned(call.output_data) },
    error: call.status === 'failed' ? call.error_message : undefined,
  };
}

/* ---------- the one entry point ---------- */

export function buildShape(selection: Selection | null, src: ShapeSources): ViewShape | null {
  if (!selection) return null;
  switch (selection.type) {
    case 'workflow':
      return workflowShape(src);
    case 'stage':
      return stageShape(selection.id, src);
    case 'agent':
      return agentShape(selection.id, src);
    case 'llmCall':
      return llmCallShape(selection.id, src);
    case 'toolCall':
      return toolCallShape(selection.id, src);
    default:
      return null;
  }
}

/** What the frame says when the thing clicked is not on the page (yet). */
export const MISSING_LABEL: Record<SelectionType, string> = {
  workflow: 'This run is not loaded.',
  stage: 'This stage is not on the page.',
  agent: 'This agent is not on the page.',
  llmCall: 'This model call is not on the page.',
  toolCall: 'This tool call is not on the page.',
};
