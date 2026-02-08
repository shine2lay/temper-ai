"""Helper functions extracted from DialogueOrchestrator to reduce class size.

These are internal implementation details - use DialogueOrchestrator's public API.
"""
import logging
from typing import Any, Dict, List, Optional

from src.constants.probabilities import PROB_MEDIUM, PROB_VERY_HIGH_PLUS
from src.strategies.base import AgentOutput, Conflict, SynthesisResult

logger = logging.getLogger(__name__)


def get_merit_weights(
    agent_outputs: List[AgentOutput],
    merit_domain: Optional[str],
) -> Dict[str, float]:
    """Get merit weights for each agent from observability tracker.

    Queries AgentMeritScore from observability database and converts to weights.
    Falls back to equal weights (1.0) if scores unavailable.

    Args:
        agent_outputs: Agent outputs to get weights for
        merit_domain: Domain for merit score lookup

    Returns:
        Dict mapping agent_name to weight (0.0-1.0+)
    """
    weights = {}

    try:
        from sqlmodel import select

        from src.observability import AgentMeritScore, ExecutionTracker

        tracker = ExecutionTracker()
        if not tracker.backend:
            logger.debug("Observability tracker not initialized, using equal weights")
            return {out.agent_name: 1.0 for out in agent_outputs}

        with tracker.backend.get_session_context() as session:
            for output in agent_outputs:
                agent_name = output.agent_name
                domain = merit_domain or agent_name

                statement = select(AgentMeritScore).where(
                    AgentMeritScore.agent_name == agent_name,
                    AgentMeritScore.domain == domain,
                )
                merit_score = session.exec(statement).first()

                if merit_score and merit_score.expertise_score is not None:
                    weights[agent_name] = merit_score.expertise_score
                    logger.debug(
                        f"Merit weight for {agent_name} in {domain}: "
                        f"{merit_score.expertise_score:.3f}"
                    )
                elif merit_score and merit_score.success_rate is not None:
                    weights[agent_name] = merit_score.success_rate
                    logger.debug(
                        f"Merit weight for {agent_name} (success_rate): "
                        f"{merit_score.success_rate:.3f}"
                    )
                else:
                    weights[agent_name] = PROB_MEDIUM
                    logger.debug(f"No merit score for {agent_name}, using neutral weight {PROB_MEDIUM}")

    except (ImportError, AttributeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to load merit scores: {e}. Using equal weights.")
        weights = {out.agent_name: 1.0 for out in agent_outputs}

    for output in agent_outputs:
        if output.agent_name not in weights:
            weights[output.agent_name] = 1.0

    return weights


def merit_weighted_synthesis(
    agent_outputs: List[AgentOutput],
    merit_domain: Optional[str],
) -> SynthesisResult:
    """Synthesize decision using merit-weighted voting.

    Higher-merit agents have more influence on the final decision.
    Merit scores are multiplied by confidence to get weighted votes.

    Args:
        agent_outputs: Agent outputs from final round
        merit_domain: Domain for merit score lookup

    Returns:
        SynthesisResult with merit-weighted decision
    """
    from collections import defaultdict

    merit_weights = get_merit_weights(agent_outputs, merit_domain)

    weighted_votes = defaultdict(float)
    agent_votes = {}

    for output in agent_outputs:
        decision = output.decision
        agent_name = output.agent_name
        confidence = output.confidence
        merit_weight = merit_weights.get(agent_name, 1.0)

        vote_weight = merit_weight * confidence
        weighted_votes[decision] += vote_weight
        agent_votes[agent_name] = decision

    if not weighted_votes:
        raise ValueError("No votes recorded")

    winning_decision = max(weighted_votes, key=weighted_votes.get)
    total_weight = sum(weighted_votes.values())
    decision_support = weighted_votes[winning_decision] / total_weight if total_weight > 0 else 0

    supporting_agents = [
        out for out in agent_outputs if out.decision == winning_decision
    ]
    if supporting_agents:
        weighted_conf_sum = sum(
            out.confidence * merit_weights.get(out.agent_name, 1.0)
            for out in supporting_agents
        )
        weight_sum = sum(
            merit_weights.get(out.agent_name, 1.0)
            for out in supporting_agents
        )
        avg_confidence = weighted_conf_sum / weight_sum if weight_sum > 0 else 0
        final_confidence = decision_support * avg_confidence
    else:
        final_confidence = PROB_MEDIUM

    reasoning = build_merit_weighted_reasoning(
        winning_decision,
        decision_support,
        agent_outputs,
        merit_weights,
        weighted_votes,
    )

    conflicts = []
    if len(weighted_votes) > 1:
        all_agents = [out.agent_name for out in agent_outputs]
        all_decisions = list(weighted_votes.keys())
        disagreement_score = 1.0 - decision_support

        conflicts.append(Conflict(
            agents=all_agents,
            decisions=all_decisions,
            disagreement_score=disagreement_score,
            context={"weighted_votes": dict(weighted_votes)},
        ))

    metadata = {
        "total_agents": len(agent_outputs),
        "decision_support": decision_support,
        "merit_weights": merit_weights,
        "weighted_votes": dict(weighted_votes),
        "supporters": [out.agent_name for out in supporting_agents],
        "dissenters": [out.agent_name for out in agent_outputs if out.decision != winning_decision],
    }

    vote_counts = {
        decision: len([o for o in agent_outputs if o.decision == decision])
        for decision in weighted_votes.keys()
    }

    return SynthesisResult(
        decision=winning_decision,
        confidence=final_confidence,
        method="merit_weighted",
        votes=vote_counts,
        conflicts=conflicts,
        reasoning=reasoning,
        metadata=metadata,
    )


def build_merit_weighted_reasoning(
    decision: Any,
    support: float,
    agent_outputs: List[AgentOutput],
    merit_weights: Dict[str, float],
    weighted_votes: Dict[Any, float],
) -> str:
    """Build reasoning explanation for merit-weighted synthesis.

    Args:
        decision: Winning decision
        support: Decision support (0.0-1.0)
        agent_outputs: All agent outputs
        merit_weights: Merit weights by agent
        weighted_votes: Weighted vote totals by decision

    Returns:
        Human-readable reasoning string
    """
    supporters = [out for out in agent_outputs if out.decision == decision]
    supporter_names = [
        f"{out.agent_name} (merit: {merit_weights.get(out.agent_name, 1.0):.2f})"
        for out in supporters
    ]

    reasoning = f"Merit-weighted decision: '{decision}' with {support:.1%} weighted support.\n\n"

    reasoning += f"Supporters ({len(supporters)}/{len(agent_outputs)}): "
    reasoning += ", ".join(supporter_names) + "\n\n"

    if len(weighted_votes) > 1:
        reasoning += "Weighted vote breakdown:\n"
        for dec, weight in sorted(weighted_votes.items(), key=lambda x: x[1], reverse=True):
            percentage = (weight / sum(weighted_votes.values())) * 100
            reasoning += f"  - '{dec}': {weight:.2f} ({percentage:.1f}%)\n"

    reasoning += "\nNote: Votes weighted by agent merit scores and confidence."

    return reasoning


def curate_recent(
    dialogue_history: List[Dict[str, Any]],
    current_round: int,
    context_window_size: int,
) -> List[Dict[str, Any]]:
    """Curate history to recent rounds only (sliding window).

    Args:
        dialogue_history: Full dialogue history
        current_round: Current round number
        context_window_size: Number of recent rounds to include

    Returns:
        Recent rounds only
    """
    rounds_dict = {}
    for entry in dialogue_history:
        round_num = entry["round"]
        if round_num not in rounds_dict:
            rounds_dict[round_num] = []
        rounds_dict[round_num].append(entry)

    all_rounds = sorted(rounds_dict.keys())
    recent_rounds = all_rounds[-context_window_size:] if all_rounds else []

    curated = []
    for round_num in recent_rounds:
        curated.extend(rounds_dict[round_num])

    logger.debug(
        f"Context curation (recent): {len(dialogue_history)} entries -> "
        f"{len(curated)} entries (last {len(recent_rounds)} rounds)"
    )

    return curated


def curate_relevant(
    dialogue_history: List[Dict[str, Any]],
    agent_name: Optional[str],
    context_window_size: int,
) -> List[Dict[str, Any]]:
    """Curate history to entries relevant to current agent.

    Uses keyword matching and agent participation to filter relevant history.
    Falls back to recent strategy if agent_name not provided.

    Args:
        dialogue_history: Full dialogue history
        agent_name: Name of current agent
        context_window_size: Window size for recent fallback

    Returns:
        Relevant history entries
    """
    if not agent_name:
        logger.debug("No agent_name for relevance filtering, using recent strategy")
        return curate_recent(dialogue_history, len(dialogue_history), context_window_size)

    curated = []
    latest_round = max((entry["round"] for entry in dialogue_history), default=0)

    for entry in dialogue_history:
        if entry["round"] == latest_round:
            curated.append(entry)
            continue
        if entry["agent"] == agent_name:
            curated.append(entry)
            continue
        reasoning = str(entry.get("reasoning", "")).lower()
        if agent_name.lower() in reasoning:
            curated.append(entry)
            continue

    if len(curated) < 2:
        logger.debug(
            f"Relevance filtering produced too little context ({len(curated)} entries), "
            f"using recent strategy"
        )
        return curate_recent(dialogue_history, len(dialogue_history), context_window_size)

    logger.debug(
        f"Context curation (relevant for {agent_name}): "
        f"{len(dialogue_history)} entries -> {len(curated)} entries"
    )

    return curated


def calculate_semantic_similarity(
    current_outputs: List[AgentOutput],
    previous_outputs: List[AgentOutput],
    get_embedding_model_fn,
) -> float:
    """Calculate semantic similarity between current and previous outputs.

    Args:
        current_outputs: Outputs from current round
        previous_outputs: Outputs from previous round
        get_embedding_model_fn: Callable to get the embedding model

    Returns:
        Similarity score (0.0-1.0)
    """
    from sentence_transformers.util import cos_sim

    model = get_embedding_model_fn()
    if model is None:
        raise RuntimeError("Failed to load SentenceTransformer model")

    prev_decisions = {out.agent_name: out.decision for out in previous_outputs}
    curr_decisions = {out.agent_name: out.decision for out in current_outputs}

    common_agents = set(prev_decisions.keys()) & set(curr_decisions.keys())
    if not common_agents:
        return 0.0

    similar_count = 0
    for agent in common_agents:
        prev_text = str(prev_decisions[agent])
        curr_text = str(curr_decisions[agent])

        if prev_text == curr_text:
            similar_count += 1
            continue

        embeddings = model.encode([prev_text, curr_text])
        similarity = cos_sim(embeddings[0], embeddings[1]).item()

        if similarity >= PROB_VERY_HIGH_PLUS:
            similar_count += 1
            logger.debug(
                f"Agent {agent} semantically similar: {similarity:.3f} "
                f"(prev: '{prev_text[:50]}...', curr: '{curr_text[:50]}...')"
            )

    return similar_count / len(common_agents)


def calculate_exact_match_convergence(
    current_outputs: List[AgentOutput],
    previous_outputs: List[AgentOutput],
) -> float:
    """Calculate exact match convergence between current and previous outputs.

    Args:
        current_outputs: Outputs from current round
        previous_outputs: Outputs from previous round

    Returns:
        Convergence score (0.0-1.0)
    """
    prev_decisions = {out.agent_name: out.decision for out in previous_outputs}
    curr_decisions = {out.agent_name: out.decision for out in current_outputs}

    common_agents = set(prev_decisions.keys()) & set(curr_decisions.keys())
    if not common_agents:
        return 0.0

    unchanged = sum(
        1 for agent in common_agents
        if str(prev_decisions[agent]) == str(curr_decisions[agent])
    )

    return unchanged / len(common_agents)
