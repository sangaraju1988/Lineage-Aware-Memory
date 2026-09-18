#!/usr/bin/env python3
"""
Generate publication-style figures from the most recent real results/ run
of each Group A/B/C experiment (Section 6's "figures/*.png" requirement).

Visual style (palette, serif font, spine/grid conventions) mirrors the
published paper's own ``gen_figures.py`` at the repo root, so the extension
paper's figures read as a continuation of the same visual language rather
than a mismatched second style.

Each figure is written into the specific run_id folder it was computed
from (``results/<experiment>/<run_id>/figures/<name>.png``), never into a
shared/loose location, so every figure stays traceable to the exact
raw_results.json / summary_stats.json / run_manifest.json it came from --
the same traceability RESULTS.md's numbers are held to.

Run via ``make figures`` (after ``make experiments`` has populated
results/), or directly: ``python experiments/make_figures.py``.
"""

from __future__ import annotations

import json
import sys
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
        "figure.dpi": 200,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
    }
)

GRAY = "#6B7280"
RED = "#DC2626"
GREEN = "#059669"
BLUE = "#1D4ED8"
PURPLE = "#9333EA"
AMBER = "#D97706"
DETECTOR_COLORS = {"D1": GRAY, "D2": GRAY, "D3": GRAY, "D4": AMBER, "D5": GREEN}


def _latest_run_dir(experiment: str, *, prefer_max_key: Optional[str] = None) -> Optional[Path]:
    """Return the run_id directory to plot for ``experiment``.

    By default, the lexicographically-latest run_id (timestamps sort
    lexicographically, so this is also the most recent). When
    ``prefer_max_key`` is given (Group C1's "n_seeds"), the run whose
    summary_stats.json has the largest value for that key is preferred
    instead -- C1 has both the real 30-seed run and, harmlessly, whatever
    fast dev-loop re-runs a contributor made locally; the figure should
    always reflect the full run, not whichever happened most recently.
    """
    exp_dir = RESULTS_ROOT / experiment
    if not exp_dir.is_dir():
        return None
    run_dirs = sorted(p for p in exp_dir.iterdir() if p.is_dir())
    if not run_dirs:
        return None
    if prefer_max_key is None:
        return run_dirs[-1]
    best, best_val = None, -1.0
    for rd in run_dirs:
        stats_path = rd / "summary_stats.json"
        if not stats_path.exists():
            continue
        val = json.loads(stats_path.read_text()).get(prefer_max_key, -1)
        if isinstance(val, (int, float)) and val > best_val:
            best, best_val = rd, val
    return best or run_dirs[-1]


def _load(run_dir: Path, name: str) -> Dict[str, Any]:
    return json.loads((run_dir / name).read_text())  # type: ignore[no-any-return]


def _save(fig: "plt.Figure", run_dir: Path, name: str) -> None:
    out = run_dir / "figures" / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"  wrote {out.relative_to(RESULTS_ROOT.parent)}")


def fig_a1_detector_f1_original_dataset() -> None:
    run_dir = _latest_run_dir("a1_d4_eval")
    if run_dir is None:
        print("skip a1: no results found (run `make experiments` first)")
        return
    stats = _load(run_dir, "summary_stats.json")
    detectors = stats["detectors"]
    names = list(detectors.keys())
    short = [n.split("_")[0] for n in names]
    f1s = [detectors[n]["f1"] for n in names]
    ci_los = [detectors[n].get("f1_bootstrap_ci", {}).get("ci_lo", f1) for n, f1 in zip(names, f1s)]
    ci_his = [detectors[n].get("f1_bootstrap_ci", {}).get("ci_hi", f1) for n, f1 in zip(names, f1s)]
    yerr = [[f1 - lo for f1, lo in zip(f1s, ci_los)], [hi - f1 for f1, hi in zip(f1s, ci_his)]]
    colors = [DETECTOR_COLORS.get(s, GRAY) for s in short]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    x = np.arange(len(short))
    bars = ax.bar(x, f1s, yerr=yerr, capsize=5, color=colors, width=0.55, edgecolor="white", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("F1 score")
    ax.set_ylim(0, 1.15)
    ax.set_title(
        "Detector F1 on the original 43-pair dataset\n(TC/TV/LO/CS categories; 95% bootstrap CI, n=10,000)",
        fontsize=10,
    )
    for bar, f1 in zip(bars, f1s):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03, f"{f1:.3f}", ha="center", fontsize=8.5
        )
    _save(fig, run_dir, "detector_f1_original_dataset")


