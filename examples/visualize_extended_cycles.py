#!/usr/bin/env python3
"""
M5 Extended Self-Improvement Cycles

Tests more variants including bigger models to find optimal configuration.
Runs multiple cycles to see continuous improvement.
"""

import json
import random
from datetime import datetime, timedelta

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

# Expanded model catalog with bigger models
MODELS = {
    # Small models
    "phi3:mini": {"quality": 0.75, "speed": 4.0, "cost": 0.018, "params": "3.8B"},
    "llama3.2:3b": {"quality": 0.73, "speed": 4.2, "cost": 0.016, "params": "3B"},
    "gemma2:2b": {"quality": 0.88, "speed": 4.5, "cost": 0.015, "params": "2B"},

    # Medium models
    "llama3.1:8b": {"quality": 0.70, "speed": 5.0, "cost": 0.020, "params": "8B"},
    "mistral:7b": {"quality": 0.82, "speed": 6.0, "cost": 0.025, "params": "7B"},
    "qwen2:7b": {"quality": 0.84, "speed": 5.5, "cost": 0.023, "params": "7B"},

    # Large models
    "llama3.1:70b": {"quality": 0.94, "speed": 12.0, "cost": 0.060, "params": "70B"},
    "mixtral:8x7b": {"quality": 0.91, "speed": 10.0, "cost": 0.045, "params": "47B"},
    "qwen2:72b": {"quality": 0.93, "speed": 11.0, "cost": 0.055, "params": "72B"},

    # Specialized models
    "deepseek-coder:6.7b": {"quality": 0.80, "speed": 5.8, "cost": 0.022, "params": "6.7B"},
    "codellama:13b": {"quality": 0.86, "speed": 7.5, "cost": 0.032, "params": "13B"},
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
        "total_duration": sum(e["duration"] for e in executions),
        "total_cost": sum(e["cost"] for e in executions),
    }

def detect_problems(metrics, thresholds, aggressive=False):
    """Detect performance problems."""
    problems = []

    # Standard problems
    if metrics["avg_quality"] < thresholds["quality"]:
        gap = thresholds["quality"] - metrics["avg_quality"]
        problems.append({
            "type": "quality_low",
            "severity": "HIGH" if gap > 0.05 else "MEDIUM",
            "description": f"Quality {metrics['avg_quality']:.3f} below threshold {thresholds['quality']:.3f}",
            "gap": gap,
        })

    if metrics["avg_cost"] > thresholds["cost"]:
        problems.append({
            "type": "cost_high",
            "severity": "MEDIUM",
            "description": f"Cost ${metrics['avg_cost']:.4f} exceeds threshold ${thresholds['cost']:.4f}",
        })

    if metrics["avg_duration"] > thresholds["speed"]:
        problems.append({
            "type": "speed_low",
            "severity": "LOW",
            "description": f"Duration {metrics['avg_duration']:.2f}s exceeds threshold {thresholds['speed']:.2f}s",
        })

    # Aggressive mode: Even if thresholds met, look for improvement opportunities
    if aggressive and not problems:
        if metrics["avg_quality"] < 0.95:
            problems.append({
                "type": "quality_improvement",
                "severity": "LOW",
                "description": f"Quality {metrics['avg_quality']:.3f} could be improved further",
            })

    return problems

def propose_improvements(current_model, problems, cycle_num):
    """Propose model changes based on problems - more aggressive selection."""
    candidates = []

    if not problems:
        return []

    # Get current model size
    current_params = MODELS[current_model]["params"]

    for problem in problems:
        if problem["type"] in ["quality_low", "quality_improvement"]:
            # Quality problem - suggest higher quality models
            # Include bigger models for quality
            if cycle_num <= 2:
                # Early cycles: Try medium and large models
                candidates.extend([
                    "gemma2:2b", "mistral:7b", "qwen2:7b",
                    "codellama:13b", "mixtral:8x7b"
                ])
            else:
                # Later cycles: Try the biggest models
                candidates.extend([
                    "llama3.1:70b", "qwen2:72b", "mixtral:8x7b"
                ])

        elif problem["type"] == "cost_high":
            # Cost problem - suggest cheaper models
            candidates.extend([
                "phi3:mini", "gemma2:2b", "llama3.2:3b"
            ])

        elif problem["type"] == "speed_low":
            # Speed problem - suggest faster models
            candidates.extend([
                "phi3:mini", "gemma2:2b", "llama3.2:3b"
            ])

    # Remove current model and duplicates
    candidates = list(set(candidates))
    if current_model in candidates:
        candidates.remove(current_model)

    # Return top 4 candidates (more variants)
    return candidates[:4]

