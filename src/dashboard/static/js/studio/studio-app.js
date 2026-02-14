/**
 * Studio App - Entry point for the MAF Workflow Studio.
 *
 * Wires all studio modules together and handles page initialization.
 * Loaded by studio.html via <script type="module" src="js/studio/studio-app.js">.
 *
 * Responsibilities:
 * - Instantiate all studio modules in dependency order
 * - Load config catalogs from the server
 * - Handle URL parameters for loading existing workflows
 * - Wire the canvas drop handler to create elements via CommandStack
 * - Guard against unsaved changes on page unload
 */

import { ConfigStore } from './config-store.js';
import { SchemaRegistry } from './schema-registry.js';
import { CommandStack } from './command-stack.js';
import { CanvasManager } from './canvas-manager.js';
import { Palette } from './palette.js';
import { FormBuilder } from './form-builder.js';
import { PropertyPanel } from './property-panel.js';
import { EdgeManager } from './edge-manager.js';
import { YamlBridge } from './yaml-bridge.js';
import { Toolbar } from './toolbar.js';
import { ValidationDisplay } from './validation-display.js';
import { AddNodeCommand } from './command-stack.js';

/**
 * Initialize the Workflow Studio application.
 *
 * Creates all module instances in dependency order, loads catalogs,
 * handles URL-based workflow import, and wires up the drop handler
 * and unsaved-changes guard.
 */
async function init() {
    // --- 1. Create instances in dependency order ---

    const configStore = new ConfigStore();
    const schemaRegistry = new SchemaRegistry();
    const commandStack = new CommandStack();
    const canvasManager = new CanvasManager('cy-studio', configStore);
    const formBuilder = new FormBuilder(schemaRegistry);
    const palette = new Palette(configStore);
    const yamlBridge = new YamlBridge(configStore, canvasManager);
    const propertyPanel = new PropertyPanel(configStore, schemaRegistry, formBuilder, commandStack);
    const edgeManager = new EdgeManager(canvasManager, configStore, commandStack);
    const toolbar = new Toolbar(configStore, commandStack, canvasManager, yamlBridge);
    const validationDisplay = new ValidationDisplay(configStore, canvasManager);

    // --- 2. Load catalogs from the server ---

    await configStore.loadCatalogs();

    // --- 3. Handle URL parameters ---

    const params = new URLSearchParams(window.location.search);
    const workflowParam = params.get('workflow');

    if (workflowParam) {
        await yamlBridge.importWorkflow(workflowParam);
    } else {
        configStore.newWorkflow('untitled');
    }

    // --- 4. Wire canvas drop handler ---

    canvasManager.cy.on('studio:drop', (event, extraData) => {
        handleDrop(extraData, configStore, commandStack, canvasManager);
    });

    // --- 5. Wire palette workflow loading ---

    configStore.addEventListener('palette-load-workflow', async (event) => {
        const { name } = event.detail;
        if (configStore.dirty) {
            if (!confirm('You have unsaved changes. Load this workflow anyway?')) {
                return;
            }
        }
        try {
            await yamlBridge.importWorkflow(name);
        } catch (err) {
            console.error(`Failed to load workflow "${name}":`, err);
        }
    });

    // --- 6. Unsaved changes guard ---

    window.addEventListener('beforeunload', (event) => {
        if (configStore.dirty) {
            event.returnValue = 'You have unsaved changes.';
            return 'You have unsaved changes.';
        }
    });
}

/**
 * Handle a palette item dropped onto the canvas.
 *
 * Fetches the config for the dropped item from the server and
 * creates the appropriate element via an AddNodeCommand on the
 * CommandStack.
 *
 * @param {{ data: { type: string, name: string }, position: { x: number, y: number } }} dropData
 *   - The drop event payload from CanvasManager.
 * @param {ConfigStore} configStore - The studio config store.
 * @param {CommandStack} commandStack - The undo/redo command stack.
 * @param {CanvasManager} canvasManager - The Cytoscape canvas manager.
 */
async function handleDrop(dropData, configStore, commandStack, canvasManager) {
    const { data, position } = dropData;

    try {
        if (data.type === 'stages') {
            const resp = await fetch(
                `/api/studio/configs/stages/${encodeURIComponent(data.name)}`
            );
            if (!resp.ok) {
                console.error(`Failed to fetch stage "${data.name}": ${resp.status}`);
                return;
            }
            const stageData = await resp.json();
            const element = {
                type: 'stage',
                name: data.name,
                config: stageData.stage || {},
                position,
            };
            commandStack.execute(new AddNodeCommand(configStore, element));
        } else if (data.type === 'agents') {
            // Find the stage node at the drop position
            const stageId = findStageAtPosition(canvasManager, position);

            const resp = await fetch(
                `/api/studio/configs/agents/${encodeURIComponent(data.name)}`
            );
            if (!resp.ok) {
                console.error(`Failed to fetch agent "${data.name}": ${resp.status}`);
                return;
            }
            const agentData = await resp.json();
            const element = {
                type: 'agent',
                name: data.name,
                parentId: stageId || null,
                config: agentData.agent || {},
                position,
            };
            commandStack.execute(new AddNodeCommand(configStore, element));
        }
    } catch (err) {
        console.error('Drop handler error:', err);
    }
}

/**
 * Find a stage compound node at the given canvas position.
 *
 * Iterates over all stage-type nodes on the canvas and checks
 * whether the given position falls within their bounding box.
 *
 * @param {CanvasManager} canvasManager - The Cytoscape canvas manager.
 * @param {{ x: number, y: number }} position - Canvas coordinates to check.
 * @returns {string|null} The ID of the stage node at the position, or null.
 */
function findStageAtPosition(canvasManager, position) {
    const cy = canvasManager.cy;
    if (!cy) return null;

    const stageNodes = cy.nodes('[type="stage"]');

    for (let i = 0; i < stageNodes.length; i++) {
        const node = stageNodes[i];
        const bb = node.boundingBox();
        if (
            position.x >= bb.x1 &&
            position.x <= bb.x2 &&
            position.y >= bb.y1 &&
            position.y <= bb.y2
        ) {
            return node.id();
        }
    }

    return null;
}

// --- Bootstrap ---

init().catch((err) => {
    console.error('MAF Studio initialization failed:', err);

    // Show a user-visible error in the canvas area
    const canvasContainer = document.getElementById('cy-studio');
    if (canvasContainer) {
        canvasContainer.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.style.cssText =
            'display:flex;align-items:center;justify-content:center;' +
            'height:100%;color:#ef5350;font-size:16px;padding:32px;text-align:center;';
        errorDiv.textContent =
            'Failed to initialize Workflow Studio. Check the browser console for details.';
        canvasContainer.appendChild(errorDiv);
    }
});
