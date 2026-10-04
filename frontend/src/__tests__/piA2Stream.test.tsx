/**
 * Pi's stream in the run view (A2 proof).
 *
 * The fixtures are real Pi 0.87.1 RPC output from scripted, offline model
 * calls (no provider, no network), mapped by temper_ai/llm/pi_stream.py,
 * recorded by Temper's EventRecorder and sent through its real
 * WebSocketManager; tests/test_llm/pi_a2_replay.py writes them. Each holds
 * every message a page received, the run's record at the start and halfway,
 * and the record at the end. These tests feed exactly those messages to the
 * page's store and view, in order and in the ways a connection goes wrong.
 */
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup, fireEvent } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { AgentStoryView } from '@/components/live/AgentStoryView';
import {
  STORY_TEXT_LIMIT,
  TOOL_PROGRESS_LIMIT,
  appendChunk,
  fullStory,
  newStory,
  reconcileCall,
} from '@/lib/piStory';
import type { StoryItem, StoryTool } from '@/lib/agentStory';
import type { WorkflowExecution, WSEvent } from '@/types';
import s1 from './fixtures/pi_a2/s1_stream.json';
import s2 from './fixtures/pi_a2/s2_errors.json';
import s3 from './fixtures/pi_a2/s3_large_untrusted.json';
import s4 from './fixtures/pi_a2/s4_retry_recover.json';
import s5 from './fixtures/pi_a2/s5_retry_fail.json';
import s6 from './fixtures/pi_a2/s6_abort.json';
import s7 from './fixtures/pi_a2/s7_compaction.json';

interface Chunk {
  agent_id?: string;
  content: string;
  chunk_type?: string;
  call_id?: string | null;
  seq?: number | null;
  done?: boolean;
}

interface Msg {
  type: string;
  event_type?: string;
  timestamp?: string;
  data?: Record<string, unknown> & { chunks?: Chunk[] };
}

interface StoredCall {
  id: string;
  status: string;
  response?: string | null;
  thinking?: string | null;
  error_message?: string | null;
  total_tokens?: number | null;
}

interface StoredAgent {
  status: string;
  error_message?: string | null;
  total_tokens?: number | null;
  llm_calls?: StoredCall[];
  tool_calls?: Array<{ call_id?: string | null; status: string }>;
}

interface Fixture {
  scenario: string;
  agent_id: string;
  live: Msg[];
  start: { index: number; snapshot: unknown };
  mid: { index: number; snapshot: unknown };
  final: unknown;
  outcome: {
    status: string;
    errors: string[];
    tokens: Record<string, number>;
    structured_output: Record<string, unknown> | null;
  };
}

const ALL = [s1, s2, s3, s4, s5, s6, s7].map((f) => f as unknown as Fixture);
const BY_NAME = Object.fromEntries(ALL.map((f) => [f.scenario, f])) as Record<string, Fixture>;
const NAMES = ALL.map((f) => f.scenario);
const SECRET = 'A2-SYNTH-SECRET';
const SYSTEM_MARKER = 'A2-FIXTURE: system message removed';

const S = () => useExecutionStore.getState();

function snapshot(wf: unknown) {
  act(() => S().applySnapshot(wf as WorkflowExecution));
}

function play(msgs: Msg[]) {
  act(() => {
    for (const m of msgs) S().applyEvent(m as unknown as WSEvent);
  });
}

function storyOf(f: Fixture): StoryItem[] {
  return fullStory(S().agents.get(f.agent_id), S().stories.get(f.agent_id));
}

function storedAgent(wf: unknown): StoredAgent {
  const nodes = (wf as { nodes: Array<{ agent?: StoredAgent; agents?: StoredAgent[] }> }).nodes;
  return (nodes[0].agent ?? nodes[0].agents?.[0]) as StoredAgent;
}

