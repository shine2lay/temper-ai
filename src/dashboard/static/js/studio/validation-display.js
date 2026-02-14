/**
 * ValidationDisplay - Bottom validation bar for the MAF Workflow Studio.
 *
 * Manages the validation summary and expandable error/warning list.
 * Listens for 'validation-changed' events from ConfigStore and mirrors
 * validation state onto canvas nodes via CanvasManager.  Clicking an
 * error entry selects the offending element and centers the canvas on it.
 */

import { ConfigStore } from './config-store.js';

// --- Constants ---

const READY_TEXT = 'Ready';
const HIDDEN_CLASS = 'hidden';
const EXPANDED_INDICATOR = ' \u25BC';   // Down-pointing triangle
const COLLAPSED_INDICATOR = ' \u25B6';  // Right-pointing triangle

export class ValidationDisplay {
    /**
     * @param {ConfigStore} configStore - Client-side state store.
     * @param {import('./canvas-manager.js').CanvasManager} canvasManager - Cytoscape canvas controller.
     */
    constructor(configStore, canvasManager) {
        this._configStore = configStore;
        this._canvasManager = canvasManager;

        /** @type {Set<string>} IDs of nodes currently marked invalid on the canvas. */
        this._invalidNodeIds = new Set();

        // DOM references
        this._summaryEl = document.getElementById('validation-summary');
        this._detailsEl = document.getElementById('validation-details');

        // Bind event listeners
        this._configStore.addEventListener(
            'validation-changed',
            (event) => this._onValidationChanged(event)
        );

        // Summary click toggles the details panel
        if (this._summaryEl) {
            this._summaryEl.addEventListener('click', () => this._toggleDetails());
            this._summaryEl.style.cursor = 'pointer';
        }
    }

    // --- Event Handlers ---

    /**
     * Handle validation-changed events from ConfigStore.
     * Updates the summary text, renders the error list, and syncs
     * invalid flags on canvas nodes.
     *
     * @param {CustomEvent} event - Contains { errors: Array<{path, message, elementId?, severity?}> }
     */
    _onValidationChanged(event) {
        const errors = event.detail.errors || [];

        const errorCount = errors.filter(
            (e) => !e.severity || e.severity === 'error'
        ).length;
        const warningCount = errors.filter(
            (e) => e.severity === 'warning'
        ).length;

        this._updateSummary(errorCount, warningCount);
        this._syncCanvasNodes(errors);

        if (errors.length > 0) {
            this._renderErrors(errors);
        } else {
            this._hideDetails();
        }
    }

    // --- Summary ---

    /**
     * Update the summary span text with error/warning counts or "Ready".
     * Appends a collapsed/expanded indicator when there are issues.
     *
     * @param {number} errorCount - Number of errors.
     * @param {number} warningCount - Number of warnings.
     */
    _updateSummary(errorCount, warningCount) {
        if (!this._summaryEl) return;

        if (errorCount === 0 && warningCount === 0) {
            this._summaryEl.textContent = READY_TEXT;
            this._summaryEl.className = '';
            return;
        }

        const parts = [];
        if (errorCount > 0) {
            parts.push(`${errorCount} error${errorCount !== 1 ? 's' : ''}`);
        }
        if (warningCount > 0) {
            parts.push(`${warningCount} warning${warningCount !== 1 ? 's' : ''}`);
        }

        const isExpanded = this._detailsEl && !this._detailsEl.classList.contains(HIDDEN_CLASS);
        const indicator = isExpanded ? EXPANDED_INDICATOR : COLLAPSED_INDICATOR;

        this._summaryEl.textContent = parts.join(', ') + indicator;
        this._summaryEl.className = errorCount > 0 ? 'has-errors' : 'has-warnings';
    }

    // --- Details Toggle ---

