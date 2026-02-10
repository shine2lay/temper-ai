/**
 * Flowchart Panel — Cytoscape.js node graph (LangFlow-style).
 * Shows stages as compound nodes with agent children, data flow edges,
 * and collaboration edges. Live updates via DataStore events.
 */

const STATUS_COLORS = {
    completed: '#66bb6a',
    running:   '#4fc3f7',
    failed:    '#ef5350',
    pending:   '#6a7080',
};

const CYTOSCAPE_STYLE = [
    // Stage (compound/parent) nodes
    {
        selector: 'node[type="stage"]',
        style: {
            'background-color': '#1e2a4a',
            'border-color': '#2a3a5c',
            'border-width': 2,
            'shape': 'roundrectangle',
            'label': 'data(name)',
            'text-valign': 'top',
            'text-halign': 'center',
            'color': '#a0a0b0',
            'font-size': 12,
            'font-weight': 'bold',
            'padding': '20px',
            'text-margin-y': -5,
            'min-width': 180,
            'min-height': 80,
        },
    },
    // Agent (child) nodes
    {
        selector: 'node[type="agent"]',
        style: {
            'background-color': '#0f1729',
            'border-color': '#2a3a5c',
            'border-width': 2,
            'shape': 'roundrectangle',
            'width': 160,
            'height': 60,
            'label': 'data(label)',
            'text-wrap': 'wrap',
            'text-max-width': '140px',
            'color': '#e0e0e0',
            'font-size': 11,
            'text-valign': 'center',
            'text-halign': 'center',
        },
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
];

// Spacing constants for manual LR layout (stages left-to-right, agents top-to-bottom)
const LAYOUT = {
    AGENT_WIDTH: 160,
    AGENT_HEIGHT: 60,
    AGENT_GAP_Y: 20,       // vertical gap between agents
    STAGE_GAP_X: 120,      // horizontal gap between stages
    STAGE_PAD_X: 30,       // horizontal padding inside stage
    STAGE_PAD_Y: 40,       // vertical padding inside stage (top has label)
};

export class FlowchartPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._cy = null;
        this._lastTopology = '';
        this._changeHandler = () => this.render();
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
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

        // Click stage node → select stage in DataStore
        this._cy.on('tap', 'node[type="stage"]', (e) => {
            this.dataStore.select('stage', e.target.id());
        });
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

        // Only re-layout when topology (set of element IDs) changes
        const currentTopology = this._cy.elements().map(e => e.id()).sort().join(',');
        if (currentTopology !== this._lastTopology) {
            this._lastTopology = currentTopology;
            this._applyLayout();
        }
    }

    _applyLayout() {
        if (!this._cy || this._cy.elements().length === 0) return;

        // Position map: agent id → { x, y }
        const positions = {};
        const agentNodes = this._cy.nodes('[type="agent"]');
        agentNodes.forEach(n => {
            positions[n.id()] = { x: n.data('_px'), y: n.data('_py') };
        });

        this._cy.layout({
            name: 'preset',
            positions: (node) => {
                // Only position agent (child) nodes — compound parents auto-wrap
                if (node.data('type') === 'agent') {
                    return positions[node.id()] || { x: 0, y: 0 };
                }
                return undefined;
            },
            fit: true,
            padding: 30,
            animate: true,
            animationDuration: 300,
        }).run();
    }

    _buildElements(wf) {
        const elements = [];
        const stages = wf.stages || [];
        let collabIdx = 0;
        let xCursor = 0;

        for (let i = 0; i < stages.length; i++) {
            const stage = stages[i];
            const stageData = this.dataStore.stages.get(stage.id) || stage;

            // Stage compound node (position derived from children)
            elements.push({
                group: 'nodes',
                data: {
                    id: stage.id,
                    name: stageData.stage_name || stageData.name || stage.id,
                    type: 'stage',
                    status: stageData.status || 'pending',
                },
            });

            // Agent child nodes — positioned left-to-right by stage, top-to-bottom within
            const agents = stageData.agents || stage.agents || [];
            const agentCount = agents.filter(a => a.id).length;
            const stageX = xCursor + LAYOUT.STAGE_PAD_X + LAYOUT.AGENT_WIDTH / 2;
            let agentIdx = 0;

            for (const agent of agents) {
                if (!agent.id) continue;
                const agentData = this.dataStore.agents.get(agent.id) || agent;
                const name = agentData.agent_name || agentData.name || agent.id;
                const model = (agentData.agent_config_snapshot || {}).model || '';
                const tokens = agentData.total_tokens;
                const cost = agentData.estimated_cost_usd;
                const status = agentData.status || 'pending';

                // Build multi-line label
                const lines = [name];
                if (model) lines.push(model);
                const metricParts = [];
                if (tokens) metricParts.push(`${tokens} tok`);
                if (cost != null && cost > 0) metricParts.push(`$${cost.toFixed(4)}`);
                if (metricParts.length) lines.push(metricParts.join(' | '));

                // Compute position: x = stage column, y = agent row within stage
                const px = stageX;
                const py = LAYOUT.STAGE_PAD_Y + agentIdx * (LAYOUT.AGENT_HEIGHT + LAYOUT.AGENT_GAP_Y);

                elements.push({
                    group: 'nodes',
                    data: {
                        id: agent.id,
                        parent: stage.id,
                        name: name,
                        label: lines.join('\n'),
                        type: 'agent',
                        status: status,
                        model: model,
                        _px: px,
                        _py: py,
                    },
                });
                agentIdx++;
            }

            // Advance x cursor past this stage
            const stageWidth = LAYOUT.STAGE_PAD_X * 2 + LAYOUT.AGENT_WIDTH;
            xCursor += stageWidth + LAYOUT.STAGE_GAP_X;

            // If stage has no agents, add a placeholder width
            if (agentCount === 0) {
                // Stage still needs some width even without agents
                // xCursor already advanced above
            }

            // Collaboration edges within stage
            const collabEvents = stageData.collaboration_events || stage.collaboration_events || [];
            for (const event of collabEvents) {
                const involved = event.agents_involved || [];
                if (involved.length >= 2) {
                    const edgeId = `collab-${involved[0]}-${involved[1]}-${collabIdx++}`;
                    elements.push({
                        group: 'edges',
                        data: {
                            id: edgeId,
                            source: involved[0],
                            target: involved[1],
                            type: 'collaboration',
                            label: event.event_type || '',
                        },
                    });
                }
            }

            // Sequential stage-to-stage data flow edges
            if (i > 0) {
                const prevStage = stages[i - 1];
                const prevData = this.dataStore.stages.get(prevStage.id) || prevStage;
                const outputKeys = Object.keys(prevData.output_data || {});
                const label = outputKeys.join(', ');
                elements.push({
                    group: 'edges',
                    data: {
                        id: `flow-${prevStage.id}-${stage.id}`,
                        source: prevStage.id,
                        target: stage.id,
                        type: 'data_flow',
                        label: label,
                    },
                });
            }
        }

        return elements;
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

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
        if (this._cy) {
            this._cy.destroy();
            this._cy = null;
        }
    }

    static get metadata() {
        return { id: 'flowchart', title: 'Flowchart' };
    }
}
