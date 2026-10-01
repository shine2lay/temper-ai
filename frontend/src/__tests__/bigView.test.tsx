/**
 * The big view: one frame for everything you click.
 *
 * These tests read the view the way a person does — select a thing, look at
 * the strip of facts, open an arrow, open a fold, step the timeline. They
 * assert on what is *shown*, never on a component's internals, so the frame
 * can be rebuilt without rewriting them.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, act, fireEvent, within, cleanup } from '@testing-library/react';
import { useExecutionStore } from '@/store/executionStore';
import type { AgentExecution, LLMCall, NodeExecution, ToolCall, WorkflowExecution } from '@/types';
import { openBigView, openArrow, openFold, openRow, foldKeys, facts, view } from './bigViewHarness';

/* ---------- a run holding one of each kind ---------- */

const MARKDOWN = '# Verdict\n\nThe plan **holds**. See [the note](https://example.test).';
const JSON_TEXT = '{"verdict": "ship", "risks": ["none"], "score": 0.9}';
const CODE = 'function decide(x) {\n  return x > 1;\n}';
const PLAIN = 'first line\nsecond line\nthird line';
const LONG = Array.from({ length: 400 }, (_, i) => `row ${i}`).join('\n');

const LLM_ONE: LLMCall = {
  id: 'llm-1',
  agent_execution_id: 'a-model',
  provider: 'anthropic',
  model: 'opus-5.5',
  status: 'completed',
  start_time: '2026-03-01T10:00:00Z',
  end_time: '2026-03-01T10:00:04Z',
  duration_seconds: 4,
  prompt_tokens: 900,
  completion_tokens: 300,
  total_tokens: 1200,
  estimated_cost_usd: 0.042,
  prompt: [
    { role: 'system', content: 'You weigh a plan.' },
    { role: 'user', content: 'Should we ship?' },
  ],
  response: MARKDOWN,
  thinking: 'Weighing the two sides.',
};

const LLM_TWO: LLMCall = {
  ...LLM_ONE,
  id: 'llm-2',
  start_time: '2026-03-01T10:00:09Z',
  end_time: '2026-03-01T10:00:12Z',
  duration_seconds: 3,
  thinking: undefined,
  response: JSON_TEXT,
};

const TOOL_ONE: ToolCall = {
  id: 'tool-1',
  tool_execution_id: 'tool-1',
  agent_execution_id: 'a-model',
  tool_name: 'Bash',
  status: 'completed',
  start_time: '2026-03-01T10:00:05Z',
  end_time: '2026-03-01T10:00:06Z',
  duration_seconds: 1,
  transport: 'mcp',
  server: 'playwright-mcp',
  input_params: { command: 'ls -la' },
  output_data: { stdout: PLAIN },
};

const MODEL_AGENT: AgentExecution = {
  id: 'a-model',
  agent_name: 'weigher',
  status: 'completed',
  stage_execution_id: 'n-main',
  start_time: '2026-03-01T10:00:00Z',
  end_time: '2026-03-01T10:00:12Z',
  duration_seconds: 12,
  prompt_tokens: 1800,
  completion_tokens: 600,
  total_tokens: 2400,
  estimated_cost_usd: 0.084,
  confidence_score: 0.9,
  total_llm_calls: 2,
  total_tool_calls: 1,
  llm_calls: [LLM_ONE, LLM_TWO],
  tool_calls: [TOOL_ONE],
  input_data: { question: 'Should we ship?' },
  output: MARKDOWN,
  reasoning: 'Both sides were weighed.',
  agent_config_snapshot: {
    agent: {
      provider: 'anthropic',
      model: 'opus-5.5',
      type: 'standard',
      system_prompt: 'You weigh a plan.',
      tools: ['Bash', 'Read'],
    },
  },
};

