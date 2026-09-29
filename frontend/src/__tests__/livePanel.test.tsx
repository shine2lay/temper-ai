/**
 * The live panel: the run's agents on the left, the chosen agent's story on
 * the right, and the panel itself — how tall it is, what it follows, and
 * how a run that is over reads back.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent, cleanup, within } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { LivePanel } from '@/components/live/LivePanel';
import { DEFAULT_SHARE } from '@/components/live/useLivePanelSize';
import { toolStepLabel } from '@/lib/toolLabels';
import { fullStory } from '@/lib/agentStory';
import type { AgentExecution, NodeExecution, WorkflowExecution, WSEvent } from '@/types';

const RUN = 'run-live-0001';

/** Words arriving for one agent, on the run's own clock. */
function makeStreamBatchEvent(
  agentId: string,
  chunks: Array<{ content: string; chunk_type?: string; done?: boolean; call_id?: string }>,
  at = '2026-09-28T10:00:30Z',
): WSEvent {
  return {
    type: 'event',
    event_type: 'llm_stream_batch',
    agent_id: agentId,
    timestamp: at,
    data: { chunks: chunks.map((c) => ({ agent_id: agentId, ...c })) },
  } as WSEvent;
}

function agent(over: Partial<AgentExecution> & { id: string; agent_name: string }): AgentExecution {
  return {
    status: 'running',
    start_time: '2026-09-28T10:00:00Z',
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
    ...over,
  } as AgentExecution;
}

function node(id: string, name: string, agents: AgentExecution[], status = 'running'): NodeExecution {
  return {
    id,
    name,
    type: 'stage',
    status,
    start_time: '2026-09-28T10:00:00Z',
    end_time: null,
    duration_seconds: null,
    cost_usd: 0,
    total_tokens: 0,
    agents,
  } as NodeExecution;
}

function run(nodes: NodeExecution[], status = 'running'): WorkflowExecution {
  return {
    id: RUN,
    workflow_name: 'demo',
    status,
    start_time: '2026-09-28T10:00:00Z',
    end_time: null,
    duration_seconds: null,
    nodes,
    stages: nodes,
    total_tokens: 0,
    total_cost_usd: 0,
  } as WorkflowExecution;
}

function toolEvent(
  kind: 'started' | 'completed' | 'failed',
  agentId: string,
  over: Record<string, unknown>,
): WSEvent {
  return {
    type: 'event',
    event_type: `tool.call.${kind}`,
    agent_id: agentId,
    timestamp: '2026-09-28T10:00:05Z',
    data: { agent_id: agentId, ...over },
  } as WSEvent;
}

