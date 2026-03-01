/**
 * Left panel for the Studio editor.
 * Top: "Workflow Stages" — clickable navigator for stages in the current workflow.
 * Bottom: "Add Stages" — collapsible, searchable palette of stage configs to drag onto canvas.
 */
import { useDesignStore, type DesignStage } from '@/store/designStore';
import { STAGE_PALETTE } from '@/lib/constants';
import { ResourceBrowser } from './ResourceBrowser';

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

      {/* Spacer pushes resource browser to bottom */}
      <div className="flex-1" />

      {/* Tabbed resource browser */}
      <ResourceBrowser />
    </div>
  );
}