/** What a reader learns from a story: its words, thinking, steps and failures. */
function told(items: StoryItem[]) {
  const words: string[] = [];
  const thinking: string[] = [];
  const steps: string[] = [];
  const errors: string[] = [];
  for (const i of items) {
    if (i.kind === 'thinking') {
      if (i.text.trim()) thinking.push(i.text);
    } else if (i.kind === 'tool') {
      steps.push(`${i.toolId}:${i.status}`);
    } else if (i.error) {
      errors.push(i.text);
    } else if (!i.request && i.text.trim()) {
      words.push(i.text);
    }
  }
  return { words, thinking, steps: [...steps].sort(), errors };
}

/** The story a page shows when it opens the finished run: the record only. */
function reloaded(f: Fixture) {
  act(() => S().reset());
  snapshot(f.final);
  const out = told(storyOf(f));
  act(() => S().reset());
  return out;
}

function liveFromStart(f: Fixture) {
  snapshot(f.start.snapshot);
  play(f.live.slice(f.start.index));
}

const isBatch = (m: Msg) => m.event_type === 'llm_stream_batch';
const chunksOf = (m: Msg): Chunk[] => (isBatch(m) ? m.data?.chunks ?? [] : []);

/**
 * The same run as a producer that numbers its chunks would send it. Temper's chunk
 * plumbing does not carry the mapper's numbers today (the Pi step leaves it unchanged),
 * so the fixtures hold none; the page still uses numbers when a producer sends them.
 */
function numbered(f: Fixture): Fixture {
  const counts = new Map<string, number>();
  const live = (JSON.parse(JSON.stringify(f.live)) as Msg[]).map((m) => {
    for (const c of chunksOf(m)) {
      if (!c.call_id) continue;
      const key = c.chunk_type === 'tool_progress' ? `progress:${c.call_id}` : c.call_id;
      const n = (counts.get(key) ?? 0) + 1;
      counts.set(key, n);
      c.seq = n;
    }
    return m;
  });
  return { ...f, live };
}

// Stored times carry no zone and live ones do; on a UTC machine a mix-up between the two
// cannot show. Read every time here as a browser west of UTC would.
beforeAll(() => {
  vi.stubEnv('TZ', 'America/Los_Angeles');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  useExecutionStore.getState().reset();
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe('a Pi run read live and read back', () => {
  it('reads times as a browser west of UTC does', () => {
    // A stored time without a zone would be read as local time here.
    expect(new Date('2026-01-15T12:00:00').getTimezoneOffset()).toBe(480);
  });

  it.each(NAMES)('%s: a page open from the start ends with the story the record keeps', (name) => {
    const f = BY_NAME[name];
    const expected = reloaded(f);
    liveFromStart(f);
    expect(told(storyOf(f))).toEqual(expected);
    // Something was said or done in every scenario: the comparison is not empty.
    const e = expected;
    expect(e.words.length + e.steps.length + e.errors.length).toBeGreaterThan(0);
  });

  it.each(NAMES)('%s: a page that joins halfway tells the same story', (name) => {
    const f = BY_NAME[name];
    const expected = reloaded(f);
    snapshot(f.mid.snapshot);
    play(f.live.slice(f.mid.index));
    expect(told(storyOf(f))).toEqual(expected);
  });

  it.each(NAMES)('%s: a dropped connection loses words, not the story', (name) => {
    const f = BY_NAME[name];
    const expected = reloaded(f);
    const k = f.start.index + Math.max(1, Math.floor((f.mid.index - f.start.index) / 2));
    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, k));
    // Messages k .. mid never arrive. The page reconnects: a fresh snapshot,
    // one message it already had sent again, then everything after.
    snapshot(f.mid.snapshot);
    play([f.live[k - 1]]);
    play(f.live.slice(f.mid.index));
    expect(told(storyOf(f))).toEqual(expected);
  });

  it('a step whose end was lost with the connection ends as the record says', () => {
    const f = BY_NAME.s1_stream;
    const ends = f.live
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => m.event_type?.startsWith('tool.call.') && m.event_type !== 'tool.call.started');
    expect(ends.length).toBeGreaterThan(0);
    const lost = ends[ends.length - 1];
    const id = lost.m.data?.call_id as string;
    const expected = reloaded(f);
    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, lost.i));
    const step = () => storyOf(f).find((i): i is StoryTool => i.kind === 'tool' && i.toolId === id);
    expect(step()?.status).toBe('running');
    // The connection drops before the step's end; the page comes back after the run.
    snapshot(f.final);
    expect(step()?.status).toBe('completed');
    expect(told(storyOf(f))).toEqual(expected);
  });

  it.each(NAMES)('%s: every message arriving twice changes nothing', (name) => {
    const f = BY_NAME[name];
    const expected = reloaded(f);
    snapshot(f.start.snapshot);
    for (const m of f.live.slice(f.start.index)) play([m, m]);
    expect(told(storyOf(f))).toEqual(expected);
  });

  it('a slow page that takes every message in one go sees what a quick one sees', () => {
    const f = BY_NAME.s3_large_untrusted;
    snapshot(f.start.snapshot);
    for (const m of f.live.slice(f.start.index)) play([m]);
    const oneByOne = told(storyOf(f));
    act(() => S().reset());
    liveFromStart(f); // one act for all of it
    expect(told(storyOf(f))).toEqual(oneByOne);
  });
});