    /**
     * Toggle visibility of the validation details panel.
     * Updates the summary indicator to reflect the new state.
     */
    _toggleDetails() {
        if (!this._detailsEl) return;

        // Only toggle if there are items to show
        if (this._detailsEl.children.length === 0) return;

        this._detailsEl.classList.toggle(HIDDEN_CLASS);
        this._refreshSummaryIndicator();
    }

    /**
     * Update just the expand/collapse indicator on the summary text
     * without changing the error/warning counts.
     */
    _refreshSummaryIndicator() {
        if (!this._summaryEl) return;

        const text = this._summaryEl.textContent;
        // Strip any existing indicator
        const stripped = text.replace(/\s*[\u25BC\u25B6]\s*$/, '');

        if (stripped === READY_TEXT) return;

        const isExpanded = this._detailsEl && !this._detailsEl.classList.contains(HIDDEN_CLASS);
        const indicator = isExpanded ? EXPANDED_INDICATOR : COLLAPSED_INDICATOR;
        this._summaryEl.textContent = stripped + indicator;
    }

    /**
     * Hide the details panel and update the summary indicator.
     */
    _hideDetails() {
        if (this._detailsEl) {
            this._detailsEl.innerHTML = '';
            this._detailsEl.classList.add(HIDDEN_CLASS);
        }
        this._refreshSummaryIndicator();
    }

    // --- Error List Rendering ---

    /**
     * Render the list of validation errors/warnings as clickable items.
     * Each item selects the offending element and highlights it on the canvas.
     *
     * @param {Array<{path: string, message: string, elementId?: string, severity?: string}>} errors
     */
    _renderErrors(errors) {
        if (!this._detailsEl) return;

        this._detailsEl.innerHTML = '';

        for (const error of errors) {
            const item = document.createElement('div');
            const severity = error.severity || 'error';
            item.className = `validation-item ${severity}`;
            item.textContent = `[${error.path}]: ${error.message}`;

            if (error.elementId) {
                item.style.cursor = 'pointer';
                item.addEventListener('click', () => {
                    this._configStore.setSelection(error.elementId);
                    this._canvasManager.highlightNode(error.elementId);
                });
            }

            this._detailsEl.appendChild(item);
        }

        // Show the details panel (remove hidden class)
        this._detailsEl.classList.remove(HIDDEN_CLASS);
        this._refreshSummaryIndicator();
    }

    // --- Canvas Node Sync ---

    /**
     * Sync the invalid flag on canvas nodes. Marks nodes referenced by
     * errors as invalid and clears the flag on nodes that were previously
     * invalid but are no longer in the error list.
     *
     * @param {Array<{path: string, message: string, elementId?: string, severity?: string}>} errors
     */
    _syncCanvasNodes(errors) {
        // Collect the set of node IDs that have errors in this validation pass
        const currentInvalidIds = new Set();
        for (const error of errors) {
            if (error.elementId) {
                currentInvalidIds.add(error.elementId);
            }
        }

        // Clear nodes that were invalid before but are now valid
        for (const nodeId of this._invalidNodeIds) {
            if (!currentInvalidIds.has(nodeId)) {
                this._canvasManager.setNodeInvalid(nodeId, false);
            }
        }

        // Mark currently invalid nodes
        for (const nodeId of currentInvalidIds) {
            this._canvasManager.setNodeInvalid(nodeId, true);
        }

        // Update the tracked set
        this._invalidNodeIds = currentInvalidIds;
    }

    // --- Public API ---

    /**
     * Clear all validation state. Resets the summary to "Ready", hides the
     * details panel, and removes the invalid flag from all tracked nodes.
     */
    clearAll() {
        // Reset all currently-invalid nodes on the canvas
        for (const nodeId of this._invalidNodeIds) {
            this._canvasManager.setNodeInvalid(nodeId, false);
        }
        this._invalidNodeIds.clear();

        // Reset the summary text
        if (this._summaryEl) {
            this._summaryEl.textContent = READY_TEXT;
            this._summaryEl.className = '';
        }

        // Clear and hide the details panel
        this._hideDetails();
    }
}
