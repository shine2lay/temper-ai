/**
 * YamlBridge - Import/export bridge between the MAF Workflow Studio canvas
 * and YAML configuration files.
 *
 * Responsibilities:
 * - Import existing workflow configs from the server into the canvas
 * - Export the current canvas state to YAML configuration format
 * - Provide a raw YAML preview/edit modal for direct YAML manipulation
 * - Save exported configs back to the server
 *
 * Uses the global `jsyaml` object (loaded via CDN as js-yaml) for
 * YAML serialization and parsing.
 */

import { ConfigStore } from './config-store.js';

// --- Constants ---

const STAGE_X_SPACING = 300;
const STAGE_Y_START = 100;
const YAML_DUMP_OPTIONS = { indent: 2, lineWidth: 120, noRefs: true };

/**
 * Extract the agent execution mode from a stage config.
 * Matches the NodeBuilder.get_agent_mode() logic on the backend:
 * checks stage.execution.agent_mode, then execution.agent_mode,
 * defaulting to "sequential".
 * @param {object} stageConfig - The parsed stage configuration.
 * @returns {string} "parallel", "sequential", or "adaptive".
 */
function getAgentMode(stageConfig) {
    if (!stageConfig || typeof stageConfig !== 'object') return 'sequential';
    const inner = stageConfig.stage || stageConfig;
    const execution = inner.execution || {};
    return (typeof execution === 'object' && execution.agent_mode) || 'sequential';
}

/**
 * Extract a clean config name from a stage_ref path.
 * Handles: "configs/stages/foo.yaml" -> "foo",
 *          "foo.yaml" -> "foo", "foo" -> "foo"
 * @param {string} stageRef - The stage_ref value from workflow config.
 * @returns {string} Clean config name for the API.
 */
function extractConfigName(stageRef) {
    if (!stageRef) return '';
    // Strip directory path
    let name = stageRef.includes('/') ? stageRef.split('/').pop() : stageRef;
    // Strip .yaml / .yml extension
    name = name.replace(/\.ya?ml$/i, '');
    return name;
}

// --- YamlBridge ---

export class YamlBridge {
    /**
     * @param {ConfigStore} configStore - The studio config store instance.
     * @param {import('./canvas-manager.js').CanvasManager} canvasManager
     *   - Canvas manager for auto-layout after import.
     */
    constructor(configStore, canvasManager) {
        this._store = configStore;
        this._canvas = canvasManager;

        // Modal DOM elements
        this._modal = document.getElementById('yaml-modal');
        this._editor = document.getElementById('yaml-modal-editor');
        this._closeBtn = document.getElementById('yaml-modal-close');
        this._applyBtn = document.getElementById('yaml-modal-apply');
        this._cancelBtn = document.getElementById('yaml-modal-cancel');

        this._setupModalListeners();
    }

    // --- Modal Listeners ---

    /**
     * Wire close and cancel buttons to hide the modal, and the apply
     * button to parse and re-import edited YAML.
     */
    _setupModalListeners() {
        if (this._closeBtn) {
            this._closeBtn.addEventListener('click', () => this._hideModal());
        }
        if (this._cancelBtn) {
            this._cancelBtn.addEventListener('click', () => this._hideModal());
        }
        if (this._applyBtn) {
            this._applyBtn.addEventListener('click', () => this._applyYamlEdits());
        }
    }

    // --- Import ---

