/**
 * TanStack Query hooks for the Config CRUD API (Plan 2) and Profile CRUD API (Plan 3).
 *
 * Config endpoints:  /api/configs/{type}
 * Profile endpoints: /api/profiles/{type}
 * Template endpoints: /api/configs/templates/{type}
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';

// ── Types ────────────────────────────────────────────────────────────

export interface ConfigSummary {
  name: string;
  description: string;
  config_type?: string;
  version?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ConfigDetail {
  id: string;
  name: string;
  description: string;
  config_data: Record<string, unknown>;
  config_type?: string;
  version?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ConfigListResponse {
  configs: ConfigSummary[];
  total: number;
}

export interface ProfileSummary {
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface ProfileDetail {
  id: string;
  name: string;
  description: string;
  config_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProfileListResponse {
  profiles: ProfileSummary[];
  total: number;
}

export interface TemplateSummary {
  name: string;
  description: string;
  filename: string;
}

export interface TemplateListResponse {
  templates: TemplateSummary[];
  total: number;
}

// ── Fetch helper ─────────────────────────────────────────────────────

const CONFIGS_BASE = '/api/studio/configs';
const PROFILES_BASE = '/api/studio/profiles';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Config CRUD hooks ────────────────────────────────────────────────

/** List all configs of a given type. */
export function useConfigs(configType: string) {
  return useQuery<ConfigListResponse>({
    queryKey: ['configs', configType],
    queryFn: () => fetchJSON(`${CONFIGS_BASE}/${configType}`),
  });
}

/** Get a single config by type and name. */
export function useConfig(configType: string, name: string | null) {
  return useQuery<ConfigDetail>({
    queryKey: ['configs', configType, name],
    queryFn: () => fetchJSON(`${CONFIGS_BASE}/${configType}/${name}`),
    enabled: !!name,
  });
}

/** Create a new config. */
export function useCreateConfig(configType: string) {
  const qc = useQueryClient();
  return useMutation<
    { id: string; name: string; version: number },
    Error,
    { name: string; description?: string; config_data: Record<string, unknown> }
  >({
    mutationFn: (body) =>
      fetchJSON(`${CONFIGS_BASE}/${configType}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['configs', configType] });
    },
  });
}

/** Update an existing config. */
export function useUpdateConfig(configType: string, name: string) {
  const qc = useQueryClient();
  return useMutation<
    Record<string, unknown>,
    Error,
    { description?: string; config_data?: Record<string, unknown> }
  >({
    mutationFn: (body) =>
      fetchJSON(`${CONFIGS_BASE}/${configType}/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['configs', configType] });
      qc.invalidateQueries({ queryKey: ['configs', configType, name] });
    },
  });
}

/** Delete a config. */
export function useDeleteConfig(configType: string) {
  const qc = useQueryClient();
  return useMutation<{ status: string }, Error, string>({
    mutationFn: (name) =>
      fetchJSON(`${CONFIGS_BASE}/${configType}/${name}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['configs', configType] });
    },
  });
}

/** Fork a config (DB or filesystem template) into a new tenant-owned copy. */
export function useForkConfig(configType: string) {
  const qc = useQueryClient();
  return useMutation<
    { id: string; name: string; forked_from: string },
    Error,
    { sourceName: string; newName: string; overrides?: Record<string, unknown> }
  >({
    mutationFn: ({ sourceName, newName, overrides }) =>
      fetchJSON(`${CONFIGS_BASE}/${configType}/${sourceName}/fork`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName, overrides: overrides ?? {} }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['configs', configType] });
    },
  });
}

/** List pre-deployed filesystem templates available for forking. */
export function useTemplates(configType: string) {
  return useQuery<TemplateListResponse>({
    queryKey: ['configs', 'templates', configType],
    queryFn: () => fetchJSON(`${CONFIGS_BASE}/templates/${configType}`),
  });
}

// ── Profile CRUD hooks ───────────────────────────────────────────────

/** List all profiles of a given type. */
export function useProfiles(profileType: string) {
  return useQuery<ProfileListResponse>({
    queryKey: ['profiles', profileType],
    queryFn: () => fetchJSON(`${PROFILES_BASE}/${profileType}`),
  });
}

/** Get a single profile by type and name. */
export function useProfile(profileType: string, name: string | null) {
  return useQuery<ProfileDetail>({
    queryKey: ['profiles', profileType, name],
    queryFn: () => fetchJSON(`${PROFILES_BASE}/${profileType}/${name}`),
    enabled: !!name,
  });
}

/** Create a new profile. */
export function useCreateProfile(profileType: string) {
  const qc = useQueryClient();
  return useMutation<
    { id: string; name: string; profile_type: string },
    Error,
    { name: string; description?: string; config_data: Record<string, unknown> }
  >({
    mutationFn: (body) =>
      fetchJSON(`${PROFILES_BASE}/${profileType}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profiles', profileType] });
    },
  });
}

/** Update an existing profile. */
export function useUpdateProfile(profileType: string, name: string) {
  const qc = useQueryClient();
  return useMutation<
    { id: string; name: string; profile_type: string },
    Error,
    { description?: string; config_data?: Record<string, unknown> }
  >({
    mutationFn: (body) =>
      fetchJSON(`${PROFILES_BASE}/${profileType}/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profiles', profileType] });
      qc.invalidateQueries({ queryKey: ['profiles', profileType, name] });
    },
  });
}

/** Delete a profile. */
export function useDeleteProfile(profileType: string) {
  const qc = useQueryClient();
  return useMutation<{ status: string }, Error, string>({
    mutationFn: (name) =>
      fetchJSON(`${PROFILES_BASE}/${profileType}/${name}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profiles', profileType] });
    },
  });
}
