/**
 * Workflow List — fetches workflow summaries from REST API and renders
 * a filterable, paginated, clickable table.
 */

document.addEventListener('DOMContentLoaded', () => {
    const state = {
        workflows: [],
        filter: 'all',
        search: '',
        offset: 0,
        limit: 50,
        total: 0,
        loading: true,
        error: null,
    };

    const controlsEl = document.getElementById('list-controls');
    const tableContainer = document.getElementById('workflow-table-container');
    const paginationEl = document.getElementById('pagination-controls');
    const errorContainer = document.getElementById('error-container');

    buildControls();
    fetchWorkflows();

    // Auto-refresh when running workflows exist
    setInterval(() => {
        if (state.workflows.some(w => w.status === 'running')) {
            fetchWorkflows();
        }
    }, 5000);

    // ---- Data fetching ----

    async function fetchWorkflows() {
        state.loading = true;
        state.error = null;
        renderLoading();

        const params = new URLSearchParams({
            limit: String(state.limit),
            offset: String(state.offset),
        });
        if (state.filter !== 'all') {
            params.set('status', state.filter);
        }

        try {
            const resp = await fetch(`/api/workflows?${params}`);
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            }
            const data = await resp.json();

            if (Array.isArray(data)) {
                state.workflows = data;
                state.total = data.length;
            } else if (data && Array.isArray(data.workflows)) {
                state.workflows = data.workflows;
                state.total = typeof data.total === 'number' ? data.total : data.workflows.length;
            } else {
                state.workflows = [];
                state.total = 0;
            }

            state.loading = false;
            state.error = null;
            renderTable();
            renderPagination();
            renderError();
        } catch (err) {
            state.loading = false;
            state.error = err.message;
            state.workflows = [];
            renderError();
            renderTable();
            renderPagination();
        }
    }

    // ---- Controls ----

    function buildControls() {
        controlsEl.textContent = '';

        const filterGroup = document.createElement('div');
        filterGroup.className = 'filter-group';

        const filters = [
            { value: 'all', label: 'All' },
            { value: 'running', label: 'Running' },
            { value: 'completed', label: 'Completed' },
            { value: 'failed', label: 'Failed' },
        ];

        for (const f of filters) {
            const btn = document.createElement('button');
            btn.className = 'filter-btn' + (state.filter === f.value ? ' active' : '');
            btn.textContent = f.label;
            btn.type = 'button';
            btn.addEventListener('click', () => {
                state.filter = f.value;
                state.offset = 0;
                buildControls();
                fetchWorkflows();
            });
            filterGroup.appendChild(btn);
        }

        controlsEl.appendChild(filterGroup);

        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'search-input';
        searchInput.placeholder = 'Search workflow name...';
        searchInput.value = state.search;
        searchInput.addEventListener('input', (e) => {
            state.search = e.target.value.toLowerCase();
            renderTable();
        });
        controlsEl.appendChild(searchInput);
    }

    // ---- Error rendering ----

    function renderError() {
        errorContainer.textContent = '';
        if (!state.error) return;

        const banner = document.createElement('div');
        banner.className = 'error-banner';
        banner.textContent = `Failed to load workflows: ${state.error}`;
        errorContainer.appendChild(banner);
    }

    // ---- Loading ----

    function renderLoading() {
        const content = tableContainer.querySelector('.panel-content');
        if (!content) return;
        content.textContent = '';
        const spinner = document.createElement('div');
        spinner.className = 'loading-spinner';
        content.appendChild(spinner);
    }

    // ---- Table rendering ----

    function renderTable() {
        const content = tableContainer.querySelector('.panel-content');
        if (!content) return;
        content.textContent = '';

        const filtered = getFilteredWorkflows();

        if (state.loading) {
            const spinner = document.createElement('div');
            spinner.className = 'loading-spinner';
            content.appendChild(spinner);
            return;
        }

        if (filtered.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';

            const icon = document.createElement('div');
            icon.className = 'empty-icon';
            icon.textContent = '---';
            empty.appendChild(icon);

            const text = document.createElement('div');
            text.className = 'empty-text';
            text.textContent = state.search
                ? 'No workflows match your search.'
                : 'No workflow runs found.';
            empty.appendChild(text);

            const sub = document.createElement('div');
            sub.className = 'empty-subtext';
            sub.textContent = state.search
                ? 'Try a different search term or change the status filter.'
                : 'Run a workflow with "maf run" to see it here.';
            empty.appendChild(sub);

            content.appendChild(empty);
            return;
        }

        const table = document.createElement('table');
        table.className = 'data-table';

        // Header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        const columns = [
            'Status', 'Name', 'Started', 'Duration',
            'Tokens', 'Cost', 'LLM Calls', 'Tool Calls', 'Env',
        ];
        for (const col of columns) {
            const th = document.createElement('th');
            th.textContent = col;
            headerRow.appendChild(th);
        }
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Body
        const tbody = document.createElement('tbody');
        for (const wf of filtered) {
            const row = document.createElement('tr');
            row.addEventListener('click', () => {
                window.location.href = `index.html?workflow_id=${encodeURIComponent(wf.id)}`;
            });
            row.style.cursor = 'pointer';

            // Status
            appendCell(row, () => {
                const badge = document.createElement('span');
                badge.className = `status-badge ${wf.status || 'pending'}`;
                badge.textContent = wf.status || 'unknown';
                return badge;
            });

            // Name
            appendCell(row, () => {
                const span = document.createElement('span');
                span.className = 'workflow-name-cell';
                span.textContent = wf.workflow_name || wf.id;
                span.title = wf.workflow_name || wf.id;
                return span;
            });

            // Started
            appendTextCell(row, formatTime(wf.start_time), 'col-mono');

            // Duration
            appendTextCell(row, formatDuration(wf.duration_seconds), 'col-mono');

            // Tokens
            appendTextCell(row, formatTokens(wf.total_tokens), 'col-mono');

            // Cost
            appendTextCell(row, formatCost(wf.total_cost_usd), 'col-mono');

            // LLM Calls
            appendTextCell(row, wf.total_llm_calls != null ? String(wf.total_llm_calls) : '-', 'col-mono');

            // Tool Calls
            appendTextCell(row, wf.total_tool_calls != null ? String(wf.total_tool_calls) : '-', 'col-mono');

            // Environment
            appendCell(row, () => {
                if (!wf.environment) return document.createTextNode('-');
                const tag = document.createElement('span');
                tag.className = 'env-tag';
                tag.textContent = wf.environment;
                return tag;
            });

            tbody.appendChild(row);
        }

        table.appendChild(tbody);
        content.appendChild(table);
    }

    function appendCell(row, contentFn) {
        const td = document.createElement('td');
        td.appendChild(contentFn());
        row.appendChild(td);
    }

    function appendTextCell(row, text, className) {
        const td = document.createElement('td');
        if (className) td.className = className;
        td.textContent = text;
        row.appendChild(td);
    }

    // ---- Pagination ----

    function renderPagination() {
        paginationEl.textContent = '';

        const filtered = getFilteredWorkflows();
        if (filtered.length === 0 && state.total === 0) return;

        const start = state.offset + 1;
        const end = state.offset + state.workflows.length;

        const info = document.createElement('span');
        info.className = 'page-info';
        if (state.total > 0) {
            info.textContent = `Showing ${start}-${end} of ${state.total}`;
        } else {
            info.textContent = `Showing ${filtered.length} result${filtered.length !== 1 ? 's' : ''}`;
        }
        paginationEl.appendChild(info);

        const buttons = document.createElement('div');
        buttons.className = 'page-buttons';

        const prevBtn = document.createElement('button');
        prevBtn.className = 'page-btn';
        prevBtn.textContent = 'Prev';
        prevBtn.type = 'button';
        prevBtn.disabled = state.offset === 0;
        prevBtn.addEventListener('click', () => {
            state.offset = Math.max(0, state.offset - state.limit);
            fetchWorkflows();
        });
        buttons.appendChild(prevBtn);

        const nextBtn = document.createElement('button');
        nextBtn.className = 'page-btn';
        nextBtn.textContent = 'Next';
        nextBtn.type = 'button';
        nextBtn.disabled = state.offset + state.limit >= state.total;
        nextBtn.addEventListener('click', () => {
            state.offset += state.limit;
            fetchWorkflows();
        });
        buttons.appendChild(nextBtn);

        paginationEl.appendChild(buttons);
    }

    // ---- Client-side search filter ----

    function getFilteredWorkflows() {
        if (!state.search) return state.workflows;
        return state.workflows.filter(wf => {
            const name = (wf.workflow_name || '').toLowerCase();
            return name.includes(state.search);
        });
    }

    // ---- Formatting helpers ----

    function formatDuration(seconds) {
        if (seconds == null) return '-';
        if (seconds < 60) return `${seconds.toFixed(1)}s`;
        const mins = Math.floor(seconds / 60);
        const secs = (seconds % 60).toFixed(0);
        return `${mins}m ${secs}s`;
    }

    function formatTokens(count) {
        if (count == null) return '-';
        if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
        return count.toLocaleString();
    }

    function formatCost(usd) {
        if (usd == null) return '-';
        return `$${usd.toFixed(4)}`;
    }

    function formatTime(isoString) {
        if (!isoString) return '-';
        let s = isoString;
        if (typeof s === 'string' && !/[Zz]$/.test(s) && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z';
        return new Date(s).toLocaleString();
    }
});
