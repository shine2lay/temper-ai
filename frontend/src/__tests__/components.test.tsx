/**
 * Component rendering tests — verify that UI components correctly display
 * data from the Zustand store after WebSocket snapshots and events.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { ToolOriginBadge } from '@/components/shared/ToolOriginBadge';
import { StreamingPanel } from '@/components/shared/StreamingPanel';
import { openBigView, openArrow, foldKeys, facts } from './bigViewHarness';
import { AgentCardContent } from '@/components/dag/AgentCardContent';
import type { AgentExecution } from '@/types';
import {
  MOCK_WORKFLOW,
  makeAgentEndEvent,
  makeStreamBatchEvent,
  makeWorkflowEndEvent,
} from './fixtures';

function resetStore() {
  useExecutionStore.setState({
    workflow: null,
    stages: new Map(),
    agents: new Map(),
    llmCalls: new Map(),
    toolCalls: new Map(),
    streamingContent: new Map(),
    selection: null,
    wsStatus: { connected: false, reconnectAttempt: 0, lastHeartbeat: null, wsError: null },
    eventLog: [],
    expandedStages: new Set(),
  });
}

describe('StatusBadge', () => {
  it('renders status text', () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText('running')).toBeInTheDocument();
  });

  it('renders completed status', () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders failed status', () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText('failed')).toBeInTheDocument();
  });
});

describe('the big view on a model call', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('puts the model, the status and how long it took on the top strip', () => {
    openBigView('llmCall', 'llm-001');

    expect(screen.getByTestId('bv-title')).toHaveTextContent('ollama/qwen3');
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
    expect(facts().join(' ')).toContain('5000ms');
  });

  it('says so when the call is not on the page', () => {
    openBigView('llmCall', 'nonexistent');
    expect(screen.getByText('This model call is not on the page.')).toBeInTheDocument();
  });

  it('shows the error when the call failed', () => {
    // Add a failed LLM call via setState (respects immer immutability)
    act(() => {
      const llmCalls = new Map(useExecutionStore.getState().llmCalls);
      llmCalls.set('llm-fail', {
        id: 'llm-fail',
        status: 'failed',
        start_time: null,
        end_time: null,
        duration_seconds: null,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        estimated_cost_usd: 0,
        error_message: 'Connection timeout',
      } as any);
      useExecutionStore.setState({ llmCalls });
    });

    openBigView('llmCall', 'llm-fail');
    expect(screen.getByText('Connection timeout')).toBeInTheDocument();
  });
});

describe('the big view on a tool call', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('names the tool and its status', () => {
    openBigView('toolCall', 'tool-001');

    expect(screen.getByTestId('bv-title')).toHaveTextContent('Bash');
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
  });

  it('says so when the call is not on the page', () => {
    openBigView('toolCall', 'nonexistent');
    expect(screen.getByText('This tool call is not on the page.')).toBeInTheDocument();
  });

  it('shows output_data (not output) behind the right-hand arrow', () => {
    openBigView('toolCall', 'tool-001');
    // Closed, the arrow shows nothing: that is what keeps a big run quick.
    expect(screen.queryByTestId('bv-out-body')).not.toBeInTheDocument();

    const out = openArrow('out');
    expect(out.textContent).toMatch(/hello/);
  });

  it('offers the safety checks as a fold of their own', () => {
    openBigView('toolCall', 'tool-001');
    expect(foldKeys()).toContain('safety');
  });
});

describe('StreamingPanel', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('shows "waiting for stream" when no streaming content', () => {
    // A snapshot seeds a stream for *running* agents so their transcript
    // stays visible, so use an agent that has none.
    render(<StreamingPanel agentId="agent-without-stream" />);
    expect(screen.getByText(/waiting|no stream/i)).toBeInTheDocument();
  });

  it('renders streaming content after stream batch events', () => {
    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('agent-002', [{ content: 'Streaming live text' }]),
      );
    });

    render(<StreamingPanel agentId="agent-002" />);
    expect(screen.getByText(/Streaming live text/)).toBeInTheDocument();
  });

  it('accumulates multiple stream batches', () => {
    act(() => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'Part one. ' }]));
      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'Part two.' }]));
    });

    render(<StreamingPanel agentId="agent-002" />);
    expect(screen.getByText(/Part one\. Part two\./)).toBeInTheDocument();
  });

  it('shows thinking content in collapsible section', () => {
    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('agent-002', [
          { content: 'Deep thought', chunk_type: 'thinking' },
          { content: 'Visible output' },
        ]),
      );
    });

    render(<StreamingPanel agentId="agent-002" />);
    // Visible output is always shown
    expect(screen.getByText(/Visible output/)).toBeInTheDocument();
    // Thinking is in a collapsible — the trigger label should be visible
    expect(screen.getByText('Thinking')).toBeInTheDocument();
  });
});

describe('Store updates trigger component re-renders', () => {
  beforeEach(() => {
    resetStore();
  });

  it('components reflect state changes from applyEvent', () => {
    // Apply initial snapshot
    act(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    // Open the big view on an existing call
    openBigView('llmCall', 'llm-001');
    expect(screen.getByTestId('bv-title')).toHaveTextContent('ollama/qwen3');
    expect(facts().join(' ')).toContain('350'); // total_tokens

    // An agent_end event that doesn't change the LLM call
    act(() => {
      useExecutionStore.getState().applyEvent(makeAgentEndEvent());
    });

    // The call is still the thing on screen
    expect(screen.getByTestId('bv-title')).toHaveTextContent('ollama/qwen3');
  });

  it('workflow status changes propagate to components', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    // Verify running status
    let state = useExecutionStore.getState();
    expect(state.workflow!.status).toBe('running');

    // Apply workflow_end event
    act(() => {
      useExecutionStore.getState().applyEvent(makeWorkflowEndEvent());
    });

    state = useExecutionStore.getState();
    expect(state.workflow!.status).toBe('completed');
    expect(state.workflow!.duration_seconds).toBe(180);
  });

  it('streaming content appears after stream batch events', () => {
    act(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    // The snapshot seeds a placeholder stream for each running agent.
    const seeded = useExecutionStore.getState().streamingContent.size;

    // Apply stream batch
    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('agent-002', [{ content: 'Hello' }]),
      );
    });

    // Now streaming content exists for that agent, without adding entries
    // for anyone else.
    const entry = useExecutionStore.getState().streamingContent.get('agent-002');
    expect(entry).toBeDefined();
    expect(entry!.content).toBe('Hello');
    expect(useExecutionStore.getState().streamingContent.size).toBe(Math.max(seeded, 1));
  });
});


describe('ToolOriginBadge', () => {
  // A run that made five MCP calls through the provider reported "Tool
  // Calls 0". Now that they are recorded, the row has to say what they were.
  it('names the MCP server and the provider that ran the call', () => {
    render(<ToolOriginBadge tool={{ transport: 'mcp', server: 'browser', executed_by: 'claude' }} />);
    expect(screen.getByText('MCP · browser')).toBeTruthy();
    expect(screen.getByText('via claude')).toBeTruthy();
  });

  it('says only MCP when the server is unknown', () => {
    render(<ToolOriginBadge tool={{ transport: 'mcp', server: null, executed_by: 'temper' }} />);
    expect(screen.getByText('MCP')).toBeTruthy();
    expect(screen.queryByText(/^via /)).toBeNull();
  });

  it('renders nothing for a temper-run builtin, the historical default', () => {
    const { container } = render(<ToolOriginBadge tool={{ transport: 'builtin', server: null, executed_by: 'temper' }} />);
    expect(container.textContent).toBe('');
  });

  it('marks a provider-run builtin as such', () => {
    render(<ToolOriginBadge tool={{ transport: 'builtin', server: null, executed_by: 'claude' }} />);
    expect(screen.getByText('via claude')).toBeTruthy();
    expect(screen.queryByText(/MCP/)).toBeNull();
  });
});

describe('the agent card', () => {
  beforeEach(resetStore);

  // A tool handed settings of its own is stored as an object, not a name.
  // Putting that object on the page threw "Objects are not valid as a React
  // child" and the error boundary blanked the whole run page \u2014 graph, tabs
  // and all \u2014 for every run of an agent with such a tool.
  it('names a tool that was given settings of its own, instead of blanking the page', () => {
    const agent = {
      id: 'agent-tools',
      agent_name: 'repo_answer',
      status: 'completed',
      duration_seconds: 4,
      total_tokens: 100,
      estimated_cost_usd: 0.01,
      total_llm_calls: 1,
      total_tool_calls: 1,
      agent_config_snapshot: {
        agent: {
          type: 'llm',
          model: 'claude-sonnet-4',
          provider: 'anthropic',
          tools: [
            'ReadFile',
            { name: 'OpenPullRequestAsApp', config: { identity: 'app' } },
          ] as unknown as string[],
        },
      },
    } as unknown as AgentExecution;

    render(<AgentCardContent agent={agent} />);

    expect(screen.getByText('ReadFile')).toBeTruthy();
    expect(screen.getByText('OpenPullRequestAsApp')).toBeTruthy();
  });
});
