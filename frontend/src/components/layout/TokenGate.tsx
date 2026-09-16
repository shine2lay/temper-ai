import { KeyRound } from 'lucide-react';
import { useEffect, useState } from 'react';

import { clearApiKey, getApiKey, setApiKey, setUnauthorizedHandler } from '@/lib/authFetch';

/**
 * Asks for the API token when the server requires one.
 *
 * Shown on first load if the server reports auth_required and nothing is
 * stored, and again whenever a request comes back 401 — which is also how
 * a token that was revoked or mistyped surfaces.
 */
export function TokenGate({ children }: { children: React.ReactNode }) {
  const [needsToken, setNeedsToken] = useState(false);
  const [value, setValue] = useState('');
  const [rejected, setRejected] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setRejected(Boolean(getApiKey()));
      setNeedsToken(true);
    });

    // A plain fetch: asking whether a token is needed must not need one.
    fetch('/api/runtime-config')
      .then((r) => (r.ok ? r.json() : null))
      .then((config: { auth_required?: boolean } | null) => {
        if (config?.auth_required && !getApiKey()) setNeedsToken(true);
      })
      .catch(() => {
        /* server unreachable — the page's own error states cover it */
      });
  }, []);

  if (!needsToken) return <>{children}</>;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setApiKey(value);
    // Simplest correct way to re-run every query with the new token.
    window.location.reload();
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-temper-bg p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-temper-border bg-temper-surface p-6"
      >
        <div className="mb-4 flex items-center gap-2 text-temper-text">
          <KeyRound className="h-5 w-5 text-temper-accent" />
          <h1 className="text-base font-medium">This temper server needs a token</h1>
        </div>

        <p className="mb-4 text-sm text-temper-text-muted">
          {rejected
            ? 'That token was rejected. Check the value of TEMPER_API_TOKEN on the server.'
            : 'Paste the value of TEMPER_API_TOKEN. It stays in this browser.'}
        </p>

        <label htmlFor="api-token" className="mb-1 block text-xs text-temper-text-dim">
          API token
        </label>
        <input
          id="api-token"
          type="password"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mb-4 w-full rounded border border-temper-border bg-temper-bg px-3 py-2 text-sm text-temper-text"
          placeholder="TEMPER_API_TOKEN"
        />

        <div className="flex gap-2">
          <button
            type="submit"
            className="flex-1 rounded bg-temper-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            disabled={!value.trim()}
          >
            Continue
          </button>
          {getApiKey() && (
            <button
              type="button"
              onClick={() => {
                clearApiKey();
                setValue('');
              }}
              className="rounded border border-temper-border px-3 py-2 text-sm text-temper-text-muted"
            >
              Forget stored token
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
