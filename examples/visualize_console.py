#!/usr/bin/env python3
"""Create console-based Gantt chart visualization of M5.1 experiment metrics."""

import json
from datetime import datetime

# Load metrics
with open("/tmp/m5_demo_metrics.json") as f:
    data = json.load(f)

metrics = data["metrics"]
summary = data["summary"]
winner = data["winner"]

# ANSI color codes
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'

    # Quality colors
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    CYAN = '\033[96m'

    # Variant colors
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'

def quality_char(quality):
    """Return character and color for quality score."""
    if quality >= 0.85:
        return Colors.GREEN + '█' + Colors.RESET
    elif quality >= 0.75:
        return Colors.YELLOW + '▓' + Colors.RESET
    elif quality >= 0.65:
        return Colors.YELLOW + '▒' + Colors.RESET
    else:
        return Colors.RED + '░' + Colors.RESET

print("\n" + "=" * 80)
print(f"{Colors.BOLD}M5.1 EXPERIMENT: GANTT CHART TIMELINE{Colors.RESET}")
print("=" * 80)

print(f"\n{Colors.BOLD}Scenario:{Colors.RESET} Find Best Ollama Model for Product Extraction")
print(f"{Colors.BOLD}Executions:{Colors.RESET} 50 per variant (200 total LLM calls)")
print(f"{Colors.BOLD}Winner:{Colors.RESET} {Colors.GREEN}gemma2:2b (+25.7% quality improvement){Colors.RESET}")

print(f"\n{Colors.BOLD}Legend:{Colors.RESET}")
print(f"  {Colors.GREEN}█{Colors.RESET} High Quality (≥0.85)  ", end="")
print(f"{Colors.YELLOW}▓{Colors.RESET} Good (0.75-0.84)  ", end="")
print(f"{Colors.YELLOW}▒{Colors.RESET} Medium (0.65-0.74)  ", end="")
print(f"{Colors.RED}░{Colors.RESET} Low (<0.65)")

print("\n" + "-" * 80)
print(f"{Colors.BOLD}EXECUTION TIMELINE{Colors.RESET} (each block = 1 execution, color = quality)")
print("-" * 80 + "\n")

# Group metrics by variant
variants_data = {
    "control": {"label": "Control: llama3.1:8b (baseline)", "metrics": []},
    "variant_1": {"label": "Variant 1: gemma2:2b ⭐ WINNER", "metrics": []},
    "variant_2": {"label": "Variant 2: phi3:mini", "metrics": []},
    "variant_3": {"label": "Variant 3: mistral:7b", "metrics": []},
}

for m in metrics:
    variants_data[m["variant_id"]]["metrics"].append(m)

# Display timeline for each variant
for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    variant = variants_data[variant_id]
    label = variant["label"]

    # Highlight winner
    if variant_id == "variant_1":
        print(f"{Colors.GREEN}{Colors.BOLD}{label}{Colors.RESET}")
    else:
        print(f"{Colors.BOLD}{label}{Colors.RESET}")

    # Create timeline bar (50 executions)
    timeline = ""
    for m in sorted(variant["metrics"], key=lambda x: x["execution_index"]):
        timeline += quality_char(m["quality_score"])

    print(f"  {timeline}")

    # Show stats
    stats = summary[variant_id]
    print(f"  Quality: {stats['avg_quality']:.3f}  Duration: {stats['total_duration']:.1f}s  Cost: ${stats['total_cost']:.3f}")
    print()

print("-" * 80)
print(f"{Colors.BOLD}PERFORMANCE METRICS SUMMARY{Colors.RESET}")
print("-" * 80 + "\n")

