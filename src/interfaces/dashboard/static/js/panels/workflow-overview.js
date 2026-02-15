/**
 * Workflow Overview Panel — Sidebar panel showing workflow status, metrics, and stage list.
 * Displays live-updating workflow information with clickable stage navigation.
 */
import { ensureUTCString } from '../data-store.js';

// --- Formatting helpers ---

function formatDuration(seconds) {
    if (seconds == null || isNaN(seconds)) return '--';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
}

function formatCost(usd) {
    if (usd == null || isNaN(usd)) return '--';
    return `$${Number(usd).toFixed(4)}`;
}

function formatTokens(count) {
    if (count == null || isNaN(count)) return '--';
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toLocaleString();
}

// --- JSON viewer (safe DOM construction, no innerHTML) ---

function buildJsonViewer(obj, container) {
    const pre = document.createElement('pre');
    pre.className = 'json-viewer';
    const text = JSON.stringify(obj, null, 2);
    pre.textContent = text;
    container.appendChild(pre);
}

// --- Panel ---

export class WorkflowOverviewPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._rafId = null;
        this._changeHandler = (e) => {
            const ct = e.detail?.changeType;
            console.log('[WorkflowOverview] change event:', ct);
            // Handle all changes except stream content and selection
            if (ct === 'stream' || ct === 'selection') return;
            if (this._rafId == null) {
                this._rafId = requestAnimationFrame(() => {
                    this._rafId = null;
                    console.log('[WorkflowOverview] Rendering...');
                    this.render();
                });
            }
        };
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    render() {
        const wf = this.dataStore.workflow;

        // Clear previous content
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        if (!wf) {
            this._renderEmptyState();
            return;
        }

        // Status badge
        this._renderStatusBadge(wf);

        // Metrics row
        this._renderMetrics(wf);

        // Stage list
        this._renderStageList(wf);

        // Tags (if present)
        this._renderTags(wf);

        // Environment / Trigger (if present)
        this._renderMeta(wf);

        // Config section (collapsible)
        this._renderConfigSection(wf);
    }

    _renderEmptyState() {
        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '...';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'Waiting for workflow data';

        empty.appendChild(icon);
        empty.appendChild(text);
        this.container.appendChild(empty);
    }

    _renderStatusBadge(wf) {
        const status = wf.status || 'pending';
        const badge = document.createElement('span');
        badge.className = 'status-badge ' + status;
        badge.textContent = status;
        badge.style.display = 'inline-block';
        badge.style.marginBottom = '8px';
        this.container.appendChild(badge);
    }

    _renderMetrics(wf) {
        const row = document.createElement('div');
        row.className = 'metrics-row';

        // Aggregate metrics from all LLM / tool calls
        let totalTokens = 0;
        let totalCost = 0;
        const llmCount = this.dataStore.llmCalls.size;
        const toolCount = this.dataStore.toolCalls.size;

        for (const llm of this.dataStore.llmCalls.values()) {
            totalTokens += (llm.total_tokens || llm.tokens || 0);
            totalCost += (llm.cost || 0);
        }

        // Duration
        let duration = wf.duration_seconds;
        if (!duration && wf.start_time && wf.status === 'running') {
            const start = new Date(ensureUTCString(wf.start_time));
            duration = (Date.now() - start.getTime()) / 1000;
        }

        const metrics = [
            { label: 'Tokens', value: formatTokens(totalTokens) },
            { label: 'Cost', value: formatCost(totalCost) },
            { label: 'LLM Calls', value: String(llmCount) },
            { label: 'Tool Calls', value: String(toolCount) },
            { label: 'Duration', value: formatDuration(duration) },
        ];

        for (const m of metrics) {
            const card = document.createElement('div');
            card.className = 'metric-card';

            const val = document.createElement('div');
            val.className = 'metric-value';
            val.textContent = m.value;

            const lbl = document.createElement('div');
            lbl.className = 'metric-label';
            lbl.textContent = m.label;

            card.appendChild(val);
            card.appendChild(lbl);
            row.appendChild(card);
        }

        this.container.appendChild(row);
    }

    _renderStageList(wf) {
        // Always read fresh data from stages Map
        const stages = Array.from(this.dataStore.stages.values());
        if (stages.length === 0) {
            // Fallback to workflow.stages if Map is empty
            const wfStages = wf.stages || [];
            if (wfStages.length === 0) return;
            stages.push(...wfStages);
        }

        const heading = document.createElement('div');
        heading.className = 'text-muted';
        heading.style.fontSize = '11px';
        heading.style.textTransform = 'uppercase';
        heading.style.letterSpacing = '0.5px';
        heading.style.marginTop = '12px';
        heading.style.marginBottom = '4px';
        heading.textContent = 'Stages';
        this.container.appendChild(heading);

        const list = document.createElement('div');
        list.className = 'stage-list';

        for (const stage of stages) {
            // Always use fresh data from Map
            const stageData = stage;
            const item = document.createElement('div');
            item.className = 'stage-item';
            if (this.dataStore.selectedStageId === stage.id) {
                item.classList.add('selected');
            }

            // Status dot
            const dot = document.createElement('span');
            dot.className = 'stage-status-dot ' + (stageData.status || 'pending');

            // Name
            const name = document.createElement('span');
            name.className = 'stage-name';
            name.textContent = stageData.stage_name || stageData.name || stage.id;

            // Duration
            const dur = document.createElement('span');
            dur.className = 'stage-duration';
            let stageDuration = stageData.duration_seconds;
            if (!stageDuration && stageData.start_time && stageData.status === 'running') {
                const start = new Date(ensureUTCString(stageData.start_time));
                stageDuration = (Date.now() - start.getTime()) / 1000;
            }
            dur.textContent = formatDuration(stageDuration);

            item.appendChild(dot);
            item.appendChild(name);
            item.appendChild(dur);

            // Click to select stage
            const stageId = stage.id;
            item.addEventListener('click', () => {
                this.dataStore.select('stage', stageId);
            });

            list.appendChild(item);
        }

        this.container.appendChild(list);
    }

    _renderTags(wf) {
        const tags = wf.tags || wf.labels;
        if (!tags || (Array.isArray(tags) && tags.length === 0)) return;

        const wrapper = document.createElement('div');
        wrapper.style.marginTop = '12px';

        const heading = document.createElement('div');
        heading.className = 'text-muted';
        heading.style.fontSize = '11px';
        heading.style.textTransform = 'uppercase';
        heading.style.letterSpacing = '0.5px';
        heading.style.marginBottom = '4px';
        heading.textContent = 'Tags';
        wrapper.appendChild(heading);

        const tagContainer = document.createElement('div');
        tagContainer.style.display = 'flex';
        tagContainer.style.flexWrap = 'wrap';
        tagContainer.style.gap = '4px';

        const tagList = Array.isArray(tags) ? tags : Object.keys(tags);
        for (const t of tagList) {
            const tagEl = document.createElement('span');
            tagEl.className = 'tag tag-info';
            tagEl.textContent = String(t);
            tagContainer.appendChild(tagEl);
        }

        wrapper.appendChild(tagContainer);
        this.container.appendChild(wrapper);
    }

    _renderMeta(wf) {
        const items = [];
        if (wf.environment) items.push(['Environment', wf.environment]);
        if (wf.trigger_type) items.push(['Trigger', wf.trigger_type]);

        if (items.length === 0) return;

        const wrapper = document.createElement('div');
        wrapper.style.marginTop = '12px';
        wrapper.style.fontSize = '12px';
        wrapper.style.color = 'var(--text-secondary)';

        for (const [label, value] of items) {
            const row = document.createElement('div');
            row.style.display = 'flex';
            row.style.justifyContent = 'space-between';
            row.style.padding = '2px 0';

            const labelEl = document.createElement('span');
            labelEl.className = 'text-muted';
            labelEl.textContent = label;

            const valueEl = document.createElement('span');
            valueEl.className = 'mono';
            valueEl.textContent = value;

            row.appendChild(labelEl);
            row.appendChild(valueEl);
            wrapper.appendChild(row);
        }

        this.container.appendChild(wrapper);
    }

    _renderConfigSection(wf) {
        const config = wf.config || wf.workflow_config;
        if (!config) return;

        const section = document.createElement('div');
        section.className = 'collapsible collapsed';
        section.style.marginTop = '12px';

        const header = document.createElement('div');
        header.className = 'collapsible-header';

        const headerText = document.createElement('span');
        headerText.textContent = 'Configuration';

        const icon = document.createElement('span');
        icon.className = 'collapse-icon';
        icon.textContent = '\u25BC';

        header.appendChild(headerText);
        header.appendChild(icon);

        const body = document.createElement('div');
        body.className = 'collapsible-body';
        buildJsonViewer(config, body);

        header.addEventListener('click', () => {
            section.classList.toggle('collapsed');
        });

        section.appendChild(header);
        section.appendChild(body);
        this.container.appendChild(section);
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
        if (this._rafId != null) cancelAnimationFrame(this._rafId);
    }

    static get metadata() {
        return { id: 'workflow-overview', title: 'Workflow Overview' };
    }
}
