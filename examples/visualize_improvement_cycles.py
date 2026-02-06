#!/usr/bin/env python3
"""
M5 Self-Improvement Cycle Visualization

Shows iterative improvement cycles:
  Cycle 1: Baseline → Detect Problem → Experiment → Deploy Winner
  Cycle 2: New Baseline → Detect Problem → Experiment → Deploy Winner
  ...and so on
"""

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
    DIM = '\033[2m'

# Model configurations
MODELS = {
    "llama3.1:8b": {"quality": 0.70, "speed": 5.0, "cost": 0.020},
    "gemma2:2b": {"quality": 0.88, "speed": 4.5, "cost": 0.015},
    "phi3:mini": {"quality": 0.75, "speed": 4.0, "cost": 0.018},
    "mistral:7b": {"quality": 0.82, "speed": 6.0, "cost": 0.025},
    "llama3.2:3b": {"quality": 0.73, "speed": 4.2, "cost": 0.016},
}

def simulate_executions(model, num_samples=50):
    """Simulate N executions of a model."""
    config = MODELS[model]
    executions = []

    for i in range(num_samples):
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

def detect_problems(metrics, thresholds):
    """Detect performance problems."""
    problems = []

    if metrics["avg_quality"] < thresholds["quality"]:
        problems.append({
            "type": "quality_low",
            "severity": "HIGH",
            "description": f"Quality {metrics['avg_quality']:.3f} below threshold {thresholds['quality']:.3f}",
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
            "severity": "MEDIUM",
            "description": f"Duration {metrics['avg_duration']:.2f}s exceeds threshold {thresholds['speed']:.2f}s",
        })

    return problems

def propose_improvements(current_model, problems):
    """Propose model changes based on problems."""
    if not problems:
        return []

    # Find alternative models
    candidates = []

    for problem in problems:
        if problem["type"] == "quality_low":
            # Suggest higher quality models
            candidates.extend(["gemma2:2b", "mistral:7b"])
        elif problem["type"] == "cost_high":
            # Suggest cheaper models
            candidates.extend(["phi3:mini", "gemma2:2b", "llama3.2:3b"])
        elif problem["type"] == "speed_low":
            # Suggest faster models
            candidates.extend(["phi3:mini", "gemma2:2b"])

    # Remove current model and duplicates
    candidates = list(set(candidates))
    if current_model in candidates:
        candidates.remove(current_model)

    return candidates[:2]  # Return top 2 candidates

def run_experiment(control_model, variant_models):
    """Run A/B experiment with control + variants."""
    results = {}

    # Run control
    control_execs = simulate_executions(control_model, 50)
    results[control_model] = {
        "metrics": analyze_performance(control_execs),
        "role": "control",
    }

    # Run variants
    for variant in variant_models:
        variant_execs = simulate_executions(variant, 50)
        results[variant] = {
            "metrics": analyze_performance(variant_execs),
            "role": "variant",
        }

    return results

