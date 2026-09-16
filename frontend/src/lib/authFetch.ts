/**
 * Fetch wrapper that carries the API token, when the server wants one.
 *
 * The server is open unless TEMPER_API_TOKEN is set, so this is a no-op
 * for most installs. When a token *is* required, every hook already goes
 * through authFetch, so this is the only place that needs to know.
 *
 * The token is typed in by the user and kept in localStorage. It is never
 * fetched from the server — an open endpoint that hands out the
 * credential would be pointless.
 */

const STORAGE_KEY = 'temper_api_token';

let onUnauthorized: (() => void) | null = null;

export function getApiKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // private browsing, storage disabled
  }
}

export function setApiKey(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token.trim());
    // Mirrored into a cookie so the WebSocket handshake can carry it:
    // browsers cannot set headers on a WebSocket.
    document.cookie = `temper_token=${encodeURIComponent(token.trim())}; path=/; SameSite=Strict`;
  } catch {
    /* ignore */
  }
}

export function clearApiKey(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
    document.cookie = 'temper_token=; path=/; Max-Age=0; SameSite=Strict';
  } catch {
    /* ignore */
  }
}

/** Called when the server rejects the token, so the UI can ask again. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getApiKey();
  const response = await fetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 401) {
    onUnauthorized?.();
  }
  return response;
}
