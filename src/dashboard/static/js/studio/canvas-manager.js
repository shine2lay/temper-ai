/**
 * CanvasManager - Cytoscape.js canvas for the MAF Workflow Studio builder mode.
 *
 * Provides an editable graph canvas with:
 * - HTML5 drag-and-drop target for palette items
 * - Compound nodes for stages with agent children
 * - Dagre auto-layout on demand
 * - Two-way sync with ConfigStore (store changes update canvas, canvas
 *   selection/position changes update store)
 * - Node validation states (invalid border) and highlight animations
 */

import { ConfigStore } from './config-store.js';

// --- Constants ---

const ANIMATION_DURATION_MS = 300;
const FIT_PADDING_PX = 50;
const ZOOM_STEP = 1.2;
const DAGRE_NODE_SEP = 50;
const DAGRE_RANK_SEP = 80;
const DAGRE_PADDING = 40;

// --- Styles ---

const STUDIO_STYLES = [
    // Stage (compound/parent) nodes — label rendered via HTML overlay
    {
        selector: 'node[type="stage"]',
        style: {
            'background-color': '#111827',
            'background-opacity': 0.95,
            'border-color': '#374151',
            'border-width': 2,
            'shape': 'roundrectangle',
            'padding': 52,
            'min-width': 240,
            'min-height': 60,
            'label': '',
        },
    },
    // Agent (child) nodes inside a stage
    {
        selector: 'node[type="agent"]',
        style: {
            'background-color': '#1e293b',
            'border-color': '#334155',
            'border-width': 1.5,
            'shape': 'roundrectangle',
            'width': 200,
            'height': 52,
            'label': '',
        },
    },
    // Selected stage
    {
        selector: 'node[type="stage"]:selected',
        style: {
            'border-color': '#60a5fa',
            'border-width': 3,
        },
    },
    // Selected agent
    {
        selector: 'node[type="agent"]:selected',
        style: {
            'border-color': '#60a5fa',
            'border-width': 2.5,
        },
    },
    // Invalid node (validation error)
    {
        selector: 'node[?invalid]',
        style: {
            'border-color': '#ef4444',
            'border-style': 'dashed',
            'border-width': 3,
        },
    },
    // Highlighted node (flash animation)
    {
        selector: '.highlighted',
        style: {
            'border-color': '#f59e0b',
            'border-width': 4,
        },
    },
    // Stage dependency edges (between stages)
    {
        selector: 'edge[flowType="stage-dep"]',
        style: {
            'width': 2.5,
            'line-color': '#6366f1',
            'target-arrow-color': '#6366f1',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'arrow-scale': 1.4,
            'line-opacity': 0.85,
            'label': 'data(label)',
            'font-size': 9,
            'color': '#6366f1',
            'text-opacity': 0.7,
            'text-background-color': '#0a0e1a',
            'text-background-opacity': 0.8,
            'text-background-padding': 3,
        },
    },
    // Agent flow edges (sequential flow within a stage)
    {
        selector: 'edge[flowType="agent-flow"]',
        style: {
            'width': 1.5,
            'line-color': '#475569',
            'target-arrow-color': '#475569',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'arrow-scale': 0.9,
            'line-style': 'dashed',
            'line-dash-pattern': [6, 3],
            'line-opacity': 0.6,
        },
    },
    // Default edges (fallback for edges without flowType)
    {
        selector: 'edge',
        style: {
            'width': 2.5,
            'line-color': '#6366f1',
            'target-arrow-color': '#6366f1',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'arrow-scale': 1.4,
            'line-opacity': 0.8,
        },
    },
    // Selected edge
    {
        selector: 'edge:selected',
        style: {
            'width': 3.5,
            'line-color': '#f59e0b',
            'target-arrow-color': '#f59e0b',
            'line-opacity': 1,
        },
    },
];

// --- CanvasManager ---

export class CanvasManager {
    /**
     * @param {string} containerId - DOM element ID for the Cytoscape container.
     * @param {ConfigStore} configStore - The studio config store instance.
     */
    constructor(containerId, configStore) {
        this._containerId = containerId;
        this._store = configStore;
        this._cy = null;
        this._boundListeners = [];
        this._initCytoscape();
        this._setupDropTarget();
        this._setupSelection();
        this._setupDragSync();
    }

