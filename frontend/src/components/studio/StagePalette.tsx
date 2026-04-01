/**
 * Left panel for the Studio editor — a building-blocks library.
 *
 * Sections:
 * 1. Outline  — compact stage list (click to select, shows flow order)
 * 2. Agents   — drag or click to add to selected stage
 * 3. Tools    — reference list of registered tools
 */
import { useState, useCallback, type DragEvent, type KeyboardEvent as KBEvent } from 'react';
import { useDesignStore, defaultDesignStage, type DesignStage } from '@/store/designStore';
import { useConfigs } from '@/hooks/useConfigAPI';
import { useRegistry } from '@/hooks/useRegistry';
import { STAGE_PALETTE } from '@/lib/constants';

/* ---------- Section wrapper ---------- */

function Section({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-temper-border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-1.5 px-3 py-2 hover:bg-temper-surface/50 transition-colors"
      >
        <span className="text-[10px] text-temper-text-dim w-3">{open ? '\u25BC' : '\u25B6'}</span>
        <span className="text-xs font-semibold text-temper-text flex-1 text-left">{title}</span>
        {badge && <span className="text-[10px] text-temper-text-dim">{badge}</span>}
      </button>
      {open && <div className="px-2 pb-2">{children}</div>}
    </div>
  );
}

/* ---------- Outline ---------- */

function OutlineItem({
  stage,
  colorIndex,
  isSelected,
}: {
  stage: DesignStage;
  colorIndex: number;
  isSelected: boolean;
}) {
  const selectStage = useDesignStore((s) => s.selectStage);
  const color = STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];
  const isSingleAgent = stage.agents.length === 1 && !stage.stage_ref;

  return (
    <button
      onClick={() => selectStage(stage.name)}
      className={`w-full text-left px-2 py-1 rounded flex items-center gap-2 transition-colors text-[11px] ${
        isSelected
          ? 'bg-temper-accent/15 text-temper-text'
          : 'text-temper-text-muted hover:bg-temper-surface hover:text-temper-text'
      }`}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="truncate flex-1">{stage.name}</span>
      <span className={`text-[9px] px-1 py-px rounded shrink-0 ${
        isSingleAgent ? 'bg-violet-900/30 text-violet-400' : 'bg-blue-900/30 text-blue-400'
      }`}>
        {isSingleAgent ? 'agent' : `${stage.agents.length}a`}
      </span>
    </button>
  );
}

/* ---------- Agent tile ---------- */

function AgentTile({
  name,
  isAssigned,
  onAdd,
}: {
  name: string;
  isAssigned: boolean;
  onAdd: () => void;
}) {
  const onDragStart = (e: DragEvent) => {
    e.dataTransfer.setData('application/studio-stage-name', name);
    e.dataTransfer.setData('application/studio-agent-name', name);
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={isAssigned ? undefined : onAdd}
      role="button"
      tabIndex={0}
      onKeyDown={(e: KBEvent) => {
        if (!isAssigned && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onAdd(); }
      }}
      className={`w-full text-left px-2 py-1.5 rounded text-[11px] transition-colors cursor-grab active:cursor-grabbing ${
        isAssigned
          ? 'text-temper-text-dim opacity-50'
          : 'text-temper-text hover:bg-temper-accent/10'
      }`}
    >
      <span className="truncate">{name}</span>
      {isAssigned && <span className="text-[9px] text-temper-text-dim ml-1">(in stage)</span>}
    </div>
  );
}

/* ---------- Main export ---------- */

