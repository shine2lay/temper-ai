/**
 * Left panel for the Studio editor.
 * Top: "Workflow Stages" — clickable navigator for stages in the current workflow.
 * Bottom: "Add Stages" — collapsible, searchable palette of stage configs to drag onto canvas.
 */
import { useState, useRef, useCallback, type DragEvent, type KeyboardEvent } from 'react';
import { useDesignStore, defaultDesignStage, type DesignStage } from '@/store/designStore';
import { useStudioConfigs } from '@/hooks/useStudioAPI';
import { STAGE_PALETTE } from '@/lib/constants';

/* ---------- Workflow stage list (top section) ---------- */

const MAX_SIDEBAR_AGENT_PILLS = 2;

function WorkflowStageItem({
  stage,
  colorIndex,
  isSelected,
}: {
  stage: DesignStage;
  colorIndex: number;
  isSelected: boolean;
}) {
  const selectStage = useDesignStore((s) => s.selectStage);
  const resolvedInfo = useDesignStore((s) => s.resolvedStageInfo[stage.name]);
  const color = STAGE_PALETTE[colorIndex % STAGE_PALETTE.length];

  // Use resolved info from config, fall back to inline stage data
  const agents = resolvedInfo ? resolvedInfo.agents : stage.agents;
  const agentMode = resolvedInfo ? resolvedInfo.agentMode : stage.agent_mode;
  const hasCondition = stage.condition != null;
  const showModeBadge = agentMode !== 'sequential';

  const visibleAgents = agents.slice(0, MAX_SIDEBAR_AGENT_PILLS);
  const overflowCount = agents.length - MAX_SIDEBAR_AGENT_PILLS;

  return (
    <button
      onClick={() => selectStage(stage.name)}
      className={`w-full text-left px-2.5 py-1.5 rounded-md flex items-start gap-2 transition-colors ${
        isSelected
          ? 'bg-temper-accent/15 border border-temper-accent/40'
          : 'hover:bg-temper-surface border border-transparent'
      }`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0 mt-1"
        style={{ backgroundColor: color }}
      />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-temper-text truncate flex items-center gap-1">
          {stage.name}
          {hasCondition && (
            <span
              className="w-1.5 h-1.5 rounded-full bg-yellow-400 shrink-0 inline-block"
              title={`Condition: ${stage.condition}`}
            />
          )}
        </div>
        {agents.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap mt-0.5">
            {visibleAgents.map((name) => (
              <span
                key={name}
                className="text-[9px] px-1 py-px rounded bg-temper-surface text-temper-text-dim truncate max-w-[80px]"
              >
                {name}
              </span>
            ))}
            {overflowCount > 0 && (
              <span className="text-[9px] text-temper-text-dim">
                +{overflowCount}
              </span>
            )}
            {showModeBadge && (
              <span className="text-[9px] px-1 py-px rounded bg-amber-900/30 text-amber-400">
                {agentMode}
              </span>
            )}
          </div>
        )}
      </div>
      {stage.depends_on.length > 0 && (
        <span className="text-[10px] text-temper-text-dim shrink-0 mt-0.5">
          {stage.depends_on.length} dep{stage.depends_on.length !== 1 ? 's' : ''}
        </span>
      )}
    </button>
  );
}