    /** @returns {object|null} The Cytoscape instance. */
    get cy() {
        return this._cy;
    }

    // --- Initialization ---

    _initCytoscape() {
        const container = document.getElementById(this._containerId);
        if (!container) {
            console.error(
                `CanvasManager: container element "${this._containerId}" not found`
            );
            return;
        }

        this._cy = cytoscape({
            container,
            style: STUDIO_STYLES,
            layout: { name: 'preset' },
            wheelSensitivity: 0.3,
            boxSelectionEnabled: true,
            selectionType: 'single',
        });

        this._initHtmlLabels();
        this._setupStoreListeners();
    }

    // --- HTML Overlays ---

    /**
     * Initialize cytoscape-node-html-label for rich HTML overlays
     * on stage and agent nodes.
     */
    _initHtmlLabels() {
        if (!this._cy || !this._cy.nodeHtmlLabel) return;

        this._cy.nodeHtmlLabel([
            // Stage compound node overlay: name + mode/strategy info
            {
                query: 'node[type="stage"]',
                halign: 'center',
                valign: 'top',
                cssClass: 'cy-html-label',
                tpl: (data) => {
                    const name = this._escapeHtml(data.label || 'Stage');
                    const agentMode = data.agentMode || 'sequential';
                    const strategy = this._escapeHtml(data.strategy || '');
                    const agentCount = data.agentCount || 0;
                    const maxRounds = data.maxRounds || 1;

                    // Mode badge
                    const modeClass = agentMode === 'parallel' ? 'parallel'
                        : agentMode === 'adaptive' ? 'adaptive'
                        : 'sequential';
                    const modeLabel = agentMode === 'parallel' ? 'parallel'
                        : agentMode === 'adaptive' ? 'adaptive'
                        : 'sequential';

                    // Build meta items
                    let metaHtml = `<span class="stage-mode-badge ${modeClass}">${modeLabel}</span>`;
                    if (strategy) {
                        metaHtml += `<span class="stage-meta-sep">\u00b7</span>`;
                        metaHtml += `<span class="stage-meta-item">${strategy}</span>`;
                    }
                    if (agentCount > 0) {
                        metaHtml += `<span class="stage-meta-sep">\u00b7</span>`;
                        metaHtml += `<span class="stage-meta-item">${agentCount} agent${agentCount !== 1 ? 's' : ''}</span>`;
                    }
                    if (maxRounds > 1) {
                        metaHtml += `<span class="stage-meta-sep">\u00b7</span>`;
                        metaHtml += `<span class="stage-meta-item stage-meta-rounds">\u00d7${maxRounds} rounds</span>`;
                    }

                    return `<div class="stage-label">
                        <div class="stage-label-name">${name}</div>
                        <div class="stage-label-meta">${metaHtml}</div>
                    </div>`;
                },
            },
            // Agent node overlay: icon + name + model
            {
                query: 'node[type="agent"]',
                halign: 'center',
                valign: 'center',
                cssClass: 'cy-html-label',
                tpl: (data) => {
                    const name = this._escapeHtml(data.label || 'Agent');
                    const model = this._escapeHtml(data.model || '');
                    const desc = this._escapeHtml(data.desc || '');
                    const modelLine = model
                        ? `<div class="agent-label-model">${model}</div>`
                        : '';
                    const descLine = (!model && desc)
                        ? `<div class="agent-label-desc">${desc}</div>`
                        : '';
                    return `<div class="agent-label">
                        <div class="agent-label-header">
                            <span class="agent-label-icon">A</span>
                            <span class="agent-label-name">${name}</span>
                        </div>
                        ${modelLine}${descLine}
                    </div>`;
                },
            },
        ]);
    }

    /**
     * Escape HTML entities in a string.
     * @param {string} str - Input string.
     * @returns {string} Escaped string safe for innerHTML.
     */
    _escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // --- Store -> Canvas Sync ---

