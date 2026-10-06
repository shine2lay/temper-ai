/**
 * Calls to the Team page API (/api/team/*), all through authFetch.
 *
 * The routes exist only while the server's Team switch is on: with it off
 * every one of them answers 404, and the page treats that as "no Team".
 */
import { authFetch } from '@/lib/authFetch';
import type {
  TeamAnswerRequest,
  TeamAnswerResult,
  TeamCancelResult,
  TeamCheckResult,
  TeamMessage,
  TeamMessageRequest,
  TeamMessageSent,
  TeamRoles,
  TeamRun,
  TeamStatus,
  TeamTrialInput,
  TeamTrialRequest,
  TeamTrialStarted,
  TeamTrialsPage,
} from '@/types/team';

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

/**
 * No reply came: the network failed, Temper took too long, or it failed
 * (5xx) before saying what it did. The request may or may not have been
 * done, so a retry must send the same request id.
 */
export class TeamNoAnswerError extends Error {
  constructor(message = "Temper didn't answer") {
    super(message);
    this.name = 'TeamNoAnswerError';
  }
}

/** How long a send waits for Temper before it counts as no answer. */
export const TEAM_SEND_TIMEOUT_MS = 30_000;

/** How long a trial start waits (SPEC 3: no answer in 20 s is "Temper didn't answer"). */
export const TEAM_START_TIMEOUT_MS = 20_000;

async function refusal(response: Response): Promise<TeamApiError> {
  let detail: unknown = null;
  try {
    const body = await response.json();
    detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
  } catch {
    /* not JSON: keep the status only */
  }
  return new TeamApiError(response.status, detail);
}

async function readJson<T>(url: string): Promise<T> {
  const response = await authFetch(url);
  if (!response.ok) throw await refusal(response);
  return (await response.json()) as T;
}

/**
 * POST a JSON body. A refusal (4xx) throws TeamApiError with the server's
 * own words; no reply at all (network, timeout, 5xx) throws
 * TeamNoAnswerError.
 */
async function postJson<T>(url: string, body: unknown, timeoutMs: number = TEAM_SEND_TIMEOUT_MS): Promise<T> {
  let response: Response;
  try {
    const timeout =
      typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
        ? AbortSignal.timeout(timeoutMs)
        : undefined;
    response = await authFetch(url, { method: 'POST', body: JSON.stringify(body), signal: timeout });
  } catch {
    throw new TeamNoAnswerError();
  }
  if (response.status >= 500) throw new TeamNoAnswerError();
  if (!response.ok) throw await refusal(response);
  try {
    return (await response.json()) as T;
  } catch {
    throw new TeamNoAnswerError();
  }
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

/**
 * POST /api/team/runs/{id}/waits/{wait_id}/answer: the only way the page
 * answers Temper. 409 carries who answered first (answered_by, answered_at,
 * answered_source); 400 carries `problem`.
 */
export function postTeamAnswer(executionId: string, waitId: string, body: TeamAnswerRequest): Promise<TeamAnswerResult> {
  return postJson<TeamAnswerResult>(
    `/api/team/runs/${encodeURIComponent(executionId)}/waits/${encodeURIComponent(waitId)}/answer`,
    body,
  );
}

/**
 * POST /api/runs/{id}/cancel: Stop run. The answer is the run's own status;
 * anything but cancelling or cancelled means the run had already ended.
 */
export function postCancelRun(executionId: string, reason: string): Promise<TeamCancelResult> {
  return postJson<TeamCancelResult>(`/api/runs/${encodeURIComponent(executionId)}/cancel`, { reason });
}

/**
 * GET /api/team/trials: newest first, one item per run of a trial's
 * workflow (its own run, then its re-runs and forks).
 */
export function fetchTeamTrials(limit: number, offset: number): Promise<TeamTrialsPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return readJson<TeamTrialsPage>(`/api/team/trials?${query.toString()}`);
}

/** GET /api/team/roles: the box's role list, read only. */
export function fetchTeamRoles(): Promise<TeamRoles> {
  return readJson<TeamRoles>('/api/team/roles');
}

/** POST /api/team/check: every check a start makes; writes nothing, takes no request id. */
export function postTeamCheck(input: TeamTrialInput): Promise<TeamCheckResult> {
  return postJson<TeamCheckResult>('/api/team/check', input, TEAM_START_TIMEOUT_MS);
}

/**
 * POST /api/team/trials: Run trial. 400 carries {problems, notes} (or
 * {problem} without a request id); 409 request_id_reused; 401/403 the guard.
 */
export function postTeamTrial(request: TeamTrialRequest): Promise<TeamTrialStarted> {
  return postJson<TeamTrialStarted>('/api/team/trials', request, TEAM_START_TIMEOUT_MS);
}

/** POST /api/team/runs/{id}/messages: one message to a member (pending or held). */
export function postTeamMessage(executionId: string, request: TeamMessageRequest): Promise<TeamMessageSent> {
  return postJson<TeamMessageSent>(`/api/team/runs/${encodeURIComponent(executionId)}/messages`, request);
}

export const teamKeys = {
  status: ['team', 'status'] as const,
  run: (executionId: string) => ['team', 'run', executionId] as const,
  message: (executionId: string, messageId: string) => ['team', 'message', executionId, messageId] as const,
  trials: (limit: number, offset: number) => ['team', 'trials', limit, offset] as const,
  roles: ['team', 'roles'] as const,
};
