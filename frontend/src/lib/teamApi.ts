/**
 * Calls to the Team page API (/api/team/*), all through authFetch.
 *
 * The routes exist only while the server's Team switch is on: with it off
 * every one of them answers 404, and the page treats that as "no Team".
 */
import { authFetch } from '@/lib/authFetch';
import type { TeamMessage, TeamRun, TeamStatus } from '@/types/team';

/** A refusal or failure from the Team API, with the server's own words. */
export class TeamApiError extends Error {
  readonly status: number;
  /** The response's `detail`, as sent (a string or a structured object). */
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Temper answered ${status}`);
    this.name = 'TeamApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function readJson<T>(url: string): Promise<T> {
  const response = await authFetch(url);
  if (!response.ok) {
    let detail: unknown = null;
    try {
      const body = await response.json();
      detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
    } catch {
      /* not JSON: keep the status only */
    }
    throw new TeamApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

/** GET /api/team/status: the switch, the limits and the guard mode. null when off. */
export async function fetchTeamStatus(): Promise<TeamStatus | null> {
  try {
    return await readJson<TeamStatus>('/api/team/status');
  } catch (err) {
    if (err instanceof TeamApiError && err.status === 404) return null;
    throw err;
  }
}

/** GET /api/team/runs/{id}: everything the run view shows. 404 when it isn't a team trial. */
export function fetchTeamRun(executionId: string): Promise<TeamRun> {
  return readJson<TeamRun>(`/api/team/runs/${encodeURIComponent(executionId)}`);
}

/** GET /api/team/runs/{id}/messages/{message_id}: one message's full body. */
export function fetchTeamMessage(executionId: string, messageId: string): Promise<TeamMessage> {
  return readJson<TeamMessage>(
    `/api/team/runs/${encodeURIComponent(executionId)}/messages/${encodeURIComponent(messageId)}`,
  );
}

export const teamKeys = {
  status: ['team', 'status'] as const,
  run: (executionId: string) => ['team', 'run', executionId] as const,
  message: (executionId: string, messageId: string) => ['team', 'message', executionId, messageId] as const,
};
