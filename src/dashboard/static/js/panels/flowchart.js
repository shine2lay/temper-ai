/**
 * Flowchart Panel — Cytoscape.js node graph (LangFlow-style).
 * Shows stages as compound nodes with agent children, data flow edges,
 * and collaboration edges. HTML overlays via cytoscape-node-html-label
 * for rich stage headers and agent cards. Live updates via DataStore events.
 *
 * Collapsed DAG: groups repeat executions of the same stage name into
 * a single node with iteration badges and aggregated metrics.
 */

import {
    stageHeaderTpl,
    agentCardTpl,
    formatDataFlowLabel,
    formatCollabLabel,
} from './flowchart-templates.js';

const STATUS_COLORS = {
    completed: '#66bb6a',
    running:   '#4fc3f7',
    failed:    '#ef5350',
    pending:   '#6a7080',
};

// Distinct colors for each unique stage (edges + name text)
const STAGE_PALETTE = [
    '#42a5f5', // blue
    '#ab47bc', // purple
    '#26a69a', // teal
    '#ffa726', // orange
    '#ec407a', // pink
    '#7e57c2', // deep purple
    '#26c6da', // cyan
    '#d4e157', // lime
    '#8d6e63', // brown
    '#78909c', // blue-grey
];

const CYTOSCAPE_STYLE = [
    // Stage (compound/parent) nodes — label removed, HTML overlay replaces it
    {
        selector: 'node[type="stage"]',
        style: {
            'background-color': '#1e2a4a',
            'border-color': '#2a3a5c',
            'border-width': 2,
            'shape': 'roundrectangle',
            'text-valign': 'top',
            'text-halign': 'center',
            'padding': '20px',
            'min-width': 200,
            'min-height': 100,
        },
    },
    // Completed stage tinted background
    {
        selector: 'node[type="stage"][status="completed"]',
        style: { 'background-color': '#162318' },
    },
    // Failed stage tinted background
    {
        selector: 'node[type="stage"][status="failed"]',
        style: { 'background-color': '#231616' },
    },
    // Stage header child node — invisible canvas node for HTML overlay
    {
        selector: 'node[type="stage-header"]',
        style: {
            'background-opacity': 0,
            'border-width': 0,
            'width': 180,
            'height': 50,
            'shape': 'roundrectangle',
        },
    },
    // Agent (child) nodes — label removed, HTML overlay replaces it
    {
        selector: 'node[type="agent"]',
        style: {
            'background-color': '#0f1729',
            'border-color': '#2a3a5c',
            'border-width': 2,
            'shape': 'roundrectangle',
            'width': 180,
            'height': 90,
        },
    },
    // Completed agent tinted background
    {
        selector: 'node[type="agent"][status="completed"]',
        style: { 'background-color': '#121f14' },
    },
    // Failed agent tinted background
    {
        selector: 'node[type="agent"][status="failed"]',
        style: { 'background-color': '#1f1212' },
    },
    // Status-based border colors
    {
        selector: 'node[status="completed"]',
        style: { 'border-color': STATUS_COLORS.completed },
    },
    {
        selector: 'node[status="running"]',
        style: { 'border-color': STATUS_COLORS.running, 'border-width': 3 },
    },
    {
        selector: 'node[status="failed"]',
        style: { 'border-color': STATUS_COLORS.failed },
    },
    {
        selector: 'node[status="pending"]',
        style: { 'border-color': STATUS_COLORS.pending },
    },
    // Data flow edges (stage-to-stage)
    {
        selector: 'edge[type="data_flow"]',
        style: {
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'line-color': '#4fc3f7',
            'target-arrow-color': '#4fc3f7',
            'width': 2,
            'label': 'data(label)',
            'font-size': 9,
            'color': '#6a7080',
            'text-rotation': 'autorotate',
            'text-margin-y': -10,
        },
    },
    // Loop-back edges (dashed, forced arc so they never look straight)
    {
        selector: 'edge[type="loop_back"]',
        style: {
            'curve-style': 'unbundled-bezier',
            'control-point-distances': [80],
            'control-point-weights': [0.5],
            'line-style': 'dashed',
            'line-color': '#ffa726',
            'target-arrow-shape': 'triangle',
            'target-arrow-color': '#ffa726',
            'width': 2,
            'label': 'data(label)',
            'font-size': 9,
            'color': '#ffa726',
            'text-rotation': 'autorotate',
            'text-margin-y': -10,
        },
    },
    // Collaboration edges (agent-to-agent within stage)
    {
        selector: 'edge[type="collaboration"]',
        style: {
            'curve-style': 'bezier',
            'line-style': 'dashed',
            'line-color': '#6a7080',
            'width': 1,
            'label': 'data(label)',
            'font-size': 9,
            'color': '#6a7080',
        },
    },
    // Selection highlight
    {
        selector: ':selected',
        style: { 'border-color': '#4fc3f7', 'border-width': 3 },
    },
    // Per-stage edge coloring (overrides default edge colors when set)
    {
        selector: 'edge[edgeColor]',
        style: {
            'line-color': 'data(edgeColor)',
            'target-arrow-color': 'data(edgeColor)',
        },
    },
];

