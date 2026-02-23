import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

export function LoginPage() {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = apiKey.trim();
    if (!trimmed) {
      setError('Please enter an API key.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch('/api/workflows', {
        headers: { Authorization: `Bearer ${trimmed}` },
      });

      if (res.status === 401 || res.status === 403) {
        setError('Invalid API key. Please check and try again.');
        return;
      }

      localStorage.setItem('temper_api_key', trimmed);
      navigate('/');
    } catch {
      setError('Could not connect to the server. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-temper-bg">
      <div className="w-full max-w-sm bg-temper-panel border border-temper-border rounded-lg p-8 flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-temper-text">Temper AI Dashboard</h1>
          <p className="text-sm text-temper-muted">
            Enter your API key to access the dashboard.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="api-key" className="text-sm text-temper-text">
              API Key
            </label>
            <input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="tk_..."
              autoComplete="current-password"
              className="w-full px-3 py-2 bg-temper-surface border border-temper-border rounded text-temper-text text-sm placeholder:text-temper-muted focus:outline-none focus:border-temper-accent"
            />
          </div>

          {error && (
            <p className="text-sm text-temper-failed">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-temper-accent text-temper-bg font-medium rounded text-sm hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {loading ? 'Connecting...' : 'Connect'}
          </button>
        </form>
      </div>
    </div>
  );
}