def select_winner(experiment_results):
    """Select winner based on composite score."""
    # Composite score: 0.6×quality + 0.25×(1/speed) + 0.15×(1/cost)
    scores = {}

    for model, data in experiment_results.items():
        m = data["metrics"]

        # Normalize (inverse for speed and cost - lower is better)
        quality_score = m["avg_quality"]
        speed_score = 1.0 / m["avg_duration"] * 10  # Scale to ~0-1 range
        cost_score = 1.0 / m["avg_cost"] * 0.02  # Scale to ~0-1 range

        composite = (
            quality_score * 0.6 +
            speed_score * 0.25 +
            cost_score * 0.15
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
print(f"{Colors.BOLD}M5 SELF-IMPROVEMENT CYCLE: ITERATIVE OPTIMIZATION{Colors.RESET}")
print("=" * 100)

print(f"\n{Colors.BOLD}Simulation Overview:{Colors.RESET}")
print("  • Shows multiple improvement cycles")
print("  • Each cycle: Run baseline → Analyze → Detect problems → Experiment → Deploy winner")
print("  • System learns and improves over time")

# Thresholds for problem detection
thresholds = {
    "quality": 0.85,  # Want quality ≥ 0.85
    "cost": 0.018,    # Want cost ≤ $0.018
    "speed": 4.5,     # Want duration ≤ 4.5s
}

print(f"\n{Colors.BOLD}Performance Thresholds:{Colors.RESET}")
print(f"  • Quality: ≥ {thresholds['quality']:.2f}")
print(f"  • Cost: ≤ ${thresholds['cost']:.3f}")
print(f"  • Speed: ≤ {thresholds['speed']:.1f}s")

# Start simulation
current_model = "llama3.1:8b"
cycle_history = []
base_time = datetime(2026, 2, 1, 10, 0, 0)
cumulative_time = 0

print("\n" + "=" * 100)
print(f"{Colors.BOLD}IMPROVEMENT CYCLES{Colors.RESET}")
print("=" * 100)

for cycle in range(1, 4):  # Run 3 cycles
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}CYCLE {cycle}: {current_model}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'─' * 100}{Colors.RESET}")

    cycle_start_time = base_time + timedelta(seconds=cumulative_time)

    # PHASE 1: DETECT - Run baseline and collect data
    print(f"\n{Colors.BOLD}Phase 1: DETECT{Colors.RESET} - Collecting baseline performance data")
    print(f"  Running {current_model} for 50 executions...")

    baseline_execs = simulate_executions(current_model, 50)
    baseline_metrics = analyze_performance(baseline_execs)
    cumulative_time += baseline_metrics["total_duration"]

    print(f"  {Colors.GREEN}✓{Colors.RESET} Collected 50 execution records")
    print(f"  Quality: {baseline_metrics['avg_quality']:.3f}")
    print(f"  Duration: {baseline_metrics['avg_duration']:.2f}s")
    print(f"  Cost: ${baseline_metrics['avg_cost']:.4f}")
    print(f"  Total time: {baseline_metrics['total_duration']:.1f}s ({baseline_metrics['total_duration']/60:.1f}m)")

    # PHASE 2: ANALYZE - Detect problems
    print(f"\n{Colors.BOLD}Phase 2: ANALYZE{Colors.RESET} - Detecting performance problems")

    problems = detect_problems(baseline_metrics, thresholds)

    if problems:
        print(f"  {Colors.RED}⚠{Colors.RESET}  Detected {len(problems)} problem(s):")
        for p in problems:
            severity_color = Colors.RED if p["severity"] == "HIGH" else Colors.YELLOW
            print(f"    • [{severity_color}{p['severity']}{Colors.RESET}] {p['type']}: {p['description']}")
    else:
        print(f"  {Colors.GREEN}✓{Colors.RESET} No problems detected - performance meets all thresholds")
        print(f"  {Colors.GREEN}✓{Colors.RESET} System is optimally configured")
        cycle_history.append({
            "cycle": cycle,
            "model": current_model,
            "metrics": baseline_metrics,
            "problems": [],
            "action": "no_change",
        })
        break  # Stop improvement cycle

    # PHASE 3: STRATEGY - Propose improvements
    print(f"\n{Colors.BOLD}Phase 3: STRATEGY{Colors.RESET} - Proposing improvements")

    candidates = propose_improvements(current_model, problems)
    print(f"  Proposed {len(candidates)} candidate model(s) to test:")
    for candidate in candidates:
        print(f"    • {candidate}")

    # PHASE 4: EXPERIMENT - Run A/B test
    print(f"\n{Colors.BOLD}Phase 4: EXPERIMENT{Colors.RESET} - Running A/B test")
    print(f"  Testing: {current_model} (control) + {len(candidates)} variant(s)")
    print("  Samples per variant: 50")

    experiment_results = run_experiment(current_model, candidates)

    # Calculate total experiment time
    experiment_time = sum(
        data["metrics"]["total_duration"]
        for data in experiment_results.values()
    )
    cumulative_time += experiment_time

    print(f"  {Colors.GREEN}✓{Colors.RESET} Experiment complete")
    print(f"  Total experiment time: {experiment_time:.1f}s ({experiment_time/60:.1f}m)")

    # Show experiment results
    print(f"\n  {Colors.BOLD}Experiment Results:{Colors.RESET}")
    print(f"  {'Model':<20s} {'Quality':>10s} {'Duration':>12s} {'Cost':>10s} {'Role':>10s}")
    print(f"  {'-' * 70}")

    for model, data in experiment_results.items():
        m = data["metrics"]
        role_str = f"({data['role']})" if data['role'] == 'control' else ""

        quality_color = Colors.GREEN if m["avg_quality"] >= thresholds["quality"] else Colors.YELLOW

        print(f"  {model:<20s} {quality_color}{m['avg_quality']:>10.3f}{Colors.RESET} "
              f"{m['avg_duration']:>10.2f}s  ${m['avg_cost']:>8.4f}  {role_str}")

    # PHASE 5: DEPLOY - Select and deploy winner
    print(f"\n{Colors.BOLD}Phase 5: DEPLOY{Colors.RESET} - Selecting winner")

    winner, improvement, scores = select_winner(experiment_results)

    if winner == current_model:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET}  Current model {current_model} remains best choice")
        print(f"  {Colors.YELLOW}⚠{Colors.RESET}  No deployment needed")
        action = "no_change"
    else:
        print(f"  {Colors.GREEN}🏆 Winner: {winner}{Colors.RESET}")
        print(f"  {Colors.GREEN}✓{Colors.RESET}  Quality improvement: {improvement:+.1f}%")
        print(f"  {Colors.GREEN}✓{Colors.RESET}  Deploying {winner} as new baseline")
        action = "deployed"
        current_model = winner  # Deploy winner

    # Record cycle
    cycle_history.append({
        "cycle": cycle,
        "model": current_model,
        "metrics": baseline_metrics,
        "problems": problems,
        "winner": winner,
        "improvement": improvement,
        "action": action,
        "duration": baseline_metrics["total_duration"] + experiment_time,
    })

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 100)
print(f"{Colors.BOLD}IMPROVEMENT HISTORY SUMMARY{Colors.RESET}")
print("=" * 100 + "\n")

