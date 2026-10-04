/**
 * The story of a Pi agent step's turn (see agentStory.ts for the story itself).
 *
 * Only Pi agents use this module, so every other agent's page stays exactly as
 * it was. It tells the same story, plus what a Pi worker's events give:
 *
 * A producer that numbers its words (`seq`, from 1 per call) and names the
 * call in its final event (`llm_call_id`) gets more: a word heard twice (a
 * reconnect replays them) is told once, a gap in the numbering marks the
 * call as partial, and the call's final message replaces the live words —
 * the final is what the model said; the live words were a preview of it.
 */
import type { AgentExecution, LLMCall, ToolCall } from '@/types';
import type {
  AgentStory,
  StoryItem,
  StoryItemKind,
  StoryText,
  StoryThinking,
  StoryTool,
  StreamChunk,
} from './agentStory';
import { asList } from './asList';
import { ensureUTC } from './utils';

/** Is this agent a Pi agent step's turn? Its page uses this module. */
export function isPiAgent(agent: unknown): boolean {
  if (!agent || typeof agent !== 'object') return false;
  const a = agent as {
    executed_by?: unknown;
    type?: unknown;
    agent_config?: { type?: unknown } | null;
    agent_config_snapshot?: { agent?: { type?: unknown } | null } | null;
  };
  return a.executed_by === 'pi'
    || a.type === 'pi'
    || a.agent_config?.type === 'pi'
    || a.agent_config_snapshot?.agent?.type === 'pi';
}

export function newStory(): AgentStory {
  return {
    items: [],
    streamedCalls: new Set(),
    toolIds: new Set(),
    seqs: new Map(),
    finalCalls: new Set(),
    gapCalls: new Set(),
  };
}

/** The longest text one story item keeps; the run's record keeps it all. */
export const STORY_TEXT_LIMIT = 40_000;
/** The longest progress report of a running tool shown. */
export const TOOL_PROGRESS_LIMIT = 2_000;

/** Set `item.text` to `text`, keeping at most STORY_TEXT_LIMIT characters. */
function setBounded(item: StoryText | StoryThinking, text: string): void {
  if (text.length > STORY_TEXT_LIMIT) {
    item.text = text.slice(0, STORY_TEXT_LIMIT);
    item.clipped = text.length - STORY_TEXT_LIMIT;
  } else {
    item.text = text;
    delete item.clipped;
  }
}

