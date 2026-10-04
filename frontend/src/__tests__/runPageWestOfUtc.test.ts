/**
 * Two run-page faults found by the Pi proofs (A2's B1 and B2), which hit every
 * run, not only Pi ones:
 *
 * - B1: the server stores times without a zone (UTC); live events carry one.
 *   Read as local time, stored items sorted hours late in a browser west of
 *   UTC, so a page that joined halfway put what it heard before what happened
 *   earlier.
 * - B2: a tool's live end event says `error` and `duration_ms`; the store read
 *   only the stored row's names (`error_message`, `duration_seconds`), so a
 *   failed tool showed no error or duration until a reload.
 *
 * The clock is pinned west of UTC: on a UTC machine B1 cannot show.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fullStory, newStory, startTool } from '@/lib/agentStory';
import { useExecutionStore } from '@/store/executionStore';
import type { AgentExecution, LLMCall } from '@/types';
import { MOCK_WORKFLOW, makeToolCallEvent } from './fixtures';

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Los_Angeles');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

describe('B1: a page that joins halfway, west of UTC', () => {
  it('reads times as a browser west of UTC does', () => {
    // A stored time without a zone would be read as local time here.
    expect(new Date('2026-01-15T12:00:00').getTimezoneOffset()).toBe(480);
  });

  it('puts what happened before the page opened before what it heard live', () => {
    // Stored (no zone, UTC): a model call at 19:00. Heard live (with a zone): a tool at 19:05.
    const earlier = {
      id: 'llm-1',
      start_time: '2026-01-15T19:00:00',
      response: 'Planned the work.',
    } as unknown as LLMCall;
    const agent = { llm_calls: [earlier], tool_calls: [] } as unknown as Pick<
      AgentExecution,
      'llm_calls' | 'tool_calls'
    >;
    const live = newStory();
    startTool(live, { toolId: 'tool-9', toolName: 'Bash', at: '2026-01-15T19:05:00Z' });

    const story = fullStory(agent, live);

    expect(story.map((item) => item.kind)).toEqual(['text', 'tool']);
    expect(story[0]).toMatchObject({ text: 'Planned the work.' });
  });

  it('places a live word by its model call, read as UTC too', () => {
    const calls = [
      { id: 'llm-1', start_time: '2026-01-15T19:00:00', response: 'first' },
      { id: 'llm-2', start_time: '2026-01-15T19:10:00' },
    ] as unknown as LLMCall[];
    const agent = { llm_calls: calls, tool_calls: [] } as unknown as Pick<
      AgentExecution,
      'llm_calls' | 'tool_calls'
    >;
    const live = newStory();
    // A tool heard at 19:05 and the second call's words, which arrived with no time of their own.
    startTool(live, { toolId: 'tool-9', toolName: 'Bash', at: '2026-01-15T19:05:00Z' });
    live.items.push({ kind: 'text', id: 'live-text', text: 'second', callId: 'llm-2' });
    live.streamedCalls.add('llm-2');

    const story = fullStory(agent, live);

    expect(story.map((item) => (item.kind === 'tool' ? 'tool' : (item as { text: string }).text))).toEqual([
      'first',
      'tool',
      'second',
    ]);
  });
});

describe('B2: a failed tool, live', () => {
  beforeEach(() => {
    useExecutionStore.getState().reset();
    useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
  });

  it('shows the error and the duration the live event carries, without a reload', () => {
    const { applyEvent } = useExecutionStore.getState();
    applyEvent({
      ...makeToolCallEvent(),
      event_type: 'tool.call.started',
      data: { agent_id: 'agent-001', tool_name: 'Bash', tool_execution_id: 'tool-7' },
    } as never);
    applyEvent({
      ...makeToolCallEvent(),
      event_type: 'tool.call.failed',
      data: {
        agent_id: 'agent-001',
        tool_name: 'Bash',
        tool_execution_id: 'tool-7',
        status: 'failed',
        error: 'exit status 2: no such file',
        duration_ms: 1500,
      },
    } as never);

    const story = useExecutionStore.getState().stories.get('agent-001');
    const tool = story?.items.find((item) => item.kind === 'tool');
    expect(tool).toMatchObject({
      status: 'failed',
      error: 'exit status 2: no such file',
      durationSeconds: 1.5,
    });
  });

  it('still reads a stored row\'s names', () => {
    useExecutionStore.getState().applyEvent(
      makeToolCallEvent({
        tool_execution_id: 'tool-8',
        id: 'tool-8',
        status: 'failed',
        error_message: 'permission denied',
        duration_seconds: 2,
      }),
    );

    const story = useExecutionStore.getState().stories.get('agent-001');
    const tool = story?.items.find((item) => item.kind === 'tool' && item.toolId === 'tool-8');
    expect(tool).toMatchObject({ status: 'failed', error: 'permission denied', durationSeconds: 2 });
  });
});
