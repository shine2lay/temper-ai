/**
 * The made-up pages the safe-rendering specs show content on: a run (agent
 * cards, big view, live panel, gate) and a Team run (goal, outcome,
 * timeline message). Every /api read is answered here; see
 * safeRenderingHarness.ts for the sealed browser.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, type Browser, type Page } from '@playwright/test';
import { openSealed, type ApiHandler, type Sealed } from './safeRenderingHarness';

export const BASE = process.env.TEMPER_E2E_BASE_URL ?? 'http://127.0.0.1:8420';
export const PLAIN = 'Plain words for this part.';

type Theme = 'dark' | 'light';
type Viewport = { width: number; height: number };

/* ---------- a made-up run ---------- */

export const RUN_ID = 'safe-rendering-0001';
const T0 = Date.now() - 300_000;
export const at = (s: number) => new Date(T0 + s * 1000).toISOString();

export interface AgentText {
  name: string;
  output?: string;
  reasoning?: string;
  response?: string;
  thinking?: string;
  script?: string;
  systemPrompt?: string;
  status?: string;
}

function agent(i: number, a: AgentText) {
  const script = a.script !== undefined;
  const call = {
    id: `sr-llm-${i}`,
    agent_execution_id: `sr-agent-${i}`,
    provider: 'claude_code',
    model: 'model-x',
    status: 'completed',
    start_time: at(i * 10 + 1),
    end_time: at(i * 10 + 5),
    duration_seconds: 4,
    latency_ms: 4000,
    prompt_tokens: 10,
    completion_tokens: 10,
    total_tokens: 20,
    estimated_cost_usd: 0.001,
    prompt: [{ role: 'user', content: PLAIN }],
    response: a.response ?? PLAIN,
    thinking: a.thinking,
  };
  return {
    id: `sr-agent-${i}`,
    agent_name: a.name,
    status: a.status ?? 'completed',
    round: 1,
    start_time: at(i * 10),
    end_time: a.status === 'running' ? null : at(i * 10 + 8),
    duration_seconds: a.status === 'running' ? null : 8,
    prompt_tokens: 10,
    completion_tokens: 10,
    total_tokens: 20,
    estimated_cost_usd: 0.001,
    total_llm_calls: script ? 0 : 1,
    total_tool_calls: 0,
    llm_calls: script ? [] : [call],
    tool_calls: [],
    output: a.output ?? PLAIN,
    reasoning: a.reasoning,
    agent_config_snapshot: script
      ? { agent: { agent: { type: 'script', timeout_seconds: 30, script_template: a.script } } }
      : { agent: { provider: 'claude_code', model: 'model-x', type: 'standard', system_prompt: a.systemPrompt ?? PLAIN } },
  };
}

export function runSnapshot(agents: AgentText[], status = 'completed') {
  const list = agents.map((a, i) => agent(i, a));
  const node = {
    id: 'sr-n-study',
    name: 'study',
    stage_name: 'study',
    type: 'stage',
    status,
    start_time: at(0),
    end_time: status === 'running' ? null : at(60),
    duration_seconds: status === 'running' ? null : 60,
    depends_on: [],
    agents: list,
    num_agents_executed: list.length,
    num_agents_succeeded: list.length,
    num_agents_failed: 0,
    cost_usd: 0.001,
    total_tokens: 20,
  };
  return {
    id: RUN_ID,
    workflow_name: 'safe_rendering_probe',
    status,
    start_time: at(0),
    end_time: status === 'running' ? null : at(60),
    duration_seconds: status === 'running' ? null : 60,
    nodes: [node],
    stages: [node],
    total_tokens: 20,
    total_cost_usd: 0.001,
    total_llm_calls: 1,
    total_tool_calls: 0,
  };
}

export type Snapshot = ReturnType<typeof runSnapshot>;

function runApi(snapshot: Snapshot, gates: unknown[] = []): ApiHandler {
  return (pathname) => {
    if (pathname === `/api/workflows/${RUN_ID}/agents`) {
      const node = snapshot.nodes[0];
      return {
        status: 200,
        body: {
          agents: node.agents.map((a) => ({
            id: a.id,
            agent_name: a.agent_name,
            round: a.round,
            status: a.status,
            node_id: node.id,
            node_name: node.name,
            start_time: a.start_time,
            end_time: a.end_time,
            duration_seconds: a.duration_seconds,
            total_tokens: a.total_tokens,
            estimated_cost_usd: a.estimated_cost_usd,
          })),
        },
      };
    }
    if (pathname === `/api/workflows/${RUN_ID}`) return { status: 200, body: snapshot };
    if (pathname === `/api/runs/${RUN_ID}/gates`) return { status: 200, body: { gates } };
    if (pathname.startsWith('/api/runs/')) return { status: 200, body: { gates: [], checkpoints: [] } };
    return null;
  };
}

