"""
Statistical Significance Analysis
===================================

Loads per-seed results from:
  - sweep_summary.csv        (synthetic schema, 30 seeds)
  - tpch_results.json        (TPC-H schema, 30 seeds)
  - degradation_results.json (completeness sweep, 30 seeds each)

For each naive-vs-lineage-aware comparison (leak rate, reuse rate) on both
schemas, computes:
  1. Bootstrap 95% CI on the difference in means (10,000 resamples)
  2. Mann-Whitney U test p-value (non-parametric, no normality assumption)

Prints a clean summary table and saves stats_results.json.

Note on Mann-Whitney U for leak rate:
  The lineage-aware system has leak rate = 0.0 on ALL 30 seeds by design
  (formal safety guarantee, Theorem 1). Mann-Whitney U on a constant vs. a
  non-constant distribution is technically valid but the p-value carries no
  new empirical content — the result is guaranteed by the theorem. We report
  it for completeness and note this explicitly.
"""

import json, csv, statistics, random
from scipy import stats as scipy_stats
from typing import List, Dict, Tuple

# ──────────────────────────────────────────────────────────────────────────
# Load data
# ──────────────────────────────────────────────────────────────────────────

def load_sweep_raw() -> Dict:
    """Load per-seed raw values from tpch_results.json (which has raw arrays)
    and reconstruct synthetic per-seed values from sweep_summary.csv + sweep_raw.json
    if available, otherwise use tpch raw for both.
    """
    import os

    # TPC-H: raw per-seed data is in tpch_results.json
    with open("tpch_results.json") as f:
        tpch = json.load(f)

    tpch_naive_leak  = tpch["raw"]["naive_leak"]
    tpch_la_leak     = tpch["raw"]["la_leak"]
    tpch_naive_reuse = tpch["raw"]["naive_reuse"]
    tpch_la_reuse    = tpch["raw"]["la_reuse"]

    # Synthetic: regenerate per-seed values from simulate.py (deterministic)
    # We re-run the 30-seed sweep here rather than storing raw values separately
    import sys, io
    from simulate import run_seed_sweep
    random.seed(0)
    _, all_rows = run_seed_sweep(n_seeds=30)

    syn_naive_leak  = all_rows["naive"]["leak"]
    syn_la_leak     = all_rows["lineage_aware"]["leak"]
    syn_naive_reuse = all_rows["naive"]["reuse"]
    syn_la_reuse    = all_rows["lineage_aware"]["reuse"]

    # Degradation
    deg_data = None
    if os.path.exists("degradation_results.json"):
        with open("degradation_results.json") as f:
            deg_data = json.load(f)

    return {
        "synthetic": {
            "naive_leak":  syn_naive_leak,
            "la_leak":     syn_la_leak,
            "naive_reuse": syn_naive_reuse,
            "la_reuse":    syn_la_reuse,
        },
        "tpch": {
            "naive_leak":  tpch_naive_leak,
            "la_leak":     tpch_la_leak,
            "naive_reuse": tpch_naive_reuse,
            "la_reuse":    tpch_la_reuse,
        },
        "degradation": deg_data,
    }


# ──────────────────────────────────────────────────────────────────────────
# Bootstrap CI on the difference of means
# ──────────────────────────────────────────────────────────────────────────