    /**
     * Subscribe to ConfigStore events and mirror changes onto the canvas.
     * Each listener is tracked in _boundListeners for clean teardown.
     */
    _setupStoreListeners() {
        this._addStoreListener('element-added', (e) => {
            this._onElementAdded(e.detail.element);
        });

        this._addStoreListener('element-removed', (e) => {
            this._onElementRemoved(e.detail.elementId);
        });

        this._addStoreListener('property-changed', (e) => {
            this._onPropertyChanged(
                e.detail.elementId,
                e.detail.property,
                e.detail.value
            );
        });

        this._addStoreListener('position-changed', (e) => {
            this._onPositionChanged(e.detail.elementId, e.detail.position);
        });

        this._addStoreListener('edge-added', (e) => {
            this._onEdgeAdded(e.detail.edge);
        });

        this._addStoreListener('edge-removed', (e) => {
            this._onEdgeRemoved(e.detail.edgeId);
        });

        this._addStoreListener('document-changed', () => {
            this._rebuildCanvas();
        });
    }

    /**
     * Helper to attach a named event listener to the store and track it
     * for later removal in destroy().
     */
    _addStoreListener(eventName, handler) {
        this._store.addEventListener(eventName, handler);
        this._boundListeners.push({ eventName, handler });
    }

    /**
     * Handle element-added: add the appropriate node to the canvas.
     */
    _onElementAdded(element) {
        if (!this._cy || !element) return;

        // Guard against duplicate additions
        if (this._cy.getElementById(element.id).length > 0) return;

        if (element.type === 'stage') {
            this.addStageNode(element.id, element.name, element.position, {
                strategy: element.strategy || '',
                agentMode: element.agentMode || 'sequential',
                maxRounds: element.maxRounds || 1,
                agentCount: element.agentCount || 0,
            });
        } else if (element.type === 'agent') {
            this.addAgentNode(
                element.id,
                element.name,
                element.parentId,
                element.position,
                {
                    model: element.model || '',
                    description: element.description || '',
                }
            );
        }
    }

    /**
     * Handle element-removed: remove the node from the canvas.
     */
    _onElementRemoved(elementId) {
        if (!this._cy || !elementId) return;
        this.removeElement(elementId);
    }

    /**
     * Handle property-changed: update the matching canvas node's data.
     * The 'name' property is mapped to the Cytoscape 'label' data field.
     */
    _onPropertyChanged(elementId, property, value) {
        if (!this._cy || !elementId) return;

        const node = this._cy.getElementById(elementId);
        if (node.length === 0) return;

        if (property === 'name') {
            node.data('label', value);
        } else if (property === 'parentId') {
            // Reparenting: Cytoscape requires remove + re-add to change parent
            const data = { ...node.data() };
            const pos = node.position();
            this._cy.remove(node);
            data.parent = value;
            this._cy.add({ group: 'nodes', data, position: pos });
        } else {
            // Generic data update (e.g. config sub-fields, invalid flag)
            node.data(property, value);
        }
    }

    /**
     * Handle position-changed: animate the node to its new position.
     */
    _onPositionChanged(elementId, position) {
        if (!this._cy || !elementId || !position) return;

        const node = this._cy.getElementById(elementId);
        if (node.length === 0) return;

        node.animate(
            { position: { x: position.x, y: position.y } },
            { duration: ANIMATION_DURATION_MS }
        );
    }

    /**
     * Handle edge-added: add an edge to the canvas.
     */
    _onEdgeAdded(edge) {
        if (!this._cy || !edge) return;

        // Guard against duplicate edges
        if (this._cy.getElementById(edge.id).length > 0) return;

        this.addEdge(edge.id, edge.source, edge.target, edge.flowType, edge.label);
    }

    /**
     * Handle edge-removed: remove the edge from the canvas.
     */
    _onEdgeRemoved(edgeId) {
        if (!this._cy || !edgeId) return;
        this.removeElement(edgeId);
    }

    // --- Drop Target ---

