/**
 * Flowchart HTML overlay templates for cytoscape-node-html-label.
 * Pure functions returning HTML strings from Cytoscape node data() objects.
 */

/** HTML-escape user-controlled strings to prevent XSS. */
export function esc(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Format token count: 1234 → "1.2K", null → "--" */
export function fmtTokens(count) {
    if (count == null) return '--';
    if (count >= 1000) return (count / 1000).toFixed(1) + 'K';
    return String(count);
}

/** Format duration: 12.3 → "12.3s", 90 → "1m 30s" */
export function fmtDuration(seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return seconds.toFixed(1) + 's';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

/** Format cost: 0.0123 → "$0.0123" */
export function fmtCost(usd) {
    if (usd == null || usd <= 0) return '--';
    return '$' + usd.toFixed(4);
}

/** Map status → CSS dot class */
function dotClass(status) {
    const s = (status || 'pending').toLowerCase();
    const valid = ['completed', 'running', 'failed', 'pending', 'halted', 'timeout'];
    return 'fc-dot-' + (valid.includes(s) ? s : 'pending');
}

/** Map strategy name → badge CSS class */
function badgeClass(strategy) {
    if (!strategy) return '';
    const s = strategy.toLowerCase();
    if (s.includes('debate'))    return 'fc-badge-debate';
    if (s.includes('dialogue'))  return 'fc-badge-dialogue';
    if (s.includes('parallel'))  return 'fc-badge-parallel';
    return 'fc-badge-sequential';
}

/**
 * Stage header HTML overlay.
 * @param {object} data - Cytoscape node data() for a stage-header node
 */
export function stageHeaderTpl(data) {
    const status = data.status || 'pending';
    const name = esc(data.name);
    const strategy = data.strategy;
    const execMode = data.execMode;

    // Badge: prefer strategy, fall back to execMode
    const badgeText = strategy || execMode || '';
    const badgeHtml = badgeText
        ? `<span class="fc-stage-badge ${badgeClass(badgeText)}">${esc(badgeText)}</span>`
        : '';

    // Metrics row
    const parts = [];
    if (data.agentCount != null) parts.push(data.agentCount + 'a');
    if (data.totalTokens)        parts.push(fmtTokens(data.totalTokens) + ' tok');
    if (data.totalCost > 0)      parts.push(fmtCost(data.totalCost));
    if (data.durationSeconds)    parts.push(fmtDuration(data.durationSeconds));
    const metricsHtml = parts.length
        ? `<div class="fc-stage-metrics">${parts.join(' · ')}</div>`
        : '';

    // Tooltip rows (all values escaped for XSS safety)
    const tipRows = [];
    if (data.iterationCount > 1) tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Iterations</span><span class="fc-tip-val">${esc(data.iterationCount)}</span></div>`);
    if (data.numSucceeded != null) tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Succeeded</span><span class="fc-tip-val">${esc(data.numSucceeded)}</span></div>`);
    if (data.numFailed > 0)        tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Failed</span><span class="fc-tip-val">${esc(data.numFailed)}</span></div>`);
    if (data.collabRounds > 0)     tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Rounds</span><span class="fc-tip-val">${esc(data.collabRounds)}</span></div>`);
    if (data.totalTokens)          tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Tokens</span><span class="fc-tip-val">${esc(fmtTokens(data.totalTokens))}</span></div>`);
    if (data.totalCost > 0)        tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Cost</span><span class="fc-tip-val">${esc(fmtCost(data.totalCost))}</span></div>`);
    const tooltipHtml = tipRows.length
        ? `<div class="fc-tooltip">${tipRows.join('')}</div>`
        : '';

    const hoverClass = tooltipHtml ? ' fc-hoverable' : '';

    // Iteration badge for collapsed nodes with multiple executions
    const iterBadge = (data.iterationCount > 1)
        ? `<span class="fc-iteration-badge">x${data.iterationCount}</span>`
        : '';

    return `<div class="fc-stage-header${hoverClass}">` +
        `<div class="fc-stage-top"><span class="fc-stage-dot ${dotClass(status)}"></span><span class="fc-stage-name"${data.stageColor ? ` style="color:${data.stageColor}"` : ''}>${name}</span>${iterBadge}</div>` +
        badgeHtml +
        metricsHtml +
        tooltipHtml +
        `</div>`;
}

