/**
 * TanStack Query hooks for the Config Docs API.
 */
import { useQuery } from '@tanstack/react-query';
import { authFetch } from '@/lib/authFetch';

export interface FieldDoc {
  name: string;
  type: string;
  default: string | null;
  required: boolean;
  description: string;
  constraints: Record<string, unknown>;
}

export interface SectionDoc {
  class_name: string;
  heading: string;
  description: string;
  fields: FieldDoc[];
  sub_sections: SectionDoc[];
}

export interface SchemaDocResponse {
  tier: string;
  sections: SectionDoc[];
}

export interface ExampleEntry {
  name: string;
  content: string;
}

export interface ExamplesResponse {
  tier: string;
  examples: ExampleEntry[];
}

export interface RegistryEntry {
  name: string;
  description: string;
  class_path?: string;
}

export interface RegistryResponse {
  agent_types: RegistryEntry[];
  strategies: RegistryEntry[];
  resolvers: RegistryEntry[];
  tools: RegistryEntry[];
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await authFetch(url);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

export function useSchemaDoc(tier: string) {
  return useQuery<SchemaDocResponse>({
    queryKey: ['docs', 'schema', tier],
    queryFn: () => fetchJSON(`/api/docs/schemas/${tier}`),
    staleTime: 5 * 60 * 1000,
    enabled: !!tier,
  });
}

export function useRegistries() {
  return useQuery<RegistryResponse>({
    queryKey: ['docs', 'registries'],
    queryFn: () => fetchJSON('/api/docs/registries'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useExamples(tier: string) {
  return useQuery<ExamplesResponse>({
    queryKey: ['docs', 'examples', tier],
    queryFn: () => fetchJSON(`/api/docs/examples/${tier}`),
    staleTime: 5 * 60 * 1000,
    enabled: !!tier,
  });
}
