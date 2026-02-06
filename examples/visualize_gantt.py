#!/usr/bin/env python3
"""Create Gantt chart visualization of M5.1 experiment metrics."""

import json
from datetime import datetime

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

# Load metrics
with open("/tmp/m5_demo_metrics.json") as f:
    data = json.load(f)

metrics = data["metrics"]
summary = data["summary"]
winner = data["winner"]

# Convert timestamps
for m in metrics:
    m["start_dt"] = datetime.fromisoformat(m["start_time"])
    m["end_dt"] = datetime.fromisoformat(m["end_time"])

# Group by variant
variants_data = {}
for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    variants_data[variant_id] = [m for m in metrics if m["variant_id"] == variant_id]

# Create figure
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                gridspec_kw={'height_ratios': [3, 1]})

# Color mapping based on quality score
def quality_to_color(quality):
    """Map quality score to color (red=poor, yellow=ok, green=excellent)."""
    if quality < 0.7:
        return '#ff6b6b'  # Red
    elif quality < 0.8:
        return '#ffd93d'  # Yellow
    else:
        return '#6bcf7f'  # Green

# --- Top plot: Gantt chart of executions ---
variant_labels = {
    "control": "Control: llama3.1:8b (baseline)",
    "variant_1": "Variant 1: gemma2:2b (WINNER ⭐)",
    "variant_2": "Variant 2: phi3:mini",
    "variant_3": "Variant 3: mistral:7b",
}

y_positions = {"control": 0, "variant_1": 1, "variant_2": 2, "variant_3": 3}

# Plot each execution as a horizontal bar
for variant_id, variant_metrics in variants_data.items():
    y_pos = y_positions[variant_id]

    for m in variant_metrics:
        # Bar width is the duration
        width = (m["end_dt"] - m["start_dt"]).total_seconds() / 86400  # Convert to days for matplotlib
        color = quality_to_color(m["quality_score"])

        ax1.barh(y_pos, width, left=m["start_dt"], height=0.6,
                color=color, alpha=0.8, edgecolor='white', linewidth=0.5)

# Format top plot
ax1.set_yticks(list(y_positions.values()))
ax1.set_yticklabels([variant_labels[vid] for vid in ["control", "variant_1", "variant_2", "variant_3"]])
ax1.set_xlabel("Time", fontsize=12, fontweight='bold')
ax1.set_title("M5.1 Experiment Execution Timeline\n50 Executions per Variant (200 Total)",
              fontsize=14, fontweight='bold', pad=20)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
ax1.xaxis.set_major_locator(mdates.SecondLocator(interval=60))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
ax1.grid(axis='x', alpha=0.3, linestyle='--')
ax1.set_xlim(left=min(m["start_dt"] for m in metrics),
             right=max(m["end_dt"] for m in metrics))

# Add legend for quality colors
quality_legend = [
    mpatches.Patch(color='#6bcf7f', label='High Quality (>0.8)'),
    mpatches.Patch(color='#ffd93d', label='Medium Quality (0.7-0.8)'),
    mpatches.Patch(color='#ff6b6b', label='Low Quality (<0.7)'),
]
ax1.legend(handles=quality_legend, loc='upper right', fontsize=10)

# --- Bottom plot: Summary statistics bar chart ---
variant_order = ["control", "variant_1", "variant_2", "variant_3"]
labels = [variant_labels[vid].split(':')[1].strip() for vid in variant_order]
quality_scores = [summary[vid]["avg_quality"] for vid in variant_order]
durations = [summary[vid]["total_duration"] for vid in variant_order]
costs = [summary[vid]["total_cost"] for vid in variant_order]

x_pos = range(len(variant_order))
bar_width = 0.25

# Create grouped bar chart
bars1 = ax2.bar([p - bar_width for p in x_pos], quality_scores, bar_width,
                label='Avg Quality', color='#6bcf7f', alpha=0.8)
bars2 = ax2.bar(x_pos, [d/100 for d in durations], bar_width,
                label='Total Duration (÷100s)', color='#4a90e2', alpha=0.8)
bars3 = ax2.bar([p + bar_width for p in x_pos], costs, bar_width,
                label='Total Cost ($)', color='#f39c12', alpha=0.8)

# Add value labels on bars
for bars in [bars1, bars2, bars3]:
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}', ha='center', va='bottom', fontsize=9)

ax2.set_xticks(x_pos)
ax2.set_xticklabels(labels, rotation=15, ha='right')
ax2.set_ylabel('Value', fontsize=11, fontweight='bold')
ax2.set_title('Performance Metrics Summary', fontsize=12, fontweight='bold', pad=10)
ax2.legend(loc='upper left', fontsize=10)
ax2.grid(axis='y', alpha=0.3, linestyle='--')

# Add winner annotation
winner_x = variant_order.index("variant_1")
ax2.annotate('WINNER\n+25.7%', xy=(winner_x, 1.0), xytext=(winner_x, 1.3),
            arrowprops=dict(arrowstyle='->', color='green', lw=2),
            fontsize=12, fontweight='bold', color='green',
            ha='center', bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgreen', alpha=0.7))

plt.tight_layout()

# Save figure
output_file = "/tmp/m5_demo_gantt.png"
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"✅ Gantt chart saved to: {output_file}")

# Also display summary
print("\n" + "="*70)
print("M5.1 EXPERIMENT METRICS SUMMARY")
print("="*70)

for variant_id in variant_order:
    stats = summary[variant_id]
    label = variant_labels[variant_id]

    print(f"\n{label}")
    print(f"  Executions: {stats['executions']}")
    print(f"  Quality: {stats['avg_quality']:.3f} (range: {stats['min_quality']:.3f} - {stats['max_quality']:.3f})")
    print(f"  Avg Duration: {stats['avg_duration']:.2f}s")
    print(f"  Total Duration: {stats['total_duration']:.1f}s ({stats['total_duration']/60:.1f} min)")
    print(f"  Total Cost: ${stats['total_cost']:.3f}")

if winner:
    print(f"\n{'='*70}")
    print(f"🏆 WINNER: {winner['model']}")
    print(f"   Improvement: +{winner['improvement_percentage']:.1f}%")
    print(f"   Confidence: {winner['confidence_level']*100:.1f}%")
    print(f"{'='*70}")

print(f"\n📊 Gantt chart visualization: {output_file}")
