/**
 * Script logs on the page: the store that keeps one window per attempt being watched, and the
 * view the live panel and the full-screen agent view show. The log API is a small fake server
 * behind `authFetch`; the run's socket is played by calling the store as the socket hook does.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, cleanup, waitFor, within } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { useScriptLogStore, farBehind } from '@/store/scriptLogStore';
import { ScriptLogView } from '@/components/scriptlog/ScriptLogView';
import { LivePanel } from '@/components/live/LivePanel';
import { WINDOW_MAX_CHARS } from '@/lib/scriptLog';
import type { AgentExecution, NodeExecution, WorkflowExecution } from '@/types';
import { openBigView, view } from './bigViewHarness';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/authFetch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/authFetch')>()),
  authFetch,
}));

const RUN = 'run-script-log';
const T = '2026-10-02T12:00:00.000+00:00';

type Entry = { stream?: string; text: string; kind?: string; outcome?: string; exit_code?: number };
type RawRow = Record<string, unknown> & { seq: number; attempt_id: string };

/** The rows "saved" per attempt, as the server would have them. */
const saved = new Map<string, RawRow[]>();
const ROWS_PER_PAGE = 3;
let requests: string[] = [];

function rawRow(attempt: string, seq: number, entries: Entry[] | string, extra: Record<string, unknown> = {}): RawRow {
  const list = typeof entries === 'string' ? [{ text: entries }] : entries;
  const bytes = list.reduce((n, e) => n + e.text.length, 0);
  return {
    attempt_id: attempt,
    seq,
    entries: list.map((e) => ({ stream: 'stdout', t: T, ...e })),
    bytes,
    saved_bytes: seq * 10,
    dropped_bytes: 0,
    lost_bytes: 0,
    limit: 10_000_000,
    truncated: false,
    ...extra,
  };
}

function save(attempt: string, ...rows: RawRow[]) {
  saved.set(attempt, [...(saved.get(attempt) ?? []), ...rows]);
}

/** GET /api/runs/<run>/agents/<attempt>/log, paged by rows rather than bytes. */
async function fakeServer(url: string) {
  requests.push(url);
  const u = new URL(url, 'http://test');
  const m = u.pathname.match(/^\/api\/runs\/([^/]+)\/agents\/([^/]+)\/log$/);
  const run = m ? decodeURIComponent(m[1]) : '';
  const rows = m ? saved.get(decodeURIComponent(m[2])) : undefined;
  if (run !== RUN || !rows) return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) };
  const after = u.searchParams.get('after_seq');
  const before = u.searchParams.get('before_seq');
  let chosen: RawRow[];
  if (after != null) chosen = rows.filter((r) => r.seq > Number(after)).slice(0, ROWS_PER_PAGE);
  else if (before != null) chosen = rows.filter((r) => r.seq < Number(before)).slice(-ROWS_PER_PAGE);
  else chosen = rows.slice(-ROWS_PER_PAGE);
  const newest = rows.length ? rows[rows.length - 1].seq : 0;
  const first = chosen.length ? chosen[0].seq : 0;
  const last = chosen.length ? chosen[chosen.length - 1].seq : 0;
  const body = {
    execution_id: RUN,
    rows: chosen,
    first_seq: first,
    last_seq: last,
    newest_seq: newest,
    has_more_before: first > 1,
    has_more_after: chosen.length ? last < newest : false,
  };
  return { ok: true, status: 200, json: async () => body };
}

function agent(id: string, over: Partial<AgentExecution> = {}): AgentExecution {
  return {
    id,
    agent_name: 'talker',
    status: 'running',
    start_time: '2026-10-02T12:00:00Z',
    end_time: null,
    duration_seconds: null,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    total_llm_calls: 0,
    total_tool_calls: 0,
    llm_calls: [],
    tool_calls: [],
    agent_config_snapshot: { agent: { agent: { type: 'script' } } },
    ...over,
  } as AgentExecution;
}

function loadRun(agents: AgentExecution[], status = 'running') {
  const node = {
    id: 'node-talk',
    name: 'talk',
    type: 'stage',
    status,
    start_time: '2026-10-02T12:00:00Z',
    end_time: null,
    duration_seconds: null,
    cost_usd: 0,
    total_tokens: 0,
    agents,
  } as unknown as NodeExecution;
  const run = {
    id: RUN,
    workflow_name: 'ci_script_log',
    status,
    start_time: '2026-10-02T12:00:00Z',
    end_time: null,
    duration_seconds: null,
    nodes: [node],
    stages: [node],
    total_tokens: 0,
    total_cost_usd: 0,
  } as unknown as WorkflowExecution;
  act(() => {
    useExecutionStore.getState().applySnapshot(run);
  });
}

