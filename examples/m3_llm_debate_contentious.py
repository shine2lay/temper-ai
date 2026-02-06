"""
M3 Contentious Multi-Round Debate Demo

This demo creates a more contentious debate with 4 stubborn agents
to showcase 5 full rounds of debate without early convergence.

Usage:
    PYTHONPATH=/home/shinelay/meta-autonomous-framework python3 examples/m3_llm_debate_contentious.py
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.panel import Panel

from examples.m3_llm_debate_demo import DebateAgent, LLMDebateSimulator, console


def main():
    """Run contentious 5-round debate with 4 stubborn agents."""

    console.print(Panel.fit(
        "[bold cyan]M3 Contentious 5-Round Debate Demo[/bold cyan]\n"
        "4 stubborn agents with strong opposing views\n"
        "Force 5 full rounds to see complete debate evolution",
        border_style="cyan"
    ))

    # Define 4 agents with strong, opposing positions
    agents = [
        DebateAgent(
            name="aggressive_pm",
            role="Aggressive Product Manager",
            initial_position="Launch Now",
            initial_reasoning="We're already behind competitors. Every day we wait costs us millions in market share. Ship now, fix later.",
            persona="You're extremely aggressive and profit-focused. You STRONGLY believe launching immediately is critical. You're very difficult to persuade - only overwhelming evidence will change your mind. You tend to defend your position vigorously."
        ),
        DebateAgent(
            name="paranoid_security",
            role="Paranoid Security Engineer",
            initial_position="Wait 1 Month",
            initial_reasoning="The payment system has critical vulnerabilities. We could face lawsuits, regulatory fines, and reputation damage. Security MUST come first.",
            persona="You're extremely security-focused and risk-averse. You STRONGLY believe we must wait to fix security issues. You see catastrophic risks everywhere. You're very difficult to persuade - only concrete risk mitigation plans will change your mind."
        ),
        DebateAgent(
            name="data_purist",
            role="Data Purist Analyst",
            initial_position="Launch Beta",
            initial_reasoning="We need 10,000+ data points before full launch. Beta with strict controls is the only scientifically valid approach.",
            persona="You're extremely data-driven and methodical. You STRONGLY believe beta testing is the only valid approach. You dismiss arguments without data. You're difficult to persuade without statistical evidence."
        ),
        DebateAgent(
            name="perfectionist_engineer",
            role="Perfectionist Engineer",
            initial_position="Wait 1 Month",
            initial_reasoning="The code quality is unacceptable. We have technical debt, missing tests, and architectural flaws. We need a month of refactoring.",
            persona="You're extremely quality-focused and perfectionist. You believe launching with known bugs is unethical. You're very difficult to persuade - only if others acknowledge quality concerns will you budge."
        ),
    ]

    console.print("\n[yellow]Scenario:[/yellow] Product launch decision for a fintech payment platform")
    console.print("[yellow]Context:[/yellow] Working product, but security vulnerabilities and bugs remain")
    console.print("[yellow]Stakes:[/yellow] High - financial data, regulatory compliance, competitive market\n")

    # Run debate with forced 5 rounds (very high convergence threshold)
    simulator = LLMDebateSimulator(
        model="llama3.3:latest",
        temperature=0.8,  # Higher temperature for more variety
        max_rounds=5,
        convergence_threshold=1.0,  # Require 100% convergence to stop early
        verbose=True
    )

    result = simulator.run_debate(
        agents=agents,
        scenario="Product launch timing decision for fintech payment platform"
    )

    # Display results
    console.print("\n" + "="*80)
    console.print("[bold green]Final Convergence Analysis[/bold green]")
    console.print("="*80 + "\n")

    console.print(f"[cyan]Total Rounds:[/cyan] {result['rounds_completed']}")
    console.print(f"[cyan]Final Decision:[/cyan] {result['final_decision']}")
    console.print(f"[cyan]Converged:[/cyan] {result['converged']}")
    console.print(f"[cyan]Final Distribution:[/cyan] {result['final_distribution']}\n")

    # Show mind changes over time
    console.print("[bold yellow]Agent Mind Changes Over 5 Rounds:[/bold yellow]\n")

    for agent in agents:
        changes = []
        prev_pos = agent.initial_position
        changes.append(f"R0: {prev_pos}")

        # Track changes through rounds
        for round_num in range(1, result['rounds_completed'] + 1):
            # This is simplified - in real implementation we'd track each round
            changes.append(f"R{round_num}: ?")

        console.print(f"[cyan]{agent.name}:[/cyan] {' → '.join(changes)}")

    console.print("\n[bold green]✓ 5-Round Debate Complete![/bold green]")
    console.print("[dim]Note: With 4 stubborn agents, consensus is harder to achieve[/dim]")


if __name__ == "__main__":
    main()
