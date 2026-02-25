import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './index.css';
import { initTheme } from './lib/theme';

// Apply stored/system theme before first render to avoid flash
initTheme();

declare global {
  interface Window {
    __TEMPER_DASHBOARD_TOKEN__?: string;
  }
}

/**
 * Fetch the runtime config from the backend and store the dashboard
 * token on `window` so authFetch can use it as a fallback API key.
 */
async function bootstrapRuntimeConfig(): Promise<void> {
  try {
    const res = await fetch('/api/runtime-config');
    if (!res.ok) return;
    const data = (await res.json()) as { dashboard_token?: string | null };
    if (data.dashboard_token) {
      window.__TEMPER_DASHBOARD_TOKEN__ = data.dashboard_token;
    }
  } catch (err) {
    console.warn('[temper] Could not fetch runtime-config:', err);
  }
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

function render() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  );
}

bootstrapRuntimeConfig().then(render);
