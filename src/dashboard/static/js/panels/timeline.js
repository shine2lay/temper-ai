/**
 * Timeline Panel — Plotly.js horizontal bar chart (Gantt-style).
 * Shows hierarchical view of workflow/stage/agent/LLM/tool call timings.
 */

// Color palette per entity type
const COLORS = {
    workflow: '#42a5f5',  // blue
    stage:    '#66bb6a',  // green
    agent:    '#ffa726',  // orange
    llmCall:  '#ef5350',  // red
    toolCall: '#ffee58',  // yellow
};

// Indentation per hierarchy level
const INDENT = {
    workflow: '',
    stage:    '  ',
    agent:    '    ',
    llmCall:  '      ',
    toolCall: '      ',
};

function toEpochSeconds(timeValue) {
    if (timeValue == null) return null;
    const d = new Date(timeValue);
    if (isNaN(d.getTime())) return null;
    return d.getTime() / 1000;
}

function formatHoverDuration(seconds) {
    if (seconds == null || isNaN(seconds)) return '--';
    if (seconds < 60) return `${seconds.toFixed(2)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}m ${secs}s`;
}

export class TimelinePanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._plotDiv = null;
        this._initialized = false;
        this._entities = [];
        this._changeHandler = () => this.render();
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    render() {
        const wf = this.dataStore.workflow;
        if (!wf) {
            this._renderEmptyState();
            return;
        }

        // Ensure we have a plot container
        if (!this._plotDiv) {
            // Clear container
            while (this.container.firstChild) {
                this.container.removeChild(this.container.firstChild);
            }
            this._plotDiv = document.createElement('div');
            this._plotDiv.className = 'timeline-container';
            this.container.appendChild(this._plotDiv);
        }

        // Check if Plotly is available
        if (typeof Plotly === 'undefined') {
            this._renderPlotlyMissing();
            return;
        }

        const { trace, layout, entities } = this._buildPlotData(wf);
        this._entities = entities;

        if (entities.length === 0) {
            this._renderEmptyState();
            return;
        }

        if (!this._initialized) {
            Plotly.newPlot(this._plotDiv, [trace], layout, {
                displayModeBar: false,
                responsive: true,
            });
            this._plotDiv.on('plotly_click', (data) => this._handleClick(data));
            this._initialized = true;
        } else {
            Plotly.react(this._plotDiv, [trace], layout);
        }
    }

    _buildPlotData(wf) {
        const nowSeconds = Date.now() / 1000;
        const wfStart = toEpochSeconds(wf.start_time);
        const baseTime = wfStart || nowSeconds;

        const labels = [];
        const starts = [];
        const durations = [];
        const colors = [];
        const hoverTexts = [];
        const entities = [];

        // Helper to add a bar
        const addBar = (name, type, id, startTime, endTime, status, prefix) => {
            const sEpoch = toEpochSeconds(startTime);
            if (sEpoch == null) return;

            let eEpoch = toEpochSeconds(endTime);
            if (eEpoch == null && status === 'running') {
                eEpoch = nowSeconds;
            }
            if (eEpoch == null) {
                eEpoch = sEpoch + 0.1; // minimal bar for pending/unknown
            }

            const startOffset = sEpoch - baseTime;
            const duration = Math.max(eEpoch - sEpoch, 0.01);

            labels.push(prefix + name);
            starts.push(startOffset);
            durations.push(duration);
            colors.push(COLORS[type] || '#888');
            hoverTexts.push(
                `${name}<br>Status: ${status || 'unknown'}<br>Duration: ${formatHoverDuration(duration)}`
            );
            entities.push({ type, id });
        };

        // Workflow bar
        addBar(
            wf.workflow_name || 'Workflow',
            'workflow',
            wf.workflow_id || wf.id,
            wf.start_time,
            wf.end_time,
            wf.status,
            INDENT.workflow
        );

        // Stages
        const stages = wf.stages || [];
        for (const stage of stages) {
            const stageData = this.dataStore.stages.get(stage.id) || stage;
            addBar(
                stageData.stage_name || stageData.name || stage.id,
                'stage',
                stage.id,
                stageData.start_time,
                stageData.end_time,
                stageData.status,
                INDENT.stage
            );

            // Agents within stage
            const agents = stageData.agents || stage.agents || [];
            for (const agent of agents) {
                const agentData = this.dataStore.agents.get(agent.id) || agent;
                addBar(
                    agentData.agent_name || agentData.name || agent.id,
                    'agent',
                    agent.id,
                    agentData.start_time,
                    agentData.end_time,
                    agentData.status,
                    INDENT.agent
                );

                // LLM calls within agent
                const llmCalls = agentData.llm_calls || agent.llm_calls || [];
                for (const llm of llmCalls) {
                    const llmData = this.dataStore.llmCalls.get(llm.id) || llm;
                    addBar(
                        llmData.model || llmData.name || llm.id,
                        'llmCall',
                        llm.id,
                        llmData.start_time,
                        llmData.end_time,
                        llmData.status,
                        INDENT.llmCall
                    );
                }

                // Tool calls within agent
                const toolCalls = agentData.tool_calls || agent.tool_calls || [];
                for (const tool of toolCalls) {
                    const toolData = this.dataStore.toolCalls.get(tool.id) || tool;
                    addBar(
                        toolData.tool_name || toolData.name || tool.id,
                        'toolCall',
                        tool.id,
                        toolData.start_time,
                        toolData.end_time,
                        toolData.status,
                        INDENT.toolCall
                    );
                }
            }
        }

        const trace = {
            type: 'bar',
            orientation: 'h',
            y: labels,
            x: durations,
            base: starts,
            marker: { color: colors },
            hovertext: hoverTexts,
            hoverinfo: 'text',
        };

        const barCount = labels.length;
        const height = Math.max(300, barCount * 28 + 60);

        const layout = {
            barmode: 'overlay',
            showlegend: false,
            margin: { l: 200, r: 20, t: 10, b: 30 },
            xaxis: {
                title: 'Time (seconds)',
                type: 'linear',
                gridcolor: 'rgba(42, 58, 92, 0.3)',
                zerolinecolor: 'rgba(42, 58, 92, 0.5)',
            },
            yaxis: {
                autorange: 'reversed',
                tickfont: { family: 'JetBrains Mono, Fira Code, Consolas, monospace', size: 11 },
            },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { color: '#e0e0e0', size: 11 },
            height: height,
        };

        return { trace, layout, entities };
    }

    _handleClick(data) {
        if (!data || !data.points || data.points.length === 0) return;
        const pointIndex = data.points[0].pointIndex;
        if (pointIndex < 0 || pointIndex >= this._entities.length) return;

        const entity = this._entities[pointIndex];
        if (!entity) return;

        // Map entity type to DataStore select types
        const selectTypeMap = {
            workflow: null, // no workflow selection in DataStore
            stage: 'stage',
            agent: 'agent',
            llmCall: 'llmCall',
            toolCall: 'toolCall',
        };

        const selectType = selectTypeMap[entity.type];
        if (selectType) {
            this.dataStore.select(selectType, entity.id);
        }
    }

    _renderEmptyState() {
        // Only render if we don't already have a plot
        if (this._plotDiv && this._initialized) return;

        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '---';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'No timeline data available';

        const subtext = document.createElement('div');
        subtext.className = 'empty-subtext';
        subtext.textContent = 'Timeline will appear when workflow execution starts';

        empty.appendChild(icon);
        empty.appendChild(text);
        empty.appendChild(subtext);
        this.container.appendChild(empty);

        this._plotDiv = null;
        this._initialized = false;
    }

    _renderPlotlyMissing() {
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const msg = document.createElement('div');
        msg.className = 'empty-state';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'Plotly.js not loaded';

        const subtext = document.createElement('div');
        subtext.className = 'empty-subtext';
        subtext.textContent = 'Timeline chart requires Plotly.js to be included in the page';

        msg.appendChild(text);
        msg.appendChild(subtext);
        this.container.appendChild(msg);

        this._plotDiv = null;
        this._initialized = false;
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
        if (this._plotDiv && typeof Plotly !== 'undefined') {
            try {
                Plotly.purge(this._plotDiv);
            } catch (_) {
                // Ignore cleanup errors
            }
        }
        this._plotDiv = null;
        this._initialized = false;
    }

    static get metadata() {
        return { id: 'timeline', title: 'Timeline' };
    }
}
