/**
 * MAF Dashboard — Entry point.
 * Initializes data store, WebSocket, panel registry, and wires everything together.
 */
import { DataStore, ensureUTCString } from './data-store.js';
import { WebSocketClient } from './websocket-client.js';
import { PanelRegistry } from './panel-registry.js';
import { ClientEventBus } from './event-bus.js';

document.addEventListener('DOMContentLoaded', async () => {
    // Parse workflow_id from URL
    const params = new URLSearchParams(window.location.search);
    const workflowId = params.get('workflow_id');

    if (!workflowId) {
        window.location.href = 'list.html';
        return;
    }

    // Initialize core infrastructure
    const dataStore = new DataStore();
    const eventBus = new ClientEventBus();
    const registry = new PanelRegistry(dataStore, eventBus);

    // Update header on data changes
    dataStore.addEventListener('change', (e) => {
        updateHeader(dataStore);
        updateEventLog(e.detail, dataStore);
    });

    // Connection status indicator
    const connStatus = document.getElementById('connection-status');

    // Try REST API first for initial data
    try {
        const resp = await fetch(`/api/workflows/${workflowId}`);
        if (resp.ok) {
            const workflow = await resp.json();
            dataStore.applySnapshot(workflow);
        }
    } catch (err) {
        console.warn('Failed to fetch initial data:', err);
    }

    // Connect WebSocket for live updates
    const wsClient = new WebSocketClient(workflowId, dataStore);
    wsClient.onStatusChange = (connected) => {
        connStatus.textContent = connected ? 'Connected' : 'Reconnecting...';
        connStatus.className = 'connection-indicator ' +
            (connected ? 'connected' : 'disconnected');
    };
    wsClient.connect();

    // --- View tab switching ---
    document.querySelectorAll('.viz-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.viz-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.viz-view').forEach(v => v.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById('panel-' + tab.dataset.view);
            if (target) target.classList.add('active');

            // Re-render panels when their tab becomes visible
            if (tab.dataset.view === 'flowchart') {
                const fp = registry.panels.get('flowchart');
                if (fp) fp.refresh();
            }
            if (tab.dataset.view === 'timeline') {
                const tp = registry.panels.get('timeline');
                if (tp && tp.refresh) tp.refresh();
            }
            if (tab.dataset.view === 'debate-rounds') {
                const dp = registry.panels.get('debate-rounds');
                if (dp && dp.refresh) dp.refresh();
            }
        });
    });

    // Register panels (panels imported dynamically when available)
    try {
        const { WorkflowOverviewPanel } = await import('./panels/workflow-overview.js');
        registry.register(WorkflowOverviewPanel, 'panel-workflow-overview');
    } catch (e) { console.debug('WorkflowOverviewPanel not yet available'); }

    try {
        const { TimelinePanel } = await import('./panels/timeline.js');
        registry.register(TimelinePanel, 'panel-timeline');
    } catch (e) { console.debug('TimelinePanel not yet available'); }

    try {
        const { FlowchartPanel } = await import('./panels/flowchart.js');
        registry.register(FlowchartPanel, 'panel-flowchart');
    } catch (e) { console.debug('FlowchartPanel not yet available'); }

    try {
        const { DebateRoundsPanel } = await import('./panels/debate-rounds.js');
        registry.register(DebateRoundsPanel, 'panel-debate-rounds');
    } catch (e) { console.debug('DebateRoundsPanel not yet available'); }

    try {
        const { StageDetailPanel } = await import('./panels/stage-detail.js');
        registry.register(StageDetailPanel, 'panel-stage-detail');
    } catch (e) { console.debug('StageDetailPanel not yet available'); }

    try {
        const { AgentDetailPanel } = await import('./panels/agent-detail.js');
        registry.register(AgentDetailPanel, 'panel-agent-detail');
    } catch (e) { console.debug('AgentDetailPanel not yet available'); }

    try {
        const { LLMInspectorPanel } = await import('./panels/llm-inspector.js');
        registry.register(LLMInspectorPanel, 'panel-llm-inspector');
    } catch (e) { console.debug('LLMInspectorPanel not yet available'); }

    // --- Detail overlay management ---
    const overlay = document.getElementById('detail-overlay');
    const backdrop = document.getElementById('detail-backdrop');
    const overlayClose = document.getElementById('detail-overlay-close');
    const overlayTitle = document.getElementById('detail-overlay-title');

    const panelMap = {
        stage: 'panel-stage-detail',
        agent: 'panel-agent-detail',
        llmCall: 'panel-llm-inspector',
        toolCall: 'panel-llm-inspector',
    };
    const titleMap = {
        stage: 'Stage Detail',
        agent: 'Agent Detail',
        llmCall: 'LLM Inspector',
        toolCall: 'Tool Inspector',
    };

    function showDetailOverlay(type) {
        // Hide all detail panels
        overlay.querySelectorAll('.detail-panel').forEach(p => {
            p.classList.remove('visible');
            p.classList.add('hidden');
        });

        // Show the matching panel
        const panelId = panelMap[type];
        if (panelId) {
            const panel = document.getElementById(panelId);
            if (panel) {
                panel.classList.remove('hidden');
                panel.classList.add('visible');
            }
        }

        overlayTitle.textContent = titleMap[type] || 'Details';
        overlay.classList.remove('hidden');
        backdrop.classList.remove('hidden');

        // Trigger transition on next frame
        requestAnimationFrame(() => {
            overlay.classList.add('visible');
            backdrop.classList.add('visible');
        });
    }

    function hideDetailOverlay() {
        overlay.classList.remove('visible');
        backdrop.classList.remove('visible');
        setTimeout(() => {
            overlay.classList.add('hidden');
            backdrop.classList.add('hidden');
        }, 250);
    }

    overlayClose.addEventListener('click', () => dataStore.clearSelection());
    backdrop.addEventListener('click', () => dataStore.clearSelection());
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlay.classList.contains('hidden')) {
            dataStore.clearSelection();
        }
    });

    dataStore.addEventListener('change', (e) => {
        if (e.detail?.changeType !== 'selection') return;
        const { type, id } = e.detail;
        if (!type || !id) {
            hideDetailOverlay();
        } else {
            showDetailOverlay(type);
        }
    });

    // --- Streaming button management (multi-agent) ---
    const streamingBtns = document.getElementById('streaming-btns');

    function onStreamingBtnClick(agentId) {
        dataStore.selectedAgentId = agentId;
        showDetailOverlay('llmCall');
        dataStore._notify('stream');
    }

    dataStore.addEventListener('change', (e) => {
        if (e.detail?.changeType !== 'stream') return;
        updateStreamingBtns(dataStore);
    });

    function updateStreamingBtns(ds) {
        // Collect currently active agent IDs
        const activeIds = new Set();
        for (const [agentId, entry] of ds.streamingContent) {
            if (!entry.done) activeIds.add(agentId);
        }

        // Remove buttons for agents that are no longer streaming
        for (const btn of [...streamingBtns.children]) {
            if (!activeIds.has(btn.dataset.agentId)) {
                btn.remove();
            }
        }

        // Add buttons for new streaming agents (skip if already present)
        const existing = new Set(
            [...streamingBtns.children].map(b => b.dataset.agentId)
        );
        for (const agentId of activeIds) {
            if (existing.has(agentId)) continue;
            const agentData = ds.agents.get(agentId);
            const agentName = agentData?.agent_name || agentData?.name || 'Agent';
            const btn = document.createElement('button');
            btn.className = 'streaming-btn';
            btn.dataset.agentId = agentId;
            btn.title = 'View LLM stream — ' + agentName;
            btn.innerHTML = '<span class="streaming-dot"></span><span>' + agentName + '</span>';
            btn.addEventListener('click', () => onStreamingBtnClick(agentId));
            streamingBtns.appendChild(btn);
        }
    }
});

