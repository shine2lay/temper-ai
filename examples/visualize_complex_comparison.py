#!/usr/bin/env python3
"""
M5 Complex Model Comparison - 20+ models with realistic task complexity

Simulates different types of tasks (simple, medium, complex, edge cases)
and shows how different models perform across task types.
"""

import random
from collections import defaultdict


# ANSI colors
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RED = '\033[91m'

# EXPANDED model catalog - 22 models
MODELS = {
    # Tiny models (1-4B)
    "qwen2:0.5b": {"base_quality": 0.62, "speed": 3.0, "cost": 0.010, "params": "0.5B", "family": "Qwen", "complexity_factor": 0.7},
    "qwen2:1.5b": {"base_quality": 0.68, "speed": 3.5, "cost": 0.012, "params": "1.5B", "family": "Qwen", "complexity_factor": 0.75},
    "gemma2:2b": {"base_quality": 0.88, "speed": 4.5, "cost": 0.015, "params": "2B", "family": "Gemma", "complexity_factor": 0.90},
    "llama3.2:3b": {"base_quality": 0.73, "speed": 4.2, "cost": 0.016, "params": "3B", "family": "Llama", "complexity_factor": 0.80},
    "phi3:mini": {"base_quality": 0.75, "speed": 4.0, "cost": 0.018, "params": "3.8B", "family": "Phi", "complexity_factor": 0.82},

    # Small-Medium models (6-8B)
    "deepseek-coder:6.7b": {"base_quality": 0.80, "speed": 5.8, "cost": 0.022, "params": "6.7B", "family": "DeepSeek", "complexity_factor": 0.88},
    "gemma:7b": {"base_quality": 0.83, "speed": 5.2, "cost": 0.021, "params": "7B", "family": "Gemma", "complexity_factor": 0.89},
    "mistral:7b": {"base_quality": 0.82, "speed": 6.0, "cost": 0.025, "params": "7B", "family": "Mistral", "complexity_factor": 0.88},
    "qwen2:7b": {"base_quality": 0.84, "speed": 5.5, "cost": 0.023, "params": "7B", "family": "Qwen", "complexity_factor": 0.90},
    "llama3.1:8b": {"base_quality": 0.70, "speed": 5.0, "cost": 0.020, "params": "8B", "family": "Llama", "complexity_factor": 0.85},

    # Medium models (13-15B)
    "codellama:13b": {"base_quality": 0.86, "speed": 7.5, "cost": 0.032, "params": "13B", "family": "CodeLlama", "complexity_factor": 0.92},
    "phi3:medium": {"base_quality": 0.85, "speed": 7.0, "cost": 0.030, "params": "14B", "family": "Phi", "complexity_factor": 0.91},
    "qwen2:14b": {"base_quality": 0.87, "speed": 7.2, "cost": 0.031, "params": "14B", "family": "Qwen", "complexity_factor": 0.93},
    "wizardcoder:13b": {"base_quality": 0.84, "speed": 7.8, "cost": 0.033, "params": "13B", "family": "WizardCoder", "complexity_factor": 0.90},
    "vicuna:13b": {"base_quality": 0.81, "speed": 7.3, "cost": 0.029, "params": "13B", "family": "Vicuna", "complexity_factor": 0.88},

    # Large models (30-34B)
    "codellama:34b": {"base_quality": 0.89, "speed": 9.5, "cost": 0.042, "params": "34B", "family": "CodeLlama", "complexity_factor": 0.95},
    "deepseek-coder:33b": {"base_quality": 0.90, "speed": 9.8, "cost": 0.043, "params": "33B", "family": "DeepSeek", "complexity_factor": 0.96},

    # Very Large models (47-70B+)
    "mixtral:8x7b": {"base_quality": 0.91, "speed": 10.0, "cost": 0.045, "params": "47B", "family": "Mixtral", "complexity_factor": 0.97},
    "llama3.1:70b": {"base_quality": 0.94, "speed": 12.0, "cost": 0.060, "params": "70B", "family": "Llama", "complexity_factor": 0.99},
    "qwen2:72b": {"base_quality": 0.93, "speed": 11.0, "cost": 0.055, "params": "72B", "family": "Qwen", "complexity_factor": 0.98},
    "deepseek-coder:67b": {"base_quality": 0.92, "speed": 11.5, "cost": 0.058, "params": "67B", "family": "DeepSeek", "complexity_factor": 0.98},
    "mixtral:8x22b": {"base_quality": 0.93, "speed": 11.8, "cost": 0.062, "params": "141B", "family": "Mixtral", "complexity_factor": 0.99},
}

