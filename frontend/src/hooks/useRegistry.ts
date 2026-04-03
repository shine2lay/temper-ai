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
  mcp_servers: string[];
  safety_policies: string[];
  condition_operators: string[];
}

async function fetchRegistry(): Promise<Registry> {
  const res = await authFetch('/api/studio/registry');
  if (!res.ok) throw new Error(`Registry fetch failed: ${res.status}`);
  const data = await res.json();

  // Fetch MCP servers from dedicated endpoint (separate from registry
  // because the registry endpoint may use cached bytecode in Docker)
  if (!data.mcp_servers || data.mcp_servers.length === 0) {
    try {
      const mcpRes = await authFetch('/api/mcp-servers');
      if (mcpRes.ok) {
        const mcpData = await mcpRes.json();
        data.mcp_servers = mcpData.mcp_servers ?? [];
      }
    } catch {
      // Endpoint may not exist on older backends
    }
  }
  if (!data.mcp_servers) data.mcp_servers = [];
  return data;
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