export async function sealedRun(
  browser: Browser,
  snapshot: Snapshot,
  opts: { gates?: unknown[]; theme?: Theme; viewport?: Viewport } = {},
): Promise<Sealed> {
  const sealed = await openSealed(browser, BASE, runApi(snapshot, opts.gates), {
    snapshot,
    theme: opts.theme,
    viewport: opts.viewport,
  });
  await sealed.page.goto(`/app/workflow/${RUN_ID}`);
  await expect(sealed.page.getByTestId('live-panel')).toBeVisible();
  await expect(sealed.page.locator('.react-flow__node').first()).toBeVisible();
  return sealed;
}

export const bigView = (page: Page) => page.getByTestId('big-view');

export async function openAgent(page: Page, name: string) {
  await page.locator('.react-flow__node').getByText(name, { exact: true }).first().click();
  await expect(bigView(page)).toBeVisible();
}

/** A big-view fold; its box is always there, `data-open` says whether it is open. */
export async function openFold(page: Page, key: string) {
  const fold = page.getByTestId(`bv-fold-${key}`);
  await expect(fold).toBeVisible();
  if ((await fold.getAttribute('data-open')) !== 'true') await page.getByTestId(`bv-fold-${key}-trigger`).click();
  await expect(fold).toHaveAttribute('data-open', 'true');
  return fold;
}

export async function openOut(page: Page) {
  const body = page.getByTestId('bv-out-body');
  if (!(await body.isVisible())) await page.getByTestId('bv-out-toggle').click();
  await expect(body).toBeVisible();
  return body;
}

/* ---------- the Team run page ---------- */

export interface Fixture {
  route: string;
  status: number;
  body: Record<string, unknown>;
}

export function fixture(name: string): Fixture {
  return JSON.parse(readFileSync(path.join(process.cwd(), 'e2e/fixtures/team', `${name}.json`), 'utf8')) as Fixture;
}

const TEAM_RUN = /^\/api\/team\/runs\/[^/]+$/;
const TEAM_MESSAGE = /^\/api\/team\/runs\/[^/]+\/messages\/[^/]+$/;

function teamApi(run: Fixture, message: Fixture = fixture('message-read')): ApiHandler {
  const status = fixture('status-on');
  return (pathname) => {
    if (pathname === '/api/team/status') return { status: status.status, body: status.body };
    if (TEAM_MESSAGE.test(pathname)) return { status: message.status, body: message.body };
    if (TEAM_RUN.test(pathname)) return { status: run.status, body: run.body };
    return null;
  };
}

export function withGoal(run: Fixture, goal: string): Fixture {
  const body = structuredClone(run.body) as { trial: { goal: string } };
  body.trial.goal = goal;
  return { ...run, body: body as unknown as Record<string, unknown> };
}

export function withOutcome(run: Fixture, summary: string): Fixture {
  const body = structuredClone(run.body) as { outcome: { done: { summary: string } } };
  body.outcome.done.summary = summary;
  return { ...run, body: body as unknown as Record<string, unknown> };
}

export function withMessage(message: Fixture, text: string): Fixture {
  return { ...message, body: { ...message.body, body: text } };
}

export const GOAL = 'section[aria-labelledby="team-goal-title"]';
export const OUTCOME = 'section[aria-labelledby="team-outcome-summary"]';

export async function openTeamRun(
  browser: Browser,
  run: Fixture,
  opts: { message?: Fixture; theme?: Theme; viewport?: Viewport } = {},
): Promise<Sealed> {
  const sealed = await openSealed(browser, BASE, teamApi(run, opts.message), { theme: opts.theme, viewport: opts.viewport });
  await sealed.page.goto(`/app/team/runs/${String(run.body.execution_id)}`);
  await expect(sealed.page.locator(GOAL)).toBeVisible();
  return sealed;
}

/** Stand-in gate with an upstream output and one option's preview. */
export function gateWith(upstream: string, preview: string) {
  return {
    node_name: 'review',
    status: 'waiting',
    event_id: 'sr-gate-1',
    upstream: [{ node: 'study', output: upstream }],
    questions: [{ id: 'q1', question: 'Which way?', options: [{ label: 'First way', preview }, { label: 'Second way' }] }],
  };
}

/** A finished stream for agent 0, sent through the fake websocket. */
export function finishedStream(text: string) {
  return {
    type: 'event',
    event_type: 'llm_stream_batch',
    agent_id: 'sr-agent-0',
    timestamp: at(9),
    data: { chunks: [{ agent_id: 'sr-agent-0', content: text, chunk_type: 'content', call_id: 'sr-llm-0', done: true }] },
  };
}