describe('what the page says while the agent works', () => {
  it('a tool call being written is a request, not a step that ran', () => {
    const f = BY_NAME.s1_stream;
    const firstRun = f.live.findIndex((m) => m.event_type === 'tool.call.started');
    expect(firstRun).toBeGreaterThan(f.start.index);
    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, firstRun));
    const { unmount } = render(<AgentStoryView items={storyOf(f)} live />);
    expect(screen.getAllByTestId('story-request').length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId('story-tool')).toHaveLength(0);
    unmount();

    const started = f.live.filter((m) => m.event_type === 'tool.call.started').length;
    play([f.live[firstRun], f.live[firstRun + 1]]);
    render(<AgentStoryView items={storyOf(f)} live />);
    expect(screen.getAllByTestId('story-tool')).toHaveLength(Math.min(2, started));
  });

  it('the chunks Temper sends carry no numbers (the Pi step leaves its plumbing as it was)', () => {
    for (const f of ALL) {
      for (const m of f.live) for (const c of chunksOf(m)) expect(c.seq ?? null).toBeNull();
    }
  });

  it("a running tool's progress replaces the last report and never piles up", () => {
    const f = numbered(BY_NAME.s1_stream);
    const bashStart = f.live.find(
      (m) => m.event_type === 'tool.call.started' && m.data?.tool_name === 'bash',
    );
    const bashId = bashStart?.data?.call_id as string;
    expect(bashId).toBeTruthy();
    const progressAt = f.live
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => chunksOf(m).some((c) => c.chunk_type === 'tool_progress' && c.call_id === bashId));
    expect(progressAt.length).toBeGreaterThan(1);
    const reports = progressAt.flatMap(({ m }) => chunksOf(m).filter((c) => c.chunk_type === 'tool_progress'));
    const last = reports[reports.length - 1];
    const lastAt = progressAt[progressAt.length - 1].i;
    const ended = f.live.findIndex(
      (m) => m.event_type?.startsWith('tool.call.') && m.event_type !== 'tool.call.started' && m.data?.call_id === bashId,
    );
    expect(ended).toBeGreaterThan(lastAt);

    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, progressAt[0].i));
    const card = () => S().streamingContent.get(f.agent_id)?.content ?? '';
    const before = card();
    play(f.live.slice(progressAt[0].i, lastAt + 1).filter((m) => progressAt.some(({ m: p }) => p === m) || !isBatch(m)));
    // Progress reports are not words: the card's text did not grow by them.
    expect(card()).toBe(before);

    const tool = () => storyOf(f).find((i): i is StoryTool => i.kind === 'tool' && i.toolId === bashId);
    expect(tool()).toMatchObject({ status: 'running', progress: last.content.slice(-TOOL_PROGRESS_LIMIT) });
    // Each report is the whole output so far: the step holds one, not their sum.
    const sum = reports.reduce((n, c) => n + c.content.length, 0);
    expect(sum).toBeGreaterThan(last.content.length);
    // The same reports again (a reconnect) and an older one late change nothing.
    play([f.live[lastAt], f.live[progressAt[0].i]]);
    expect(tool()).toMatchObject({ progress: last.content });

    const { unmount } = render(<AgentStoryView items={storyOf(f)} live />);
    expect(screen.getByTestId('story-tool-progress').textContent).toBe(last.content);
    unmount();

    play(f.live.slice(lastAt + 1, ended + 1));
    expect(tool()?.status).toBe('completed');
    expect(tool()).not.toHaveProperty('progress');
  });

  it('a model call ending is not the agent finishing', () => {
    const f = BY_NAME.s2_errors;
    const lastCallEnd = f.live.map((m) => m.event_type).lastIndexOf('llm.call.completed');
    const agentEnd = f.live.findIndex((m) => m.event_type === 'agent.failed');
    expect(lastCallEnd).toBeGreaterThan(0);
    expect(agentEnd).toBeGreaterThan(lastCallEnd);

    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, lastCallEnd + 1));
    expect(S().agents.get(f.agent_id)?.status).toBe('running');
    expect(storyOf(f).some((i) => i.id === 'agent-failure')).toBe(false);

    play(f.live.slice(lastCallEnd + 1));
    expect(S().agents.get(f.agent_id)?.status).toBe('failed');
    const items = storyOf(f);
    const end = items[items.length - 1];
    expect(end).toMatchObject({ kind: 'text', error: true, text: f.outcome.errors.join('; ') });
  });

  it('words that arrive after their call ended are not told twice', () => {
    const f = BY_NAME.s1_stream;
    const ends = f.live.map((m, i) => ({ m, i })).filter(({ m }) => m.event_type === 'llm.call.completed');
    const lastEnd = ends[ends.length - 1];
    const callId = lastEnd.m.data?.llm_call_id as string;
    const wordsAt = f.live.findIndex(
      (m) => chunksOf(m).some((c) => c.call_id === callId && c.chunk_type === 'content' && c.content),
    );
    expect(wordsAt).toBeGreaterThan(0);
    expect(wordsAt).toBeLessThan(lastEnd.i);
    const order = f.live.slice(f.start.index).filter((m) => m !== f.live[wordsAt]);
    order.splice(order.indexOf(lastEnd.m) + 1, 0, f.live[wordsAt]);

    const expected = reloaded(f);
    snapshot(f.start.snapshot);
    play(order);
    expect(told(storyOf(f))).toEqual(expected);
  });

  it('words out of order mark the reply partial until its final message puts it right', () => {
    const f = numbered(BY_NAME.s1_stream);
    const callId = f.live.find((m) => m.event_type === 'llm.call.started')?.data?.llm_call_id as string;
    const batches = f.live
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => chunksOf(m).some((c) => c.call_id === callId && c.seq != null && !c.done));
    expect(batches.length).toBeGreaterThan(1);
    const [a, b] = batches;
    const end = f.live.findIndex((m) => m.event_type === 'llm.call.completed' && m.data?.llm_call_id === callId);

    const expected = reloaded(f);
    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, a.i));
    play([b.m, a.m]);
    play(f.live.slice(b.i + 1, end).filter((m) => m !== a.m && m !== b.m));
    const { unmount } = render(<AgentStoryView items={storyOf(f)} live />);
    expect(screen.getAllByTestId('story-partial').length).toBeGreaterThan(0);
    unmount();

    play(f.live.slice(end));
    render(<AgentStoryView items={storyOf(f)} live={false} />);
    expect(screen.queryAllByTestId('story-partial')).toHaveLength(0);
    expect(told(storyOf(f))).toEqual(expected);
  });

  it("a call's final message has the last word over what streamed", () => {
    const f = BY_NAME.s1_stream;
    const ends = f.live.map((m, i) => ({ m, i })).filter(({ m }) => m.event_type === 'llm.call.completed');
    const { m: end, i: endAt } = ends[ends.length - 1];
    const callId = end.data?.llm_call_id as string;
    const reply = end.data?.response_content as string;
    const mine = (c: Chunk) => c.call_id === callId && c.chunk_type === 'content' && !!c.content;
    // A provider whose streamed words differ from its final message.
    const live = f.live.map((m) =>
      chunksOf(m).some(mine)
        ? { ...m, data: { ...m.data, chunks: chunksOf(m).map((c) => (mine(c) ? { ...c, content: c.content.toUpperCase() } : c)) } }
        : m,
    );
    const streamed = () =>
      (S().stories.get(f.agent_id)?.items ?? [])
        .filter((it) => it.kind === 'text' && it.callId === callId && !it.request && !it.error)
        .map((it) => (it as { text: string }).text)
        .join('');
    const expected = reloaded(f);
    snapshot(f.start.snapshot);
    play(live.slice(f.start.index, endAt));
    expect(reply.toUpperCase()).not.toBe(reply);
    expect(streamed()).toBe(reply.toUpperCase());
    play(live.slice(endAt));
    expect(streamed()).toBe(reply);
    expect(told(storyOf(f))).toEqual(expected);
  });

  it('streamed words, Unicode included, add up to the final reply', () => {
    const f = BY_NAME.s1_stream;
    const ends = f.live.map((m, i) => ({ m, i })).filter(({ m }) => m.event_type === 'llm.call.completed');
    const { m: end, i } = ends[ends.length - 1];
    const callId = end.data?.llm_call_id as string;
    const reply = end.data?.response_content as string;
    expect([...reply].some((ch) => ch.codePointAt(0)! > 0x7f)).toBe(true); // not only ASCII
    snapshot(f.start.snapshot);
    play(f.live.slice(f.start.index, i)); // everything before the final message
    const streamed = (S().stories.get(f.agent_id)?.items ?? [])
      .filter((it) => it.kind === 'text' && it.callId === callId && !it.request && !it.error)
      .map((it) => (it as { text: string }).text)
      .join('');
    expect(streamed).toBe(reply);
  });
});

