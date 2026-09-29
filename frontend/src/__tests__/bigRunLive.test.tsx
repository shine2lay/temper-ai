/**
 * A big run replayed onto the run page: more agents than the node tree
 * keeps (loop rounds, parallel lanes, agents that started after the last
 * snapshot), more stream events than any buffer holds, and thinking in both
 * styles. Every agent is named in the live strip and in its panel, and a
 * click opens its panel.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent, waitFor, within, cleanup } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { LiveStreamBar } from '@/components/dag/LiveStreamBar';
import { AgentDetailPanel } from '@/components/panels/AgentDetailPanel';
import { useAgentLookup, MAX_LOOKUPS_PER_AGENT, LOOKUP_INTERVAL_MS } from '@/hooks/useAgentLookup';
import { snapshotFingerprint } from '@/hooks/useInitialData';
import { UNNAMED_AGENT } from '@/lib/liveAgents';
import { makeStreamBatchEvent } from './fixtures';
import type {
  AgentExecution,
  AgentIndexEntry,
  ExecutionStatus,
  NodeExecution,
  WorkflowExecution,
} from '@/types';

const RUN_ID = 'run-big-0001';
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/** Ids like the server's: a leak of one onto the page is easy to spot. */
function uuid(n: number): string {
  return `5a1d0c3e-7b2a-4c11-9e0f-${n.toString(16).padStart(12, '0')}`;
}

const NODES: Record<string, string[]> = {
  plan: ['planner', 'researcher', 'critic'],
  build: ['implementer', 'tester', 'linter'],
  review: ['reviewer', 'security', 'docs'],
  fix: ['fixer', 'verifier', 'reporter'],
};
const ROUNDS = 5;
/** Its last rounds run side by side, like dispatched lanes. */
const PARALLEL = 'implementer';
const PARALLEL_FROM = 3;

interface Planned {
  id: string;
  name: string;
  node: string;
  round: number;
  status: ExecutionStatus;
}

function planRun(): Planned[] {
  const out: Planned[] = [];
  let n = 1;
  for (const [node, names] of Object.entries(NODES)) {
    for (const name of names) {
      for (let round = 1; round <= ROUNDS; round++) {
        const running = round === ROUNDS || (name === PARALLEL && round >= PARALLEL_FROM);
        out.push({ id: uuid(n++), name, node, round, status: running ? 'running' : 'completed' });
      }
    }
  }
  return out;
}

const PLANNED = planRun();
/** Started after the page's snapshot: only the lookup can name them. */
const LATE: Planned[] = [1, 2, 3].map((i) => ({
  id: uuid(900 + i), name: `scout-${i}`, node: 'review', round: 1, status: 'running',
}));

function indexEntry(p: Planned): AgentIndexEntry {
  return {
    id: p.id,
    agent_name: p.name,
    round: p.round,
    status: p.status,
    node_id: `node-${p.node}`,
    node_name: p.node,
    start_time: '2026-09-28T10:00:00Z',
    end_time: p.status === 'completed' ? '2026-09-28T10:01:00Z' : null,
    duration_seconds: p.status === 'completed' ? 60 : null,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    estimated_cost_usd: 0.01,
    provider: 'claude_code',
    model: 'sonnet',
  };
}

function treeAgent(p: Planned): AgentExecution {
  return {
    id: p.id,
    agent_name: p.name,
    status: p.status,
    stage_execution_id: `node-${p.node}`,
    start_time: '2026-09-28T10:00:00Z',
    end_time: null,
    duration_seconds: null,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    estimated_cost_usd: 0.01,
    total_llm_calls: 1,
    total_tool_calls: 0,
    llm_calls: [],
    tool_calls: [],
    agent_config_snapshot: { agent: { provider: 'claude_code', model: 'sonnet', type: 'llm' } },
  };
}

/**
 * The run as the server sends it: the tree keeps the newest agent of each
 * name, the agent index names every agent started so far.
 */
function snapshot(): WorkflowExecution {
  const nodes: NodeExecution[] = Object.entries(NODES).map(([node, names]) => ({
    id: `node-${node}`,
    name: node,
    stage_name: node,
    type: 'stage',
    status: 'running',
    start_time: '2026-09-28T10:00:00Z',
    end_time: null,
    duration_seconds: null,
    agents: names.map((name) => treeAgent(PLANNED.filter((p) => p.name === name).at(-1)!)),
  })) as NodeExecution[];
  return {
    id: RUN_ID,
    workflow_name: 'epd_build',
    status: 'running',
    start_time: '2026-09-28T10:00:00Z',
    end_time: null,
    duration_seconds: null,
    nodes,
    stages: nodes,
    total_tokens: 0,
    total_cost_usd: 0,
    agent_index: PLANNED.map(indexEntry),
  } as WorkflowExecution;
}

