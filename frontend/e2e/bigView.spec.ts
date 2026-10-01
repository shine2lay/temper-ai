/**
 * The big view: one full-screen view for everything you click.
 *
 * Six things on the run page can be opened — the run, a stage, an agent, a
 * script agent, a model call, a tool call — and all six have to land in the
 * same frame: a thin strip of facts on top, the thing itself in the middle,
 * what went in on the left, what came out on the right, and one timeline of
 * everything that happened. A unit test can prove the shape; only a click on
 * the real page proves the graph, the tabs, the store and the view agree.
 *
 * The run is made up (`replayInto`), so this costs nothing, needs no API key
 * and never shows real prompts. It runs against any server serving the built
 * dashboard:
 *
 *   npm run build && TEMPER_E2E_BASE_URL=http://127.0.0.1:8420 \
 *     npx playwright test e2e/bigView.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';
import { replayInto } from './liveReplay';

const OUT = process.env.TEMPER_PROOF_DIR ?? 'e2e/proofs/bigview';
const RUN_ID = 'replay-bigview-0001';

const T0 = Date.now() - 300_000;
const at = (s: number) => new Date(T0 + s * 1000).toISOString();

const MARKDOWN = [
  '# What we found',
  '',
  'The cache key is **shared** between two jobs, so they overwrite each other.',
  '',
  '- one: give each job its own key',
  '- two: keep the old key for the nightly build',
  '',
  'See [the note](https://example.test/cache).',
].join('\n');

const PLAIN = ['first line', 'second line', 'third line'].join('\n');

/* ---------- a made-up run holding one of every kind ---------- */

const LLM_ONE = {
  id: 'bv-llm-1',
  agent_execution_id: 'bv-writer',
  provider: 'claude_code',
  model: 'claude-sonnet-4-5',
  status: 'completed',
  start_time: at(2),
  end_time: at(26),
  duration_seconds: 24,
  latency_ms: 24_000,
  prompt_tokens: 1800,
  completion_tokens: 420,
  total_tokens: 2220,
  estimated_cost_usd: 0.021,
  prompt: [
    { role: 'system', content: 'You study a build and report what you find.' },
    { role: 'user', content: 'Why do the two jobs fight over the cache?' },
  ],
  response: MARKDOWN,
  thinking: 'Both jobs name the same key, so the second one wins.',
};

const LLM_TWO = {
  ...LLM_ONE,
  id: 'bv-llm-2',
  start_time: at(40),
  end_time: at(52),
  duration_seconds: 12,
  thinking: undefined,
  response: '{"verdict": "split the key", "confidence": 0.82, "steps": ["edit", "test"]}',
};

const TOOL_ONE = {
  id: 'bv-tool-1',
  tool_execution_id: 'bv-tool-1',
  agent_execution_id: 'bv-writer',
  tool_name: 'Read',
  status: 'completed',
  start_time: at(28),
  end_time: at(30),
  duration_seconds: 2,
  transport: 'mcp',
  server: 'playwright-mcp',
  input_params: { file_path: '/repo/.github/workflows/release.yml' },
  output_data: { lines: 212, text: PLAIN },
};

const TOOL_TWO = {
  ...TOOL_ONE,
  id: 'bv-tool-2',
  tool_execution_id: 'bv-tool-2',
  tool_name: 'Bash',
  start_time: at(32),
  end_time: at(36),
  duration_seconds: 4,
  input_params: { command: 'npm run build' },
  output_data: { stdout: PLAIN, exit_code: 0 },
};

const WRITER = {
  id: 'bv-writer',
  agent_name: 'writer',
  status: 'completed',
  round: 1,
  start_time: at(0),
  end_time: at(55),
  duration_seconds: 55,
  prompt_tokens: 3600,
  completion_tokens: 840,
  total_tokens: 4440,
  estimated_cost_usd: 0.042,
  confidence_score: 0.82,
  total_llm_calls: 2,
  total_tool_calls: 2,
  llm_calls: [LLM_ONE, LLM_TWO],
  tool_calls: [TOOL_ONE, TOOL_TWO],
  input_data: { question: 'Why do the two jobs fight over the cache?' },
  output: MARKDOWN,
  reasoning: 'Both jobs name the same key.',
  agent_config_snapshot: {
    agent: {
      provider: 'claude_code',
      model: 'claude-sonnet-4-5',
      type: 'standard',
      system_prompt: 'You study a build and report what you find.',
      tools: ['Read', 'Bash', 'Grep'],
    },
  },
};