    /**
     * Import a workflow from the server into the canvas.
     *
     * Fetches the workflow config, then iterates over its stage references
     * to fetch each stage and its agents, building a complete document
     * structure for the ConfigStore.
     *
     * @param {string} workflowName - Name of the workflow config to import.
     * @throws {Error} If the workflow fetch fails.
     */
    async importWorkflow(workflowName) {
        // Fetch the workflow config
        const workflowResp = await fetch(
            `/api/studio/configs/workflows/${encodeURIComponent(workflowName)}`
        );
        if (!workflowResp.ok) {
            throw new Error(
                `Failed to fetch workflow "${workflowName}": ${workflowResp.status}`
            );
        }
        const workflowData = await workflowResp.json();
        const workflowConfig = workflowData.workflow;

        if (!workflowConfig) {
            throw new Error(
                `Invalid workflow config for "${workflowName}": missing "workflow" key`
            );
        }

        // Build the document structure
        const doc = {
            type: 'workflow',
            name: workflowConfig.name || workflowName,
            config: { workflow: { ...workflowConfig } },
            elements: [],
            edges: [],
        };

        // Track stage element IDs by stage name for edge creation
        const stageElementMap = new Map();
        const stages = workflowConfig.stages || [];

        for (let i = 0; i < stages.length; i++) {
            const stageEntry = stages[i];
            const stageName = stageEntry.name;
            const stageRef = stageEntry.stage_ref;

            // Generate a deterministic element ID for the stage
            const stageElementId = 'el_stage_' + i + '_' + stageName;

            // Fetch the stage config (extract clean name from path-style refs)
            let stageConfig = {};
            if (stageRef) {
                const cleanRef = extractConfigName(stageRef);
                try {
                    const stageResp = await fetch(
                        `/api/studio/configs/stages/${encodeURIComponent(cleanRef)}`
                    );
                    if (stageResp.ok) {
                        const stageData = await stageResp.json();
                        stageConfig = stageData.stage || stageData;
                    } else {
                        console.warn(
                            `Failed to fetch stage "${cleanRef}" (ref: ${stageRef}): ${stageResp.status}`
                        );
                    }
                } catch (err) {
                    console.warn(`Error fetching stage "${stageRef}":`, err);
                }
            }

            // Extract execution and collaboration info for visual display
            const collaboration = stageConfig.collaboration || {};
            const strategyRaw = collaboration.strategy || '';
            // Extract just the class name from full paths like "src.strategies.dialogue.DialogueOrchestrator"
            const strategy = strategyRaw.includes('.')
                ? strategyRaw.split('.').pop()
                : strategyRaw;

            // Execution mode: parallel, sequential, or adaptive
            const agentMode = getAgentMode(stageConfig);

            // Multi-round: extract max_rounds from collaboration config
            const collabConfig = collaboration.config || {};
            const maxRounds = collabConfig.max_rounds
                || collaboration.max_rounds || 1;

            // Create stage element with visual metadata
            const agents = stageConfig.agents || [];
            const stageElement = {
                id: stageElementId,
                type: 'stage',
                name: stageName,
                config: stageConfig,
                strategy: strategy || 'sequential',
                agentMode,
                maxRounds,
                agentCount: agents.length,
                description: stageConfig.description || '',
                position: { x: i * STAGE_X_SPACING, y: STAGE_Y_START },
            };
            doc.elements.push(stageElement);
            stageElementMap.set(stageName, stageElementId);

            // Determine if agents should be linked with sequential chain arrows
            // based on the execution.agent_mode (matches NodeBuilder.get_agent_mode)
            const agentMode = getAgentMode(stageConfig);
            const isSequential = agentMode === 'sequential';

            // Fetch and create agent elements for this stage
            for (let j = 0; j < agents.length; j++) {
                const agentName = typeof agents[j] === 'string'
                    ? agents[j]
                    : agents[j].name;

                let agentConfig = {};
                try {
                    const agentResp = await fetch(
                        `/api/studio/configs/agents/${encodeURIComponent(agentName)}`
                    );
                    if (agentResp.ok) {
                        const agentData = await agentResp.json();
                        agentConfig = agentData.agent || agentData;
                    } else {
                        console.warn(
                            `Failed to fetch agent "${agentName}": ${agentResp.status}`
                        );
                    }
                } catch (err) {
                    console.warn(`Error fetching agent "${agentName}":`, err);
                }

                // Extract agent visual metadata
                const agentDesc = agentConfig.description || '';
                const agentModel = agentConfig.model || agentConfig.llm_config?.model || '';

                const agentElementId = 'el_agent_' + i + '_' + j + '_' + agentName;
                const agentElement = {
                    id: agentElementId,
                    type: 'agent',
                    name: agentName,
                    parentId: stageElementId,
                    config: agentConfig,
                    description: agentDesc,
                    model: agentModel,
                    position: { x: i * STAGE_X_SPACING, y: STAGE_Y_START + 80 },
                };
                doc.elements.push(agentElement);

                // Add sequential flow edge to previous agent (only for sequential agent_mode)
                if (j > 0 && isSequential) {
                    const prevAgentName = typeof agents[j - 1] === 'string'
                        ? agents[j - 1]
                        : agents[j - 1].name;
                    const prevAgentId = 'el_agent_' + i + '_' + (j - 1) + '_' + prevAgentName;
                    doc.edges.push({
                        id: 'flow_' + prevAgentId + '_' + agentElementId,
                        source: prevAgentId,
                        target: agentElementId,
                        flowType: 'agent-flow',
                    });
                }
            }
        }

        // Create stage dependency edges from depends_on references
        for (let i = 0; i < stages.length; i++) {
            const stageEntry = stages[i];
            const dependsOn = stageEntry.depends_on || [];
            const targetId = stageElementMap.get(stageEntry.name);

            for (const depName of dependsOn) {
                const sourceId = stageElementMap.get(depName);
                if (sourceId && targetId) {
                    doc.edges.push({
                        id: 'edge_' + sourceId + '_' + targetId,
                        source: sourceId,
                        target: targetId,
                        flowType: 'stage-dep',
                        label: 'depends on',
                    });
                }
            }
        }

        // Load the document into the store and auto-layout
        this._store.setActiveDocument(doc);
        this._canvas.autoLayout();
    }

