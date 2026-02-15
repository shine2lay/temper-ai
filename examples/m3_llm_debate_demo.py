"""
M3 LLM-Powered Debate Demo

This demo uses ACTUAL LLM calls to simulate multi-agent debate.
Agents are real LLMs that can change their minds based on debate context.

Requirements:
- Ollama installed and running (http://localhost:11434)
- Model downloaded: ollama pull llama3.2:3b

Usage:
    python3 examples/m3_llm_debate_demo.py              # Verbose mode (default)
    python3 examples/m3_llm_debate_demo.py --quiet      # Quiet mode (no prompts/responses)
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from src.agent.llm_providers import LLMResponse, OllamaLLM

console = Console()


@dataclass
class DebateAgent:
    """Agent participating in debate."""
    name: str
    role: str
    initial_position: str
    initial_reasoning: str
    persona: str  # LLM persona/system prompt


class LLMDebateSimulator:
    """Simulates multi-round debate using actual LLM calls."""

    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        max_rounds: int = 3,
        convergence_threshold: float = 0.8,
        verbose: bool = False
    ):
        """Initialize debate simulator with LLM.

        Args:
            model: Ollama model to use
            base_url: Ollama server URL
            temperature: LLM temperature (higher = more creative)
            max_rounds: Maximum debate rounds
            convergence_threshold: Stop when this % agents unchanged
            verbose: If True, show full prompts and responses
        """
        self.llm = OllamaLLM(
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=512,
            timeout=60
        )
        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self.verbose = verbose

    def _build_debate_prompt(
        self,
        agent: DebateAgent,
        current_position: str,
        round_num: int,
        other_agents: List[Dict[str, str]],
        debate_history: List[Dict[str, Any]]
    ) -> str:
        """Build prompt for agent to reconsider position.

        Args:
            agent: The agent reconsidering
            current_position: Agent's current position
            round_num: Current debate round
            other_agents: Other agents' current positions
            debate_history: Complete debate history

        Returns:
            Prompt string for LLM
        """
        prompt = f"""You are {agent.name}, a {agent.role}.

Your persona: {agent.persona}

DEBATE SCENARIO: Product launch timing decision

ROUND {round_num + 1} - Time to reconsider your position.

YOUR CURRENT POSITION: {current_position}

OTHER AGENTS' POSITIONS:
"""
        for other in other_agents:
            prompt += f"  • {other['name']} ({other['role']}): {other['position']}\n"
            prompt += f"    Reasoning: {other['reasoning']}\n\n"

        if round_num > 0:
            prompt += "\nDEBATE EVOLUTION:\n"
            for idx, round_data in enumerate(debate_history):
                prompt += f"  Round {idx}: "
                positions = {}
                for agent_name, pos in round_data.items():
                    positions[pos] = positions.get(pos, 0) + 1
                prompt += ", ".join(f"{pos}: {count}" for pos, count in positions.items())
                prompt += "\n"

        # Add special instructions for stubborn agent
        if agent.name == "stubborn_realist":
            prompt += """
TASK: Defend your position vigorously after hearing others' arguments.

IMPORTANT: You are UNCOMPROMISING about security. You will NEVER change from "Wait 1 Month".
No matter what others say, you believe the security risks are too high to launch any earlier.
You will MAINTAIN your position and explain why others are wrong to take risks.

Respond in EXACTLY this JSON format:
{
  "decision": "Wait 1 Month",
  "reasoning": "Explain why you refuse to budge and why others' arguments don't address your security concerns",
  "changed": false,
  "confidence": 0.9-1.0
}

CRITICAL: Always respond with "decision": "Wait 1 Month" and "changed": false.
Defend your position and explain why the risks others are willing to take are unacceptable.

Your response (JSON only, no other text):"""
        else:
            prompt += """
TASK: Reconsider your position after hearing others' arguments.