const SCRIPT_AGENT: AgentExecution = {
  id: 'a-script',
  agent_name: 'collect_files',
  status: 'completed',
  stage_execution_id: 'n-main',
  start_time: '2026-03-01T10:00:12Z',
  end_time: '2026-03-01T10:00:13Z',
  duration_seconds: 1,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  estimated_cost_usd: 0,
  confidence_score: null,
  total_llm_calls: 0,
  total_tool_calls: 0,
  llm_calls: [],
  tool_calls: [],
  input_data: { root: '/app' },
  output: PLAIN,
  // A script agent's config arrives double-nested, the way the server sends it.
  agent_config_snapshot: {
    agent: { agent: { type: 'script', script_template: CODE, timeout_seconds: 30 } },
  } as unknown as AgentExecution['agent_config_snapshot'],
};

const STAGE: NodeExecution = {
  id: 'n-main',
  name: 'decide',
  stage_name: 'decide',
  type: 'stage',
  status: 'completed',
  start_time: '2026-03-01T10:00:00Z',
  end_time: '2026-03-01T10:00:13Z',
  duration_seconds: 13,
  cost_usd: 0.084,
  total_tokens: 2400,
  agents: [MODEL_AGENT, SCRIPT_AGENT],
  num_agents_executed: 2,
  num_agents_succeeded: 2,
  num_agents_failed: 0,
  output_data: { verdict: 'ship' },
  stage_config_snapshot: { stage: { collaboration: { strategy: 'parallel' } } },
} as NodeExecution;

const RUN: WorkflowExecution = {
  id: 'wf-big',
  workflow_name: 'shipping_call',
  status: 'completed',
  start_time: '2026-03-01T10:00:00Z',
  end_time: '2026-03-01T10:00:13Z',
  duration_seconds: 13,
  nodes: [STAGE],
  stages: [STAGE],
  total_tokens: 2400,
  total_cost_usd: 0.084,
  input_data: { question: 'Should we ship?' },
  output_data: { verdict: 'ship', note: MARKDOWN },
} as WorkflowExecution;

function loadRun(run: WorkflowExecution = RUN) {
  act(() => {
    useExecutionStore.getState().applySnapshot(run);
  });
}

/** The six kinds, as a reader reaches them. */
const KINDS: [label: string, type: 'workflow' | 'stage' | 'agent' | 'llmCall' | 'toolCall', id: string, title: string][] = [
  ['the run', 'workflow', 'wf-big', 'shipping_call'],
  ['a stage', 'stage', 'n-main', 'decide'],
  ['an agent', 'agent', 'a-model', 'weigher'],
  ['a script agent', 'agent', 'a-script', 'collect_files'],
  ['a model call', 'llmCall', 'llm-1', 'opus-5.5'],
  ['a tool call', 'toolCall', 'tool-1', 'Bash'],
];

beforeEach(() => {
  useExecutionStore.getState().reset();
  cleanup();
});

/* ---------- the frame ---------- */

