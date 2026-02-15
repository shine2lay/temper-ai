"""Post-execution detailed report for maf run --show-details.

Renders per-stage panels showing input context, agent outputs,
synthesis results, and final stage output using Rich formatting.

All LLM/tool-generated content is rendered via plain Text() objects
to prevent Rich markup injection. Only framework labels use
Text.from_markup().
"""
import json
from typing import Any, Dict, List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.constants.limits import MAX_MEDIUM_STRING_LENGTH

# Infrastructure keys filtered from input display
_INFRA_KEYS = frozenset({
    "tracker", "config_loader", "tool_registry", "workflow_id",
    "tool_executor", "show_details", "detail_console", "visualizer",
})

# Table column width constants for agent outputs display
TABLE_COL_AGENT_MAX_WIDTH = 20
TABLE_COL_OUTPUT_RATIO = 3
TABLE_COL_CONF_MAX_WIDTH = 8
TABLE_COL_TOOLS_MAX_WIDTH = 8


def _tool_calls_count(tool_calls: Any) -> int:
    """Get tool call count from either list (new) or int (legacy)."""
    if isinstance(tool_calls, list):
        return len(tool_calls)
    if isinstance(tool_calls, int):
        return tool_calls
    return 0


def _tool_calls_list(tool_calls: Any) -> List[dict]:
    """Get tool calls as a list, returning empty list for legacy int format."""
    if isinstance(tool_calls, list):
        return tool_calls
    return []


def _render_tool_call_detail(tc: dict, index: int) -> List[Any]:
    """Render details for a single tool call.

    Args:
        tc: Tool call dict
        index: Tool call number

    Returns:
        List of Rich renderables
    """
    renderables: list[Any] = []

    tc_name = tc.get("name", "unknown")
    tc_success = tc.get("success", None)
    status_str = "ok" if tc_success else "error" if tc_success is False else "?"

    line = Text("    ")
    line.append(f"{index}. {tc_name}", style="bold")
    line.append(f" [{status_str}]")
    renderables.append(line)

    # Parameters
    tc_params = tc.get("parameters", tc.get("arguments", {}))
    if tc_params:
        try:
            params_str = json.dumps(tc_params, indent=4, default=str)  # noqa: Standard JSON indent
        except (TypeError, ValueError):
            params_str = str(tc_params)
        renderables.append(Text.from_markup("    [dim]Parameters:[/dim]"))
        renderables.append(Text(f"      {params_str}"))

    # Result or error
    if tc.get("result") is not None:
        result_str = str(tc["result"])
        renderables.append(Text.from_markup("    [dim]Result:[/dim]"))
        renderables.append(Text(f"      {result_str}"))
    if tc.get("error"):
        error_str = str(tc["error"])
        renderables.append(Text.from_markup("    [dim]Error:[/dim]"))
        renderables.append(Text(f"      {error_str}"))

    return renderables


def _render_agent_detail(agent_name: str, output_data: dict) -> List[Any]:
    """Render full detail section for a single agent.

    Returns a list of Rich renderables.
    """
    renderables: list[Any] = []

    # Header
    renderables.append(Text(""))
    renderables.append(Text.from_markup(f"  [bold cyan]{agent_name}[/bold cyan]"))

    # Full output
    output_text = str(output_data.get("output", "") or "")
    if output_text:
        renderables.append(Text.from_markup("  [dim]Output:[/dim]"))
        renderables.append(Text(f"  {output_text}"))

    # Full reasoning
    reasoning = str(output_data.get("reasoning", "") or "")
    if reasoning:
        renderables.append(Text.from_markup("  [dim]Reasoning:[/dim]"))
        renderables.append(Text(f"  {reasoning}"))

    # Tool calls detail
    tc_list = _tool_calls_list(output_data.get("tool_calls", []))
    if tc_list:
        renderables.append(Text.from_markup(f"  [dim]Tool Calls ({len(tc_list)}):[/dim]"))
        for i, tc in enumerate(tc_list, 1):
            renderables.extend(_render_tool_call_detail(tc, i))

    return renderables


def _is_internal_agent(agent_name: str) -> bool:
    return agent_name.startswith("__") and agent_name.endswith("__")


