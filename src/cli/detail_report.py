"""Post-execution detailed report for maf run --show-details.

Renders per-stage panels showing input context, agent outputs,
synthesis results, and final stage output using Rich formatting.
"""
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def print_detailed_report(result: dict, console: Console) -> None:
    """Print a detailed post-execution report.

    Iterates stage_outputs and renders per-stage panels with:
    - Input context (keys available from prior stages)
    - Agent outputs table (name, output preview, confidence, tokens, cost)
    - Synthesis result (method, confidence, votes)
    - Stage output (final output preview)

    Args:
        result: Workflow execution result dict
        console: Rich Console instance for output
    """
    stage_outputs = result.get("stage_outputs")
    if not stage_outputs or not isinstance(stage_outputs, dict):
        return

    console.print()
    console.rule("[bold]Detailed Execution Report[/bold]")

    stage_names = list(stage_outputs.keys())
    for idx, stage_name in enumerate(stage_names):
        stage_data = stage_outputs[stage_name]
        if not isinstance(stage_data, dict):
            continue

        lines: list[str] = []

        # Input context: show what keys were available from prior stages
        prior_stages = stage_names[:idx]
        if prior_stages:
            lines.append(f"[bold]Input:[/bold] {', '.join(prior_stages)}")
        else:
            lines.append("[bold]Input:[/bold] (workflow inputs)")
        lines.append("")

        # Agent outputs table
        agent_outputs = stage_data.get("agent_outputs", {})
        if agent_outputs:
            table = Table(
                show_header=True,
                header_style="bold",
                expand=True,
                padding=(0, 1),
            )
            table.add_column("Agent", style="cyan", max_width=20)
            table.add_column("Output", ratio=3)
            table.add_column("Confidence", justify="right", max_width=12)
            table.add_column("Tokens", justify="right", max_width=10)
            table.add_column("Cost", justify="right", max_width=10)

            for agent_name, output_data in agent_outputs.items():
                if not isinstance(output_data, dict):
                    continue
                # Skip internal sentinel keys
                if agent_name.startswith("__") and agent_name.endswith("__"):
                    continue

                output_preview = _truncate(
                    output_data.get("output", ""), 500
                )
                confidence = output_data.get("confidence")
                conf_str = f"{confidence:.2f}" if confidence is not None else "-"
                tokens = output_data.get("tokens")
                tokens_str = str(tokens) if tokens else "-"
                cost = output_data.get("cost_usd") or output_data.get("cost")
                cost_str = f"${cost:.4f}" if cost else "-"

                table.add_row(
                    agent_name,
                    output_preview,
                    conf_str,
                    tokens_str,
                    cost_str,
                )

            lines.append("[bold]Agents:[/bold]")

        # Agent reasoning (shown below table)
        reasoning_lines: list[Text] = []
        for agent_name, output_data in agent_outputs.items():
            if not isinstance(output_data, dict):
                continue
            if agent_name.startswith("__") and agent_name.endswith("__"):
                continue
            reasoning = output_data.get("reasoning", "")
            if reasoning:
                # Use plain Text to avoid Rich markup injection from LLM output
                label = Text.from_markup(f"  [dim]{agent_name}:[/dim] ")
                content = Text(_truncate(str(reasoning), 300))
                combined = Text()
                combined.append_text(label)
                combined.append_text(content)
                reasoning_lines.append(combined)

        # Synthesis result
        synthesis = stage_data.get("synthesis_result") or stage_data.get("synthesis")
        synthesis_lines: list[str] = []
        if synthesis and isinstance(synthesis, dict):
            method = synthesis.get("method", "")
            conf = synthesis.get("confidence")
            votes = synthesis.get("votes", {})
            parts = []
            if method:
                parts.append(f"method={method}")
            if conf is not None:
                parts.append(f"confidence={conf:.2f}")
            if votes:
                parts.append(f"votes={votes}")
            synthesis_lines.append(
                f"[bold]Synthesis:[/bold] {', '.join(parts)}"
            )

        # Stage final output
        final_output = stage_data.get("output") or stage_data.get("decision", "")

        # Build panel content as a list of renderables
        renderables: list[Any] = [Text.from_markup("\n".join(lines))]

        if agent_outputs:
            renderables.append(table)

        if reasoning_lines:
            renderables.append(Text(""))
            renderables.append(
                Text.from_markup("[bold]Reasoning:[/bold]")
            )
            for rl in reasoning_lines:
                renderables.append(rl)

        if synthesis_lines:
            renderables.append(Text(""))
            for sl in synthesis_lines:
                renderables.append(Text.from_markup(sl))

        if final_output:
            renderables.append(Text(""))
            renderables.append(
                Text.from_markup("[bold]Stage Output:[/bold]")
            )
            # Use plain Text for agent-generated content
            renderables.append(Text(_truncate(str(final_output), 500)))

        panel = Panel(
            Group(*renderables),
            title=f"[bold]Stage: {stage_name}[/bold]",
            border_style="cyan",
            expand=True,
        )
        console.print(panel)