const SCRIPTER = {
  id: 'bv-scripter',
  agent_name: 'collect_files',
  status: 'completed',
  round: 1,
  start_time: at(56),
  end_time: at(58),
  duration_seconds: 2,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  estimated_cost_usd: 0,
  total_llm_calls: 0,
  total_tool_calls: 0,
  llm_calls: [],
  tool_calls: [],
  input_data: { root: '/repo' },
  output: PLAIN,
  agent_config_snapshot: {
    agent: {
      agent: {
        type: 'script',
        timeout_seconds: 30,
        script_template: 'import os\n\nfor name in os.listdir(root):\n    print(name)\n',
      },
    },
  },
};

const BREAKER = {
  ...SCRIPTER,
  id: 'bv-breaker',
  agent_name: 'packager',
  status: 'failed',
  start_time: at(60),
  end_time: at(64),
  duration_seconds: 4,
  output: undefined,
  error_message: 'exit code 1',
  agent_config_snapshot: { agent: { provider: 'claude_code', model: 'claude-sonnet-4-5' } },
};

function snapshot() {
  const study = {
    id: 'bv-n-study',
    name: 'study',
    stage_name: 'study',
    type: 'stage',
    status: 'completed',
    start_time: at(0),
    end_time: at(58),
    duration_seconds: 58,
    depends_on: [],
    agents: [WRITER, SCRIPTER],
    input_data: { repo: 'temper-ai' },
    output_data: { verdict: 'split the key', notes: MARKDOWN },
    num_agents_executed: 2,
    num_agents_succeeded: 2,
    num_agents_failed: 0,
    cost_usd: 0.042,
    total_tokens: 4440,
  };
  const ship = {
    ...study,
    id: 'bv-n-ship',
    name: 'ship',
    stage_name: 'ship',
    status: 'failed',
    start_time: at(60),
    end_time: at(64),
    duration_seconds: 4,
    depends_on: ['study'],
    agents: [BREAKER],
    error_message: 'the package step could not run',
    num_agents_succeeded: 0,
    num_agents_failed: 1,
    output_data: undefined,
  };
  const nodes = [study, ship];
  return {
    id: RUN_ID,
    workflow_name: 'cache_study',
    status: 'failed',
    start_time: at(0),
    end_time: at(64),
    duration_seconds: 64,
    nodes,
    stages: nodes,
    total_tokens: 4440,
    total_cost_usd: 0.042,
    total_llm_calls: 2,
    total_tool_calls: 2,
    input_data: { repo: 'temper-ai', question: 'Why do the two jobs fight over the cache?' },
    output_data: { verdict: 'split the key', report: MARKDOWN },
  };
}

/* ---------- opening each of the six ---------- */

const panelOf = (page: Page) => page.getByTestId('big-view');

async function close(page: Page) {
  await page.keyboard.press('Escape');
  await expect(panelOf(page)).toBeHidden();
}

async function openRunItself(page: Page) {
  await page.getByLabel('Workflow details').click();
  await expect(panelOf(page)).toBeVisible();
}

async function openStage(page: Page, id: string) {
  await page.locator(`.react-flow__node[data-id="${id}"]`).click({ position: { x: 12, y: 12 }, force: true });
  await expect(panelOf(page)).toBeVisible();
}

/** Agents of a stage are cards inside its box; click the card by its name. */
async function openAgent(page: Page, name: string) {
  await page.locator('.react-flow__node').getByText(name, { exact: true }).first().click();
  await expect(panelOf(page)).toBeVisible();
}

/**
 * The same view, opened from the bottom live panel, which is how a reader
 * reaches an agent whose card sits below the fold of the graph.
 */
async function openAgentViaPanel(page: Page, name: string) {
  await page.getByTestId('live-agent-row').filter({ hasText: name }).first().click();
  await page.getByTestId('live-details-button').click();
  await expect(panelOf(page)).toBeVisible();
}

/** Let the opening animation finish before measuring anything. */
async function settled(page: Page) {
  await panelOf(page).evaluate((el) =>
    Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished.catch(() => undefined))),
  );
}

/** A picture for the proof folder, taken once everything has stopped moving. */
async function shot(page: Page, name: string) {
  await settled(page);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

async function openModelCall(page: Page) {
  await page.getByRole('tab', { name: 'LLM Calls' }).click();
  await page.getByRole('row').filter({ hasText: 'writer' }).first().click();
  await expect(panelOf(page)).toBeVisible();
}

/** Tool calls are reached from the event log, the way a reader finds them. */
async function openToolCall(page: Page) {
  await page.getByRole('tab', { name: 'Event Log' }).click();
  await page.getByRole('button', { name: /tool_call Bash/ }).first().click();
  await expect(panelOf(page)).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await replayInto(page, snapshot());
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
});

