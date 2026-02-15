/**
 * Debate Rounds Panel — Chat-style conversation view for multi-round debate/dialogue.
 * Shows round-by-round agent outputs with convergence indicators and synthesis result.
 */

const DOMPURIFY_CONFIG = {
    ALLOWED_TAGS: [
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'p', 'br', 'hr',
        'ul', 'ol', 'li',
        'strong', 'em', 'code', 'pre',
        'blockquote', 'a', 'table', 'thead',
        'tbody', 'tr', 'th', 'td',
        'del', 'ins', 'sub', 'sup', 'img'
    ],
    ALLOWED_ATTR: ['href', 'title', 'alt', 'src'],
    ALLOW_DATA_ATTR: false,
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick']
};

function sanitizeAndParse(text) {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }
    const html = DOMPurify.sanitize(marked.parse(String(text)), DOMPURIFY_CONFIG);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    for (const a of wrapper.querySelectorAll('a')) {
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
    }
    return wrapper.innerHTML;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

export class DebateRoundsPanel {
    constructor(container, dataStore, eventBus) {
        this.container = container;
        this.dataStore = dataStore;
        this.eventBus = eventBus;
        this._fetching = false;
        this._renderVersion = 0;
        this._changeHandler = (e) => this._onDataChange(e.detail);
        this.dataStore.addEventListener('change', this._changeHandler);
        this.render();
    }

    static get metadata() {
        return { id: 'debate-rounds', title: 'Debate' };
    }

    _onDataChange(detail) {
        console.log('[DebateRounds] _onDataChange:', detail?.changeType);
        // Re-render on snapshot (initial load) and event updates (real-time streaming)
        // Skip only stream content updates
        if (detail && (detail.changeType === 'snapshot' || detail.changeType === 'event')) {
            console.log('[DebateRounds] Rendering...');
            this.render();
        }
    }

