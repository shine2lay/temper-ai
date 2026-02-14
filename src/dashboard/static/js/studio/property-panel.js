/**
 * PropertyPanel - Right-side properties panel for the MAF Workflow Studio.
 *
 * Renders editable forms for the selected canvas element (stage or agent),
 * or workflow-level properties when nothing is selected. Uses SchemaRegistry
 * for JSON Schema resolution and FormBuilder for HTML form generation.
 * Property changes are tracked via ChangePropertyCommand for undo/redo.
 */

import { ConfigStore } from './config-store.js';
import { SchemaRegistry } from './schema-registry.js';
import { FormBuilder } from './form-builder.js';
import { ChangePropertyCommand } from './command-stack.js';

export class PropertyPanel {
    /**
     * @param {ConfigStore} configStore - Client-side state store
     * @param {SchemaRegistry} schemaRegistry - JSON Schema fetcher/resolver
     * @param {FormBuilder} formBuilder - Schema-to-form renderer
     * @param {import('./command-stack.js').CommandStack} commandStack - Undo/redo stack
     */
    constructor(configStore, schemaRegistry, formBuilder, commandStack) {
        this._configStore = configStore;
        this._schemaRegistry = schemaRegistry;
        this._formBuilder = formBuilder;
        this._commandStack = commandStack;

        this._panelContent = document.getElementById('property-panel-content');

        this._configStore.addEventListener(
            'selection-changed',
            (event) => this._onSelectionChanged(event)
        );
        this._configStore.addEventListener(
            'document-changed',
            () => this._onDocumentChanged()
        );
    }

    // --- Event Handlers ---

    /**
     * Handle selection changes on the canvas.
     * Routes to the appropriate renderer based on element type.
     * @param {CustomEvent} event - Contains { elementId, element }
     */
    _onSelectionChanged(event) {
        const { element } = event.detail;

        if (!element) {
            this._renderWorkflowProperties();
            return;
        }

        if (element.type === 'stage') {
            this._renderElementProperties(element, 'stages');
        } else if (element.type === 'agent') {
            this._renderElementProperties(element, 'agents');
        }
    }

    /**
     * Handle document changes (new/load workflow).
     * Re-renders the current selection or workflow properties.
     */
    _onDocumentChanged() {
        const selectedId = this._configStore.selectedElement;
        if (selectedId) {
            const doc = this._configStore.activeDocument;
            const element = doc
                ? doc.elements.find(el => el.id === selectedId)
                : null;
            if (element) {
                const configType = element.type === 'stage' ? 'stages' : 'agents';
                this._renderElementProperties(element, configType);
                return;
            }
        }
        this._renderWorkflowProperties();
    }

    // --- Renderers ---

    /**
     * Render workflow-level properties when no element is selected.
     * Fetches the workflow schema and builds a form from the active document.
     */
    async _renderWorkflowProperties() {
        const activeDocument = this._configStore.activeDocument;

        if (!activeDocument) {
            this._showEmptyState('No workflow loaded');
            return;
        }

        try {
            const fullSchema = await this._schemaRegistry.getSchema('workflows');
            const innerSchema = this._schemaRegistry.getInnerSchema('workflows', fullSchema);
            const resolvedSchema = this._schemaRegistry.resolveAllRefs(innerSchema, fullSchema);

            const data = activeDocument.config.workflow;

            const onChange = (path, value) => {
                this._setNestedValue(activeDocument.config.workflow, path, value);
                this._configStore.markDirty();
            };

            const form = this._formBuilder.buildForm(resolvedSchema, data, onChange, '');

            this._clearPanel();
            this._appendHeader('Workflow Properties');
            this._panelContent.appendChild(form);
        } catch (err) {
            console.error('PropertyPanel: Failed to render workflow properties', err);
            this._showEmptyState('Failed to load workflow schema');
        }
    }

    /**
     * Render properties for a selected stage or agent element.
     * @param {object} element - The canvas element (from configStore)
     * @param {string} configType - 'stages' or 'agents'
     */
    async _renderElementProperties(element, configType) {
        try {
            const fullSchema = await this._schemaRegistry.getSchema(configType);
            const innerSchema = this._schemaRegistry.getInnerSchema(configType, fullSchema);

            // If the schema has no wrapper key, try using the full schema directly
            const schemaToResolve = innerSchema || fullSchema;
            const resolvedSchema = this._schemaRegistry.resolveAllRefs(schemaToResolve, fullSchema);

            const data = element.config;

            const onChange = (path, value) => {
                const oldValue = this._getNestedValue(element.config, path);
                this._setNestedValue(element.config, path, value);

                // If the name field changed, update the canvas label too
                if (path === 'name') {
                    this._configStore.updateElementProperty(element.id, 'name', value);
                }

                const command = new ChangePropertyCommand(
                    this._configStore,
                    element.id,
                    path,
                    oldValue,
                    value
                );
                this._commandStack.execute(command);
            };

            const form = this._formBuilder.buildForm(resolvedSchema, data, onChange, '');

            const typeLabel = configType === 'stages' ? 'Stage' : 'Agent';
            const displayName = element.name || typeLabel;

            this._clearPanel();
            this._appendHeader(`${typeLabel}: ${displayName}`);
            this._panelContent.appendChild(form);
        } catch (err) {
            console.error(`PropertyPanel: Failed to render ${configType} properties`, err);
            this._showEmptyState(`Failed to load ${configType} schema`);
        }
    }

    // --- Helper Methods ---

    /**
     * Set a value at a dot-separated path in an object.
     * Creates intermediate objects as needed.
     * @param {object} obj - Target object
     * @param {string} path - Dot-separated path (e.g., 'error_handling.max_retries')
     * @param {*} value - Value to set
     */
    _setNestedValue(obj, path, value) {
        if (!obj || !path) return;

        const parts = path.split('.');
        let current = obj;

        for (let i = 0; i < parts.length - 1; i++) {
            const key = parts[i];
            if (current[key] === undefined || current[key] === null || typeof current[key] !== 'object') {
                current[key] = {};
            }
            current = current[key];
        }

        const lastKey = parts[parts.length - 1];
        if (value === undefined) {
            delete current[lastKey];
        } else {
            current[lastKey] = value;
        }
    }

    /**
     * Get a value at a dot-separated path in an object.
     * @param {object} obj - Source object
     * @param {string} path - Dot-separated path (e.g., 'error_handling.max_retries')
     * @returns {*} The value at the path, or undefined if not found
     */
    _getNestedValue(obj, path) {
        if (!obj || !path) return undefined;

        const parts = path.split('.');
        let current = obj;

        for (const key of parts) {
            if (current === undefined || current === null || typeof current !== 'object') {
                return undefined;
            }
            current = current[key];
        }

        return current;
    }

    /**
     * Clear the panel content div.
     */
    _clearPanel() {
        if (this._panelContent) {
            this._panelContent.innerHTML = '';
        }
    }

    /**
     * Show an empty state message in the panel.
     * @param {string} message - Text to display
     */
    _showEmptyState(message) {
        this._clearPanel();
        const div = document.createElement('div');
        div.className = 'empty-state';
        div.textContent = message;
        this._panelContent.appendChild(div);
    }

    /**
     * Append a styled header to the panel content.
     * @param {string} text - Header text
     */
    _appendHeader(text) {
        const header = document.createElement('div');
        header.className = 'panel-header';
        header.textContent = text;
        this._panelContent.appendChild(header);
    }
}