# Task complexity types
TASK_TYPES = {
    "simple": {
        "name": "Simple Extraction",
        "description": "Extract basic product info (name, price) from clean text",
        "base_difficulty": 0.0,  # No penalty
        "frequency": 0.30,
    },
    "medium": {
        "name": "Standard Extraction",
        "description": "Extract multiple fields with some ambiguity",
        "base_difficulty": 0.05,  # Small penalty
        "frequency": 0.40,
    },
    "complex": {
        "name": "Complex Reasoning",
        "description": "Extract info from messy text, resolve ambiguities, infer missing data",
        "base_difficulty": 0.12,  # Medium penalty
        "frequency": 0.20,
    },
    "edge_case": {
        "name": "Edge Cases",
        "description": "Unusual formats, multiple products, contradictory info",
        "base_difficulty": 0.20,  # Large penalty
        "frequency": 0.10,
    },
}

def get_random_task_type():
    """Select task type based on frequency distribution."""
    rand = random.random()
    cumulative = 0
    for task_type, config in TASK_TYPES.items():
        cumulative += config["frequency"]
        if rand <= cumulative:
            return task_type
    return "medium"

def simulate_executions_complex(model, num_samples=50):
    """
    Simulate N executions with realistic task complexity.

    - Different tasks have different difficulty
    - Smaller models struggle more with complex tasks
    - Larger models handle all tasks well but are slower/expensive
    """
    config = MODELS[model]
    executions = []

    # Track performance by task type for analysis
    by_task_type = defaultdict(list)

    for i in range(num_samples):
        # Select task type
        task_type = get_random_task_type()
        task_config = TASK_TYPES[task_type]

        # Base quality from model
        base_quality = config["base_quality"]

        # Apply complexity penalty based on model's complexity handling
        # Smaller models get hit harder by complex tasks
        complexity_penalty = task_config["base_difficulty"] * (1.0 - config["complexity_factor"])

        # Calculate quality for this task
        quality = base_quality - complexity_penalty

        # Add realistic variation
        quality += random.uniform(-0.02, 0.02)
        quality = max(0, min(1, quality))

        # Duration varies slightly by task complexity
        duration = config["speed"] + random.uniform(-0.5, 0.5)
        if task_type in ["complex", "edge_case"]:
            duration *= 1.1  # Complex tasks take 10% longer

        # Cost is mostly fixed but varies slightly
        cost = config["cost"] + random.uniform(-0.002, 0.002)

        execution = {
            "quality": quality,
            "duration": max(0.1, duration),
            "cost": max(0, cost),
            "task_type": task_type,
        }

        executions.append(execution)
        by_task_type[task_type].append(execution)

    return executions, by_task_type

def analyze_performance(executions):
    """Analyze execution data and return metrics."""
    avg_quality = sum(e["quality"] for e in executions) / len(executions)
    avg_duration = sum(e["duration"] for e in executions) / len(executions)
    avg_cost = sum(e["cost"] for e in executions) / len(executions)

    return {
        "avg_quality": avg_quality,
        "avg_duration": avg_duration,
        "avg_cost": avg_cost,
        "min_quality": min(e["quality"] for e in executions),
        "max_quality": max(e["quality"] for e in executions),
    }

def analyze_by_task_type(by_task_type):
    """Analyze performance broken down by task type."""
    analysis = {}
    for task_type, executions in by_task_type.items():
        if executions:
            analysis[task_type] = {
                "count": len(executions),
                "avg_quality": sum(e["quality"] for e in executions) / len(executions),
                "avg_duration": sum(e["duration"] for e in executions) / len(executions),
            }
    return analysis

def select_models_to_test(current_model, cycle_num, all_models, tested_models):
    """Smart model selection based on cycle."""
    available = [m for m in all_models if m not in tested_models]

    if not available:
        available = list(all_models.keys())

    # Cycle 1-2: Test diverse sizes
    if cycle_num <= 2:
        categories = {
            "tiny": [m for m in available if "0.5b" in m.lower() or "1.5b" in m.lower() or "2b" in m.lower() or "3b" in m.lower()],
            "small": [m for m in available if "6.7b" in m.lower() or "7b" in m.lower() or "8b" in m.lower()],
            "medium": [m for m in available if "13b" in m.lower() or "14b" in m.lower() or "15b" in m.lower()],
            "large": [m for m in available if "33b" in m.lower() or "34b" in m.lower()],
            "xlarge": [m for m in available if "47b" in m.lower() or "67b" in m.lower() or "70b" in m.lower() or "72b" in m.lower() or "141b" in m.lower()],
        }
        selected = []
        for cat, models in categories.items():
            if models:
                selected.append(random.choice(models))
        return selected[:6]

    # Cycle 3+: Focus on high quality models
    else:
        high_quality = [m for m in available if MODELS[m]["base_quality"] >= 0.85]
        if high_quality:
            return random.sample(high_quality, min(5, len(high_quality)))
        else:
            return random.sample(available, min(5, len(available)))

