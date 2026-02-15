/**
 * CommandStack - Undo/redo system using the Command pattern.
 * Each command has execute() and undo() methods.
 * Emits events via EventTarget when stack changes.
 */

const MAX_STACK_SIZE = 100;

// --- Command Classes ---

/**
 * AddNodeCommand - Adds an element to the store.
 */
export class AddNodeCommand {
    constructor(store, element) {
        this.store = store;
        this.element = element;
    }

    execute() {
        const added = this.store.addElement(this.element);
        // Capture the auto-generated ID so undo() can find the element
        if (added && added.id) {
            this.element.id = added.id;
        }
    }

    undo() {
        if (this.element.id) {
            this.store.removeElement(this.element.id);
        }
    }

    get description() {
        return `Add ${this.element.type}: ${this.element.name}`;
    }
}

/**
 * RemoveNodeCommand - Removes an element and its connected edges.
 */
export class RemoveNodeCommand {
    constructor(store, elementId) {
        this.store = store;
        this.elementId = elementId;
        this.element = null;
        this.removedEdges = [];
    }

    execute() {
        const doc = this.store.activeDocument;
        this.element = doc.elements.find(e => e.id === this.elementId);
        
        this.removedEdges = doc.edges.filter(
            e => e.source === this.elementId || e.target === this.elementId
        );
        
        for (const edge of this.removedEdges) {
            this.store.removeEdge(edge.id);
        }
        
        this.store.removeElement(this.elementId);
    }

    undo() {
        this.store.addElement(this.element);
        for (const edge of this.removedEdges) {
            this.store.addEdge(edge);
        }
    }

    get description() {
        return `Remove ${this.element?.type}: ${this.element?.name}`;
    }
}

/**
 * AddEdgeCommand - Adds an edge to the store.
 */
export class AddEdgeCommand {
    constructor(store, edge) {
        this.store = store;
        this.edge = edge;
    }

    execute() {
        this.store.addEdge(this.edge);
    }

    undo() {
        this.store.removeEdge(this.edge.id);
    }

    get description() {
        return `Add edge`;
    }
}

/**
 * RemoveEdgeCommand - Removes an edge from the store.
 */
export class RemoveEdgeCommand {
    constructor(store, edgeId) {
        this.store = store;
        this.edgeId = edgeId;
        this.edge = null;
    }

    execute() {
        const doc = this.store.activeDocument;
        this.edge = doc.edges.find(e => e.id === this.edgeId);
        this.store.removeEdge(this.edgeId);
    }

    undo() {
        this.store.addEdge(this.edge);
    }

    get description() {
        return `Remove edge`;
    }
}

/**
 * MoveNodeCommand - Updates element position.
 */
export class MoveNodeCommand {
    constructor(store, elementId, oldPosition, newPosition) {
        this.store = store;
        this.elementId = elementId;
        this.oldPosition = { ...oldPosition };
        this.newPosition = { ...newPosition };
    }

    execute() {
        this.store.updateElementPosition(this.elementId, this.newPosition);
    }

    undo() {
        this.store.updateElementPosition(this.elementId, this.oldPosition);
    }

    get description() {
        return `Move node`;
    }
}

/**
 * ChangePropertyCommand - Updates a single element property.
 */
export class ChangePropertyCommand {
    constructor(store, elementId, property, oldValue, newValue) {
        this.store = store;
        this.elementId = elementId;
        this.property = property;
        this.oldValue = oldValue;
        this.newValue = newValue;
    }

    execute() {
        this.store.updateElementProperty(this.elementId, this.property, this.newValue);
    }

    undo() {
        this.store.updateElementProperty(this.elementId, this.property, this.oldValue);
    }

    get description() {
        return `Change ${this.property}`;
    }
}

/**
 * ReparentNodeCommand - Changes element parent (for nested stages/agents).
 */
export class ReparentNodeCommand {
    constructor(store, elementId, oldParentId, newParentId) {
        this.store = store;
        this.elementId = elementId;
        this.oldParentId = oldParentId;
        this.newParentId = newParentId;
    }

    execute() {
        this.store.updateElementProperty(this.elementId, 'parentId', this.newParentId);
    }

    undo() {
        this.store.updateElementProperty(this.elementId, 'parentId', this.oldParentId);
    }

    get description() {
        return `Reparent node`;
    }
}

/**
 * CommandStack - Manages undo/redo stacks and command execution.
 */
export class CommandStack extends EventTarget {
    constructor() {
        super();
        this._undoStack = [];
        this._redoStack = [];
    }

    /**
     * Execute a command and add it to the undo stack.
     */
    execute(command) {
        command.execute();
        this._undoStack.push(command);
        this._redoStack = [];
        
        if (this._undoStack.length > MAX_STACK_SIZE) {
            this._undoStack.shift();
        }
        
        this._emit();
    }

    /**
     * Undo the last command.
     */
    undo() {
        if (!this.canUndo) return;
        
        const command = this._undoStack.pop();
        command.undo();
        this._redoStack.push(command);
        this._emit();
    }

    /**
     * Redo the last undone command.
     */
    redo() {
        if (!this.canRedo) return;
        
        const command = this._redoStack.pop();
        command.execute();
        this._undoStack.push(command);
        this._emit();
    }

    /**
     * Check if undo is available.
     */
    get canUndo() {
        return this._undoStack.length > 0;
    }

    /**
     * Check if redo is available.
     */
    get canRedo() {
        return this._redoStack.length > 0;
    }

    /**
     * Get description of next undo command.
     */
    get undoDescription() {
        return this._undoStack.at(-1)?.description ?? '';
    }

    /**
     * Get description of next redo command.
     */
    get redoDescription() {
        return this._redoStack.at(-1)?.description ?? '';
    }

    /**
     * Clear both undo and redo stacks.
     */
    clear() {
        this._undoStack = [];
        this._redoStack = [];
        this._emit();
    }

    /**
     * Emit stack-changed event with current state.
     */
    _emit() {
        this.dispatchEvent(new CustomEvent('stack-changed', {
            detail: {
                canUndo: this.canUndo,
                canRedo: this.canRedo,
                undoDescription: this.undoDescription,
                redoDescription: this.redoDescription,
            }
        }));
    }
}