    // --- Export ---

    /**
     * Export the current canvas state to a YAML-compatible config object.
     *
     * Builds the workflow config structure from the active document's
     * elements and edges, producing a format that matches the MAF
     * workflow YAML schema.
     *
     * @returns {{ workflow: object }} The complete workflow config object,
     *   or null if no active document exists.
     */
    exportToYaml() {
        const doc = this._store.activeDocument;
        if (!doc) return null;

        const docWorkflow = (doc.config && doc.config.workflow) || {};
        const elements = doc.elements || [];
        const dependsOnMap = this._buildDependsOnMap();

        // Build stages array from stage elements
        const stageRefs = [];
        for (const el of elements) {
            if (el.type !== 'stage') continue;

            const stageRef = { name: el.name, stage_ref: el.name };

            // Resolve depends_on from edges
            const depSourceIds = dependsOnMap.get(el.id) || [];
            if (depSourceIds.length > 0) {
                const depNames = [];
                for (const srcId of depSourceIds) {
                    const srcElement = elements.find(
                        (e) => e.id === srcId && e.type === 'stage'
                    );
                    if (srcElement) {
                        depNames.push(srcElement.name);
                    }
                }
                if (depNames.length > 0) {
                    stageRef.depends_on = depNames;
                }
            }

            stageRefs.push(stageRef);
        }

        // Assemble workflow config
        const workflowConfig = {
            name: docWorkflow.name || doc.name || 'untitled',
            description: docWorkflow.description || '',
            version: docWorkflow.version || '1.0',
            stages: stageRefs,
        };

        // Preserve error_handling if present
        if (docWorkflow.error_handling) {
            workflowConfig.error_handling = docWorkflow.error_handling;
        }

        const config = { workflow: workflowConfig };

        return config;
    }

    /**
     * Serialize the current workflow to a YAML string.
     *
     * @returns {string} The YAML string, or empty string if no document.
     */
    exportToYamlString() {
        const config = this.exportToYaml();
        if (!config) return '';
        return window.jsyaml.dump(config, YAML_DUMP_OPTIONS);
    }

    // --- Export Individual Configs ---

    /**
     * Export all unique stage configs from the canvas.
     *
     * @returns {Array<{ name: string, yaml: string }>} Array of stage configs
     *   with their YAML serializations.
     */
    exportStageConfigs() {
        const doc = this._store.activeDocument;
        if (!doc) return [];

        const seen = new Set();
        const results = [];

        for (const el of doc.elements) {
            if (el.type !== 'stage') continue;
            if (seen.has(el.name)) continue;
            seen.add(el.name);

            const config = { stage: el.config || {} };
            results.push({
                name: el.name,
                yaml: window.jsyaml.dump(config, YAML_DUMP_OPTIONS),
            });
        }

        return results;
    }

    /**
     * Export all unique agent configs from the canvas.
     *
     * @returns {Array<{ name: string, yaml: string }>} Array of agent configs
     *   with their YAML serializations.
     */
    exportAgentConfigs() {
        const doc = this._store.activeDocument;
        if (!doc) return [];

        const seen = new Set();
        const results = [];

        for (const el of doc.elements) {
            if (el.type !== 'agent') continue;
            if (seen.has(el.name)) continue;
            seen.add(el.name);

            const config = { agent: el.config || {} };
            results.push({
                name: el.name,
                yaml: window.jsyaml.dump(config, YAML_DUMP_OPTIONS),
            });
        }

        return results;
    }

    // --- YAML Preview Modal ---

