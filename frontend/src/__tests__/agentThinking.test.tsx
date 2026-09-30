/**
 * An agent that thought: its thinking has to be readable from its own panel.
 *
 * The panel already put a violet "thinking" badge on each model call, but the
 * text lived inside the call's own inspector — so reading what a twenty-call
 * agent thought meant opening twenty calls one at a time, which nobody does.
 *
 * It is folded by default: an agent that thinks is normal, and the answer stays
 * the thing you see first. And it is drawn as thinking, in its own block, never
 * run together with what the agent actually said.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { AgentDetailPanel } from '@/components/panels/AgentDetailPanel';
import { MOCK_WORKFLOW } from './fixtures';
import type { AgentExecution, LLMCall, WorkflowExecution } from '@/types';

function call(id: string, thinking?: string, response = 'Done.'): LLMCall {
  return {
    id,
    model: 'claude-opus-5-5',
    provider: 'claude',
    status: 'completed',
    start_time: '2026-09-29T10:00:00Z',
    end_time: '2026-09-29T10:00:20Z',
    duration_seconds: 20,
    prompt_tokens: 500,
    completion_tokens: 200,
    total_tokens: 700,
    estimated_cost_usd: 0.01,
    response,
    thinking,
  } as LLMCall;
}

/** A finished run whose one agent made `calls` \u2014 the shape the page is given. */
function runWith(calls: LLMCall[]): WorkflowExecution {
  const agent: AgentExecution = {
    id: 'a-thinker',
    agent_name: 'deep_thinker',
    status: 'completed',
    stage_execution_id: 'stage-001',
    start_time: '2026-09-29T10:00:00Z',
    end_time: '2026-09-29T10:01:00Z',
    duration_seconds: 60,
    prompt_tokens: 500,
    completion_tokens: 200,
    total_tokens: 700,
    estimated_cost_usd: 0.01,
    total_llm_calls: calls.length,
    total_tool_calls: 0,
    llm_calls: calls,
    tool_calls: [],
  } as AgentExecution;

  const stage = { ...MOCK_WORKFLOW.stages![0], status: 'completed', agents: [agent] };
  return {
    ...MOCK_WORKFLOW,
    status: 'completed',
    nodes: [stage],
    stages: [stage],
  } as WorkflowExecution;
}

function load(calls: LLMCall[]) {
  act(() => {
    useExecutionStore.setState({
      workflow: null,
      stages: new Map(),
      agents: new Map(),
      llmCalls: new Map(),
      toolCalls: new Map(),
      streamingContent: new Map(),
      selection: null,
      eventLog: [],
      expandedStages: new Set(),
    });
    useExecutionStore.getState().applySnapshot(runWith(calls));
  });
}

describe("an agent's own panel shows what it thought", () => {
  beforeEach(() => load([]));

  it('gathers the thinking of every call into one section', () => {
    load([
      call('c1', 'The effort flag never reached the command line.'),
      call('c2'),
      call('c3', 'Both paths have to record it, not just the watched one.'),
    ]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    // Named with how many calls thought, so the section is worth opening.
    const trigger = screen.getByText(/Thinking \(2 calls\)/);
    fireEvent.click(trigger);

    const section = screen.getByTestId('agent-thinking');
    expect(section.textContent).toContain('The effort flag never reached');
    expect(section.textContent).toContain('Both paths have to record it');
  });

  it('is folded until it is asked for', () => {
    load([call('c1', 'A long deliberation nobody asked to read yet.')]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    expect(screen.queryByTestId('agent-thinking')).toBeNull();
    expect(screen.getByText(/Thinking \(1 call\)/)).toBeInTheDocument();
  });

  it('says nothing at all when no call thought', () => {
    load([call('c1'), call('c2')]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    expect(screen.queryByText(/^Thinking \(/)).toBeNull();
  });

  it('keeps thinking out of the answer', () => {
    load([call('c1', 'Maybe the tests are wrong.', 'The tests are right.')]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    fireEvent.click(screen.getByText(/Thinking \(1 call\)/));
    const section = screen.getByTestId('agent-thinking');
    expect(section.textContent).toContain('Maybe the tests are wrong');
    expect(section.textContent).not.toContain('The tests are right');
  });

  it('points each block at the call that produced it', () => {
    load([call('c1'), call('c2', 'Second call thought about it.')]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    fireEvent.click(screen.getByText(/Thinking \(1 call\)/));
    // Numbered as in the call list below it, so #2 means the same call there.
    const opener = screen.getByRole('button', { name: /#2 claude-opus-5-5/ });
    fireEvent.click(opener);
    expect(useExecutionStore.getState().selection).toEqual({ type: 'llmCall', id: 'c2' });
  });
});

describe('thinking read back from storage survives a reload', () => {
  it('needs no live stream to be there', () => {
    // A fresh page: nothing was streamed into this store, the run is over.
    load([call('c1', 'Recorded when the run happened, not when the page opened.')]);
    render(<AgentDetailPanel agentId="a-thinker" />);

    expect(useExecutionStore.getState().streamingContent.size).toBe(0);
    fireEvent.click(screen.getByText(/Thinking \(1 call\)/));
    expect(screen.getByTestId('agent-thinking').textContent).toContain(
      'Recorded when the run happened',
    );
  });
});
