"""CLI commands for DSPy prompt optimization."""

import logging
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.optimize_constants import (
    AGENT_FILTER_HELP,
    CLI_DEFAULT_MAX_DEMOS,
    CLI_DEFAULT_MIN_TRAINING_EXAMPLES,
    COMPILE_HELP,
    COMPILE_SUCCESS_MSG,
    CONFIG_LOAD_ERROR_MSG,
    DRY_RUN_HELP,
    DSPY_NOT_INSTALLED_MSG,
    INSUFFICIENT_DATA_MSG,
    LIST_HELP,
    MAX_DEMOS_HELP,
    MIN_EXAMPLES_HELP,
    NO_PROGRAMS_MSG,
    OPTIMIZE_GROUP_HELP,
    OPTIMIZER_HELP,
    PREVIEW_HELP,
    PREVIEW_NO_PROGRAM_MSG,
)

logger = logging.getLogger(__name__)
console = Console()


@click.group(name="optimize", help=OPTIMIZE_GROUP_HELP)
def optimize_group() -> None:
    """DSPy prompt optimization commands."""


@optimize_group.command(name="compile", help=COMPILE_HELP)
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--optimizer", default="bootstrap", help=OPTIMIZER_HELP)
@click.option(
    "--min-examples",
    default=CLI_DEFAULT_MIN_TRAINING_EXAMPLES,
    type=int,
    help=MIN_EXAMPLES_HELP,
)
@click.option(
    "--max-demos", default=CLI_DEFAULT_MAX_DEMOS, type=int, help=MAX_DEMOS_HELP,
)
@click.option("--dry-run", is_flag=True, help=DRY_RUN_HELP)
def compile_cmd(
    config_path: str,
    optimizer: str,
    min_examples: int,
    max_demos: int,
    dry_run: bool,
) -> None:
    """Compile optimized prompts for an agent."""
    agent_config = _load_agent_config(config_path)
    if agent_config is None:
        return
    agent_name = agent_config["agent"]["name"]

    try:
        from temper_ai.optimization.data_collector import TrainingDataCollector
        from temper_ai.optimization._schemas import PromptOptimizationConfig  # noqa: F401
    except ImportError:
        console.print(DSPY_NOT_INSTALLED_MSG)
        return

    collector = TrainingDataCollector()
    examples = collector.collect_examples(
        agent_name=agent_name, max_examples=min_examples * 2,
    )

    if dry_run:
        _show_dry_run_stats(agent_name, examples, min_examples)
        return

    if len(examples) < min_examples:
        console.print(
            INSUFFICIENT_DATA_MSG.format(
                count=len(examples), required=min_examples,
            )
        )
        return

    _run_compilation(agent_name, examples, optimizer, max_demos)


def _show_dry_run_stats(
    agent_name: str, examples: list, min_examples: int,
) -> None:
    """Display training data statistics."""
    console.print(f"\n[bold]Agent:[/bold] {agent_name}")
    console.print(f"[bold]Examples found:[/bold] {len(examples)}")
    console.print(f"[bold]Min required:[/bold] {min_examples}")
    sufficient = len(examples) >= min_examples
    status = "[green]Sufficient[/green]" if sufficient else "[red]Insufficient[/red]"
    console.print(f"[bold]Status:[/bold] {status}")


def _run_compilation(
    agent_name: str,
    examples: list,
    optimizer: str,
    max_demos: int,
) -> None:
    """Execute the compilation pipeline."""
    try:
        from temper_ai.optimization._schemas import PromptOptimizationConfig
        from temper_ai.optimization.compiler import DSPyCompiler
        from temper_ai.optimization.program_builder import DSPyProgramBuilder
        from temper_ai.optimization.program_store import CompiledProgramStore

        config = PromptOptimizationConfig(
            optimizer=optimizer,  # type: ignore[arg-type]  # click passes str
            max_demos=max_demos,
        )
        builder = DSPyProgramBuilder()
        program = builder.build_from_config(config)

        compiler = DSPyCompiler()
        result = compiler.compile(
            program=program,
            training_examples=examples,
            config=config,
        )

        store = CompiledProgramStore(store_dir=config.program_store_dir)
        store.save(agent_name, result.metadata, metadata={
            "optimizer": result.optimizer_type,
        })
        console.print(
            COMPILE_SUCCESS_MSG.format(agent_name=agent_name)
        )
    except ImportError:
        console.print(DSPY_NOT_INSTALLED_MSG)


@optimize_group.command(name="list", help=LIST_HELP)
@click.option("--agent", default=None, help=AGENT_FILTER_HELP)
def list_cmd(agent: str | None) -> None:
    """List compiled optimization programs."""
    from temper_ai.optimization.program_store import CompiledProgramStore

    store = CompiledProgramStore()
    programs = store.list_programs(agent_name=agent)

    if not programs:
        console.print(NO_PROGRAMS_MSG)
        return

    table = Table(title="Compiled Programs")
    table.add_column("Program ID")
    table.add_column("Agent")
    table.add_column("Created")
    table.add_column("Metadata")

    for prog in programs:
        table.add_row(
            prog["program_id"],
            prog["agent_name"],
            prog.get("created_at", ""),
            str(prog.get("metadata", {})),
        )
    console.print(table)


@optimize_group.command(name="preview", help=PREVIEW_HELP)
@click.argument("config_path", type=click.Path(exists=True))
def preview_cmd(config_path: str) -> None:
    """Preview what an optimized prompt looks like."""
    agent_config = _load_agent_config(config_path)
    if agent_config is None:
        return
    agent_name = agent_config["agent"]["name"]

    from temper_ai.optimization.program_store import CompiledProgramStore
    from temper_ai.optimization.prompt_adapter import DSPyPromptAdapter

    store = CompiledProgramStore()
    adapter = DSPyPromptAdapter(store=store)

    prompt_cfg = agent_config["agent"].get("prompt", {})
    base_prompt = prompt_cfg.get("inline", "")
    if not base_prompt and prompt_cfg.get("template"):
        template_path = Path(prompt_cfg["template"])
        if template_path.is_file():
            base_prompt = template_path.read_text()

    if not base_prompt:
        base_prompt = "(no prompt configured)"

    result = adapter.augment_prompt(agent_name, base_prompt)

    if result == base_prompt:
        console.print(
            PREVIEW_NO_PROGRAM_MSG.format(agent_name=agent_name)
        )
        return

    console.print("\n[bold]Optimized Prompt Preview:[/bold]\n")
    console.print(result)


def _load_agent_config(config_path: str) -> dict | None:
    """Load and return agent config from YAML file."""
    try:
        with open(config_path) as f:
            data: dict = yaml.safe_load(f)
            return data
    except (yaml.YAMLError, OSError) as exc:
        console.print(CONFIG_LOAD_ERROR_MSG.format(error=exc))
        return None
