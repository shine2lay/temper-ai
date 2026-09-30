/**
 * A stage inside another stage: its panel has to open.
 *
 * The graph draws the top level (plus the rounds a dispatcher added, lifted
 * out), so `stages` has no key for a nested node and every panel that read it
 * said "Stage not found" — on a real run, all six inner `pitch_*` stages of an
 * epd_propose run and the inner `environment` stage of a github_work run.
 * The store keeps those nodes in `nestedStages`; panels read both, the header
 * counts and the graph keep reading `stages` alone.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { StageDetailPanel } from '@/components/panels/StageDetailPanel';
import { AgentDetailPanel } from '@/components/panels/AgentDetailPanel';
import { WorkflowSummaryBar } from '@/components/layout/WorkflowSummaryBar';
import type { AgentExecution, NodeExecution, WorkflowExecution } from '@/types';

function agent(id: string, name: string, status = 'completed'): AgentExecution {
  return {
    id,
    agent_name: name,
    status,
    start_time: '2026-09-29T10:00:00Z',
    end_time: '2026-09-29T10:00:30Z',
    duration_seconds: 30,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    estimated_cost_usd: 0.02,
    total_llm_calls: 1,
    total_tool_calls: 0,
    llm_calls: [],
    tool_calls: [],
  } as AgentExecution;
}

/** A run shaped like github_work: a stage inside a stage, agents in both. */
function nestedRun(status = 'completed'): WorkflowExecution {
  const stackDetect = agent('a-stack-detect', 'task_stack_detect');
  const claim = agent('a-claim', 'task_claim');
  const triage = agent('a-triage', 'github_triage');

  // `stack_up` ran under the stage itself, with no node of its own — the
  // shape an epd_propose `pitch_*` stage has for most of its agents.
  const stackUp = agent('a-stack-up', 'task_stack_up');

  const environment: NodeExecution = {
    id: 'n-environment',
    name: 'environment',
    type: 'stage',
    status: 'completed',
    start_time: '2026-09-29T10:00:00Z',
    end_time: '2026-09-29T10:00:40Z',
    duration_seconds: 40,
    agents: [stackDetect, stackUp],
    num_agents_executed: 2,
    num_agents_succeeded: 2,
    num_agents_failed: 0,
    child_nodes: [
      {
        id: 'n-stack-detect',
        name: 'stack_detect',
        type: 'agent',
        status: 'completed',
        start_time: '2026-09-29T10:00:00Z',
        end_time: '2026-09-29T10:00:30Z',
        duration_seconds: 30,
        agent: stackDetect,
      } as NodeExecution,
    ],
  } as NodeExecution;

  const build: NodeExecution = {
    id: 'n-build',
    name: 'build',
    type: 'stage',
    status: 'completed',
    start_time: '2026-09-29T09:59:00Z',
    end_time: '2026-09-29T10:01:00Z',
    duration_seconds: 120,
    agents: [claim],
    child_nodes: [
      {
        id: 'n-claim',
        name: 'claim',
        type: 'agent',
        status: 'completed',
        start_time: '2026-09-29T09:59:00Z',
        agent: claim,
      } as NodeExecution,
      environment,
    ],
  } as NodeExecution;

  const triageNode: NodeExecution = {
    id: 'n-triage',
    name: 'triage',
    type: 'agent',
    status: 'completed',
    start_time: '2026-09-29T09:58:00Z',
    agent: triage,
  } as NodeExecution;

  return {
    id: 'run-nested-001',
    workflow_name: 'github_work',
    status,
    start_time: '2026-09-29T09:58:00Z',
    end_time: status === 'completed' ? '2026-09-29T10:01:00Z' : null,
    duration_seconds: status === 'completed' ? 180 : null,
    nodes: [triageNode, build],
    total_tokens: 450,
    total_cost_usd: 0.06,
  } as WorkflowExecution;
}

function load(workflow: WorkflowExecution) {
  act(() => {
    useExecutionStore.getState().reset();
    useExecutionStore.getState().applySnapshot(workflow);
  });
}