# ============================================================================
# MAIN SIMULATION
# ============================================================================

print("\n" + "=" * 110)
print(f"{Colors.BOLD}M5 COMPLEX MODEL COMPARISON - 22 Models with Realistic Task Complexity{Colors.RESET}")
print("=" * 110)

print(f"\n{Colors.BOLD}Enhanced Input Simulation:{Colors.RESET}")
print(f"  • Task Types: {len(TASK_TYPES)} (simple, medium, complex, edge cases)")
print("  • Distribution: 30% simple, 40% medium, 20% complex, 10% edge cases")
print("  • Complexity Impact: Smaller models struggle more on complex tasks")
print("  • Realistic: Large models handle all tasks well but are slower/expensive")

print(f"\n{Colors.BOLD}Task Type Details:{Colors.RESET}")
for task_type, config in TASK_TYPES.items():
    print(f"  • {config['name']:25s} ({config['frequency']*100:2.0f}%): {config['description']}")

print(f"\n{Colors.BOLD}Model Catalog:{Colors.RESET}")
print(f"  Total models: {len(MODELS)}")

by_family = defaultdict(list)
for model, config in MODELS.items():
    by_family[config["family"]].append(model)

print(f"  Families: {len(by_family)}")
for family, models in sorted(by_family.items()):
    print(f"    • {family}: {len(models)} models")

# Track all tested models
tested_models = set()
all_results = {}
all_task_breakdowns = {}

current_model = "llama3.1:8b"
tested_models.add(current_model)

print("\n" + "=" * 110)
print(f"{Colors.BOLD}TESTING CYCLES{Colors.RESET}")
print("=" * 110)

for cycle in range(1, 6):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'─' * 110}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}CYCLE {cycle}: Baseline = {current_model} ({MODELS[current_model]['params']}){Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'─' * 110}{Colors.RESET}")

    # Run baseline with complex tasks
    baseline_execs, baseline_by_type = simulate_executions_complex(current_model, 50)
    baseline_metrics = analyze_performance(baseline_execs)
    baseline_task_analysis = analyze_by_task_type(baseline_by_type)

    all_results[current_model] = {
        **baseline_metrics,
        "params": MODELS[current_model]["params"],
        "family": MODELS[current_model]["family"],
        "tested_in_cycle": cycle,
        "role": "baseline",
    }
    all_task_breakdowns[current_model] = baseline_task_analysis

    print(f"\n  Baseline: {current_model}")
    print(f"    Overall: Quality {baseline_metrics['avg_quality']:.3f} | "
          f"Duration {baseline_metrics['avg_duration']:.2f}s | Cost ${baseline_metrics['avg_cost']:.4f}")

    print("    By Task Type:")
    for task_type in ["simple", "medium", "complex", "edge_case"]:
        if task_type in baseline_task_analysis:
            analysis = baseline_task_analysis[task_type]
            print(f"      • {TASK_TYPES[task_type]['name']:25s}: Q={analysis['avg_quality']:.3f} ({analysis['count']} tasks)")

    # Select variants
    variants = select_models_to_test(current_model, cycle, MODELS, tested_models)

    print(f"\n  Testing {len(variants)} variant(s):")
    for v in variants:
        tested_models.add(v)
        params = MODELS[v]["params"]
        expected_q = MODELS[v]["base_quality"]
        complexity_f = MODELS[v]["complexity_factor"]
        print(f"    • {v:<30s} ({params:>5s}, base Q: {expected_q:.3f}, complexity handling: {complexity_f:.2f})")

    # Run experiments
    experiment_results = {current_model: baseline_metrics}
    experiment_task_breakdowns = {current_model: baseline_task_analysis}

    for variant in variants:
        variant_execs, variant_by_type = simulate_executions_complex(variant, 50)
        variant_metrics = analyze_performance(variant_execs)
        variant_task_analysis = analyze_by_task_type(variant_by_type)

        experiment_results[variant] = variant_metrics
        experiment_task_breakdowns[variant] = variant_task_analysis

        all_results[variant] = {
            **variant_metrics,
            "params": MODELS[variant]["params"],
            "family": MODELS[variant]["family"],
            "tested_in_cycle": cycle,
            "role": "variant",
        }
        all_task_breakdowns[variant] = variant_task_analysis

    # Display results
    print(f"\n  {Colors.BOLD}Results (sorted by quality):{Colors.RESET}")
    print(f"  {'Model':<30s} {'Size':>6s} {'Avg Quality':>12s} {'Simple':>8s} {'Complex':>8s} {'Edge':>8s}")
    print(f"  {'-' * 90}")

    sorted_results = sorted(experiment_results.items(),
                           key=lambda x: x[1]["avg_quality"],
                           reverse=True)

    for model, metrics in sorted_results:
        params = MODELS[model]["params"]
        quality_color = Colors.GREEN if metrics["avg_quality"] >= 0.90 else Colors.YELLOW

        # Get task type qualities
        task_breakdown = experiment_task_breakdowns[model]
        simple_q = task_breakdown.get("simple", {}).get("avg_quality", 0)
        complex_q = task_breakdown.get("complex", {}).get("avg_quality", 0)
        edge_q = task_breakdown.get("edge_case", {}).get("avg_quality", 0)

        marker = " (baseline)" if model == current_model else ""
        if sorted_results[0][0] == model and model != current_model:
            marker = f" {Colors.GREEN}← WINNER{Colors.RESET}"

        print(f"  {model:<30s} {params:>6s} {quality_color}{metrics['avg_quality']:>12.3f}{Colors.RESET} "
              f"{simple_q:>8.3f} {complex_q:>8.3f} {edge_q:>8.3f}{marker}")

    # Select winner (pure quality)
    winner = sorted_results[0][0]
    winner_quality = sorted_results[0][1]["avg_quality"]

    if winner != current_model:
        improvement = (winner_quality - baseline_metrics["avg_quality"]) / baseline_metrics["avg_quality"] * 100
        print(f"\n  {Colors.GREEN}🏆 Deploying {winner} (+{improvement:.1f}% quality){Colors.RESET}")
        current_model = winner
    else:
        print(f"\n  {Colors.YELLOW}⚠  Baseline remains best{Colors.RESET}")