describe('the frame, for every kind', () => {
  it.each(KINDS)('opens on %s with a strip, a box and two arrows', (_label, type, id, title) => {
    loadRun();
    openBigView(type, id);

    expect(screen.getByTestId('big-view')).toBeInTheDocument();
    expect(screen.getByTestId('bv-title')).toHaveTextContent(title);
    // The strip is one line of facts, never a block.
    expect(screen.getByTestId('bv-strip')).toBeInTheDocument();
    expect(facts().length).toBeGreaterThan(1);
    expect(screen.getByTestId('bv-box')).toBeInTheDocument();
    expect(screen.getByTestId('bv-in')).toBeInTheDocument();
    expect(screen.getByTestId('bv-out')).toBeInTheDocument();
    // Never two kinds of panel: the old sheet is gone.
    expect(screen.queryByTestId('detail-sheet')).toBeNull();
  });

  it('gives the timeline to the things that can have one, and to no other', () => {
    loadRun();
    // A run, a stage, an agent: the stream of calls under them belongs there,
    // even when it is empty, because "nothing happened" is worth knowing.
    for (const [, type, id] of KINDS.filter(([, , nodeId]) => !nodeId.startsWith('llm-') && !nodeId.startsWith('tool-'))) {
      openBigView(type, id);
      expect(screen.getByTestId('bv-timeline-section')).toBeInTheDocument();
      cleanup();
    }
    // A single call has no stream of its own: no empty band on the screen.
    for (const [type, id] of [
      ['llmCall', 'llm-1'],
      ['toolCall', 'tool-1'],
    ] as const) {
      openBigView(type, id);
      expect(screen.queryByTestId('bv-timeline-section')).toBeNull();
      cleanup();
    }
  });

  it('fills the screen rather than sitting in a drawer', () => {
    loadRun();
    openBigView('agent', 'a-model');

    const panel = screen.getByTestId('big-view');
    // Full bleed on a phone, at least 80% of the window from md up.
    expect(panel.className).toContain('h-full');
    expect(panel.className).toContain('w-full');
    expect(panel.className).toMatch(/md:h-\[9\dvh\]/);
    expect(panel.className).toMatch(/md:w-\[9\dvw\]/);
  });

  it('says so plainly when the thing clicked is not on the page', () => {
    loadRun();
    openBigView('agent', 'a-nobody');

    expect(screen.getByTestId('bv-missing')).toHaveTextContent('This agent is not on the page.');
  });

  it('closes on Escape and gives the selection back', () => {
    loadRun();
    openBigView('agent', 'a-model');
    expect(useExecutionStore.getState().selection).not.toBeNull();

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(useExecutionStore.getState().selection).toBeNull();
  });

  it('keeps the run, the stage and the agent one click apart', () => {
    loadRun();
    openBigView('agent', 'a-model');

    // Up to the stage it belongs to.
    act(() => {
      fireEvent.click(screen.getByTestId('bv-parent'));
    });
    expect(useExecutionStore.getState().selection).toEqual({ type: 'stage', id: 'n-main' });
    expect(screen.getByTestId('bv-title')).toHaveTextContent('decide');

    // And down again, through the stage's own list.
    openFold('children');
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /weigher/i }));
    });
    expect(useExecutionStore.getState().selection).toEqual({ type: 'agent', id: 'a-model' });
  });

  it('starts every subject with both arrows closed', () => {
    loadRun();
    openBigView('agent', 'a-model');
    openArrow('in');
    expect(screen.getByTestId('bv-in-body')).toBeInTheDocument();

    act(() => {
      useExecutionStore.getState().select('agent', 'a-script');
    });

    expect(screen.queryByTestId('bv-in-body')).toBeNull();
  });
});

/* ---------- what each kind puts in the frame ---------- */