# Timeline visualization
print(f"{Colors.BOLD}Timeline:{Colors.RESET}\n")

for i, cycle_data in enumerate(cycle_history):
    cycle_num = cycle_data["cycle"]
    model = cycle_data["model"]
    metrics = cycle_data["metrics"]
    action = cycle_data.get("action", "deployed")

    # Draw timeline
    if i == 0:
        arrow = "START"
    else:
        prev_model = cycle_history[i-1]["model"]
        if model != prev_model:
            arrow = f"{Colors.GREEN}↓ DEPLOYED{Colors.RESET}"
        else:
            arrow = f"{Colors.YELLOW}↓ NO CHANGE{Colors.RESET}"

    print(f"  {arrow}")
    print("  │")
    print(f"  ├─ {Colors.BOLD}Cycle {cycle_num}: {model}{Colors.RESET}")
    print(f"  │  Quality: {metrics['avg_quality']:.3f} | Cost: ${metrics['avg_cost']:.4f} | Speed: {metrics['avg_duration']:.2f}s")

    if cycle_data.get("problems"):
        print(f"  │  Problems: {len(cycle_data['problems'])} detected")
    else:
        print(f"  │  {Colors.GREEN}✓ Optimal - No problems{Colors.RESET}")

    print("  │")

print(f"  {Colors.GREEN}✓ OPTIMIZATION COMPLETE{Colors.RESET}\n")

# Performance progression
print(f"{Colors.BOLD}Performance Progression:{Colors.RESET}\n")

print(f"  {'Cycle':<8s} {'Model':<20s} {'Quality':>10s} {'Cost':>10s} {'Speed':>10s}")
print(f"  {'-' * 60}")

for cycle_data in cycle_history:
    cycle_num = cycle_data["cycle"]
    model = cycle_data["model"]
    m = cycle_data["metrics"]

    quality_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_quality"] >= thresholds["quality"] else Colors.RED + "✗" + Colors.RESET
    cost_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_cost"] <= thresholds["cost"] else Colors.RED + "✗" + Colors.RESET
    speed_icon = Colors.GREEN + "✓" + Colors.RESET if m["avg_duration"] <= thresholds["speed"] else Colors.RED + "✗" + Colors.RESET

    print(f"  {cycle_num:<8d} {model:<20s} {quality_icon} {m['avg_quality']:>8.3f}  {cost_icon} ${m['avg_cost']:>7.4f}  {speed_icon} {m['avg_duration']:>7.2f}s")

# Final result
final = cycle_history[-1]
initial = cycle_history[0]

print(f"\n{Colors.BOLD}Overall Improvement:{Colors.RESET}")
print(f"  Initial Model: {initial['model']}")
print(f"  Final Model: {final['model']}")

quality_improvement = (final['metrics']['avg_quality'] - initial['metrics']['avg_quality']) / initial['metrics']['avg_quality'] * 100
cost_improvement = (initial['metrics']['avg_cost'] - final['metrics']['avg_cost']) / initial['metrics']['avg_cost'] * 100
speed_improvement = (initial['metrics']['avg_duration'] - final['metrics']['avg_duration']) / initial['metrics']['avg_duration'] * 100

print(f"\n  Quality: {Colors.GREEN}{quality_improvement:+.1f}%{Colors.RESET}")
print(f"  Cost: {Colors.GREEN}{cost_improvement:+.1f}%{Colors.RESET} (lower is better)")
print(f"  Speed: {Colors.GREEN}{speed_improvement:+.1f}%{Colors.RESET} (faster)")

total_time = sum(c.get("duration", 0) for c in cycle_history)
print(f"\n  Total optimization time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
print(f"  Cycles run: {len(cycle_history)}")

print("\n" + "=" * 100)
print(f"{Colors.GREEN}{Colors.BOLD}✓ M5 SELF-IMPROVEMENT CYCLE COMPLETE{Colors.RESET}")
print("=" * 100 + "\n")