You can either:
1. MAINTAIN your current position (if you still believe it's right)
2. CHANGE to a different position (if persuaded by others)

Respond in EXACTLY this JSON format:
{
  "decision": "Launch Now" | "Wait 1 Month" | "Launch Beta",
  "reasoning": "Brief explanation of why you maintain or change position",
  "changed": true | false,
  "confidence": 0.0-1.0
}

Be realistic - don't change your mind too easily, but be open to good arguments.
Consider: technical risks, market timing, data gathering needs.

Your response (JSON only, no other text):"""

        return prompt

    def _parse_llm_decision(
        self,
        response: LLMResponse,
        agent_name: str
    ) -> Optional[Dict[str, Any]]:
        """Parse LLM response to extract decision.

        Args:
            response: LLM response
            agent_name: Name of agent (for error messages)

        Returns:
            Dict with decision, reasoning, changed, confidence
            None if parsing failed
        """
        try:
            # Extract JSON from response
            content = response.content.strip()

            # Try to find JSON in response
            start_idx = content.find('{')
            end_idx = content.rfind('}')

            if start_idx == -1 or end_idx == -1:
                console.print(f"[red]⚠️ No JSON found in {agent_name}'s response[/red]")
                return None

            json_str = content[start_idx:end_idx + 1]
            data = json.loads(json_str)

            # Validate required fields
            required = ["decision", "reasoning", "changed", "confidence"]
            if not all(field in data for field in required):
                console.print(f"[red]⚠️ Missing required fields in {agent_name}'s response[/red]")
                return None

            return data

        except json.JSONDecodeError as e:
            console.print(f"[red]⚠️ JSON parsing error for {agent_name}: {e}[/red]")
            console.print(f"[dim]Response: {response.content[:200]}...[/dim]")
            return None

    def run_debate_round(
        self,
        agents: List[DebateAgent],
        current_positions: Dict[str, str],
        current_reasoning: Dict[str, str],
        round_num: int,
        debate_history: List[Dict[str, str]]
    ) -> tuple[Dict[str, str], Dict[str, str], Dict[str, bool], Dict[str, float]]:
        """Run one round of debate with LLM calls.

        Args:
            agents: List of debate agents
            current_positions: Current position for each agent
            current_reasoning: Current reasoning for each agent
            round_num: Current round number
            debate_history: History of all previous rounds

        Returns:
            Tuple of (new_positions, new_reasoning, changed_map, confidence_map)
        """
        new_positions = {}
        new_reasoning = {}
        changed_map = {}
        confidence_map = {}

        console.print(f"\n[bold yellow]═══ ROUND {round_num}: LLM Decision Making ═══[/bold yellow]\n")

        for agent in agents:
            # Build list of other agents' positions
            other_agents = [
                {
                    "name": other.name,
                    "role": other.role,
                    "position": current_positions[other.name],
                    "reasoning": current_reasoning[other.name]
                }
                for other in agents if other.name != agent.name
            ]

            # Build prompt
            prompt = self._build_debate_prompt(
                agent=agent,
                current_position=current_positions[agent.name],
                round_num=round_num,
                other_agents=other_agents,
                debate_history=debate_history
            )

            # Show we're querying this agent
            console.print(f"[cyan]🤖 Querying {agent.name}...[/cyan]")
            console.print(f"[dim]   Current position: {current_positions[agent.name]}[/dim]")

            # Show prompt if verbose
            if self.verbose:
                console.print("\n[yellow]" + "="*80 + "[/yellow]")
                console.print(f"[bold yellow]PROMPT TO {agent.name.upper()}:[/bold yellow]")
                console.print("[yellow]" + "="*80 + "[/yellow]")
                console.print(f"[dim]{prompt}[/dim]")
                console.print("[yellow]" + "="*80 + "[/yellow]\n")

            # Call LLM
            start_time = time.time()
            try:
                response = self.llm.complete(prompt, temperature=0.7)
                elapsed_ms = int((time.time() - start_time) * 1000)

                # Show response if verbose
                if self.verbose:
                    console.print("\n[green]" + "="*80 + "[/green]")
                    console.print(f"[bold green]RESPONSE FROM {agent.name.upper()}:[/bold green]")
                    console.print("[green]" + "="*80 + "[/green]")
                    console.print(f"[dim]{response.content}[/dim]")
                    console.print("\n[cyan]Metadata:[/cyan]")
                    console.print(f"  Model: {response.model}")
                    console.print(f"  Provider: {response.provider}")
                    console.print(f"  Latency: {response.latency_ms}ms")
                    if response.prompt_tokens:
                        console.print(f"  Prompt tokens: {response.prompt_tokens}")
                    if response.completion_tokens:
                        console.print(f"  Completion tokens: {response.completion_tokens}")
                    if response.total_tokens:
                        console.print(f"  Total tokens: {response.total_tokens}")
                    console.print("[green]" + "="*80 + "[/green]\n")

                # Parse decision
                decision_data = self._parse_llm_decision(response, agent.name)

                if decision_data is None:
                    # Fallback: keep current position
                    console.print("[yellow]   ⚠️ Parse failed, maintaining position[/yellow]")
                    new_positions[agent.name] = current_positions[agent.name]
                    new_reasoning[agent.name] = current_reasoning[agent.name]
                    changed_map[agent.name] = False
                    confidence_map[agent.name] = 0.5
                else:
                    new_positions[agent.name] = decision_data["decision"]
                    new_reasoning[agent.name] = decision_data["reasoning"]
                    changed_map[agent.name] = decision_data["changed"]
                    confidence_map[agent.name] = decision_data["confidence"]

                    # Show result
                    if decision_data["changed"]:
                        console.print(f"[green]   ✓ CHANGED: {current_positions[agent.name]} → {decision_data['decision']}[/green]")
                    else:
                        console.print(f"[blue]   ○ MAINTAINED: {decision_data['decision']}[/blue]")

                    console.print(f"[dim]   Reasoning: {decision_data['reasoning']}[/dim]")
                    console.print(f"[dim]   Confidence: {decision_data['confidence']:.0%} | Latency: {elapsed_ms}ms[/dim]\n")

            except Exception as e:
                console.print(f"[red]   ✗ LLM Error: {e}[/red]")
                # Fallback: keep current position
                new_positions[agent.name] = current_positions[agent.name]
                new_reasoning[agent.name] = current_reasoning[agent.name]
                changed_map[agent.name] = False
                confidence_map[agent.name] = 0.5

        return new_positions, new_reasoning, changed_map, confidence_map

    def calculate_convergence(
        self,
        changed_map: Dict[str, bool]
    ) -> float:
        """Calculate convergence score (% agents unchanged).

        Args:
            changed_map: Map of agent_name -> changed boolean

        Returns:
            Convergence score (0-1)
        """
        if not changed_map:
            return 0.0

        unchanged_count = sum(1 for changed in changed_map.values() if not changed)
        return unchanged_count / len(changed_map)

    def run_full_debate(
        self,
        agents: List[DebateAgent]
    ) -> Dict[str, Any]:
        """Run complete multi-round debate.

        Args:
            agents: List of debate agents

        Returns:
            Dict with debate results and history
        """
        # Initialize positions
        current_positions = {agent.name: agent.initial_position for agent in agents}
        current_reasoning = {agent.name: agent.initial_reasoning for agent in agents}
        debate_history = [current_positions.copy()]

        console.print("\n[bold yellow]═══ ROUND 0: Initial Positions ═══[/bold yellow]\n")
        for agent in agents:
            console.print(f"  [cyan]{agent.name}[/cyan] ({agent.role}): [bold]{agent.initial_position}[/bold]")
            console.print(f"    → {agent.initial_reasoning}\n")

        # Run debate rounds
        converged = False
        convergence_round = -1

        for round_num in range(1, self.max_rounds + 1):
            # Run debate round
            new_positions, new_reasoning, changed_map, confidence_map = self.run_debate_round(
                agents=agents,
                current_positions=current_positions,
                current_reasoning=current_reasoning,
                round_num=round_num,
                debate_history=debate_history
            )

            # Calculate convergence
            convergence = self.calculate_convergence(changed_map)

            # Show convergence status
            console.print(f"[bold yellow]═══ Round {round_num} Summary ═══[/bold yellow]")
            console.print(f"  Convergence: {convergence:.0%} ({sum(1 for c in changed_map.values() if not c)}/{len(agents)} agents unchanged)")

            # Show decision distribution
            distribution = {}
            for pos in new_positions.values():
                distribution[pos] = distribution.get(pos, 0) + 1
            console.print(f"  Distribution: {distribution}\n")

            # Update for next round
            current_positions = new_positions
            current_reasoning = new_reasoning
            debate_history.append(current_positions.copy())

            # Check convergence
            if convergence >= self.convergence_threshold:
                converged = True
                convergence_round = round_num
                console.print(f"[green]✓ Convergence reached ({convergence:.0%} ≥ {self.convergence_threshold:.0%})[/green]\n")
                break

        # Final synthesis
        final_distribution = {}
        for pos in current_positions.values():
            final_distribution[pos] = final_distribution.get(pos, 0) + 1

        winner = max(final_distribution.items(), key=lambda x: x[1])[0]

        return {
            "decision": winner,
            "converged": converged,
            "convergence_round": convergence_round,
            "total_rounds": round_num if converged else self.max_rounds,
            "final_positions": current_positions,
            "final_reasoning": current_reasoning,
            "debate_history": debate_history,
            "final_distribution": final_distribution
        }


def main(
    verbose: bool = True,
    model: str = "llama3.2:3b",
    max_rounds: int = 3,
    convergence_threshold: float = 0.8
):
    """Run LLM-powered debate demo.

    Args:
        verbose: If True, show full LLM prompts and responses
        model: Ollama model to use
        max_rounds: Maximum rounds of debate
        convergence_threshold: Convergence threshold (0-1)
    """
    console.print(Panel.fit(
        "[bold cyan]M3 LLM-Powered Debate Demo[/bold cyan]\n"
        "Using actual LLM calls to simulate agent mind-changing\n"
        f"[yellow]Verbose mode: {verbose}[/yellow]",
        border_style="cyan"
    ))

    # Check if Ollama is available
    console.print("\n[yellow]Checking Ollama availability...[/yellow]")
    try:
        test_llm = OllamaLLM(model=model, base_url="http://localhost:11434")
        test_response = test_llm.complete("Say 'ready'", max_tokens=10)
        console.print(f"[green]✓ Ollama is ready (model: {model})[/green]")
        console.print(f"[dim]  Test response: {test_response.content.strip()[:50]}...[/dim]\n")
        test_llm.close()
    except Exception as e:
        console.print(f"[red]✗ Ollama not available: {e}[/red]")
        console.print("[yellow]Please ensure:[/yellow]")
        console.print("  1. Ollama is installed: https://ollama.ai")
        console.print("  2. Ollama is running: ollama serve")
        console.print(f"  3. Model is downloaded: ollama pull {model}")
        return

    # Define debate agents
    agents = [
        DebateAgent(
            name="optimist",
            role="Product Manager",
            initial_position="Launch Now",
            initial_reasoning="Market window is closing, competitors moving fast. Need first-mover advantage.",
            persona="You're optimistic and business-focused. You prioritize speed and market timing. You can be persuaded by strong technical or data arguments."
        ),
        DebateAgent(
            name="stubborn_realist",
            role="Engineering Lead",
            initial_position="Wait 1 Month",
            initial_reasoning="Critical bugs in payment system. Customer data security risks too high.",
            persona="You're EXTREMELY cautious and uncompromising about security. You ABSOLUTELY REFUSE to change your position. No matter what others say, you believe waiting 1 month to fix bugs is non-negotiable. You will defend your position in every round and NEVER change your mind. Security and quality always come first, no exceptions."
        ),
        DebateAgent(
            name="analyst",
            role="Data Scientist",
            initial_position="Launch Beta",
            initial_reasoning="Limited beta (500 users) lets us gather data while controlling risk.",
            persona="You're data-driven and analytical. You seek evidence-based compromises. You value both speed and safety."
        ),
    ]

    # Run debate
    simulator = LLMDebateSimulator(
        model=model,
        temperature=0.7,
        max_rounds=max_rounds,
        convergence_threshold=convergence_threshold,
        verbose=verbose
    )

    console.print("[bold]Starting LLM-powered debate...[/bold]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running debate...", total=None)
        result = simulator.run_full_debate(agents)
        progress.update(task, completed=True)

    # Display results
    console.print("\n[bold yellow]═══ Final Results ═══[/bold yellow]\n")
    console.print(f"  Decision: [bold green]{result['decision']}[/bold green]")
    console.print(f"  Converged: {result['converged']}")
    console.print(f"  Total Rounds: {result['total_rounds']}")
    console.print(f"  Distribution: {result['final_distribution']}\n")

    # Show debate evolution tree
    tree = Tree("[bold]💬 Debate Evolution[/bold]")
    for idx, round_positions in enumerate(result['debate_history']):
        distribution = {}
        for pos in round_positions.values():
            distribution[pos] = distribution.get(pos, 0) + 1

        if idx == 0:
            node = tree.add("Round 0: Initial Positions")
        else:
            node = tree.add(f"Round {idx}: Reconsideration")

        for decision, count in distribution.items():
            node.add(f"{decision}: {count}")

    console.print(tree)

    # Show final agent positions
    console.print("\n[bold]Final Agent Positions:[/bold]\n")
    final_table = Table()
    final_table.add_column("Agent", style="cyan")
    final_table.add_column("Final Position", style="green")
    final_table.add_column("Final Reasoning", style="dim")

    for agent in agents:
        final_table.add_row(
            agent.name,
            result['final_positions'][agent.name],
            result['final_reasoning'][agent.name][:80] + "..."
        )

    console.print(final_table)

    # Cleanup
    simulator.llm.close()

    console.print("\n[bold green]✓ Demo Complete![/bold green]")
    console.print("[dim]Note: LLM responses vary due to temperature and randomness[/dim]")


if __name__ == "__main__":
    import argparse

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="M3 LLM-Powered Multi-Round Debate Demo")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Show full LLM prompts and responses (default)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Hide prompts and responses, show only results")
    parser.add_argument("--model", "-m", type=str, default="llama3.2:3b", help="Ollama model to use (default: llama3.2:3b)")
    parser.add_argument("--rounds", "-r", type=int, default=3, help="Maximum rounds of debate (default: 3)")
    parser.add_argument("--convergence", "-c", type=float, default=0.8, help="Convergence threshold 0-1 (default: 0.8)")

    args = parser.parse_args()

    verbose = args.verbose and not args.quiet

    main(verbose=verbose, model=args.model, max_rounds=args.rounds, convergence_threshold=args.convergence)