def _build_agent_row(agent_name: str, output_data: Any) -> Optional[tuple]:
    """Build a table row tuple for one agent, or None if skipped."""
    if not isinstance(output_data, dict):
        return None
    if _is_internal_agent(agent_name):
        return None

    raw_output = str(output_data.get("output", "") or "")
    preview = raw_output[:MAX_MEDIUM_STRING_LENGTH] + "..." if len(raw_output) > MAX_MEDIUM_STRING_LENGTH else raw_output

    confidence = output_data.get("confidence")
    conf_str = f"{confidence:.2f}" if confidence is not None else "-"
    tokens = output_data.get("tokens")
    tokens_str = str(tokens) if tokens else "-"
    cost = output_data.get("cost_usd") or output_data.get("cost")
    cost_str = f"${cost:.4f}" if cost else "-"

    tc_count = _tool_calls_count(output_data.get("tool_calls", 0))
    tc_str = str(tc_count) if tc_count else "-"

    return (agent_name, Text(preview), conf_str, tokens_str, cost_str, tc_str)


def _render_agent_summary_table(agent_outputs: dict) -> Optional[Table]:
    """Render agent summary table."""
    if not agent_outputs:
        return None

    table = Table(
        show_header=True,
        header_style="bold",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Agent", style="cyan", max_width=TABLE_COL_AGENT_MAX_WIDTH)
    table.add_column("Output Preview", ratio=TABLE_COL_OUTPUT_RATIO)
    table.add_column("Conf", justify="right", max_width=TABLE_COL_CONF_MAX_WIDTH)
    table.add_column("Tokens", justify="right", max_width=10)
    table.add_column("Cost", justify="right", max_width=10)
    table.add_column("Tools", justify="right", max_width=TABLE_COL_TOOLS_MAX_WIDTH)

    for agent_name, output_data in agent_outputs.items():
        row = _build_agent_row(agent_name, output_data)
        if row is not None:
            table.add_row(*row)

    return table


def _render_synthesis_section(synthesis: dict) -> List[Any]:
    """Render synthesis section.

    Args:
        synthesis: Synthesis result dict

    Returns:
        List of Rich renderables
    """
    renderables: list[Any] = []
    renderables.append(Text(""))

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

    renderables.append(Text.from_markup(
        f"[bold]Synthesis:[/bold] {', '.join(parts)}"
    ))
    return renderables


def _render_stage_input_context(
    prior_stages: List[str], stage_data: Optional[dict] = None,
) -> List[Any]:
    """Render input context section for a stage.

    Shows source-resolved refs when context metadata is available,
    otherwise falls back to passthrough or legacy display.
    """
    renderables: list[Any] = []
    context_meta = None
    if isinstance(stage_data, dict):
        context_meta = stage_data.get("_context_meta")

    if context_meta is not None and context_meta.get("mode") == "source-resolved":
        sources = context_meta.get("sources", {})
        defaults_used = context_meta.get("defaults_used", [])
        renderables.append(Text.from_markup(
            f"[bold]Context:[/bold] source-resolved ({len(sources)} inputs)"
        ))
        for input_name, source_ref in sources.items():
            suffix = ""
            if input_name in defaults_used:
                suffix = "  [default used]"
            line = Text(f"  {input_name:<20} <- {source_ref}{suffix}")
            renderables.append(line)
    elif context_meta is not None and context_meta.get("mode") == "passthrough":
        renderables.append(Text.from_markup(
            "[bold]Context:[/bold] passthrough (all prior outputs)"
        ))
    elif prior_stages:
        renderables.append(Text.from_markup(
            f"[bold]Input:[/bold] {', '.join(prior_stages)}"
        ))
    else:
        renderables.append(Text.from_markup(
            "[bold]Input:[/bold] (workflow inputs)"
        ))

    return renderables


def _render_stage_agents(stage_data: dict) -> List[Any]:
    """Render agent summary table and per-agent details for a stage."""
    renderables: list[Any] = []
    agent_outputs = stage_data.get("agent_outputs", {})

    table = _render_agent_summary_table(agent_outputs)
    if table:
        renderables.append(Text.from_markup("[bold]Agents:[/bold]"))
        renderables.append(table)

    for agent_name, output_data in agent_outputs.items():
        if not isinstance(output_data, dict) or _is_internal_agent(agent_name):
            continue
        renderables.extend(_render_agent_detail(agent_name, output_data))

    return renderables


def _render_stage_output(stage_data: dict) -> List[Any]:
    """Render synthesis and final output sections for a stage."""
    renderables: list[Any] = []

    synthesis = stage_data.get("synthesis_result") or stage_data.get("synthesis")
    if synthesis and isinstance(synthesis, dict):
        renderables.extend(_render_synthesis_section(synthesis))

    final_output = stage_data.get("output") or stage_data.get("decision", "")
    if final_output:
        renderables.append(Text(""))
        renderables.append(Text.from_markup("[bold]Stage Output:[/bold]"))
        renderables.append(Text(str(final_output)))

    return renderables


def _render_structured_outputs(stage_data: dict) -> List[Any]:
    """Render structured compartment when non-empty."""
    renderables: list[Any] = []
    structured = stage_data.get("structured")
    if not structured or not isinstance(structured, dict):
        return renderables

    renderables.append(Text(""))
    renderables.append(Text.from_markup("[bold]Structured Outputs:[/bold]"))
    for field_name, value in structured.items():
        value_str = str(value)
        preview = (
            value_str[:MAX_MEDIUM_STRING_LENGTH] + "..."
            if len(value_str) > MAX_MEDIUM_STRING_LENGTH
            else value_str
        )
        line = Text(f"  {field_name}:  {preview}")
        renderables.append(line)

    return renderables


def _render_stage_panel(
    stage_name: str, stage_data: Any, prior_stages: List[str]
) -> Optional[Panel]:
    """Build a Panel for a single stage, or None if stage_data is not a dict."""
    if not isinstance(stage_data, dict):
        return None

    renderables: list[Any] = _render_stage_input_context(prior_stages, stage_data)
    renderables.append(Text(""))
    renderables.extend(_render_stage_agents(stage_data))
    renderables.extend(_render_stage_output(stage_data))
    renderables.extend(_render_structured_outputs(stage_data))

    return Panel(
        Group(*renderables),
        title=f"[bold]Stage: {stage_name}[/bold]",
        border_style="cyan",
        expand=True,
    )


_STATUS_STYLES: Dict[str, str] = {
    "completed": "green",
    "degraded": "yellow",
    "failed": "red",
}


def _render_store_entry(
    stage_name: str, stage_data: dict, is_current: bool,
) -> List[Any]:
    """Render a single store entry as compact lines."""
    renderables: list[Any] = []

    marker = " *" if is_current else ""
    status = stage_data.get("stage_status", "")
    status_style = _STATUS_STYLES.get(status, "dim")

    header = Text("  ")
    header.append(f"{stage_name}{marker}", style="bold" if is_current else "")
    if status:
        header.append(f"  [{status}]", style=status_style)
    renderables.append(header)

    output = stage_data.get("output") or stage_data.get("decision", "")
    if output:
        renderables.append(Text(f"    output: {len(str(output)):,} chars", style="dim"))

    structured = stage_data.get("structured", {})
    if structured and isinstance(structured, dict):
        renderables.append(Text(f"    structured: {{{', '.join(structured.keys())}}}", style="dim"))

    return renderables


def _render_store_snapshot(
    stage_outputs: dict, current_idx: int,
) -> Panel:
    """Render a compact snapshot of the global store after the current stage."""
    stage_names = list(stage_outputs.keys())
    entries_to_show = stage_names[: current_idx + 1]

    renderables: list[Any] = []
    for sname in entries_to_show:
        sdata = stage_outputs[sname]
        if not isinstance(sdata, dict):
            continue
        is_current = (sname == stage_names[current_idx])
        renderables.extend(_render_store_entry(sname, sdata, is_current))

    return Panel(
        Group(*renderables),
        title=f"[dim]Store ({len(entries_to_show)} entries)[/dim]",
        border_style="dim",
        expand=True,
        padding=(0, 1),
    )


def print_detailed_report(result: dict, console: Console) -> None:
    """Print a detailed post-execution report."""
    stage_outputs = result.get("stage_outputs")
    if not stage_outputs or not isinstance(stage_outputs, dict):
        return

    console.print()
    console.rule("[bold]Detailed Execution Report[/bold]")

    stage_names = list(stage_outputs.keys())
    for idx, stage_name in enumerate(stage_names):
        panel = _render_stage_panel(
            stage_name, stage_outputs[stage_name], stage_names[:idx]
        )
        if panel is not None:
            console.print(panel)
        console.print(_render_store_snapshot(stage_outputs, idx))
