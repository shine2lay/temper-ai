/**
 * Stage Detail Panel — Shows selected stage's full details.
 * Displays metrics, agent success bar, input/output data,
 * collaboration events, and clickable agent list.
 */

const DOMPURIFY_CONFIG = {
    ALLOWED_TAGS: [
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'p', 'br', 'hr',
        'ul', 'ol', 'li',
        'strong', 'em', 'code', 'pre',
        'blockquote', 'a', 'table', 'thead',
        'tbody', 'tr', 'th', 'td',
        'del', 'ins', 'sub', 'sup', 'img'
    ],
    ALLOWED_ATTR: ['href', 'title', 'alt', 'src'],
    ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick']
};

function sanitizeAndParse(text) {
    const html = DOMPurify.sanitize(marked.parse(String(text)), DOMPURIFY_CONFIG);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    for (const a of wrapper.querySelectorAll('a')) {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
    }
    return wrapper.innerHTML;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function formatDuration(seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}

function formatCost(usd) {
    if (usd == null) return '--';
    if (usd < 0.001) return `$${usd.toFixed(6)}`;
    if (usd < 0.01) return `$${usd.toFixed(4)}`;
    return `$${usd.toFixed(4)}`;
}

function formatTokens(count) {
    if (count == null) return '--';
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toLocaleString();
}

function formatJSON(obj) {
    if (obj == null) return 'null';
    const str = JSON.stringify(obj, null, 2);
    return str.replace(
        /("(?:[^"\\]|\\.)*")(\s*:)?|(\b\d+\.?\d*\b)|(\bnull\b)|(\btrue\b|\bfalse\b)/g,
        (match, key, colon, number, nullVal, bool) => {
            if (key && colon) {
                return `<span class="json-key">${escapeHtml(key)}</span>${colon}`;
            }
            if (key) return `<span class="json-string">${escapeHtml(key)}</span>`;
            if (number) return `<span class="json-number">${number}</span>`;
            if (nullVal) return `<span class="json-null">null</span>`;
            if (bool) return `<span class="json-boolean">${bool}</span>`;
            return match;
        }
    );
}

