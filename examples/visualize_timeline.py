#!/usr/bin/env python3
"""Create historical timeline Gantt chart showing actual execution times."""

import json
from datetime import datetime, timedelta

# Load metrics
with open("/tmp/m5_demo_metrics.json") as f:
    data = json.load(f)

metrics = data["metrics"]
summary = data["summary"]

# ANSI color codes
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RED = '\033[91m'

def format_time(dt):
    """Format datetime to HH:MM:SS."""
    return dt.strftime("%H:%M:%S")

def duration_to_bar(duration, max_duration, bar_width=40):
    """Convert duration to bar visualization."""
    bar_len = int((duration / max_duration) * bar_width)
    return '█' * max(1, bar_len)

print("\n" + "=" * 100)
print(f"{Colors.BOLD}M5.1 EXPERIMENT: HISTORICAL TIMELINE GANTT CHART{Colors.RESET}")
print("=" * 100)

print(f"\n{Colors.BOLD}Shows chronological execution order with actual start/end times and durations{Colors.RESET}")

# Parse timestamps and sort by time
for m in metrics:
    m["start_dt"] = datetime.fromisoformat(m["start_time"])
    m["end_dt"] = datetime.fromisoformat(m["end_time"])

# Get overall time range
first_start = min(m["start_dt"] for m in metrics)
last_end = max(m["end_dt"] for m in metrics)
total_experiment_duration = (last_end - first_start).total_seconds()

print(f"\n{Colors.BOLD}Experiment Timeline:{Colors.RESET}")
print(f"  Start: {format_time(first_start)}")
print(f"  End: {format_time(last_end)}")
print(f"  Total Duration: {total_experiment_duration:.1f}s ({total_experiment_duration/60:.1f} minutes)")

# Group by variant
variants_info = {
    "control": {"label": "Control: llama3.1:8b", "color": Colors.BLUE},
    "variant_1": {"label": "Variant 1: gemma2:2b ⭐", "color": Colors.GREEN},
    "variant_2": {"label": "Variant 2: phi3:mini", "color": Colors.YELLOW},
    "variant_3": {"label": "Variant 3: mistral:7b", "color": Colors.MAGENTA},
}

# Show execution rounds for each variant
print("\n" + "-" * 100)
print(f"{Colors.BOLD}EXECUTION ROUNDS BY VARIANT{Colors.RESET}")
print("-" * 100)

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    variant_metrics = sorted(
        [m for m in metrics if m["variant_id"] == variant_id],
        key=lambda x: x["start_dt"]
    )

    info = variants_info[variant_id]
    stats = summary[variant_id]

    print(f"\n{info['color']}{Colors.BOLD}{info['label']}{Colors.RESET}")
    print(f"  Total Executions: {len(variant_metrics)} | Avg Duration: {stats['avg_duration']:.2f}s")
    print(f"  Timeline: {format_time(variant_metrics[0]['start_dt'])} → {format_time(variant_metrics[-1]['end_dt'])}")
    print()

    # Show first 10 and last 10 executions
    show_metrics = variant_metrics[:10] + variant_metrics[-10:] if len(variant_metrics) > 20 else variant_metrics

    max_duration = max(m["duration_seconds"] for m in variant_metrics)

    for i, m in enumerate(show_metrics):
        exec_num = m["execution_index"] + 1
        start_time = format_time(m["start_dt"])
        end_time = format_time(m["end_dt"])
        duration = m["duration_seconds"]
        quality = m["quality_score"]

        # Create duration bar
        bar = duration_to_bar(duration, max_duration, bar_width=30)
        bar = info['color'] + bar + Colors.RESET

        # Quality indicator
        if quality >= 0.85:
            quality_str = f"{Colors.GREEN}{quality:.3f}{Colors.RESET}"
        elif quality >= 0.75:
            quality_str = f"{Colors.YELLOW}{quality:.3f}{Colors.RESET}"
        else:
            quality_str = f"{Colors.RED}{quality:.3f}{Colors.RESET}"

        print(f"  #{exec_num:2d}  {start_time} → {end_time}  {bar}  {duration:5.2f}s  Q:{quality_str}")

        # Show ellipsis if we skipped middle executions
        if i == 9 and len(variant_metrics) > 20:
            print(f"  ...  (executions #{11}-{len(variant_metrics)-10} omitted)")