def fig_a2_d4_vs_d5_ao_category() -> None:
    run_dir = _latest_run_dir("a2_d5_eval")
    if run_dir is None:
        print("skip a2: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    metrics = ["precision", "recall", "f1"]
    d4 = [stats["D4"][m] for m in metrics]
    d5 = [stats["D5"][m] for m in metrics]
    mcnemar = stats["mcnemar_D4_vs_D5"]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    x = np.arange(len(metrics))
    w = 0.32
    ax.bar(x - w / 2, d4, width=w, label="D4 (no aggregation check)", color=AMBER, edgecolor="white")
    ax.bar(x + w / 2, d5, width=w, label="D5 (D4 + aggregation-equality)", color=GREEN, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(["Precision", "Recall", "F1"])
    ax.set_ylim(0, 1.25)
    ax.legend(fontsize=8.5, loc="upper center")
    ax.set_title(
        f"D4 vs D5 on the Aggregation-Operator (AO) category\n"
        f"McNemar p={mcnemar['p_value']:.5f} (n_discordant={mcnemar['n_discordant']}, exact test)",
        fontsize=10,
    )
    for xi, (v4, v5) in enumerate(zip(d4, d5)):
        ax.text(xi - w / 2, v4 + 0.03, f"{v4:.2f}", ha="center", fontsize=8)
        ax.text(xi + w / 2, v5 + 0.03, f"{v5:.2f}", ha="center", fontsize=8)
    _save(fig, run_dir, "d4_vs_d5_ao_category")


def fig_a4_full_matrix_f1_by_detector() -> None:
    run_dir = _latest_run_dir("a4_full_matrix")
    if run_dir is None:
        print("skip a4: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    detectors = stats["detectors"]
    names = list(detectors.keys())
    short = [n.split("_")[0] for n in names]
    f1s = [detectors[n]["overall"]["f1"] for n in names]
    colors = [DETECTOR_COLORS.get(s, GRAY) for s in short]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    x = np.arange(len(short))
    bars = ax.bar(x, f1s, color=colors, width=0.55, edgecolor="white", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("F1 score")
    ax.set_ylim(0, 1.15)
    ax.set_title(f"Overall F1, full {stats['n_pairs']}-pair dataset\n(43 original + 10 AO)", fontsize=10)
    for bar, f1 in zip(bars, f1s):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03, f"{f1:.3f}", ha="center", fontsize=8.5
        )

    ax = axes[1]
    categories = sorted(stats["category_counts"].keys())
    d4_by_cat = [detectors["D4_structural_topology"]["by_category"][c]["f1"] for c in categories]
    d5_by_cat = [detectors["D5_with_aggregation"]["by_category"][c]["f1"] for c in categories]
    xc = np.arange(len(categories))
    w = 0.32
    ax.bar(xc - w / 2, d4_by_cat, width=w, label="D4", color=AMBER, edgecolor="white")
    ax.bar(xc + w / 2, d5_by_cat, width=w, label="D5", color=GREEN, edgecolor="white")
    ax.set_xticks(xc)
    ax.set_xticklabels(categories)
    ax.set_ylim(0, 1.25)
    ax.legend(fontsize=8.5)
    ax.set_title("D4 vs D5 F1 by category\n(AO is D4's designed blind spot)", fontsize=10)
    _save(fig, run_dir, "full_matrix_f1_by_detector")


def fig_a5_runtime_benchmark() -> None:
    run_dir = _latest_run_dir("a5_runtime_benchmark")
    if run_dir is None:
        print("skip a5: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    per_pair = stats["per_pair"]
    pair_names = list(per_pair.keys())
    d4_us = [per_pair[p]["D4_mean_us"] for p in pair_names]
    d5_us = [per_pair[p]["D5_mean_us"] for p in pair_names]

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    x = np.arange(len(pair_names))
    w = 0.32
    ax.bar(x - w / 2, d4_us, width=w, label="D4", color=AMBER, edgecolor="white")
    ax.bar(x + w / 2, d5_us, width=w, label="D5", color=GREEN, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels([p.replace("_", "\n") for p in pair_names])
    ax.set_ylabel("Mean latency (microseconds)")
    ax.legend(fontsize=8.5)
    ax.set_title(
        f"D4 vs D5 runtime, {stats['n_iter']} timed iterations each\n"
        f"(max regression: {stats['max_regression_pct_any_pair']:.1f}%, "
        f"{'not' if not stats['measurable_regression'] else ''} measurable)",
        fontsize=10,
    )
    for xi, (v4, v5) in enumerate(zip(d4_us, d5_us)):
        ax.text(xi - w / 2, v4, f"{v4:.2f}", ha="center", va="bottom", fontsize=8)
        ax.text(xi + w / 2, v5, f"{v5:.2f}", ha="center", va="bottom", fontsize=8)
    _save(fig, run_dir, "runtime_benchmark_d4_vs_d5")


def fig_b2_materialization_sweep() -> None:
    run_dir = _latest_run_dir("b2_materialization_sweep")
    if run_dir is None:
        print("skip b2: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    rows = stats["rows"]
    labels = [r["config_name"].replace("_", "\n") for r in rows]
    stock = [r["stock_leak_rate_mean"] for r in rows]
    stock_sd = [r["stock_leak_rate_sd"] for r in rows]
    closure = [r["closure_leak_rate_mean"] for r in rows]

    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    x = np.arange(len(labels))
    w = 0.32
    ax.bar(
        x - w / 2,
        stock,
        width=w,
        yerr=stock_sd,
        capsize=4,
        label="Stock gate (no closure)",
        color=RED,
        edgecolor="white",
        error_kw={"elinewidth": 1.2},
    )
    ax.bar(x + w / 2, closure, width=w, label="With materialization closure", color=GREEN, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.8)
    ax.set_ylabel("Leak rate (%)")
    ax.legend(fontsize=8.5)
    ax.set_title(
        "Materialization-boundary leak rate across 5 chain/topology configurations\n"
        "(30 seeds each, mean ± sd; config 1 reproduces PR #1's original 2-chain/3-dept case)",
        fontsize=9.5,
    )
    for xi, v in zip(x, stock):
        ax.text(xi - w / 2, v + 1, f"{v:.1f}%", ha="center", fontsize=7.5, fontweight="bold")
    _save(fig, run_dir, "materialization_sweep_leak_rate")


def fig_c2_storage_overhead() -> None:
    run_dir = _latest_run_dir("c2_storage_overhead")
    if run_dir is None:
        print("skip c2: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    fig, ax = plt.subplots(figsize=(6, 4.2))
    labels = ["Measured\n(JSON)", "Measured\n(pickle)", "Paper estimate\n(analytical, lo-hi)"]
    ratios = [stats["json_ratio_mean"], stats["pickle_ratio_mean"], None]
    est_lo, est_hi = (
        stats["paper_analytical_estimate"]["ratio_lo"],
        stats["paper_analytical_estimate"]["ratio_hi"],
    )

    x = np.arange(2)
    bars = ax.bar(x, ratios[:2], color=[BLUE, PURPLE], width=0.5, edgecolor="white")
    ax.axhspan(est_lo, est_hi, color=GRAY, alpha=0.18, label=f"paper estimate [{est_lo}x, {est_hi}x]")
    ax.set_xticks(x)
    ax.set_xticklabels(labels[:2])
    ax.set_ylabel("Storage overhead ratio (AMU / bare value)")
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title(
        f"Measured storage overhead vs. the paper's analytical estimate\n"
        f"n={stats['n_amus_measured']} AMUs -- refinement, not a correction (see docs/limitations.md)",
        fontsize=9.5,
    )
    for bar, v in zip(bars, ratios[:2]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            v + 0.08,
            f"{v:.2f}x",
            ha="center",
            fontsize=9,
            fontweight="bold",
        )
    _save(fig, run_dir, "storage_overhead_measured_vs_estimate")


def fig_c3_sql_bugfix_leak_rate() -> None:
    run_dir = _latest_run_dir("c3_sql_bugfix_demo")
    if run_dir is None:
        print("skip c3: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    fig, ax = plt.subplots(figsize=(5.5, 4.2))
    labels = ["Pre-fix\n(keep_unqualified=False)", "Post-fix\n(keep_unqualified=True)"]
    rates = [stats["pre_fix_leak_rate_of_exploitable_pct"], stats["post_fix_leak_rate_of_exploitable_pct"]]
    colors = [RED, GREEN]
    x = np.arange(2)
    bars = ax.bar(x, rates, color=colors, width=0.5, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Leak rate (% of exploitable queries)")
    ax.set_ylim(0, 105)
    ax.set_title(
        f"SQL unqualified-column leak rate, before vs. after PR #1's fix\n"
        f"({stats['n_queries_with_exploitable_sensitive_column']} exploitable queries, "
        f"Operations dept. requester)",
        fontsize=9.5,
    )
    for bar, v in zip(bars, rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2, v + 2, f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold"
        )
    _save(fig, run_dir, "sql_bugfix_leak_rate_before_after")


def fig_c1_conformance_status() -> None:
    run_dir = _latest_run_dir("c1_conformance", prefer_max_key="n_seeds")
    if run_dir is None:
        print("skip c1: no results found")
        return
    stats = _load(run_dir, "summary_stats.json")
    fig, ax = plt.subplots(figsize=(5.5, 2.6))
    ax.axis("off")
    ok = stats["passed"]
    color = GREEN if ok else RED
    ax.text(
        0.5,
        0.62,
        "PASSED" if ok else "FAILED",
        ha="center",
        va="center",
        fontsize=22,
        fontweight="bold",
        color=color,
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.18,
        f"{stats['n_seeds']} seeds -- {stats['n_mismatches']} mismatches -- {stats['elapsed_seconds']:.2f}s",
        ha="center",
        va="center",
        fontsize=10,
        color="#374151",
        transform=ax.transAxes,
    )
    ax.set_title("Group C1: amu-governance vs. root repo conformance", fontsize=10.5)
    _save(fig, run_dir, "conformance_status")


def main() -> int:
    print("Generating figures from the latest results/ runs...")
    fig_a1_detector_f1_original_dataset()
    fig_a2_d4_vs_d5_ao_category()
    fig_a4_full_matrix_f1_by_detector()
    fig_a5_runtime_benchmark()
    fig_b2_materialization_sweep()
    fig_c1_conformance_status()
    fig_c2_storage_overhead()
    fig_c3_sql_bugfix_leak_rate()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
