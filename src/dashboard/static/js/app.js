/**
 * MAF Dashboard — Entry point.
 * Initializes data store, WebSocket, panel registry, and wires everything together.
 */
import { DataStore } from './data-store.js';
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

            // Re-render flowchart when its tab becomes visible (Cytoscape
            // needs a visible container with non-zero dimensions to init)
            if (tab.dataset.view === 'flowchart') {
                const fp = registry.panels.get('flowchart');
                if (fp) {
                    fp.render();
                    if (fp._cy) { fp._cy.resize(); fp._cy.fit(); }
                }
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
        const { AgentDetailPanel } = await import('./panels/agent-detail.js');
        registry.register(AgentDetailPanel, 'panel-agent-detail');
    } catch (e) { console.debug('AgentDetailPanel not yet available'); }

    try {
        const { LLMInspectorPanel } = await import('./panels/llm-inspector.js');
        registry.register(LLMInspectorPanel, 'panel-llm-inspector');
    } catch (e) { console.debug('LLMInspectorPanel not yet available'); }
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
        const start = new Date(wf.start_time);
        const elapsed = (Date.now() - start.getTime()) / 1000;
        durEl.textContent = formatDuration(elapsed);
    }
}

function updateEventLog(detail, dataStore) {
    if (detail?.changeType !== 'event') return;
    const container = document.getElementById('event-log-entries');
    if (!container) return;

    const event = detail;
    const entry = document.createElement('div');
    entry.className = 'event-entry';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'event-time';
    timeSpan.textContent = new Date(event.timestamp || Date.now()).toLocaleTimeString();

    const typeSpan = document.createElement('span');
    typeSpan.className = 'event-type';
    typeSpan.textContent = event.event_type || event.changeType;

    entry.appendChild(timeSpan);
    entry.appendChild(typeSpan);
    container.prepend(entry);

    // Limit entries
    while (container.children.length > 100) {
        container.removeChild(container.lastChild);
    }
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}
