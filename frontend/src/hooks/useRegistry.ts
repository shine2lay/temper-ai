/**
 * Fetches runtime registry values from the backend so Studio dropdowns
 * stay in sync with registered strategies, providers, tools, etc.
 */
import { useQuery } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';

export interface Registry {
  strategies: string[];
  agent_types: string[];
  providers: string[];
  tools: string[];
  safety_policies: string[];
  condition_operators: string[];
}

async function fetchRegistry(): Promise<Registry> {
  const res = await authFetch('/api/studio/registry');
  if (!res.ok) throw new Error(`Registry fetch failed: ${res.status}`);
  return res.json();
}

/** Singleton query — cached for the lifetime of the app. */
export function useRegistry() {
  return useQuery<Registry>({
    queryKey: ['studio', 'registry'],
    queryFn: fetchRegistry,
    staleTime: 5 * 60 * 1000, // 5 min — registries rarely change at runtime
  });
}

/** Convert a string array into InlineSelect options. */
export function toOptions(values: string[] | undefined): { value: string; label: string }[] {
  if (!values) return [];
  return values.map((v) => ({ value: v, label: v }));
}
