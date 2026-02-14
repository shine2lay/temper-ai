/**
 * LLM Inspector Panel — Shows selected LLM call prompt/response
 * or selected tool call details.
 * Dual-purpose: renders LLM call view or tool call view based on selection.
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

function formatTokens(count) {
    if (count == null) return '--';
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toLocaleString();
}

function formatCost(usd) {
    if (usd == null) return '--';
    if (usd < 0.001) return `$${usd.toFixed(6)}`;
    if (usd < 0.01) return `$${usd.toFixed(4)}`;
    return `$${usd.toFixed(4)}`;
}

function formatLatencyMs(ms) {
    if (ms == null) return '--';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function formatDuration(seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}

export class LLMInspectorPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._changeHandler = (e) => this._onDataChange(e.detail);
        this.dataStore.addEventListener('change', this._changeHandler);
        // Track last rendered streaming lengths for incremental updates
        this._streamLengths = new Map(); // agent_id -> {content, thinking}
        this.render();
    }

    static get metadata() {
        return { id: 'llm-inspector', title: 'LLM Inspector' };
    }

    _onDataChange(detail) {
        if (detail.changeType === 'stream') {
            this._updateStreamingDisplay();
            return;
        }
        if (detail.changeType === 'selection' || detail.changeType === 'snapshot') {
            this._renderWithFetch();
        }
        // LLM/tool call data doesn't change via events — no need to re-render on 'event'
    }

    async _renderWithFetch() {
        this.container.innerHTML = '';
        this.container.style.overflow = '';

        const llmCallId = this.dataStore.selectedLLMCallId;
        const toolCallId = this.dataStore.selectedToolCallId;

        if (llmCallId) {
            // Try API first for full prompt/response data
            let llmCall = await this._fetchData('llm-calls', llmCallId);
            if (llmCall) {
                const existing = this.dataStore.llmCalls.get(llmCallId);
                if (existing) Object.assign(existing, llmCall);
                else this.dataStore.llmCalls.set(llmCallId, llmCall);
            } else {
                llmCall = this.dataStore.llmCalls.get(llmCallId);
            }
            if (llmCall) {
                this._renderLLMCall(llmCall);
                return;
            }
        }

        if (toolCallId) {
            let toolCall = await this._fetchData('tool-calls', toolCallId);
            if (toolCall) {
                const existing = this.dataStore.toolCalls.get(toolCallId);
                if (existing) Object.assign(existing, toolCall);
                else this.dataStore.toolCalls.set(toolCallId, toolCall);
            } else {
                toolCall = this.dataStore.toolCalls.get(toolCallId);
            }
            if (toolCall) {
                this._renderToolCall(toolCall);
                return;
            }
        }

        this._renderEmptyState();
    }

    render() {
        this.container.innerHTML = '';
        this.container.style.overflow = '';

        const llmCallId = this.dataStore.selectedLLMCallId;
        const toolCallId = this.dataStore.selectedToolCallId;

        if (llmCallId) {
            const llmCall = this.dataStore.llmCalls.get(llmCallId);
            if (llmCall) { this._renderLLMCall(llmCall); return; }
        }
        if (toolCallId) {
            const toolCall = this.dataStore.toolCalls.get(toolCallId);
            if (toolCall) { this._renderToolCall(toolCall); return; }
        }
        this._renderEmptyState();
    }

    async _fetchData(type, id) {
        try {
            const resp = await fetch(`/api/${type}/${id}`);
            if (resp.ok) return await resp.json();
        } catch (err) {
            console.warn(`Failed to fetch ${type}/${id}:`, err);
        }
        return null;
    }

    _renderEmptyState(msg) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '\u{1F50D}';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = msg || 'Select an LLM call from the agent detail to inspect';

        empty.appendChild(icon);
        empty.appendChild(text);
        this.container.appendChild(empty);
    }

    // ---- LLM Call View ----

    _renderLLMCall(call) {
        // Header
        this.container.appendChild(this._buildLLMHeader(call));

        // Metadata row
        this.container.appendChild(this._buildLLMMetadata(call));

        // Token breakdown with bar
        this.container.appendChild(this._buildTokenBreakdown(call));

        // Prompt (main section)
        this.container.appendChild(this._buildPromptSection('Prompt', call.prompt));

        // Response (main section, rendered as markdown)
        this.container.appendChild(this._buildPromptSection('Response', call.response, true));

        // Error (if failed)
        if (call.status === 'failed' && call.error_message) {
            this.container.appendChild(this._buildErrorSection(call.error_message));
        }
    }

    _buildLLMHeader(call) {
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;';

        const title = document.createElement('span');
        title.style.cssText = 'font-size:16px;font-weight:600;';
        title.textContent = 'LLM Call';

        header.appendChild(title);

        if (call.model) {
            const modelTag = document.createElement('span');
            modelTag.className = 'tag tag-info';
            modelTag.textContent = call.model;
            header.appendChild(modelTag);
        }

        const statusBadge = document.createElement('span');
        statusBadge.className = `status-badge ${call.status === 'success' ? 'completed' : call.status === 'failed' ? 'failed' : 'running'}`;
        statusBadge.textContent = call.status || 'unknown';
        header.appendChild(statusBadge);

        return header;
    }

    _buildLLMMetadata(call) {
        const row = document.createElement('div');
        row.className = 'metrics-row';
        row.style.marginBottom = '8px';

        const items = [
            { label: 'Provider', value: call.provider || '--' },
            { label: 'Temperature', value: call.temperature != null ? call.temperature : '--' },
            { label: 'Max Tokens', value: call.max_tokens != null ? call.max_tokens.toLocaleString() : '--' },
            { label: 'Latency', value: formatLatencyMs(call.latency_ms) },
            { label: 'Cost', value: formatCost(call.estimated_cost_usd) },
        ];

        for (const item of items) {
            const card = document.createElement('div');
            card.className = 'metric-card';

            const val = document.createElement('div');
            val.className = 'metric-value';
            val.style.fontSize = '16px';
            val.textContent = item.value;

            const lbl = document.createElement('div');
            lbl.className = 'metric-label';
            lbl.textContent = item.label;

            card.appendChild(val);
            card.appendChild(lbl);
            row.appendChild(card);
        }

        return row;
    }

    _buildTokenBreakdown(call) {
        const wrapper = document.createElement('div');
        wrapper.style.marginBottom = '8px';

        const labelRow = document.createElement('div');
        labelRow.style.cssText = 'display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:2px;';

        const promptLabel = document.createElement('span');
        promptLabel.textContent = `Prompt: ${formatTokens(call.prompt_tokens)}`;

        const compLabel = document.createElement('span');
        compLabel.textContent = `Completion: ${formatTokens(call.completion_tokens)}`;

        const totalLabel = document.createElement('span');
        totalLabel.style.fontWeight = '600';
        totalLabel.textContent = `Total: ${formatTokens(call.total_tokens)}`;

        labelRow.appendChild(promptLabel);
        labelRow.appendChild(totalLabel);
        labelRow.appendChild(compLabel);
        wrapper.appendChild(labelRow);

        const bar = document.createElement('div');
        bar.className = 'token-bar';

        const total = (call.prompt_tokens || 0) + (call.completion_tokens || 0);
        if (total > 0) {
            const inputPct = ((call.prompt_tokens || 0) / total * 100).toFixed(1);
            const outputPct = ((call.completion_tokens || 0) / total * 100).toFixed(1);

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

    _buildPromptSection(label, content, useMarkdown = false) {
        const display = document.createElement('div');
        display.className = 'prompt-display';

        const headerRow = document.createElement('div');
        headerRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

        const lbl = document.createElement('div');
        lbl.className = 'prompt-label';
        lbl.textContent = label;
        headerRow.appendChild(lbl);

        // Copy button
        if (content != null) {
            const copyBtn = document.createElement('button');
            copyBtn.style.cssText = 'background:var(--bg-input);border:1px solid var(--border-color);border-radius:var(--radius-sm);color:var(--text-secondary);font-size:11px;padding:2px 8px;cursor:pointer;';
            copyBtn.textContent = 'Copy';
            copyBtn.addEventListener('click', () => {
                const raw = typeof content === 'object' ? JSON.stringify(content, null, 2) : String(content);
                navigator.clipboard.writeText(raw).then(() => {
                    copyBtn.textContent = 'Copied!';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
                }).catch(() => {
                    copyBtn.textContent = 'Failed';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
                });
            });
            headerRow.appendChild(copyBtn);
        }

        display.appendChild(headerRow);

        if (content == null) {
            const text = document.createElement('div');
            text.className = 'prompt-text';
            text.style.cssText = 'max-height:40vh;overflow-y:auto;';
            text.textContent = '(empty)';
            text.style.color = 'var(--text-muted)';
            text.style.fontStyle = 'italic';
            display.appendChild(text);
        } else if (useMarkdown && typeof content === 'string' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const md = document.createElement('div');
            md.className = 'markdown-content';
            md.style.cssText = 'max-height:40vh;overflow-y:auto;';
            md.innerHTML = sanitizeAndParse(content);
            display.appendChild(md);
        } else {
            const text = document.createElement('div');
            text.className = 'prompt-text';
            text.style.cssText = 'max-height:40vh;overflow-y:auto;';
            if (typeof content === 'object') {
                text.textContent = JSON.stringify(content, null, 2);
            } else {
                text.textContent = String(content);
            }
            display.appendChild(text);
        }

        return display;
    }

    _buildErrorSection(errorMessage) {
        const section = document.createElement('div');
        section.style.cssText = 'margin-top:8px;padding:8px 12px;background:rgba(239,83,80,0.1);border:1px solid var(--error);border-radius:var(--radius-sm);';

        const label = document.createElement('div');
        label.style.cssText = 'font-size:11px;font-weight:600;text-transform:uppercase;color:var(--error);margin-bottom:4px;';
        label.textContent = 'Error';
        section.appendChild(label);

        const msg = document.createElement('div');
        msg.style.cssText = 'font-family:var(--font-mono);font-size:12px;color:var(--error);white-space:pre-wrap;word-break:break-word;';
        msg.textContent = errorMessage;
        section.appendChild(msg);

        return section;
    }

    // ---- Tool Call View ----

    _renderToolCall(call) {
        // Header
        this.container.appendChild(this._buildToolHeader(call));

        // Metadata
        this.container.appendChild(this._buildToolMetadata(call));

        // Input Parameters
        if (call.input_params) {
            this.container.appendChild(this._buildCollapsible('Input Parameters', () => this._buildJsonViewer(call.input_params), false));
        }

        // Output Data
        if (call.output_data) {
            this.container.appendChild(this._buildCollapsible('Output Data', () => this._buildJsonViewer(call.output_data), false));
        }

        // Error (if failed)
        if ((call.status === 'failed' || call.status === 'error') && call.error_message) {
            this.container.appendChild(this._buildErrorSection(call.error_message));
        }
    }

    _buildToolHeader(call) {
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;';

        const title = document.createElement('span');
        title.style.cssText = 'font-size:16px;font-weight:600;';
        title.textContent = 'Tool Call';

        header.appendChild(title);

        if (call.tool_name) {
            const nameTag = document.createElement('span');
            nameTag.className = 'tag tag-warning';
            nameTag.textContent = call.tool_name;
            header.appendChild(nameTag);
        }

        const statusBadge = document.createElement('span');
        const statusClass = (call.status === 'success' || call.status === 'completed') ? 'completed' : call.status === 'failed' ? 'failed' : 'running';
        statusBadge.className = `status-badge ${statusClass}`;
        statusBadge.textContent = call.status || 'unknown';
        header.appendChild(statusBadge);

        return header;
    }

    _buildToolMetadata(call) {
        const row = document.createElement('div');
        row.className = 'metrics-row';
        row.style.marginBottom = '8px';

        const items = [
            { label: 'Duration', value: formatDuration(call.duration_seconds) },
            { label: 'Status', value: call.status || '--' },
        ];

        if (call.approval_required != null) {
            items.push({ label: 'Approval', value: call.approval_required ? 'Required' : 'Auto' });
        }
        if (call.safety_checks != null) {
            items.push({ label: 'Safety', value: call.safety_checks ? 'Passed' : 'Skipped' });
        }

        for (const item of items) {
            const card = document.createElement('div');
            card.className = 'metric-card';

            const val = document.createElement('div');
            val.className = 'metric-value';
            val.style.fontSize = '16px';
            val.textContent = item.value;

            const lbl = document.createElement('div');
            lbl.className = 'metric-label';
            lbl.textContent = item.label;

            card.appendChild(val);
            card.appendChild(lbl);
            row.appendChild(card);
        }

        return row;
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

    // ---- Streaming View ----

    _updateStreamingDisplay() {
        const agentId = this.dataStore.selectedAgentId;
        if (!agentId) return;

        const streamData = this.dataStore.streamingContent.get(agentId);
        if (!streamData) return;

        // If stream is done, transition to normal render
        if (streamData.done) {
            this._streamLengths.delete(agentId);
            this.render();
            return;
        }

        // Get or create streaming container
        let streamContainer = this.container.querySelector('.streaming-content');
        if (!streamContainer) {
            // First streaming update — build the streaming view
            this.container.innerHTML = '';
            this._renderStreamingView(agentId, streamData);
            return;
        }

        // Incremental DOM append
        const prev = this._streamLengths.get(agentId) || { content: 0, thinking: 0 };

        if (streamData.thinking.length > prev.thinking) {
            const thinkingEl = streamContainer.querySelector('.streaming-thinking');
            if (thinkingEl) {
                const newText = streamData.thinking.slice(prev.thinking);
                thinkingEl.appendChild(document.createTextNode(newText));
            }
        }

        if (streamData.content.length > prev.content) {
            const contentEl = streamContainer.querySelector('.streaming-text');
            if (contentEl) {
                const newText = streamData.content.slice(prev.content);
                contentEl.appendChild(document.createTextNode(newText));
            }
        }

        // Auto-scroll the container to bottom
        streamContainer.scrollTop = streamContainer.scrollHeight;

        this._streamLengths.set(agentId, {
            content: streamData.content.length,
            thinking: streamData.thinking.length
        });
    }

    _renderStreamingView(agentId, streamData) {
        // Override panel-content overflow so flex children control scrolling
        this.container.style.overflow = 'hidden';

        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-shrink:0;';

        const title = document.createElement('span');
        title.style.cssText = 'font-size:16px;font-weight:600;';
        title.textContent = 'LLM Streaming';
        header.appendChild(title);

        const badge = document.createElement('span');
        badge.className = 'status-badge running';
        badge.textContent = 'streaming';
        header.appendChild(badge);

        this.container.appendChild(header);

        const streamContainer = document.createElement('div');
        streamContainer.className = 'streaming-content';
        streamContainer.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;overflow-y:auto;background:var(--bg-input);border:1px solid var(--border-color);border-radius:var(--radius-sm);padding:8px 12px;';

        if (streamData.thinking) {
            const thinkingEl = document.createElement('div');
            thinkingEl.className = 'streaming-thinking';
            thinkingEl.style.cssText = 'color:var(--text-muted);font-style:italic;font-family:var(--font-mono);font-size:12px;white-space:pre-wrap;word-break:break-word;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--border-color);';
            thinkingEl.appendChild(document.createTextNode(streamData.thinking));
            streamContainer.appendChild(thinkingEl);
        }

        const contentEl = document.createElement('div');
        contentEl.className = 'streaming-text';
        contentEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word;color:var(--text-primary);';
        contentEl.appendChild(document.createTextNode(streamData.content));
        streamContainer.appendChild(contentEl);

        this.container.appendChild(streamContainer);

        // Auto-scroll to bottom on initial render
        streamContainer.scrollTop = streamContainer.scrollHeight;

        this._streamLengths.set(agentId, {
            content: streamData.content.length,
            thinking: streamData.thinking.length
        });
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
    }
}
