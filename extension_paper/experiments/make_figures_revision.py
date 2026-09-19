#!/usr/bin/env python3
"""
Peer-review revision figures: AO-25 full matrix (D1-D5 x 5 categories),
the hash-only ablation (D1 vs D1-ext vs D4 vs D5), and the depth/input-size
scaling benchmark. Same visual conventions (serif font, spine/grid style,
detector color map, 300 DPI) as experiments/make_figures.py, kept as a
separate script so the original eight figures' generation is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 9,
        "figure.dpi": 300,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
    }
)

GRAY = "#6B7280"
GREEN = "#059669"
BLUE = "#1D4ED8"
PURPLE = "#9333EA"
AMBER = "#D97706"
DETECTOR_COLORS = {"D1": GRAY, "D2": GRAY, "D3": GRAY, "D4": AMBER, "D5": GREEN, "D1ext": BLUE}


def _latest_run_dir(experiment: str) -> Optional[Path]:
    exp_dir = RESULTS_ROOT / experiment
    if not exp_dir.is_dir():
        return None
    run_dirs = sorted(p for p in exp_dir.iterdir() if p.is_dir())
    return run_dirs[-1] if run_dirs else None


def _load(run_dir: Path, name: str) -> Dict[str, Any]:
    return json.loads((run_dir / name).read_text())


def _save(fig: "plt.Figure", run_dir: Path, name: str) -> None:
    out = run_dir / "figures" / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {out.relative_to(RESULTS_ROOT.parent)}")


def fig_ao25_full_matrix() -> None:
    run_dir = _latest_run_dir("a6_ao25_eval")
    if run_dir is None:
        print("skip a6: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    detectors = stats["detectors"]
    names = list(detectors.keys())
    short = [n.split("_")[0] for n in names]
    categories = ["TC", "TV", "LO", "CS", "AO"]

    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    n_det = len(names)
    n_cat = len(categories)
    w = 0.8 / n_det
    x = np.arange(n_cat)
    for i, (name, s) in enumerate(zip(names, short)):
        f1s = [detectors[name]["by_category"][c]["f1"] for c in categories]
        offset = (i - (n_det - 1) / 2) * w
        ax.bar(
            x + offset,
            f1s,
            width=w,
            label=s,
            color=DETECTOR_COLORS.get(s, GRAY),
            edgecolor="white",
            linewidth=0.6,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{c}\n(n={stats['category_counts'][c]})" for c in categories])
    ax.set_ylabel("F1 score")
    ax.set_ylim(0, 1.32)
    ax.set_title(
        f"D1-D5 F1 by category, {stats['n_pairs']}-pair matrix (43 original + 25 AO)\n"
        f"TV's F1=0 is a zero-denominator convention on an all-negative category, not a detector failure",
        fontsize=9.5,
        pad=42,
    )
    ax.legend(fontsize=8.5, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    fig.tight_layout()
    _save(fig, run_dir, "ao25_full_matrix_f1_by_detector")


def fig_hash_ablation() -> None:
    run_dir = _latest_run_dir("a7_hash_ablation")
    if run_dir is None:
        print("skip a7: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    detectors = stats["detectors"]
    order = ["D1_exact_hash", "D1ext_hash_with_aggregation", "D4_structural_topology", "D5_with_aggregation"]
    labels = [
        "D1\n(exact hash)",
        "D1-ext\n(hash + agg.,\nno topology)",
        "D4\n(structural +\ntopology)",
        "D5\n(D4 + agg.\nequality)",
    ]
    colors = [GRAY, BLUE, AMBER, GREEN]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    ax = axes[0]
    ao_f1 = [detectors[d]["by_category"]["AO"]["f1"] for d in order]
    bars = ax.bar(labels, ao_f1, color=colors, edgecolor="white", linewidth=0.8)
    for bar, v in zip(bars, ao_f1):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.03, f"{v:.3f}", ha="center", fontsize=8.5)
    ax.set_ylabel("F1 score")
    ax.set_ylim(0, 1.2)
    ax.set_title("AO category (n=25):\nextending the hash alone nearly closes it", fontsize=9.5)

    ax = axes[1]
    tv_f1 = [detectors[d]["by_category"]["TV"]["f1"] for d in order]
    overall_f1 = [detectors[d]["overall"]["f1"] for d in order]
    x = np.arange(len(order))
    w = 0.32
    ax.bar(x - w / 2, tv_f1, width=w, label="TV category F1", color="#B91C1C", edgecolor="white")
    ax.bar(x + w / 2, overall_f1, width=w, label="Overall F1 (68 pairs)", color=PURPLE, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 1.2)
    ax.legend(fontsize=8)
    ax.set_title("...but D1-ext still inherits D1's\nTV false-positive problem", fontsize=9.5)
    for xi, (t, o) in enumerate(zip(tv_f1, overall_f1)):
        ax.text(xi - w / 2, t + 0.03, f"{t:.2f}", ha="center", fontsize=7.5)
        ax.text(xi + w / 2, o + 0.03, f"{o:.2f}", ha="center", fontsize=7.5)

    fig.suptitle(
        "Ablation: hash-payload extension alone vs. D5's structural+topology+aggregation design",
        fontsize=10,
        y=1.04,
    )
    _save(fig, run_dir, "hash_ablation")


def fig_scaling_benchmark() -> None:
    run_dir = _latest_run_dir("a8_scaling_benchmark")
    if run_dir is None:
        print("skip a8: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    ax = axes[0]
    depths = [r["depth"] for r in stats["closure_vs_depth"]]
    means = [r["mean_us"] for r in stats["closure_vs_depth"]]
    ax.plot(depths, means, marker="o", color=PURPLE, linewidth=1.6)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log", base=2)
    ax.set_xlabel("Materialization-chain depth (registered hops)")
    ax.set_ylabel("Mean closure latency (microseconds)")
    ax.set_title(
        "close_lineage() runtime vs. chain depth\n(linear in depth; default guard caps at depth 8)",
        fontsize=9.5,
    )
    ax.axvline(8, color=GRAY, linestyle=":", linewidth=1.2)
    ax.text(8.3, means[0], "default\n_max_depth=8", fontsize=7.5, color=GRAY)

    ax = axes[1]
    d4 = stats["detector_runtime_vs_input_size"]["D4_structural_topology"]
    d5 = stats["detector_runtime_vs_input_size"]["D5_with_aggregation"]
    ns = [r["n_tables_columns"] for r in d4]
    d4_us = [r["mean_us"] for r in d4]
    d5_us = [r["mean_us"] for r in d5]
    ax.plot(ns, d4_us, marker="o", color=AMBER, label="D4", linewidth=1.6)
    ax.plot(ns, d5_us, marker="s", color=GREEN, label="D5", linewidth=1.6)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log", base=2)
    ax.set_xlabel("Tables/columns touched (n)")
    ax.set_ylabel("Mean detector latency (microseconds)")
    ax.legend(fontsize=8.5)
    ax.set_title(
        "D4/D5 runtime vs. lineage size\n(D5's overhead over D4 stays small at every size)", fontsize=9.5
    )

    _save(fig, run_dir, "scaling_benchmark")


def main() -> None:
    print("Generating peer-review revision figures...")
    fig_ao25_full_matrix()
    fig_hash_ablation()
    fig_scaling_benchmark()
    print("Done.")


if __name__ == "__main__":
    main()