function updateHeader(dataStore) {
    const wf = dataStore.workflow;
    if (!wf) return;

    document.getElementById('workflow-name').textContent = wf.workflow_name || '';

    const statusEl = document.getElementById('workflow-status');
    statusEl.textContent = wf.status || '';
    statusEl.className = 'status-badge ' + (wf.status || '');

    const durEl = document.getElementById('workflow-duration');
    if (wf.duration_seconds) {
        durEl.textContent = formatDuration(wf.duration_seconds);
    } else if (wf.start_time && wf.status === 'running') {
        const start = new Date(ensureUTCString(wf.start_time));
        const elapsed = (Date.now() - start.getTime()) / 1000;
        durEl.textContent = formatDuration(elapsed);
    }
}

function updateEventLog(detail, dataStore) {
    if (detail?.changeType === 'snapshot') {
        populateEventLogFromSnapshot(dataStore);
        return;
    }
    if (detail?.changeType !== 'event') return;
    const container = document.getElementById('event-log-entries');
    if (!container) return;

    const event = detail;
    container.prepend(createEventEntry(
        event.timestamp || Date.now(),
        event.event_type || event.changeType,
        event.label || ''
    ));

    // Limit entries
    while (container.children.length > 200) {
        container.removeChild(container.lastChild);
    }
}