// Spacing constants for manual LR layout (stages left-to-right, agents top-to-bottom)
const LAYOUT = {
    AGENT_WIDTH: 180,
    AGENT_HEIGHT: 90,
    AGENT_GAP_Y: 20,            // vertical gap between agents
    STAGE_GAP_X: 120,           // horizontal gap between stages
    STAGE_GAP_Y: 40,            // vertical gap between parallel stages
    STAGE_PAD_X: 30,            // horizontal padding inside stage
    STAGE_PAD_Y: 60,            // vertical padding inside stage (room for header)
    STAGE_HEADER_HEIGHT: 50,    // height of the stage header node
};

export class FlowchartPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._cy = null;
        this._lastTopology = '';
        this._dirty = false;
        this._rafId = null;
        this._changeHandler = (e) => {
            const ct = e.detail?.changeType;
            // Update on snapshot and event changes (stage/agent lifecycle)
            // Skip only stream content and selection changes
            if (ct === 'stream' || ct === 'selection') return;
            this._scheduleRender();
        };
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    _scheduleRender() {
        if (this._rafId) return;
        this._rafId = requestAnimationFrame(() => {
            this._rafId = null;
            this.render();
        });
    }

    _initCytoscape() {
        if (this._cy) return;
        if (typeof cytoscape === 'undefined') return;

        // Defer if container is not visible (e.g. hidden tab)
        if (this.container.offsetWidth === 0 || this.container.offsetHeight === 0) {
            return;
        }

        this._cy = cytoscape({
            container: this.container,
            style: CYTOSCAPE_STYLE,
            layout: { name: 'preset' },
            minZoom: 0.3,
            maxZoom: 3,
            boxSelectionEnabled: false,
            wheelSensitivity: 0.3,
        });

        // Click agent node → select agent in DataStore
        this._cy.on('tap', 'node[type="agent"]', (e) => {
            this.dataStore.select('agent', e.target.id());
        });

        // Click stage node → attach iteration context then select
        this._cy.on('tap', 'node[type="stage"]', (e) => {
            const stageId = e.target.id();
            const stageData = this.dataStore.stages.get(stageId);
            if (stageData) {
                stageData._allExecutionIds = e.target.data('_allExecutionIds') || [];
                stageData._iterationTriggers = e.target.data('_iterationTriggers') || {};
            }
            this.dataStore.select('stage', stageId);
        });

        // Click stage-header node → attach iteration context then select parent
        this._cy.on('tap', 'node[type="stage-header"]', (e) => {
            const parentId = e.target.data('parent');
            const stageData = this.dataStore.stages.get(parentId);
            if (stageData) {
                stageData._allExecutionIds = e.target.data('_allExecutionIds') || [];
                stageData._iterationTriggers = e.target.data('_iterationTriggers') || {};
            }
            this.dataStore.select('stage', parentId);
        });

        // Register HTML label overlays (graceful: guard if extension not loaded)
        if (typeof this._cy.nodeHtmlLabel === 'function') {
            this._cy.nodeHtmlLabel([
                {
                    query: 'node[type="stage-header"]',
                    halign: 'center',
                    valign: 'center',
                    halignBox: 'center',
                    valignBox: 'center',
                    tpl: (data) => stageHeaderTpl(data),
                    enablePointerEvents: true,
                },
                {
                    query: 'node[type="agent"]',
                    halign: 'center',
                    valign: 'center',
                    halignBox: 'center',
                    valignBox: 'center',
                    tpl: (data) => agentCardTpl(data),
                    enablePointerEvents: true,
                },
            ]);
        }
    }

    render() {
        const wf = this.dataStore.workflow;
        if (!wf) {
            this._renderEmptyState();
            return;
        }

        if (typeof cytoscape === 'undefined') {
            this._renderLibMissing();
            return;
        }

        // Defer rendering when container is hidden (e.g. inactive tab)
        if (this.container.offsetWidth === 0 || this.container.offsetHeight === 0) {
            this._dirty = true;
            return;
        }
        this._dirty = false;

        this._initCytoscape();
        if (!this._cy) return;

        const elements = this._buildElements(wf);

        if (elements.length === 0) {
            this._renderEmptyState();
            return;
        }

        // Clear empty state overlay if present
        const emptyEl = this.container.querySelector('.empty-state');
        if (emptyEl) emptyEl.remove();

        // Batch update elements
        this._cy.batch(() => {
            // Remove elements no longer present
            const newIds = new Set(elements.map(el => el.data.id));
            this._cy.elements().forEach(ele => {
                if (!newIds.has(ele.id())) ele.remove();
            });

            for (const el of elements) {
                const existing = this._cy.getElementById(el.data.id);
                if (existing.length > 0) {
                    // Update data on existing element
                    existing.data(el.data);
                } else {
                    // Add new element
                    this._cy.add(el);
                }
            }
        });

        // Force style recalculation for data-bound selectors (e.g. node[status])
        this._cy.style().update();

        // Only re-layout when topology (set of element IDs) changes
        const currentTopology = this._cy.elements().map(e => e.id()).sort().join(',');
        if (currentTopology !== this._lastTopology) {
            this._lastTopology = currentTopology;
            this._applyLayout();
        }
    }

    _applyLayout() {
        if (!this._cy || this._cy.elements().length === 0) return;

        // Position map: node id → { x, y } for agent and stage-header nodes
        const positions = {};
        this._cy.nodes('[type="agent"], [type="stage-header"]').forEach(n => {
            positions[n.id()] = { x: n.data('_px'), y: n.data('_py') };
        });

        this._cy.layout({
            name: 'preset',
            positions: (node) => {
                const t = node.data('type');
                if (t === 'agent' || t === 'stage-header') {
                    return positions[node.id()] || { x: 0, y: 0 };
                }
                // Compound parents auto-wrap children
                return undefined;
            },
            fit: true,
            padding: 30,
            animate: true,
            animationDuration: 300,
        }).run();
    }

    // --- Collapsed DAG: group executions, aggregate metrics, build elements ---

    _buildElements(wf) {
        const elements = [];
        const stages = wf.stages || [];
        const dagInfo = this._extractDagInfo(wf);
        const stageGroups = this._groupExecutionsByName(stages);
        const positions = this._computeStagePositions(stageGroups, dagInfo);

        // Assign a distinct color to each unique stage name
        const stageColors = new Map();
        let colorIdx = 0;
        for (const [name] of stageGroups) {
            stageColors.set(name, STAGE_PALETTE[colorIdx % STAGE_PALETTE.length]);
            colorIdx++;
        }

        const iterationTriggers = this._computeIterationTriggers(stageGroups, dagInfo);

        for (const [name, executions] of stageGroups) {
            const latest = executions[executions.length - 1];
            if (!latest.id) continue;

            const pos = positions.get(name) || { x: 0, y: 0 };
            const allExecutionIds = executions.map(e => e.id);
            const iterationCount = executions.length;
            const aggregated = this._aggregateIterationMetrics(executions);

            // Build trigger map for this stage's iterations
            const triggerMap = {};
            for (const eid of allExecutionIds) {
                const t = iterationTriggers.get(eid);
                if (t) triggerMap[eid] = t;
            }

            this._addStageElements(elements, latest, pos, {
                iterationCount,
                _allExecutionIds: allExecutionIds,
                _iterationTriggers: triggerMap,
                stageColor: stageColors.get(name),
                ...aggregated,
            });

            // Collab edges only for latest execution's agents
            this._addCollabEdges(elements, latest);
        }

        this._addCollapsedDagEdges(elements, stageGroups, dagInfo, stageColors, iterationTriggers);

        return elements;
    }

    /** Group execution records by stage name, sorted by start_time within each group. */
    _groupExecutionsByName(stages) {
        const groups = new Map();
        for (const stage of stages) {
            if (!stage.id) continue;
            const stageData = this.dataStore.stages.get(stage.id) || stage;
            const name = stageData.stage_name || stageData.name || stage.id;
            if (!groups.has(name)) groups.set(name, []);
            groups.get(name).push(stage);
        }
        // Sort each group by start_time (preserves execution order)
        for (const [, execs] of groups) {
            execs.sort((a, b) => {
                const ad = this.dataStore.stages.get(a.id) || a;
                const bd = this.dataStore.stages.get(b.id) || b;
                const at = ad.started_at || ad.start_time || '';
                const bt = bd.started_at || bd.start_time || '';
                return at < bt ? -1 : at > bt ? 1 : 0;
            });
        }
        return groups;
    }

    /** Aggregate metrics across all iterations of a stage. */
    _aggregateIterationMetrics(executions) {
        let totalTokens = 0;
        let totalCost = 0;
        let durationSeconds = 0;
        let numSucceeded = 0;
        let numFailed = 0;
        let collabRounds = 0;

        for (const exec of executions) {
            const agents = exec.agents || [];
            totalTokens += this._sumAgentField(agents, 'total_tokens');
            totalCost += this._sumAgentField(agents, 'estimated_cost_usd');

            const sd = this.dataStore.stages.get(exec.id) || exec;
            durationSeconds += sd.duration_seconds || 0;
            numSucceeded += sd.num_agents_succeeded || 0;
            numFailed += sd.num_agents_failed || 0;
            collabRounds += (sd.collaboration_events || []).length;
        }

        return { totalTokens, totalCost, durationSeconds, numSucceeded, numFailed, collabRounds };
    }

    /**
     * Compute {stageName → {x, y}} positions from DAG topology.
     * Accepts stageGroups Map (name → executions[]) for collapsed view.
     * X = column from depth (longest path from root), Y = row within depth group.
     * Falls back to sequential left-to-right when no depends_on is present.
     */
    _computeStagePositions(stageGroups, dagInfo) {
        const positions = new Map();
        const colWidth = LAYOUT.AGENT_WIDTH + 2 * LAYOUT.STAGE_PAD_X + LAYOUT.STAGE_GAP_X;

        if (!dagInfo.hasDeps) {
            let i = 0;
            for (const [name] of stageGroups) {
                positions.set(name, { x: i * colWidth, y: 0 });
                i++;
            }
            return positions;
        }

        const depths = this._computeDepthsFromDepMap(dagInfo.depMap);

        // Group stage names by depth for vertical distribution
        const depthGroups = new Map();
        for (const [name] of stageGroups) {
            const depth = depths.get(name) ?? 0;
            if (!depthGroups.has(depth)) depthGroups.set(depth, []);
            depthGroups.get(depth).push(name);
        }

        // Assign X from depth, Y centered within each depth group
        for (const [depth, names] of depthGroups) {
            const x = depth * colWidth;
            const heights = names.map(name => {
                const execs = stageGroups.get(name);
                const latest = execs[execs.length - 1];
                return this._estimateStageHeight(latest);
            });
            const totalH = heights.reduce((a, b) => a + b, 0)
                + (names.length - 1) * LAYOUT.STAGE_GAP_Y;
            let yCursor = -totalH / 2;
            for (let i = 0; i < names.length; i++) {
                positions.set(names[i], { x, y: yCursor });
                yCursor += heights[i] + LAYOUT.STAGE_GAP_Y;
            }
        }

        return positions;
    }

    /**
     * Compute longest-path depths from a dependency map (name → [dep names]).
     * Roots (no deps) get depth 0; each other stage = max(pred depths) + 1.
     */
    _computeDepthsFromDepMap(depMap) {
        const depths = new Map();
        for (const [name, deps] of depMap) {
            if (deps.length === 0) depths.set(name, 0);
        }
        let changed = true;
        while (changed) {
            changed = false;
            for (const [name, deps] of depMap) {
                if (deps.length === 0) continue;
                if (!deps.every(d => depths.has(d))) continue;
                const newDepth = Math.max(...deps.map(d => depths.get(d))) + 1;
                if (depths.get(name) !== newDepth) {
                    depths.set(name, newDepth);
                    changed = true;
                }
            }
        }
        return depths;
    }

    /** Estimate total height of a stage for vertical spacing. */
    _estimateStageHeight(stage) {
        const agentCount = Math.max((stage.agents || []).length, 1);
        return LAYOUT.STAGE_PAD_Y
            + agentCount * (LAYOUT.AGENT_HEIGHT + LAYOUT.AGENT_GAP_Y);
    }

    /**
     * Add stage compound node, header child, and agent child nodes at pos.
     * pos.x = center X, pos.y = top Y of the stage content area.
     * overrides: optional object merged into header node data (for collapsed metrics).
     */
    _addStageElements(elements, stage, pos, overrides = {}) {
        const stageData = this.dataStore.stages.get(stage.id) || stage;
        const status = stageData.status || 'pending';
        const name = stageData.stage_name || stageData.name || stage.id;

        // Extract stage config for strategy/execMode
        const stageConfig = stageData.stage_config_snapshot?.stage || {};
        const collaboration = stageConfig.collaboration || {};
        const execution = stageConfig.execution || {};
        const strategy = collaboration.strategy || '';
        const execMode = execution.agent_mode || '';

        // Stage compound (parent) node
        elements.push({
            group: 'nodes',
            data: {
                id: stage.id,
                type: 'stage',
                status,
                label: name,
                _allExecutionIds: overrides._allExecutionIds || [stage.id],
                _iterationTriggers: overrides._iterationTriggers || {},
            },
        });

        // Stage header child node (HTML overlay anchor)
        // Fields match stageHeaderTpl expectations: name, status, strategy,
        // execMode, agentCount, totalTokens, totalCost, durationSeconds, etc.
        const agents = stage.agents || [];
        const headerData = {
            id: `${stage.id}-header`,
            parent: stage.id,
            type: 'stage-header',
            name,
            label: name,
            status,
            strategy,
            execMode,
            agentCount: agents.length || stageData.num_agents_executed || 0,
            totalTokens: this._sumAgentField(agents, 'total_tokens'),
            totalCost: this._sumAgentField(agents, 'estimated_cost_usd'),
            durationSeconds: stageData.duration_seconds || null,
            numSucceeded: stageData.num_agents_succeeded ?? null,
            numFailed: stageData.num_agents_failed ?? 0,
            collabRounds: (stageData.collaboration_events || []).length,
            _px: pos.x,
            _py: pos.y + LAYOUT.STAGE_HEADER_HEIGHT / 2,
            ...overrides,
        };
        elements.push({ group: 'nodes', data: headerData });

        // Agent child nodes
        for (let j = 0; j < agents.length; j++) {
            const agent = agents[j];
            if (!agent.id) continue;
            const ad = this.dataStore.agents.get(agent.id) || agent;
            const agentName = ad.agent_name || ad.name || agent.id;
            const agentConfig = ad.agent_config_snapshot?.agent || {};
            elements.push({
                group: 'nodes',
                data: {
                    id: agent.id,
                    parent: stage.id,
                    type: 'agent',
                    name: agentName,
                    agentName,
                    label: agentName,
                    status: ad.status || 'pending',
                    role: ad.role || agentConfig.type || '',
                    model: agentConfig.model || '',
                    promptTokens: ad.prompt_tokens || 0,
                    completionTokens: ad.completion_tokens || 0,
                    durationSeconds: ad.duration_seconds || null,
                    numLlmCalls: ad.num_llm_calls || 0,
                    numToolCalls: ad.num_tool_calls || 0,
                    estimatedCost: ad.estimated_cost_usd || 0,
                    confidenceScore: ad.confidence_score ?? null,
                    _px: pos.x,
                    _py: pos.y + LAYOUT.STAGE_PAD_Y
                        + j * (LAYOUT.AGENT_HEIGHT + LAYOUT.AGENT_GAP_Y)
                        + LAYOUT.AGENT_HEIGHT / 2,
                },
            });
        }
    }

    /** Sum a numeric field across agents in a stage. */
    _sumAgentField(agents, field) {
        let total = 0;
        for (const agent of agents) {
            const ad = this.dataStore.agents.get(agent.id) || agent;
            total += ad[field] || 0;
        }
        return total;
    }

    /**
     * Infer who triggered each iteration of re-executed stages.
     * Returns Map<execId, triggerStageName|null>.
     * Iteration #1 → null (normal DAG flow), iteration #2+ → name of the
     * upstream stage (depends_on or loop-back source) whose execution
     * most recently started before this one.
     */
    _computeIterationTriggers(stageGroups, dagInfo) {
        const triggers = new Map();

        // Build predecessor map: stage name → all upstream names (depends_on + loop-back sources)
        const predecessors = new Map();
        for (const [name, deps] of dagInfo.depMap) {
            predecessors.set(name, [...deps]);
        }
        for (const [srcName, targetName] of dagInfo.loopsBackTo) {
            if (!predecessors.has(targetName)) predecessors.set(targetName, []);
            const preds = predecessors.get(targetName);
            if (!preds.includes(srcName)) preds.push(srcName);
        }

        // Global timeline: all executions sorted by start_time
        const timeline = [];
        for (const [name, execs] of stageGroups) {
            for (const exec of execs) {
                const sd = this.dataStore.stages.get(exec.id) || exec;
                timeline.push({
                    id: exec.id,
                    name,
                    startTime: sd.started_at || sd.start_time || '',
                });
            }
        }
        timeline.sort((a, b) => (a.startTime < b.startTime ? -1 : a.startTime > b.startTime ? 1 : 0));

        for (const [name, execs] of stageGroups) {
            if (execs.length <= 1) continue;
            const preds = predecessors.get(name) || [];
            if (preds.length === 0) continue;

            // First iteration: normal flow, no trigger label
            triggers.set(execs[0].id, null);

            // Subsequent iterations: find most recent predecessor before this exec
            for (let i = 1; i < execs.length; i++) {
                const sd = this.dataStore.stages.get(execs[i].id) || execs[i];
                const myStart = sd.started_at || sd.start_time || '';
                let triggerName = null;
                for (let t = timeline.length - 1; t >= 0; t--) {
                    if (timeline[t].startTime >= myStart) continue;
                    if (preds.includes(timeline[t].name)) {
                        triggerName = timeline[t].name;
                        break;
                    }
                }
                triggers.set(execs[i].id, triggerName || (preds.length === 1 ? preds[0] : 'rerun'));
            }
        }

        return triggers;
    }

    /** Add collaboration edges between consecutive agents within a stage. */
    _addCollabEdges(elements, stage) {
        const agents = stage.agents || [];
        const stageData = this.dataStore.stages.get(stage.id) || stage;
        const stageType = stageData.stage_type || 'collab';
        for (let j = 1; j < agents.length; j++) {
            if (!agents[j].id || !agents[j - 1].id) continue;
            elements.push({
                group: 'edges',
                data: {
                    id: `collab-${agents[j - 1].id}-${agents[j].id}`,
                    source: agents[j - 1].id,
                    target: agents[j].id,
                    type: 'collaboration',
                    label: formatCollabLabel(stageType, agents.length),
                },
            });
        }
    }

    /**
     * Extract DAG dependency info from workflow config snapshot.
     * Returns { depMap, loopsBackTo, hasDeps } where depMap maps
     * stage name → [dependency names] and loopsBackTo maps stage name → loop target.
     */
    _extractDagInfo(wf) {
        const result = { depMap: new Map(), loopsBackTo: new Map(), hasDeps: false };
        const configSnap = wf.workflow_config || wf.workflow_config_snapshot;
        if (!configSnap) return result;

        const wfConfig = configSnap.workflow || configSnap;
        const configStages = wfConfig.stages || [];

        for (const cs of configStages) {
            if (typeof cs === 'string') continue;
            const name = cs.name || '';
            if (!name) continue;

            const deps = cs.depends_on || [];
            result.depMap.set(name, deps);
            if (deps.length > 0) result.hasDeps = true;

            if (cs.loops_back_to) {
                result.loopsBackTo.set(name, cs.loops_back_to);
            }
        }

        return result;
    }

    /**
     * Add collapsed DAG edges: one edge per dependency + loop-back edges.
     * Replaces the old _addDagFlowEdges / _addSequentialFlowEdges pair.
     */
    _addCollapsedDagEdges(elements, stageGroups, dagInfo, stageColors, iterationTriggers) {
        // Build nameToNodeId map (name → latest execution ID)
        const nameToNodeId = new Map();
        for (const [name, execs] of stageGroups) {
            nameToNodeId.set(name, execs[execs.length - 1].id);
        }

        if (dagInfo.hasDeps) {
            // Normal forward dependency edges: one per dependency
            for (const [name, deps] of dagInfo.depMap) {
                const targetId = nameToNodeId.get(name);
                if (!targetId) continue;

                for (const depName of deps) {
                    const sourceId = nameToNodeId.get(depName);
                    if (!sourceId) continue;

                    const prevData = this.dataStore.stages.get(sourceId) || {};
                    const outputKeys = Object.keys(prevData.output_data || {});
                    const label = formatDataFlowLabel(outputKeys);

                    elements.push({
                        group: 'edges',
                        data: {
                            id: `flow-${sourceId}-${targetId}`,
                            source: sourceId,
                            target: targetId,
                            type: 'data_flow',
                            label,
                            edgeColor: stageColors.get(depName),
                        },
                    });
                }
            }

            // Loop-back edges (dashed, curved arc with per-source trigger count)
            for (const [srcName, targetName] of dagInfo.loopsBackTo) {
                const sourceId = nameToNodeId.get(srcName);
                const targetId = nameToNodeId.get(targetName);
                if (!sourceId || !targetId) continue;

                // Count how many times this specific source triggered the target
                const targetExecs = stageGroups.get(targetName) || [];
                let loopCount = 0;
                for (const exec of targetExecs) {
                    if (iterationTriggers.get(exec.id) === srcName) loopCount++;
                }
                if (loopCount <= 0) continue;

                elements.push({
                    group: 'edges',
                    data: {
                        id: `loop-${sourceId}-${targetId}`,
                        source: sourceId,
                        target: targetId,
                        type: 'loop_back',
                        label: loopCount > 1 ? `loop x${loopCount}` : 'loop',
                        edgeColor: stageColors.get(srcName),
                    },
                });
            }
        } else {
            // Sequential edges between unique stage names (no DAG info)
            const names = [...stageGroups.keys()];
            for (let i = 1; i < names.length; i++) {
                const prevId = nameToNodeId.get(names[i - 1]);
                const currId = nameToNodeId.get(names[i]);
                if (!prevId || !currId) continue;

                const prevData = this.dataStore.stages.get(prevId) || {};
                const outputKeys = Object.keys(prevData.output_data || {});
                const label = formatDataFlowLabel(outputKeys);

                elements.push({
                    group: 'edges',
                    data: {
                        id: `flow-${prevId}-${currId}`,
                        source: prevId,
                        target: currId,
                        type: 'data_flow',
                        label,
                        edgeColor: stageColors.get(names[i - 1]),
                    },
                });
            }
        }
    }

    _renderEmptyState() {
        // Keep cy instance alive — just clear elements
        if (this._cy) {
            this._cy.elements().remove();
            this._lastTopology = '';
        }

        let emptyEl = this.container.querySelector('.empty-state');
        if (emptyEl) return; // already showing

        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '---';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'No flowchart data available';

        const subtext = document.createElement('div');
        subtext.className = 'empty-subtext';
        subtext.textContent = 'Flowchart will appear when workflow execution starts';

        empty.appendChild(icon);
        empty.appendChild(text);
        empty.appendChild(subtext);
        this.container.appendChild(empty);
    }

    _renderLibMissing() {
        if (this.container.querySelector('.empty-state')) return;

        const msg = document.createElement('div');
        msg.className = 'empty-state';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'Cytoscape.js not loaded';

        const subtext = document.createElement('div');
        subtext.className = 'empty-subtext';
        subtext.textContent = 'Flowchart view requires Cytoscape.js to be included in the page';

        msg.appendChild(text);
        msg.appendChild(subtext);
        this.container.appendChild(msg);
    }

    refresh() {
        this.render();
        if (this._cy) {
            this._cy.resize();
            this._cy.fit();
        }
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
        if (this._cy) {
            this._cy.destroy();
            this._cy = null;
        }
    }

    static get metadata() {
        return { id: 'flowchart', title: 'Flowchart' };
    }
}
