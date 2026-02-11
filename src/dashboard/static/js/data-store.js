/**
 * Reactive state container for dashboard data.
 * Uses EventTarget for change notification.
 */
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
        this.events.push(event);

        const data = event.data || {};
        switch (event.event_type) {
            case 'workflow_start':
            case 'workflow_end':
                if (this.workflow) Object.assign(this.workflow, data);
                break;
            case 'stage_start':
                this.stages.set(data.stage_id || event.stage_id, data);
                break;
            case 'stage_end': {
                const stage = this.stages.get(data.stage_id || event.stage_id);
                if (stage) Object.assign(stage, data);
                break;
            }
            case 'agent_start':
                this.agents.set(data.agent_id || event.agent_id, data);
                break;
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

    _notify(changeType, detail = null) {
        this.dispatchEvent(new CustomEvent('change', {
            detail: { changeType, ...detail }
        }));
    }
}
