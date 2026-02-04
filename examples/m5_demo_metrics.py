#!/usr/bin/env python3
"""
M5.1 Demo: Metrics Collection (Non-Interactive)

Runs the M5.1 demo and exports metrics for visualization.
"""

import json
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/home/shinelay/meta-autonomous-framework")

from src.observability.models import AgentExecution
from src.self_improvement.data_models import AgentConfig, ExperimentConfig
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.storage.observability_store import ObservabilityStore


def main():
    """Run demo and collect metrics."""
    print("Running M5.1 demo and collecting metrics...")

    # Initialize
    obs_store = ObservabilityStore(":memory:")
    obs_store.create_tables()
    analyzer = PerformanceAnalyzer(obs_store)
    orchestrator = ExperimentOrchestrator(obs_store)

    # Variant configurations
    variants = {
        "control": {
            "model": "llama3.1:8b",
            "quality": 0.70,
            "speed": 5.0,
            "cost": 0.020,
        },
        "variant_1": {
            "model": "gemma2:2b",
            "quality": 0.88,
            "speed": 4.5,
            "cost": 0.015,
        },
        "variant_2": {
            "model": "phi3:mini",
            "quality": 0.75,
            "speed": 4.0,
            "cost": 0.018,
        },
        "variant_3": {
            "model": "mistral:7b",
            "quality": 0.82,
            "speed": 6.0,
            "cost": 0.025,
        },
    }

    # Collect metrics
    all_metrics = []
    start_time = datetime.utcnow()

    for variant_id, config in variants.items():
        print(f"  Simulating {variant_id}: {config['model']}...")

        variant_start = datetime.utcnow()

        # Create 50 execution records per variant
        session = obs_store.get_session()
        try:
            for i in range(50):
                # Add small random variation
                quality = config["quality"] + random.uniform(-0.02, 0.02)
                speed = config["speed"] + random.uniform(-0.5, 0.5)
                cost = config["cost"] + random.uniform(-0.002, 0.002)

                # Timestamp with realistic spacing
                timestamp = variant_start + timedelta(seconds=i * speed)

                record = AgentExecution(
                    agent_name="product_extractor",
                    config_version=variant_id,
                    model_name=config["model"],
                    quality_score=max(0, min(1, quality)),
                    cost_usd=max(0, cost),
                    duration_seconds=max(0.1, speed),
                    input_tokens=100,
                    output_tokens=50,
                    success=True,
                    timestamp=timestamp,
                    metadata={"variant": variant_id},
                )

                session.add(record)

                # Track metrics
                all_metrics.append({
                    "variant_id": variant_id,
                    "model": config["model"],
                    "execution_index": i,
                    "timestamp": timestamp.isoformat(),
                    "quality_score": record.quality_score,
                    "duration_seconds": record.duration_seconds,
                    "cost_usd": record.cost_usd,
                    "cumulative_time": (timestamp - variant_start).total_seconds(),
                })

            session.commit()
            print(f"    ✓ {len(all_metrics)} total executions recorded")
        finally:
            session.close()

    # Create experiment
    print("\n  Creating experiment...")
    agent_config = AgentConfig(
        agent_name="product_extractor",
        model_name="llama3.1:8b",
        system_prompt="Extract product information",
        temperature=0.7,
    )

    experiment_config = ExperimentConfig(
        name="Find Best Ollama Model",
        description="Test alternative models",
        target_samples_per_variant=50,
        target_metric="quality_score",
        significance_level=0.05,
    )

    experiment = orchestrator.create_experiment(agent_config, experiment_config)

    # Add variants
    for variant_id, config in list(variants.items())[1:]:  # Skip control
        variant_config = AgentConfig(
            agent_name="product_extractor",
            model_name=config["model"],
            system_prompt="Extract product information",
            temperature=0.7,
        )
        orchestrator.add_variant(experiment.id, variant_config, f"Testing {config['model']}")

    # Get winner
    print("  Analyzing results...")
    winner = orchestrator.get_winner(experiment.id, force=True)

    # Compute summary statistics
    summary = {}
    for variant_id, config in variants.items():
        variant_metrics = [m for m in all_metrics if m["variant_id"] == variant_id]

        summary[variant_id] = {
            "model": config["model"],
            "executions": len(variant_metrics),
            "avg_quality": sum(m["quality_score"] for m in variant_metrics) / len(variant_metrics),
            "avg_duration": sum(m["duration_seconds"] for m in variant_metrics) / len(variant_metrics),
            "avg_cost": sum(m["cost_usd"] for m in variant_metrics) / len(variant_metrics),
            "total_duration": max(m["cumulative_time"] for m in variant_metrics) if variant_metrics else 0,
        }

    # Output results
    print("\n" + "=" * 70)
    print("METRICS COLLECTED")
    print("=" * 70)

    print("\nSummary by Variant:")
    for variant_id, stats in summary.items():
        print(f"\n  {variant_id}: {stats['model']}")
        print(f"    Executions: {stats['executions']}")
        print(f"    Avg Quality: {stats['avg_quality']:.3f}")
        print(f"    Avg Duration: {stats['avg_duration']:.2f}s")
        print(f"    Avg Cost: ${stats['avg_cost']:.4f}")
        print(f"    Total Time: {stats['total_duration']:.1f}s")

    if winner:
        print(f"\n🏆 Winner: {winner.winner_variant_id}")
        print(f"   Improvement: {winner.improvement_percentage:+.1f}%")
        print(f"   Confidence: {winner.confidence_level:.1%}")

    # Export data
    output_file = "/tmp/m5_demo_metrics.json"
    with open(output_file, "w") as f:
        json.dump({
            "summary": summary,
            "winner": {
                "variant_id": winner.winner_variant_id if winner else None,
                "improvement_percentage": winner.improvement_percentage if winner else None,
                "confidence_level": winner.confidence_level if winner else None,
            } if winner else None,
            "metrics": all_metrics,
        }, f, indent=2)

    print(f"\n✅ Metrics exported to: {output_file}")
    return output_file


if __name__ == "__main__":
    main()
