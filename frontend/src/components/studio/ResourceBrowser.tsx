/**
 * Tabbed resource browser for the Studio left sidebar.
 * Tabs: Stages | Agents | Tools
 * Stages: draggable tiles + "New Stage" button
 * Agents: clickable tiles + "New Agent" button (creates scaffold in DB)
 * Tools: browse-only reference list
 */
import { useState, useRef, useCallback, type DragEvent, type KeyboardEvent } from 'react';
import { useDesignStore, defaultDesignStage, type DesignStage } from '@/store/designStore';
import { useConfigs, useCreateConfig } from '@/hooks/useConfigAPI';

type Tab = 'stages' | 'agents' | 'tools';

const TABS: { key: Tab; label: string }[] = [
  { key: 'stages', label: 'Stages' },
  { key: 'agents', label: 'Agents' },
  { key: 'tools', label: 'Tools' },
];

/* ---------- Stage tile (draggable + clickable) ---------- */

function StageTile({
  name,
  description,
  onAdd,
}: {
  name: string;
  description: string;
  onAdd: () => void;
}) {
  const onDragStart = (e: DragEvent) => {
    e.dataTransfer.setData('application/studio-stage-name', name);
    e.dataTransfer.setData('application/studio-stage-ref', `configs/stages/${name}.yaml`);
    e.dataTransfer.effectAllowed = 'move';
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onAdd();
    }
  };

  return (
    <div
      draggable
      tabIndex={0}
      role="button"
      aria-label={`Add stage: ${name}`}
      onDragStart={onDragStart}
      onClick={onAdd}
      onKeyDown={onKeyDown}
      className="px-2.5 py-1.5 rounded-md bg-temper-surface border border-temper-border cursor-grab hover:border-temper-accent/50 hover:bg-temper-accent/5 focus:outline-none focus:ring-2 focus:ring-temper-accent/50 transition-colors"
      title={description || name}
    >
      <div className="text-[11px] font-medium text-temper-text truncate">{name}</div>
      {description && (
        <div className="text-[10px] text-temper-text-muted truncate mt-0.5">
          {description}
        </div>
      )}
    </div>
  );
}

/* ---------- Agent tile (clickable) ---------- */

function AgentTile({
  name,
  description,
  onClick,
}: {
  name: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left px-2.5 py-1.5 rounded-md bg-temper-surface border border-temper-border hover:border-temper-accent/50 hover:bg-temper-accent/5 focus:outline-none focus:ring-2 focus:ring-temper-accent/50 transition-colors"
      title={description || name}
    >
      <div className="text-[11px] font-medium text-temper-text truncate">{name}</div>
      {description && (
        <div className="text-[10px] text-temper-text-muted truncate mt-0.5">
          {description}
        </div>
      )}
    </button>
  );
}

/* ---------- Tool tile (browse-only) ---------- */

function ToolTile({ name, description }: { name: string; description: string }) {
  return (
    <div
      className="px-2.5 py-1.5 rounded-md bg-temper-surface/50 border border-temper-border/50"
      title={description || name}
    >
      <div className="text-[11px] font-medium text-temper-text-dim truncate">{name}</div>
      {description && (
        <div className="text-[10px] text-temper-text-dim truncate mt-0.5">
          {description}
        </div>
      )}
    </div>
  );
}

/* ---------- Main ResourceBrowser ---------- */

