/**
 * A made-up run, for pictures of the live panel.
 *
 * Nothing here is real: the agents, their words and their tools are invented
 * so the panel can be photographed in states a real run would take hours (and
 * money) to reach — many agents at once, a loop on its second round, a step
 * that failed, a run read back after it ended.
 *
 * The page under the camera is the real build. Only its two sources are
 * replaced: the REST snapshot and the websocket.
 */

export const RUN_ID = 'replay-live-0001';

/**
 * The made-up run starts a couple of minutes ago, so the times on screen read
 * like a run in progress rather than one that began last spring.
 */
const T0 = Date.now() - 130_000;

function at(secondsIn: number): string {
  return new Date(T0 + secondsIn * 1000).toISOString();
}

interface AgentSpec {
  id: string;
  name: string;
  status: string;
  started: number;
  ended?: number;
  cost?: number;
  round?: number;
  thinking?: string;
  said?: string;
  tools?: Array<{
    name: string;
    args: Record<string, unknown>;
    failed?: boolean;
    seconds?: number;
    result?: unknown;
    error?: string;
  }>;
}

function agent(spec: AgentSpec) {
  const calls = spec.thinking || spec.said
    ? [{
        id: `${spec.id}-llm-1`,
        agent_execution_id: spec.id,
        provider: 'claude_code',
        model: 'claude-sonnet-4-5',
        status: 'completed',
        start_time: at(spec.started + 1),
        end_time: at((spec.ended ?? spec.started + 30) - 1),
        duration_seconds: 20,
        prompt_tokens: 1800,
        completion_tokens: 420,
        total_tokens: 2220,
        estimated_cost_usd: spec.cost ?? 0.02,
        thinking: spec.thinking,
        response: spec.said,
      }]
    : [];
  const tools = (spec.tools ?? []).map((tool, i) => ({
    id: `${spec.id}-tool-${i + 1}`,
    tool_execution_id: `${spec.id}-tool-${i + 1}`,
    agent_execution_id: spec.id,
    tool_name: tool.name,
    status: tool.failed ? 'failed' : 'completed',
    start_time: at(spec.started + 2 + i * 3),
    end_time: at(spec.started + 2 + i * 3 + (tool.seconds ?? 2)),
    duration_seconds: tool.seconds ?? 2,
    input_params: tool.args,
    output_data: tool.result ?? { ok: true },
    error_message: tool.error,
  }));
  return {
    id: spec.id,
    agent_name: spec.name,
    status: spec.status,
    round: spec.round ?? 1,
    start_time: at(spec.started),
    end_time: spec.ended != null ? at(spec.ended) : null,
    duration_seconds: spec.ended != null ? spec.ended - spec.started : null,
    prompt_tokens: 1800,
    completion_tokens: 420,
    total_tokens: 2220,
    estimated_cost_usd: spec.cost ?? 0.02,
    total_llm_calls: calls.length,
    total_tool_calls: tools.length,
    llm_calls: calls,
    tool_calls: tools,
  };
}

function node(
  id: string,
  name: string,
  status: string,
  agents: ReturnType<typeof agent>[],
  extra: Record<string, unknown> = {},
) {
  return {
    id,
    name,
    type: 'stage',
    status,
    start_time: at(0),
    end_time: status === 'completed' ? at(120) : null,
    duration_seconds: status === 'completed' ? 120 : null,
    stage_name: name,
    depends_on: [],
    agents,
    ...extra,
  };
}