describe('failures stay in sight', () => {
  it('a retried call that failed, the call that gave up and the agent all say so, live and after reload', () => {
    const f = BY_NAME.s5_retry_fail;
    const expected = reloaded(f);
    liveFromStart(f);
    const live = told(storyOf(f));
    expect(live).toEqual(expected);
    const failedCalls = storedAgent(f.final).llm_calls?.filter((c) => c.status === 'failed') ?? [];
    expect(failedCalls.length).toBe(2);
    expect(live.errors).toEqual([
      ...failedCalls.map((c) => c.error_message),
      f.outcome.errors.join('; '),
    ]);
    render(<AgentStoryView items={storyOf(f)} live={false} />);
    expect(screen.getAllByTestId('story-error')).toHaveLength(3);
  });

  it('an aborted reply keeps what it said and says it was stopped', () => {
    const f = BY_NAME.s6_abort;
    liveFromStart(f);
    const call = storedAgent(f.final).llm_calls?.[0];
    expect(call?.status).toBe('failed');
    const t = told(storyOf(f));
    expect(t.words).toEqual([call?.response]);
    expect(t.errors).toEqual([call?.error_message, f.outcome.errors.join('; ')]);
  });

  it('failed tools are red on the card and in the story', () => {
    const f = BY_NAME.s2_errors;
    liveFromStart(f);
    const steps = storyOf(f).filter((i) => i.kind === 'tool');
    expect(steps.length).toBe(2);
    expect(steps.every((s) => s.kind === 'tool' && s.status === 'failed' && !!s.error)).toBe(true);
    const card = S().streamingContent.get(f.agent_id)?.toolActivity ?? [];
    expect(card.map((t) => t.status)).toEqual(['failed', 'failed']);
  });

  it('a result that does not match its schema fails the agent visibly', () => {
    const f = BY_NAME.s2_errors;
    expect(f.outcome.status).toBe('failed');
    expect(f.outcome.structured_output).toBeNull();
    expect(storedAgent(f.final)).toMatchObject({ status: 'failed', error_message: f.outcome.errors.join('; ') });
    const ok = BY_NAME.s1_stream;
    expect(ok.outcome.status).toBe('completed');
    expect(ok.outcome.structured_output).toMatchObject({ status: expect.any(String), ticks: expect.any(Number) });
  });
});