export function ResourceBrowser() {
  const [activeTab, setActiveTab] = useState<Tab>('stages');
  const [search, setSearch] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  const { data: stageData, isLoading: stagesLoading } = useConfigs('stage');
  const { data: agentData, isLoading: agentsLoading } = useConfigs('agent');
  const { data: toolData, isLoading: toolsLoading } = useConfigs('tool');

  const createStageMutation = useCreateConfig('stage');
  const createAgentMutation = useCreateConfig('agent');

  const addStage = useDesignStore((s) => s.addStage);
  const selectStage = useDesignStore((s) => s.selectStage);
  const selectAgent = useDesignStore((s) => s.selectAgent);
  const existingStages = useDesignStore((s) => s.stages);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);

  const filterConfigs = useCallback(
    (configs: { name: string; description?: string }[] | undefined) => {
      if (!configs) return [];
      return configs
        .filter((c) => !search || c.name.toLowerCase().includes(search.toLowerCase()))
        .sort((a, b) => a.name.localeCompare(b.name));
    },
    [search],
  );

  /** Generate unique name avoiding collisions with existing items. */
  function generateUniqueName(base: string, existingNames: Set<string>): string {
    if (!existingNames.has(base)) return base;
    let n = 1;
    while (existingNames.has(`${base}_${n}`)) n++;
    return `${base}_${n}`;
  }

  /** Add existing stage config to canvas. */
  const handleAddStage = useCallback(
    (stageName: string, stageRef: string) => {
      const existing = new Set(existingStages.map((s) => s.name));
      const name = generateUniqueName(stageName, existing);
      const newStage: DesignStage = {
        ...defaultDesignStage(name),
        stage_ref: stageRef || null,
      };
      addStage(newStage);
      selectStage(name);
    },
    [addStage, selectStage, existingStages],
  );

  /** Create a new blank stage in DB and add to canvas. */
  const handleNewStage = useCallback(async () => {
    const existingStageNames = new Set([
      ...existingStages.map((s) => s.name),
      ...(stageData?.configs?.map((c) => c.name) ?? []),
    ]);
    const name = generateUniqueName('new_stage', existingStageNames);

    let savedToDb = false;
    try {
      await createStageMutation.mutateAsync({
        name,
        config_data: { stage: { name, agents: [], execution: { agent_mode: 'sequential' } } },
      });
      savedToDb = true;
    } catch {
      // Add as inline stage if DB create fails
    }

    const newStage: DesignStage = {
      ...defaultDesignStage(name),
      stage_ref: savedToDb ? `configs/stages/${name}.yaml` : null,
    };
    addStage(newStage);
    selectStage(name);
  }, [addStage, selectStage, existingStages, stageData, createStageMutation]);

  /** Assign agent to selected stage or just select the agent. */
  const handleAssignAgent = useCallback(
    (agentName: string) => {
      if (selectedStageName) {
        const store = useDesignStore.getState();
        const stage = store.stages.find((s) => s.name === selectedStageName);
        if (stage && !stage.agents.includes(agentName)) {
          store.updateStage(selectedStageName, {
            agents: [...stage.agents, agentName],
          });
        }
      }
      selectAgent(agentName);
    },
    [selectedStageName, selectAgent],
  );

  /** Create a new agent scaffold in DB. */
  const handleNewAgent = useCallback(async () => {
    const existingAgentNames = new Set(agentData?.configs?.map((c) => c.name) ?? []);
    const name = generateUniqueName('new_agent', existingAgentNames);

    try {
      await createAgentMutation.mutateAsync({
        name,
        config_data: {
          agent: {
            name,
            description: '',
            prompt: { inline: '' },
            inference: { provider: '', model: '', temperature: 0.7, max_tokens: 4096 },
            error_handling: {
              retry_strategy: 'ExponentialBackoff',
              max_retries: 2,
              fallback: 'GracefulDegradation',
            },
            tools: [],
          },
        },
      });
    } catch {
      // Silently continue
    }

    // If a stage is selected, add agent to it
    if (selectedStageName) {
      const store = useDesignStore.getState();
      const stage = store.stages.find((s) => s.name === selectedStageName);
      if (stage) {
        store.updateStage(selectedStageName, {
          agents: [...stage.agents, name],
        });
      }
    }
    selectAgent(name);
  }, [agentData, createAgentMutation, selectedStageName, selectAgent]);

  /** Arrow key navigation within list. */
  const onListKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const items = listRef.current?.querySelectorAll<HTMLElement>('[role="button"], button');
    if (!items || items.length === 0) return;
    const focused = document.activeElement as HTMLElement;
    const arr = Array.from(items);
    const idx = arr.indexOf(focused);
    if (e.key === 'ArrowDown') {
      arr[idx < arr.length - 1 ? idx + 1 : 0]?.focus();
    } else {
      arr[idx > 0 ? idx - 1 : arr.length - 1]?.focus();
    }
  }, []);

  const stages = filterConfigs(stageData?.configs);
  const agents = filterConfigs(agentData?.configs);
  const tools = filterConfigs(toolData?.configs);
  const isLoading =
    activeTab === 'stages' ? stagesLoading : activeTab === 'agents' ? agentsLoading : toolsLoading;

  return (
    <div className="flex flex-col border-t border-temper-border">
      {/* Tab bar */}
      <div className="flex border-b border-temper-border">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key);
              setSearch('');
            }}
            className={`flex-1 px-1 py-1.5 text-[10px] font-medium transition-colors ${
              activeTab === tab.key
                ? 'text-temper-accent border-b-2 border-temper-accent'
                : 'text-temper-text-dim hover:text-temper-text'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="px-2 pt-1.5">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${activeTab}...`}
          className="w-full px-2 py-1 text-[11px] bg-temper-surface border border-temper-border rounded text-temper-text placeholder:text-temper-text-dim"
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <p className="text-[10px] text-temper-text-muted px-3 py-2">Loading...</p>
      )}

      {/* List */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div
        ref={listRef}
        className="flex flex-col gap-1 px-2 py-1.5 overflow-y-auto"
        style={{ maxHeight: 'calc(100vh - 400px)' }}
        onKeyDown={onListKeyDown}
      >
        {/* Stages tab */}
        {activeTab === 'stages' && (
          <>
            {stages.map((cfg) => (
              <StageTile
                key={cfg.name}
                name={cfg.name}
                description={cfg.description ?? ''}
                onAdd={() => handleAddStage(cfg.name, `configs/stages/${cfg.name}.yaml`)}
              />
            ))}
            {stages.length === 0 && !stagesLoading && (
              <p className="text-[10px] text-temper-text-dim px-1">No matches</p>
            )}
            {/* Blank stage button */}
            <div
              role="button"
              tabIndex={0}
              onClick={() => handleAddStage('new_stage', '')}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleAddStage('new_stage', '');
                }
              }}
              className="px-2.5 py-1.5 rounded-md border border-dashed border-temper-border cursor-pointer hover:border-temper-accent/50 transition-colors"
            >
              <div className="text-[11px] font-medium text-temper-text-muted">+ Blank Stage</div>
            </div>
            {/* Create new stage in DB */}
            <button
              onClick={handleNewStage}
              disabled={createStageMutation.isPending}
              className="px-2.5 py-1.5 rounded-md bg-temper-accent/10 border border-temper-accent/30 hover:bg-temper-accent/20 text-[11px] font-medium text-temper-accent transition-colors disabled:opacity-50"
            >
              + New Stage
            </button>
          </>
        )}

        {/* Agents tab */}
        {activeTab === 'agents' && (
          <>
            {selectedStageName && (
              <p className="text-[10px] text-temper-accent px-1 py-0.5">
                Click to assign to &quot;{selectedStageName}&quot;
              </p>
            )}
            {agents.map((cfg) => (
              <AgentTile
                key={cfg.name}
                name={cfg.name}
                description={cfg.description ?? ''}
                onClick={() => handleAssignAgent(cfg.name)}
              />
            ))}
            {agents.length === 0 && !agentsLoading && (
              <p className="text-[10px] text-temper-text-dim px-1">No matches</p>
            )}
            <button
              onClick={handleNewAgent}
              disabled={createAgentMutation.isPending}
              className="px-2.5 py-1.5 rounded-md bg-temper-accent/10 border border-temper-accent/30 hover:bg-temper-accent/20 text-[11px] font-medium text-temper-accent transition-colors disabled:opacity-50"
            >
              + New Agent
            </button>
          </>
        )}

        {/* Tools tab */}
        {activeTab === 'tools' && (
          <>
            {tools.map((cfg) => (
              <ToolTile
                key={cfg.name}
                name={cfg.name}
                description={cfg.description ?? ''}
              />
            ))}
            {tools.length === 0 && !toolsLoading && (
              <p className="text-[10px] text-temper-text-dim px-1">No tools found</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
