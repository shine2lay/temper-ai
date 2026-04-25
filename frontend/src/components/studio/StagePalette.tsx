/**
 * Left panel for the Studio editor — a building-blocks library.
 *
 * Sections:
 * 1. Outline  — compact stage list (click to select, shows flow order)
 * 2. Agents   — drag or click to add to selected stage
 * 3. Tools    — reference list of registered tools
 */
import { useState, useCallback, type DragEvent, type KeyboardEvent as KBEvent } from 'react';
import { useReactFlow } from '@xyflow/react';
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
  const { fitView } = useReactFlow();
  const color = STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];
  const isSingleAgent = stage.agents.length === 1 && !stage.stage_ref;

  const handleClick = () => {
    selectStage(stage.name);
    // Pan canvas to center the selected node
    setTimeout(() => fitView({ nodes: [{ id: stage.name }], duration: 300, padding: 0.5 }), 50);
  };

  return (
    <button
      onClick={handleClick}
      className={`w-full text-left px-2 py-1 rounded flex items-center gap-2 transition-colors text-[11px] ${
        isSelected
          ? 'bg-temper-accent/15 text-temper-text'
          : 'text-temper-text-muted hover:bg-temper-surface hover:text-temper-text'
      }`}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="truncate flex-1">{isSingleAgent ? stage.agents[0] : stage.name}</span>
      {!isSingleAgent && (
        <span className={`text-[9px] px-1 py-px rounded shrink-0 ${
          stage.agents.length === 0 ? 'bg-temper-surface text-temper-text-dim' : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
        }`}>
          {stage.agents.length === 0 ? 'empty' : `${stage.agents.length} agents`}
        </span>
      )}
    </button>
  );
}

/* ---------- Agent tile ---------- */

function AgentTile({
  name,
  isAssigned,
  isUsed,
  usedInStages,
  onAdd,
}: {
  name: string;
  isAssigned: boolean;
  isUsed?: boolean;
  usedInStages?: string;
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
      className={`w-full text-left px-2 py-1.5 rounded text-[11px] transition-colors cursor-grab active:cursor-grabbing flex items-center gap-1 ${
        isAssigned
          ? 'text-temper-text-dim opacity-50'
          : 'text-temper-text hover:bg-temper-accent/10'
      }`}
    >
      {isUsed && !isAssigned && (
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" title={usedInStages ?? 'Used in workflow'} />
      )}
      <span className="truncate">{name}</span>
      {isAssigned && <span className="text-[9px] text-temper-text-dim ml-auto shrink-0">(in stage)</span>}
    </div>
  );
}

/* ---------- Main export ---------- */

export function StagePalette() {
  const stages = useDesignStore((s) => s.stages);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);
  const selectStage = useDesignStore((s) => s.selectStage);
  const selectAgent = useDesignStore((s) => s.selectAgent);
  const addStage = useDesignStore((s) => s.addStage);
  const updateStage = useDesignStore((s) => s.updateStage);
  const setAutoFocusStageName = useDesignStore((s) => s.setAutoFocusStageName);
  const { fitView } = useReactFlow();

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

  // Agents used anywhere in the workflow
  const usedInWorkflow = new Set(stages.flatMap((s) => s.agents));

  // Add agent to selected stage, or create a new single-agent node
  const handleAddAgent = useCallback(
    (agentName: string) => {
      if (selectedStageName && selectedStage) {
        if (!selectedStage.agents.includes(agentName)) {
          updateStage(selectedStageName, { agents: [...selectedStage.agents, agentName] });
        }
      } else {
        // No stage selected — add agent to canvas as a standalone node
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
        // Open the agent properties panel directly
        selectAgent(agentName);
      }
    },
    [selectedStageName, selectedStage, stages, addStage, selectStage, updateStage],
  );

  // Add a blank stage node — position at viewport center with auto-focus on name
  const handleAddBlankStage = useCallback(() => {
    const existing = new Set(stages.map((s) => s.name));
    let name = 'new_stage';
    let n = 1;
    while (existing.has(name)) { name = `new_stage_${n}`; n++; }
    addStage({ ...defaultDesignStage(name) });
    selectStage(name);
    setAutoFocusStageName(name);
    setTimeout(() => fitView({ nodes: [{ id: name }], duration: 300, padding: 0.5 }), 100);
  }, [stages, addStage, selectStage, setAutoFocusStageName, fitView]);

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
          {filteredAgents.map((agentName) => {
            const stagesUsing = stages.filter(s => s.agents.includes(agentName)).map(s => s.name);
            return (
            <AgentTile
              key={agentName}
              name={agentName}
              isAssigned={assignedAgents.has(agentName)}
              isUsed={usedInWorkflow.has(agentName)}
              usedInStages={stagesUsing.length > 0 ? `Used in: ${stagesUsing.join(', ')}` : undefined}
              onAdd={() => handleAddAgent(agentName)}
            />
          );
          })}
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
                <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">{s}</span>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[9px] text-temper-text-dim uppercase tracking-wider mb-1">Tools</div>
            <div className="flex flex-wrap gap-1">
              {tools.map((t) => (
                <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">{t}</span>
              ))}
            </div>
          </div>
          {registry?.mcp_servers && registry.mcp_servers.length > 0 && (
            <div>
              <div className="text-[9px] text-temper-text-dim uppercase tracking-wider mb-1">MCP Servers</div>
              <div className="flex flex-wrap gap-1">
                {registry.mcp_servers.map((s) => (
                  <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-900/30 text-cyan-400">{s}</span>
                ))}
              </div>
            </div>
          )}
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
