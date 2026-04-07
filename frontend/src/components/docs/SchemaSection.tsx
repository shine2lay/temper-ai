import type { SectionDoc } from '@/hooks/useDocsAPI';
import { FieldsTable } from './FieldsTable';

interface SchemaSectionProps {
  section: SectionDoc;
  depth?: number;
}

export function SchemaSection({ section, depth = 0 }: SchemaSectionProps) {
  const HeadingTag = depth === 0 ? 'h3' : 'h4';
  const headingClass = depth === 0
    ? 'text-base font-semibold text-temper-text'
    : 'text-sm font-medium text-temper-text';

  return (
    <div className="mb-6">
      <HeadingTag className={headingClass}>
        {section.heading || section.class_name}
      </HeadingTag>

      {section.description && (
        <p className="mt-1 mb-3 text-sm text-temper-text-muted leading-relaxed whitespace-pre-line">
          {section.description.trim()}
        </p>
      )}

      {section.fields.length > 0 && (
        <div className="mt-3">
          <FieldsTable fields={section.fields} />
        </div>
      )}

      {section.sub_sections.length > 0 && (
        <div className={`mt-4 ${depth > 0 ? 'pl-4 border-l border-temper-border' : ''}`}>
          {section.sub_sections.map((sub) => (
            <SchemaSection key={sub.class_name} section={sub} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