/** A row arriving over the run's socket, the way hooks/useWorkflowWebSocket.ts hands it on. */
function live(row: unknown, executionId: string | undefined = RUN) {
  act(() => {
    useScriptLogStore.getState().offerLive(executionId, row);
  });
}

const lineTexts = () => screen.queryAllByTestId('script-log-line').map((el) => el.lastElementChild?.textContent);

beforeEach(() => {
  saved.clear();
  requests = [];
  authFetch.mockReset();
  authFetch.mockImplementation(fakeServer);
  useExecutionStore.getState().reset();
  useScriptLogStore.getState().reset();
});

afterEach(() => {
  cleanup();
  useScriptLogStore.getState().reset();
});

describe('the store', () => {
  it('keeps an attempt while someone watches it, and frees it when the last one stops', () => {
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'a1');
    store.watch(RUN, 'a1');
    store.unwatch('a1');
    expect(useScriptLogStore.getState().attempts.a1?.watchers).toBe(1);
    store.unwatch('a1');
    expect(useScriptLogStore.getState().attempts.a1).toBeUndefined();
  });

  it('ignores rows for attempts nobody watches, for another run, and anything malformed', () => {
    const store = useScriptLogStore.getState();
    store.offerLive(RUN, rawRow('nobody', 1, 'x\n'));
    expect(useScriptLogStore.getState().attempts).toEqual({});
    store.watch(RUN, 'a1');
    const before = useScriptLogStore.getState().attempts.a1;
    store.offerLive('another-run', rawRow('a1', 1, 'x\n'));
    for (const bad of [null, 'row', 5, [], { seq: '1', attempt_id: 'a1' }, { seq: 1, attempt_id: 'a1', entries: 7 },
      { seq: 2, attempt_id: 'a1', entries: [null, { text: 1 }] }, { attempt_id: 'a1' }]) {
      expect(() => store.offerLive(RUN, bad)).not.toThrow();
    }
    const after = useScriptLogStore.getState().attempts.a1;
    expect(after.win.rows).toEqual([]);
    expect(before.win.rows).toEqual([]);
  });

  it('keeps two attempts of one agent name apart', async () => {
    save('a1', rawRow('a1', 1, 'first try\n'));
    save('a2', rawRow('a2', 1, 'second try\n'));
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'a1');
    store.watch(RUN, 'a2');
    await store.loadTail('a1');
    await store.loadTail('a2');
    store.offerLive(RUN, rawRow('a2', 2, 'more of the second\n'));
    const { attempts } = useScriptLogStore.getState();
    expect(attempts.a1.win.rows.map((r) => r.entries[0].text)).toEqual(['first try\n']);
    expect(attempts.a2.win.rows.map((r) => r.entries[0].text)).toEqual(['second try\n', 'more of the second\n']);
  });

  it('an agent with no saved log is an error that asking again cannot fix', async () => {
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'ghost');
    await store.loadTail('ghost');
    const a = useScriptLogStore.getState().attempts.ghost;
    expect(a.error).toMatch(/no saved log/);
    expect(a.retryable).toBe(false);
  });

  it('a slow answer for a log that was closed and opened again is dropped', async () => {
    save('a1', rawRow('a1', 1, 'old\n'));
    let release: () => void = () => {};
    authFetch.mockImplementationOnce((url: string) => new Promise((resolve) => {
      release = () => resolve(fakeServer(url));
    }));
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'a1');
    const slow = store.loadTail('a1');
    store.unwatch('a1');
    store.watch(RUN, 'a1');
    release();
    await slow;
    const a = useScriptLogStore.getState().attempts.a1;
    expect(a.win.loaded).toBe(false);
    expect(a.loading).toBeNull();
  });

  it('after a reconnect every open log at its end catches up', async () => {
    save('a1', rawRow('a1', 1, 'x\n'));
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'a1');
    await store.loadTail('a1');
    expect(useScriptLogStore.getState().attempts.a1.win.needsCatchUp).toBe(false);
    store.markStale();
    expect(useScriptLogStore.getState().attempts.a1.win.needsCatchUp).toBe(true);
  });

  it('far behind a fast script, it reads the newest page instead of every row in between', async () => {
    save('a1', rawRow('a1', 1, 'x\n'));
    const store = useScriptLogStore.getState();
    store.watch(RUN, 'a1');
    await store.loadTail('a1');
    store.offerLive(RUN, rawRow('a1', 900, '', { stub: true, saved_bytes: WINDOW_MAX_CHARS * 3 }));
    expect(farBehind(useScriptLogStore.getState().attempts.a1.win)).toBe(true);
    save('a1', ...[898, 899, 900].map((s) => rawRow('a1', s, `row ${s}\n`, { saved_bytes: WINDOW_MAX_CHARS * 3 })));
    requests = [];
    useScriptLogStore.setState((s) => ({ attempts: { ...s.attempts, a1: { ...s.attempts.a1, lastReadAt: 0 } } }));
    await store.loadAfter('a1');
    expect(requests).toHaveLength(1);
    expect(requests[0]).not.toMatch(/after_seq|before_seq/);
    expect(useScriptLogStore.getState().attempts.a1.win.endSeq).toBe(900);
  });
});

