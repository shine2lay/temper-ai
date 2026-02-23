/**
 * TanStack Query hooks for the Studio CRUD API and run trigger.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';

interface StudioConfigSummary {
  name: string;
  description: string;
  version: string;
}

interface StudioConfigList {
  configs: StudioConfigSummary[];
  total: number;
}

interface ValidationResult {
  valid: boolean;
  errors: string[];
}

interface RunResponse {
  execution_id: string;
  status: string;
  message: string;
}

const STUDIO_BASE = '/api/studio';
const RUNS_BASE = '/api/runs';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

/** List all configs of a given type (workflows, stages, agents, tools). */
export function useStudioConfigs(configType: string) {
  return useQuery<StudioConfigList>({
    queryKey: ['studio', 'configs', configType],
    queryFn: () => fetchJSON(`${STUDIO_BASE}/configs/${configType}`),
  });
}

/** Get a single config by type and name. */
export function useStudioConfig(configType: string, name: string | null) {
  return useQuery<Record<string, unknown>>({
    queryKey: ['studio', 'config', configType, name],
    queryFn: () => fetchJSON(`${STUDIO_BASE}/configs/${configType}/${name}`),
    enabled: !!name,
  });
}

/** Save (create or update) a workflow config. */
export function useSaveWorkflow() {
  const queryClient = useQueryClient();

  return useMutation<
    Record<string, unknown>,
    Error,
    { name: string; data: Record<string, unknown>; isNew: boolean }
  >({
    mutationFn: async ({ name, data, isNew }) => {
      const method = isNew ? 'POST' : 'PUT';
      return fetchJSON(`${STUDIO_BASE}/configs/workflows/${name}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['studio', 'configs', 'workflows'] });
    },
  });
}

/** Validate a workflow config without saving. */
export function useValidateWorkflow() {
  return useMutation<ValidationResult, Error, Record<string, unknown>>({
    mutationFn: async (data) => {
      return fetchJSON(`${STUDIO_BASE}/validate/workflows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
    },
  });
}

/** Save (create or update) an agent config. */
export function useSaveAgent() {
  const queryClient = useQueryClient();

  return useMutation<
    Record<string, unknown>,
    Error,
    { name: string; data: Record<string, unknown>; isNew: boolean }
  >({
    mutationFn: async ({ name, data, isNew }) => {
      const method = isNew ? 'POST' : 'PUT';
      return fetchJSON(`${STUDIO_BASE}/configs/agents/${name}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['studio', 'configs', 'agents'] });
    },
  });
}

/** Validate an agent config without saving. */
export function useValidateAgent() {
  return useMutation<ValidationResult, Error, Record<string, unknown>>({
    mutationFn: async (data) => {
      return fetchJSON(`${STUDIO_BASE}/validate/agents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
    },
  });
}

/** Trigger a workflow run. Returns execution_id for navigation. */
export function useRunWorkflow() {
  return useMutation<RunResponse, Error, { workflow: string; inputs?: Record<string, unknown> }>({
    mutationFn: async ({ workflow, inputs }) => {
      return fetchJSON(RUNS_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow, inputs: inputs ?? {} }),
      });
    },
  });
}