def run_experiment(control_model, variant_models):
    """Run A/B experiment with control + variants."""
    results = {}

    # Run control
    control_execs = simulate_executions(control_model, 50)
    results[control_model] = {
        "metrics": analyze_performance(control_execs),
        "role": "control",
        "params": MODELS[control_model]["params"],
    }

    # Run variants
    for variant in variant_models:
        variant_execs = simulate_executions(variant, 50)
        results[variant] = {
            "metrics": analyze_performance(variant_execs),
            "role": "variant",
            "params": MODELS[variant]["params"],
        }

    return results

def select_winner(experiment_results, prioritize_quality=True):
    """Select winner based on composite score."""
    scores = {}

    for model, data in experiment_results.items():
        m = data["metrics"]

        if prioritize_quality:
            # PURE quality optimization: 1.0×quality + 0.0×speed + 0.0×cost (ONLY quality matters)
            quality_score = m["avg_quality"]
            speed_score = 1.0 / m["avg_duration"] * 10
            cost_score = 1.0 / m["avg_cost"] * 0.02

            composite = (
                quality_score * 1.0 +
                speed_score * 0.0 +
                cost_score * 0.0
            )
        else:
            # Balanced: 0.5×quality + 0.3×speed + 0.2×cost
            quality_score = m["avg_quality"]
            speed_score = 1.0 / m["avg_duration"] * 10
            cost_score = 1.0 / m["avg_cost"] * 0.02

            composite = (
                quality_score * 0.5 +
                speed_score * 0.3 +
                cost_score * 0.2
            )

        scores[model] = {
            "composite": composite,
            "quality": quality_score,
            "metrics": m,
        }

    # Find winner
    winner = max(scores.items(), key=lambda x: x[1]["composite"])

    # Calculate improvement over control
    control = [m for m, d in experiment_results.items() if d["role"] == "control"][0]
    improvement = (
        (scores[winner[0]]["quality"] - scores[control]["quality"]) / scores[control]["quality"] * 100
    )

    return winner[0], improvement, scores

# ============================================================================
# MAIN SIMULATION
# ============================================================================

print("\n" + "=" * 100)
print(f"{Colors.BOLD}M5 EXTENDED SELF-IMPROVEMENT: TESTING BIGGER MODELS{Colors.RESET}")
print("=" * 100)

print(f"\n{Colors.BOLD}Simulation Configuration:{Colors.RESET}")
print("  • Starting model: llama3.1:8b")
print("  • Models available: 11 (from 2B to 72B parameters)")
print("  • Variants per cycle: Up to 4")
print("  • Max cycles: 6")
print(f"  • Strategy: {Colors.BOLD}PURE QUALITY OPTIMIZATION{Colors.RESET} - Cost and speed ignored")
print(f"  • Composite score: {Colors.BOLD}100% quality{Colors.RESET} (0% speed, 0% cost)")

# Thresholds - AGGRESSIVE quality target
thresholds = {
    "quality": 0.92,  # Very high quality target - force big models
    "cost": 0.070,    # Very relaxed cost (allow expensive models)
    "speed": 15.0,    # Very relaxed speed (allow slow models)
}

print(f"\n{Colors.BOLD}Performance Thresholds:{Colors.RESET}")
print(f"  • Quality: ≥ {thresholds['quality']:.2f} (HIGH priority)")
print(f"  • Cost: ≤ ${thresholds['cost']:.3f} (relaxed for bigger models)")
print(f"  • Speed: ≤ {thresholds['speed']:.1f}s (relaxed for bigger models)")

# Start simulation
current_model = "llama3.1:8b"
cycle_history = []
cumulative_time = 0
max_cycles = 6

print("\n" + "=" * 100)
print(f"{Colors.BOLD}IMPROVEMENT CYCLES{Colors.RESET}")
print("=" * 100)