function populateEventLogFromSnapshot(dataStore) {
    const container = document.getElementById('event-log-entries');
    if (!container) return;

    const entries = [];

    // Stages
    for (const stage of dataStore.stages.values()) {
        const name = stage.stage_name || stage.name || 'Stage';
        if (stage.start_time) {
            entries.push({ timestamp: stage.start_time, event_type: 'stage_start', label: name });
        }
        if (stage.end_time) {
            const suffix = stage.status ? ` (${stage.status})` : '';
            entries.push({ timestamp: stage.end_time, event_type: 'stage_end', label: name + suffix });
        }

        // Collaboration events on stage
        for (const evt of (stage.collaboration_events || [])) {
            const agents = (evt.agents_involved || []).join(', ');
            entries.push({
                timestamp: evt.timestamp,
                event_type: evt.event_type || 'collaboration',
                label: agents
            });
        }
    }

    // Agents
    for (const agent of dataStore.agents.values()) {
        const name = agent.agent_name || agent.name || 'Agent';
        if (agent.start_time) {
            entries.push({ timestamp: agent.start_time, event_type: 'agent_start', label: name });
        }
        if (agent.end_time) {
            const suffix = agent.status ? ` (${agent.status})` : '';
            entries.push({ timestamp: agent.end_time, event_type: 'agent_end', label: name + suffix });
        }
    }

    // LLM calls
    for (const llm of dataStore.llmCalls.values()) {
        const parts = [llm.provider, llm.model].filter(Boolean);
        const label = parts.length > 0 ? parts.join('/') : 'LLM Call';
        if (llm.start_time) {
            entries.push({ timestamp: llm.start_time, event_type: 'llm_call', label });
        }
    }

    // Tool calls
    for (const tool of dataStore.toolCalls.values()) {
        const label = tool.tool_name || 'Tool Call';
        if (tool.start_time) {
            entries.push({ timestamp: tool.start_time, event_type: 'tool_call', label });
        }
    }

    // Filter out entries without valid timestamps, sort chronologically
    const sorted = entries
        .filter(e => e.timestamp)
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    // Render: newest at top
    container.innerHTML = '';
    for (let i = sorted.length - 1; i >= 0; i--) {
        const e = sorted[i];
        container.appendChild(createEventEntry(e.timestamp, e.event_type, e.label));
    }
}

function createEventEntry(timestamp, eventType, label) {
    const entry = document.createElement('div');
    entry.className = 'event-entry';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'event-time';
    timeSpan.textContent = new Date(ensureUTCString(timestamp)).toLocaleTimeString();

    const typeSpan = document.createElement('span');
    typeSpan.className = 'event-type';
    typeSpan.textContent = eventType;

    entry.appendChild(timeSpan);
    entry.appendChild(typeSpan);

    if (label) {
        const labelSpan = document.createElement('span');
        labelSpan.className = 'event-label';
        labelSpan.textContent = label;
        entry.appendChild(labelSpan);
    }

    return entry;
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}
