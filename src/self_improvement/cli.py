#!/usr/bin/env python3
"""
M5 Self-Improvement CLI.

Command-line interface for running M5 improvement iterations and monitoring progress.

Usage:
    m5 run <agent-name> [--config CONFIG_FILE]
    m5 analyze <agent-name> [--window HOURS]
    m5 optimize <agent-name> [--config CONFIG_FILE]
    m5 status <agent-name>
    m5 metrics <agent-name>
    m5 pause <agent-name>
    m5 resume <agent-name>
    m5 reset <agent-name>
    m5 health
    m5 check-experiments <agent-name>
    m5 list-agents
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from src.constants.durations import HOURS_PER_WEEK
from src.constants.limits import THRESHOLD_MEDIUM_COUNT
from src.database import get_database, get_session, init_database
from src.self_improvement.loop import LoopConfig, M5SelfImprovementLoop
from src.self_improvement.performance_analyzer import PerformanceAnalyzer

# Initialize observability database if not already initialized
try:
    get_database()
except RuntimeError:
    # Use default SQLite database
    db_url = f"sqlite:///{Path.home()}/.claude/observability.db"
    init_database(db_url)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Table column widths for formatted output
TABLE_AGENT_NAME_WIDTH = 30
TABLE_PHASE_WIDTH = 15
TABLE_STATUS_WIDTH = 15
TABLE_ITERATION_WIDTH = 10


class M5CLI:
    """M5 Self-Improvement CLI."""

    def __init__(self) -> None:
        """Initialize CLI."""
        pass

    def run_iteration(self, agent_name: str, config_file: Optional[str] = None) -> int:
        """
        Run complete improvement iteration.

        Args:
            agent_name: Name of agent
            config_file: Optional path to config file

        Returns:
            Exit code (0 = success, 1 = failure)
        """
        print(f"🔄 Starting M5 improvement iteration for: {agent_name}")

        # Load config
        config = self._load_config(config_file)

        # Run iteration
        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session, config)

            try:
                result = loop.run_iteration(agent_name)

                if result.success:
                    print(f"\n✅ Iteration {result.iteration_number} completed successfully!")
                    print(f"   Phases: {' → '.join([p.value for p in result.phases_completed])}")
                    print(f"   Duration: {result.duration_seconds:.1f}s")

                    # Show phase results
                    if result.detection_result and not result.detection_result.has_problem:
                        print("   No problems detected - agent performing well")

                    if result.deployment_result:
                        print(f"   Deployed: {result.deployment_result.deployment_id}")
                        print(f"   Rollback monitoring: {'enabled' if result.deployment_result.rollback_monitoring_enabled else 'disabled'}")

                    return 0
                else:
                    print("\n❌ Iteration failed!")
                    print(f"   Error: {result.error}")
                    if result.error_phase:
                        print(f"   Failed at phase: {result.error_phase.value}")
                    return 1

            except Exception as e:
                print(f"\n❌ Error running iteration: {e}")
                logger.exception("Iteration error")
                return 1

    def analyze(self, agent_name: str, window_hours: int = HOURS_PER_WEEK) -> int:
        """
        Analyze agent performance (Phase 2 only).

        Args:
            agent_name: Name of agent
            window_hours: Analysis window in hours

        Returns:
            Exit code
        """
        print(f"📊 Analyzing performance for: {agent_name}")
        print(f"   Window: {window_hours} hours ({window_hours/24:.1f} days)")

        with get_session() as session:
            analyzer = PerformanceAnalyzer(session)

            try:
                profile = analyzer.analyze_agent_performance(
                    agent_name=agent_name,
                    window_hours=window_hours,
                    min_executions=THRESHOLD_MEDIUM_COUNT,
                )

                print("\n📈 Performance Analysis:")
                print(f"   Total executions: {profile.total_executions}")
                print(f"   Time window: {profile.window_start.strftime('%Y-%m-%d %H:%M')} to {profile.window_end.strftime('%Y-%m-%d %H:%M')}")

                print("\n   Metrics:")
                for metric_name, metric_data in profile.metrics.items():
                    mean = metric_data.get('mean')
                    std = metric_data.get('std')
                    if mean is not None:
                        print(f"   - {metric_name}: {mean:.4f} (±{std:.4f})" if std else f"   - {metric_name}: {mean:.4f}")

                return 0

            except Exception as e:
                print(f"\n❌ Analysis failed: {e}")
                logger.exception("Analysis error")
                return 1

    def optimize(self, agent_name: str, config_file: Optional[str] = None) -> int:
        """
        Alias for run_iteration (more intuitive name).

        Args:
            agent_name: Name of agent
            config_file: Optional path to config file

        Returns:
            Exit code
        """
        return self.run_iteration(agent_name, config_file)

    def status(self, agent_name: str) -> int:
        """
        Show loop status for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        print(f"📋 M5 Loop Status: {agent_name}")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            # Get state
            state = loop.get_state(agent_name)
            if not state:
                print("   No loop state found (not yet started)")
                return 0

            print(f"\n   Current phase: {state['current_phase']}")
            print(f"   Status: {state['status']}")
            print(f"   Iteration: {state['iteration_number']}")
            print(f"   Started: {state['started_at']}")
            print(f"   Updated: {state['updated_at']}")

            if state['last_error']:
                print(f"   Last error: {state['last_error']}")

            # Get progress
            progress = loop.get_progress(agent_name)
            print(f"\n   Health: {progress.health_status}")
            print(f"   Total completed: {progress.total_iterations_completed}")

            return 0

    def metrics(self, agent_name: str) -> int:
        """
        Show metrics for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        print(f"📊 M5 Metrics: {agent_name}")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            metrics = loop.get_metrics(agent_name)
            if not metrics:
                print("   No metrics available (no iterations run)")
                return 0

            print("\n   Iteration Metrics:")
            print(f"   - Total iterations: {metrics['total_iterations']}")
            print(f"   - Successful: {metrics['successful_iterations']}")
            print(f"   - Failed: {metrics['failed_iterations']}")
            print(f"   - Success rate: {metrics['success_rate']:.1%}")
            print(f"   - Avg duration: {metrics['avg_iteration_duration']:.1f}s")

            print("\n   Improvement Metrics:")
            print(f"   - Experiments run: {metrics['total_experiments']}")
            print(f"   - Successful deployments: {metrics['successful_deployments']}")
            print(f"   - Rollbacks: {metrics['rollbacks']}")

            print("\n   Phase Success Rates:")
            for phase, rate in metrics['phase_success_rates'].items():
                print(f"   - {phase}: {rate:.1%}")

            if metrics['last_iteration_at']:
                print(f"\n   Last iteration: {metrics['last_iteration_at']}")

            return 0

    def pause(self, agent_name: str) -> int:
        """
        Pause loop for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        print(f"⏸️  Pausing M5 loop for: {agent_name}")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            try:
                loop.pause(agent_name)
                print("   ✅ Loop paused")
                return 0
            except Exception as e:
                print(f"   ❌ Failed to pause: {e}")
                return 1

    def resume(self, agent_name: str) -> int:
        """
        Resume paused loop.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        print(f"▶️  Resuming M5 loop for: {agent_name}")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            try:
                loop.resume(agent_name)
                print("   ✅ Loop resumed")
                return 0
            except Exception as e:
                print(f"   ❌ Failed to resume: {e}")
                return 1

    def reset(self, agent_name: str) -> int:
        """
        Reset loop state for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        # Confirm reset
        response = input(f"⚠️  Reset all state for {agent_name}? This cannot be undone. [y/N]: ")
        if response.lower() != 'y':
            print("   Cancelled")
            return 0

        print(f"🔄 Resetting M5 loop state for: {agent_name}")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            try:
                loop.reset_state(agent_name)
                print("   ✅ State reset")
                return 0
            except Exception as e:
                print(f"   ❌ Failed to reset: {e}")
                return 1

    def health(self) -> int:
        """
        Check M5 system health.

        Returns:
            Exit code
        """
        print("🏥 M5 System Health Check")

        with get_session() as session:
            # Note: M5CLI doesn't have coord_db attribute, using None for now
            loop = M5SelfImprovementLoop(None, session)

            health = loop.health_check()

            print(f"\n   Overall status: {health['status'].upper()}")
            print(f"   Timestamp: {health['timestamp']}")

            print("\n   Components:")
            for component, status in health['components'].items():
                icon = "✅" if status == "healthy" else "❌"
                print(f"   {icon} {component}: {status}")

            return 0 if health['status'] == 'healthy' else 1

    def check_experiments(self, agent_name: str) -> int:
        """
        Check experiment status for agent.

        Args:
            agent_name: Name of agent

        Returns:
            Exit code
        """
        print(f"🧪 Checking experiments for: {agent_name}")

        with get_session() as session:
            from sqlmodel import select
            from src.self_improvement.storage.experiment_models import M5Experiment
            from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator

            orchestrator = ExperimentOrchestrator(session)

            # Get all experiments for agent using SQLModel
            stmt = (
                select(M5Experiment)
                .where(M5Experiment.agent_name == agent_name)
                .order_by(M5Experiment.created_at.desc())  # type: ignore[attr-defined]
                .limit(5)
            )
            experiments = session.exec(stmt).all()

            if not experiments:
                print("   No experiments found")
                return 0

            print("\n   Recent Experiments:")
            for exp in experiments:
                print(f"\n   Experiment: {exp.id}")
                print(f"   - Status: {exp.status}")
                print(f"   - Created: {exp.created_at}")

                # Get results if completed
                if exp.status == 'completed':
                    try:
                        analysis = orchestrator.analyze_experiment(exp.id)
                        winner = analysis.winner.variant_id if analysis.winner else 'none'
                        print(f"   - Winner: {winner}")
                    except Exception as e:
                        print(f"   - Analysis error: {e}")

            return 0

    def list_agents(self) -> int:
        """
        List all agents with M5 state.

        Returns:
            Exit code
        """
        print("📋 Agents with M5 Loop State")
        print("   (Not yet implemented: requires coord_db attribute)")
        # TODO: Implement proper database query for M5 loop state
        # rows = self.coord_db.query("SELECT agent_name, current_phase, status, iteration_number FROM m5_loop_state ORDER BY updated_at DESC")
        return 0

    def _load_config(self, config_file: Optional[str]) -> LoopConfig:
        """
        Load config from file or return defaults.

        Args:
            config_file: Path to config file (optional)

        Returns:
            LoopConfig
        """
        if not config_file:
            return LoopConfig()

        config_path = Path(config_file)
        if not config_path.exists():
            print(f"⚠️  Config file not found: {config_file}, using defaults")
            return LoopConfig()

        try:
            with open(config_path) as f:
                config_data = json.load(f)
            return LoopConfig.from_dict(config_data)
        except Exception as e:
            print(f"⚠️  Error loading config: {e}, using defaults")
            return LoopConfig()


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='M5 Self-Improvement CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  m5 run my_agent                    # Run improvement iteration
  m5 analyze my_agent --window 336   # Analyze last 2 weeks
  m5 optimize my_agent               # Run optimization (alias for run)
  m5 status my_agent                 # Check status
  m5 metrics my_agent                # Show metrics
  m5 pause my_agent                  # Pause loop
  m5 resume my_agent                 # Resume loop
  m5 reset my_agent                  # Reset state
  m5 health                          # System health check
  m5 check-experiments my_agent      # Check experiments
  m5 list-agents                     # List all agents
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # run command
    run_parser = subparsers.add_parser('run', help='Run improvement iteration')
    run_parser.add_argument('agent_name', help='Name of agent')
    run_parser.add_argument('--config', help='Path to config file')

    # analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze agent performance')
    analyze_parser.add_argument('agent_name', help='Name of agent')
    analyze_parser.add_argument('--window', type=int, default=HOURS_PER_WEEK, help=f'Analysis window in hours (default: {HOURS_PER_WEEK})')

    # optimize command (alias for run)
    optimize_parser = subparsers.add_parser('optimize', help='Optimize agent (alias for run)')
    optimize_parser.add_argument('agent_name', help='Name of agent')
    optimize_parser.add_argument('--config', help='Path to config file')

    # status command
    status_parser = subparsers.add_parser('status', help='Show loop status')
    status_parser.add_argument('agent_name', help='Name of agent')

    # metrics command
    metrics_parser = subparsers.add_parser('metrics', help='Show metrics')
    metrics_parser.add_argument('agent_name', help='Name of agent')

    # pause command
    pause_parser = subparsers.add_parser('pause', help='Pause loop')
    pause_parser.add_argument('agent_name', help='Name of agent')

    # resume command
    resume_parser = subparsers.add_parser('resume', help='Resume loop')
    resume_parser.add_argument('agent_name', help='Name of agent')

    # reset command
    reset_parser = subparsers.add_parser('reset', help='Reset loop state')
    reset_parser.add_argument('agent_name', help='Name of agent')

    # health command
    subparsers.add_parser('health', help='Check system health')

    # check-experiments command
    check_exp_parser = subparsers.add_parser('check-experiments', help='Check experiments')
    check_exp_parser.add_argument('agent_name', help='Name of agent')

    # list-agents command
    subparsers.add_parser('list-agents', help='List all agents')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    cli = M5CLI()

    # Route to appropriate command
    if args.command == 'run':
        return cli.run_iteration(args.agent_name, args.config)
    elif args.command == 'analyze':
        return cli.analyze(args.agent_name, args.window)
    elif args.command == 'optimize':
        return cli.optimize(args.agent_name, args.config)
    elif args.command == 'status':
        return cli.status(args.agent_name)
    elif args.command == 'metrics':
        return cli.metrics(args.agent_name)
    elif args.command == 'pause':
        return cli.pause(args.agent_name)
    elif args.command == 'resume':
        return cli.resume(args.agent_name)
    elif args.command == 'reset':
        return cli.reset(args.agent_name)
    elif args.command == 'health':
        return cli.health()
    elif args.command == 'check-experiments':
        return cli.check_experiments(args.agent_name)
    elif args.command == 'list-agents':
        return cli.list_agents()
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
