#!/usr/bin/env python3
"""
M5 Extended Model Comparison - Test MANY models

Comprehensive testing of different model sizes and families.
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

# COMPREHENSIVE model catalog - 20+ models
MODELS = {
    # Tiny models (1-3B)
    "qwen2:1.5b": {"quality": 0.68, "speed": 3.5, "cost": 0.012, "params": "1.5B", "family": "Qwen"},
    "gemma2:2b": {"quality": 0.88, "speed": 4.5, "cost": 0.015, "params": "2B", "family": "Gemma"},
    "llama3.2:3b": {"quality": 0.73, "speed": 4.2, "cost": 0.016, "params": "3B", "family": "Llama"},
    "phi3:mini": {"quality": 0.75, "speed": 4.0, "cost": 0.018, "params": "3.8B", "family": "Phi"},

    # Small-Medium models (6-8B)
    "deepseek-coder:6.7b": {"quality": 0.80, "speed": 5.8, "cost": 0.022, "params": "6.7B", "family": "DeepSeek"},
    "gemma:7b": {"quality": 0.83, "speed": 5.2, "cost": 0.021, "params": "7B", "family": "Gemma"},
    "mistral:7b": {"quality": 0.82, "speed": 6.0, "cost": 0.025, "params": "7B", "family": "Mistral"},
    "qwen2:7b": {"quality": 0.84, "speed": 5.5, "cost": 0.023, "params": "7B", "family": "Qwen"},
    "llama3.1:8b": {"quality": 0.70, "speed": 5.0, "cost": 0.020, "params": "8B", "family": "Llama"},

    # Medium models (13-14B)
    "codellama:13b": {"quality": 0.86, "speed": 7.5, "cost": 0.032, "params": "13B", "family": "CodeLlama"},
    "phi3:medium": {"quality": 0.85, "speed": 7.0, "cost": 0.030, "params": "14B", "family": "Phi"},
    "qwen2:14b": {"quality": 0.87, "speed": 7.2, "cost": 0.031, "params": "14B", "family": "Qwen"},
    "wizardcoder:13b": {"quality": 0.84, "speed": 7.8, "cost": 0.033, "params": "13B", "family": "WizardCoder"},

    # Large models (30-34B)
    "codellama:34b": {"quality": 0.89, "speed": 9.5, "cost": 0.042, "params": "34B", "family": "CodeLlama"},
    "deepseek-coder:33b": {"quality": 0.90, "speed": 9.8, "cost": 0.043, "params": "33B", "family": "DeepSeek"},

    # Very Large models (47-70B+)
    "mixtral:8x7b": {"quality": 0.91, "speed": 10.0, "cost": 0.045, "params": "47B", "family": "Mixtral"},
    "llama3.1:70b": {"quality": 0.94, "speed": 12.0, "cost": 0.060, "params": "70B", "family": "Llama"},
    "qwen2:72b": {"quality": 0.93, "speed": 11.0, "cost": 0.055, "params": "72B", "family": "Qwen"},
    "deepseek-coder:67b": {"quality": 0.92, "speed": 11.5, "cost": 0.058, "params": "67B", "family": "DeepSeek"},
}

def simulate_executions(model, num_samples=50):
    """Simulate N executions of a model."""
    config = MODELS[model]
    executions = []

    for i in range(num_samples):
        # Add realistic variation
        quality = config["quality"] + random.uniform(-0.02, 0.02)
        duration = config["speed"] + random.uniform(-0.5, 0.5)
        cost = config["cost"] + random.uniform(-0.002, 0.002)

        executions.append({
            "quality": max(0, min(1, quality)),
            "duration": max(0.1, duration),
            "cost": max(0, cost),
        })

    return executions

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

def select_models_to_test(current_model, cycle_num, all_models, tested_models):
    """Smart model selection based on cycle."""
    available = [m for m in all_models if m not in tested_models]

    if not available:
        # If all tested, pick top performers we haven't retested recently
        available = list(all_models.keys())

    # Cycle 1-2: Test diverse sizes
    if cycle_num <= 2:
        # Pick one from each size category
        categories = {
            "tiny": [m for m in available if "1.5b" in m or "2b" in m or "3b" in m],
            "small": [m for m in available if "6.7b" in m or "7b" in m or "8b" in m],
            "medium": [m for m in available if "13b" in m or "14b" in m],
            "large": [m for m in available if "33b" in m or "34b" in m or "47b" in m],
            "xlarge": [m for m in available if "67b" in m or "70b" in m or "72b" in m],
        }
        selected = []
        for cat, models in categories.items():
            if models:
                selected.append(random.choice(models))
        return selected[:6]  # Max 6 variants

    # Cycle 3+: Focus on high quality models
    else:
        high_quality = [m for m in available if MODELS[m]["quality"] >= 0.85]
        if high_quality:
            return random.sample(high_quality, min(5, len(high_quality)))
        else:
            return random.sample(available, min(5, len(available)))

# ============================================================================
# MAIN SIMULATION
# ============================================================================

print("\n" + "=" * 100)
print(f"{Colors.BOLD}M5 COMPREHENSIVE MODEL COMPARISON{Colors.RESET}")
print("=" * 100)

print(f"\n{Colors.BOLD}Model Catalog:{Colors.RESET}")
print(f"  Total models: {len(MODELS)}")

# Group by family
by_family = defaultdict(list)
for model, config in MODELS.items():
    by_family[config["family"]].append(model)

print(f"  Families: {len(by_family)}")
for family, models in sorted(by_family.items()):
    print(f"    • {family}: {len(models)} models")

print(f"\n{Colors.BOLD}Strategy:{Colors.RESET}")
print("  • Pure quality optimization (100% quality, 0% cost, 0% speed)")
print("  • Test 5-6 variants per cycle")
print("  • Run 5 cycles to test ~30 total experiments")

# Track all tested models
tested_models = set()
all_results = {}

current_model = "llama3.1:8b"
tested_models.add(current_model)

print("\n" + "=" * 100)
print(f"{Colors.BOLD}TESTING CYCLES{Colors.RESET}")
print("=" * 100)

for cycle in range(1, 6):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}CYCLE {cycle}: Baseline = {current_model} ({MODELS[current_model]['params']}){Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")

    # Run baseline
    baseline_execs = simulate_executions(current_model, 50)
    baseline_metrics = analyze_performance(baseline_execs)

    all_results[current_model] = {
        **baseline_metrics,
        "params": MODELS[current_model]["params"],
        "family": MODELS[current_model]["family"],
        "tested_in_cycle": cycle,
        "role": "baseline",
    }

    print(f"\n  Baseline: {current_model}")
    print(f"    Quality: {baseline_metrics['avg_quality']:.3f} | "
          f"Duration: {baseline_metrics['avg_duration']:.2f}s | "
          f"Cost: ${baseline_metrics['avg_cost']:.4f}")

    # Select variants to test
    variants = select_models_to_test(current_model, cycle, MODELS, tested_models)

    print(f"\n  Testing {len(variants)} variant(s):")
    for v in variants:
        tested_models.add(v)
        params = MODELS[v]["params"]
        expected_q = MODELS[v]["quality"]
        print(f"    • {v:<30s} ({params:>5s}, expected Q: {expected_q:.3f})")

    # Run experiments
    experiment_results = {current_model: baseline_metrics}

    for variant in variants:
        variant_execs = simulate_executions(variant, 50)
        variant_metrics = analyze_performance(variant_execs)
        experiment_results[variant] = variant_metrics

        all_results[variant] = {
            **variant_metrics,
            "params": MODELS[variant]["params"],
            "family": MODELS[variant]["family"],
            "tested_in_cycle": cycle,
            "role": "variant",
        }

    # Display results
    print(f"\n  {Colors.BOLD}Results (sorted by quality):{Colors.RESET}")
    print(f"  {'Model':<30s} {'Size':>6s} {'Quality':>10s} {'Duration':>10s} {'Cost':>10s}")
    print(f"  {'-' * 80}")

    sorted_results = sorted(experiment_results.items(),
                           key=lambda x: x[1]["avg_quality"],
                           reverse=True)

    for model, metrics in sorted_results:
        params = MODELS[model]["params"]
        quality_color = Colors.GREEN if metrics["avg_quality"] >= 0.90 else Colors.YELLOW

        marker = " (baseline)" if model == current_model else ""
        if sorted_results[0][0] == model and model != current_model:
            marker = f" {Colors.GREEN}← WINNER{Colors.RESET}"

        print(f"  {model:<30s} {params:>6s} {quality_color}{metrics['avg_quality']:>10.3f}{Colors.RESET} "
              f"{metrics['avg_duration']:>8.2f}s  ${metrics['avg_cost']:>8.4f}{marker}")

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

print("\n" + "=" * 100)
print(f"{Colors.BOLD}COMPREHENSIVE MODEL ANALYSIS{Colors.RESET}")
print("=" * 100)

print(f"\n{Colors.BOLD}All Tested Models ({len(all_results)}):{Colors.RESET}\n")

# Sort by quality
sorted_all = sorted(all_results.items(), key=lambda x: x[1]["avg_quality"], reverse=True)

print(f"{'Rank':<5s} {'Model':<30s} {'Size':>6s} {'Family':<12s} {'Quality':>10s} {'Speed':>10s} {'Cost':>10s} {'Cycle':>6s}")
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

    print(f"{rank:<3d} {medal:<2s} {model:<30s} {data['params']:>6s} {data['family']:<12s} "
          f"{quality_color}{data['avg_quality']:>10.3f}{Colors.RESET} "
          f"{data['avg_duration']:>8.2f}s  ${data['avg_cost']:>8.4f}  {data['tested_in_cycle']:>6d}")

# Analysis by family
print(f"\n{Colors.BOLD}Performance by Family:{Colors.RESET}\n")

family_stats = defaultdict(list)
for model, data in all_results.items():
    family_stats[data["family"]].append(data)

print(f"{'Family':<15s} {'Count':>6s} {'Avg Quality':>12s} {'Best Model':>30s}")
print("-" * 80)

for family in sorted(family_stats.keys()):
    models = family_stats[family]
    avg_quality = sum(m["avg_quality"] for m in models) / len(models)
    best_model = max(models, key=lambda x: x["avg_quality"])
    best_model_name = [name for name, data in all_results.items() if data == best_model][0]

    print(f"{family:<15s} {len(models):>6d} {avg_quality:>12.3f}     {best_model_name}")

# Analysis by size
print(f"\n{Colors.BOLD}Performance by Model Size:{Colors.RESET}\n")

size_categories = {
    "Tiny (1-4B)": [m for m, d in all_results.items() if "1.5B" in d["params"] or "2B" in d["params"] or "3B" in d["params"] or "3.8B" in d["params"]],
    "Small (6-8B)": [m for m, d in all_results.items() if "6.7B" in d["params"] or "7B" in d["params"] or "8B" in d["params"]],
    "Medium (13-14B)": [m for m, d in all_results.items() if "13B" in d["params"] or "14B" in d["params"]],
    "Large (30-34B)": [m for m, d in all_results.items() if "33B" in d["params"] or "34B" in d["params"]],
    "X-Large (47B+)": [m for m, d in all_results.items() if "47B" in d["params"] or "67B" in d["params"] or "70B" in d["params"] or "72B" in d["params"]],
}

print(f"{'Category':<20s} {'Count':>6s} {'Avg Quality':>12s} {'Avg Cost':>10s} {'Avg Speed':>10s}")
print("-" * 75)

for category, models in size_categories.items():
    if models:
        avg_quality = sum(all_results[m]["avg_quality"] for m in models) / len(models)
        avg_cost = sum(all_results[m]["avg_cost"] for m in models) / len(models)
        avg_speed = sum(all_results[m]["avg_duration"] for m in models) / len(models)

        print(f"{category:<20s} {len(models):>6d} {avg_quality:>12.3f}  ${avg_cost:>8.4f}  {avg_speed:>8.2f}s")

# Key insights
print(f"\n{Colors.BOLD}Key Insights:{Colors.RESET}\n")

top3 = sorted_all[:3]
print(f"  🥇 Best Quality: {top3[0][0]} ({top3[0][1]['params']}) - {top3[0][1]['avg_quality']:.3f}")
print(f"  🥈 Second Best: {top3[1][0]} ({top3[1][1]['params']}) - {top3[1][1]['avg_quality']:.3f}")
print(f"  🥉 Third Best: {top3[2][0]} ({top3[2][1]['params']}) - {top3[2][1]['avg_quality']:.3f}")

# Best value (quality per dollar)
value_models = [(m, d["avg_quality"] / d["avg_cost"]) for m, d in all_results.items()]
best_value = max(value_models, key=lambda x: x[1])
print(f"\n  💰 Best Value: {best_value[0]} ({all_results[best_value[0]]['params']}) - "
      f"{all_results[best_value[0]]['avg_quality']:.3f} quality at ${all_results[best_value[0]]['avg_cost']:.4f}")

# Fastest high-quality (quality >= 0.85, fastest speed)
fast_quality = [(m, d) for m, d in all_results.items() if d["avg_quality"] >= 0.85]
if fast_quality:
    fastest_quality = min(fast_quality, key=lambda x: x[1]["avg_duration"])
    print(f"  ⚡ Fastest High-Quality: {fastest_quality[0]} ({fastest_quality[1]['params']}) - "
          f"{fastest_quality[1]['avg_quality']:.3f} quality in {fastest_quality[1]['avg_duration']:.2f}s")

# Correlation analysis
qualities = [d["avg_quality"] for d in all_results.values()]
sizes = [float(d["params"].replace("B", "")) for d in all_results.values()]

print(f"\n  📊 Tested {len(all_results)} different models across {len(by_family)} families")
print(f"  📈 Quality range: {min(qualities):.3f} - {max(qualities):.3f}")
print(f"  📏 Size range: {min(sizes):.1f}B - {max(sizes):.1f}B parameters")

print("\n" + "=" * 100)
print(f"{Colors.GREEN}{Colors.BOLD}✓ COMPREHENSIVE MODEL COMPARISON COMPLETE{Colors.RESET}")
print("=" * 100 + "\n")
