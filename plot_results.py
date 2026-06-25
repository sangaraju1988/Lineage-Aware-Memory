import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

with open("/home/claude/lineage_playground/sweep_raw.json") as f:
    all_rows = json.load(f)

systems = ["no_memory", "naive", "lineage_aware"]
labels = ["No Memory\n(status quo)", "Naive Shared Memory\n(content-gated)", "Lineage-Aware\nGoverned Memory"]
colors = ["#9CA3AF", "#EF4444", "#10B981"]

fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))

metrics = [
    ("leak", "Leak Rate (%)\nlower is better", axes[0]),
    ("reuse", "Memory Reuse Rate (%)\nhigher is better", axes[1]),
    ("conflict_recall", "Metric-Conflict Recall (%)\nhigher is better", axes[2]),
]

for key, title, ax in metrics:
    means = []
    sds = []
    plot_labels = []
    plot_colors = []
    for sys_name, label, color in zip(systems, labels, colors):
        vals = all_rows[sys_name].get(key, [])
        if not vals:
            continue
        means.append(np.mean(vals))
        sds.append(np.std(vals))
        plot_labels.append(label)
        plot_colors.append(color)
    x = np.arange(len(plot_labels))
    bars = ax.bar(x, means, yerr=sds, capsize=4, color=plot_colors, width=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(plot_labels, fontsize=9)
    ax.set_title(title, fontsize=10)
    ax.set_ylim(0, 105)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width()/2, m + 3, f"{m:.1f}", ha="center", fontsize=9, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("Lineage-Aware Memory Governance vs. Existing Approaches\n(30-seed synthetic workload, mean \u00b1 std dev)",
             fontsize=12, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.90])
plt.savefig("/home/claude/lineage_playground/results_chart.png", dpi=160)
print("Saved results_chart.png")