describe('a stage inside another stage', () => {
  beforeEach(() => {
    load(nestedRun());
  });

  it('keeps the drawn map top-level and the nested nodes beside it', () => {
    const { stages, nestedStages } = useExecutionStore.getState();
    expect([...stages.keys()].sort()).toEqual(['n-build', 'n-triage']);
    expect([...nestedStages.keys()].sort()).toEqual([
      'n-claim',
      'n-environment',
      'n-stack-detect',
    ]);
    // Never in both: a live update would land on one copy and leave the other.
    for (const id of nestedStages.keys()) expect(stages.has(id)).toBe(false);
  });

  it('opens the inner stage instead of saying it is not found', () => {
    render(<StageDetailPanel stageId="n-environment" />);

    expect(screen.queryByText(/not found/i)).toBeNull();
    expect(screen.getByRole('heading', { name: 'environment' })).toBeInTheDocument();
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
    // Its timing and its agent, not an empty shell.
    expect(screen.getByText('40.0s')).toBeInTheDocument();
    expect(screen.getByText('task_stack_detect')).toBeInTheDocument();
  });

  it('still opens a top-level stage', () => {
    render(<StageDetailPanel stageId="n-build" />);

    expect(screen.queryByText(/not found/i)).toBeNull();
    expect(screen.getByRole('heading', { name: 'build' })).toBeInTheDocument();
  });

  it('says so for a stage id the run never had', () => {
    render(<StageDetailPanel stageId="n-nope" />);

    expect(screen.getByText(/Stage not found/i)).toBeInTheDocument();
  });

  it('takes an agent of an inner stage back to the node it ran as', () => {
    render(<AgentDetailPanel agentId="a-stack-detect" />);

    const back = screen.getByRole('button', { name: /Back to Stage/i });
    fireEvent.click(back);

    // The agent ran as a node of its own, nested inside `environment`.
    const selection = useExecutionStore.getState().selection;
    expect(selection).toEqual({ type: 'stage', id: 'n-stack-detect' });

    // And what the link opens is that node, not an empty panel.
    render(<StageDetailPanel stageId={selection!.id} />);
    expect(screen.queryByText(/not found/i)).toBeNull();
    expect(screen.getByRole('heading', { name: 'stack_detect' })).toBeInTheDocument();
  });

  it('takes an agent that ran under the inner stage back to that stage', () => {
    render(<AgentDetailPanel agentId="a-stack-up" />);

    fireEvent.click(screen.getByRole('button', { name: /Back to Stage/i }));

    const selection = useExecutionStore.getState().selection;
    expect(selection).toEqual({ type: 'stage', id: 'n-environment' });

    render(<StageDetailPanel stageId={selection!.id} />);
    expect(screen.queryByText(/not found/i)).toBeNull();
    expect(screen.getByRole('heading', { name: 'environment' })).toBeInTheDocument();
  });

  it('counts only the top-level stages in the header', () => {
    render(<WorkflowSummaryBar />);

    // Two top-level nodes, both completed — the three nested ones do not count.
    expect(screen.getByText('2/2')).toBeInTheDocument();
  });

  it('keeps an inner stage selected across a snapshot refresh', () => {
    act(() => {
      useExecutionStore.getState().select('stage', 'n-environment');
      useExecutionStore.getState().applySnapshot(nestedRun());
    });

    expect(useExecutionStore.getState().selection).toEqual({
      type: 'stage',
      id: 'n-environment',
    });
  });

  it('lets a live event close an inner stage', () => {
    const run = nestedRun('running');
    const inner = run.nodes![1].child_nodes![1];
    inner.status = 'running';
    inner.end_time = null;
    inner.duration_seconds = null;
    load(run);
    act(() => {
      useExecutionStore.getState().applyEvent({
        type: 'event',
        event_type: 'event.updated',
        timestamp: '2026-09-29T10:02:00Z',
        data: { event_id: 'n-environment', status: 'failed' },
      });
    });

    const closed = useExecutionStore.getState().nestedStages.get('n-environment');
    expect(closed?.status).toBe('failed');
    expect(closed?.end_time).toBe('2026-09-29T10:02:00Z');
    // The drawn map did not grow a key for it.
    expect(useExecutionStore.getState().stages.has('n-environment')).toBe(false);
  });

  it('gives an index-only agent of an inner node its stage back', () => {
    const run = nestedRun();
    run.agent_index = [
      {
        id: 'a-stack-detect-round-1',
        agent_name: 'task_stack_detect',
        status: 'completed',
        node_id: 'n-stack-detect',
        node_name: 'stack_detect',
        round: 1,
      },
    ] as WorkflowExecution['agent_index'];
    load(run);

    const agentRecord = useExecutionStore.getState().agents.get('a-stack-detect-round-1');
    expect(agentRecord?.stage_id).toBe('n-stack-detect');
  });
});