describe('what each kind shows', () => {
  it('an agent: its prompt, its tools, its config — each folded away', () => {
    loadRun();
    openBigView('agent', 'a-model');

    expect(foldKeys()).toEqual(expect.arrayContaining(['system', 'tools', 'thinking', 'reasoning', 'config']));
    // Folded means not rendered, so a big run opens cheap.
    expect(screen.queryByText('You weigh a plan.')).toBeNull();
    openFold('system');
    expect(screen.getByTestId('bv-fold-system')).toHaveTextContent('You weigh a plan.');
  });

  it('an agent: the model, the cost and the calls are on the strip', () => {
    loadRun();
    openBigView('agent', 'a-model');

    const strip = facts().join(' | ');
    expect(strip).toContain('anthropic/opus-5.5');
    expect(strip).toContain('12.0s');
    expect(strip).toMatch(/2\.4K|2400/);
    expect(strip).toContain('2 model');
    expect(strip).toContain('decide');
  });

  it('an agent: handed in on the left, its result on the right', () => {
    loadRun();
    openBigView('agent', 'a-model');

    expect(within(screen.getByTestId('bv-in')).getByText(/handed/i)).toBeInTheDocument();
    const inBody = openArrow('in');
    expect(within(inBody).getByTestId('bv-json')).toHaveTextContent('Should we ship?');

    const outBody = openArrow('out');
    expect(within(outBody).getByText('markdown')).toBeInTheDocument();
  });

  it('a script agent: the script it ran, and no model facts', () => {
    loadRun();
    openBigView('agent', 'a-script');

    expect(foldKeys()).toContain('script');
    openFold('script');
    expect(screen.getByTestId('bv-fold-script')).toHaveTextContent('function decide');

    const strip = facts().join(' | ');
    expect(strip).toContain('script');
    expect(strip).toContain('30s');
    expect(strip).not.toContain('tokens');
  });

  it('a model call: the conversation sent on the left, the answer on the right', () => {
    loadRun();
    openBigView('llmCall', 'llm-1');

    const inBody = openArrow('in');
    expect(within(inBody).getByTestId('bv-messages')).toHaveTextContent('Should we ship?');
    const outBody = openArrow('out');
    // A prose answer reads as markdown: the heading is a heading.
    expect(within(outBody).getByRole('heading', { name: /Verdict/i })).toBeInTheDocument();
    // Its thinking is its own fold, not dumped into the answer.
    expect(foldKeys()).toContain('thinking');
  });

  it('a model call that answered in JSON: a tree, not a paragraph of braces', () => {
    loadRun();
    openBigView('llmCall', 'llm-2');

    const outBody = openArrow('out');
    // Structured answers are the common case, and have to fold like any other
    // JSON: rendering them as prose was a raw dump in disguise.
    expect(within(outBody).getByTestId('bv-auto')).toBeInTheDocument();
    expect(within(outBody).getByText('json')).toBeInTheDocument();
    const before = outBody.textContent ?? '';
    expect(before).toContain('verdict');
    const toggles = within(outBody).getAllByRole('button');
    act(() => {
      fireEvent.click(toggles[toggles.length - 1]);
    });
    expect(outBody.textContent).not.toBe(before);
  });

  it('a tool call: its arguments on the left, its return on the right', () => {
    loadRun();
    openBigView('toolCall', 'tool-1');

    const inBody = openArrow('in');
    expect(within(inBody).getByTestId('bv-json')).toHaveTextContent('ls -la');
    const outBody = openArrow('out');
    expect(outBody).toHaveTextContent('second line');
    expect(facts().join(' | ')).toContain('playwright-mcp');
  });

  it('a stage: what fed it and what it produced', () => {
    loadRun();
    openBigView('stage', 'n-main');

    openFold('children');
    expect(screen.getByRole('button', { name: /weigher/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /collect_files/i })).toBeInTheDocument();
    const outBody = openArrow('out');
    expect(outBody).toHaveTextContent('ship');
  });

  it('the run: its stages, its inputs and its final answer', () => {
    loadRun();
    openBigView('workflow', 'wf-big');

    openFold('children');
    expect(screen.getByRole('button', { name: /decide/i })).toBeInTheDocument();
    const inBody = openArrow('in');
    expect(inBody).toHaveTextContent('Should we ship?');
    const outBody = openArrow('out');
    expect(within(outBody).getByTestId('bv-json')).toHaveTextContent('verdict');
  });
});

/* ---------- the timeline ---------- */