    /**
     * Open the YAML preview modal with the current workflow exported
     * as a YAML string. The user can view and edit the YAML directly.
     */
    showYamlPreview() {
        const yamlStr = this.exportToYamlString();
        if (this._editor) {
            this._editor.value = yamlStr;
        }
        this._showModal();
    }

    /**
     * Show the modal by removing the 'hidden' class.
     */
    _showModal() {
        if (this._modal) {
            this._modal.classList.remove('hidden');
        }
    }

    /**
     * Hide the modal by adding the 'hidden' class.
     */
    _hideModal() {
        if (this._modal) {
            this._modal.classList.add('hidden');
        }
    }

    /**
     * Parse the edited YAML from the modal textarea, validate it,
     * and re-import the result into the ConfigStore if valid.
     */
    _applyYamlEdits() {
        if (!this._editor) return;

        const yamlText = this._editor.value;
        let parsed;

        try {
            parsed = window.jsyaml.load(yamlText);
        } catch (err) {
            console.error('YAML parse error:', err);
            alert(`Invalid YAML: ${err.message}`);
            return;
        }

        // Validate basic structure
        if (!parsed || typeof parsed !== 'object') {
            alert('YAML must contain a valid mapping/object.');
            return;
        }

        if (!parsed.workflow) {
            alert('YAML must contain a "workflow" key at the top level.');
            return;
        }

        const workflow = parsed.workflow;

        // Rebuild the document from the parsed YAML
        const doc = {
            type: 'workflow',
            name: workflow.name || 'untitled',
            config: { workflow: { ...workflow } },
            elements: [],
            edges: [],
        };

        const stageElementMap = new Map();
        const stages = workflow.stages || [];

        for (let i = 0; i < stages.length; i++) {
            const stageEntry = stages[i];
            const stageName = stageEntry.name || `stage_${i}`;
            const stageElementId = 'el_stage_' + i + '_' + stageName;

            doc.elements.push({
                id: stageElementId,
                type: 'stage',
                name: stageName,
                config: {},
                position: { x: i * STAGE_X_SPACING, y: STAGE_Y_START },
            });
            stageElementMap.set(stageName, stageElementId);
        }

        // Create edges from depends_on
        for (let i = 0; i < stages.length; i++) {
            const stageEntry = stages[i];
            const dependsOn = stageEntry.depends_on || [];
            const stageName = stageEntry.name || `stage_${i}`;
            const targetId = stageElementMap.get(stageName);

            for (const depName of dependsOn) {
                const sourceId = stageElementMap.get(depName);
                if (sourceId && targetId) {
                    doc.edges.push({
                        id: 'edge_' + sourceId + '_' + targetId,
                        source: sourceId,
                        target: targetId,
                    });
                }
            }
        }

        this._store.setActiveDocument(doc);
        this._canvas.autoLayout();
        this._hideModal();
    }

    // --- Save to Server ---

    /**
     * Save the current canvas workflow config to the server.
     *
     * Exports the canvas to a config object and PUTs it to the
     * studio API endpoint.
     *
     * @param {string} name - The workflow name to save as.
     * @returns {Promise<Response>} The fetch response.
     * @throws {Error} If export produces no config or the request fails.
     */
    async saveWorkflow(name) {
        const config = this.exportToYaml();
        if (!config) {
            throw new Error('No active document to save');
        }

        const resp = await fetch(
            `/api/studio/configs/workflows/${encodeURIComponent(name)}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config),
            }
        );

        if (!resp.ok) {
            const detail = await resp.text();
            throw new Error(
                `Failed to save workflow "${name}": ${resp.status} - ${detail}`
            );
        }

        // Mark the store as clean after a successful save
        this._store.markClean();

        return resp;
    }

    // --- Helpers ---

    /**
     * Build a map of targetId -> [sourceIds] from the active document's edges.
     *
     * This is used to resolve depends_on relationships when exporting:
     * each edge represents a dependency where the source stage must
     * complete before the target stage can begin.
     *
     * @returns {Map<string, string[]>} Map from target element ID to
     *   array of source element IDs.
     */
    _buildDependsOnMap() {
        const doc = this._store.activeDocument;
        if (!doc) return new Map();

        const edges = doc.edges || [];
        const map = new Map();

        for (const edge of edges) {
            // Skip agent-flow edges — only stage dependencies matter for export
            if (edge.flowType === 'agent-flow') continue;

            if (!map.has(edge.target)) {
                map.set(edge.target, []);
            }
            map.get(edge.target).push(edge.source);
        }

        return map;
    }
}