describe('the log view', () => {
  it('shows saved lines as text, labelled by stream and timed, with the limit', async () => {
    save('a1',
      rawRow('a1', 1, [{ text: 'step 1\n' }, { stream: 'stderr', text: 'careful\n' }]),
      rawRow('a1', 2, '<img src=x onerror="window.__pwned=1"> & <b>not bold</b>\n'));
    loadRun([agent('a1')]);
    const { container } = render(<ScriptLogView attemptId="a1" />);
    await waitFor(() => expect(lineTexts()).toHaveLength(3));
    expect(lineTexts()).toEqual(['step 1', 'careful', '<img src=x onerror="window.__pwned=1"> & <b>not bold</b>']);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    const [, errLine] = screen.getAllByTestId('script-log-line');
    expect(errLine).toHaveAttribute('data-stream', 'stderr');
    expect(within(errLine).getByText('err')).toBeInTheDocument();
    expect(within(errLine).getByRole('time')).toHaveAttribute('datetime', T);
    expect(screen.getByTestId('script-log-status')).toHaveTextContent('Live');
    expect(screen.getByTestId('script-log-limit')).toHaveTextContent('20 B saved · limit 10 MB');
  });

  it('adds rows as the socket sends them, and says how it ended', async () => {
    save('a1', rawRow('a1', 1, 'starting\n'));
    loadRun([agent('a1')]);
    render(<ScriptLogView attemptId="a1" />);
    await waitFor(() => expect(lineTexts()).toEqual(['starting']));
    live(rawRow('a1', 1, 'starting\n'));
    live(rawRow('a1', 2, 'half a line, '));
    live(rawRow('a1', 3, 'then the rest\n'));
    expect(lineTexts()).toEqual(['starting', 'half a line, then the rest']);
    live(rawRow('a1', 4, [{ stream: 'temper', text: '[failed: exit code 3]', kind: 'end', outcome: 'failed', exit_code: 3 }],
      { end: { outcome: 'failed', exit_code: 3 } }));
    expect(screen.getByTestId('script-log-status')).toHaveTextContent('Failed · exit code 3');
    expect(screen.getByTestId('script-log')).toHaveAttribute('data-status', 'failed');
    const note = screen.getByTestId('script-log-note');
    expect(note).toHaveAttribute('data-kind', 'end');
    expect(note).toHaveTextContent('[failed: exit code 3]');
  });

  it('catches up on rows missed while the socket was away', async () => {
    save('a1', rawRow('a1', 1, 'one\n'));
    loadRun([agent('a1')]);
    render(<ScriptLogView attemptId="a1" />);
    await waitFor(() => expect(lineTexts()).toEqual(['one']));
    // Rows are sent once saved: the server has 2 to 4, but only 4 came over the socket.
    save('a1', rawRow('a1', 2, 'two\n'), rawRow('a1', 3, 'three\n'), rawRow('a1', 4, 'four\n'));
    live(rawRow('a1', 4, 'four\n'));
    expect(lineTexts()).toEqual(['one']);
    await waitFor(() => expect(lineTexts()).toEqual(['one', 'two', 'three', 'four']), { timeout: 3000 });
    expect(requests.at(-1)).toMatch(/after_seq=1\b/);
    // The same rows again, as a reconnect might send them, change nothing.
    live(rawRow('a1', 3, 'three\n'));
    live(rawRow('a1', 4, 'four\n'));
    expect(lineTexts()).toEqual(['one', 'two', 'three', 'four']);
  });

  it('makes the limit plain when it was reached', async () => {
    save('a1',
      rawRow('a1', 1, 'x'.repeat(10), { saved_bytes: 2_000_000, limit: 2_000_000 }),
      rawRow('a1', 2, [{ stream: 'temper', text: '[log limit of 2,000,000 bytes reached: the rest is not saved]', kind: 'truncated' }],
        { saved_bytes: 2_000_000, limit: 2_000_000, truncated: true, dropped_bytes: 3_000_000 }));
    loadRun([agent('a1', { agent_config_snapshot: { agent: { agent: { type: 'script', log_max_bytes: 2_000_000 } } } } as Partial<AgentExecution>)]);
    render(<ScriptLogView attemptId="a1" />);
    await waitFor(() => expect(screen.getByTestId('script-log-truncated')).toBeInTheDocument());
    expect(screen.getByTestId('script-log-truncated')).toHaveTextContent('Limit reached: 3 MB not saved');
    expect(screen.getByTestId('script-log-limit')).toHaveTextContent('2 MB saved · limit 2 MB');
    expect(screen.getByTestId('script-log-note')).toHaveAttribute('data-kind', 'truncated');
  });

  it('reads older output on request', async () => {
    save('a1', ...[1, 2, 3, 4, 5].map((s) => rawRow('a1', s, `line ${s}\n`)));
    loadRun([agent('a1', { status: 'completed' })], 'completed');
    render(<ScriptLogView attemptId="a1" />);
    await waitFor(() => expect(lineTexts()).toEqual(['line 3', 'line 4', 'line 5']));
    // It has ended without its end note here, so it reads once more for the rest first.
    await waitFor(() => expect(requests.some((r) => /after_seq=5\b/.test(r))).toBe(true));
    await waitFor(() => expect(screen.getByTestId('script-log-older')).toBeEnabled());
    act(() => {
      screen.getByTestId('script-log-older').click();
    });
    await waitFor(() => expect(lineTexts()).toEqual(['line 1', 'line 2', 'line 3', 'line 4', 'line 5']));
    expect(screen.queryByTestId('script-log-older')).toBeNull();
  });

  it('says so when nothing was saved', async () => {
    save('a1');
    loadRun([agent('a1', { status: 'completed' })], 'completed');
    render(<ScriptLogView attemptId="a1" />);
    expect(await screen.findByTestId('script-log-empty')).toHaveTextContent(/Nothing was saved/);
    expect(screen.getByTestId('script-log-status')).toHaveTextContent('Nothing saved');
  });

  it('shows the error, without the lines, when the log cannot be read', async () => {
    loadRun([agent('ghost')]);
    render(<ScriptLogView attemptId="ghost" />);
    expect(await screen.findByTestId('script-log-error')).toHaveTextContent(/no saved log/);
  });
});

describe('where the log shows', () => {
  it('the live panel shows a script agent its log instead of a story', async () => {
    save('a1', rawRow('a1', 1, 'hello from the script\n'));
    loadRun([agent('a1')]);
    render(<LivePanel />);
    const log = await screen.findByTestId('script-log');
    expect(log).toHaveAttribute('data-attempt', 'a1');
    await waitFor(() => expect(lineTexts()).toEqual(['hello from the script']));
  });

  it('a model agent keeps its story', () => {
    loadRun([agent('m1', { agent_config_snapshot: { agent: { type: 'llm', model: 'm', provider: 'p' } } } as Partial<AgentExecution>)]);
    render(<LivePanel />);
    expect(screen.queryByTestId('script-log')).toBeNull();
  });

  it('the full-screen view of a script agent opens on its log', async () => {
    save('a1', rawRow('a1', 1, 'from the big view\n'));
    loadRun([agent('a1', { status: 'completed' })], 'completed');
    openBigView('agent', 'a1');
    const fold = within(view()).getByTestId('bv-script-log');
    await waitFor(() => expect(within(fold).getAllByTestId('script-log-line')).toHaveLength(1));
    expect(within(fold).getByTestId('script-log-line')).toHaveTextContent('from the big view');
  });
});