beforeEach(() => {
  useExecutionStore.getState().reset();
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the story of one agent', () => {
  it('keeps thinking, text and tool steps in the order they happened', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(run([
        node('n1', 'build', [agent({ id: 'a1', agent_name: 'coder' })]),
      ]));
    });
    render(<LivePanel />);

    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(makeStreamBatchEvent('a1', [
        { content: 'Let me check the tests.', chunk_type: 'thinking', call_id: 'c1' },
      ]));
      applyEvent(makeStreamBatchEvent('a1', [{ content: 'Running the suite.', call_id: 'c1' }]));
      applyEvent(toolEvent('started', 'a1', {
        event_id: 't1', tool_name: 'Bash', input_params: { command: 'npm test' },
      }));
      applyEvent(toolEvent('completed', 'a1', {
        tool_execution_id: 't1', tool_name: 'Bash', status: 'success',
        duration_seconds: 12, output_data: { stdout: 'ok' },
      }));
      applyEvent(makeStreamBatchEvent('a1', [{ content: 'All green.', call_id: 'c2' }]));
    });

    const story = screen.getByTestId('agent-story');
    const text = story.textContent ?? '';
    expect(text.indexOf('Let me check the tests.')).toBeLessThan(text.indexOf('Running the suite.'));
    expect(text.indexOf('Running the suite.')).toBeLessThan(text.indexOf('Run npm test'));
    expect(text.indexOf('Run npm test')).toBeLessThan(text.indexOf('All green.'));
    expect(within(story).getAllByTestId('story-tool')).toHaveLength(1);
  });

  it('streams word by word into one paragraph, not one line per word', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(run([
        node('n1', 'build', [agent({ id: 'a1', agent_name: 'coder' })]),
      ]));
    });
    render(<LivePanel />);
    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      for (const word of ['Check', 'ing ', 'the ', 'code', '.']) {
        applyEvent(makeStreamBatchEvent('a1', [{ content: word, call_id: 'c1' }]));
      }
    });
    const items = useExecutionStore.getState().stories.get('a1')?.items ?? [];
    expect(items).toHaveLength(1);
    expect(screen.getByTestId('agent-story').textContent).toContain('Checking the code.');
  });

  it('shows a failed step in red, with what went wrong', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(run([
        node('n1', 'build', [agent({ id: 'a1', agent_name: 'coder' })]),
      ]));
    });
    render(<LivePanel />);
    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(toolEvent('started', 'a1', {
        event_id: 't9', tool_name: 'Bash', input_params: { command: 'npm run build' },
      }));
      applyEvent(toolEvent('failed', 'a1', {
        tool_execution_id: 't9', tool_name: 'Bash', status: 'error',
        duration_seconds: 3, error_message: 'exit code 1',
      }));
    });

    const step = screen.getByTestId('story-tool');
    expect(step.querySelector('.text-red-400')).not.toBeNull();
    fireEvent.click(within(step).getByRole('button'));
    expect(step.textContent).toContain('exit code 1');
  });

  it('reads a finished run back from what temper stored', () => {
    const done = agent({
      id: 'a1',
      agent_name: 'coder',
      status: 'completed',
      end_time: '2026-09-28T10:02:00Z',
      duration_seconds: 120,
      llm_calls: [{
        id: 'llm-1',
        status: 'completed',
        start_time: '2026-09-28T10:00:01Z',
        end_time: '2026-09-28T10:00:20Z',
        duration_seconds: 19,
        prompt_tokens: 10,
        completion_tokens: 5,
        total_tokens: 15,
        estimated_cost_usd: 0.002,
        thinking: 'The build script looks wrong.',
        response: 'I fixed the build script.',
      }],
      tool_calls: [{
        id: 'tool-1',
        tool_name: 'Edit',
        status: 'completed',
        start_time: '2026-09-28T10:00:10Z',
        end_time: '2026-09-28T10:00:11Z',
        duration_seconds: 1,
        input_params: { file_path: '/repo/build.sh' },
        output_data: { ok: true },
      }],
    });
    act(() => {
      useExecutionStore.getState().applySnapshot(run([node('n1', 'build', [done], 'completed')], 'completed'));
    });
    render(<LivePanel />);

    const text = screen.getByTestId('agent-story').textContent ?? '';
    expect(text).toContain('The build script looks wrong.');
    expect(text).toContain('I fixed the build script.');
    expect(text).toMatch(/Edit .*build\.sh/);
  });

  it('tells a story only once for a page that joined the run late', () => {
    // The page streamed the newest call itself; the earlier one it can only
    // read back. Neither may be told twice.
    const live = agent({
      id: 'a1',
      agent_name: 'coder',
      llm_calls: [
        {
          id: 'llm-1', status: 'completed', start_time: '2026-09-28T10:00:01Z',
          end_time: '2026-09-28T10:00:05Z', duration_seconds: 4, prompt_tokens: 1,
          completion_tokens: 1, total_tokens: 2, estimated_cost_usd: 0, response: 'Earlier work.',
        },
        {
          id: 'llm-2', status: 'running', start_time: '2026-09-28T10:00:06Z',
          end_time: null, duration_seconds: null, prompt_tokens: 1, completion_tokens: 1,
          total_tokens: 2, estimated_cost_usd: 0, response: 'Newest words.',
        },
      ],
    });
    act(() => {
      useExecutionStore.getState().applySnapshot(run([node('n1', 'build', [live])]));
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('a1', [{ content: 'Newest words.', call_id: 'llm-2' }]),
      );
    });

    const items = fullStory(
      useExecutionStore.getState().agents.get('a1'),
      useExecutionStore.getState().stories.get('a1'),
    );
    const said = items.filter((i) => i.kind === 'text').map((i) => (i as { text: string }).text);
    expect(said).toEqual(['Earlier work.', 'Newest words.']);
  });
});