test.describe('the big view', () => {
  test('opens for all six kinds, and fills the screen each time', async ({ page }) => {
    const seen: string[] = [];

    const kinds: [string, () => Promise<void>][] = [
      ['workflow', () => openRunItself(page)],
      ['stage', () => openStage(page, 'bv-n-study')],
      ['agent', () => openAgent(page, 'writer')],
      ['scriptAgent', () => openAgentViaPanel(page, 'collect_files')],
      ['llmCall', () => openModelCall(page)],
      ['toolCall', () => openToolCall(page)],
    ];

    for (const [expected, open] of kinds) {
      await open();
      const panel = panelOf(page);
      await expect(panel).toHaveAttribute('data-kind', expected);
      seen.push(expected);

      // The five parts of the frame, every time.
      await expect(panel.getByTestId('bv-strip')).toBeVisible();
      await expect(panel.getByTestId('bv-box')).toBeVisible();
      await expect(panel.getByTestId('bv-in')).toBeVisible();
      await expect(panel.getByTestId('bv-out')).toBeVisible();
      await expect(panel.getByTestId('bv-missing')).toHaveCount(0);
      // The stream belongs to the things that can have one; a single call
      // shows no empty band where it would be.
      const leaf = expected === 'llmCall' || expected === 'toolCall';
      await expect(panel.getByTestId('bv-timeline-section')).toHaveCount(leaf ? 0 : 1);

      // At least 80% of the window, in both directions.
      const box = await panel.boundingBox();
      const size = page.viewportSize();
      expect(box, `${expected}: the view has no box`).not.toBeNull();
      expect(box!.width / size!.width, `${expected}: too narrow`).toBeGreaterThanOrEqual(0.8);
      expect(box!.height / size!.height, `${expected}: too short`).toBeGreaterThanOrEqual(0.8);

      await close(page);
    }

    expect(seen).toEqual(['workflow', 'stage', 'agent', 'scriptAgent', 'llmCall', 'toolCall']);
  });

  test('the old right-hand sheet is gone, not hidden behind a setting', async ({ page }) => {
    await openStage(page, 'bv-n-study');

    // Nothing of the old drawer: no 70%-wide sheet, no "Stage Details" header,
    // no second panel style open beside the view.
    await expect(page.getByTestId('detail-sheet')).toHaveCount(0);
    await expect(page.getByText('Stage Details', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Agent Details', { exact: true })).toHaveCount(0);
    await expect(page.locator('[class*="w-[70%]"]')).toHaveCount(0);
  });

  test('both arrows open: what went in on the left, what came out on the right', async ({ page }) => {
    await openAgent(page, 'writer');
    const panel = panelOf(page);

    // Closed, they are arrows with no body.
    await expect(panel.getByTestId('bv-in-body')).toHaveCount(0);
    await expect(panel.getByTestId('bv-out-body')).toHaveCount(0);

    await panel.getByTestId('bv-in-toggle').click();
    await expect(panel.getByTestId('bv-in-body')).toContainText('fight over the cache');

    await panel.getByTestId('bv-out-toggle').click();
    const out = panel.getByTestId('bv-out-body');
    // Markdown rendered as markdown, not dumped as text.
    await expect(out.locator('h1')).toContainText('What we found');
    await expect(out.locator('strong').first()).toBeVisible();

    // Both at once: a JSON tree on the left, markdown on the right.
    await shot(page, 'agent-both-arrows');
  });

  test('a model call shows the conversation sent and the answer', async ({ page }) => {
    await openModelCall(page);
    const panel = panelOf(page);

    await panel.getByTestId('bv-in-toggle').click();
    await expect(panel.getByTestId('bv-in-body')).toContainText('system');

    await panel.getByTestId('bv-out-toggle').click();
    await expect(panel.getByTestId('bv-out-body')).toBeVisible();

    // The conversation sent, and the answer rendered as markdown.
    await shot(page, 'model-call');
  });

  test('a tool call shows its arguments and its return', async ({ page }) => {
    await openToolCall(page);
    const panel = panelOf(page);

    await panel.getByTestId('bv-in-toggle').click();
    await expect(panel.getByTestId('bv-in-body')).toContainText('npm run build');
    await panel.getByTestId('bv-out-toggle').click();
    await expect(panel.getByTestId('bv-out-body')).toContainText('second line');
  });

  test('the timeline is one stream, and a row opens in place', async ({ page }) => {
    await openAgent(page, 'writer');
    const panel = panelOf(page);

    const rows = panel.getByTestId('bv-row');
    await expect(rows).toHaveCount(4);
    // Model calls and tool calls interleaved by time, not grouped in two lists.
    expect(await rows.evaluateAll((els) => els.map((el) => el.getAttribute('data-row-type')))).toEqual([
      'llm',
      'tool',
      'tool',
      'llm',
    ]);
    await expect(panel.getByText('LLM Calls', { exact: true })).toHaveCount(0);
    await expect(panel.getByText('Tool Calls', { exact: true })).toHaveCount(0);

    // Three rows, each opening where it sits.
    for (const index of [0, 1, 3]) {
      await rows.nth(index).getByTestId('bv-row-trigger').click();
      await expect(rows.nth(index).getByTestId('bv-row-body')).toBeVisible();
      await expect(rows).toHaveCount(4);
    }
    await expect(panel.getByTestId('bv-row-body')).toHaveCount(3);

    await shot(page, 'timeline-open');
  });

  test('Escape closes it and gives focus back to what was clicked', async ({ page }) => {
    const trigger = page.getByLabel('Workflow details');
    await trigger.click();
    await expect(panelOf(page)).toBeVisible();

    // Focus is inside the view while it is open, and stays there on Tab.
    const inside = () =>
      page.evaluate(() => !!document.activeElement?.closest('[data-testid="big-view"]'));
    expect(await inside()).toBe(true);
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    expect(await inside()).toBe(true);

    await page.keyboard.press('Escape');
    await expect(panelOf(page)).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test('a click outside closes it', async ({ page }) => {
    await openStage(page, 'bv-n-study');
    await page.mouse.click(4, 4);
    await expect(panelOf(page)).toBeHidden();
  });

  test('the folds in the middle open one at a time, and nothing is a raw dump', async ({ page }) => {
    await openAgent(page, 'writer');
    const panel = panelOf(page);

    // Folded away until asked for.
    await expect(panel.getByTestId('bv-fold-system')).toBeVisible();
    await expect(panel.getByTestId('bv-fold-system')).not.toContainText('You study a build');

    await panel.getByTestId('bv-fold-system-trigger').click();
    await expect(panel.getByTestId('bv-fold-system')).toContainText('You study a build');

    await panel.getByTestId('bv-fold-config-trigger').click();
    // A JSON tree, foldable — not a wall of braces in a <pre>.
    await expect(panel.getByTestId('bv-fold-config').getByTestId('bv-json')).toBeVisible();

    await shot(page, 'agent-folds');
  });

  test('a long output gets a height of its own and scrolls inside it', async ({ page }) => {
    await openAgent(page, 'writer');
    const panel = panelOf(page);
    await panel.getByTestId('bv-out-toggle').click();

    const scrolls = await panel
      .getByTestId('bv-out-body')
      .locator('[style*="max-height"]')
      .count();
    expect(scrolls).toBeGreaterThan(0);
  });

  test('a script agent shows its script, and a failed one shows why', async ({ page }) => {
    await openAgentViaPanel(page, 'collect_files');
    const panel = panelOf(page);
    await expect(panel).toHaveAttribute('data-kind', 'scriptAgent');
    await panel.getByTestId('bv-fold-script-trigger').click();
    await expect(panel.getByTestId('bv-fold-script')).toContainText('os.listdir');
    await shot(page, 'script-agent');
    await close(page);

    await openStage(page, 'bv-n-ship');
    await expect(panelOf(page).getByTestId('bv-error')).toContainText('could not run');
    await shot(page, 'failed-stage');
  });

  test('the top strip stays one line, even on a narrow window', async ({ page }) => {
    await page.setViewportSize({ width: 420, height: 820 });
    await openAgent(page, 'writer');

    await settled(page);
    const strip = panelOf(page).getByTestId('bv-strip');
    const box = await strip.boundingBox();
    expect(box).not.toBeNull();
    // One line: the strip's own height, not a block that grew.
    expect(box!.height).toBeLessThanOrEqual(56);
    // And on a phone the view is the whole screen.
    const panel = await panelOf(page).boundingBox();
    expect(panel!.width).toBeGreaterThanOrEqual(419);

    await shot(page, 'phone');
  });

  test('the bottom live panel keeps step with the view', async ({ page }) => {
    await openAgent(page, 'writer');
    await close(page);

    // Clicking in the view set the panel's pick; the panel still works.
    await expect(page.getByTestId('live-panel')).toBeVisible();
    await expect(page.getByTestId('live-panel')).toContainText('writer');
  });
});

/* ---------- the size of run this has to stay quick on ---------- */

/**
 * 126 agents over seven stages, and one agent with 120 calls: the shape of
 * the runs this page is really used on. The view has to open at once, and a
 * long stream must not mount in one go.
 */
function bigSnapshot() {
  const STAGES = 7;
  const PER_STAGE = 18;
  const nodes = [];
  for (let s = 0; s < STAGES; s++) {
    const agents = [];
    for (let i = 0; i < PER_STAGE; i++) {
      const id = `big-a-${s}-${i}`;
      const busy = s === 0 && i === 0;
      agents.push({
        id,
        agent_name: busy ? 'the_busy_one' : `agent_${s}_${i}`,
        status: 'completed',
        start_time: at(s * 10),
        end_time: at(s * 10 + 9),
        duration_seconds: 9,
        model: 'claude-sonnet-4-5',
        provider: 'claude_code',
        total_tokens: 1200,
        cost_usd: 0.004,
        input_data: { step: i },
        output_data: { done: true },
        llm_calls: busy
          ? Array.from({ length: 60 }, (_, c) => ({
              id: `big-llm-${c}`,
              agent_execution_id: id,
              provider: 'claude_code',
              model: 'claude-sonnet-4-5',
              status: 'completed',
              start_time: at(c * 2),
              end_time: at(c * 2 + 1),
              duration_seconds: 1,
              total_tokens: 900,
              estimated_cost_usd: 0.002,
              prompt: [{ role: 'user', content: `step ${c}` }],
              response: `answer ${c}`,
            }))
          : [],
        tool_calls: busy
          ? Array.from({ length: 60 }, (_, c) => ({
              id: `big-tool-${c}`,
              agent_execution_id: id,
              tool_name: 'Read',
              status: 'success',
              start_time: at(c * 2 + 1),
              end_time: at(c * 2 + 2),
              duration_seconds: 1,
              arguments: { path: `file_${c}.py` },
              result: `contents of file ${c}`,
            }))
          : [],
      });
    }
    nodes.push({
      id: `big-n-${s}`,
      name: `stage_${s}`,
      stage_name: `stage_${s}`,
      node_type: 'stage',
      status: 'completed',
      start_time: at(s * 10),
      end_time: at(s * 10 + 9),
      duration_seconds: 9,
      depends_on: s === 0 ? [] : [`stage_${s - 1}`],
      agents,
      num_agents_executed: PER_STAGE,
      num_agents_succeeded: PER_STAGE,
      num_agents_failed: 0,
      total_tokens: 1200 * PER_STAGE,
      cost_usd: 0.004 * PER_STAGE,
    });
  }
  return {
    id: 'replay-bigview-0002',
    workflow_name: 'a_big_run',
    status: 'completed',
    start_time: at(0),
    end_time: at(70),
    duration_seconds: 70,
    nodes,
    stages: nodes,
    total_tokens: 1200 * STAGES * PER_STAGE,
    total_cost_usd: 0.004 * STAGES * PER_STAGE,
    total_llm_calls: 60,
    total_tool_calls: 60,
    input_data: { what: 'a lot' },
    output_data: { done: true },
  };
}

test.describe('on a big run', () => {
  test('opens at once, and a long stream arrives in pieces', async ({ page }) => {
    await replayInto(page, bigSnapshot());
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    expect(await page.getByTestId('live-agent-row').count()).toBeGreaterThan(100);

    // The run itself: everything the page knows, in one view.
    let t0 = Date.now();
    await openRunItself(page);
    const runMs = Date.now() - t0;
    await close(page);

    // The agent with 120 calls.
    await page.getByTestId('live-agent-row').filter({ hasText: 'the_busy_one' }).first().click();
    t0 = Date.now();
    await page.getByTestId('live-details-button').click();
    await expect(panelOf(page)).toBeVisible();
    await expect(panelOf(page).getByTestId('bv-timeline')).toHaveAttribute('data-rows', '120');
    const agentMs = Date.now() - t0;

    // Folded rows are not mounted: the stream arrives a page at a time.
    const mounted = await panelOf(page).getByTestId('bv-row').count();
    expect(mounted).toBeGreaterThan(0);
    expect(mounted, 'a folded stream should not mount all 120 rows').toBeLessThan(60);
    await panelOf(page).getByTestId('bv-timeline-more').click();
    expect(await panelOf(page).getByTestId('bv-row').count()).toBeGreaterThan(mounted);

    // "Feels instant": a second and a half is generous for a cold open on CI.
    expect(runMs, `the run itself took ${runMs}ms`).toBeLessThan(1500);
    expect(agentMs, `the busy agent took ${agentMs}ms`).toBeLessThan(1500);

    await shot(page, 'big-run');
  });
});
