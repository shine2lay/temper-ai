/**
 * Toolbar - Top toolbar for the MAF Workflow Studio.
 *
 * Renders and manages buttons for creating, importing, saving, running
 * workflows, and undo/redo/zoom/layout controls.  Listens for keyboard
 * shortcuts (Ctrl+Z, Ctrl+Shift+Z, Ctrl+S, Delete) and keeps button
 * states in sync with the CommandStack and ConfigStore dirty flag.
 */

import { ConfigStore } from './config-store.js';

// Tags that should suppress keyboard shortcuts when focused
const INPUT_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

// API endpoint for running workflows
const RUN_ENDPOINT = '/api/workflows/run';

export class Toolbar {
    /**
     * @param {ConfigStore}  configStore   Shared store for workflow state.
     * @param {CommandStack} commandStack  Undo/redo command stack.
     * @param {CanvasManager} canvasManager Cytoscape canvas controller.
     * @param {object}       yamlBridge    YAML import/export bridge.
     */
    constructor(configStore, commandStack, canvasManager, yamlBridge) {
        this._store = configStore;
        this._commandStack = commandStack;
        this._canvas = canvasManager;
        this._yamlBridge = yamlBridge;
        this._el = document.getElementById('studio-toolbar');

        this._btnSave = null;
        this._btnUndo = null;
        this._btnRedo = null;

        this._render();
        this._setupKeyboardShortcuts();

        this._commandStack.addEventListener('stack-changed', () => {
            this._updateButtonStates();
        });

        this._store.addEventListener('dirty-changed', () => {
            this._updateButtonStates();
        });
    }

    // ── Rendering ──────────────────────────────────────────────────

    /** Build the full toolbar layout with button groups and dividers. */
    _render() {
        if (!this._el) return;

        this._el.innerHTML = '';

        // --- Group 1: File operations ---
        this._el.appendChild(
            this._createButton('New', 'btn-secondary', () => {
                this._store.newWorkflow('untitled');
            })
        );
        this._el.appendChild(
            this._createButton('Import', 'btn-secondary', () => {
                const name = prompt('Workflow name to import:');
                if (name) {
                    this._yamlBridge.importWorkflow(name);
                }
            })
        );

        this._el.appendChild(this._createDivider());

        // --- Group 2: Save / Run ---
        this._btnSave = this._createButton(
            'Save', 'btn-primary', () => this._handleSave(), 'btn-save'
        );
        this._el.appendChild(this._btnSave);
        this._el.appendChild(
            this._createButton('Save & Run', 'btn-primary', () => {
                this._handleSaveAndRun();
            })
        );

        this._el.appendChild(this._createDivider());

        // --- Group 3: Edit (undo / redo) ---
        this._btnUndo = this._createButton(
            'Undo', 'btn-icon', () => this._commandStack.undo(), 'btn-undo'
        );
        this._el.appendChild(this._btnUndo);

        this._btnRedo = this._createButton(
            'Redo', 'btn-icon', () => this._commandStack.redo(), 'btn-redo'
        );
        this._el.appendChild(this._btnRedo);

        this._el.appendChild(this._createDivider());

        // --- Group 4: View ---
        this._el.appendChild(
            this._createButton('Zoom In', 'btn-icon', () => this._canvas.zoomIn())
        );
        this._el.appendChild(
            this._createButton('Zoom Out', 'btn-icon', () => this._canvas.zoomOut())
        );
        this._el.appendChild(
            this._createButton('Fit', 'btn-icon', () => this._canvas.fit())
        );
        this._el.appendChild(
            this._createButton('Auto Layout', 'btn-icon', () => this._canvas.autoLayout())
        );

        this._el.appendChild(this._createDivider());

        // --- Group 5: YAML ---
        this._el.appendChild(
            this._createButton('YAML', 'btn-secondary', () => {
                this._yamlBridge.showYamlPreview();
            })
        );

        // Set initial button states
        this._updateButtonStates();
    }

    // ── Button helpers ─────────────────────────────────────────────

