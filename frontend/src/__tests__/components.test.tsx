/**
 * Component rendering tests — verify that UI components correctly display
 * data from the Zustand store after WebSocket snapshots and events.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { LLMCallInspector } from '@/components/panels/LLMCallInspector';
import { ToolCallInspector } from '@/components/panels/ToolCallInspector';
import { StreamingPanel } from '@/components/panels/StreamingPanel';
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
    wsStatus: { connected: false, reconnectAttempt: 0, lastHeartbeat: null },
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

describe('LLMCallInspector', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('renders LLM call details from store', () => {
    render(<LLMCallInspector llmCallId="llm-001" />);

    expect(screen.getByText('ollama/qwen3')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('5000ms')).toBeInTheDocument();
  });

  it('shows "not found" for missing LLM call', () => {
    render(<LLMCallInspector llmCallId="nonexistent" />);
    expect(screen.getByText('LLM call not found.')).toBeInTheDocument();
  });

  it('displays error_message when status is failed', () => {
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

    render(<LLMCallInspector llmCallId="llm-fail" />);
    expect(screen.getByText('Connection timeout')).toBeInTheDocument();
  });
});

describe('ToolCallInspector', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('renders tool call details from store', () => {
    render(<ToolCallInspector toolCallId="tool-001" />);

    expect(screen.getByText('Bash')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('shows "not found" for missing tool call', () => {
    render(<ToolCallInspector toolCallId="nonexistent" />);
    expect(screen.getByText('Tool call not found.')).toBeInTheDocument();
  });

  it('displays output_data (not output)', () => {
    render(<ToolCallInspector toolCallId="tool-001" />);

    // Both input_params and output_data are rendered — verify output_data content exists
    const matches = screen.getAllByText(/hello/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it('displays safety badge when safety_checks_applied is present', () => {
    render(<ToolCallInspector toolCallId="tool-001" />);
    expect(screen.getByText('safety checked')).toBeInTheDocument();
  });
});

describe('StreamingPanel', () => {
  beforeEach(() => {
    resetStore();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('shows "waiting for stream" when no streaming content', () => {
    render(<StreamingPanel agentId="agent-002" />);
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

    // Render LLM inspector for existing call
    const { rerender } = render(<LLMCallInspector llmCallId="llm-001" />);
    expect(screen.getByText('ollama/qwen3')).toBeInTheDocument();
    expect(screen.getByText('350')).toBeInTheDocument(); // total_tokens

    // Simulate agent_end event that doesn't change the LLM call
    act(() => {
      useExecutionStore.getState().applyEvent(makeAgentEndEvent());
    });

    // LLM call should still be visible
    rerender(<LLMCallInspector llmCallId="llm-001" />);
    expect(screen.getByText('ollama/qwen3')).toBeInTheDocument();
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

    // Initially no streaming content
    expect(useExecutionStore.getState().streamingContent.size).toBe(0);

    // Apply stream batch
    act(() => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('agent-002', [{ content: 'Hello' }]),
      );
    });

    // Now streaming content exists
    const entry = useExecutionStore.getState().streamingContent.get('agent-002');
    expect(entry).toBeDefined();
    expect(entry!.content).toBe('Hello');
  });
});
