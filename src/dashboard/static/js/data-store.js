/**
 * Reactive state container for dashboard data.
 * Uses EventTarget for change notification.
 */

/**
 * Normalize naive ISO-8601 strings (no timezone suffix) to explicit UTC
 * by appending 'Z'. Strings that already have a timezone indicator are
 * returned unchanged.
 */
export function ensureUTCString(isoString) {
    if (!isoString || typeof isoString !== 'string') return isoString;
    if (/[Zz]$/.test(isoString) || /[+-]\d{2}:\d{2}$/.test(isoString)) return isoString;
    return isoString + 'Z';
}

export class DataStore extends EventTarget {
    constructor() {
        super();
        this.workflow = null;
        this.stages = new Map();
        this.agents = new Map();
        this.llmCalls = new Map();
        this.toolCalls = new Map();
        this.events = [];

        // Streaming state: agent_id -> {content, thinking, done}
        this.streamingContent = new Map();

        // Selection state
        this.selectedStageId = null;
        this.selectedAgentId = null;
        this.selectedLLMCallId = null;
        this.selectedToolCallId = null;
    }

    applySnapshot(snapshot) {
        this.workflow = snapshot;
        this.stages.clear();
        this.agents.clear();
        this.llmCalls.clear();
        this.toolCalls.clear();

        for (const stage of (snapshot.stages || [])) {
            this.stages.set(stage.id, stage);
            for (const agent of (stage.agents || [])) {
                this.agents.set(agent.id, agent);
                for (const llm of (agent.llm_calls || [])) {
                    this.llmCalls.set(llm.id, llm);
                }
                for (const tool of (agent.tool_calls || [])) {
                    this.toolCalls.set(tool.id, tool);
                }
            }
        }

        this._notify('snapshot');
    }

    applyEvent(event) {
        console.log('[DataStore] applyEvent:', event.event_type, event);
        this.events.push(event);

        const data = event.data || {};
        switch (event.event_type) {
            case 'workflow_start':
            case 'workflow_end':
                if (this.workflow) Object.assign(this.workflow, data);
                break;
            case 'stage_start': {
                const stageId = data.stage_id || event.stage_id;
                if (!data.id) data.id = stageId;
                const existingStage = this.stages.get(stageId);
                if (existingStage) {
                    // Merge into existing entry — preserves rich snapshot fields
                    Object.assign(existingStage, data);
                } else {
                    this.stages.set(stageId, data);
                    // Add to workflow.stages array so flowchart can discover new stages
                    if (this.workflow) {
                        if (!this.workflow.stages) this.workflow.stages = [];
                        this.workflow.stages.push(data);
                    }
                }
                break;
            }
            case 'stage_end': {
                const stage = this.stages.get(data.stage_id || event.stage_id);
                if (stage) Object.assign(stage, data);
                break;
            }
            case 'agent_start': {
                const agentId = data.agent_id || event.agent_id;
                if (!data.id) data.id = agentId;
                const existingAgent = this.agents.get(agentId);
                if (existingAgent) {
                    // Merge into existing entry — preserves rich snapshot fields
                    // (llm_calls, tool_calls, tokens, cost, reasoning, config, etc.)
                    Object.assign(existingAgent, data);
                } else {
                    this.agents.set(agentId, data);
                    // Link new agent to its parent stage's agents array
                    if (data.stage_id) {
                        const parentStage = this.stages.get(data.stage_id);
                        if (parentStage) {
                            if (!parentStage.agents) parentStage.agents = [];
                            const exists = parentStage.agents.some(a => a.id === agentId);
                            if (!exists) {
                                parentStage.agents.push(data);
                            }
                        }
                    }
                }
                break;
            }
            case 'agent_end':
            case 'agent_output': {
                const agent = this.agents.get(data.agent_id || event.agent_id);
                if (agent) Object.assign(agent, data);
                break;
            }
            case 'llm_call':
                this.llmCalls.set(data.llm_call_id, data);
                break;
            case 'tool_call':
                this.toolCalls.set(data.tool_execution_id, data);
                break;
            case 'llm_stream_batch':
                this._applyStreamBatch(data.chunks || []);
                return; // Use 'stream' change type instead of 'event'
        }

        this._notify('event', event);
    }

    _applyStreamBatch(chunks) {
        for (const chunk of chunks) {
            const agentId = chunk.agent_id;
            if (!agentId) continue;

            let entry = this.streamingContent.get(agentId);
            if (!entry) {
                entry = { content: '', thinking: '', done: false };
                this.streamingContent.set(agentId, entry);
            }

            if (chunk.chunk_type === 'thinking') {
                entry.thinking += chunk.content;
            } else {
                entry.content += chunk.content;
            }

            if (chunk.done) {
                entry.done = true;
            }
        }

        this._notify('stream');
    }

    select(type, id) {
        switch (type) {
            case 'stage':
                this.selectedStageId = id;
                break;
            case 'agent':
                this.selectedAgentId = id;
                this.selectedLLMCallId = null;
                this.selectedToolCallId = null;
                break;
            case 'llmCall':
                this.selectedLLMCallId = id;
                this.selectedToolCallId = null;
                break;
            case 'toolCall':
                this.selectedToolCallId = id;
                this.selectedLLMCallId = null;
                break;
        }
        this._notify('selection', { type, id });
    }

    clearSelection() {
        this.selectedStageId = null;
        this.selectedAgentId = null;
        this.selectedLLMCallId = null;
        this.selectedToolCallId = null;
        this._notify('selection', { type: null, id: null });
    }

    _notify(changeType, detail = null) {
        console.log('[DataStore] _notify:', changeType, detail);
        this.dispatchEvent(new CustomEvent('change', {
            detail: { changeType, ...detail }
        }));
    }
}
