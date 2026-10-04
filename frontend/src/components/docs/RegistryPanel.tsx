import { useRegistries } from '@/hooks/useDocsAPI';
import type { RegistryEntry } from '@/hooks/useDocsAPI';

interface RegistryTableProps {
  title: string;
  entries: RegistryEntry[];
}

function RegistryTable({ title, entries }: RegistryTableProps) {
  if (entries.length === 0) return null;

  return (
    <div className="mb-8">
      <h3 className="text-base font-semibold text-temper-text mb-3">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
              <tr className="border-b border-temper-border text-left">
                <th className="py-2 pr-4 font-medium text-temper-muted whitespace-nowrap">Name</th>
                <th className="py-2 pr-4 font-medium text-temper-muted">Description</th>
                {entries.some((e) => e.class_path) && (
                  <th className="py-2 font-medium text-temper-muted whitespace-nowrap">Class</th>
                )}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.name} className="border-b border-temper-border/50 hover:bg-temper-surface/50">
                  <td className="py-2 pr-4 align-top">
                    <code className="font-mono text-xs text-temper-accent bg-temper-accent/10 px-1.5 py-0.5 rounded whitespace-nowrap">
                      {entry.name}
                    </code>
                  </td>
                  <td className="py-2 pr-4 align-top text-temper-text">
                    {entry.description || <span className="text-temper-muted italic text-xs">—</span>}
                  </td>
                  {entries.some((e) => e.class_path) && (
                    <td className="py-2 align-top">
                      {entry.class_path ? (
                        <code className="font-mono text-xs text-temper-muted">{entry.class_path}</code>
                      ) : (
                        <span className="text-temper-muted">—</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
      </div>
    </div>
  );
}

export function RegistryPanel() {
  const { data, isLoading, error } = useRegistries();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-temper-muted text-sm">
        Loading registries…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-400">
        Failed to load registries: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="p-6">
      <RegistryTable title="Agent Types" entries={data.agent_types} />
      <RegistryTable title="Strategies" entries={data.strategies} />
      <RegistryTable title="Resolvers" entries={data.resolvers} />
      <RegistryTable title="Tools" entries={data.tools} />
    </div>
  );
}