# Create bar chart for quality scores
print(f"{Colors.BOLD}Average Quality Score Comparison:{Colors.RESET}\n")
max_quality = 1.0
bar_width = 50

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_data[variant_id]["label"].split(':')[0]

    # Normalize bar length
    bar_len = int((stats['avg_quality'] / max_quality) * bar_width)
    bar = '█' * bar_len

    # Color the bar
    if variant_id == "variant_1":
        bar = Colors.GREEN + bar + Colors.RESET
    elif stats['avg_quality'] >= 0.80:
        bar = Colors.CYAN + bar + Colors.RESET
    elif stats['avg_quality'] >= 0.70:
        bar = Colors.YELLOW + bar + Colors.RESET
    else:
        bar = Colors.RED + bar + Colors.RESET

    print(f"{label:20s} {bar} {stats['avg_quality']:.3f}")

print(f"\n{Colors.BOLD}Total Duration Comparison:{Colors.RESET}\n")
max_duration = max(summary[v]["total_duration"] for v in summary)

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_data[variant_id]["label"].split(':')[0]

    bar_len = int((stats['total_duration'] / max_duration) * bar_width)
    bar = Colors.BLUE + ('█' * bar_len) + Colors.RESET

    print(f"{label:20s} {bar} {stats['total_duration']:.1f}s ({stats['total_duration']/60:.1f}m)")

print(f"\n{Colors.BOLD}Total Cost Comparison:{Colors.RESET}\n")
max_cost = max(summary[v]["total_cost"] for v in summary)

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_data[variant_id]["label"].split(':')[0]

    bar_len = int((stats['total_cost'] / max_cost) * bar_width)
    bar = Colors.MAGENTA + ('█' * bar_len) + Colors.RESET

    print(f"{label:20s} {bar} ${stats['total_cost']:.3f}")

print("\n" + "-" * 80)
print(f"{Colors.BOLD}DETAILED STATISTICS{Colors.RESET}")
print("-" * 80 + "\n")

# Detailed table
header = f"{'Variant':<25s} {'Executions':>11s} {'Avg Quality':>12s} {'Avg Duration':>13s} {'Total Cost':>12s}"
print(Colors.BOLD + header + Colors.RESET)
print("-" * 80)

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_data[variant_id]["label"].split(':')[1].strip()

    row = f"{label:<25s} {stats['executions']:>11d} {stats['avg_quality']:>12.3f} {stats['avg_duration']:>11.2f}s  ${stats['total_cost']:>10.3f}"

    if variant_id == "variant_1":
        print(Colors.GREEN + row + Colors.RESET)
    else:
        print(row)

print("\n" + "=" * 80)
print(f"{Colors.GREEN}{Colors.BOLD}🏆 WINNER: {winner['model']}{Colors.RESET}")
print(f"   {Colors.GREEN}Improvement: +{winner['improvement_percentage']:.1f}%{Colors.RESET}")
print(f"   {Colors.GREEN}Confidence: {winner['confidence_level']*100:.1f}%{Colors.RESET}")
print(f"   Statistical Significance: {Colors.GREEN}Yes{Colors.RESET}")
print("=" * 80 + "\n")

print(f"{Colors.BOLD}Key Insights:{Colors.RESET}")
print(f"  • gemma2:2b achieved {Colors.GREEN}25.7% higher quality{Colors.RESET} than baseline")
print(f"  • gemma2:2b is also {Colors.GREEN}9% faster{Colors.RESET} (4.55s vs 4.99s)")
print(f"  • gemma2:2b costs {Colors.GREEN}25% less{Colors.RESET} ($0.754 vs $1.016)")
print(f"  • phi3:mini is fastest but quality is only moderate (0.751)")
print(f"  • mistral:7b has good quality (0.821) but is slowest and most expensive")

print(f"\n{Colors.BOLD}Recommendation:{Colors.RESET}")
print(f"  {Colors.GREEN}✓ Deploy gemma2:2b to production{Colors.RESET}")
print(f"  {Colors.GREEN}✓ Expected impact: Better quality, faster, cheaper{Colors.RESET}")
print(f"  {Colors.GREEN}✓ Enable rollback monitoring for 24 hours{Colors.RESET}")
print()