function addBounded(item: StoryText | StoryThinking, more: string): void {
  if (item.clipped) {
    item.clipped += more.length;
    return;
  }
  setBounded(item, item.text + more);
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

/* ------------------------------------------------------------------ */
/* Live: words and tool steps as they arrive                           */
/* ------------------------------------------------------------------ */

/**
 * Is this numbered chunk new? Drops one heard already (a reconnect replays
 * them) and notes a gap when some never arrived.
 */
function isNew(story: AgentStory, key: string, seq: number, gapOf?: string): boolean {
  story.seqs ??= new Map();
  const last = story.seqs.get(key) ?? 0;
  if (seq <= last) return false;
  if (gapOf && seq > last + 1) {
    story.gapCalls ??= new Set();
    story.gapCalls.add(gapOf);
  }
  story.seqs.set(key, seq);
  return true;
}

/**
 * Add a streamed chunk to the story.
 *
 * Words of the same kind from the same call join the item they belong to,
 * so the story reads as paragraphs, not as a thousand fragments. A chunk
 * that ends a call closes its items: the next call starts new ones.
 */
export function appendChunk(story: AgentStory, chunk: StreamChunk, at?: string): boolean {
  const callId = chunk.call_id ?? undefined;
  if (chunk.chunk_type === 'tool_progress') {
    // A running tool's output so far: it updates that step, it is not words.
    progressTool(story, chunk);
    return false;
  }
  if (callId && chunk.seq != null) {
    const told = !!story.finalCalls?.has(callId);
    if (!isNew(story, callId, chunk.seq, told ? undefined : callId)) return false;
    // The final message already told this call: the words are new to the page, not to the story.
    if (told) return true;
  } else if (callId && story.finalCalls?.has(callId)) {
    // Unnumbered words of a call whose final message is in: a late or repeated copy.
    return false;
  }
  if (callId) story.streamedCalls.add(callId);

  if (chunk.content) {
    const kind: StoryItemKind = chunk.chunk_type === 'thinking' ? 'thinking' : 'text';
    // A tool call being written is its own line: it asks for a step, it is not one.
    const request = chunk.chunk_type === 'tool_call';
    const partial = !!(callId && story.gapCalls?.has(callId));
    const last = story.items[story.items.length - 1];
    if (
      last &&
      (last.kind === 'text' || last.kind === 'thinking') &&
      last.kind === kind &&
      !last.closed &&
      (last.callId ?? undefined) === callId &&
      !!(last as StoryText).request === request &&
      !(last as StoryText).error
    ) {
      addBounded(last, chunk.content);
      if (partial) last.partial = true;
    } else {
      const item: StoryText | StoryThinking = kind === 'thinking'
        ? { kind: 'thinking', id: nextId('think'), text: '', at, callId }
        : { kind: 'text', id: nextId('text'), text: '', at, callId, ...(request ? { request } : {}) };
      setBounded(item, chunk.content);
      if (partial) item.partial = true;
      story.items.push(item);
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
  return true;
}

/**
 * A running tool reported its output so far. Each report is the whole output
 * up to now, so it replaces the last one; an older report arriving late is dropped.
 */
function progressTool(story: AgentStory, chunk: StreamChunk): void {
  const toolId = chunk.call_id ?? undefined;
  if (!toolId) return;
  if (chunk.seq != null && !isNew(story, `progress:${toolId}`, chunk.seq)) return;
  for (const item of story.items) {
    if (item.kind === 'tool' && item.toolId === toolId && item.status === 'running') {
      const text = chunk.content ?? '';
      item.progress = text.length > TOOL_PROGRESS_LIMIT ? text.slice(-TOOL_PROGRESS_LIMIT) : text;
      return;
    }
  }
  // Its start has not reached the page (or it already ended): a report is only a preview.
}

/**
 * A model call's final message is in. It is what the model said: it replaces
 * the live words of that call (which may have missed some, or heard some
 * twice), adds what the page never heard, and says plainly if the call failed.
 *
 * A field left `null`/`undefined` says nothing; an empty string says "none".
 */
export function reconcileCall(
  story: AgentStory,
  final: {
    callId: string;
    text?: string | null;
    thinking?: string | null;
    error?: string | null;
    at?: string;
  },
): void {
  const { callId } = final;
  story.finalCalls ??= new Set();
  story.finalCalls.add(callId);
  story.streamedCalls.add(callId);
  story.gapCalls?.delete(callId);
  replaceWords(story, callId, 'thinking', final.thinking, final.at);
  replaceWords(story, callId, 'text', final.text, final.at);
  if (final.error) {
    const id = `err-${callId}`;
    const had = story.items.find((i) => i.id === id);
    if (had && had.kind === 'text') {
      had.text = final.error;
    } else {
      story.items.push({ kind: 'text', id, text: final.error, error: true, closed: true, callId, at: final.at });
    }
  }
  for (const item of story.items) {
    if (item.callId !== callId || item.kind === 'tool') continue;
    item.closed = true;
    delete item.partial;
  }
}

/**
 * A call's final message as the run's record has it, once the call has ended.
 * A page that lost the call's final event (with its connection) reads it here.
 */
export function storedFinal(
  agent: Pick<AgentExecution, 'llm_calls'> | null | undefined,
  id: string,
): Parameters<typeof reconcileCall>[1] | null {
  for (const call of asList(agent?.llm_calls)) {
    if (callId(call) !== id) continue;
    if (call.status !== 'completed' && call.status !== 'failed') return null;
    return {
      callId: id,
      text: call.response ?? null,
      thinking: call.thinking ?? null,
      error: call.status === 'failed' ? (call.error_message || 'The model call failed.') : null,
      at: call.start_time ?? undefined,
    };
  }
  return null;
}

/**
 * How a tool step ended, as the run's record has it, once it has. A page that
 * lost the step's end (with its connection) reads it here.
 */
export function storedToolEnd(
  agent: Pick<AgentExecution, 'tool_calls'> | null | undefined,
  id: string,
): Parameters<typeof finishTool>[1] | null {
  for (const call of asList(agent?.tool_calls)) {
    if (toolId(call) !== id) continue;
    const status = String(call.status ?? '');
    if (!status || status === 'running' || status === 'pending') return null;
    return {
      toolId: id,
      exact: true,
      toolName: call.tool_name,
      status: status === 'failed' ? 'failed' : 'completed',
      durationSeconds: call.duration_seconds ?? undefined,
      result: call.output_data,
      error: call.error_message ?? undefined,
    };
  }
  return null;
}

function replaceWords(
  story: AgentStory,
  callId: string,
  kind: 'text' | 'thinking',
  value: string | null | undefined,
  at?: string,
): void {
  if (value == null) return;
  const mine = story.items.filter(
    (i): i is StoryText | StoryThinking =>
      i.kind === kind && i.callId === callId && !(i as StoryText).request && !(i as StoryText).error,
  );
  if (mine.length > 0) {
    const [first, ...rest] = mine;
    if (value) setBounded(first, value);
    const drop = new Set<StoryItem>(value ? rest : mine);
    story.items = story.items.filter((i) => !drop.has(i));
    return;
  }
  if (!value) return;
  const item: StoryText | StoryThinking = kind === 'thinking'
    ? { kind: 'thinking', id: `final-think-${callId}`, text: '', at, callId, closed: true }
    : { kind: 'text', id: `final-text-${callId}`, text: '', at, callId, closed: true };
  setBounded(item, value);
  // Thinking goes before the call's first item; words after its last.
  const idx = story.items.map((i) => i.callId).lastIndexOf(callId);
  const firstIdx = story.items.findIndex((i) => i.callId === callId);
  if (kind === 'thinking' && firstIdx >= 0) story.items.splice(firstIdx, 0, item);
  else if (idx >= 0) story.items.splice(idx + 1, 0, item);
  else story.items.push(item);
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
 * order they were asked for. An `exact` id (the producer's own call id, which
 * its start carried too) is never matched by name: two calls of one tool can
 * run at once, and a start this page missed must not close the other.
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
    exact?: boolean;
  },
): void {
  let open: StoryTool | undefined;
  for (const item of story.items) {
    if (item.kind !== 'tool') continue;
    // Its own step, even one already ended: an end told twice is still one step.
    if (step.toolId && item.toolId === step.toolId) {
      open = item;
      break;
    }
    if (item.status !== 'running') continue;
    if (step.exact && step.toolId) continue;
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
  delete open.progress;
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
  // The producer's call id when it gave one: the id its live events carry too.
  return call.call_id ?? call.id ?? call.tool_execution_id ?? '';
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
      const item: StoryThinking = { kind: 'thinking', id: `stored-think-${id}`, text: '', at, callId: id, closed: true };
      setBounded(item, call.thinking);
      out.push(item);
    }
    if (call.response) {
      const item: StoryText = { kind: 'text', id: `stored-text-${id}`, text: '', at, callId: id, closed: true };
      setBounded(item, call.response);
      out.push(item);
    }
    if (call.error_message) {
      out.push({
        kind: 'text',
        id: `stored-err-${id}`,
        text: call.error_message,
        at,
        callId: id,
        closed: true,
        error: true,
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

/**
 * A stored time comes without a zone (the server keeps UTC); a live one carries
 * its zone. Read both as UTC, or a page that joins halfway puts what it heard
 * before what happened earlier wherever the browser is not on UTC.
 */
function parseTime(at: string | null | undefined): number {
  return at ? Date.parse(ensureUTC(at)) : NaN;
}

function timeOf(item: StoryItem): number {
  const t = parseTime(item.at);
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
  agent: (Pick<AgentExecution, 'llm_calls' | 'tool_calls'> & Partial<Pick<AgentExecution, 'status' | 'error_message'>>) | null | undefined,
  live: AgentStory | undefined,
): StoryItem[] {
  const story = wovenStory(agent, live);
  // How the agent ended, when it failed: the last word of its story, never lost.
  const failure = agentFailure(agent);
  return failure ? [...story, failure] : story;
}

function agentFailure(
  agent: (Partial<Pick<AgentExecution, 'status' | 'error_message'>> & { error?: unknown }) | null | undefined,
): StoryText | null {
  if (agent?.status !== 'failed') return null;
  const said = agent.error_message ?? agent.error;
  const text = typeof said === 'string' && said.trim() ? said : 'The agent failed.';
  return { kind: 'text', id: 'agent-failure', text, error: true, closed: true };
}

function wovenStory(
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
    const t = parseTime(call.start_time);
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