for cycle in range(1, max_cycles + 1):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}CYCLE {cycle}: {current_model} ({MODELS[current_model]['params']} params){Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")

    # PHASE 1: DETECT
    print(f"\n{Colors.BOLD}Phase 1: DETECT{Colors.RESET}")
    print(f"  Running {current_model} for 50 executions...")

    baseline_execs = simulate_executions(current_model, 50)
    baseline_metrics = analyze_performance(baseline_execs)
    cumulative_time += baseline_metrics["total_duration"]

    print(f"  {Colors.GREEN}✓{Colors.RESET} Collected 50 records")
    print(f"  Quality: {baseline_metrics['avg_quality']:.3f} | "
          f"Duration: {baseline_metrics['avg_duration']:.2f}s | "
          f"Cost: ${baseline_metrics['avg_cost']:.4f}")

    # PHASE 2: ANALYZE
    print(f"\n{Colors.BOLD}Phase 2: ANALYZE{Colors.RESET}")

    # Use aggressive mode after cycle 2 to keep pushing for improvements
    aggressive = cycle >= 2
    problems = detect_problems(baseline_metrics, thresholds, aggressive=aggressive)

    if problems:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET}  Detected {len(problems)} issue(s):")
        for p in problems:
            severity_color = Colors.RED if p["severity"] == "HIGH" else Colors.YELLOW
            print(f"    • [{severity_color}{p['severity']}{Colors.RESET}] {p['type']}: {p['description']}")
    else:
        print(f"  {Colors.GREEN}✓{Colors.RESET} All thresholds met - Performance optimal")
        cycle_history.append({
            "cycle": cycle,
            "model": current_model,
            "params": MODELS[current_model]["params"],
            "metrics": baseline_metrics,
            "problems": [],
            "action": "no_change",
        })
        break

    # PHASE 3: STRATEGY
    print(f"\n{Colors.BOLD}Phase 3: STRATEGY{Colors.RESET}")

    candidates = propose_improvements(current_model, problems, cycle)
    print(f"  Proposed {len(candidates)} variant(s) to test:")
    for candidate in candidates:
        params = MODELS[candidate]["params"]
        quality = MODELS[candidate]["quality"]
        print(f"    • {candidate:<25s} ({params:>5s} params, expected quality: {quality:.3f})")

    # PHASE 4: EXPERIMENT
    print(f"\n{Colors.BOLD}Phase 4: EXPERIMENT{Colors.RESET}")
    print(f"  Running A/B test: {current_model} + {len(candidates)} variants")
    print(f"  Total samples: {(len(candidates) + 1) * 50}")

    experiment_results = run_experiment(current_model, candidates)

    experiment_time = sum(d["metrics"]["total_duration"] for d in experiment_results.values())
    cumulative_time += experiment_time

    print(f"  {Colors.GREEN}✓{Colors.RESET} Complete in {experiment_time/60:.1f} minutes")

    # Show results
    print(f"\n  {Colors.BOLD}Results:{Colors.RESET}")
    print(f"  {'Model':<25s} {'Size':>6s} {'Quality':>10s} {'Duration':>12s} {'Cost':>10s}")
    print(f"  {'-' * 75}")

    for model in sorted(experiment_results.keys(), key=lambda m: experiment_results[m]["metrics"]["avg_quality"], reverse=True):
        data = experiment_results[model]
        m = data["metrics"]
        params = data["params"]

        role_marker = " (control)" if data["role"] == "control" else ""
        quality_color = Colors.GREEN if m["avg_quality"] >= thresholds["quality"] else Colors.YELLOW

        print(f"  {model:<25s} {params:>6s} {quality_color}{m['avg_quality']:>10.3f}{Colors.RESET} "
              f"{m['avg_duration']:>10.2f}s  ${m['avg_cost']:>8.4f}{role_marker}")

    # PHASE 5: DEPLOY
    print(f"\n{Colors.BOLD}Phase 5: DEPLOY{Colors.RESET}")

    winner, improvement, scores = select_winner(experiment_results, prioritize_quality=True)

    if winner == current_model:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET}  Current model remains best - No deployment")
        action = "no_change"
    else:
        winner_quality = experiment_results[winner]["metrics"]["avg_quality"]
        winner_params = MODELS[winner]["params"]

        print(f"  {Colors.GREEN}🏆 Winner: {winner} ({winner_params} params){Colors.RESET}")
        print(f"  {Colors.GREEN}✓{Colors.RESET}  Quality improvement: {improvement:+.1f}%")
        print(f"  {Colors.GREEN}✓{Colors.RESET}  New quality: {winner_quality:.3f}")
        print(f"  {Colors.GREEN}✓{Colors.RESET}  Deploying as new baseline")

        action = "deployed"
        current_model = winner

    # Record cycle
    cycle_history.append({
        "cycle": cycle,
        "model": current_model,
        "params": MODELS[current_model]["params"],
        "metrics": baseline_metrics,
        "problems": problems,
        "winner": winner,
        "improvement": improvement if winner != current_model else 0,
        "action": action,
        "duration": baseline_metrics["total_duration"] + experiment_time,
    })

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 100)
print(f"{Colors.BOLD}IMPROVEMENT JOURNEY SUMMARY{Colors.RESET}")
print("=" * 100 + "\n")

# Timeline
print(f"{Colors.BOLD}Evolution Timeline:{Colors.RESET}\n")