/** Agents that stream thinking, each its own way. */
const TAGGED = PLANNED.find((p) => p.name === 'reviewer' && p.status === 'running')!;
const STREAMED = PLANNED.find((p) => p.name === 'fixer' && p.status === 'running')!;
const STREAM_EVENTS = 6_000;

/**
 * Replay the run's output: every agent of every round (a page opened late
 * gets the whole stream again), then the late agents, 6,000 events in all.
 */
function replayStream(): void {
  const { applyEvent } = useExecutionStore.getState();
  const everyone = [...PLANNED, ...LATE];
  for (let i = 0; i < STREAM_EVENTS; i++) {
    const p = everyone[i % everyone.length];
    const step = Math.floor(i / everyone.length);
    if (p.id === TAGGED.id) {
      // The Claude Code provider: thinking inside the text.
      applyEvent(makeStreamBatchEvent(p.id, [
        { content: `Checked file ${step}.\n<thinking>Is file ${step} safe?\nLooks fine.</thinking>\n` },
      ]));
    } else if (p.id === STREAMED.id) {
      // A provider with a thinking stream of its own.
      applyEvent(makeStreamBatchEvent(p.id, [
        { content: `Weighing fix ${step}.\n`, chunk_type: 'thinking' },
        { content: `Applied fix ${step}.\n` },
        { content: '', done: true },
      ]));
    } else {
      applyEvent(makeStreamBatchEvent(p.id, [{ content: `${p.name} step ${step}\n` }]));
    }
  }
}

function resetStore() {
  useExecutionStore.getState().reset();
}

function LivePage() {
  useAgentLookup(RUN_ID);
  const selection = useExecutionStore((s) => s.selection);
  return (
    <>
      <LiveStreamBar />
      {selection?.type === 'agent' && (
        <div data-testid="panel">
          <AgentDetailPanel agentId={selection.id} />
        </div>
      )}
    </>
  );
}