export function StagePalette() {
  const stages = useDesignStore((s) => s.stages);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const selectStage = useDesignStore((s) => s.selectStage);
  const addStage = useDesignStore((s) => s.addStage);
  const updateStage = useDesignStore((s) => s.updateStage);

  const { data: agentData } = useConfigs('agent');
  const { data: registry } = useRegistry();
  const [agentSearch, setAgentSearch] = useState('');

  // Agents from config store
  const allAgents = agentData?.configs?.map((c) => c.name).sort() ?? [];
  const filteredAgents = agentSearch
    ? allAgents.filter((n) => n.toLowerCase().includes(agentSearch.toLowerCase()))
    : allAgents;

  // Which agents are assigned to the selected stage
  const selectedStage = stages.find((s) => s.name === selectedStageName);
  const assignedAgents = new Set(selectedStage?.agents ?? []);

  // Add agent to selected stage, or create a new single-agent node
  const handleAddAgent = useCallback(
    (agentName: string) => {
      if (selectedStageName && selectedStage) {
        if (!selectedStage.agents.includes(agentName)) {
          updateStage(selectedStageName, { agents: [...selectedStage.agents, agentName] });
        }
      } else {
        // No stage selected — create a new single-agent node
        const existing = new Set(stages.map((s) => s.name));
        let name = agentName;
        if (existing.has(name)) {
          let n = 1;
          while (existing.has(`${name}_${n}`)) n++;
          name = `${name}_${n}`;
        }
        const newStage: DesignStage = { ...defaultDesignStage(name), agents: [agentName] };
        addStage(newStage);
        selectStage(name);
      }
    },
    [selectedStageName, selectedStage, stages, addStage, selectStage, updateStage],
  );

  // Add a blank stage node
  const handleAddBlankStage = useCallback(() => {
    const existing = new Set(stages.map((s) => s.name));
    let name = 'new_stage';
    let n = 1;
    while (existing.has(name)) { name = `new_stage_${n}`; n++; }
    addStage({ ...defaultDesignStage(name) });
    selectStage(name);
  }, [stages, addStage, selectStage]);

  const tools = registry?.tools ?? [];
  const strategies = registry?.strategies ?? [];

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Outline */}
      <Section title="Outline" badge={`${stages.length}`}>
        {stages.length === 0 ? (
          <p className="text-[10px] text-temper-text-dim px-1">No stages yet</p>
        ) : (
          <div className="flex flex-col gap-px">
            {stages.map((stage, i) => (
              <OutlineItem
                key={stage.name}
                stage={stage}
                colorIndex={i}
                isSelected={selectedStageName === stage.name}
              />
            ))}
          </div>
        )}
        <button
          onClick={handleAddBlankStage}
          className="mt-1.5 w-full px-2 py-1 rounded border border-dashed border-temper-border text-[10px] text-temper-text-dim hover:border-temper-accent/50 hover:text-temper-accent transition-colors"
        >
          + Add Stage
        </button>
      </Section>

      {/* Agents */}
      <Section
        title="Agents"
        badge={selectedStageName ? `\u2192 ${selectedStageName}` : undefined}
      >
        <input
          type="text"
          value={agentSearch}
          onChange={(e) => setAgentSearch(e.target.value)}
          placeholder="Search agents..."
          className="w-full px-2 py-1 mb-1.5 text-[11px] bg-temper-surface border border-temper-border rounded text-temper-text placeholder:text-temper-text-dim"
        />
        {selectedStageName && (
          <p className="text-[9px] text-temper-accent px-1 mb-1">
            Click to add to &ldquo;{selectedStageName}&rdquo;
          </p>
        )}
        <div className="flex flex-col gap-px max-h-[300px] overflow-y-auto">
          {filteredAgents.map((name) => (
            <AgentTile
              key={name}
              name={name}
              isAssigned={assignedAgents.has(name)}
              onAdd={() => handleAddAgent(name)}
            />
          ))}
          {filteredAgents.length === 0 && (
            <p className="text-[10px] text-temper-text-dim px-1">
              {allAgents.length === 0 ? 'No agent configs found' : 'No matches'}
            </p>
          )}
        </div>
      </Section>

      {/* Tools & Strategies — quick reference */}
      <Section title="Registry" defaultOpen={false}>
        <div className="space-y-2">
          <div>
            <div className="text-[9px] text-temper-text-dim uppercase tracking-wider mb-1">Strategies</div>
            <div className="flex flex-wrap gap-1">
              {strategies.map((s) => (
                <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/30 text-blue-400">{s}</span>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[9px] text-temper-text-dim uppercase tracking-wider mb-1">Tools</div>
            <div className="flex flex-wrap gap-1">
              {tools.map((t) => (
                <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/30 text-amber-400">{t}</span>
              ))}
            </div>
          </div>
          {registry?.providers && (
            <div>
              <div className="text-[9px] text-temper-text-dim uppercase tracking-wider mb-1">Providers</div>
              <div className="flex flex-wrap gap-1">
                {registry.providers.map((p) => (
                  <span key={p} className="text-[10px] px-1.5 py-0.5 rounded bg-temper-surface text-temper-text-dim">{p}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}