for i, cycle_data in enumerate(cycle_history):
    model = cycle_data["model"]
    params = cycle_data["params"]
    metrics = cycle_data["metrics"]

    if i == 0:
        arrow = "START"
    else:
        prev_model = cycle_history[i-1]["model"]
        if model != prev_model:
            arrow = f"{Colors.GREEN}↓ UPGRADE{Colors.RESET}"
        else:
            arrow = f"{Colors.YELLOW}↓ NO CHANGE{Colors.RESET}"

    print(f"  {arrow}")
    print(f"  │")
    print(f"  ├─ {Colors.BOLD}Cycle {cycle_data['cycle']}: {model} ({params}){Colors.RESET}")
    print(f"  │  Q: {metrics['avg_quality']:.3f} | C: ${metrics['avg_cost']:.4f} | S: {metrics['avg_duration']:.2f}s")

    if cycle_data.get("improvement", 0) > 0:
        print(f"  │  {Colors.GREEN}Improvement: +{cycle_data['improvement']:.1f}%{Colors.RESET}")

    print(f"  │")

print(f"  {Colors.GREEN}✓ OPTIMIZATION COMPLETE{Colors.RESET}\n")

# Performance table
print(f"{Colors.BOLD}Performance Progression:{Colors.RESET}\n")
print(f"  {'Cycle':<6s} {'Model':<25s} {'Size':>6s} {'Quality':>10s} {'Cost':>10s} {'Speed':>10s}")
print(f"  {'-' * 80}")

for cycle_data in cycle_history:
    cycle = cycle_data["cycle"]
    model = cycle_data["model"]
    params = cycle_data["params"]
    m = cycle_data["metrics"]

    quality_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_quality"] >= thresholds["quality"] else Colors.RED + "✗" + Colors.RESET
    cost_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_cost"] <= thresholds["cost"] else Colors.YELLOW + "⚠" + Colors.RESET
    speed_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_duration"] <= thresholds["speed"] else Colors.YELLOW + "⚠" + Colors.RESET

    print(f"  {cycle:<6d} {model:<25s} {params:>6s} {quality_icon} {m['avg_quality']:>8.3f}  "
          f"{cost_icon} ${m['avg_cost']:>7.4f}  {speed_icon} {m['avg_duration']:>7.2f}s")

# Final analysis
initial = cycle_history[0]
final = cycle_history[-1]

print(f"\n{Colors.BOLD}Final Analysis:{Colors.RESET}\n")
print(f"  Journey: {initial['model']} ({initial['params']}) → {final['model']} ({final['params']})")

quality_delta = final['metrics']['avg_quality'] - initial['metrics']['avg_quality']
cost_delta = final['metrics']['avg_cost'] - initial['metrics']['avg_cost']
speed_delta = final['metrics']['avg_duration'] - initial['metrics']['avg_duration']

quality_pct = (quality_delta / initial['metrics']['avg_quality']) * 100
cost_pct = (cost_delta / initial['metrics']['avg_cost']) * 100
speed_pct = (speed_delta / initial['metrics']['avg_duration']) * 100

print(f"\n  Quality: {initial['metrics']['avg_quality']:.3f} → {final['metrics']['avg_quality']:.3f} "
      f"({Colors.GREEN if quality_delta > 0 else Colors.RED}{quality_pct:+.1f}%{Colors.RESET})")
print(f"  Cost: ${initial['metrics']['avg_cost']:.4f} → ${final['metrics']['avg_cost']:.4f} "
      f"({Colors.GREEN if cost_delta < 0 else Colors.RED}{cost_pct:+.1f}%{Colors.RESET})")
print(f"  Speed: {initial['metrics']['avg_duration']:.2f}s → {final['metrics']['avg_duration']:.2f}s "
      f"({Colors.GREEN if speed_delta < 0 else Colors.RED}{speed_pct:+.1f}%{Colors.RESET})")

total_time = sum(c.get("duration", 0) for c in cycle_history)
print(f"\n  Total optimization time: {total_time/60:.1f} minutes")
print(f"  Cycles executed: {len(cycle_history)}")

print(f"\n{Colors.BOLD}Key Insight:{Colors.RESET}")
if "70b" in final['model'] or "72b" in final['model']:
    print(f"  {Colors.GREEN}✓{Colors.RESET} Bigger model ({final['params']}) achieved best quality!")
    print(f"  {Colors.GREEN}✓{Colors.RESET} Trade-off: Higher cost/latency for superior performance")
elif "2b" in final['model'] or "3b" in final['model']:
    print(f"  {Colors.GREEN}✓{Colors.RESET} Small model ({final['params']}) provided best balance!")
    print(f"  {Colors.GREEN}✓{Colors.RESET} Efficient: Good quality with low cost/latency")
else:
    print(f"  {Colors.GREEN}✓{Colors.RESET} Medium model ({final['params']}) found optimal balance")

print("\n" + "=" * 100)
print(f"{Colors.GREEN}{Colors.BOLD}✓ M5 EXTENDED CYCLE COMPLETE - {final['model'].upper()} IS OPTIMAL{Colors.RESET}")
print("=" * 100 + "\n")
