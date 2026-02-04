#!/usr/bin/env python3
"""Generate M5.1 demo metrics for visualization."""

import json
import random
from datetime import datetime, timedelta

# Variant configurations (from M5.1 demo scenario)
variants = {
    "control": {"model": "llama3.1:8b", "quality": 0.70, "speed": 5.0, "cost": 0.020},
    "variant_1": {"model": "gemma2:2b", "quality": 0.88, "speed": 4.5, "cost": 0.015},
    "variant_2": {"model": "phi3:mini", "quality": 0.75, "speed": 4.0, "cost": 0.018},
    "variant_3": {"model": "mistral:7b", "quality": 0.82, "speed": 6.0, "cost": 0.025},
}

def generate_metrics():
    """Generate realistic experiment metrics."""
    all_metrics = []
    summary = {}
    base_time = datetime(2026, 2, 1, 10, 0, 0)  # Fixed start time

    for variant_id, config in variants.items():
        print(f"Generating metrics for {variant_id}: {config['model']}...")

        variant_start = base_time
        cumulative_time = 0

        # Generate 50 executions per variant
        for i in range(50):
            # Add realistic variation
            quality = config["quality"] + random.uniform(-0.02, 0.02)
            duration = config["speed"] + random.uniform(-0.5, 0.5)
            cost = config["cost"] + random.uniform(-0.002, 0.002)

            # Calculate timestamp (executions happen sequentially)
            timestamp = variant_start + timedelta(seconds=cumulative_time)
            cumulative_time += max(0.1, duration)

            all_metrics.append({
                "variant_id": variant_id,
                "model": config["model"],
                "execution_index": i,
                "timestamp": timestamp.isoformat(),
                "quality_score": max(0, min(1, quality)),
                "duration_seconds": max(0.1, duration),
                "cost_usd": max(0, cost),
                "start_time": timestamp.isoformat(),
                "end_time": (timestamp + timedelta(seconds=max(0.1, duration))).isoformat(),
            })

        # Calculate summary stats
        variant_metrics = [m for m in all_metrics if m["variant_id"] == variant_id]
        summary[variant_id] = {
            "model": config["model"],
            "executions": len(variant_metrics),
            "avg_quality": sum(m["quality_score"] for m in variant_metrics) / len(variant_metrics),
            "avg_duration": sum(m["duration_seconds"] for m in variant_metrics) / len(variant_metrics),
            "avg_cost": sum(m["cost_usd"] for m in variant_metrics) / len(variant_metrics),
            "min_quality": min(m["quality_score"] for m in variant_metrics),
            "max_quality": max(m["quality_score"] for m in variant_metrics),
            "total_duration": sum(m["duration_seconds"] for m in variant_metrics),
            "total_cost": sum(m["cost_usd"] for m in variant_metrics),
        }

    # Export data
    output = {
        "summary": summary,
        "winner": {
            "variant_id": "variant_1",
            "model": "gemma2:2b",
            "improvement_percentage": 25.7,
            "confidence_level": 0.999,
        },
        "metrics": all_metrics,
    }

    output_file = "/tmp/m5_demo_metrics.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Generated {len(all_metrics)} execution metrics")
    print(f"📊 Exported to: {output_file}")

    # Print summary
    print("\nSummary by Variant:")
    for variant_id, stats in summary.items():
        print(f"\n  {variant_id}: {stats['model']}")
        print(f"    Quality: {stats['avg_quality']:.3f} (±{(stats['max_quality']-stats['min_quality'])/2:.3f})")
        print(f"    Avg Duration: {stats['avg_duration']:.2f}s")
        print(f"    Total Duration: {stats['total_duration']:.1f}s")
        print(f"    Total Cost: ${stats['total_cost']:.3f}")

    return output_file

if __name__ == "__main__":
    generate_metrics()
