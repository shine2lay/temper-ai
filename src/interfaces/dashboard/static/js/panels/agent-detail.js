/**
 * Agent Detail Panel — Shows selected agent's full details.
 * Displays metrics, token usage, input/output data, reasoning,
 * config, and lists of LLM/tool calls.
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
    // Force links to open in new tab
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

function formatLatencyMs(ms) {
    if (ms == null) return '--';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

export class AgentDetailPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._changeHandler = (e) => this._onDataChange(e.detail);
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    static get metadata() {
        return { id: 'agent-detail', title: 'Agent Detail' };
    }

    _onDataChange(detail) {
        if (detail.changeType === 'stream') return;
        if (detail.changeType === 'selection' || detail.changeType === 'snapshot') {
            this._renderWithFetch();
            return;
        }
        if (detail.changeType === 'event') {
            // Fetch fresh data when the selected agent completes or outputs
            const agentId = this.dataStore.selectedAgentId;
            if (!agentId) return;
            const eventAgentId = detail.data?.agent_id || detail.agent_id;
            if (eventAgentId === agentId &&
                (detail.event_type === 'agent_end' || detail.event_type === 'agent_output')) {
                this._renderWithFetch();
            }
            // Ignore events for other agents — our displayed data hasn't changed
        }
    }

    async _renderWithFetch() {
        this.container.innerHTML = '';
        const agentId = this.dataStore.selectedAgentId;
        if (!agentId) {
            this._renderEmptyState();
            return;
        }

        // Show cached data immediately if available
        let agent = this.dataStore.agents.get(agentId);
        if (agent) {
            this._renderAgent(agent);
        }

        // Fetch full data from API (has output_data, reasoning, llm_calls, etc.)
        const fresh = await this._fetchAgent(agentId);
        if (!fresh) {
            // API unavailable — keep cached render or show empty
            if (!agent) this._renderEmptyState('Agent not found');
            return;
        }

        // Bail if selection changed during fetch
        if (this.dataStore.selectedAgentId !== agentId) return;

        // Merge fresh data into Map (benefits all panels)
        if (agent) {
            Object.assign(agent, fresh);
        } else {
            agent = fresh;
            this.dataStore.agents.set(agentId, agent);
        }

        // Re-render with full data
        this.container.innerHTML = '';
        this._renderAgent(agent);
    }

    render() {
        this.container.innerHTML = '';
        const agentId = this.dataStore.selectedAgentId;
        if (!agentId) {
            this._renderEmptyState();
            return;
        }
        const agent = this.dataStore.agents.get(agentId);
        if (!agent) {
            this._renderEmptyState('Agent not found');
            return;
        }
        this._renderAgent(agent);
    }

    async _fetchAgent(id) {
        try {
            const resp = await fetch(`/api/agents/${id}`);
            if (resp.ok) return await resp.json();
        } catch (err) {
            console.warn(`Failed to fetch agent ${id}:`, err);
        }
        return null;
    }

    _renderEmptyState(msg) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '\u{1F916}';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = msg || 'Select an agent from the timeline to view details';

        empty.appendChild(icon);
        empty.appendChild(text);
        this.container.appendChild(empty);
    }

    _renderAgent(agent) {
        // Create scroll wrapper
        const scrollWrapper = document.createElement('div');
        scrollWrapper.style.cssText = 'overflow-y:auto;flex:1;min-height:0;';

        // Header
        scrollWrapper.appendChild(this._buildHeader(agent));

        // Configuration section (description, expected inputs/outputs)
        const config = agent.agent_config_snapshot;
        if (config && config.agent && (config.agent.description || config.agent.expected_inputs || config.agent.expected_outputs)) {
            scrollWrapper.appendChild(this._buildAgentConfigSection(config.agent));
        }

        // Metrics row
        scrollWrapper.appendChild(this._buildMetrics(agent));

        // Token usage bar
        if (agent.prompt_tokens || agent.completion_tokens) {
            scrollWrapper.appendChild(this._buildTokenBar(agent));
        }

        // Confidence score
        if (agent.confidence_score != null) {
            scrollWrapper.appendChild(this._buildConfidence(agent.confidence_score));
        }

        // Input data (collapsible, collapsed)
        if (agent.input_data) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Input Data', () => this._buildJsonViewer(agent.input_data), true)
            );
        }

        // Output (collapsible, expanded) — render as markdown
        if (agent.output_data) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Output', () => this._buildOutputDisplay(agent.output_data), false)
            );
        }

        // Reasoning (collapsible, collapsed)
        if (agent.reasoning) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Reasoning', () => this._buildTextDisplay(agent.reasoning), true)
            );
        }

        // Agent config (collapsible, collapsed)
        if (agent.agent_config_snapshot) {
            scrollWrapper.appendChild(
                this._buildCollapsible('Agent Config', () => this._buildJsonViewer(agent.agent_config_snapshot), true)
            );
        }

        // LLM Calls list
        const llmCalls = agent.llm_calls || [];
        if (llmCalls.length > 0) {
            scrollWrapper.appendChild(this._buildCallSection('LLM Calls', llmCalls, 'llm'));
        }

        // Tool Calls list
        const toolCalls = agent.tool_calls || [];
        if (toolCalls.length > 0) {
            scrollWrapper.appendChild(this._buildCallSection('Tool Calls', toolCalls, 'tool'));
        }

        // Add scroll wrapper to container
        this.container.appendChild(scrollWrapper);
    }

    _buildHeader(agent) {
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;flex-shrink:0;';

        const name = document.createElement('span');
        name.style.cssText = 'font-size:16px;font-weight:600;';
        name.textContent = agent.agent_name || 'Agent';

        const statusBadge = document.createElement('span');
        statusBadge.className = `status-badge ${agent.status || ''}`;
        statusBadge.textContent = agent.status || 'unknown';

        header.appendChild(name);
        header.appendChild(statusBadge);

        // Model/provider info
        const config = agent.agent_config_snapshot;
        if (config) {
            if (config.model) {
                const modelTag = document.createElement('span');
                modelTag.className = 'tag tag-info';
                modelTag.textContent = config.model;
                header.appendChild(modelTag);
            }
            if (config.provider) {
                const provTag = document.createElement('span');
                provTag.className = 'tag';
                provTag.style.cssText = 'background:rgba(160,160,176,0.15);color:var(--text-secondary);';
                provTag.textContent = config.provider;
                header.appendChild(provTag);
            }
        }

        if (agent.agent_type) {
            const typeTag = document.createElement('span');
            typeTag.className = 'tag';
            typeTag.style.cssText = 'background:rgba(160,160,176,0.1);color:var(--text-muted);';
            typeTag.textContent = agent.agent_type;
            header.appendChild(typeTag);
        }

        return header;
    }

    _buildAgentConfigSection(agentConfig) {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'background:rgba(79,195,247,0.05);border:1px solid var(--border-color);border-radius:6px;padding:12px;margin-bottom:12px;flex-shrink:0;';

        // Description
        if (agentConfig.description) {
            const descLabel = document.createElement('div');
            descLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            descLabel.textContent = 'Description';
            wrapper.appendChild(descLabel);

            const descText = document.createElement('div');
            descText.style.cssText = 'font-size:13px;color:var(--text-primary);line-height:1.5;margin-bottom:12px;';
            descText.textContent = agentConfig.description;
            wrapper.appendChild(descText);
        }

        // Key parameters grid
        const params = [];
        if (agentConfig.temperature != null) params.push({ label: 'Temperature', value: agentConfig.temperature });
        if (agentConfig.max_tokens != null) params.push({ label: 'Max Tokens', value: agentConfig.max_tokens });
        if (agentConfig.top_p != null) params.push({ label: 'Top P', value: agentConfig.top_p });
        if (agentConfig.max_iterations != null) params.push({ label: 'Max Iterations', value: agentConfig.max_iterations });
        if (agentConfig.timeout_seconds != null) params.push({ label: 'Timeout', value: `${agentConfig.timeout_seconds}s` });

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

        // Tools
        if (agentConfig.tools && agentConfig.tools.length > 0) {
            const toolsLabel = document.createElement('div');
            toolsLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            toolsLabel.textContent = 'Available Tools';
            wrapper.appendChild(toolsLabel);

            const toolsContainer = document.createElement('div');
            toolsContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;';

            for (const tool of agentConfig.tools.slice(0, 10)) {
                const toolName = typeof tool === 'string' ? tool : (tool.name || tool.tool_name || 'Unknown');
                const tag = document.createElement('span');
                tag.className = 'tag';
                tag.style.cssText = 'background:rgba(79,195,247,0.15);color:var(--accent);font-size:11px;';
                tag.textContent = toolName;
                toolsContainer.appendChild(tag);
            }

            if (agentConfig.tools.length > 10) {
                const more = document.createElement('span');
                more.style.cssText = 'font-size:11px;color:var(--text-muted);';
                more.textContent = `+${agentConfig.tools.length - 10} more`;
                toolsContainer.appendChild(more);
            }

            wrapper.appendChild(toolsContainer);
        }

        // Expected inputs
        if (agentConfig.expected_inputs && agentConfig.expected_inputs.length > 0) {
            const inputLabel = document.createElement('div');
            inputLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            inputLabel.textContent = 'Expected Inputs';
            wrapper.appendChild(inputLabel);

            const inputContainer = document.createElement('div');
            inputContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;';

            for (const field of agentConfig.expected_inputs) {
                const tag = document.createElement('span');
                tag.style.cssText = 'font-family:var(--font-mono);font-size:11px;background:rgba(79,195,247,0.1);color:var(--accent);padding:2px 8px;border-radius:3px;';
                tag.textContent = field;
                inputContainer.appendChild(tag);
            }
            wrapper.appendChild(inputContainer);
        }

        // Expected outputs
        if (agentConfig.expected_outputs && agentConfig.expected_outputs.length > 0) {
            const outputLabel = document.createElement('div');
            outputLabel.style.cssText = 'font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;';
            outputLabel.textContent = 'Expected Outputs';
            wrapper.appendChild(outputLabel);

            const outputContainer = document.createElement('div');
            outputContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;';

            for (const field of agentConfig.expected_outputs) {
                const tag = document.createElement('span');
                tag.style.cssText = 'font-family:var(--font-mono);font-size:11px;background:rgba(52,199,89,0.1);color:var(--success);padding:2px 8px;border-radius:3px;';
                tag.textContent = field;
                outputContainer.appendChild(tag);
            }
            wrapper.appendChild(outputContainer);
        }

        return wrapper;
    }

    _buildMetrics(agent) {
        const row = document.createElement('div');
        row.className = 'metrics-row';
        row.style.cssText = 'margin-bottom:8px;flex-shrink:0;';

        const metrics = [
            { label: 'Prompt Tok', value: formatTokens(agent.prompt_tokens) },
            { label: 'Compl Tok', value: formatTokens(agent.completion_tokens) },
            { label: 'Cost', value: formatCost(agent.estimated_cost_usd) },
            { label: 'Duration', value: formatDuration(agent.duration_seconds) },
            { label: 'LLM Calls', value: agent.num_llm_calls != null ? agent.num_llm_calls : (agent.llm_calls || []).length },
            { label: 'Tool Calls', value: agent.num_tool_calls != null ? agent.num_tool_calls : (agent.tool_calls || []).length },
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

    _buildTokenBar(agent) {
        const wrapper = document.createElement('div');
        wrapper.style.marginBottom = '8px';

        const labelRow = document.createElement('div');
        labelRow.style.cssText = 'display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:2px;';

        const promptLabel = document.createElement('span');
        promptLabel.textContent = `Prompt: ${formatTokens(agent.prompt_tokens)}`;
        const compLabel = document.createElement('span');
        compLabel.textContent = `Completion: ${formatTokens(agent.completion_tokens)}`;

        labelRow.appendChild(promptLabel);
        labelRow.appendChild(compLabel);
        wrapper.appendChild(labelRow);

        const bar = document.createElement('div');
        bar.className = 'token-bar';

        const total = (agent.prompt_tokens || 0) + (agent.completion_tokens || 0);
        if (total > 0) {
            const inputPct = ((agent.prompt_tokens || 0) / total * 100).toFixed(1);
            const outputPct = ((agent.completion_tokens || 0) / total * 100).toFixed(1);

            const inputBar = document.createElement('div');
            inputBar.className = 'token-input';
            inputBar.style.width = `${inputPct}%`;

            const outputBar = document.createElement('div');
            outputBar.className = 'token-output';
            outputBar.style.width = `${outputPct}%`;

            bar.appendChild(inputBar);
            bar.appendChild(outputBar);
        }

        wrapper.appendChild(bar);
        return wrapper;
    }

    _buildConfidence(score) {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'margin-bottom:8px;display:flex;align-items:center;gap:8px;';

        const label = document.createElement('span');
        label.style.cssText = 'font-size:12px;color:var(--text-secondary);';
        label.textContent = 'Confidence:';

        const value = document.createElement('span');
        value.style.cssText = 'font-size:16px;font-weight:600;font-family:var(--font-mono);';

        let color;
        if (score > 0.7) color = 'var(--success)';
        else if (score >= 0.5) color = 'var(--warning)';
        else color = 'var(--error)';

        value.style.color = color;
        value.textContent = score.toFixed(2);

        wrapper.appendChild(label);
        wrapper.appendChild(value);
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
        // Extract markdown string from {output: "..."} or JSON string '{"output": "..."}'
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
            // Fallback: show raw data
            const pre = document.createElement('div');
            pre.className = 'prompt-text';
            pre.textContent = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);
            display.appendChild(pre);
        }
        return display;
    }

    _buildTextDisplay(data) {
        const display = document.createElement('div');
        display.className = 'prompt-display';

        const raw = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);

        // Render as markdown if marked + DOMPurify are available and content looks like text
        if (typeof data === 'string' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const md = document.createElement('div');
            md.className = 'markdown-content';
            md.innerHTML = sanitizeAndParse(raw);
            display.appendChild(md);
        } else {
            const text = document.createElement('div');
            text.className = 'prompt-text';
            text.textContent = raw;
            display.appendChild(text);
        }

        return display;
    }

    _buildCallSection(title, calls, type) {
        const section = document.createElement('div');
        section.style.marginTop = '8px';

        const heading = document.createElement('div');
        heading.style.cssText = 'font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;';
        heading.textContent = title;
        section.appendChild(heading);

        const list = document.createElement('div');
        list.className = 'call-list';

        for (const call of calls) {
            const item = document.createElement('div');
            item.className = `call-item ${type === 'llm' ? 'llm-call' : 'tool-call'}`;

            const selectedId = type === 'llm'
                ? this.dataStore.selectedLLMCallId
                : this.dataStore.selectedToolCallId;
            if (call.id === selectedId) {
                item.classList.add('selected');
            }

            const nameSpan = document.createElement('span');
            nameSpan.className = 'call-name';
            if (type === 'llm') {
                const parts = [call.provider, call.model].filter(Boolean);
                nameSpan.textContent = parts.length > 0 ? parts.join('/') : 'LLM Call';
            } else {
                nameSpan.textContent = call.tool_name || 'Tool Call';
            }

            item.appendChild(nameSpan);

            if (type === 'llm') {
                const tokSpan = document.createElement('span');
                tokSpan.className = 'call-tokens';
                tokSpan.textContent = formatTokens(call.total_tokens);
                item.appendChild(tokSpan);

                const durSpan = document.createElement('span');
                durSpan.className = 'call-duration';
                durSpan.textContent = formatLatencyMs(call.latency_ms);
                item.appendChild(durSpan);

                if (call.status) {
                    const statusTag = document.createElement('span');
                    statusTag.className = `tag ${call.status === 'success' ? 'tag-success' : call.status === 'failed' ? 'tag-error' : 'tag-info'}`;
                    statusTag.textContent = call.status;
                    item.appendChild(statusTag);
                }
            } else {
                const durSpan = document.createElement('span');
                durSpan.className = 'call-duration';
                durSpan.textContent = formatDuration(call.duration_seconds);
                item.appendChild(durSpan);

                if (call.status) {
                    const statusTag = document.createElement('span');
                    statusTag.className = `tag ${call.status === 'success' || call.status === 'completed' ? 'tag-success' : call.status === 'failed' ? 'tag-error' : 'tag-info'}`;
                    statusTag.textContent = call.status;
                    item.appendChild(statusTag);
                }
            }

            item.addEventListener('click', () => {
                if (type === 'llm') {
                    this.dataStore.select('llmCall', call.id);
                } else {
                    this.dataStore.select('toolCall', call.id);
                }
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
