/**
 * Authenticated fetch wrapper.
 *
 * Reads API key from localStorage (runtime override) or from the
 * VITE_API_KEY env var baked in at build time.  Attaches it as a
 * Bearer token on every request.
 */
import { toast } from 'sonner';

export function getApiKey(): string | null {
  return (
    localStorage.getItem('temper_api_key') ||
    window.__TEMPER_DASHBOARD_TOKEN__ ||
    import.meta.env.VITE_API_KEY ||
    null
  );
}

export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }
  const response = await fetch(input, {
    ...init,
    headers: {
      ...headers,
      ...init?.headers,
    },
  });

  if (response.status === 401) {
    localStorage.removeItem('temper_api_key');
    toast.error('Session expired. Please re-enter your API key.');
    window.location.href = '/app/login';
  } else if (response.status === 403) {
    toast.error('Permission denied. You do not have access to this resource.');
  }

  return response;
}
