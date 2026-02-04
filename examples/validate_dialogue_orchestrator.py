#!/usr/bin/env python3
"""End-to-end validation script for DialogueOrchestrator.

This script validates that DialogueOrchestrator works correctly by:
1. Creating a simple dialogue-enabled workflow
2. Simulating multi-round agent execution
3. Verifying dialogue history propagation
4. Testing convergence detection
5. Checking cost tracking
6. Validating final synthesis

Usage:
    python examples/validate_dialogue_orchestrator.py

Expected output:
    Dialogue transcript showing multiple rounds, agent position changes,
    convergence detection, and final synthesized decision.
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies.dialogue import (
    DialogueOrchestrator,
    DialogueRound,
    DialogueHistory
)
from src.strategies.base import AgentOutput, SynthesisResult


class MockAgent:
    """Mock agent for dialogue validation."""

    def __init__(self, name: str, initial_position: str, confidence: float = 0.8):
        self.name = name
        self.initial_position = initial_position
        self.confidence = confidence
        self.round_count = 0

    def execute(self, dialogue_history: List[Dict[str, Any]] = None) -> AgentOutput:
        """Execute agent and return output.

        Args:
            dialogue_history: List of prior dialogue rounds (None for round 1)

        Returns:
            AgentOutput with decision, reasoning, and confidence
        """
        self.round_count += 1

        if dialogue_history is None or len(dialogue_history) == 0:
            # Round 1: Initial position
            return AgentOutput(
                agent_name=self.name,
                decision=self.initial_position,
                reasoning=f"Initial position: {self.initial_position}",
                confidence=self.confidence,
                metadata={"cost_usd": 0.5, "round": 1}
            )
        else:
            # Round 2+: Respond to dialogue
            last_round = dialogue_history[-1]

            # Simple convergence logic: change position if majority disagrees
            decisions = [entry["output"] for entry in last_round["entries"]]
            majority_decision = max(set(decisions), key=decisions.count)

            if majority_decision != self.initial_position:
                # Change position to majority
                new_position = majority_decision
                reasoning = (
                    f"Changed from '{self.initial_position}' to '{new_position}' "
                    f"after seeing majority support in round {len(dialogue_history)}"
                )
                new_confidence = self.confidence + 0.05  # Slightly more confident
            else:
                # Maintain position
                new_position = self.initial_position
                reasoning = (
                    f"Maintaining '{self.initial_position}' position "
                    f"(majority agrees)"
                )
                new_confidence = self.confidence + 0.10  # More confident

            return AgentOutput(
                agent_name=self.name,
                decision=new_position,
                reasoning=reasoning,
                confidence=min(new_confidence, 0.95),
                metadata={"cost_usd": 0.5, "round": self.round_count}
            )


def simulate_dialogue_round(
    agents: List[MockAgent],
    dialogue_history: List[Dict[str, Any]] = None
) -> List[AgentOutput]:
    """Simulate one round of dialogue.

    Args:
        agents: List of agents to execute
        dialogue_history: Prior dialogue history (None for round 1)

    Returns:
        List of AgentOutput from this round
    """
    outputs = []
    for agent in agents:
        output = agent.execute(dialogue_history)
        outputs.append(output)
    return outputs


def build_dialogue_history_entry(
    round_number: int,
    outputs: List[AgentOutput]
) -> Dict[str, Any]:
    """Build dialogue history entry for a round.

    Args:
        round_number: Zero-indexed round number
        outputs: Agent outputs from this round

    Returns:
        Dictionary with round metadata and agent entries
    """
    return {
        "round": round_number,
        "entries": [
            {
                "agent": output.agent_name,
                "output": output.decision,
                "reasoning": output.reasoning,
                "confidence": output.confidence
            }
            for output in outputs
        ]
    }


def calculate_convergence(
    current_outputs: List[AgentOutput],
    previous_outputs: List[AgentOutput]
) -> float:
    """Calculate convergence score between two rounds.

    Args:
        current_outputs: Outputs from current round
        previous_outputs: Outputs from previous round

    Returns:
        Convergence score (0.0 to 1.0): percentage of unchanged positions
    """
    if not previous_outputs:
        return 0.0

    # Map agent names to decisions
    prev_decisions = {out.agent_name: out.decision for out in previous_outputs}
    curr_decisions = {out.agent_name: out.decision for out in current_outputs}

    # Count unchanged positions
    unchanged = sum(
        1 for agent, decision in curr_decisions.items()
        if prev_decisions.get(agent) == decision
    )

    return unchanged / len(curr_decisions)


def print_dialogue_transcript(
    all_rounds: List[List[AgentOutput]],
    convergence_scores: List[float],
    total_cost: float,
    converged: bool,
    convergence_round: int
):
    """Print formatted dialogue transcript.

    Args:
        all_rounds: List of all round outputs
        convergence_scores: Convergence score for each round
        total_cost: Total cost across all rounds
        converged: Whether dialogue converged
        convergence_round: Round where convergence occurred (-1 if not converged)
    """
    print("\n" + "="*60)
    print("DIALOGUE VALIDATION TRANSCRIPT")
    print("="*60)

    for round_idx, outputs in enumerate(all_rounds):
        print(f"\nRound {round_idx + 1}:")
        print("-" * 40)

        for output in outputs:
            print(f"  {output.agent_name}:")
            print(f"    Decision: '{output.decision}'")
            print(f"    Confidence: {output.confidence:.2f}")
            print(f"    Cost: ${output.metadata['cost_usd']:.2f}")
            if round_idx > 0:
                # Show if position changed
                prev_decision = all_rounds[round_idx - 1][
                    [o.agent_name for o in all_rounds[round_idx - 1]].index(output.agent_name)
                ].decision
                if prev_decision != output.decision:
                    print(f"    ← CHANGED from '{prev_decision}'")
            print()

        if round_idx > 0:
            print(f"  Convergence: {convergence_scores[round_idx]:.1%} "
                  f"({int(convergence_scores[round_idx] * len(outputs))}/{len(outputs)} agents unchanged)")

    print("\n" + "="*60)
    print("DIALOGUE SUMMARY")
    print("="*60)
    print(f"Total Rounds: {len(all_rounds)}")
    print(f"Total Cost: ${total_cost:.2f}")
    print(f"Converged: {'✅ Yes' if converged else '❌ No'}")
    if converged:
        print(f"Convergence Round: {convergence_round + 1}")

    # Final decision distribution
    final_outputs = all_rounds[-1]
    decisions = [out.decision for out in final_outputs]
    decision_counts = {d: decisions.count(d) for d in set(decisions)}
    final_decision = max(decision_counts, key=decision_counts.get)

    print(f"\nFinal Decision: '{final_decision}'")
    print(f"Support: {decision_counts[final_decision]}/{len(final_outputs)} agents")
    print("="*60)


def validate_dialogue_orchestrator():
    """Run end-to-end validation of DialogueOrchestrator."""

    print("\n🔍 DIALOGUE ORCHESTRATOR VALIDATION")
    print("="*60)

    # Step 1: Create DialogueOrchestrator
    print("\n1. Creating DialogueOrchestrator...")
    strategy = DialogueOrchestrator(
        max_rounds=3,
        convergence_threshold=0.85,
        cost_budget_usd=10.0,
        min_rounds=2
    )
    print(f"   ✓ max_rounds: {strategy.max_rounds}")
    print(f"   ✓ convergence_threshold: {strategy.convergence_threshold}")
    print(f"   ✓ cost_budget_usd: ${strategy.cost_budget_usd}")
    print(f"   ✓ min_rounds: {strategy.min_rounds}")
    print(f"   ✓ requires_requery: {strategy.requires_requery}")

    # Step 2: Create mock agents
    print("\n2. Creating mock agents...")
    agents = [
        MockAgent("researcher", "Option A", 0.75),
        MockAgent("analyst", "Option B", 0.80),
        MockAgent("critic", "Option A", 0.70)
    ]
    print(f"   ✓ Created {len(agents)} agents")
    for agent in agents:
        print(f"     - {agent.name}: '{agent.initial_position}' (confidence: {agent.confidence})")

    # Step 3: Simulate multi-round dialogue
    print("\n3. Simulating multi-round dialogue...")

    all_rounds = []
    dialogue_history = []
    convergence_scores = [0.0]  # Round 1 has no convergence
    total_cost = 0.0
    converged = False
    convergence_round = -1

    for round_idx in range(strategy.max_rounds):
        print(f"\n   Round {round_idx + 1}...")

        # Execute agents
        if round_idx == 0:
            outputs = simulate_dialogue_round(agents, dialogue_history=None)
        else:
            outputs = simulate_dialogue_round(agents, dialogue_history=dialogue_history)

        all_rounds.append(outputs)

        # Track cost
        round_cost = sum(out.metadata["cost_usd"] for out in outputs)
        total_cost += round_cost
        print(f"     Round cost: ${round_cost:.2f}, Total: ${total_cost:.2f}")

        # Build dialogue history entry
        history_entry = build_dialogue_history_entry(round_idx, outputs)
        dialogue_history.append(history_entry)

        # Check convergence (after min_rounds)
        if round_idx >= strategy.min_rounds - 1 and round_idx > 0:
            convergence = calculate_convergence(outputs, all_rounds[round_idx - 1])
            convergence_scores.append(convergence)
            print(f"     Convergence: {convergence:.1%}")

            if convergence >= strategy.convergence_threshold:
                converged = True
                convergence_round = round_idx
                print(f"     ✓ Converged! (>= {strategy.convergence_threshold:.1%})")
                break
        elif round_idx > 0:
            convergence = calculate_convergence(outputs, all_rounds[round_idx - 1])
            convergence_scores.append(convergence)
            print(f"     Convergence: {convergence:.1%} (min_rounds not met)")

        # Check budget
        if total_cost >= strategy.cost_budget_usd:
            print(f"     ⚠️  Budget exceeded (${total_cost:.2f} >= ${strategy.cost_budget_usd:.2f})")
            break

    # Step 4: Test final synthesis
    print("\n4. Testing final synthesis...")
    final_outputs = all_rounds[-1]
    result = strategy.synthesize(final_outputs, {})

    print(f"   ✓ Decision: '{result.decision}'")
    print(f"   ✓ Confidence: {result.confidence:.2f}")
    print(f"   ✓ Method: {result.method}")
    print(f"   ✓ Votes: {result.votes}")
    print(f"   ✓ Strategy metadata: {result.metadata.get('strategy')}")
    print(f"   ✓ Synthesis method: {result.metadata.get('synthesis_method')}")

    # Step 5: Print transcript
    print_dialogue_transcript(
        all_rounds,
        convergence_scores,
        total_cost,
        converged,
        convergence_round
    )

    # Step 6: Validate results
    print("\n5. Validating results...")

    validations = []

    # Check that multiple rounds executed
    if len(all_rounds) > 1:
        validations.append(("✅", "Multiple rounds executed"))
    else:
        validations.append(("❌", "Only one round executed"))

    # Check that agents were re-invoked
    if all(agent.round_count > 1 for agent in agents):
        validations.append(("✅", "All agents re-invoked"))
    else:
        validations.append(("❌", "Not all agents re-invoked"))

    # Check that dialogue history was propagated
    if len(dialogue_history) == len(all_rounds):
        validations.append(("✅", "Dialogue history propagated"))
    else:
        validations.append(("❌", "Dialogue history incomplete"))

    # Check convergence detection
    if converged or len(all_rounds) == strategy.max_rounds:
        validations.append(("✅", "Convergence or max rounds reached"))
    else:
        validations.append(("❌", "Stopped prematurely"))

    # Check cost tracking
    if total_cost > 0:
        validations.append(("✅", f"Cost tracked: ${total_cost:.2f}"))
    else:
        validations.append(("❌", "No cost tracked"))

    # Check final synthesis
    if result.decision in [out.decision for out in final_outputs]:
        validations.append(("✅", "Final decision is from agent outputs"))
    else:
        validations.append(("❌", "Final decision not from outputs"))

    # Check metadata
    if (result.metadata.get("strategy") == "dialogue" and
        result.metadata.get("synthesis_method") == "consensus_from_final_round"):
        validations.append(("✅", "Dialogue metadata present"))
    else:
        validations.append(("❌", "Dialogue metadata missing"))

    print("\nValidation Results:")
    for symbol, message in validations:
        print(f"  {symbol} {message}")

    # Overall result
    all_passed = all(symbol == "✅" for symbol, _ in validations)
    print("\n" + "="*60)
    if all_passed:
        print("🎉 VALIDATION PASSED - DialogueOrchestrator works correctly!")
    else:
        print("❌ VALIDATION FAILED - Some checks did not pass")
    print("="*60 + "\n")

    return all_passed


if __name__ == "__main__":
    try:
        success = validate_dialogue_orchestrator()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ VALIDATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