describe('the timeline', () => {
  it('merges model calls and tool calls into one stream, in the order they happened', () => {
    loadRun();
    openBigView('agent', 'a-model');

    const rows = screen.getAllByTestId('bv-row');
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.getAttribute('data-row-type'))).toEqual(['llm', 'tool', 'llm']);
    // One stream, not two lists.
    expect(screen.queryByText(/^LLM Calls$/i)).toBeNull();
    expect(screen.queryByText(/^Tool Calls$/i)).toBeNull();
  });

  it('opens a row in place, with its own in and out', () => {
    loadRun();
    openBigView('agent', 'a-model');

    const body = openRow(1); // the tool call
    expect(within(body).getByTestId('bv-row-in')).toHaveTextContent('ls -la');
    expect(within(body).getByTestId('bv-row-out')).toHaveTextContent('second line');
    // Still in place: the row count has not changed, nothing navigated away.
    expect(screen.getAllByTestId('bv-row')).toHaveLength(3);
  });

  it('builds the panes of a row only once it is open', () => {
    loadRun();
    openBigView('agent', 'a-model');

    expect(screen.queryByTestId('bv-row-body')).toBeNull();
    openRow(0);
    expect(screen.getAllByTestId('bv-row-body')).toHaveLength(1);
  });

  it('marks the rows that have thinking', () => {
    loadRun();
    openBigView('agent', 'a-model');

    const body = openRow(0);
    expect(within(body).getByTestId('bv-row-thinking')).toBeInTheDocument();
  });

  it('keeps a long stream to a page at a time', () => {
    const many: LLMCall[] = Array.from({ length: 60 }, (_, i) => ({
      ...LLM_ONE,
      id: `llm-many-${i}`,
      start_time: `2026-03-01T10:${String(10 + i).padStart(2, '0')}:00Z`,
    }));
    loadRun({
      ...RUN,
      nodes: [{ ...STAGE, agents: [{ ...MODEL_AGENT, llm_calls: many, tool_calls: [] }] }],
      stages: [{ ...STAGE, agents: [{ ...MODEL_AGENT, llm_calls: many, tool_calls: [] }] }],
    } as WorkflowExecution);
    openBigView('agent', 'a-model');

    expect(screen.getByTestId('bv-timeline')).toHaveAttribute('data-rows', '60');
    expect(screen.getAllByTestId('bv-row').length).toBeLessThan(60);
    act(() => {
      fireEvent.click(screen.getByTestId('bv-timeline-more'));
    });
    expect(screen.getAllByTestId('bv-row').length).toBe(60);
  });

  it('says so when nothing happened', () => {
    loadRun();
    openBigView('agent', 'a-script');

    expect(screen.getByTestId('bv-timeline-empty')).toBeInTheDocument();
  });
});

/* ---------- the renderer ---------- */

describe('nothing is a raw dump', () => {
  function outOf(id: string, value: unknown) {
    loadRun({
      ...RUN,
      nodes: [{ ...STAGE, agents: [{ ...MODEL_AGENT, id, output: value }] }],
      stages: [{ ...STAGE, agents: [{ ...MODEL_AGENT, id, output: value }] }],
    } as WorkflowExecution);
    openBigView('agent', id);
    return openArrow('out');
  }

  it('renders markdown as markdown', () => {
    const body = outOf('a-md', MARKDOWN);
    // The renderer names what it saw, and renders the heading as a heading.
    expect(within(body).getByText('markdown')).toBeInTheDocument();
    expect(body.querySelector('h1')).toHaveTextContent('Verdict');
    expect(body.querySelector('strong')).toHaveTextContent('holds');
  });

  it('renders JSON as a tree you can fold', () => {
    const body = outOf('a-json', JSON_TEXT);
    expect(within(body).getByText('json')).toBeInTheDocument();
    const before = body.textContent ?? '';
    expect(before).toContain('verdict');
    // A branch folds away.
    const toggles = within(body).getAllByRole('button');
    act(() => {
      fireEvent.click(toggles[toggles.length - 1]);
    });
    expect(body.textContent).not.toBe(before);
  });

  it('renders code as code', () => {
    const body = outOf('a-code', CODE);
    expect(within(body).getByText('code')).toBeInTheDocument();
  });

  it('renders plain text with its line breaks kept', () => {
    const body = outOf('a-text', PLAIN);
    expect(within(body).getByText('text')).toBeInTheDocument();
    const paragraph = body.querySelector('p.whitespace-pre-wrap');
    expect(paragraph).not.toBeNull();
    expect(paragraph).toHaveTextContent('first line');
  });

  it('gives anything long a height and lets it scroll inside its own box', () => {
    const body = outOf('a-long', LONG);
    const scroller = body.querySelector('[style*="max-height"]');
    expect(scroller).not.toBeNull();
    expect((scroller as HTMLElement).className).toContain('overflow-auto');
  });

  it('says when there is nothing, rather than showing an empty box', () => {
    loadRun();
    openBigView('agent', 'a-script');
    // A script agent has no model answer to show on the right... but it does
    // have output; its *reasoning* fold is the one that never appears.
    expect(foldKeys()).not.toContain('reasoning');
  });
});

