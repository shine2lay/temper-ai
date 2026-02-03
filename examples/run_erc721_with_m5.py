#!/usr/bin/env python3
"""
ERC721 Generator with M5 Self-Improvement Integration

Runs the ERC721 generation workflow, scores quality, then uses the M5
self-improvement loop to analyze results and generate improved configurations
for subsequent runs.

Usage:
    python examples/run_erc721_with_m5.py --model llama3:8b --iterations 3
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.self_improvement.metrics.erc721_quality import (
    score_erc721_workflow,
)
from src.self_improvement.strategies.erc721_strategy import ERC721WorkflowStrategy
from src.self_improvement.strategies.strategy import AgentConfig, LearnedPattern

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_single_iteration(
    workspace_base: Path,
    contract_name: str,
    token_name: str,
    token_symbol: str,
    llm_model: str,
    iteration: int,
    use_llm: bool = True,
) -> Dict:
    """Run a single workflow iteration and score it.

    Args:
        workspace_base: Base workspace directory
        contract_name: Contract name
        token_name: Token name
        token_symbol: Token symbol
        llm_model: Ollama model name
        iteration: Iteration number
        use_llm: Whether to use LLM

    Returns:
        Results dict with quality score
    """
    from examples.run_erc721_generator import create_workspace, run_workflow

    logger.info(f"\n{'='*60}")
    logger.info(f"  ITERATION {iteration}")
    logger.info(f"  Model: {llm_model}")
    logger.info(f"{'='*60}")

    workspace = create_workspace(workspace_base)

    results = run_workflow(
        workspace=workspace,
        contract_name=contract_name,
        token_name=token_name,
        token_symbol=token_symbol,
        llm_model=llm_model,
        use_llm=use_llm,
    )

    results["iteration"] = iteration
    results["model"] = llm_model

    return results


def generate_improvement_variants(
    current_config: Dict,
    quality_score: float,
    patterns: List[LearnedPattern],
) -> List[Dict]:
    """Use M5 strategy to generate config variants.

    Args:
        current_config: Current agent config as dict
        quality_score: Score from last run
        patterns: Learned patterns

    Returns:
        List of variant config dicts
    """
    strategy = ERC721WorkflowStrategy()

    # Build AgentConfig from dict
    config = AgentConfig(
        inference=current_config.get("inference", {}),
        prompt=current_config.get("prompt", {}),
        metadata=current_config.get("metadata", {}),
    )

    # Determine problem type based on score
    if quality_score < 0.3:
        problem_type = "low_quality"
    elif quality_score < 0.6:
        problem_type = "high_error_rate"
    else:
        problem_type = "inconsistent_output"

    if not strategy.is_applicable(problem_type):
        logger.info(f"Strategy not applicable for problem type: {problem_type}")
        return []

    # Add problem pattern
    if not patterns:
        patterns = [
            LearnedPattern(
                pattern_type=problem_type,
                description=f"Quality score {quality_score:.2f}",
                support=1,
                confidence=0.8,
                evidence={"quality_score": quality_score},
            )
        ]

    variants = strategy.generate_variants(config, patterns)

    logger.info(f"Generated {len(variants)} improvement variants:")
    for i, v in enumerate(variants):
        change = v.metadata.get("change", "unknown")
        logger.info(f"  Variant {i+1}: {change}")

    return [
        {
            "inference": v.inference,
            "prompt": v.prompt,
            "metadata": v.metadata,
        }
        for v in variants
    ]


def main():
    parser = argparse.ArgumentParser(
        description="ERC721 Generator with M5 Self-Improvement",
    )
    parser.add_argument("--model", default="llama3:8b", help="Starting Ollama model")
    parser.add_argument("--contract-name", default="SimpleNFT", help="Contract name")
    parser.add_argument("--token-name", default="SimpleNFT", help="Token name")
    parser.add_argument("--token-symbol", default="SNFT", help="Token symbol")
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of improvement iterations",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run in deterministic mode (useful for testing the M5 loop structure)",
    )
    parser.add_argument(
        "--workspace-dir",
        default=str(PROJECT_ROOT / "workspace"),
        help="Base directory for workspaces",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ERC721 Generator with M5 Self-Improvement")
    print("=" * 60)
    print(f"  Model: {args.model}")
    print(f"  Iterations: {args.iterations}")
    print(f"  Contract: {args.contract_name}")
    print("=" * 60)

    workspace_base = Path(args.workspace_dir)
    all_results = []
    current_model = args.model
    current_config = {
        "inference": {
            "model": args.model,
            "temperature": 0.2,
            "max_tokens": 4096,
        },
        "prompt": {},
        "metadata": {},
    }
    patterns: List[LearnedPattern] = []

    for iteration in range(1, args.iterations + 1):
        # --- RUN WORKFLOW ---
        results = run_single_iteration(
            workspace_base=workspace_base,
            contract_name=args.contract_name,
            token_name=args.token_name,
            token_symbol=args.token_symbol,
            llm_model=current_model,
            iteration=iteration,
            use_llm=not args.no_llm,
        )
        all_results.append(results)

        quality = results.get("quality_score", 0.0) or 0.0
        logger.info(f"\nIteration {iteration} quality score: {quality:.2f}")

        # Record pattern from this run
        if quality < 0.8:
            problem_type = "low_quality" if quality < 0.5 else "high_error_rate"
            patterns.append(
                LearnedPattern(
                    pattern_type=problem_type,
                    description=f"Iteration {iteration}: quality={quality:.2f}",
                    support=1,
                    confidence=min(0.9, 0.5 + iteration * 0.1),
                    evidence={
                        "quality_score": quality,
                        "iteration": iteration,
                        "model": current_model,
                    },
                )
            )

        # --- M5 SELF-IMPROVEMENT ---
        if iteration < args.iterations:
            logger.info("\n--- M5 Self-Improvement Analysis ---")

            # DETECT: Is quality below threshold?
            if quality >= 0.8:
                logger.info("Quality score >= 0.8, no improvement needed.")
                logger.info("Continuing with same config for comparison.")
                continue

            # ANALYZE: What went wrong?
            breakdown = results.get("quality_breakdown", {})
            weak_areas = []
            for metric, data in breakdown.items():
                if isinstance(data, dict) and data.get("score", 1.0) < 0.5:
                    weak_areas.append(metric)
            logger.info(f"Weak areas: {weak_areas or 'none identified'}")

            # STRATEGY: Generate variants
            variants = generate_improvement_variants(
                current_config, quality, patterns
            )

            if variants:
                # EXPERIMENT: Pick the best variant to try next
                # For simplicity, try the first variant (lower temperature)
                # In full M5, this would run all variants and compare
                best_variant = variants[0]
                logger.info(f"Applying variant: {best_variant['metadata'].get('change', 'unknown')}")

                # DEPLOY: Update config for next iteration
                if "model" in best_variant["inference"]:
                    current_model = best_variant["inference"]["model"]
                current_config = best_variant
            else:
                logger.info("No applicable variants. Continuing with same config.")

    # --- FINAL COMPARISON ---
    print("\n" + "=" * 60)
    print("  M5 SELF-IMPROVEMENT RESULTS")
    print("=" * 60)

    for r in all_results:
        iteration = r.get("iteration", "?")
        model = r.get("model", "?")
        quality = r.get("quality_score", 0.0) or 0.0
        duration = r.get("duration_seconds", 0.0)
        print(f"\n  Iteration {iteration}:")
        print(f"    Model: {model}")
        print(f"    Quality: {quality:.2f}")
        print(f"    Duration: {duration:.1f}s")

        breakdown = r.get("quality_breakdown", {})
        if breakdown:
            for metric, data in breakdown.items():
                if isinstance(data, dict):
                    score = data.get("score", "N/A")
                    print(f"    {metric}: {score}")
                    details = data.get("details", {})
                    if isinstance(details, dict):
                        if "stdout" in details and details["stdout"]:
                            print(f"      stdout: {details['stdout']}")
                        if "stderr" in details and details["stderr"]:
                            print(f"      stderr: {details['stderr']}")
                        if "passing" in details:
                            print(f"      passing: {details['passing']}, failing: {details['failing']}")

    # Compare first vs last
    if len(all_results) >= 2:
        first_q = all_results[0].get("quality_score", 0) or 0
        last_q = all_results[-1].get("quality_score", 0) or 0
        delta = last_q - first_q
        print(f"\n  Improvement: {first_q:.2f} -> {last_q:.2f} ({'+' if delta >= 0 else ''}{delta:.2f})")

    print("=" * 60)


if __name__ == "__main__":
    main()
