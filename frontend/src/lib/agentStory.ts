/**
 * One agent's story: what it thought, said and did, in the order it happened.
 *
 * The story is written from two sides and read as one:
 *
 *  - live, from the stream — words as they arrive, and tool steps from the
 *    run's events;
 *  - read back, from what temper stored — the model calls and tool calls of
 *    an agent that has finished, or of the part of a run that happened
 *    before this page opened.
 *
 * Every live word carries the id of the model call it belongs to, so a page
 * that joined halfway knows which calls it heard itself and which it must
 * read back — nothing is told twice.
 */
import type { AgentExecution, LLMCall, ToolCall } from '@/types';
import { asList } from './asList';

export type StoryItemKind = 'text' | 'thinking' | 'tool';

interface StoryItemBase {
  id: string;
  /** When it happened, ISO. Used to weave live and read-back together. */
  at?: string;
  /** The model call it belongs to, when known. */
  callId?: string;
}

export interface StoryText extends StoryItemBase {
  kind: 'text';
  text: string;
  /** No more words will be added (its call ended). */
  closed?: boolean;
}

export interface StoryThinking extends StoryItemBase {
  kind: 'thinking';
  text: string;
  closed?: boolean;
}

export interface StoryTool extends StoryItemBase {
  kind: 'tool';
  toolName: string;
  args?: Record<string, unknown>;
  status: 'running' | 'completed' | 'failed';
  durationSeconds?: number;
  result?: unknown;
  error?: string;
  /** The tool call's own id, so its start and its end find each other. */
  toolId?: string;
}

export type StoryItem = StoryText | StoryThinking | StoryTool;

export interface AgentStory {
  items: StoryItem[];
  /** Model calls whose words this page streamed itself. */
  streamedCalls: Set<string>;
  /** Tool calls already in the story. */
  toolIds: Set<string>;
}