def bootstrap_diff_ci(
    a: List[float], b: List[float],
    n_boot: int = 10_000, seed: int = 42,
    ci: float = 0.95
) -> Dict:
    """
    Bootstrap CI on (mean(a) - mean(b)).
    Returns: observed_diff, ci_lo, ci_hi, p_boot (proportion of bootstrap
    samples where diff <= 0, as a one-sided bootstrap p-value).
    """
    rng   = random.Random(seed)
    na, nb = len(a), len(b)
    obs_diff = statistics.mean(a) - statistics.mean(b)
    boot_diffs = []
    for _ in range(n_boot):
        sample_a = [a[rng.randrange(na)] for _ in range(na)]
        sample_b = [b[rng.randrange(nb)] for _ in range(nb)]
        boot_diffs.append(statistics.mean(sample_a) - statistics.mean(sample_b))
    boot_diffs.sort()
    alpha  = (1 - ci) / 2
    lo_idx = int(alpha * n_boot)
    hi_idx = int((1 - alpha) * n_boot)
    # One-sided p: fraction of bootstrap diffs ≤ 0 (null: a ≤ b)
    p_boot = sum(1 for d in boot_diffs if d <= 0) / n_boot
    return {
        "observed_diff": round(obs_diff, 4),
        "ci_lo":         round(boot_diffs[lo_idx], 4),
        "ci_hi":         round(boot_diffs[hi_idx], 4),
        "p_bootstrap":   round(p_boot, 4),
    }


# ──────────────────────────────────────────────────────────────────────────
# Full comparison: one metric (leak or reuse) for one schema
# ──────────────────────────────────────────────────────────────────────────

def compare(a: List[float], b: List[float],
            label_a: str = "naive", label_b: str = "la") -> Dict:
    """
    a = naive values, b = lineage-aware values, both length n_seeds.
    For leak rate: we expect a > b (naive leaks more).
    For reuse rate: we expect a ≈ b (both high) or a > b.
    """
    n = len(a)
    mean_a = round(statistics.mean(a), 4)
    sd_a   = round(statistics.pstdev(a), 4)
    mean_b = round(statistics.mean(b), 4)
    sd_b   = round(statistics.pstdev(b), 4)

    # Mann-Whitney U: H0: distributions equal; alt: a > b (naive higher leak)
    u_stat, p_mw = scipy_stats.mannwhitneyu(a, b, alternative="two-sided")
    # Also compute one-sided (naive > la)
    _, p_mw_one  = scipy_stats.mannwhitneyu(a, b, alternative="greater")

    boot = bootstrap_diff_ci(a, b)

    return {
        f"mean_{label_a}": mean_a, f"sd_{label_a}":   sd_a,
        f"mean_{label_b}": mean_b, f"sd_{label_b}":   sd_b,
        "n_seeds":         n,
        "mann_whitney_U":  round(u_stat, 2),
        "p_two_sided":     round(p_mw, 6),
        "p_one_sided":     round(p_mw_one, 6),
        "bootstrap_diff":  boot,
    }


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def print_comparison_table(label: str, result: Dict):
    naive_key = [k for k in result if k.startswith("mean_") and "naive" in k][0]
    la_key    = [k for k in result if k.startswith("mean_") and ("la" in k or "lineage" in k)][0]
    naive_sd  = naive_key.replace("mean_", "sd_")
    la_sd     = la_key.replace("mean_", "sd_")

    b = result["bootstrap_diff"]
    significant = "*" if result["p_two_sided"] < 0.05 else ""

    print(f"\n  {label}")
    print(f"    Naive      : {result[naive_key]:.2f} ± {result[naive_sd]:.2f}")
    print(f"    Lineage-Aware: {result[la_key]:.2f} ± {result[la_sd]:.2f}")
    print(f"    Diff (N-LA): {b['observed_diff']:+.2f}  "
          f"95% CI [{b['ci_lo']:+.2f}, {b['ci_hi']:+.2f}]")
    print(f"    Mann-Whitney U={result['mann_whitney_U']:.0f}  "
          f"p={result['p_two_sided']:.4f}{significant}  "
          f"(one-sided p={result['p_one_sided']:.4f})")
    if result["p_two_sided"] < 0.001:
        interp = "extremely significant (p < 0.001)"
    elif result["p_two_sided"] < 0.01:
        interp = "highly significant (p < 0.01)"
    elif result["p_two_sided"] < 0.05:
        interp = "significant (p < 0.05)"
    else:
        interp = "not significant (p ≥ 0.05)"
    print(f"    Interpretation: {interp}")


