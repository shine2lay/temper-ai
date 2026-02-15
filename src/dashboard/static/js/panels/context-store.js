/**
 * Context Store Panel — Sidebar panel showing the global context state.
 * Displays accumulated stage outputs with context metadata, structured fields,
 * output previews, agent outputs, and synthesis results.
 * Updates live as stages complete. Each stage entry is collapsible.
 */

const OUTPUT_PREVIEW_LENGTH = 300;
const FIELD_VALUE_PREVIEW_LENGTH = 200;
const INPUT_VALUE_PREVIEW_LENGTH = 500;

// Internal keys to hide from input display
const INTERNAL_INPUT_KEYS = new Set([
    '_context_meta', '_context_resolved', 'current_stage_agents',
    'tracker', 'config_loader', 'tool_registry', 'context_provider',
    'show_details', 'detail_console', 'visualizer',
]);

function truncate(str, max) {
    if (!str || str.length <= max) return str;
    return str.slice(0, max) + '...';
}

function formatChars(count) {
    if (count == null) return '--';
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toLocaleString();
}

function formatValue(value) {
    if (value == null) return 'null';
    if (typeof value === 'object') {
        try { return JSON.stringify(value, null, 2); } catch { return String(value); }
    }
    return String(value);
}

export class ContextStorePanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._rafId = null;
        // Track collapsed state per stage name so it survives re-renders
        this._collapsed = new Map();
        this._changeHandler = (e) => {
            const ct = e.detail?.changeType;
            if (ct === 'stream' || ct === 'selection') return;
            if (this._rafId == null) {
                this._rafId = requestAnimationFrame(() => {
                    this._rafId = null;
                    this.render();
                });
            }
        };
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    render() {
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const stages = Array.from(this.dataStore.stages.values());
        if (stages.length === 0) {
            this._renderEmptyState();
            return;
        }

        const stagesWithOutput = stages.filter(s => s.output_data);

        // Summary line
        const summary = document.createElement('div');
        summary.className = 'ctx-store-summary';
        summary.textContent = `${stagesWithOutput.length} / ${stages.length} stages completed`;
        this.container.appendChild(summary);

        for (const stage of stages) {
            this.container.appendChild(this._buildStageEntry(stage));
        }
    }

    _renderEmptyState() {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'No stage data yet';
        empty.appendChild(text);
        this.container.appendChild(empty);
    }

    _buildStageEntry(stage) {
        const stageName = stage.stage_name || stage.name || 'Stage';
        const status = stage.status || 'pending';
        const outputData = stage.output_data;

        const entry = document.createElement('div');
        entry.className = 'ctx-store-entry';
        if (status === 'completed' || status === 'success') entry.classList.add('completed');
        else if (status === 'running') entry.classList.add('running');
        else if (status === 'failed') entry.classList.add('failed');

        // Header row — clickable to expand/collapse
        const header = document.createElement('div');
        header.className = 'ctx-store-entry-header';

        const dot = document.createElement('span');
        dot.className = 'stage-status-dot ' + status;
        header.appendChild(dot);

        const name = document.createElement('span');
        name.className = 'ctx-store-entry-name';
        name.textContent = stageName;
        header.appendChild(name);

        const hasContent = outputData || stage.input_data;

        // Collapse toggle icon
        if (hasContent) {
            const icon = document.createElement('span');
            icon.className = 'ctx-store-toggle';
            icon.textContent = '\u25BC';
            header.appendChild(icon);
        }

        entry.appendChild(header);

        if (!hasContent) {
            const pending = document.createElement('div');
            pending.className = 'ctx-store-pending';
            pending.textContent = status === 'running' ? 'executing...' : 'pending';
            entry.appendChild(pending);
            return entry;
        }

        // Body — collapsible
        const body = document.createElement('div');
        body.className = 'ctx-store-entry-body';

        // Default: expand new stages, remember collapsed state
        const isCollapsed = this._collapsed.get(stageName) ?? false;
        if (isCollapsed) {
            body.classList.add('collapsed');
            entry.classList.add('collapsed');
        }

        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
            const nowCollapsed = !body.classList.contains('collapsed');
            body.classList.toggle('collapsed');
            entry.classList.toggle('collapsed');
            this._collapsed.set(stageName, nowCollapsed);
        });

        // 1. Resolved inputs (actual values from stage.input_data)
        const inputData = stage.input_data;
        const contextMeta = (inputData && inputData._context_meta) || (outputData && outputData._context_meta);
        if (inputData && typeof inputData === 'object') {
            body.appendChild(this._buildInputs(inputData, contextMeta));
        }

        if (!outputData) {
            const pending = document.createElement('div');
            pending.className = 'ctx-store-pending';
            pending.textContent = 'output pending...';
            body.appendChild(pending);
            entry.appendChild(body);
            return entry;
        }

        // 2. Structured output fields (extracted by LLM)
        const structured = outputData.structured;
        if (structured && typeof structured === 'object' && Object.keys(structured).length > 0) {
            body.appendChild(this._buildStructuredFields(structured));
        }

        // 3. Raw output text
        const output = outputData.output || outputData.decision || '';
        if (output) {
            body.appendChild(this._buildOutputPreview(String(output)));
        }

        // 4. Agent outputs
        const agentOutputs = outputData.agent_outputs;
        if (agentOutputs && typeof agentOutputs === 'object' && Object.keys(agentOutputs).length > 0) {
            body.appendChild(this._buildAgentOutputs(agentOutputs, outputData.agent_statuses));
        }

        // 5. Synthesis result
        const synthesis = outputData.synthesis_result;
        if (synthesis && typeof synthesis === 'object') {
            body.appendChild(this._buildSynthesis(synthesis));
        }

        entry.appendChild(body);
        return entry;
    }

    _buildInputs(inputData, contextMeta) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ctx-store-section';

        // Filter out internal keys
        const userInputs = Object.entries(inputData)
            .filter(([key]) => !INTERNAL_INPUT_KEYS.has(key));

        if (userInputs.length === 0) return wrapper;

        const sources = (contextMeta && contextMeta.sources) || {};
        const defaults = (contextMeta && contextMeta.defaults_used) || [];

        const label = document.createElement('div');
        label.className = 'ctx-store-section-label';
        label.textContent = `Inputs (${userInputs.length})`;
        wrapper.appendChild(label);

        for (const [inputName, value] of userInputs) {
            const field = document.createElement('div');
            field.className = 'ctx-store-field-block';

            // Name line with source ref
            const nameRow = document.createElement('div');
            nameRow.style.display = 'flex';
            nameRow.style.alignItems = 'center';
            nameRow.style.gap = '6px';

            const nameSpan = document.createElement('div');
            nameSpan.className = 'ctx-store-field-name';
            nameSpan.textContent = inputName;
            nameRow.appendChild(nameSpan);

            // Show source ref inline (muted)
            const sourceRef = sources[inputName];
            if (sourceRef) {
                const refSpan = document.createElement('span');
                refSpan.style.fontSize = '10px';
                refSpan.style.color = 'var(--text-muted)';
                refSpan.style.fontFamily = 'var(--font-mono)';
                refSpan.textContent = `\u2190 ${sourceRef}`;
                nameRow.appendChild(refSpan);
            }

            if (defaults.includes(inputName)) {
                const defTag = document.createElement('span');
                defTag.className = 'ctx-store-default-tag';
                defTag.textContent = 'default';
                nameRow.appendChild(defTag);
            }

            field.appendChild(nameRow);

            // Value
            const valueEl = document.createElement('div');
            valueEl.className = 'ctx-store-field-value';
            const fullValue = formatValue(value);
            valueEl.textContent = truncate(fullValue, INPUT_VALUE_PREVIEW_LENGTH);
            valueEl.title = fullValue;
            field.appendChild(valueEl);

            wrapper.appendChild(field);
        }

        return wrapper;
    }

    _buildStructuredFields(structured) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ctx-store-section';

        const label = document.createElement('div');
        label.className = 'ctx-store-section-label';
        label.textContent = 'Structured Output';
        wrapper.appendChild(label);

        for (const [fieldName, value] of Object.entries(structured)) {
            const field = document.createElement('div');
            field.className = 'ctx-store-field-block';

            const nameSpan = document.createElement('div');
            nameSpan.className = 'ctx-store-field-name';
            nameSpan.textContent = fieldName;
            field.appendChild(nameSpan);

            const valueEl = document.createElement('div');
            valueEl.className = 'ctx-store-field-value';
            const fullValue = formatValue(value);
            valueEl.textContent = truncate(fullValue, FIELD_VALUE_PREVIEW_LENGTH);
            valueEl.title = fullValue;
            field.appendChild(valueEl);

            wrapper.appendChild(field);
        }

        return wrapper;
    }

    _buildOutputPreview(output) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ctx-store-section';

        const headerRow = document.createElement('div');
        headerRow.className = 'ctx-store-section-label';

        const labelText = document.createElement('span');
        labelText.textContent = 'Raw Output';
        headerRow.appendChild(labelText);

        const charCount = document.createElement('span');
        charCount.className = 'ctx-store-char-count';
        charCount.textContent = `${formatChars(output.length)} chars`;
        headerRow.appendChild(charCount);

        wrapper.appendChild(headerRow);

        const preview = document.createElement('div');
        preview.className = 'ctx-store-output-text';
        preview.textContent = truncate(output, OUTPUT_PREVIEW_LENGTH);
        wrapper.appendChild(preview);

        // "Show more" toggle if output is longer than preview
        if (output.length > OUTPUT_PREVIEW_LENGTH) {
            const toggle = document.createElement('div');
            toggle.className = 'ctx-store-show-more';
            toggle.textContent = 'show full output';
            let expanded = false;
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                expanded = !expanded;
                preview.textContent = expanded ? output : truncate(output, OUTPUT_PREVIEW_LENGTH);
                toggle.textContent = expanded ? 'show less' : 'show full output';
                preview.classList.toggle('expanded', expanded);
            });
            wrapper.appendChild(toggle);
        }

        return wrapper;
    }

    _buildAgentOutputs(agentOutputs, agentStatuses) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ctx-store-section';

        const label = document.createElement('div');
        label.className = 'ctx-store-section-label';
        label.textContent = `Agents (${Object.keys(agentOutputs).length})`;
        wrapper.appendChild(label);

        for (const [agentName, agentData] of Object.entries(agentOutputs)) {
            // Skip internal agents
            if (agentName.startsWith('__') && agentName.endsWith('__')) continue;

            const card = document.createElement('div');
            card.className = 'ctx-store-agent-card';

            // Agent header: name + status
            const agentHeader = document.createElement('div');
            agentHeader.className = 'ctx-store-agent-header';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'ctx-store-agent-name';
            nameSpan.textContent = agentName;
            agentHeader.appendChild(nameSpan);

            // Status badge
            const statusData = agentStatuses && agentStatuses[agentName];
            const agentStatus = typeof statusData === 'string'
                ? statusData
                : (typeof statusData === 'object' && statusData?.status) || '';
            if (agentStatus) {
                const statusTag = document.createElement('span');
                statusTag.className = 'ctx-store-agent-status';
                statusTag.classList.add(agentStatus === 'completed' || agentStatus === 'success' ? 'success' : 'failed');
                statusTag.textContent = agentStatus;
                agentHeader.appendChild(statusTag);
            }

            card.appendChild(agentHeader);

            // Agent output preview
            const agentOutput = typeof agentData === 'object'
                ? (agentData.output || agentData.decision || '')
                : String(agentData || '');
            if (agentOutput) {
                const outputEl = document.createElement('div');
                outputEl.className = 'ctx-store-agent-output';
                outputEl.textContent = truncate(String(agentOutput), OUTPUT_PREVIEW_LENGTH);
                outputEl.title = String(agentOutput);
                card.appendChild(outputEl);
            }

            // Confidence + tokens
            const metricsRow = document.createElement('div');
            metricsRow.className = 'ctx-store-agent-metrics';
            const parts = [];
            if (typeof agentData === 'object') {
                if (agentData.confidence != null) parts.push(`conf: ${Number(agentData.confidence).toFixed(2)}`);
                if (agentData.tokens != null) parts.push(`${agentData.tokens} tok`);
                if (agentData.cost_usd != null || agentData.cost != null) {
                    const cost = agentData.cost_usd || agentData.cost;
                    parts.push(`$${Number(cost).toFixed(4)}`);
                }
            }
            if (parts.length > 0) {
                metricsRow.textContent = parts.join(' \u00B7 ');
                card.appendChild(metricsRow);
            }

            wrapper.appendChild(card);
        }

        return wrapper;
    }

    _buildSynthesis(synthesis) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ctx-store-section';

        const label = document.createElement('div');
        label.className = 'ctx-store-section-label';
        label.textContent = 'Synthesis';
        wrapper.appendChild(label);

        const detail = document.createElement('div');
        detail.className = 'ctx-store-synthesis';

        const parts = [];
        if (synthesis.method) parts.push(`method: ${synthesis.method}`);
        if (synthesis.confidence != null) parts.push(`confidence: ${Number(synthesis.confidence).toFixed(2)}`);
        if (synthesis.votes && typeof synthesis.votes === 'object') {
            const voteEntries = Object.entries(synthesis.votes)
                .map(([k, v]) => `${k}: ${v}`)
                .join(', ');
            if (voteEntries) parts.push(`votes: {${voteEntries}}`);
        }
        detail.textContent = parts.join(' \u00B7 ');
        wrapper.appendChild(detail);

        return wrapper;
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
        if (this._rafId != null) cancelAnimationFrame(this._rafId);
    }

    static get metadata() {
        return { id: 'context-store', title: 'Context Store' };
    }
}