/** A run of moderate size: a few stages, a loop on its second round. */
export function replayRun() {
  const plan = node('n-plan', 'plan', 'completed', [
    agent({
      id: 'ag-plan-1', name: 'architect', status: 'completed', started: 0, ended: 40, cost: 0.04,
      thinking: 'The failing job is the release build, not the tests. Start there.',
      said: 'Plan: fix the release build, then re-run the suite.',
      tools: [{ name: 'Read', args: { file_path: '/repo/.github/workflows/release.yml' } }],
    }),
    agent({
      id: 'ag-plan-2', name: 'scout', status: 'completed', started: 2, ended: 35, cost: 0.01,
      said: 'Two workflows touch the same cache key.',
      tools: [{ name: 'Grep', args: { pattern: 'cache-key' }, seconds: 1 }],
    }),
  ]);

  const build = node('n-build', 'build', 'running', [
    agent({
      id: 'ag-build-1', name: 'coder', status: 'running', started: 45, cost: 0.06,
      tools: [
        { name: 'Read', args: { file_path: '/repo/scripts/release.sh' }, seconds: 1 },
        { name: 'Edit', args: { file_path: '/repo/scripts/release.sh' }, seconds: 1 },
      ],
    }),
    agent({ id: 'ag-build-2', name: 'doc-writer', status: 'running', started: 48, cost: 0.01 }),
    agent({
      id: 'ag-build-3', name: 'packager', status: 'failed', started: 46, ended: 70, cost: 0.02,
      said: 'The package step could not run.',
      tools: [{
        name: 'Bash', args: { command: 'npm run build:release' }, failed: true, seconds: 3,
        error: 'exit code 1: missing script "build:release"',
      }],
    }),
  ], { depends_on: ['plan'] });

  const review = node('n-review', 'review', 'running', [
    agent({
      id: 'ag-rev-1', name: 'reviewer', status: 'completed', started: 60, ended: 95, round: 1, cost: 0.03,
      thinking: 'Round one: the change is in the right place but the cache key is still shared.',
      said: 'Not yet — the cache key is still shared between jobs.',
    }),
    agent({ id: 'ag-rev-2', name: 'reviewer', status: 'running', started: 100, round: 2, cost: 0.01 }),
  ], { depends_on: ['build'], loop_to: 'build', max_loops: 3 });

  const ship = node('n-ship', 'ship', 'pending', [], { depends_on: ['review'] });

  const nodes = [plan, build, review, ship];
  return {
    id: RUN_ID,
    workflow_name: 'release_repair',
    status: 'running',
    start_time: at(0),
    end_time: null,
    duration_seconds: null,
    nodes,
    stages: nodes,
    total_tokens: 18400,
    total_cost_usd: 0.2,
    total_llm_calls: 7,
    total_tool_calls: 6,
  };
}

/** The same run, over: every agent finished, read back from what was stored. */
export function finishedRun() {
  const run = replayRun();
  const nodes = run.nodes.map((n) => ({
    ...n,
    status: n.name === 'ship' ? 'completed' : n.status === 'running' ? 'completed' : n.status,
    end_time: at(180),
    duration_seconds: 180,
    agents: n.agents.map((a) => ({
      ...a,
      status: a.status === 'failed' ? 'failed' : 'completed',
      end_time: a.end_time ?? at(170),
      duration_seconds: a.duration_seconds ?? 60,
    })),
  }));
  return { ...run, status: 'completed', end_time: at(180), duration_seconds: 180, nodes, stages: nodes };
}

/** A crowded run: many agents in one stage, so the list has to scroll. */
export function bigRun() {
  const workers = Array.from({ length: 24 }, (_, i) =>
    agent({
      id: `ag-worker-${i + 1}`,
      name: `worker-${String(i + 1).padStart(2, '0')}`,
      status: i < 18 ? 'completed' : 'running',
      started: 10 + i,
      ended: i < 18 ? 40 + i : undefined,
      cost: 0.01,
      said: i < 18 ? `Shard ${i + 1} done.` : undefined,
      tools: [{ name: 'Bash', args: { command: `pytest tests/shard_${i + 1}` }, seconds: 4 }],
    }),
  );
  const done = node('n-prep', 'prepare', 'completed', [
    agent({ id: 'ag-prep-1', name: 'splitter', status: 'completed', started: 0, ended: 9, said: 'Split into 24 shards.' }),
  ]);
  const fan = node('n-fan', 'fan_out', 'running', workers, { depends_on: ['prepare'] });
  const nodes = [done, fan];
  return {
    ...replayRun(),
    workflow_name: 'shard_suite',
    nodes,
    stages: nodes,
  };
}

export interface ReplayChunk {
  agentId: string;
  content: string;
  kind?: 'thinking' | 'text';
  callId?: string;
  done?: boolean;
}

/** What the agents "say" while the camera is on, a few words at a time. */
export const LIVE_WORDS: ReplayChunk[] = [
  ...words('ag-build-1', 'ag-build-1-llm-2', 'thinking',
    'The release script hard-codes last year\'s cache key, so every job fights over the same entry. ' +
    'I will give each job its own key and keep the shared one read-only.'),
  ...words('ag-build-1', 'ag-build-1-llm-2', 'text',
    'Rewriting the cache key so each job keeps its own entry.'),
  ...words('ag-build-2', 'ag-build-2-llm-2', 'text',
    'Drafting the release notes for the fixed build.'),
  ...words('ag-rev-2', 'ag-rev-2-llm-1', 'thinking',
    'Round two: the keys are separate now. Checking the fallback path.'),
];

function words(agentId: string, callId: string, kind: 'thinking' | 'text', text: string): ReplayChunk[] {
  return text.split(/(?<=\s)/).map((content) => ({ agentId, callId, kind, content }));
}

/** Tool steps that happen while the camera is on. */
export const LIVE_TOOLS = [
  {
    agentId: 'ag-build-1',
    toolId: 'ag-build-1-tool-3',
    name: 'Bash',
    args: { command: 'npm test -- --run' },
    seconds: 14,
  },
];