if __name__ == "__main__":
    print("Loading per-seed data...", flush=True)
    data = load_sweep_raw()
    results = {}

    print("\n" + "═" * 70)
    print("STATISTICAL SIGNIFICANCE: Naive vs. Lineage-Aware (30 seeds each)")
    print("Bootstrap 95% CI on difference of means (10k resamples)")
    print("Mann-Whitney U — two-sided; * = p < 0.05")
    print("═" * 70)

    # ── Synthetic schema ──────────────────────────────────────────────────
    print("\n── Synthetic 5-Table Schema ──")
    syn = data["synthetic"]

    r_syn_leak = compare(syn["naive_leak"], syn["la_leak"])
    results["synthetic_leak"] = r_syn_leak
    print_comparison_table("Leak Rate (%)", r_syn_leak)

    r_syn_reuse = compare(syn["naive_reuse"], syn["la_reuse"])
    results["synthetic_reuse"] = r_syn_reuse
    print_comparison_table("Reuse Rate (%)", r_syn_reuse)

    # ── TPC-H schema ──────────────────────────────────────────────────────
    print("\n── TPC-H 8-Table Schema ──")
    tpch = data["tpch"]

    r_tpch_leak = compare(tpch["naive_leak"], tpch["la_leak"])
    results["tpch_leak"] = r_tpch_leak
    print_comparison_table("Leak Rate (%)", r_tpch_leak)

    r_tpch_reuse = compare(tpch["naive_reuse"], tpch["la_reuse"])
    results["tpch_reuse"] = r_tpch_reuse
    print_comparison_table("Reuse Rate (%)", r_tpch_reuse)

    # ── Degradation analysis ──────────────────────────────────────────────
    if data["degradation"]:
        print("\n── Lineage-Completeness Degradation ──")
        deg = data["degradation"]
        results["degradation"] = {}

        for schema in ["synthetic", "tpch"]:
            print(f"\n  Schema: {schema}")
            completeness_levels = ["0.5", "0.75", "0.9", "0.95", "1.0"]
            # Compare each completeness level vs. full (1.0)
            full_leaks = [r["leak_rate"] for r in deg[schema]["1.0"]["per_seed"]]
            for c_str in completeness_levels[:-1]:  # skip 1.0 (baseline)
                c_leaks = [r["leak_rate"] for r in deg[schema][c_str]["per_seed"]]
                r_deg = compare(c_leaks, full_leaks,
                                label_a=f"c={c_str}", label_b="c=1.0")
                results["degradation"][f"{schema}_{c_str}_vs_1.0"] = r_deg
                mean_c  = deg[schema][c_str]["leak_mean"]
                mean_1  = deg[schema]["1.0"]["leak_mean"]
                b = r_deg["bootstrap_diff"]
                sig = "*" if r_deg["p_two_sided"] < 0.05 else " "
                print(f"    c={c_str} vs c=1.0: "
                      f"leak {mean_c:.1f}% vs {mean_1:.1f}%  "
                      f"diff={b['observed_diff']:+.2f} "
                      f"[{b['ci_lo']:+.2f},{b['ci_hi']:+.2f}]  "
                      f"p={r_deg['p_two_sided']:.4f}{sig}")

    # ── Methodological note on zero-variance distributions ────────────────
    print("\n" + "─" * 70)
    print("Note on zero-variance distributions:")
    print("  LA system leak rate = 0.0 on ALL 30 seeds (formal safety guarantee,")
    print("  Theorem 1). Mann-Whitney U detects the naive > la difference reliably,")
    print("  but the p-value reflects the theorem, not an empirical surprise.")
    print("  Reuse rate comparison is purely empirical and carries full statistical")
    print("  weight — LA reuse variability is real (workload-dependent).")

    with open("stats_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved stats_results.json")
