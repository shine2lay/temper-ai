/**
 * Fetch wrapper — no auth required for v1.
 *
 * v1 has no authentication. This module exists to maintain the same
 * import interface as the main codebase so components don't need changes.
 */

export function getApiKey(): string | null {
  return null; // No auth in v1
}

export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });
}