    render() {
        this._renderVersion++;
        const version = this._renderVersion;

        this.container.innerHTML = '';

        const debateStages = this._findDebateStages();
        if (debateStages.length === 0) {
            this._renderEmptyState();
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'debate-panel-wrapper';

        for (const stageInfo of debateStages) {
            wrapper.appendChild(this._renderDebateStage(stageInfo));
        }

        this.container.appendChild(wrapper);

        // Fetch full stage data for output_data (dialogue_history)
        for (const stageInfo of debateStages) {
            this._fetchAndRenderStage(stageInfo.id, version);
        }
    }

    _findDebateStages() {
        const stages = [];
        console.log('[DebateRounds] _findDebateStages - checking', this.dataStore.stages.size, 'stages');
        for (const [id, stage] of this.dataStore.stages) {
            // Check collaboration_events for round_number
            const collabEvents = stage.collaboration_events || [];
            const hasRoundEvents = collabEvents.some(e => e.round_number != null);

            // Check agents for input_data.round
            const agents = stage.agents || [];
            const hasRoundAgents = agents.some(a => {
                const input = a.input_data;
                return input && input.round != null;
            });

            if (hasRoundEvents || hasRoundAgents) {
                stages.push({
                    id,
                    name: stage.stage_name || stage.name || 'Debate Stage',
                    stage,
                });
            }
        }
        return stages;
    }

    _renderDebateStage(stageInfo) {
        const section = document.createElement('div');
        section.className = 'debate-stage-section';
        section.dataset.stageId = stageInfo.id;

        const header = document.createElement('div');
        header.className = 'debate-stage-header';
        header.textContent = stageInfo.name;
        section.appendChild(header);

        // Placeholder — will be replaced by _fetchAndRenderStage
        const placeholder = document.createElement('div');
        placeholder.className = 'debate-stage-body loading-spinner';
        section.appendChild(placeholder);

        return section;
    }

    async _fetchAndRenderStage(stageId, version) {
        let stage = this.dataStore.stages.get(stageId);

        // Fetch full stage data from API to get output_data with dialogue_history.
        // Use a local copy — don't mutate the shared dataStore object, as other
        // panels (flowchart) rely on the original snapshot structure.
        try {
            const resp = await fetch(`/api/stages/${stageId}`);
            if (resp.ok) {
                const fresh = await resp.json();
                stage = Object.assign({}, stage || {}, fresh);
            }
        } catch (err) {
            console.warn(`Failed to fetch stage ${stageId}:`, err);
        }

        // Bail if a newer render started while we were fetching
        if (version !== this._renderVersion) return;

        // Find the section in DOM
        const section = this.container.querySelector(`[data-stage-id="${stageId}"]`);
        if (!section) return;

        const body = section.querySelector('.debate-stage-body');
        if (!body) return;

        body.className = 'debate-stage-body';
        body.innerHTML = '';

        // Extract dialogue_history from output_data
        const dialogueHistory = this._extractDialogueHistory(stage);
        const collabEvents = stage.collaboration_events || [];

        if (dialogueHistory && dialogueHistory.length > 0) {
            body.appendChild(this._buildRoundsFromHistory(dialogueHistory, collabEvents, stage));
        } else {
            // Fallback: group agents by input_data.round
            body.appendChild(this._buildRoundsFromAgents(stage));
        }
    }

    _extractDialogueHistory(stage) {
        const output = stage.output_data;
        if (!output) return null;

        // Navigate: output_data.synthesis_result.metadata.dialogue_history
        // or output_data.output.synthesis_result.metadata.dialogue_history
        let synthesis = null;
        if (output.synthesis_result) {
            synthesis = output.synthesis_result;
        } else if (output.output && typeof output.output === 'object' && output.output.synthesis_result) {
            synthesis = output.output.synthesis_result;
        }

        if (!synthesis || !synthesis.metadata) return null;
        return synthesis.metadata.dialogue_history || null;
    }

    _extractSynthesisResult(stage) {
        const output = stage.output_data;
        if (!output) return null;

        if (output.synthesis_result) return output.synthesis_result;
        if (output.output && typeof output.output === 'object' && output.output.synthesis_result) {
            return output.output.synthesis_result;
        }
        return null;
    }

    _buildRoundsFromHistory(history, collabEvents, stage) {
        const container = document.createElement('div');
        container.className = 'debate-rounds-container';

        // Group by round
        const roundMap = new Map();
        for (const entry of history) {
            const round = entry.round != null ? entry.round : 0;
            if (!roundMap.has(round)) roundMap.set(round, []);
            roundMap.get(round).push(entry);
        }

        // Build round-to-collaboration-event map for convergence info
        const roundEventMap = new Map();
        for (const evt of collabEvents) {
            if (evt.round_number != null) {
                roundEventMap.set(evt.round_number, evt);
            }
        }

        const synthesis = this._extractSynthesisResult(stage);
        const totalRounds = synthesis?.metadata?.dialogue_rounds || roundMap.size;

        const sortedRounds = [...roundMap.keys()].sort((a, b) => a - b);
        for (let i = 0; i < sortedRounds.length; i++) {
            const roundNum = sortedRounds[i];
            const entries = roundMap.get(roundNum);
            const collabEvent = roundEventMap.get(roundNum);

            container.appendChild(
                this._buildRoundCard(roundNum, totalRounds, entries, collabEvent)
            );

            // Add convergence indicator between rounds (not after last)
            if (i < sortedRounds.length - 1) {
                const nextEvent = roundEventMap.get(sortedRounds[i + 1]);
                container.appendChild(
                    this._buildConvergenceIndicator(
                        nextEvent?.confidence_score,
                        nextEvent?.outcome
                    )
                );
            }
        }

        // Add synthesis card at the end
        if (synthesis) {
            container.appendChild(this._buildSynthesisCard(synthesis));
        }

        return container;
    }

    _buildRoundCard(roundNum, totalRounds, entries, collabEvent) {
        const card = document.createElement('div');
        card.className = 'debate-round-card';

        // Header
        const header = document.createElement('div');
        header.className = 'debate-round-header';

        const title = document.createElement('span');
        title.className = 'debate-round-title';
        title.textContent = `Round ${roundNum + 1} of ${totalRounds}`;
        header.appendChild(title);

        // Outcome badge
        if (collabEvent && collabEvent.outcome) {
            const badge = document.createElement('span');
            const outcome = collabEvent.outcome;
            let badgeClass = 'tag';
            if (outcome === 'converged') badgeClass += ' tag-success';
            else if (outcome === 'initial') badgeClass += ' tag-info';
            else badgeClass += ' tag-warning';
            badge.className = badgeClass;
            badge.textContent = outcome;
            header.appendChild(badge);
        }

        card.appendChild(header);

        // Consensus summary — show per-agent confidence levels
        if (entries.length > 0) {
            card.appendChild(this._buildConsensusSummary(entries, collabEvent));
        }

        // Agent output cards
        for (const entry of entries) {
            card.appendChild(this._buildAgentOutputCard(entry));
        }

        return card;
    }

    _buildConsensusSummary(entries, collabEvent) {
        const bar = document.createElement('div');
        bar.className = 'consensus-summary';

        // Compute stance distribution from entries or collabEvent
        const stanceDist = this._computeStanceDistribution(entries, collabEvent);
        const hasStances = Object.keys(stanceDist).length > 0;

        // Stance distribution row (primary consensus indicator)
        if (hasStances) {
            const stanceRow = document.createElement('div');
            stanceRow.className = 'consensus-stance-row';

            const total = Object.values(stanceDist).reduce((s, v) => s + v, 0);
            const stanceOrder = ['AGREE', 'PARTIAL', 'DISAGREE'];
            for (const stance of stanceOrder) {
                const count = stanceDist[stance] || 0;
                if (count === 0) continue;
                const badge = document.createElement('span');
                badge.className = 'stance-badge stance-' + stance.toLowerCase();
                badge.textContent = `${stance} ${count}/${total}`;
                stanceRow.appendChild(badge);
            }
            bar.appendChild(stanceRow);
        }

        // Collect per-agent confidence + stance
        const agentConfs = entries.map(entry => ({
            name: entry.agent || 'Agent',
            confidence: entry.confidence != null ? entry.confidence : null,
            stance: entry.stance || '',
        }));

        const validConfs = agentConfs.filter(a => a.confidence != null);
        const minConf = validConfs.length > 0
            ? Math.min(...validConfs.map(a => a.confidence))
            : null;
        const maxConf = validConfs.length > 0
            ? Math.max(...validConfs.map(a => a.confidence))
            : null;
        const spread = (minConf != null && maxConf != null) ? maxConf - minConf : 0;

        // Only show confidence bars when there's meaningful variation (>5pp spread).
        // Auto-calculated confidence is often identical (e.g. all 1.0) and uninformative.
        const showConfidence = validConfs.length > 0 && spread > 0.05;

        if (showConfidence) {
            const avgConf = validConfs.reduce((s, a) => s + a.confidence, 0) / validConfs.length;

            const headerRow = document.createElement('div');
            headerRow.className = 'consensus-header';

            const avgLabel = document.createElement('span');
            avgLabel.className = 'consensus-majority';
            avgLabel.textContent = `Avg confidence: ${(avgConf * 100).toFixed(0)}%`;
            headerRow.appendChild(avgLabel);

            if (validConfs.length > 1) {
                const spreadLabel = document.createElement('span');
                spreadLabel.className = 'consensus-avg-conf';
                spreadLabel.textContent = `Spread: ${(spread * 100).toFixed(0)}pp`;
                spreadLabel.title = `Min: ${(minConf * 100).toFixed(0)}% / Max: ${(maxConf * 100).toFixed(0)}%`;
                headerRow.appendChild(spreadLabel);
            }

            bar.appendChild(headerRow);

            // Per-agent confidence bars
            const agentBars = document.createElement('div');
            agentBars.className = 'consensus-agent-bars';

            const colors = ['var(--accent)', '#ab47bc', 'var(--warning)', 'var(--success)', 'var(--error)'];

            for (let i = 0; i < agentConfs.length; i++) {
                const agent = agentConfs[i];
                if (agent.confidence == null) continue;

                const row = document.createElement('div');
                row.className = 'consensus-agent-row';

                const nameEl = document.createElement('span');
                nameEl.className = 'consensus-agent-name';
                nameEl.textContent = agent.name;
                row.appendChild(nameEl);

                if (agent.stance) {
                    const miniStance = document.createElement('span');
                    miniStance.className = 'stance-badge-mini stance-' + agent.stance.toLowerCase();
                    miniStance.textContent = agent.stance.charAt(0);
                    miniStance.title = agent.stance;
                    row.appendChild(miniStance);
                }

                const barTrack = document.createElement('div');
                barTrack.className = 'consensus-agent-bar-track';

                const barFill = document.createElement('div');
                barFill.className = 'consensus-agent-bar-fill';
                barFill.style.width = `${(agent.confidence * 100).toFixed(0)}%`;
                barFill.style.background = colors[i % colors.length];

                barTrack.appendChild(barFill);
                row.appendChild(barTrack);

                const pctEl = document.createElement('span');
                pctEl.className = 'consensus-agent-pct';
                pctEl.textContent = `${(agent.confidence * 100).toFixed(0)}%`;
                row.appendChild(pctEl);

                agentBars.appendChild(row);
            }

            bar.appendChild(agentBars);
        } else if (!hasStances && validConfs.length > 0) {
            // No stances and no confidence variation — just show a note
            const note = document.createElement('div');
            note.className = 'consensus-header';
            note.innerHTML = '<span class="consensus-avg-conf">All agents responded with equal confidence</span>';
            bar.appendChild(note);
        }

        return bar;
    }

    _computeStanceDistribution(entries, collabEvent) {
        // Prefer backend-computed distribution from collaboration event
        const eventDist = collabEvent?.event_data?.stance_distribution;
        if (eventDist && Object.keys(eventDist).length > 0) {
            return eventDist;
        }

        // Fallback: compute from dialogue_history entries
        const dist = {};
        for (const entry of entries) {
            const stance = (entry.stance || '').toUpperCase();
            if (stance === 'AGREE' || stance === 'DISAGREE' || stance === 'PARTIAL') {
                dist[stance] = (dist[stance] || 0) + 1;
            }
        }
        return dist;
    }

    _buildAgentOutputCard(entry) {
        const card = document.createElement('div');
        card.className = 'agent-output-card';

        // Agent header row
        const headerRow = document.createElement('div');
        headerRow.className = 'agent-output-header';

        const name = document.createElement('span');
        name.className = 'agent-output-name';
        name.textContent = entry.agent || 'Agent';
        headerRow.appendChild(name);

        // Stance badge
        if (entry.stance) {
            const stanceBadge = document.createElement('span');
            stanceBadge.className = 'stance-badge stance-' + entry.stance.toLowerCase();
            stanceBadge.textContent = entry.stance;
            headerRow.appendChild(stanceBadge);
        }

        // Confidence badge
        if (entry.confidence != null) {
            const confBadge = document.createElement('span');
            confBadge.className = 'tag';
            const pct = (entry.confidence * 100).toFixed(0);
            if (entry.confidence >= 0.8) confBadge.className += ' tag-success';
            else if (entry.confidence >= 0.5) confBadge.className += ' tag-warning';
            else confBadge.className += ' tag-error';
            confBadge.textContent = `${pct}%`;
            headerRow.appendChild(confBadge);
        }

        card.appendChild(headerRow);

        // Output body as markdown
        if (entry.output) {
            const outputDiv = document.createElement('div');
            outputDiv.className = 'markdown-content agent-output-body';
            outputDiv.innerHTML = sanitizeAndParse(entry.output);
            card.appendChild(outputDiv);
        }

        // Collapsible reasoning
        if (entry.reasoning) {
            const toggle = document.createElement('div');
            toggle.className = 'reasoning-toggle';
            toggle.textContent = 'Show reasoning';

            const reasoning = document.createElement('div');
            reasoning.className = 'reasoning-content hidden';
            reasoning.innerHTML = sanitizeAndParse(entry.reasoning);

            toggle.addEventListener('click', () => {
                const hidden = reasoning.classList.toggle('hidden');
                toggle.textContent = hidden ? 'Show reasoning' : 'Hide reasoning';
            });

            card.appendChild(toggle);
            card.appendChild(reasoning);
        }

        return card;
    }

    _buildConvergenceIndicator(score, outcome) {
        const indicator = document.createElement('div');
        indicator.className = 'convergence-indicator';

        const line = document.createElement('div');
        line.className = 'convergence-line';

        const label = document.createElement('span');
        label.className = 'convergence-label';
        if (score != null) {
            label.textContent = `Stability: ${(score * 100).toFixed(0)}%`;
        } else {
            label.textContent = 'Next round';
        }

        if (outcome === 'converged') {
            indicator.classList.add('converged');
        }

        indicator.appendChild(line);
        indicator.appendChild(label);
        indicator.appendChild(line.cloneNode());

        return indicator;
    }

    _buildSynthesisCard(synthesis) {
        const card = document.createElement('div');
        card.className = 'synthesis-card';

        const header = document.createElement('div');
        header.className = 'synthesis-header';
        header.textContent = 'Final Synthesis';

        // Metadata tags
        const meta = document.createElement('div');
        meta.className = 'synthesis-meta';

        if (synthesis.method) {
            const methodTag = document.createElement('span');
            methodTag.className = 'tag tag-info';
            methodTag.textContent = synthesis.method;
            meta.appendChild(methodTag);
        }

        if (synthesis.confidence != null) {
            const confTag = document.createElement('span');
            const pct = (synthesis.confidence * 100).toFixed(0);
            confTag.className = 'tag tag-success';
            confTag.textContent = `${pct}% confidence`;
            meta.appendChild(confTag);
        }

        const md = synthesis.metadata || {};
        if (md.dialogue_rounds) {
            const roundsTag = document.createElement('span');
            roundsTag.className = 'tag';
            roundsTag.textContent = `${md.dialogue_rounds} rounds`;
            meta.appendChild(roundsTag);
        }

        if (md.early_stop_reason) {
            const reasonTag = document.createElement('span');
            reasonTag.className = 'tag';
            reasonTag.textContent = md.early_stop_reason;
            meta.appendChild(reasonTag);
        }

        card.appendChild(header);
        card.appendChild(meta);

        // Decision
        if (synthesis.decision) {
            const decision = document.createElement('div');
            decision.className = 'markdown-content synthesis-decision';
            decision.innerHTML = sanitizeAndParse(synthesis.decision);
            card.appendChild(decision);
        }

        // Reasoning (collapsible)
        if (synthesis.reasoning) {
            const toggle = document.createElement('div');
            toggle.className = 'reasoning-toggle';
            toggle.textContent = 'Show reasoning';

            const reasoning = document.createElement('div');
            reasoning.className = 'reasoning-content hidden';
            reasoning.innerHTML = sanitizeAndParse(synthesis.reasoning);

            toggle.addEventListener('click', () => {
                const hidden = reasoning.classList.toggle('hidden');
                toggle.textContent = hidden ? 'Show reasoning' : 'Hide reasoning';
            });

            card.appendChild(toggle);
            card.appendChild(reasoning);
        }

        return card;
    }

    _buildRoundsFromAgents(stage) {
        const container = document.createElement('div');
        container.className = 'debate-rounds-container';

        const agents = stage.agents || [];
        if (agents.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            const text = document.createElement('div');
            text.className = 'empty-text';
            text.textContent = 'No dialogue history available for this stage';
            empty.appendChild(text);
            container.appendChild(empty);
            return container;
        }

        // Group agents by round (agents without input_data.round = round 0)
        const roundMap = new Map();
        for (const agent of agents) {
            const round = (agent.input_data && agent.input_data.round != null)
                ? agent.input_data.round : 0;
            if (!roundMap.has(round)) roundMap.set(round, []);
            roundMap.get(round).push(agent);
        }

        const sortedRounds = [...roundMap.keys()].sort((a, b) => a - b);
        const totalRounds = sortedRounds.length;

        for (const roundNum of sortedRounds) {
            const roundAgents = roundMap.get(roundNum);
            const entries = roundAgents.map(a => ({
                agent: a.agent_name || a.name || 'Agent',
                round: roundNum,
                output: a.output_data?.output || a.output_data?.decision || '',
                reasoning: a.reasoning || a.output_data?.reasoning || '',
                confidence: a.confidence_score ?? a.output_data?.confidence ?? null,
            }));

            container.appendChild(
                this._buildRoundCard(roundNum, totalRounds, entries, null)
            );
        }

        return container;
    }

    _renderEmptyState() {
        const empty = document.createElement('div');
        empty.className = 'empty-state';

        const icon = document.createElement('div');
        icon.className = 'empty-icon';
        icon.textContent = '---';

        const text = document.createElement('div');
        text.className = 'empty-text';
        text.textContent = 'No debate rounds found';

        const subtext = document.createElement('div');
        subtext.className = 'empty-subtext';
        subtext.textContent = 'Debate data will appear when a multi-round debate or dialogue workflow runs';

        empty.appendChild(icon);
        empty.appendChild(text);
        empty.appendChild(subtext);
        this.container.appendChild(empty);
    }

    refresh() {
        this.render();
    }

    destroy() {
        this.dataStore.removeEventListener('change', this._changeHandler);
    }
}
