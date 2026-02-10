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

const DAGRE_LAYOUT = {
    name: 'dagre',
    rankDir: 'LR',
    align: 'UL',
    nodeSep: 30,
    rankSep: 80,
    padding: 20,
    animate: true,
    animationDuration: 300,
    // Collaboration edges (within a stage) should not force agents into
    // separate ranks — keep them stacked top-to-bottom inside their stage.
    minLen: function(edge) {
        return edge.data('type') === 'collaboration' ? 0 : 1;
    },
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
            if (this._cy.elements().length > 0) {
                try {
                    this._cy.layout(DAGRE_LAYOUT).run();
                } catch (err) {
                    console.debug('Dagre layout unavailable, falling back to grid:', err.message);
                    this._cy.layout({ name: 'grid', animate: true }).run();
                }
            }
        }
    }

    _buildElements(wf) {
        const elements = [];
        const stages = wf.stages || [];
        let collabIdx = 0;

        for (let i = 0; i < stages.length; i++) {
            const stage = stages[i];
            const stageData = this.dataStore.stages.get(stage.id) || stage;

            // Stage compound node
            elements.push({
                group: 'nodes',
                data: {
                    id: stage.id,
                    name: stageData.stage_name || stageData.name || stage.id,
                    type: 'stage',
                    status: stageData.status || 'pending',
                },
            });

            // Agent child nodes
            const agents = stageData.agents || stage.agents || [];
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
                    },
                });
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
