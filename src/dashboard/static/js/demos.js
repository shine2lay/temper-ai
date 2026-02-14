/**
 * MAF Demo Execution Interface
 * Handles demo selection, input loading, and workflow execution.
 *
 * API Integration:
 * - GET /api/workflows/available → {workflows: [{path, name, description, ...}], total}
 * - POST /api/runs → {execution_id, status, message}
 * - GET /api/runs/{id} → execution status
 */

document.addEventListener('DOMContentLoaded', () => {
    // State management
    const state = {
        demos: [],
        selectedDemo: null,
        loading: false,
        executing: false,
        error: null,
    };

    // DOM elements
    const demoSelector = document.getElementById('demo-selector');
    const demoDescription = document.getElementById('demo-description');
    const inputConfig = document.getElementById('input-config');
    const runWorkflowBtn = document.getElementById('run-workflow-btn');
    const statusPanel = document.getElementById('status-panel');
    const statusMessage = document.getElementById('status-message');
    const errorContainer = document.getElementById('error-container');

    // Initialize
    init();

    // ---- Initialization ----

    async function init() {
        try {
            await fetchDemos();
            renderDemoSelect();
            attachEventListeners();
        } catch (err) {
            showError(`Failed to initialize: ${err.message}`);
        }
    }

    function attachEventListeners() {
        if (demoSelector) {
            demoSelector.addEventListener('change', handleDemoChange);
        }
        if (runWorkflowBtn) {
            runWorkflowBtn.addEventListener('click', handleExecute);
        }
    }

    // ---- API: Fetch available demos ----

    async function fetchDemos() {
        state.loading = true;
        state.error = null;

        try {
            const resp = await fetch('/api/workflows/available');
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            }

            const data = await resp.json();

            // API returns {workflows: [...], total: N}
            state.demos = data.workflows || [];

            state.loading = false;
            clearError();
        } catch (err) {
            state.loading = false;
            state.error = err.message;
            state.demos = [];
            showError(`Failed to load demos: ${err.message}`);
        }
    }

    // ---- API: Execute workflow ----

    async function executeWorkflow() {
        if (!state.selectedDemo) {
            showError('Please select a demo first.');
            return;
        }

        // Parse input from editor (sanitize control characters first)
        let inputData;
        try {
            let inputText = inputConfig ? inputConfig.value.trim() : '';
            if (inputText) {
                // Replace literal newlines/tabs inside JSON string values with spaces
                inputText = inputText.replace(/[\n\r\t]/g, ' ').replace(/ +/g, ' ');
                inputData = JSON.parse(inputText);
            } else {
                inputData = {};
            }
        } catch (err) {
            showError(`Invalid JSON input: ${err.message}`);
            return;
        }

        state.executing = true;
        renderExecuteButton();
        showStatus('Starting workflow execution...', 'info');
        showStatusPanel(true);

        try {
            const resp = await fetch('/api/runs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    workflow: state.selectedDemo.path,
                    inputs: inputData,
                }),
            });

            if (!resp.ok) {
                const errorData = await resp.json().catch(() => ({}));
                const errorMsg = errorData.detail || errorData.message || resp.statusText;
                throw new Error(`HTTP ${resp.status}: ${errorMsg}`);
            }

            const result = await resp.json();

            if (!result.execution_id) {
                throw new Error('Server did not return an execution ID.');
            }

            showStatus(
                `Workflow started! Waiting for workflow to initialize...`,
                'info'
            );

            // Poll for workflow_id, then redirect to detail page
            await pollAndRedirect(result.execution_id);

        } catch (err) {
            state.executing = false;
            renderExecuteButton();
            showError(`Execution failed: ${err.message}`);
            showStatus('', 'error');
        }
    }

    // ---- Execution Polling ----

    async function pollAndRedirect(executionId) {
        const POLL_INTERVAL_MS = 500;
        const MAX_ATTEMPTS = 30; // 15 seconds max

        for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
            try {
                const resp = await fetch(`/api/runs/${executionId}`);
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}`);
                }

                const data = await resp.json();

                if (data.workflow_id) {
                    // workflow_id available — redirect to detail page
                    window.location.href = `index.html?workflow_id=${data.workflow_id}`;
                    return;
                }

                if (data.status === 'failed' || data.status === 'cancelled') {
                    state.executing = false;
                    renderExecuteButton();
                    showStatus(
                        `Workflow ${data.status}: ${data.error_message || 'Unknown error'}`,
                        'error'
                    );
                    return;
                }
            } catch (err) {
                // Transient fetch error — keep polling
            }

            await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
        }

        // Timed out waiting for workflow_id — fall back to list page
        state.executing = false;
        renderExecuteButton();
        showStatus(
            `Workflow started but took too long to initialize.<br><a href="list.html" class="execution-link">View Workflows</a>`,
            'info'
        );
    }

    // ---- Event Handlers ----

    function handleDemoChange(event) {
        const demoPath = event.target.value;

        if (!demoPath) {
            state.selectedDemo = null;
            renderDemoDetails();
            renderInput();
            renderExecuteButton();
            return;
        }

        const demo = state.demos.find(d => d.path === demoPath);
        state.selectedDemo = demo;

        renderDemoDetails();
        renderInput();
        renderExecuteButton();
    }

    async function handleExecute(event) {
        event.preventDefault();
        if (state.executing) return;
        await executeWorkflow();
    }

    // ---- Rendering Functions ----

    function renderDemoSelect() {
        if (!demoSelector) return;

        demoSelector.innerHTML = '<option value="">-- Select a demo workflow --</option>';

        for (const demo of state.demos) {
            const option = document.createElement('option');
            option.value = demo.path;
            option.textContent = demo.name || demo.path;
            demoSelector.appendChild(option);
        }

        demoSelector.disabled = state.demos.length === 0;

        if (state.demos.length === 0) {
            demoSelector.innerHTML = '<option value="">No demos available</option>';
        }
    }

    function renderDemoDetails() {
        if (!demoDescription) return;

        if (!state.selectedDemo) {
            demoDescription.innerHTML = '';
            demoDescription.classList.add('hidden');
            return;
        }

        const demo = state.selectedDemo;
        demoDescription.classList.remove('hidden');

        let html = `<h4>${demo.name || 'Demo Workflow'}</h4>`;
        html += `<p>${demo.description || 'No description available.'}</p>`;

        // Metadata
        if (demo.version || demo.tags?.length > 0) {
            html += '<div class="demo-meta">';

            if (demo.version) {
                html += `<div class="demo-meta-item"><strong>Version:</strong> <span>${demo.version}</span></div>`;
            }

            html += '</div>';
        }

        // Tags
        if (demo.tags && demo.tags.length > 0) {
            html += '<div class="demo-tags">';
            for (const tag of demo.tags) {
                html += `<span class="demo-tag">${tag}</span>`;
            }
            html += '</div>';
        }

        demoDescription.innerHTML = html;
    }

    function renderInput() {
        if (!inputConfig) return;

        if (state.selectedDemo && state.selectedDemo.inputs) {
            // Pre-populate with example input structure based on required inputs
            const exampleInput = {};
            const inputs = state.selectedDemo.inputs;

            if (inputs.required && inputs.required.length > 0) {
                for (const key of inputs.required) {
                    exampleInput[key] = `<${key}>`;
                }
            }

            inputConfig.value = JSON.stringify(exampleInput, null, 2);
        } else {
            inputConfig.value = '{}';
        }
    }

    function renderExecuteButton() {
        if (!runWorkflowBtn) return;

        runWorkflowBtn.disabled = !state.selectedDemo || state.executing;
        runWorkflowBtn.textContent = state.executing ? 'Running...' : 'Run Workflow';

        if (state.executing) {
            runWorkflowBtn.classList.add('loading');
        } else {
            runWorkflowBtn.classList.remove('loading');
        }
    }

    // ---- Status and Error Messages ----

    function showStatusPanel(show) {
        if (!statusPanel) return;
        if (show) {
            statusPanel.classList.remove('hidden');
        } else {
            statusPanel.classList.add('hidden');
        }
    }

    function showStatus(message, type = 'info') {
        if (!statusMessage) return;

        statusMessage.innerHTML = message;
        statusMessage.className = `status-${type}`;
    }

    function showError(message) {
        if (!errorContainer) return;

        errorContainer.innerHTML = '';

        const banner = document.createElement('div');
        banner.className = 'error-banner';
        banner.textContent = message;

        errorContainer.appendChild(banner);

        // Auto-hide after 10 seconds
        setTimeout(clearError, 10000);
    }

    function clearError() {
        if (!errorContainer) return;
        errorContainer.innerHTML = '';
    }
});
