import type { FieldDoc } from '@/hooks/useDocsAPI';

interface FieldsTableProps {
  fields: FieldDoc[];
}

export function FieldsTable({ fields }: FieldsTableProps) {
  if (fields.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-temper-border text-left">
            <th className="py-2 pr-4 font-medium text-temper-muted whitespace-nowrap">Field</th>
            <th className="py-2 pr-4 font-medium text-temper-muted whitespace-nowrap">Type</th>
            <th className="py-2 pr-4 font-medium text-temper-muted whitespace-nowrap">Default</th>
            <th className="py-2 pr-4 font-medium text-temper-muted whitespace-nowrap">Required</th>
            <th className="py-2 font-medium text-temper-muted">Description</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.name} className="border-b border-temper-border/50 hover:bg-temper-surface/50">
              <td className="py-2 pr-4 align-top">
                <code className="font-mono text-xs text-temper-accent bg-temper-accent/10 px-1.5 py-0.5 rounded whitespace-nowrap">
                  {field.name}
                </code>
              </td>
              <td className="py-2 pr-4 align-top">
                <span className="font-mono text-xs text-temper-text">{field.type || '—'}</span>
              </td>
              <td className="py-2 pr-4 align-top">
                {field.default != null ? (
                  <code className="font-mono text-xs text-temper-muted">{String(field.default)}</code>
                ) : (
                  <span className="text-temper-muted">—</span>
                )}
              </td>
              <td className="py-2 pr-4 align-top text-center">
                {field.required ? (
                  <span className="text-temper-accent" title="Required">✓</span>
                ) : (
                  <span className="text-temper-muted">—</span>
                )}
              </td>
              <td className="py-2 align-top text-temper-text">
                {field.description ? (
                  <span>{field.description}</span>
                ) : (
                  <span className="text-temper-muted italic text-xs">undocumented</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