# ============================================================================
# COMPREHENSIVE ANALYSIS
# ============================================================================

print("\n" + "=" * 110)
print(f"{Colors.BOLD}COMPREHENSIVE MODEL ANALYSIS{Colors.RESET}")
print("=" * 110)

print(f"\n{Colors.BOLD}All Tested Models ({len(all_results)}):{Colors.RESET}\n")

sorted_all = sorted(all_results.items(), key=lambda x: x[1]["avg_quality"], reverse=True)

print(f"{'Rank':<5s} {'Model':<30s} {'Size':>6s} {'Family':<12s} {'Quality':>10s} {'Simple':>8s} {'Complex':>8s} {'Gap':>8s}")
print("-" * 110)

for rank, (model, data) in enumerate(sorted_all, 1):
    quality_color = Colors.GREEN if data["avg_quality"] >= 0.90 else (Colors.YELLOW if data["avg_quality"] >= 0.80 else Colors.RED)

    medal = ""
    if rank == 1:
        medal = "🥇"
    elif rank == 2:
        medal = "🥈"
    elif rank == 3:
        medal = "🥉"

    # Get task type breakdown
    task_breakdown = all_task_breakdowns.get(model, {})
    simple_q = task_breakdown.get("simple", {}).get("avg_quality", 0)
    complex_q = task_breakdown.get("complex", {}).get("avg_quality", 0)
    gap = simple_q - complex_q if (simple_q and complex_q) else 0

    print(f"{rank:<3d} {medal:<2s} {model:<30s} {data['params']:>6s} {data['family']:<12s} "
          f"{quality_color}{data['avg_quality']:>10.3f}{Colors.RESET} "
          f"{simple_q:>8.3f} {complex_q:>8.3f} {gap:>8.3f}")

print(f"\n{Colors.BOLD}Key Insight - Complexity Handling:{Colors.RESET}")
print("  Gap = Quality on Simple tasks - Quality on Complex tasks")
print("  Smaller gap = Better at handling complex tasks")

# Find models with best complexity handling
complexity_gaps = [(m, all_task_breakdowns.get(m, {}).get("simple", {}).get("avg_quality", 0) -
                        all_task_breakdowns.get(m, {}).get("complex", {}).get("avg_quality", 0))
                   for m in all_results.keys()
                   if all_task_breakdowns.get(m, {}).get("simple") and all_task_breakdowns.get(m, {}).get("complex")]

best_complexity_handling = sorted(complexity_gaps, key=lambda x: x[1])[:3]

print(f"\n{Colors.BOLD}Best Complexity Handling (smallest gap):{Colors.RESET}")
for model, gap in best_complexity_handling:
    params = all_results[model]["params"]
    print(f"  • {model:<30s} ({params:>5s}) - Gap: {gap:.3f}")

# Top performers
print(f"\n{Colors.BOLD}Top 5 Overall:{Colors.RESET}")
for rank, (model, data) in enumerate(sorted_all[:5], 1):
    print(f"  {rank}. {model:<30s} ({data['params']:>5s}) - Quality: {data['avg_quality']:.3f}")

print("\n" + "=" * 110)
print(f"{Colors.GREEN}{Colors.BOLD}✓ COMPREHENSIVE MODEL COMPARISON COMPLETE - {len(all_results)} MODELS TESTED{Colors.RESET}")
print("=" * 110 + "\n")
