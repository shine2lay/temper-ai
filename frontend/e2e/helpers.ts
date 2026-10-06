import type { APIRequestContext, ConsoleMessage } from '@playwright/test';

/**
 * The Team switch's designed "off" answer. With the switch off (the
 * default), every page load asks GET /api/team/status once and gets 404:
 * that is how the dashboard learns to hide the Team page. Tests that fail on
 * any 404 or console error let this one answer through, and only it.
 */
export function isTeamSwitchOff(url: string, status: number): boolean {
  return status === 404 && new URL(url).pathname === '/api/team/status';
}

/** Chromium's console line for that same 404 (the message carries the resource's URL). */
export function isTeamSwitchOffConsole(msg: ConsoleMessage): boolean {
  const url = msg.location().url;
  return msg.type() === 'error' && Boolean(url) && msg.text().includes('404') && isTeamSwitchOff(url, 404);
}

/** Poll a run until `done` says it is far enough along, then return its state. */
async function waitForRun(
  request: APIRequestContext,
  id: string,
  done: (body: { status: string }) => boolean,
  what: string,
): Promise<Record<string, unknown>> {
  for (let i = 0; i < 40; i++) {
    const detail = await request.get(`/api/workflows/${id}`);
    if (detail.ok()) {
      const body = await detail.json();
      if (done(body)) return body;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`run ${id} ${what}`);
}

/** The gates a run is currently parked at (what the dashboard polls). */
export async function waitingGates(
  request: APIRequestContext,
  id: string,
): Promise<{ node_name: string }[]> {
  const res = await request.get(`/api/runs/${id}/gates`);
  return res.ok() ? ((await res.json()).gates ?? []) : [];
}

/**
 * Start the zero-cost `gate_smoke` workflow and wait until it parks at its
 * gate, so a test can open the dashboard and find the modal waiting.
 *
 * Parking is a property of the node, not the run: the run stays `running`
 * with a `waiting` node under it, so wait on the gate itself.
 */
export async function startGatedRun(request: APIRequestContext): Promise<string> {
  const res = await request.post('/api/runs', { data: { workflow: 'gate_smoke' } });
  if (!res.ok()) {
    throw new Error(`could not start gate_smoke: HTTP ${res.status()} ${await res.text()}`);
  }
  const { execution_id: id } = await res.json();
  for (let i = 0; i < 40; i++) {
    if ((await waitingGates(request, id)).length > 0) return id;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`run ${id} never reached its gate`);
}

/** Wait for a run to reach a terminal state and return it. */
export async function waitForFinish(
  request: APIRequestContext,
  id: string,
): Promise<Record<string, unknown>> {
  return waitForRun(
    request,
    id,
    (b) => ['completed', 'failed', 'cancelled'].includes(b.status),
    'did not finish in time',
  );
}

/**
 * Start the zero-cost `ci_nested` workflow and wait for it to finish.
 *
 * Its shape is the point: a stage (`outer`) with a stage inside it (`inner`),
 * the shape `epd_task` and `epd_propose` runs have. Script agents only, so it
 * costs nothing and needs no API key.
 */
export async function startNestedRun(request: APIRequestContext): Promise<string> {
  const res = await request.post('/api/runs', { data: { workflow: 'ci_nested' } });
  if (!res.ok()) {
    throw new Error(`could not start ci_nested: HTTP ${res.status()} ${await res.text()}`);
  }
  const { execution_id: id } = await res.json();
  await waitForFinish(request, id);
  return id;
}

/** Start a run of the zero-cost `smoke_test` workflow and wait for it to finish. */
export async function startSmokeRun(
  request: APIRequestContext,
  inputs: Record<string, unknown> = { message: 'e2e' },
): Promise<string> {
  const res = await request.post('/api/runs', {
    data: { workflow: 'smoke_test', inputs },
  });
  if (!res.ok()) {
    throw new Error(`could not start smoke_test: HTTP ${res.status()} ${await res.text()}`);
  }
  const { execution_id: id } = await res.json();

  for (let i = 0; i < 40; i++) {
    const detail = await request.get(`/api/workflows/${id}`);
    if (detail.ok()) {
      const body = await detail.json();
      if (['completed', 'failed', 'cancelled'].includes(body.status)) return id;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`smoke_test run ${id} did not finish in time`);
}