    /**
     * Configure the container as an HTML5 drop target. Dropped items emit
     * a 'studio:drop' event on the Cytoscape instance for the studio-app
     * to handle (creating the appropriate command via CommandStack).
     */
    _setupDropTarget() {
        const container = document.getElementById(this._containerId);
        if (!container) return;

        container.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });

        container.addEventListener('drop', (e) => {
            e.preventDefault();
            let data;
            try {
                data = JSON.parse(e.dataTransfer.getData('application/json'));
            } catch (err) {
                console.warn('CanvasManager: invalid drop data', err);
                return;
            }
            const position = this._clientToCanvas(e.clientX, e.clientY);
            this._cy.emit('studio:drop', [{ data, position }]);
        });
    }

    /**
     * Convert client (viewport) coordinates to Cytoscape model coordinates,
     * accounting for current pan and zoom.
     */
    _clientToCanvas(clientX, clientY) {
        const rect = this._cy.container().getBoundingClientRect();
        const renderedX = clientX - rect.left;
        const renderedY = clientY - rect.top;
        const pan = this._cy.pan();
        const zoom = this._cy.zoom();
        return {
            x: (renderedX - pan.x) / zoom,
            y: (renderedY - pan.y) / zoom,
        };
    }

    // --- Selection ---

    /**
     * Wire up tap events to propagate selection to the ConfigStore.
     * Tapping the canvas background clears selection.
     */
    _setupSelection() {
        if (!this._cy) return;

        this._cy.on('tap', 'node', (evt) => {
            this._store.setSelection(evt.target.id());
        });

        this._cy.on('tap', (evt) => {
            if (evt.target === this._cy) {
                this._store.setSelection(null);
            }
        });
    }

    // --- Drag Position Sync ---

    /**
     * When a user finishes dragging a node on the canvas, write the new
     * position back to the ConfigStore so it persists.
     */
    _setupDragSync() {
        if (!this._cy) return;

        this._cy.on('dragfree', 'node', (evt) => {
            const node = evt.target;
            const nodeType = node.data('type');
            // Only sync draggable element types (stages and agents)
            if (nodeType === 'stage' || nodeType === 'agent') {
                const pos = node.position();
                this._store.updateElementPosition(node.id(), {
                    x: pos.x,
                    y: pos.y,
                });
            }
        });
    }

    // --- Helpers ---

    // --- Public Node/Edge API ---

    /**
     * Add a stage compound node to the canvas.
     * @param {string} id - Unique stage identifier.
     * @param {string} label - Display label for the stage.
     * @param {{x: number, y: number}} position - Canvas position.
     * @param {object} [meta] - Optional metadata.
     */
    addStageNode(id, label, position, meta = {}) {
        if (!this._cy) return;

        this._cy.add({
            group: 'nodes',
            data: {
                id,
                label,
                type: 'stage',
                strategy: meta.strategy || '',
                agentMode: meta.agentMode || 'sequential',
                maxRounds: meta.maxRounds || 1,
                agentCount: meta.agentCount || 0,
            },
            position,
        });
    }

    /**
     * Add an agent child node inside a stage compound node.
     * @param {string} id - Unique agent identifier.
     * @param {string} label - Display label for the agent.
     * @param {string} parentId - ID of the parent stage node.
     * @param {{x: number, y: number}} position - Canvas position.
     * @param {object} [meta] - Optional metadata { description, model }.
     */
    addAgentNode(id, label, parentId, position, meta = {}) {
        if (!this._cy) return;

        this._cy.add({
            group: 'nodes',
            data: {
                id,
                label,
                type: 'agent',
                parent: parentId,
                model: meta.model || '',
                desc: meta.description || '',
            },
            position,
        });
    }

    /**
     * Add an edge between two nodes.
     * @param {string} id - Unique edge identifier.
     * @param {string} sourceId - Source node ID.
     * @param {string} targetId - Target node ID.
     * @param {string} [flowType] - Edge type: 'stage-dep' or 'agent-flow'.
     * @param {string} [label] - Optional edge label.
     */
    addEdge(id, sourceId, targetId, flowType, label) {
        if (!this._cy) return;

        this._cy.add({
            group: 'edges',
            data: {
                id,
                source: sourceId,
                target: targetId,
                flowType: flowType || 'stage-dep',
                label: label || '',
            },
        });
    }

    /**
     * Remove a node or edge from the canvas by ID.
     * @param {string} id - Element ID to remove.
     */
    removeElement(id) {
        if (!this._cy) return;
        const el = this._cy.getElementById(id);
        if (el.length > 0) {
            this._cy.remove(el);
        }
    }

    // --- Layout ---

    /**
     * Run dagre hierarchical auto-layout (top-to-bottom) on all elements.
     * Animates nodes to their new positions.
     */
    autoLayout() {
        if (!this._cy || this._cy.elements().length === 0) return;

        this._cy.layout({
            name: 'dagre',
            rankDir: 'TB',
            nodeSep: DAGRE_NODE_SEP,
            rankSep: DAGRE_RANK_SEP,
            padding: DAGRE_PADDING,
            animate: true,
            animationDuration: ANIMATION_DURATION_MS,
        }).run();
    }

    /**
     * Fit the viewport to show all canvas content with padding.
     */
    fit() {
        if (!this._cy) return;
        this._cy.fit(null, FIT_PADDING_PX);
    }

    /**
     * Zoom in by one step (multiplied by ZOOM_STEP).
     */
    zoomIn() {
        if (!this._cy) return;
        this._cy.zoom(this._cy.zoom() * ZOOM_STEP);
    }

    /**
     * Zoom out by one step (divided by ZOOM_STEP).
     */
    zoomOut() {
        if (!this._cy) return;
        this._cy.zoom(this._cy.zoom() / ZOOM_STEP);
    }

    // --- Canvas Rebuild ---

    /**
     * Rebuild the entire canvas from the store's active document.
     * Called when the document changes (new workflow loaded, undo past
     * creation, etc.). Removes all existing elements and re-adds them.
     */
    _rebuildCanvas() {
        if (!this._cy) return;

        this._cy.elements().remove();

        const doc = this._store.activeDocument;
        if (!doc) return;

        const elements = doc.elements || [];
        const edges = doc.edges || [];

        // Batch additions for performance
        this._cy.batch(() => {
            // Add stage nodes first (compounds must exist before children)
            for (const el of elements) {
                if (el.type === 'stage') {
                    this.addStageNode(el.id, el.name, el.position, {
                        strategy: el.strategy || '',
                        agentMode: el.agentMode || 'sequential',
                        maxRounds: el.maxRounds || 1,
                        agentCount: el.agentCount || 0,
                    });
                }
            }

            // Add agent nodes (children of stages)
            for (const el of elements) {
                if (el.type === 'agent') {
                    this.addAgentNode(el.id, el.name, el.parentId, el.position, {
                        model: el.model || '',
                        description: el.description || '',
                    });
                }
            }

            // Add edges (both stage-dep and agent-flow)
            for (const edge of edges) {
                this.addEdge(
                    edge.id,
                    edge.source,
                    edge.target,
                    edge.flowType || 'stage-dep',
                    edge.label || ''
                );
            }
        });

        // Auto-layout if there are elements to arrange
        if (elements.length > 0) {
            this.autoLayout();
        }
    }

    // --- Validation & Highlighting ---

    /**
     * Mark a node as invalid (shows red dashed border) or clear the flag.
     * @param {string} nodeId - Target node ID.
     * @param {boolean} invalid - True to mark invalid, false to clear.
     */
    setNodeInvalid(nodeId, invalid) {
        if (!this._cy) return;
        const node = this._cy.getElementById(nodeId);
        if (node.length > 0) {
            node.data('invalid', invalid);
        }
    }

    /**
     * Center the viewport on a node and flash it with the highlighted
     * style for visual feedback (e.g. after search or validation error click).
     * @param {string} nodeId - Target node ID.
     */
    highlightNode(nodeId) {
        if (!this._cy) return;
        const node = this._cy.getElementById(nodeId);
        if (node.length === 0) return;

        this._cy.animate({
            center: { eles: node },
            zoom: this._cy.zoom(),
            duration: ANIMATION_DURATION_MS,
        });

        // flashClass adds a class temporarily (removed after duration)
        node.flashClass('highlighted', 1000);
    }

    // --- Teardown ---

    /**
     * Destroy the Cytoscape instance and remove all store listeners.
     * Call this when the studio view is torn down to prevent leaks.
     */
    destroy() {
        // Remove store listeners
        for (const { eventName, handler } of this._boundListeners) {
            this._store.removeEventListener(eventName, handler);
        }
        this._boundListeners = [];

        // Destroy Cytoscape
        if (this._cy) {
            this._cy.destroy();
            this._cy = null;
        }
    }
}
