import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useExamples } from '@/hooks/useDocsAPI';
import { cn } from '@/lib/utils';

interface ExamplesPanelProps {
  tier: string;
}

export function ExamplesPanel({ tier }: ExamplesPanelProps) {
  const { data, isLoading, error } = useExamples(tier);
  const [expanded, setExpanded] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-temper-muted text-sm">
        Loading examples…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-400">
        Failed to load examples: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    );
  }

  const examples = data?.examples ?? [];

  if (examples.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-temper-muted text-sm">
        No examples available
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-semibold text-temper-muted uppercase tracking-wider mb-2 px-1">
        Examples
      </h3>
      {examples.map((example) => {
        const isOpen = expanded === example.name;
        return (
          <div
            key={example.name}
            className="border border-temper-border rounded-md overflow-hidden"
          >
            <button
              onClick={() => setExpanded(isOpen ? null : example.name)}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition-colors',
                isOpen
                  ? 'bg-temper-surface text-temper-text'
                  : 'hover:bg-temper-surface/50 text-temper-text-muted hover:text-temper-text',
              )}
            >
              {isOpen ? (
                <ChevronDown className="w-3.5 h-3.5 shrink-0 text-temper-accent" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 shrink-0" />
              )}
              <span className="font-mono text-xs truncate">{example.name}</span>
            </button>
            {isOpen && (
              <div className="border-t border-temper-border bg-temper-bg">
                <pre className="overflow-x-auto p-3 text-xs font-mono text-temper-text leading-relaxed whitespace-pre">
                  <code>{example.content}</code>
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