export function newStory(): AgentStory {
  return { items: [], streamedCalls: new Set(), toolIds: new Set() };
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

/* ------------------------------------------------------------------ */
/* Live: words and tool steps as they arrive                           */
/* ------------------------------------------------------------------ */

export interface StreamChunk {
  content: string;
  chunk_type?: string;
  done?: boolean;
  call_id?: string | null;
}

/**
 * Add a streamed chunk to the story.
 *
 * Words of the same kind from the same call join the item they belong to,
 * so the story reads as paragraphs, not as a thousand fragments. A chunk
 * that ends a call closes its items: the next call starts new ones.
 */
export function appendChunk(story: AgentStory, chunk: StreamChunk, at?: string): void {
  const callId = chunk.call_id ?? undefined;
  if (callId) story.streamedCalls.add(callId);

  if (chunk.content) {
    const kind: StoryItemKind = chunk.chunk_type === 'thinking' ? 'thinking' : 'text';
    const last = story.items[story.items.length - 1];
    if (
      last &&
      (last.kind === 'text' || last.kind === 'thinking') &&
      last.kind === kind &&
      !last.closed &&
      (last.callId ?? undefined) === callId
    ) {
      last.text += chunk.content;
    } else {
      story.items.push(
        kind === 'thinking'
          ? { kind: 'thinking', id: nextId('think'), text: chunk.content, at, callId }
          : { kind: 'text', id: nextId('text'), text: chunk.content, at, callId },
      );
    }
  }

  if (chunk.done) {
    for (let i = story.items.length - 1; i >= 0; i--) {
      const item = story.items[i];
      if (item.kind === 'text' || item.kind === 'thinking') {
        if (item.closed) break;
        item.closed = true;
      }
    }
  }
}

/** A tool step has begun. */
export function startTool(
  story: AgentStory,
  step: { toolId?: string; toolName: string; args?: Record<string, unknown>; at?: string },
): void {
  if (step.toolId && story.toolIds.has(step.toolId)) return;
  if (step.toolId) story.toolIds.add(step.toolId);
  story.items.push({
    kind: 'tool',
    id: nextId('tool'),
    toolId: step.toolId,
    toolName: step.toolName,
    args: step.args,
    status: 'running',
    at: step.at,
  });
}

/**
 * A tool step has ended. It finds its start by id, or failing that by name
 * — the oldest still-running step of that name, since tools finish in the
 * order they were asked for.
 */
export function finishTool(
  story: AgentStory,
  step: {
    toolId?: string;
    toolName?: string;
    status: 'completed' | 'failed';
    durationSeconds?: number;
    result?: unknown;
    error?: string;
    args?: Record<string, unknown>;
    at?: string;
  },
): void {
  let open: StoryTool | undefined;
  for (const item of story.items) {
    if (item.kind !== 'tool' || item.status !== 'running') continue;
    if (step.toolId && item.toolId === step.toolId) {
      open = item;
      break;
    }
    if (!open && (!step.toolName || item.toolName === step.toolName)) open = item;
  }
  if (!open) {
    // Its start never reached this page (it joined late): show the step anyway.
    open = {
      kind: 'tool',
      id: nextId('tool'),
      toolId: step.toolId,
      toolName: step.toolName ?? 'tool',
      args: step.args,
      status: 'running',
      at: step.at,
    };
    story.items.push(open);
  }
  if (step.toolId) {
    open.toolId = step.toolId;
    story.toolIds.add(step.toolId);
  }
  open.status = step.status;
  if (step.durationSeconds != null) open.durationSeconds = step.durationSeconds;
  if (step.result !== undefined) open.result = step.result;
  if (step.error) open.error = step.error;
  if (step.args && !open.args) open.args = step.args;
}

/* ------------------------------------------------------------------ */
/* Read back: the story of what temper already stored                  */
/* ------------------------------------------------------------------ */

function callId(call: LLMCall): string {
  return call.id ?? call.llm_call_id ?? '';
}

function toolId(call: ToolCall): string {
  return call.id ?? call.tool_execution_id ?? '';
}

/**
 * The stored story of an agent: each model call's thinking and answer, and
 * each tool call, in the order they happened.
 *
 * Calls the page streamed itself are left out — it already has them, word
 * for word, and in finer grain than the store keeps.
 */
export function storyFromStored(
  agent: Pick<AgentExecution, 'llm_calls' | 'tool_calls'> | null | undefined,
  skip?: { calls?: Set<string>; tools?: Set<string> },
): StoryItem[] {
  if (!agent) return [];
  const out: StoryItem[] = [];

  for (const call of asList(agent.llm_calls)) {
    const id = callId(call);
    if (id && skip?.calls?.has(id)) continue;
    const at = call.start_time ?? undefined;
    if (call.thinking) {
      out.push({ kind: 'thinking', id: `stored-think-${id}`, text: call.thinking, at, callId: id, closed: true });
    }
    if (call.response) {
      out.push({ kind: 'text', id: `stored-text-${id}`, text: call.response, at, callId: id, closed: true });
    }
    if (call.error_message) {
      out.push({
        kind: 'text',
        id: `stored-err-${id}`,
        text: call.error_message,
        at,
        callId: id,
        closed: true,
      });
    }
  }

  for (const call of asList(agent.tool_calls)) {
    const id = toolId(call);
    if (id && skip?.tools?.has(id)) continue;
    out.push({
      kind: 'tool',
      id: `stored-tool-${id}`,
      toolId: id || undefined,
      toolName: call.tool_name,
      args: call.input_params ?? call.input_data,
      status: call.status === 'failed' ? 'failed' : call.status === 'running' ? 'running' : 'completed',
      durationSeconds: call.duration_seconds ?? undefined,
      result: call.output_data,
      error: call.error_message,
      at: call.start_time ?? undefined,
    });
  }

  return sortByTime(out);
}

function timeOf(item: StoryItem): number {
  const t = item.at ? Date.parse(item.at) : NaN;
  // No time of its own means it is happening now: it belongs at the end.
  return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
}

/** Order by when it happened, keeping items of the same moment as they are. */
function sortByTime(items: StoryItem[], timeFor: (item: StoryItem) => number = timeOf): StoryItem[] {
  return items
    .map((item, i) => ({ item, i, t: timeFor(item) }))
    .sort((a, b) => (a.t === b.t ? a.i - b.i : a.t - b.t))
    .map((x) => x.item);
}

/**
 * The whole story of one agent: what this page heard live, with everything
 * it missed read back from the store, woven together in time.
 */
export function fullStory(
  agent: Pick<AgentExecution, 'llm_calls' | 'tool_calls'> | null | undefined,
  live: AgentStory | undefined,
): StoryItem[] {
  const stored = storyFromStored(agent, { calls: live?.streamedCalls, tools: live?.toolIds });
  if (!live || live.items.length === 0) return stored;
  const liveItems = withStoredDetail(live.items, agent);
  if (stored.length === 0) return liveItems;
  // Stored items are the earlier part of the run; live items are the part
  // this page heard. A live item is placed by the model call it belongs to,
  // so what the page heard lands where it happened, not where it arrived.
  const callStart = new Map<string, number>();
  for (const call of asList(agent?.llm_calls)) {
    const id = callId(call);
    const t = call.start_time ? Date.parse(call.start_time) : NaN;
    if (id && !Number.isNaN(t)) callStart.set(id, t);
  }
  const liveIds = new Set(liveItems.map((item) => item.id));
  return sortByTime([...stored, ...liveItems], (item) => {
    if (liveIds.has(item.id) && item.callId) {
      const t = callStart.get(item.callId);
      if (t != null) return t;
    }
    return timeOf(item);
  });
}

/**
 * A tool step seen live says what was run and how it went, but its full
 * input and result only reach the page with the next snapshot. Fill those
 * in from the store when they arrive, so opening a step always shows them.
 */
function withStoredDetail(
  items: StoryItem[],
  agent: Pick<AgentExecution, 'tool_calls'> | null | undefined,
): StoryItem[] {
  const byId = new Map<string, ToolCall>();
  for (const call of asList(agent?.tool_calls)) {
    const id = toolId(call);
    if (id) byId.set(id, call);
  }
  if (byId.size === 0) return items;
  return items.map((item) => {
    if (item.kind !== 'tool' || !item.toolId) return item;
    const stored = byId.get(item.toolId);
    if (!stored) return item;
    return {
      ...item,
      args: item.args ?? stored.input_params ?? stored.input_data,
      result: item.result ?? stored.output_data,
      error: item.error ?? stored.error_message,
      durationSeconds: item.durationSeconds ?? stored.duration_seconds ?? undefined,
    } satisfies StoryTool;
  });
}