/**
 * Agent card HTML overlay.
 * @param {object} data - Cytoscape node data() for an agent node
 */
export function agentCardTpl(data) {
    const status = data.status || 'pending';
    const name = esc(data.agentName || data.name);
    const model = esc(data.model);

    // Model badge
    const modelHtml = model
        ? `<div class="fc-agent-model-badge">${model}</div>`
        : '';

    // Token mini-bar
    const prompt = data.promptTokens || 0;
    const completion = data.completionTokens || 0;
    const total = prompt + completion;
    let barHtml = '';
    if (total > 0) {
        const pPct = ((prompt / total) * 100).toFixed(1);
        const cPct = ((completion / total) * 100).toFixed(1);
        barHtml = `<div class="fc-token-bar"><div class="fc-token-prompt" style="width:${pPct}%"></div><div class="fc-token-completion" style="width:${cPct}%"></div></div>`;
    }

    // Bottom metrics
    const parts = [];
    if (data.durationSeconds) parts.push(fmtDuration(data.durationSeconds));
    if (data.numLlmCalls)     parts.push(data.numLlmCalls + ' llm');
    if (data.numToolCalls)    parts.push(data.numToolCalls + ' tool');
    const bottomHtml = parts.length
        ? `<div class="fc-agent-bottom">${parts.join(' · ')}</div>`
        : '';

    // Tooltip
    const tipRows = [];
    if (model)                       tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Model</span><span class="fc-tip-val">${model}</span></div>`);
    if (prompt)                      tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Prompt</span><span class="fc-tip-val">${esc(fmtTokens(prompt))}</span></div>`);
    if (completion)                  tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Completion</span><span class="fc-tip-val">${esc(fmtTokens(completion))}</span></div>`);
    if (data.estimatedCost > 0)      tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Cost</span><span class="fc-tip-val">${esc(fmtCost(data.estimatedCost))}</span></div>`);
    if (data.confidenceScore != null && !isNaN(data.confidenceScore)) tipRows.push(`<div class="fc-tip-row"><span class="fc-tip-key">Confidence</span><span class="fc-tip-val">${esc((Number(data.confidenceScore) * 100).toFixed(0))}%</span></div>`);
    const tooltipHtml = tipRows.length
        ? `<div class="fc-tooltip">${tipRows.join('')}</div>`
        : '';

    const hoverClass = tooltipHtml ? ' fc-hoverable' : '';

    return `<div class="fc-agent-card${hoverClass}">` +
        `<div class="fc-agent-top"><span class="fc-agent-dot ${dotClass(status)}"></span><span class="fc-agent-name">${name}</span></div>` +
        modelHtml +
        barHtml +
        bottomHtml +
        tooltipHtml +
        `</div>`;
}

/**
 * Truncate data-flow output keys for edge labels.
 * @param {string[]} outputKeys
 * @returns {string}
 */
export function formatDataFlowLabel(outputKeys) {
    if (!outputKeys || outputKeys.length === 0) return '';
    const MAX_KEYS = 3;
    const shown = outputKeys.slice(0, MAX_KEYS).join(', ');
    const extra = outputKeys.length - MAX_KEYS;
    return extra > 0 ? `${shown} +${extra} more` : shown;
}

/**
 * Format collaboration edge label with round count.
 * @param {string} eventType - e.g. "debate", "dialogue"
 * @param {number} roundCount - number of rounds/events aggregated
 * @returns {string}
 */
export function formatCollabLabel(eventType, roundCount) {
    const type = eventType || 'collab';
    if (roundCount > 1) return `${type} (${roundCount})`;
    return type;
}
