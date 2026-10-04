import { useState } from 'react';
import { useSchemaDoc } from '@/hooks/useDocsAPI';
import { SchemaSection } from './SchemaSection';
import { ExamplesPanel } from './ExamplesPanel';
import { RegistryPanel } from './RegistryPanel';
import { cn } from '@/lib/utils';

type Tier = 'agent' | 'stage' | 'workflow' | 'tool';
type ActiveTab = Tier | 'registries';

const TIER_TABS: { label: string; value: Tier }[] = [
  { label: 'Agent', value: 'agent' },
  { label: 'Stage', value: 'stage' },
  { label: 'Workflow', value: 'workflow' },
  { label: 'Tool', value: 'tool' },
];

function SchemaPane({ tier }: { tier: Tier }) {
  const { data, isLoading, error } = useSchemaDoc(tier);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32 text-temper-muted text-sm">
        Loading schema…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-400">
        Failed to load schema: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    );
  }

  const sections = data?.sections ?? [];

  if (sections.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-temper-muted text-sm">
        No schema documentation available
      </div>
    );
  }

  return (
    <div>
      {sections.map((section) => (
        <SchemaSection key={section.class_name} section={section} />
      ))}
    </div>
  );
}

export function ConfigDocs() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('agent');

  const isTierTab = activeTab !== 'registries';
  const activeTier = isTierTab ? activeTab : 'agent';

  return (
    <div className="flex flex-col h-full bg-temper-bg">
      {/* Header with tab bar */}
      <div className="shrink-0 border-b border-temper-border bg-temper-panel px-6 py-3">
        <h1 className="text-base font-semibold text-temper-text mb-3">Config Reference</h1>
        <div className="flex items-center gap-1">
          {TIER_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                activeTab === tab.value
                  ? 'bg-temper-accent/15 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
              )}
            >
              {tab.label}
            </button>
          ))}
          <div className="mx-2 h-4 w-px bg-temper-border" />
          <button
            onClick={() => setActiveTab('registries')}
            className={cn(
              'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
              activeTab === 'registries'
                ? 'bg-temper-accent/15 text-temper-accent'
                : 'text-temper-text-muted hover:text-temper-text hover:bg-temper-surface',
            )}
          >
            Registries
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'registries' ? (
          <div className="h-full overflow-y-auto">
            <RegistryPanel />
          </div>
        ) : (
          <div className="flex h-full gap-0">
            {/* Left: Schema reference */}
            <div className="flex-1 overflow-y-auto p-6 border-r border-temper-border">
              <SchemaPane tier={activeTier} />
            </div>

            {/* Right: Examples panel */}
            <div className="w-80 shrink-0 overflow-y-auto p-4 bg-temper-panel">
              <ExamplesPanel tier={activeTier} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