function mockAgentsEndpoint(agents: AgentIndexEntry[]) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === `/api/workflows/${RUN_ID}/agents`) {
      return new Response(JSON.stringify({ execution_id: RUN_ID, agents }), { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function stripTabs(): HTMLElement[] {
  const strip = screen.getByTestId('live-stream-bar');
  return within(strip).getAllByRole('button').filter((b) => b.title.startsWith('Show ') || b.title.startsWith('Open '));
}

describe('a big run on the run page', () => {
  beforeEach(() => {
    resetStore();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('names every agent in the live strip, including ones that started after the snapshot', async () => {
    const fetchMock = mockAgentsEndpoint([...PLANNED, ...LATE].map(indexEntry));
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    render(<LivePage />);
    act(() => replayStream());

    // The late agents stream before the page knows them: never shown as ids.
    expect(screen.getByTestId('live-stream-bar').textContent).not.toMatch(UUID_RE);

    await waitFor(() => expect(screen.getByText('scout-3')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalled();

    const running = [...PLANNED, ...LATE].filter((p) => p.status === 'running');
    const tabs = stripTabs();
    expect(tabs).toHaveLength(running.length);
    const labels = tabs.map((t) => t.textContent);
    for (const label of labels) {
      expect(label).not.toMatch(UUID_RE);
    }
    // Parallel lanes of one name are told apart by their round.
    expect(labels).toEqual(expect.arrayContaining(['implementer #3', 'implementer #4', 'implementer #5']));
    for (const p of running.filter((r) => r.name !== PARALLEL)) {
      expect(labels).toContain(p.name);
    }
    expect(useExecutionStore.getState().unknownAgentIds.size).toBe(0);
  });

  it('opens the panel of every agent in the strip', async () => {
    mockAgentsEndpoint([...PLANNED, ...LATE].map(indexEntry));
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    render(<LivePage />);
    act(() => replayStream());
    await waitFor(() => expect(screen.getByText('scout-1')).toBeInTheDocument());

    const count = stripTabs().length;
    for (let k = 0; k < count; k++) {
      const tab = stripTabs()[k];
      const label = tab.textContent ?? '';
      const name = label.replace(/ #\d+$/, '');
      // First click shows its output, the next opens its panel.
      if (!tab.title.startsWith('Open ')) fireEvent.click(tab);
      fireEvent.click(stripTabs()[k]);
      const panel = screen.getByTestId('panel');
      expect(within(panel).queryByText('Agent not found')).toBeNull();
      expect(within(panel).getByRole('heading', { level: 3 }).textContent).toBe(name);
      expect(panel.textContent).not.toMatch(UUID_RE);
    }
  });

  it('opens a panel with a name for every agent of the run, earlier rounds too', () => {
    mockAgentsEndpoint([]);
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    act(() => replayStream());
    for (const p of PLANNED) {
      const agent = useExecutionStore.getState().agents.get(p.id);
      expect(agent?.agent_name).toBe(p.name);
      const { unmount } = render(<AgentDetailPanel agentId={p.id} />);
      expect(screen.queryByText('Agent not found')).toBeNull();
      expect(screen.getByRole('heading', { level: 3 }).textContent).toBe(p.name);
      unmount();
    }
  });

  it('streams thinking in the strip, both styles', async () => {
    mockAgentsEndpoint([...PLANNED, ...LATE].map(indexEntry));
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    render(<LivePage />);
    act(() => replayStream());
    const lastStep = (p: Planned) => {
      const everyone = [...PLANNED, ...LATE];
      const at = everyone.findIndex((e) => e.id === p.id);
      return Math.floor((STREAM_EVENTS - 1 - at) / everyone.length);
    };

    // Tagged in the text (Claude Code): newest block, as thinking.
    fireEvent.click(stripTabs().find((t) => t.textContent === 'reviewer')!);
    let thinking = screen.getAllByTestId('live-thinking');
    expect(thinking.at(-1)!.textContent).toContain(`Is file ${lastStep(TAGGED)} safe?`);
    expect(screen.getByTestId('live-stream-bar').textContent).not.toContain('<thinking>');

    // Its own stream: shown where it came, between the text.
    fireEvent.click(stripTabs().find((t) => t.textContent === 'fixer')!);
    thinking = screen.getAllByTestId('live-thinking');
    expect(thinking.at(-1)!.textContent).toContain(`Weighing fix ${lastStep(STREAMED)}.`);
    expect(screen.getByTestId('live-stream-bar').textContent).toContain(`Applied fix ${lastStep(STREAMED)}.`);

    // Expanded shows all of it.
    fireEvent.click(screen.getByText('Expand'));
    thinking = screen.getAllByTestId('live-thinking');
    expect(thinking.length).toBeGreaterThan(10);
    expect(thinking[0].textContent).toContain('Weighing fix 0.');
  });

  it('keeps an agent in the strip after each model call ends', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    render(<LiveStreamBar />);
    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(makeStreamBatchEvent(STREAMED.id, [{ content: 'first call\n' }, { content: '', done: true }]));
      applyEvent(makeStreamBatchEvent(STREAMED.id, [{ content: 'second call\n' }]));
    });
    const fixer = stripTabs().find((t) => t.textContent === 'fixer');
    expect(fixer).toBeDefined();
    fireEvent.click(fixer!);
    expect(screen.getByTestId('live-stream-bar').textContent).toContain('second call');
    expect(useExecutionStore.getState().streamingContent.get(STREAMED.id)?.done).toBe(false);
  });

  it('shows an agent the server cannot name as unnamed, never by its id', async () => {
    vi.useFakeTimers();
    const fetchMock = mockAgentsEndpoint(PLANNED.map(indexEntry));
    const stray = uuid(999);
    act(() => {
      useExecutionStore.getState().applySnapshot(snapshot());
    });
    render(<LivePage />);
    act(() => {
      useExecutionStore.getState().applyEvent(makeStreamBatchEvent(stray, [{ content: 'who am I\n' }]));
    });
    for (let i = 0; i <= MAX_LOOKUPS_PER_AGENT + 1; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOOKUP_INTERVAL_MS + 10);
      });
    }
    expect(fetchMock).toHaveBeenCalledTimes(MAX_LOOKUPS_PER_AGENT);
    const labels = stripTabs().map((t) => t.textContent);
    expect(labels).toContain(UNNAMED_AGENT);
    expect(screen.getByTestId('live-stream-bar').textContent).not.toMatch(UUID_RE);
  });
});

describe('snapshotFingerprint', () => {
  it('changes when a loop starts its next round under the same name and status', () => {
    const before = snapshot();
    const after = snapshot();
    const node = after.nodes![1];
    node.agents = [{ ...node.agents![0], id: uuid(5000) }, ...node.agents!.slice(1)];
    expect(snapshotFingerprint(after)).not.toBe(snapshotFingerprint(before));
  });

  it('changes when the agent index gains an agent', () => {
    const before = snapshot();
    const after = { ...snapshot(), agent_index: [...PLANNED, ...LATE].map(indexEntry) };
    expect(snapshotFingerprint(after)).not.toBe(snapshotFingerprint(before));
  });
});