describe('what the page holds', () => {
  it.each(NAMES)('%s: usage is counted once per model call', (name) => {
    const f = BY_NAME[name];
    const agent = storedAgent(f.final);
    const perCall = (agent.llm_calls ?? []).reduce((n, c) => n + (c.total_tokens ?? 0), 0);
    expect(perCall).toBe(f.outcome.tokens.total_tokens);
    expect(agent.total_tokens).toBe(f.outcome.tokens.total_tokens);
  });

  it('a very long reply is cut on the page, with what was cut said, live and after reload', () => {
    const f = BY_NAME.s3_large_untrusted;
    const longest = (storedAgent(f.final).llm_calls ?? [])
      .map((c) => c.response ?? '')
      .reduce((a, b) => (b.length > a.length ? b : a), '');
    expect(longest.length).toBeGreaterThan(STORY_TEXT_LIMIT);
    for (const read of ['live', 'reload'] as const) {
      act(() => S().reset());
      if (read === 'live') liveFromStart(f);
      else snapshot(f.final);
      const item = storyOf(f).find((i) => i.kind === 'text' && i.clipped);
      expect(item).toMatchObject({ text: longest.slice(0, STORY_TEXT_LIMIT), clipped: longest.length - STORY_TEXT_LIMIT });
      const { container, unmount } = render(<AgentStoryView items={storyOf(f)} live={false} />);
      expect(screen.getByTestId('story-clipped').textContent).toContain(
        (longest.length - STORY_TEXT_LIMIT).toLocaleString(),
      );
      expect((container.textContent ?? '').length).toBeLessThan(STORY_TEXT_LIMIT * 1.25);
      unmount();
    }
  });

  it('a flood of words for one call stays bounded', () => {
    const story = newStory();
    const piece = 'abcde';
    const n = 20_000;
    for (let seq = 1; seq <= n; seq++) {
      appendChunk(story, { content: piece, chunk_type: 'content', call_id: 'flood', seq });
    }
    const item = story.items[0] as { text: string; clipped?: number };
    expect(story.items).toHaveLength(1);
    expect(item.text.length).toBe(STORY_TEXT_LIMIT);
    expect(item.clipped).toBe(n * piece.length - STORY_TEXT_LIMIT);
    reconcileCall(story, { callId: 'flood', text: 'final' });
    expect(story.items).toMatchObject([{ text: 'final', closed: true }]);
    expect(story.items[0]).not.toHaveProperty('clipped');
  });

  it('untrusted text is shown as text: no markup of its own reaches the page', () => {
    const f = BY_NAME.s3_large_untrusted;
    const raw = JSON.stringify(f.final);
    expect(/<script|onerror=|javascript:/i.test(raw)).toBe(true); // the scenario planted some
    liveFromStart(f);
    const { container } = render(<AgentStoryView items={storyOf(f)} live={false} />);
    for (const step of screen.getAllByTestId('story-tool')) {
      fireEvent.click(step.querySelector('button') as HTMLButtonElement);
    }
    expect(container.querySelectorAll('script, iframe, object, embed, img, form, link, meta, style')).toHaveLength(0);
    for (const el of Array.from(container.querySelectorAll('*'))) {
      for (const attr of Array.from(el.attributes)) {
        expect(attr.name.toLowerCase().startsWith('on')).toBe(false);
        if (attr.name === 'href' || attr.name === 'src') expect(attr.value.toLowerCase()).not.toContain('javascript:');
      }
    }
  });

  it.each(NAMES)('%s: no secret and no system message reach the page', (name) => {
    const f = BY_NAME[name];
    const raw = JSON.stringify(f);
    expect(raw).not.toContain(SECRET);
    expect(raw).not.toContain(SYSTEM_MARKER);
    liveFromStart(f);
    const { container } = render(<AgentStoryView items={storyOf(f)} live={false} />);
    expect(container.innerHTML).not.toContain(SECRET);
  });
});