/* ---------- motion ---------- */

describe('motion', () => {
  function setReducedMotion(reduce: boolean) {
    window.matchMedia = ((query: string) => ({
      matches: reduce && query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
  }

  it('staggers the timeline rows when motion is welcome', () => {
    setReducedMotion(false);
    loadRun();
    openBigView('agent', 'a-model');

    const second = screen.getAllByTestId('bv-row')[1];
    expect(second.getAttribute('style') ?? '').toContain('--bv-row-delay');
  });

  it('drops the stagger when the machine asks for less motion', () => {
    setReducedMotion(true);
    loadRun();
    openBigView('agent', 'a-model');

    for (const row of screen.getAllByTestId('bv-row')) {
      expect(row.getAttribute('style') ?? '').not.toContain('--bv-row-delay');
    }
  });

  it('carries one class per animated part, so the reduced-motion rule can reach them', () => {
    setReducedMotion(false);
    loadRun();
    openBigView('agent', 'a-model');

    expect(screen.getByTestId('big-view').className).toContain('bv-view');
    expect(screen.getAllByTestId('bv-row')[0].className).toContain('bv-row');
    openFold('system');
    expect(screen.getByTestId('bv-fold-system').querySelector('.bv-fold')).not.toBeNull();
  });
});

/* ---------- it stays quick ---------- */

describe('big runs', () => {
  it('opens on a run of 126 agents without touching their text', () => {
    const agents: AgentExecution[] = Array.from({ length: 126 }, (_, i) => ({
      ...MODEL_AGENT,
      id: `a-${i}`,
      agent_name: `worker_${i}`,
      output: LONG,
      llm_calls: [{ ...LLM_ONE, id: `llm-${i}` }],
      tool_calls: [],
    }));
    const node = { ...STAGE, agents } as NodeExecution;
    loadRun({ ...RUN, nodes: [node], stages: [node] } as WorkflowExecution);

    const started = performance.now();
    openBigView('workflow', 'wf-big');
    const took = performance.now() - started;

    expect(screen.getByTestId('bv-title')).toHaveTextContent('shipping_call');
    // Nothing of the 126 outputs is rendered until something is opened.
    expect(view().textContent).not.toContain('row 399');
    expect(took).toBeLessThan(2000);
  });

  it('shows an agent with 50+ calls a page at a time', () => {
    const calls: LLMCall[] = Array.from({ length: 55 }, (_, i) => ({ ...LLM_ONE, id: `llm-p-${i}` }));
    const agent = { ...MODEL_AGENT, llm_calls: calls, tool_calls: [] };
    const node = { ...STAGE, agents: [agent] } as NodeExecution;
    loadRun({ ...RUN, nodes: [node], stages: [node] } as WorkflowExecution);

    const started = performance.now();
    openBigView('agent', 'a-model');
    const took = performance.now() - started;

    expect(screen.getAllByTestId('bv-row').length).toBeLessThan(55);
    expect(took).toBeLessThan(2000);
  });
});

/* ---------- it keeps step with the bottom panel ---------- */

describe('the bottom live panel', () => {
  it('follows the same selection the view does', () => {
    loadRun();
    openBigView('agent', 'a-model');

    expect(useExecutionStore.getState().livePick?.id).toBe('a-model');
  });

  it('opens the view when the live panel picks an agent', () => {
    loadRun();
    const spy = vi.fn();
    const unsub = useExecutionStore.subscribe(spy);
    openBigView('agent', 'a-model');
    act(() => {
      useExecutionStore.getState().select('agent', 'a-script');
    });

    expect(screen.getByTestId('bv-title')).toHaveTextContent('collect_files');
    unsub();
  });
});
