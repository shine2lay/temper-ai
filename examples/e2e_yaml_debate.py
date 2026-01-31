"""
End-to-End YAML-Driven Debate Workflow

This script demonstrates the complete M3 workflow pipeline:
1. Load YAML configuration
2. Initialize workflow from config
3. Execute multi-agent debate
4. Generate structured output

This shows how M3 works in production with YAML configs.

Usage:
    python3 examples/e2e_yaml_debate.py
"""

import sys
import yaml
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.llm_providers import OllamaLLM, LLMResponse
from src.strategies.base import AgentOutput, SynthesisResult
from src.strategies.debate import DebateAndSynthesize

console = Console()


class YAMLWorkflowRunner:
    """Runs M3 workflows from YAML configuration."""

    def __init__(self, config_path: str):
        """Initialize workflow runner.

        Args:
            config_path: Path to workflow YAML config
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.llm = None
        self.execution_trace = []

    def _load_config(self) -> Dict[str, Any]:
        """Load YAML configuration file."""
        console.print(f"\n[yellow]Loading config:[/yellow] {self.config_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        console.print(f"[green]✓ Config loaded:[/green] {config['workflow']['name']}")
        console.print(f"[dim]  Description: {config['workflow']['description']}[/dim]\n")

        return config

    def _initialize_llm(self) -> None:
        """Initialize LLM provider from config."""
        llm_config = self.config['workflow'].get('llm_provider', {})

        provider = llm_config.get('provider', 'ollama')
        base_url = llm_config.get('base_url', 'http://localhost:11434')
        model = llm_config.get('model', 'llama3.2:3b')
        temperature = llm_config.get('temperature', 0.7)
        max_tokens = llm_config.get('max_tokens', 512)

        console.print(f"[yellow]Initializing LLM provider:[/yellow]")
        console.print(f"  Provider: {provider}")
        console.print(f"  Model: {model}")
        console.print(f"  Base URL: {base_url}")
        console.print(f"  Temperature: {temperature}\n")

        self.llm = OllamaLLM(
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=60
        )

        # Test connection
        try:
            test_response = self.llm.complete("Say 'ready'", max_tokens=10)
            console.print(f"[green]✓ LLM ready[/green]\n")
        except Exception as e:
            console.print(f"[red]✗ LLM connection failed: {e}[/red]\n")
            raise

    def _load_stage_config(self, stage_config_path: str) -> Dict[str, Any]:
        """Load stage configuration from file."""
        console.print(f"[yellow]Loading stage config:[/yellow] {stage_config_path}")

        # Try multiple path resolutions
        possible_paths = [
            stage_config_path,  # As-is (if absolute or from current dir)
            Path(stage_config_path),  # Path object
        ]

        stage_config = None
        for path in possible_paths:
            try:
                with open(path, 'r') as f:
                    stage_config = yaml.safe_load(f)
                console.print(f"[green]✓ Stage loaded:[/green] {stage_config['stage']['name']}\n")
                return stage_config
            except FileNotFoundError:
                continue

        # If we get here, file not found
        raise FileNotFoundError(f"Stage config not found: {stage_config_path}")

    def _execute_llm_agent(
        self,
        agent_config: Dict[str, Any],
        prompt: str,
        trace: Dict[str, Any]
    ) -> AgentOutput:
        """Execute single agent with LLM call.

        Args:
            agent_config: Agent configuration from YAML
            prompt: Prompt to send to LLM
            trace: Execution trace to update

        Returns:
            AgentOutput with LLM response
        """
        agent_name = agent_config['name']
        agent_role = agent_config['role']

        console.print(f"[cyan]🤖 Executing agent:[/cyan] {agent_name} ({agent_role})")

        # Track execution
        start_time = time.time()
        start_timestamp = datetime.now().isoformat()

        try:
            # Call LLM
            llm_config = agent_config.get('llm_config', {})
            response = self.llm.complete(
                prompt,
                temperature=llm_config.get('temperature', 0.7),
                max_tokens=llm_config.get('max_tokens', 512)
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            end_timestamp = datetime.now().isoformat()

            # Parse response (expecting structured output)
            content = response.content.strip()

            # Try to parse JSON
            try:
                start_idx = content.find('{')
                end_idx = content.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = content[start_idx:end_idx + 1]
                    data = json.loads(json_str)
                    decision = data.get('decision', 'Unknown')
                    reasoning = data.get('reasoning', 'No reasoning provided')
                    confidence = data.get('confidence', 0.5)
                else:
                    # Fallback
                    decision = content[:100]
                    reasoning = content
                    confidence = 0.5
            except json.JSONDecodeError:
                decision = content[:100]
                reasoning = content
                confidence = 0.5

            # Update trace
            trace['agents'].append({
                'name': agent_name,
                'role': agent_role,
                'decision': decision,
                'reasoning': reasoning,
                'confidence': confidence,
                'latency_ms': elapsed_ms,
                'tokens': response.total_tokens,
                'start_timestamp': start_timestamp,
                'end_timestamp': end_timestamp,
                'prompt': prompt,
                'raw_response': content
            })

            console.print(f"[green]  ✓ Decision:[/green] {decision}")
            console.print(f"[dim]  Reasoning: {reasoning[:80]}...[/dim]")
            console.print(f"[dim]  Latency: {elapsed_ms}ms | Tokens: {response.total_tokens}[/dim]\n")

            return AgentOutput(
                agent_name=agent_name,
                decision=decision,
                reasoning=reasoning,
                confidence=confidence,
                metadata={
                    'role': agent_role,
                    'latency_ms': elapsed_ms,
                    'tokens': response.total_tokens
                }
            )

        except Exception as e:
            console.print(f"[red]  ✗ Agent failed: {e}[/red]\n")
            raise

    def _substitute_template_vars(
        self,
        value: Any,
        inputs: Dict[str, Any]
    ) -> Any:
        """Substitute {{ workflow.inputs.X }} template variables.

        Args:
            value: Value to substitute (string, dict, list, etc.)
            inputs: Input variables to substitute

        Returns:
            Value with templates substituted
        """
        if isinstance(value, str):
            # Replace {{ workflow.inputs.X }} with actual value
            import re
            pattern = r'\{\{\s*workflow\.inputs\.(\w+)\s*\}\}'

            def replace_func(match):
                var_name = match.group(1)
                return str(inputs.get(var_name, match.group(0)))

            return re.sub(pattern, replace_func, value)

        elif isinstance(value, dict):
            return {k: self._substitute_template_vars(v, inputs) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._substitute_template_vars(item, inputs) for item in value]

        else:
            return value

    def _build_agent_prompt(
        self,
        agent_config: Dict[str, Any],
        workflow_inputs: Dict[str, Any]
    ) -> str:
        """Build prompt for agent based on config and inputs.

        Args:
            agent_config: Agent configuration
            workflow_inputs: Workflow input variables

        Returns:
            Formatted prompt string
        """
        persona = agent_config.get('persona', '')
        role = agent_config['role']
        scenario = workflow_inputs.get('scenario', '')
        options = workflow_inputs.get('options', [])
        context = workflow_inputs.get('context', '')

        prompt = f"""You are {agent_config['name']}, a {role}.

