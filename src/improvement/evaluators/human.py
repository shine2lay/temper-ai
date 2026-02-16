"""Human evaluator — user approval via CLI."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import click

from src.improvement._schemas import EvaluationResult
from src.improvement.constants import FIRST_BETTER, MAX_SCORE, MIN_SCORE, SECOND_BETTER, TIE


class HumanEvaluator:
    """Evaluator that prompts the user for approval or comparison."""

    def __init__(self, config: Any = None, llm: Any = None) -> None:
        pass

    def evaluate(
        self,
        output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Ask user to approve or reject the output."""
        click.echo("\n--- Output for review ---")
        click.echo(json.dumps(output, indent=2))
        click.echo("-------------------------\n")
        approved = click.confirm("Approve this output?", default=True)
        return EvaluationResult(
            passed=approved,
            score=MAX_SCORE if approved else MIN_SCORE,
        )

    def compare(
        self,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Ask user which output is better."""
        click.echo("\n--- Output A ---")
        click.echo(json.dumps(output_a, indent=2))
        click.echo("\n--- Output B ---")
        click.echo(json.dumps(output_b, indent=2))
        click.echo("----------------\n")
        choice = click.prompt(
            "Which is better? (A/B/tie)",
            type=click.Choice(["A", "B", "tie"], case_sensitive=False),
            default="tie",
        )
        choice = choice.upper()
        if choice == "A":
            return FIRST_BETTER
        if choice == "B":
            return SECOND_BETTER
        return TIE