function WorkflowStageList() {
  const stages = useDesignStore((s) => s.stages);
  const selectedStageName = useDesignStore((s) => s.selectedStageName);

  if (stages.length === 0) {
    return (
      <p className="text-[10px] text-temper-text-dim px-2 py-1">
        No stages yet
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {stages.map((stage, i) => (
        <WorkflowStageItem
          key={stage.name}
          stage={stage}
          colorIndex={i}
          isSelected={selectedStageName === stage.name}
        />
      ))}
    </div>
  );
}

/* ---------- Draggable palette tile ---------- */

interface PaletteTileProps {
  name: string;
  description: string;
  onAdd: () => void;
}

function PaletteTile({ name, description, onAdd }: PaletteTileProps) {
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
      aria-label={`Add stage: ${name}${description ? ` — ${description}` : ''}`}
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

interface BlankStageTileProps {
  onAdd: () => void;
}

function BlankStageTile({ onAdd }: BlankStageTileProps) {
  const onDragStart = (e: DragEvent) => {
    e.dataTransfer.setData('application/studio-stage-name', 'new_stage');
    e.dataTransfer.setData('application/studio-stage-ref', '');
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
      aria-label="Add blank stage"
      onDragStart={onDragStart}
      onClick={onAdd}
      onKeyDown={onKeyDown}
      className="px-2.5 py-1.5 rounded-md border border-dashed border-temper-border cursor-grab hover:border-temper-accent/50 focus:outline-none focus:ring-2 focus:ring-temper-accent/50 transition-colors"
    >
      <div className="text-[11px] font-medium text-temper-text-muted">+ Blank Stage</div>
      <div className="text-[10px] text-temper-text-dim mt-0.5">
        Empty stage with no config
      </div>
    </div>
  );
}

/* ---------- Add Stages palette (bottom section) ---------- */

function AddStagesPalette() {
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState(false);
  const { data, isLoading, error } = useStudioConfigs('stages');
  const listRef = useRef<HTMLDivElement>(null);

  const addStage = useDesignStore((s) => s.addStage);
  const selectStage = useDesignStore((s) => s.selectStage);
  const existingStages = useDesignStore((s) => s.stages);

  const configs = data?.configs
    ?.slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .filter((cfg) =>
      !search || cfg.name.toLowerCase().includes(search.toLowerCase()),
    );

  function generateName(base: string): string {
    const existing = new Set(existingStages.map((s) => s.name));
    if (!existing.has(base)) return base;
    let n = 1;
    while (existing.has(`${base}_${n}`)) n++;
    return `${base}_${n}`;
  }

  const handleAdd = useCallback(
    (stageName: string, stageRef: string) => {
      const name = generateName(stageName);
      const newStage: DesignStage = {
        ...defaultDesignStage(name),
        stage_ref: stageRef || null,
      };
      addStage(newStage);
      selectStage(name);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [addStage, selectStage, existingStages],
  );

  /** Arrow key navigation within the palette list. */
  const onListKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const items = listRef.current?.querySelectorAll<HTMLElement>('[role="button"]');
    if (!items || items.length === 0) return;
    const focused = document.activeElement as HTMLElement;
    const arr = Array.from(items);
    const idx = arr.indexOf(focused);
    if (e.key === 'ArrowDown') {
      const next = idx < arr.length - 1 ? idx + 1 : 0;
      arr[next]?.focus();
    } else {
      const prev = idx > 0 ? idx - 1 : arr.length - 1;
      arr[prev]?.focus();
    }
  }, []);

  return (
    <div className="flex flex-col">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center gap-1.5 px-3 py-2 border-t border-temper-border text-left hover:bg-temper-surface/50 transition-colors"
      >
        <span className="text-[10px] text-temper-text-dim">
          {collapsed ? '\u25B6' : '\u25BC'}
        </span>
        <span className="text-xs font-semibold text-temper-text">Add Stages</span>
        <span className="text-[10px] text-temper-text-dim ml-auto">drag or Enter</span>
      </button>

      {!collapsed && (
        <div className="flex flex-col gap-1.5 px-2 pb-2">
          {/* Search */}
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search stages..."
            className="px-2 py-1 text-[11px] bg-temper-surface border border-temper-border rounded text-temper-text placeholder:text-temper-text-dim"
          />

          {isLoading && (
            <p className="text-[10px] text-temper-text-muted px-1">Loading...</p>
          )}
          {error && (
            <p className="text-[10px] text-red-400 px-1">Failed to load</p>
          )}

          {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
          <div
            ref={listRef}
            className="flex flex-col gap-1 max-h-[280px] overflow-y-auto"
            onKeyDown={onListKeyDown}
          >
            {configs?.map((cfg) => (
              <PaletteTile
                key={cfg.name}
                name={cfg.name}
                description={cfg.description}
                onAdd={() => handleAdd(cfg.name, `configs/stages/${cfg.name}.yaml`)}
              />
            ))}

            {configs && configs.length === 0 && (
              <p className="text-[10px] text-temper-text-dim px-1">No matches</p>
            )}
          </div>

          <BlankStageTile onAdd={() => handleAdd('new_stage', '')} />
        </div>
      )}
    </div>
  );
}

/* ---------- Main export ---------- */

export function StagePalette() {
  const stages = useDesignStore((s) => s.stages);
  const selectStage = useDesignStore((s) => s.selectStage);

  return (
    <div className="flex flex-col h-full">
      {/* Workflow stages navigator */}
      <div className="flex flex-col shrink-0">
        <div className="flex items-center justify-between px-3 py-2 border-b border-temper-border">
          <h3 className="text-xs font-semibold text-temper-text">
            Stages
            {stages.length > 0 && (
              <span className="ml-1.5 text-temper-text-dim font-normal">
                ({stages.length})
              </span>
            )}
          </h3>
          {stages.length > 0 && (
            <button
              onClick={() => selectStage(null)}
              className="text-[10px] text-temper-text-dim hover:text-temper-accent transition-colors"
            >
              Deselect
            </button>
          )}
        </div>

        <div className="px-2 py-1.5 max-h-[320px] overflow-y-auto">
          <WorkflowStageList />
        </div>
      </div>

      {/* Spacer pushes palette to bottom */}
      <div className="flex-1" />

      {/* Draggable palette */}
      <AddStagesPalette />
    </div>
  );
}
