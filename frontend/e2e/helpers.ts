import type { APIRequestContext } from '@playwright/test';

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