Your persona: {persona}

SCENARIO: {scenario}"""

        if context:
            prompt += f"\n\nCONTEXT: {context}"

        prompt += """

AVAILABLE OPTIONS:
"""
        for option in options:
            prompt += f"  - {option}\n"

        prompt += """
TASK: Provide your analysis and recommendation.

Respond in this JSON format:
{
  "decision": "one of the options above (exact match)",
  "reasoning": "your detailed reasoning (2-3 sentences)",
  "confidence": 0.0-1.0
}

Your response (JSON only):"""

        return prompt

    def _run_stage(
        self,
        stage_config: Dict[str, Any],
        workflow_inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a workflow stage.

        Args:
            stage_config: Stage configuration
            workflow_inputs: Input variables

        Returns:
            Stage outputs
        """
        stage_info = stage_config['stage']
        console.print(f"\n[bold yellow]{'='*80}[/bold yellow]")
        console.print(f"[bold yellow]Executing Stage: {stage_info['name']}[/bold yellow]")
        console.print(f"[bold yellow]{'='*80}[/bold yellow]\n")

        # Initialize trace
        stage_trace = {
            'stage_name': stage_info['name'],
            'stage_type': stage_info['type'],
            'agents': [],
            'synthesis': None
        }

        # Execute agents
        agent_outputs = []
        agents_config = stage_info.get('agents', [])

        for agent_config in agents_config:
            prompt = self._build_agent_prompt(agent_config, workflow_inputs)
            agent_output = self._execute_llm_agent(agent_config, prompt, stage_trace)
            agent_outputs.append(agent_output)

        # Synthesize results
        console.print(f"[bold yellow]Synthesizing agent outputs...[/bold yellow]\n")

        collaboration_config = stage_info.get('collaboration', {})
        strategy_name = collaboration_config.get('strategy', 'consensus')
        strategy_config = collaboration_config.get('config', {})

        # For this demo, we'll use consensus strategy
        # In production, this would dispatch to the correct strategy
        from src.strategies.consensus import ConsensusStrategy

        strategy = ConsensusStrategy()
        synthesis_result = strategy.synthesize(agent_outputs, strategy_config)

        # Update trace
        stage_trace['synthesis'] = {
            'decision': synthesis_result.decision,
            'confidence': synthesis_result.confidence,
            'method': synthesis_result.method,
            'votes': synthesis_result.votes,
            'reasoning': synthesis_result.reasoning
        }

        self.execution_trace.append(stage_trace)

        # Display synthesis results
        self._display_synthesis_results(synthesis_result)

        return {
            'decision': synthesis_result.decision,
            'confidence': synthesis_result.confidence,
            'agent_outputs': agent_outputs,
            'synthesis_metadata': {
                'method': synthesis_result.method,
                'votes': synthesis_result.votes,
                'conflicts': synthesis_result.conflicts
            }
        }

    def _display_synthesis_results(self, result: SynthesisResult) -> None:
        """Display synthesis results in nice format."""
        console.print(Panel.fit(
            f"[bold green]Synthesis Complete[/bold green]\n\n"
            f"Decision: [bold]{result.decision}[/bold]\n"
            f"Confidence: {result.confidence:.0%}\n"
            f"Method: {result.method}",
            border_style="green"
        ))

        # Votes table
        if result.votes:
            vote_table = Table(title="Vote Distribution")
            vote_table.add_column("Option", style="cyan")
            vote_table.add_column("Votes", style="green", justify="right")
            vote_table.add_column("Percentage", style="yellow", justify="right")

            total_votes = sum(result.votes.values())
            for option, count in result.votes.items():
                percentage = (count / total_votes) * 100
                vote_table.add_row(
                    str(option),
                    str(count),
                    f"{percentage:.1f}%"
                )

            console.print(vote_table)

        console.print(f"\n[dim]Reasoning: {result.reasoning}[/dim]\n")

    def _generate_output(self) -> Dict[str, Any]:
        """Generate final workflow output."""
        workflow_config = self.config['workflow']
        output_specs = workflow_config.get('outputs', [])

        console.print(f"\n[bold yellow]{'='*80}[/bold yellow]")
        console.print(f"[bold yellow]Generating Workflow Output[/bold yellow]")
        console.print(f"[bold yellow]{'='*80}[/bold yellow]\n")

        # Build output from trace
        final_output = {
            'workflow_name': workflow_config['name'],
            'workflow_version': workflow_config['version'],
            'execution_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'stages': []
        }

        # Add stage outputs
        for stage_trace in self.execution_trace:
            stage_output = {
                'stage_name': stage_trace['stage_name'],
                'stage_type': stage_trace['stage_type'],
                'agents': stage_trace['agents'],
                'synthesis': stage_trace['synthesis']
            }
            final_output['stages'].append(stage_output)

        # Add final decision (from last stage)
        if self.execution_trace:
            last_stage = self.execution_trace[-1]
            final_output['final_decision'] = last_stage['synthesis']['decision']
            final_output['final_confidence'] = last_stage['synthesis']['confidence']

        # Calculate metrics
        total_tokens = sum(
            agent['tokens']
            for stage in self.execution_trace
            for agent in stage['agents']
        )
        total_latency = sum(
            agent['latency_ms']
            for stage in self.execution_trace
            for agent in stage['agents']
        )

        final_output['metrics'] = {
            'total_agents_executed': sum(
                len(stage['agents']) for stage in self.execution_trace
            ),
            'total_tokens': total_tokens,
            'total_latency_ms': total_latency,
            'stages_executed': len(self.execution_trace)
        }

        return final_output

    def _save_detailed_trace(self, output: Dict[str, Any]) -> str:
        """Save detailed trace with prompts and responses.

        Args:
            output: Output dictionary

        Returns:
            Path to detailed trace file
        """
        detailed_output = output.copy()

        # Add full prompts and responses to the detailed trace
        detailed_output['detailed_traces'] = []

        for stage in self.execution_trace:
            stage_detail = {
                'stage_name': stage['stage_name'],
                'stage_type': stage['stage_type'],
                'agents': []
            }

            for agent in stage['agents']:
                agent_detail = {
                    'name': agent['name'],
                    'role': agent['role'],
                    'start_timestamp': agent['start_timestamp'],
                    'end_timestamp': agent['end_timestamp'],
                    'latency_ms': agent['latency_ms'],
                    'tokens': agent['tokens'],
                    'prompt': agent['prompt'],
                    'raw_response': agent['raw_response'],
                    'parsed_output': {
                        'decision': agent['decision'],
                        'reasoning': agent['reasoning'],
                        'confidence': agent['confidence']
                    }
                }
                stage_detail['agents'].append(agent_detail)

            detailed_output['detailed_traces'].append(stage_detail)

        # Save to file
        trace_file = f"output_{output['workflow_name']}_detailed_{int(time.time())}.json"
        with open(trace_file, 'w') as f:
            json.dump(detailed_output, f, indent=2)

        return trace_file

    def _generate_gantt_chart(self, output: Dict[str, Any]) -> None:
        """Generate and display Gantt chart of execution timeline.

        Args:
            output: Output dictionary with timing information
        """
        console.print("\n[bold yellow]Execution Timeline (Gantt Chart)[/bold yellow]\n")

        # Parse timestamps and build timeline
        timeline_data = []

        for stage in self.execution_trace:
            for agent in stage['agents']:
                # Parse ISO timestamps
                start = datetime.fromisoformat(agent['start_timestamp'])
                end = datetime.fromisoformat(agent['end_timestamp'])

                timeline_data.append({
                    'name': agent['name'],
                    'role': agent['role'],
                    'start': start,
                    'end': end,
                    'duration_ms': agent['latency_ms'],
                    'tokens': agent['tokens']
                })

        # Find overall start and end
        if not timeline_data:
            return

        overall_start = min(item['start'] for item in timeline_data)
        overall_end = max(item['end'] for item in timeline_data)
        total_duration_ms = int((overall_end - overall_start).total_seconds() * 1000)

        # Create visual Gantt chart
        chart_width = 50

        console.print(f"[dim]Total Duration: {total_duration_ms}ms[/dim]\n")

        for i, item in enumerate(timeline_data):
            # Calculate relative position
            rel_start_ms = int((item['start'] - overall_start).total_seconds() * 1000)
            rel_end_ms = rel_start_ms + item['duration_ms']

            # Convert to chart positions
            start_pos = int((rel_start_ms / total_duration_ms) * chart_width)
            end_pos = int((rel_end_ms / total_duration_ms) * chart_width)
            bar_width = max(1, end_pos - start_pos)

            # Build visual bar
            bar = ' ' * start_pos + '█' * bar_width

            # Color coding
            colors = ['cyan', 'green', 'yellow', 'magenta', 'blue']
            color = colors[i % len(colors)]

            console.print(
                f"[{color}]{item['name']:20}[/{color}] "
                f"[dim]|[/dim] "
                f"[{color}]{bar}[/{color}] "
                f"[dim]{item['duration_ms']:4}ms {item['tokens']:4}tok[/dim]"
            )

        # Time axis
        console.print(f"\n[dim]{'0ms':20} | {' ' * (chart_width - 10)}{total_duration_ms}ms[/dim]\n")

    def _display_detailed_prompts(self, output: Dict[str, Any]) -> None:
        """Display detailed prompts and responses.

        Args:
            output: Output dictionary
        """
        console.print("\n[bold yellow]{'='*80}[/bold yellow]")
        console.print("[bold yellow]Detailed LLM Traces (Prompts & Responses)[/bold yellow]")
        console.print(f"[bold yellow]{'='*80}[/bold yellow]\n")

        for stage in self.execution_trace:
            console.print(f"[bold cyan]Stage: {stage['stage_name']}[/bold cyan]\n")

            for i, agent in enumerate(stage['agents'], 1):
                console.print(f"[bold green]Agent {i}: {agent['name']} ({agent['role']})[/bold green]")
                console.print(f"[dim]Latency: {agent['latency_ms']}ms | Tokens: {agent['tokens']}[/dim]\n")

                # Display prompt
                console.print("[yellow]═══ PROMPT ═══[/yellow]")
                prompt_syntax = Syntax(agent['prompt'], "text", theme="monokai", line_numbers=False)
                console.print(prompt_syntax)
                console.print()

                # Display response
                console.print("[green]═══ RAW RESPONSE ═══[/green]")
                response_syntax = Syntax(agent['raw_response'], "json", theme="monokai", line_numbers=False)
                console.print(response_syntax)
                console.print()

                # Display parsed output
                console.print("[cyan]═══ PARSED OUTPUT ═══[/cyan]")
                console.print(f"[cyan]Decision:[/cyan] {agent['decision']}")
                console.print(f"[cyan]Confidence:[/cyan] {agent['confidence']}")
                console.print(f"[cyan]Reasoning:[/cyan] {agent['reasoning'][:100]}...")
                console.print("\n" + "─" * 80 + "\n")

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute complete workflow from YAML config.

        Args:
            inputs: Workflow input variables

        Returns:
            Workflow outputs
        """
        console.print(Panel.fit(
            f"[bold cyan]M3 End-to-End YAML Workflow[/bold cyan]\n"
            f"Workflow: {self.config['workflow']['name']}\n"
            f"Description: {self.config['workflow']['description']}",
            border_style="cyan"
        ))

        # Initialize LLM
        self._initialize_llm()

        # Execute stages
        workflow_stages = self.config['workflow']['stages']

        for stage_def in workflow_stages:
            # Load stage config
            stage_config = self._load_stage_config(stage_def['config_path'])

            # Substitute template variables in stage inputs
            stage_input_templates = stage_def.get('inputs', {})
            resolved_inputs = self._substitute_template_vars(stage_input_templates, inputs)

            # Merge inputs
            stage_inputs = inputs.copy()
            stage_inputs.update(resolved_inputs)

            # Run stage
            stage_output = self._run_stage(stage_config, stage_inputs)

        # Generate final output
        final_output = self._generate_output()

        # Display final results
        self._display_final_output(final_output)

        # Display detailed traces (prompts & responses)
        self._display_detailed_prompts(final_output)

        # Display Gantt chart
        self._generate_gantt_chart(final_output)

        # Save detailed trace
        trace_file = self._save_detailed_trace(final_output)
        console.print(f"[green]✓ Detailed trace saved to:[/green] {trace_file}\n")

        # Cleanup
        if self.llm:
            self.llm.close()

        return final_output

    def _display_final_output(self, output: Dict[str, Any]) -> None:
        """Display final workflow output."""
        console.print(Panel.fit(
            f"[bold green]Workflow Complete![/bold green]\n\n"
            f"Final Decision: [bold]{output['final_decision']}[/bold]\n"
            f"Confidence: {output['final_confidence']:.0%}\n"
            f"Total Agents: {output['metrics']['total_agents_executed']}\n"
            f"Total Tokens: {output['metrics']['total_tokens']}\n"
            f"Total Latency: {output['metrics']['total_latency_ms']}ms",
            border_style="green"
        ))

        # Save output to file
        output_file = f"output_{output['workflow_name']}_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)

        console.print(f"\n[green]✓ Output saved to:[/green] {output_file}\n")


def main():
    """Run end-to-end YAML workflow demo."""
    # Define workflow inputs
    workflow_inputs = {
        'scenario': 'Product Launch Timing Decision',
        'options': [
            'Launch Now',
            'Wait 1 Month',
            'Launch Beta'
        ],
        'context': 'We have a working product but some bugs remain. Market is competitive.'
    }

    # Create simple YAML config for demo
    config_path = 'configs/workflows/e2e_simple_debate.yaml'

    try:
        # Run workflow
        runner = YAMLWorkflowRunner(config_path)
        output = runner.run(workflow_inputs)

        console.print("[bold green]✓ E2E workflow completed successfully![/bold green]")

    except FileNotFoundError as e:
        console.print(f"[red]✗ Config file not found: {e}[/red]")
        console.print("[yellow]Please ensure config files exist:[/yellow]")
        console.print(f"  - {config_path}")
        console.print(f"  - configs/stages/e2e_simple_debate_stage.yaml")

    except Exception as e:
        console.print(f"[red]✗ Workflow failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        console.print("\n[yellow]Note: Ensure Ollama is running with llama3.2:3b model[/yellow]")


if __name__ == "__main__":
    main()