    /**
     * Create a toolbar button element.
     * @param {string}   label     Button text.
     * @param {string}   className CSS class for styling.
     * @param {Function} onClick   Click handler.
     * @param {string|null} id     Optional DOM id.
     * @returns {HTMLButtonElement}
     */
    _createButton(label, className, onClick, id = null) {
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.className = className;
        btn.addEventListener('click', onClick);
        if (id) {
            btn.id = id;
        }
        return btn;
    }

    /**
     * Create a vertical divider span for separating button groups.
     * @returns {HTMLSpanElement}
     */
    _createDivider() {
        const span = document.createElement('span');
        span.className = 'toolbar-divider';
        return span;
    }

    // ── Save / Run handlers ────────────────────────────────────────

    /**
     * Save the active workflow via the YAML bridge.
     * @returns {Promise<boolean>} True if save succeeded.
     */
    async _handleSave() {
        const doc = this._store.activeDocument;
        if (!doc) {
            alert('No workflow to save');
            return false;
        }

        const name = doc.name;
        try {
            await this._yamlBridge.saveWorkflow(name);
            this._store.markClean();
            return true;
        } catch (err) {
            alert(err.message || String(err));
            return false;
        }
    }

    /**
     * Save the workflow and then run it via the API.
     * On success, redirects to the dashboard with the workflow_id.
     */
    async _handleSaveAndRun() {
        const saved = await this._handleSave();
        if (!saved) return;

        const name = this._store.activeDocument.name;
        try {
            const resp = await fetch(RUN_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow_path: `configs/workflows/${name}.yaml`,
                }),
            });

            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`Run failed (${resp.status}): ${text}`);
            }

            const result = await resp.json();
            window.location.href = '/index.html?workflow_id=' + result.workflow_id;
        } catch (err) {
            alert(err.message || String(err));
        }
    }

    // ── Keyboard shortcuts ─────────────────────────────────────────

    /** Register global keyboard shortcuts for common operations. */
    _setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Skip shortcuts when focus is in an input-like element
            if (INPUT_TAGS.has(e.target.tagName)) return;

            const ctrlOrMeta = e.ctrlKey || e.metaKey;

            // Ctrl+Shift+Z  ->  Redo
            if (ctrlOrMeta && e.shiftKey && e.key === 'Z') {
                e.preventDefault();
                this._commandStack.redo();
                return;
            }

            // Ctrl+Z  ->  Undo
            if (ctrlOrMeta && !e.shiftKey && e.key === 'z') {
                e.preventDefault();
                this._commandStack.undo();
                return;
            }

            // Ctrl+S  ->  Save
            if (ctrlOrMeta && e.key === 's') {
                e.preventDefault();
                this._handleSave();
                return;
            }

            // Delete / Backspace  ->  Remove selected element
            if (e.key === 'Delete' || e.key === 'Backspace') {
                const selectedId = this._store.selectedElement;
                if (selectedId) {
                    e.preventDefault();
                    import('./command-stack.js').then(({ RemoveNodeCommand }) => {
                        const cmd = new RemoveNodeCommand(this._store, selectedId);
                        this._commandStack.execute(cmd);
                    });
                }
            }
        });
    }

    // ── Button state management ────────────────────────────────────

    /** Update disabled/enabled state and titles for undo, redo, and save. */
    _updateButtonStates() {
        // Undo button
        if (this._btnUndo) {
            this._btnUndo.disabled = !this._commandStack.canUndo;
            const undoDesc = this._commandStack.undoDescription;
            this._btnUndo.title = undoDesc ? `Undo: ${undoDesc}` : 'Undo';
        }

        // Redo button
        if (this._btnRedo) {
            this._btnRedo.disabled = !this._commandStack.canRedo;
            const redoDesc = this._commandStack.redoDescription;
            this._btnRedo.title = redoDesc ? `Redo: ${redoDesc}` : 'Redo';
        }

        // Save button dirty indicator
        if (this._btnSave) {
            if (this._store.dirty) {
                this._btnSave.classList.add('dirty');
                this._btnSave.textContent = 'Save *';
            } else {
                this._btnSave.classList.remove('dirty');
                this._btnSave.textContent = 'Save';
            }
        }
    }
}