describe('the panel', () => {
  function threeStages() {
    return run([
      node('n1', 'plan', [agent({ id: 'a1', agent_name: 'planner', status: 'completed', duration_seconds: 30 })], 'completed'),
      node('n2', 'build', [agent({ id: 'a2', agent_name: 'coder' })]),
      node('n3', 'check', [agent({ id: 'a3', agent_name: 'tester' })]),
    ]);
  }

  it('starts at about two fifths of the page and remembers a new size', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(threeStages());
    });
    const { unmount } = render(<LivePanel />);
    const panel = screen.getByTestId('live-panel');
    expect(panel.style.height).toBe(`${Math.round(DEFAULT_SHARE * 100)}%`);

    // Drag the handle up: its parent is the page area it is measured against.
    const handle = screen.getByTestId('live-panel-handle');
    const parent = panel.parentElement as HTMLElement;
    parent.getBoundingClientRect = () => ({ bottom: 1000, height: 1000, top: 0, left: 0, right: 0, width: 800, x: 0, y: 0, toJSON: () => ({}) });
    act(() => {
      fireEvent.pointerDown(handle, { pointerId: 1, clientY: 600 });
      window.dispatchEvent(Object.assign(new Event('pointermove'), { clientY: 200 }));
      window.dispatchEvent(new Event('pointerup'));
    });
    expect(screen.getByTestId('live-panel').style.height).toBe('80%');

    unmount();
    render(<LivePanel />);
    expect(screen.getByTestId('live-panel').style.height).toBe('80%');
  });

  it('folds to a bar and comes back', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(threeStages());
    });
    render(<LivePanel />);
    expect(screen.queryByTestId('live-agent-roster')).not.toBeNull();

    fireEvent.click(screen.getByLabelText('Fold the live panel'));
    expect(screen.queryByTestId('live-agent-roster')).toBeNull();
    expect(screen.getByTestId('live-panel').style.height).toBe('34px');
    // Even folded, it says what is happening now.
    expect(screen.getByTestId('live-now-line').textContent).toContain('coder');

    fireEvent.click(screen.getByLabelText('Open the live panel'));
    expect(screen.queryByTestId('live-agent-roster')).not.toBeNull();
  });

  it('folds a stage whose agents have all finished', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(threeStages());
    });
    render(<LivePanel />);
    const headers = screen.getAllByTestId('live-group-header');
    const plan = headers.find((h) => h.textContent?.includes('plan'))!;
    expect(plan.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('planner')).toBeNull();

    fireEvent.click(plan);
    expect(screen.getByText('planner')).toBeInTheDocument();
  });

  it('opens every stage once the run is over, so the whole run reads back', () => {
    const over = threeStages();
    over.status = 'completed';
    for (const n of over.nodes) {
      n.status = 'completed';
      for (const a of n.agents ?? []) {
        a.status = 'completed';
        a.end_time = '2026-09-28T10:03:00Z';
        a.duration_seconds = 60;
      }
    }
    act(() => {
      useExecutionStore.getState().applySnapshot(over);
    });
    render(<LivePanel />);
    expect(screen.getAllByTestId('live-agent-row')).toHaveLength(3);
    for (const header of screen.getAllByTestId('live-group-header')) {
      expect(header.getAttribute('aria-expanded')).toBe('true');
    }
  });

  it('follows the busiest agent until you pick one, and goes back on Follow', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(threeStages());
    });
    render(<LivePanel />);

    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('a2', [{ content: 'coder at work', call_id: 'c1' }]),
      );
    });
    expect(screen.getByTestId('live-now-line').textContent).toContain('coder');
    expect(screen.queryByTestId('live-follow-button')).toBeNull();

    // A newer agent starts talking: the panel goes with it.
    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('a3', [{ content: 'tester at work', call_id: 'c2' }], '2026-09-28T10:05:00Z'),
      );
    });
    expect(screen.getByTestId('live-now-line').textContent).toContain('tester');

    // Picking one stops the following, and Follow starts it again.
    fireEvent.click(screen.getAllByTestId('live-agent-row').find((r) => r.textContent?.includes('coder'))!);
    expect(screen.getByTestId('live-now-line').textContent).toContain('coder');
    fireEvent.click(screen.getByTestId('live-follow-button'));
    expect(screen.getByTestId('live-now-line').textContent).toContain('tester');
  });

  it('says what is happening now, and how many others are working', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(threeStages());
    });
    render(<LivePanel />);
    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(makeStreamBatchEvent('a2', [{ content: 'working', call_id: 'c1' }]));
      applyEvent(toolEvent('started', 'a2', {
        event_id: 't1', tool_name: 'Bash', input_params: { command: 'npm test' },
      }));
    });
    const line = screen.getByTestId('live-now-line').textContent ?? '';
    expect(line).toContain('build · coder');
    expect(line).toContain('Run npm test');
    expect(line).toContain('(+1 more working)');
  });
});

describe('what a step is called', () => {
  it('says it in plain words, from the tool and what it was given', () => {
    expect(toolStepLabel('Read', { file_path: '/home/me/project/src/app.ts' })).toBe('Read …/project/src/app.ts');
    expect(toolStepLabel('Edit', { file_path: 'notes.md' })).toBe('Edit notes.md');
    expect(toolStepLabel('Write', { file_path: 'notes.md' })).toBe('Write notes.md');
    expect(toolStepLabel('Bash', { command: 'npm test' })).toBe('Run npm test');
    expect(toolStepLabel('Grep', { pattern: 'TODO' })).toBe('Search for TODO');
    expect(toolStepLabel('Glob', { pattern: '**/*.ts' })).toBe('Find files **/*.ts');
    expect(toolStepLabel('WebFetch', { url: 'https://example.com/a/b' })).toBe('Fetch example.com');
    expect(toolStepLabel('mcp__github__create_pull_request', { title: 'Fix build' })).toBe('Open a pull request Fix build');
    expect(toolStepLabel('browser_navigate', { url: 'https://example.com' })).toBe('Open example.com');
    expect(toolStepLabel('ask_user_question', { question: 'Which one?' })).toBe('Ask you Which one?');
    expect(toolStepLabel('quantum_flux', {})).toBe('Using quantum flux');
  });

  it('cuts a long command short instead of filling the line', () => {
    const label = toolStepLabel('Bash', { command: 'x'.repeat(500) });
    expect(label.length).toBeLessThan(70);
    expect(label.endsWith('…')).toBe(true);
  });
});
