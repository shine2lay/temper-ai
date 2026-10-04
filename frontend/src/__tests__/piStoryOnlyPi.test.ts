/**
 * The Pi step's page changes reach Pi agents only (L2, switched off by default):
 * an ordinary agent's events take exactly the paths they always took.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import { isPiAgent } from '@/lib/piStory';
import type { StoryTool } from '@/lib/agentStory';
import type { WSEvent } from '@/types';

const S = () => useExecutionStore.getState();
const T = '2026-10-04T03:45:17.000000+00:00';

function ev(event_type: string, data: Record<string, unknown>): WSEvent {
  return { type: 'event', event_type, data, timestamp: T } as unknown as WSEvent;
}

function play(...msgs: WSEvent[]) {
  act(() => {
    for (const m of msgs) S().applyEvent(m);
  });
}

function start(agentData: Record<string, unknown>) {
  play(
    ev('workflow.started', { name: 'w', workflow_name: 'w', event_id: 'wf', status: 'running' }),
    ev('stage.started', { name: 'n', stage_name: 'n', event_id: 'st', status: 'running', parent_id: 'wf' }),
    ev('agent.started', { agent_name: 'a', name: 'a', event_id: 'ag', status: 'running', parent_id: 'st', ...agentData }),
  );
}

function toolRun(extra: Record<string, unknown>) {
  play(
    ev('tool.call.started', { agent_id: 'ag', tool_name: 'read', call_id: 'c1', event_id: 't1', status: 'running', ...extra }),
    ev('tool.call.completed', {
      agent_id: 'ag', tool_name: 'read', call_id: 'c1', event_id: 't1-end', status: 'completed',
      duration_ms: 1500, ...extra,
    }),
  );
  return S().stories.get('ag')?.items.find((i): i is StoryTool => i.kind === 'tool');
}

function words(callId: string, content: string): WSEvent {
  return {
    type: 'event', event_type: 'llm_stream_batch', timestamp: T,
    data: { chunks: [{ agent_id: 'ag', content, chunk_type: 'content', done: false, call_id: callId }] },
  } as unknown as WSEvent;
}

beforeEach(() => {
  S().reset();
});

describe('Pi page changes reach Pi agents only', () => {
  it('knows a Pi agent from what its start says, and nothing else is one', () => {
    expect(isPiAgent({ executed_by: 'pi' })).toBe(true);
    expect(isPiAgent({ agent_config_snapshot: { agent: { type: 'pi' } } })).toBe(true);
    expect(isPiAgent({ type: 'llm' })).toBe(false);
    expect(isPiAgent({ agent_config: { type: 'script' } })).toBe(false);
    expect(isPiAgent(undefined)).toBe(false);
  });

  it("an ordinary agent's tool step is master's (duration_ms is now every workflow's B2), not Pi's", () => {
    start({ type: 'llm' });
    const tool = toolRun({});
    expect(tool?.status).toBe('completed');
    expect(tool?.durationSeconds).toBe(1.5);
    expect(S().stories.get('ag')?.pi).toBeFalsy();
  });

  it("a Pi turn's tool step takes its duration from duration_ms", () => {
    start({ type: 'pi', executed_by: 'pi' });
    const tool = toolRun({ executed_by: 'pi' });
    expect(tool?.status).toBe('completed');
    expect(tool?.durationSeconds).toBe(1.5);
    expect(S().stories.get('ag')?.pi).toBe(true);
  });

  it("an ordinary agent's words after its call ended are still added, as before", () => {
    start({ type: 'llm' });
    play(
      words('m1', 'Hello'),
      ev('llm.call.completed', { agent_id: 'ag', llm_call_id: 'm1', event_id: 'm1-end', response_content: 'Hello' }),
      words('m1', ' again'),
    );
    const text = S().stories.get('ag')?.items.filter((i) => i.kind === 'text').map((i) => (i as { text: string }).text);
    expect(text?.join('')).toBe('Hello again');
  });

  it("a Pi turn's call ending with its final message settles its words", () => {
    start({ type: 'pi', executed_by: 'pi' });
    play(
      words('m1', 'Hel'),
      ev('llm.call.completed', {
        agent_id: 'ag', llm_call_id: 'm1', event_id: 'm1-end', response_content: 'Hello.',
        authoritative_final: true, executed_by: 'pi',
      }),
      words('m1', 'lo.'),
    );
    const text = S().stories.get('ag')?.items.filter((i) => i.kind === 'text').map((i) => (i as { text: string }).text);
    expect(text?.join('')).toBe('Hello.');
  });

  it("an ordinary agent's failed call event changes nothing, as before", () => {
    start({ type: 'llm' });
    play(ev('llm.call.failed', { agent_id: 'ag', llm_call_id: 'm1', event_id: 'm1-end', error: 'boom' }));
    expect(S().llmCalls.has('m1')).toBe(false);
    expect(S().stories.get('ag')?.items ?? []).toHaveLength(0);
  });
});
