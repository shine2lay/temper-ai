/**
 * ConfigStore - Client-side state for the Workflow Studio.
 * Extends EventTarget for event-driven updates across modules.
 */

const DEFAULT_ERROR_HANDLING = {
    on_stage_failure: 'halt',
    max_stage_retries: 3,
    escalation_policy: 'LogAndContinue',
    enable_rollback: true,
    rollback_on: []
};

export class ConfigStore extends EventTarget {
    constructor() {
        super();
        this._catalogs = { workflows: [], stages: [], agents: [], tools: [] };
        this._activeDocument = null;
        this._selectedElement = null;
        this._dirty = false;
        this._resolvedConfigs = new Map();
    }

    // --- Catalog Management ---
    get catalogs() {
        return this._catalogs;
    }

    async loadCatalogs() {
        const types = ['workflows', 'stages', 'agents', 'tools'];
        const promises = types.map(async (type) => {
            try {
                const resp = await fetch(`/api/studio/configs/${type}`);
                if (!resp.ok) {
                    console.error(`Failed to load ${type} catalog: ${resp.status}`);
                    return;
                }
                const data = await resp.json();
                this._catalogs[type] = data.configs || [];
            } catch (err) {
                console.error(`Error loading ${type} catalog:`, err);
            }
        });
        await Promise.all(promises);
        this._emit('catalog-loaded', { catalogs: this._catalogs });
    }

    // --- Active Document ---
    get activeDocument() {
        return this._activeDocument;
    }

    newWorkflow(name = 'untitled') {
        this._activeDocument = {
            type: 'workflow',
            name: name,
            config: {
                workflow: {
                    name: name,
                    description: '',
                    version: '1.0',
                    stages: [],
                    error_handling: { ...DEFAULT_ERROR_HANDLING }
                }
            },
            elements: [],
            edges: []
        };
        this._dirty = false;
        this._selectedElement = null;
        this._resolvedConfigs.clear();
        this._emit('document-changed', { document: this._activeDocument });
    }

    setActiveDocument(doc) {
        this._activeDocument = doc;
        this._dirty = false;
        this._selectedElement = null;
        this._emit('document-changed', { document: this._activeDocument });
    }

    // --- Elements (stages, agents on canvas) ---
    addElement(element) {
        if (!this._activeDocument) return null;
        const newElement = {
            id: element.id || 'el_' + crypto.randomUUID(),
            type: element.type,
            name: element.name,
            parentId: element.parentId || null,
            config: element.config || {},
            position: element.position || { x: 0, y: 0 }
        };
        this._activeDocument.elements.push(newElement);
        this.markDirty();
        this._emit('element-added', { element: newElement });
        return newElement;
    }

    removeElement(elementId) {
        if (!this._activeDocument) return;
        const idx = this._activeDocument.elements.findIndex(el => el.id === elementId);
        if (idx === -1) return;

        const removed = this._activeDocument.elements.splice(idx, 1)[0];
        this.markDirty();
        this._emit('element-removed', { elementId, element: removed });
    }

    updateElementProperty(elementId, property, value) {
        if (!this._activeDocument) return;
        const element = this._activeDocument.elements.find(el => el.id === elementId);
        if (!element) return;

        element[property] = value;
        this.markDirty();
        this._emit('property-changed', { elementId, property, value });
    }

    updateElementPosition(elementId, position) {
        if (!this._activeDocument) return;
        const element = this._activeDocument.elements.find(el => el.id === elementId);
        if (!element) return;

        element.position = { ...position };
        this._emit('position-changed', { elementId, position });
    }

    // --- Edges ---
    addEdge(edge) {
        if (!this._activeDocument) return null;
        const newEdge = {
            id: edge.id || 'edge_' + crypto.randomUUID(),
            source: edge.source,
            target: edge.target
        };
        this._activeDocument.edges.push(newEdge);
        this.markDirty();
        this._emit('edge-added', { edge: newEdge });
        return newEdge;
    }

    removeEdge(edgeId) {
        if (!this._activeDocument) return;
        const idx = this._activeDocument.edges.findIndex(e => e.id === edgeId);
        if (idx === -1) return;

        const removed = this._activeDocument.edges.splice(idx, 1)[0];
        this.markDirty();
        this._emit('edge-removed', { edgeId, edge: removed });
    }

    // --- Selection ---
    get selectedElement() {
        return this._selectedElement;
    }

    setSelection(elementId) {
        this._selectedElement = elementId;
        const element = elementId && this._activeDocument
            ? this._activeDocument.elements.find(el => el.id === elementId)
            : null;
        this._emit('selection-changed', { elementId, element });
    }

    // --- Dirty State ---
    get dirty() {
        return this._dirty;
    }

    markDirty() {
        if (!this._dirty) {
            this._dirty = true;
            this._emit('dirty-changed', { dirty: true });
        }
    }

    markClean() {
        if (this._dirty) {
            this._dirty = false;
            this._emit('dirty-changed', { dirty: false });
        }
    }

    // --- Resolved Configs ---
    getResolvedConfig(type, name) {
        return this._resolvedConfigs.get(`${type}:${name}`);
    }

    setResolvedConfig(type, name, config) {
        this._resolvedConfigs.set(`${type}:${name}`, config);
    }

    // --- Validation ---
    setValidationErrors(errors) {
        this._emit('validation-changed', { errors });
    }

    // --- Helper ---
    _emit(eventName, detail = {}) {
        this.dispatchEvent(new CustomEvent(eventName, { detail }));
    }
}