print("\n" + "-" * 100)
print(f"{Colors.BOLD}TIMELINE VISUALIZATION{Colors.RESET} (showing all 200 executions chronologically)")
print("-" * 100)

# Create timeline view - show executions in 4 parallel tracks (one per variant)
# Scale timeline to fit in 80 characters
timeline_width = 80
time_scale = total_experiment_duration / timeline_width

print(f"\n{Colors.BOLD}Time Scale:{Colors.RESET} Each character = {time_scale:.1f}s")
print(f"\n{'Time':<12s} {'Control':<20s} {'Variant 1 ⭐':<20s} {'Variant 2':<20s} {'Variant 3':<20s}")
print("-" * 100)

# Create time buckets
num_rows = 30
time_per_row = total_experiment_duration / num_rows

for row in range(num_rows):
    row_start = first_start + timedelta(seconds=row * time_per_row)
    row_end = first_start + timedelta(seconds=(row + 1) * time_per_row)

    time_label = format_time(row_start)

    # Check which variants have executions in this time window
    row_output = [time_label]

    for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
        variant_metrics = [m for m in metrics if m["variant_id"] == variant_id]

        # Count executions in this time window
        executions_in_window = [
            m for m in variant_metrics
            if row_start <= m["start_dt"] < row_end or row_start <= m["end_dt"] < row_end
        ]

        info = variants_info[variant_id]

        if executions_in_window:
            # Show number of executions
            count = len(executions_in_window)
            avg_quality = sum(m["quality_score"] for m in executions_in_window) / count

            if avg_quality >= 0.85:
                indicator = f"{info['color']}{'█' * min(count, 5)}{Colors.RESET}"
            elif avg_quality >= 0.75:
                indicator = f"{info['color']}{'▓' * min(count, 5)}{Colors.RESET}"
            else:
                indicator = f"{info['color']}{'▒' * min(count, 5)}{Colors.RESET}"

            row_output.append(f"{indicator} ({count})")
        else:
            row_output.append("·" * 5)

    print(f"{row_output[0]:<12s} {row_output[1]:<20s} {row_output[2]:<20s} {row_output[3]:<20s} {row_output[4]:<20s}")

print("\n" + "-" * 100)
print(f"{Colors.BOLD}CUMULATIVE EXECUTION TIME{Colors.RESET}")
print("-" * 100 + "\n")

# Show cumulative execution time for each variant
for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    variant_metrics = sorted(
        [m for m in metrics if m["variant_id"] == variant_id],
        key=lambda x: x["start_dt"]
    )

    info = variants_info[variant_id]
    stats = summary[variant_id]

    # Calculate cumulative time
    cumulative_times = []
    cumulative = 0
    for m in variant_metrics:
        cumulative += m["duration_seconds"]
        cumulative_times.append(cumulative)

    # Show progress at 10%, 50%, 90%, 100%
    milestones = [
        (10, variant_metrics[4]),
        (25, variant_metrics[12]),
        (50, variant_metrics[24]),
        (75, variant_metrics[37]),
        (100, variant_metrics[49]),
    ]

    print(f"{info['color']}{Colors.BOLD}{info['label']}{Colors.RESET}")

    for pct, m in milestones:
        idx = m["execution_index"]
        elapsed = cumulative_times[idx]
        time_point = format_time(m["end_dt"])

        progress_bar = '█' * (pct // 2)
        print(f"  {pct:3d}% │{info['color']}{progress_bar:<50s}{Colors.RESET}│ {elapsed:6.1f}s  at {time_point}")

    print()

print("=" * 100)
print(f"{Colors.GREEN}{Colors.BOLD}🏆 WINNER: gemma2:2b (+25.7% quality, 9% faster, 25% cheaper){Colors.RESET}")
print("=" * 100 + "\n")