export class StageDetailPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._changeHandler = (e) => this._onDataChange(e.detail);
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    static get metadata() {
        return { id: 'stage-detail', title: 'Stage Detail' };
    }

    _onDataChange(detail) {
        if (detail.changeType === 'stream') return;
        if (detail.changeType === 'selection' || detail.changeType === 'snapshot') {
            this._renderWithFetch();
            return;
        }
        if (detail.changeType === 'event') {
            // Fetch fresh data when the selected stage completes
            const stageId = this.dataStore.selectedStageId;
            if (!stageId) return;
            const eventStageId = detail.data?.stage_id || detail.stage_id;
            if (eventStageId === stageId &&
                (detail.event_type === 'stage_end' || detail.event_type === 'stage_output')) {
                this._renderWithFetch();
            }
        }
    }

    async _renderWithFetch() {
        this.container.innerHTML = '';
        const stageId = this.dataStore.selectedStageId;
        if (!stageId) {
            this._renderEmptyState();
            return;
        }

        // Show cached data immediately if available
        let stage = this.dataStore.stages.get(stageId);
        if (stage) {
            this._renderStage(stage);
        }

        // Fetch full data from API (has agents with llm_calls, output_data, etc.)
        const fresh = await this._fetchStage(stageId);
        if (!fresh) {
            if (!stage) this._renderEmptyState('Stage not found');
            return;
        }

        // Bail if selection changed during fetch
        if (this.dataStore.selectedStageId !== stageId) return;

        // Merge fresh data into Map
        if (stage) {
            Object.assign(stage, fresh);
        } else {
            stage = fresh;
            this.dataStore.stages.set(stageId, stage);
        }

        // Re-render with full data
        this.container.innerHTML = '';
        this._renderStage(stage);
    }

    render() {
        this.container.innerHTML = '';
        const stageId = this.dataStore.selectedStageId;
        if (!stageId) {
            this._renderEmptyState();
            return;
        }
        const stage = this.dataStore.stages.get(stageId);
        if (!stage) {
            this._renderEmptyState('Stage not found');
            return;
        }
        this._renderStage(stage);
    }

    async _fetchStage(id) {
        try {
            const resp = await fetch(`/api/stages/${id}`);
            if (resp.ok) return await resp.json();
        } catch (err) {
            console.warn(`Failed to fetch stage ${id}:`, err);
        }
        return null;
    }

    _renderEmptyState(msg) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '\u{1F4CB}';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = msg || 'Select a stage from the sidebar to view details';

        empty.appendChild(icon);
        empty.appendChild(text);
        this.container.appendChild(empty);
    }

    _renderStage(stage) {
        const agents = stage.agents || [];

        // Create scroll wrapper
        const scrollWrapper = document.createElement('div');
        scrollWrapper.style.cssText = 'overflow-y:auto;flex:1;min-height:0;';

        // Header
        scrollWrapper.appendChild(this._buildHeader(stage));

        // Configuration section (description, inputs, outputs)
        const config = stage.stage_config_snapshot;
        if (config && (config.description || config.inputs || config.outputs)) {
            scrollWrapper.appendChild(this._buildConfigSection(config));
        }

        // Metrics row (aggregated from agents)
        scrollWrapper.appendChild(this._buildMetrics(stage, agents));

        // Agent success bar
        if (agents.length > 0) {
            scrollWrapper.appendChild(this._buildAgentSuccessBar(agents));
        }

        // Error message
        if (stage.status === 'failed' && (stage.error_message || stage.error)) {
            scrollWrapper.appendChild(this._buildErrorMessage(stage.error_message || stage.error));
        }

        // Input data (collapsible, collapsed)
        if (stage.input_data) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Input Data', () => this._buildJsonViewer(stage.input_data), true)
            );
        }

        // Output data (collapsible, expanded) — render as markdown
        if (stage.output_data) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Output Data', () => this._buildOutputDisplay(stage.output_data), false)
            );
        }

        // Collaboration events
        const collabEvents = stage.collaboration_events || [];
        if (collabEvents.length > 0) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Collaboration Events', () => this._buildCollabList(collabEvents), false)
            );
        }

        // Agents list
        if (agents.length > 0) {
            scrollWrapper.appendChild(this._buildAgentList(agents));
        }

        // Add scroll wrapper to container
        this.container.appendChild(scrollWrapper);
    }

    _buildHeader(stage) {
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;flex-shrink:0;';

        const name = document.createElement('span');
        name.style.cssText = 'font-size:16px;font-weight:600;';
        name.textContent = stage.stage_name || stage.name || 'Stage';

        const statusBadge = document.createElement('span');
        statusBadge.className = `status-badge ${stage.status || ''}`;
        statusBadge.textContent = stage.status || 'unknown';

        header.appendChild(name);
        header.appendChild(statusBadge);

        if (stage.execution_mode) {
            const modeTag = document.createElement('span');
            modeTag.className = 'tag tag-info';
            modeTag.textContent = stage.execution_mode;
            header.appendChild(modeTag);
        }

        return header;
    }

    _buildConfigSection(config) {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'background:rgba(79,195,247,0.05);border:1px solid var(--border-color);border-radius:6px;padding:12px;margin-bottom:12px;flex-shrink:0;';

        // Description
        if (config.description) {
            const descLabel = document.createElement('div');
            descLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            descLabel.textContent = 'Description';
            wrapper.appendChild(descLabel);

            const descText = document.createElement('div');
            descText.style.cssText = 'font-size:13px;color:var(--text-primary);line-height:1.5;margin-bottom:12px;';
            descText.textContent = config.description;
            wrapper.appendChild(descText);
        }

        // Key parameters grid
        const params = [];
        if (config.execution_mode) params.push({ label: 'Execution Mode', value: config.execution_mode });
        if (config.strategy) params.push({ label: 'Strategy', value: config.strategy });
        if (config.timeout_seconds != null) params.push({ label: 'Timeout', value: `${config.timeout_seconds}s` });
        if (config.max_retries != null) params.push({ label: 'Max Retries', value: config.max_retries });
        if (config.max_rounds != null) params.push({ label: 'Max Rounds', value: config.max_rounds });

        if (params.length > 0) {
            const paramsGrid = document.createElement('div');
            paramsGrid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:12px;';

            for (const p of params) {
                const cell = document.createElement('div');
                cell.style.cssText = 'background:rgba(0,0,0,0.1);padding:6px 8px;border-radius:4px;';

                const label = document.createElement('div');
                label.style.cssText = 'font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:2px;';
                label.textContent = p.label;

                const value = document.createElement('div');
                value.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-primary);font-family:var(--font-mono);';
                value.textContent = p.value;

                cell.appendChild(label);
                cell.appendChild(value);
                paramsGrid.appendChild(cell);
            }
            wrapper.appendChild(paramsGrid);
        }

        // Agents in this stage
        if (config.agents && config.agents.length > 0) {
            const agentsLabel = document.createElement('div');
            agentsLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            agentsLabel.textContent = 'Configured Agents';
            wrapper.appendChild(agentsLabel);

            const agentsContainer = document.createElement('div');
            agentsContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;';

            for (const agent of config.agents) {
                const agentName = typeof agent === 'string' ? agent : (agent.name || agent.agent_name || 'Unknown');
                const tag = document.createElement('span');
                tag.className = 'tag';
                tag.style.cssText = 'background:rgba(79,195,247,0.15);color:var(--accent);font-size:11px;';
                tag.textContent = agentName;
                agentsContainer.appendChild(tag);
            }

            wrapper.appendChild(agentsContainer);
        }

        // Inputs schema
        if (config.inputs) {
            const inputLabel = document.createElement('div');
            inputLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            inputLabel.textContent = 'Expected Inputs';
            wrapper.appendChild(inputLabel);

            const inputContent = this._buildSchemaDisplay(config.inputs);
            wrapper.appendChild(inputContent);
        }

        // Outputs schema
        if (config.outputs) {
            const outputLabel = document.createElement('div');
            outputLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            outputLabel.textContent = 'Expected Outputs';
            wrapper.appendChild(outputLabel);

            const outputContent = this._buildSchemaDisplay(config.outputs);
            wrapper.appendChild(outputContent);
        }

        return wrapper;
    }

    _buildSchemaDisplay(schema) {
        const display = document.createElement('div');
        display.style.cssText = 'font-size:12px;color:var(--text-muted);margin-bottom:12px;';

        const allFields = [];

        // Collect required fields
        if (Array.isArray(schema.required) && schema.required.length > 0) {
            for (const field of schema.required) {
                allFields.push({ name: field, required: true });
            }
        }

        // Collect optional fields
        if (Array.isArray(schema.optional) && schema.optional.length > 0) {
            for (const field of schema.optional) {
                allFields.push({ name: field, required: false });
            }
        }

        if (allFields.length > 0) {
            const container = document.createElement('div');
            container.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;';

            for (const field of allFields) {
                const tag = document.createElement('span');
                tag.style.cssText = field.required
                    ? 'font-family:var(--font-mono);font-size:11px;background:rgba(79,195,247,0.1);color:var(--accent);padding:2px 8px;border-radius:3px;'
                    : 'font-family:var(--font-mono);font-size:11px;background:rgba(160,160,176,0.1);color:var(--text-muted);padding:2px 8px;border-radius:3px;';
                tag.textContent = field.name;

                if (field.required) {
                    tag.title = 'Required';
                } else {
                    tag.title = 'Optional';
                }

                container.appendChild(tag);
            }

            display.appendChild(container);
        }

        return display;
    }

    _buildMetrics(stage, agents) {
        const row = document.createElement('div');
        row.className = 'metrics-row';
        row.style.cssText = 'margin-bottom:8px;flex-shrink:0;';

        let succeeded = 0;
        let failed = 0;
        let totalTokens = 0;
        let totalCost = 0;

        for (const agent of agents) {
            if (agent.status === 'completed' || agent.status === 'success') succeeded++;
            else if (agent.status === 'failed') failed++;
            totalTokens += (agent.prompt_tokens || 0) + (agent.completion_tokens || 0);
            totalCost += (agent.estimated_cost_usd || 0);
        }

        // Use stage-level metrics from API as fallback when agents array is sparse
        const numAgents = agents.length || stage.num_agents_executed || 0;
        const numSucceeded = succeeded || stage.num_agents_succeeded || 0;
        const numFailed = failed || stage.num_agents_failed || 0;

        const metrics = [
            { label: 'Agents', value: numAgents },
            { label: 'Succeeded', value: numSucceeded },
            { label: 'Failed', value: numFailed },
            { label: 'Duration', value: formatDuration(stage.duration_seconds) },
            { label: 'Tokens', value: formatTokens(totalTokens || null) },
            { label: 'Cost', value: formatCost(totalCost || null) },
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

        return row;
    }

    _buildAgentSuccessBar(agents) {
        const wrapper = document.createElement('div');
        wrapper.style.marginBottom = '8px';

        let succeeded = 0;
        let failed = 0;
        for (const agent of agents) {
            if (agent.status === 'completed' || agent.status === 'success') succeeded++;
            else if (agent.status === 'failed') failed++;
        }
        const total = agents.length;

        const labelRow = document.createElement('div');
        labelRow.style.cssText = 'display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:2px;';

        const succLabel = document.createElement('span');
        succLabel.textContent = `Succeeded: ${succeeded}`;
        const failLabel = document.createElement('span');
        failLabel.textContent = `Failed: ${failed}`;

        labelRow.appendChild(succLabel);
        labelRow.appendChild(failLabel);
        wrapper.appendChild(labelRow);

        const bar = document.createElement('div');
        bar.className = 'token-bar';

        if (total > 0) {
            const succPct = (succeeded / total * 100).toFixed(1);
            const failPct = (failed / total * 100).toFixed(1);

            const succBar = document.createElement('div');
            succBar.className = 'token-input';
            succBar.style.width = `${succPct}%`;
            succBar.style.background = 'var(--success)';

            const failBar = document.createElement('div');
            failBar.className = 'token-output';
            failBar.style.width = `${failPct}%`;
            failBar.style.background = 'var(--error)';

            bar.appendChild(succBar);
            bar.appendChild(failBar);
        }

        wrapper.appendChild(bar);
        return wrapper;
    }

    _buildErrorMessage(error) {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'background:rgba(255,59,48,0.1);border:1px solid var(--error);border-radius:6px;padding:8px;margin-bottom:8px;';

        const label = document.createElement('div');
        label.style.cssText = 'font-size:11px;font-weight:600;color:var(--error);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;';
        label.textContent = 'Error';

        const msg = document.createElement('div');
        msg.style.cssText = 'font-size:12px;color:var(--text-primary);font-family:var(--font-mono);white-space:pre-wrap;word-break:break-word;';
        msg.textContent = typeof error === 'string' ? error : JSON.stringify(error, null, 2);

        wrapper.appendChild(label);
        wrapper.appendChild(msg);
        return wrapper;
    }

    _buildCollapsible(title, contentBuilder, collapsed) {
        const section = document.createElement('div');
        section.className = 'collapsible' + (collapsed ? ' collapsed' : '');

        const header = document.createElement('div');
        header.className = 'collapsible-header';

        const titleSpan = document.createElement('span');
        titleSpan.textContent = title;

        const icon = document.createElement('span');
        icon.className = 'collapse-icon';
        icon.textContent = '\u25BC';

        header.appendChild(titleSpan);
        header.appendChild(icon);

        header.addEventListener('click', () => {
            section.classList.toggle('collapsed');
        });

        const body = document.createElement('div');
        body.className = 'collapsible-body';
        body.appendChild(contentBuilder());

        section.appendChild(header);
        section.appendChild(body);
        return section;
    }

    _buildJsonViewer(data) {
        const viewer = document.createElement('div');
        viewer.className = 'json-viewer';
        // formatJSON produces safe output from JSON.stringify — innerHTML is safe here
        viewer.innerHTML = formatJSON(data);
        return viewer;
    }

    _buildOutputDisplay(data) {
        let text = null;
        let parsed = data;
        if (typeof parsed === 'string') {
            try { parsed = JSON.parse(parsed); } catch { /* use as-is */ }
        }
        if (parsed && typeof parsed === 'object' && typeof parsed.output === 'string') {
            text = parsed.output;
        } else if (typeof data === 'string') {
            text = data;
        }

        const display = document.createElement('div');
        display.className = 'prompt-display';

        if (text && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const md = document.createElement('div');
            md.className = 'markdown-content';
            md.innerHTML = sanitizeAndParse(text);
            display.appendChild(md);
        } else {
            const pre = document.createElement('div');
            pre.className = 'prompt-text';
            pre.textContent = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);
            display.appendChild(pre);
        }
        return display;
    }

    _buildMarkdownDisplay(text) {
        const display = document.createElement('div');
        display.className = 'prompt-display';
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const md = document.createElement('div');
            md.className = 'markdown-content';
            md.innerHTML = sanitizeAndParse(text);
            display.appendChild(md);
        } else {
            const pre = document.createElement('div');
            pre.className = 'prompt-text';
            pre.textContent = String(text);
            display.appendChild(pre);
        }
        return display;
    }

    _buildCollabList(events) {
        const list = document.createElement('div');
        list.className = 'call-list';

        for (const evt of events) {
            const item = document.createElement('div');
            item.className = 'call-item';
            item.style.flexDirection = 'column';
            item.style.alignItems = 'flex-start';
            item.style.gap = '4px';

            const topRow = document.createElement('div');
            topRow.style.cssText = 'display:flex;align-items:center;gap:6px;width:100%;';

            const typeTag = document.createElement('span');
            typeTag.className = 'tag tag-info';
            typeTag.textContent = evt.event_type || 'collaboration';
            topRow.appendChild(typeTag);

            if (evt.round_number != null) {
                const roundTag = document.createElement('span');
                roundTag.className = 'tag';
                roundTag.style.cssText = 'background:rgba(160,160,176,0.15);color:var(--text-secondary);';
                roundTag.textContent = `Round ${evt.round_number}`;
                topRow.appendChild(roundTag);
            }

            if (evt.outcome) {
                const outcomeTag = document.createElement('span');
                outcomeTag.className = `tag ${evt.outcome === 'success' ? 'tag-success' : evt.outcome === 'failed' ? 'tag-error' : ''}`;
                outcomeTag.textContent = evt.outcome;
                topRow.appendChild(outcomeTag);
            }

            item.appendChild(topRow);

            if (evt.agents_involved && evt.agents_involved.length > 0) {
                const agentsRow = document.createElement('div');
                agentsRow.style.cssText = 'font-size:11px;color:var(--text-muted);';
                agentsRow.textContent = `Agents: ${evt.agents_involved.join(', ')}`;
                item.appendChild(agentsRow);
            }

            list.appendChild(item);
        }

        return list;
    }

    _buildAgentList(agents) {
        const section = document.createElement('div');
        section.style.marginTop = '8px';

        const heading = document.createElement('div');
        heading.style.cssText = 'font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;';
        heading.textContent = 'Agents';
        section.appendChild(heading);

        const list = document.createElement('div');
        list.className = 'call-list';

        for (const agent of agents) {
            const item = document.createElement('div');
            item.className = 'call-item';

            if (agent.id === this.dataStore.selectedAgentId) {
                item.classList.add('selected');
            }

            const nameSpan = document.createElement('span');
            nameSpan.className = 'call-name';
            nameSpan.textContent = agent.agent_name || agent.name || 'Agent';
            item.appendChild(nameSpan);

            if (agent.status) {
                const statusTag = document.createElement('span');
                statusTag.className = `tag ${agent.status === 'completed' || agent.status === 'success' ? 'tag-success' : agent.status === 'failed' ? 'tag-error' : 'tag-info'}`;
                statusTag.textContent = agent.status;
                item.appendChild(statusTag);
            }

            const config = agent.agent_config_snapshot;
            if (config && config.model) {
                const modelSpan = document.createElement('span');
                modelSpan.style.cssText = 'font-size:11px;color:var(--text-muted);';
                modelSpan.textContent = config.model;
                item.appendChild(modelSpan);
            }

            const tokens = (agent.prompt_tokens || 0) + (agent.completion_tokens || 0);
            if (tokens > 0) {
                const tokSpan = document.createElement('span');
                tokSpan.className = 'call-tokens';
                tokSpan.textContent = formatTokens(tokens);
                item.appendChild(tokSpan);
            }

            if (agent.estimated_cost_usd) {
                const costSpan = document.createElement('span');
                costSpan.className = 'call-duration';
                costSpan.textContent = formatCost(agent.estimated_cost_usd);
                item.appendChild(costSpan);
            }

            const agentId = agent.id;
            item.addEventListener('click', () => {
                this.dataStore.select('agent', agentId);
            });

            list.appendChild(item);
        }

        section.appendChild(list);
        return section;
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
    }
}
