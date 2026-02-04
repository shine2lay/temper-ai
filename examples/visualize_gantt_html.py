#!/usr/bin/env python3
"""Create interactive HTML Gantt chart visualization of M5.1 experiment metrics."""

import json
from datetime import datetime

# Load metrics
with open("/tmp/m5_demo_metrics.json") as f:
    data = json.load(f)

metrics = data["metrics"]
summary = data["summary"]
winner = data["winner"]

# Group by variant
variants_info = {
    "control": {"label": "Control: llama3.1:8b (baseline)", "color": "#3b82f6"},
    "variant_1": {"label": "Variant 1: gemma2:2b (WINNER ⭐)", "color": "#22c55e"},
    "variant_2": {"label": "Variant 2: phi3:mini", "color": "#f59e0b"},
    "variant_3": {"label": "Variant 3: mistral:7b", "color": "#ef4444"},
}

# Quality color mapping
def quality_to_color(quality):
    if quality >= 0.85:
        return "#22c55e"  # Green
    elif quality >= 0.75:
        return "#eab308"  # Yellow
    elif quality >= 0.65:
        return "#f97316"  # Orange
    else:
        return "#ef4444"  # Red

# Prepare Plotly data
traces = []

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    variant_metrics = [m for m in metrics if m["variant_id"] == variant_id]
    variant_info = variants_info[variant_id]

    # Create trace for each execution
    for m in variant_metrics:
        start_dt = datetime.fromisoformat(m["start_time"])
        end_dt = datetime.fromisoformat(m["end_time"])

        traces.append({
            "x": [m["start_time"], m["end_time"]],
            "y": [variant_info["label"], variant_info["label"]],
            "mode": "lines",
            "line": {
                "color": quality_to_color(m["quality_score"]),
                "width": 15
            },
            "hovertemplate": (
                f"<b>{m['model']}</b><br>"
                f"Execution #{m['execution_index']}<br>"
                f"Quality: {m['quality_score']:.3f}<br>"
                f"Duration: {m['duration_seconds']:.2f}s<br>"
                f"Cost: ${m['cost_usd']:.4f}<br>"
                f"<extra></extra>"
            ),
            "showlegend": False,
        })

# Create HTML
html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>M5.1 Experiment Gantt Chart</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            margin: 20px;
            background: #f8fafc;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #1e293b;
            margin-bottom: 10px;
        }}
        .subtitle {{
            color: #64748b;
            margin-bottom: 30px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }}
        .stat-card {{
            background: #f1f5f9;
            padding: 20px;
            border-radius: 6px;
            border-left: 4px solid;
        }}
        .stat-card.control {{ border-left-color: #3b82f6; }}
        .stat-card.variant_1 {{ border-left-color: #22c55e; }}
        .stat-card.variant_2 {{ border-left-color: #f59e0b; }}
        .stat-card.variant_3 {{ border-left-color: #ef4444; }}
        .stat-card h3 {{
            margin: 0 0 15px 0;
            color: #1e293b;
            font-size: 14px;
            font-weight: 600;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 13px;
        }}
        .stat-label {{
            color: #64748b;
        }}
        .stat-value {{
            font-weight: 600;
            color: #1e293b;
        }}
        .winner-badge {{
            background: #22c55e;
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
            margin-top: 10px;
        }}
        .legend {{
            display: flex;
            gap: 20px;
            margin: 20px 0;
            padding: 15px;
            background: #f8fafc;
            border-radius: 6px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>M5.1 Experiment: Gantt Chart Timeline</h1>
        <div class="subtitle">
            Real-time execution timeline showing 50 LLM calls per model variant (200 total)
        </div>

        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background: #22c55e;"></div>
                <span>High Quality (≥0.85)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #eab308;"></div>
                <span>Good Quality (0.75-0.84)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #f97316;"></div>
                <span>Medium Quality (0.65-0.74)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #ef4444;"></div>
                <span>Low Quality (<0.65)</span>
            </div>
        </div>

        <div id="gantt"></div>

        <div class="stats">
"""

# Add stat cards
for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_info[variant_id]["label"]

    winner_badge = ""
    if variant_id == "variant_1":
        winner_badge = '<div class="winner-badge">WINNER: +25.7% Quality Improvement</div>'

    html += f"""
            <div class="stat-card {variant_id}">
                <h3>{label}</h3>
                <div class="stat-row">
                    <span class="stat-label">Executions</span>
                    <span class="stat-value">{stats['executions']}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Avg Quality</span>
                    <span class="stat-value">{stats['avg_quality']:.3f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Quality Range</span>
                    <span class="stat-value">{stats['min_quality']:.3f} - {stats['max_quality']:.3f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Avg Duration</span>
                    <span class="stat-value">{stats['avg_duration']:.2f}s</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Duration</span>
                    <span class="stat-value">{stats['total_duration']:.1f}s ({stats['total_duration']/60:.1f}m)</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Total Cost</span>
                    <span class="stat-value">${stats['total_cost']:.3f}</span>
                </div>
                {winner_badge}
            </div>
"""

html += """
        </div>
    </div>

    <script>
        var data = """ + json.dumps(traces) + """;

        var layout = {
            title: {
                text: 'Execution Timeline by Model Variant',
                font: { size: 16, color: '#1e293b' }
            },
            xaxis: {
                title: 'Time',
                type: 'date',
                tickformat: '%H:%M:%S',
                gridcolor: '#e2e8f0',
            },
            yaxis: {
                title: '',
                categoryorder: 'array',
                categoryarray: [
                    'Variant 3: mistral:7b',
                    'Variant 2: phi3:mini',
                    'Variant 1: gemma2:2b (WINNER ⭐)',
                    'Control: llama3.1:8b (baseline)'
                ],
                gridcolor: '#e2e8f0',
            },
            height: 500,
            margin: { l: 280, r: 50, t: 50, b: 80 },
            hovermode: 'closest',
            plot_bgcolor: '#ffffff',
            paper_bgcolor: '#ffffff',
        };

        var config = {
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
        };

        Plotly.newPlot('gantt', data, layout, config);
    </script>
</body>
</html>
"""

# Save HTML
output_file = "/tmp/m5_demo_gantt.html"
with open(output_file, "w") as f:
    f.write(html)

print("✅ Interactive Gantt chart created!")
print(f"📊 Open in browser: file://{output_file}")
print(f"\nOr run: xdg-open {output_file}")

# Print summary
print("\n" + "="*70)
print("M5.1 EXPERIMENT METRICS SUMMARY")
print("="*70)

for variant_id in ["control", "variant_1", "variant_2", "variant_3"]:
    stats = summary[variant_id]
    label = variants_info[variant_id]["label"]

    print(f"\n{label}")
    print(f"  Executions: {stats['executions']}")
    print(f"  Quality: {stats['avg_quality']:.3f} (range: {stats['min_quality']:.3f} - {stats['max_quality']:.3f})")
    print(f"  Avg Duration: {stats['avg_duration']:.2f}s")
    print(f"  Total Duration: {stats['total_duration']:.1f}s ({stats['total_duration']/60:.1f} min)")
    print(f"  Total Cost: ${stats['total_cost']:.3f}")

print(f"\n{'='*70}")
print(f"🏆 WINNER: {winner['model']}")
print(f"   Improvement: +{winner['improvement_percentage']:.1f}%")
print(f"   Confidence: {winner['confidence_level']*100:.1f}%")
print(f"{'='*70}")
