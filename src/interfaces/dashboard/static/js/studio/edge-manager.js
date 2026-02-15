/**
 * EdgeManager - Interactive edge drawing and cycle detection for the
 * MAF Workflow Studio.
 *
 * Uses the cytoscape-edgehandles extension to let users draw dependency
 * edges between stage nodes. Enforces acyclicity via DFS-based cycle
 * detection before any edge is accepted.
 *
 * All edge mutations go through the CommandStack so they are undoable.
 */

import { ConfigStore } from './config-store.js';
import { AddEdgeCommand } from './command-stack.js';

// --- Constants ---

const SNAP_THRESHOLD = 50;

// --- EdgeManager ---

export class EdgeManager {
    /**
     * @param {import('./canvas-manager.js').CanvasManager} canvasManager
     *   - Must expose a `.cy` property returning the Cytoscape instance.
     * @param {ConfigStore} configStore
     *   - Provides `activeDocument.edges` for the current edge list.
     * @param {import('./command-stack.js').CommandStack} commandStack
     *   - Used to execute undoable AddEdgeCommand instances.
     */
    constructor(canvasManager, configStore, commandStack) {
        this._canvasManager = canvasManager;
        this._configStore = configStore;
        this._commandStack = commandStack;
        this._eh = null;

        this._initEdgehandles();
        this.enable();
    }

    // --- Edgehandles Initialization ---

    /**
     * Configure the cytoscape-edgehandles extension on the canvas.
     *
     * The extension adds interactive handles to nodes that let users
     * click-and-drag to draw new edges. We constrain connections to
     * stage-to-stage only, prevent self-loops, duplicates, and cycles.
     *
     * When an edge drawing completes, the auto-added edge is removed
     * from Cytoscape and an AddEdgeCommand is executed instead, so the
     * operation flows through the CommandStack (undo/redo support).
     */
    _initEdgehandles() {
        const cy = this._canvasManager.cy;
        if (!cy) return;

        this._eh = cy.edgehandles({
            canConnect: (sourceNode, targetNode) => {
                // Only stage-to-stage connections
                if (sourceNode.data('type') !== 'stage') return false;
                if (targetNode.data('type') !== 'stage') return false;

                // No self-loops
                if (sourceNode.id() === targetNode.id()) return false;

                // No duplicate edges
                const doc = this._configStore.activeDocument;
                if (doc) {
                    const duplicate = doc.edges.some(
                        (e) =>
                            e.source === sourceNode.id() &&
                            e.target === targetNode.id()
                    );
                    if (duplicate) return false;
                }

                // No cycles
                if (this._wouldCreateCycle(sourceNode.id(), targetNode.id())) {
                    return false;
                }

                return true;
            },

            edgeParams: (sourceNode, targetNode) => {
                return {
                    data: {
                        id: 'edge_' + crypto.randomUUID(),
                        source: sourceNode.id(),
                        target: targetNode.id(),
                    },
                };
            },

            snap: false,
            snapThreshold: SNAP_THRESHOLD,
        });

        // When edgehandles completes a draw, it auto-adds the edge to cy.
        // We remove that edge and route the creation through the CommandStack
        // so it participates in undo/redo.
        cy.on('ehcomplete', (_event, _sourceNode, _targetNode, addedEdge) => {
            const edgeData = {
                id: addedEdge.id(),
                source: addedEdge.data('source'),
                target: addedEdge.data('target'),
                flowType: 'stage-dep',
                label: 'depends on',
            };

            // Remove the edge that edgehandles auto-added
            cy.remove(addedEdge);

            // Execute through the command stack for undo/redo support
            const command = new AddEdgeCommand(this._configStore, edgeData);
            this._commandStack.execute(command);
        });
    }

    // --- Cycle Detection ---

    /**
     * Determine whether adding an edge from sourceId to targetId would
     * create a cycle in the directed graph of stage dependencies.
     *
     * Algorithm:
     *   1. Build an adjacency list from the current edges in the store.
     *   2. Temporarily add the proposed edge (sourceId -> targetId).
     *   3. Run DFS from targetId to see if sourceId is reachable.
     *   4. If reachable, a cycle would be formed.
     *
     * @param {string} sourceId - The proposed edge source node ID.
     * @param {string} targetId - The proposed edge target node ID.
     * @returns {boolean} True if adding this edge would create a cycle.
     */
    _wouldCreateCycle(sourceId, targetId) {
        const doc = this._configStore.activeDocument;
        if (!doc) return false;

        // Build adjacency list from existing stage-dep edges only
        const adjacency = new Map();
        for (const edge of doc.edges) {
            if (edge.flowType === 'agent-flow') continue;
            if (!adjacency.has(edge.source)) {
                adjacency.set(edge.source, []);
            }
            adjacency.get(edge.source).push(edge.target);
        }

        // Temporarily add the proposed edge
        if (!adjacency.has(sourceId)) {
            adjacency.set(sourceId, []);
        }
        adjacency.get(sourceId).push(targetId);

        // DFS from targetId to check if sourceId is reachable
        const visited = new Set();
        const stack = [targetId];

        while (stack.length > 0) {
            const current = stack.pop();

            if (current === sourceId) {
                return true;
            }

            if (visited.has(current)) {
                continue;
            }
            visited.add(current);

            const neighbors = adjacency.get(current);
            if (neighbors) {
                for (const neighbor of neighbors) {
                    if (!visited.has(neighbor)) {
                        stack.push(neighbor);
                    }
                }
            }
        }

        return false;
    }

    // --- Edge Style Helpers ---

    /**
     * Update visual styles on all edges based on state.
     * Reserved for future use (e.g. conditional edge coloring,
     * error highlighting, or animated flow indicators).
     */
    updateEdgeStyles() {
        // No-op for now; edge styling is handled by Cytoscape's
        // stylesheet selectors in canvas-manager.js.
    }

    // --- Enable / Disable ---

    /**
     * Enable interactive edge drawing mode. While enabled, hovering
     * over a stage node shows a drag handle for drawing edges.
     */
    enable() {
        if (this._eh) {
            this._eh.enableDrawMode();
        }
    }

    /**
     * Disable interactive edge drawing mode. Users can still select
     * and delete existing edges, but cannot draw new ones.
     */
    disable() {
        if (this._eh) {
            this._eh.disableDrawMode();
        }
    }

    // --- Cleanup ---

    /**
     * Destroy the edgehandles instance and release resources.
     * Call this when the studio view is torn down to prevent leaks.
     */
    destroy() {
        if (this._eh) {
            this._eh.destroy();
            this._eh = null;
        }
    }
}
