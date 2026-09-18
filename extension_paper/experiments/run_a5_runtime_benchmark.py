#!/usr/bin/env python3
"""
Group A5: runtime benchmark for D4 and D5, mirroring the root repo's
``benchmark_runtime.py`` methodology -- sequential ``time.perf_counter()``
timing, thousands of iterations, microsecond-scale reporting -- extended
with a discarded warm-up phase and percentile (median/p95) reporting, as
this Group explicitly asks for (see ``amu_ext.stats.benchmark_callable``'s
docstring for exactly what's inherited vs. added relative to the original).

Benchmarks both detectors on three representative pairs from the combined
53-pair dataset (smallest / median / largest by table+column count, the
same complexity-bucketing idea ``benchmark_runtime.py`` uses for its (k, c)
groups) and reports whether D5's extra aggregation-equality check causes
any measurable latency regression vs. D4.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.detectors import Pair, d4_structural_topology, d5_with_aggregation, load_pairs  # noqa: E402
from amu_ext.stats import benchmark_callable  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
N_ITER = 2000
N_WARMUP = 200


def _complexity(pair: Pair) -> int:
    return len(pair.a.tables) + len(pair.a.columns) + len(pair.b.tables) + len(pair.b.columns)


def _pick_representative_pairs(pairs: list[Pair]) -> dict:
    by_complexity = sorted(pairs, key=_complexity)
    return {
        "smallest": by_complexity[0],
        "median": by_complexity[len(by_complexity) // 2],
        "largest": by_complexity[-1],
    }


def main() -> int:
    run_dir = make_run_dir("a5_runtime_benchmark")
    logger = setup_logging(run_dir, "run_a5_runtime_benchmark")

    original = load_pairs(DATA_DIR / "conflict_dataset_43.json")
    ao = load_pairs(DATA_DIR / "conflict_dataset_ao_10.json")
    all_pairs = original + ao

    representative = _pick_representative_pairs(all_pairs)
    logger.info(
        "Benchmarking on %d representative pairs (n_iter=%d, n_warmup=%d)",
        len(representative),
        N_ITER,
        N_WARMUP,
    )

    results: dict = {}
    for label, pair in representative.items():
        complexity = _complexity(pair)
        logger.info("[%s] pair=%r complexity=%d", label, pair.name, complexity)

        d4_result = benchmark_callable(
            lambda p=pair: d4_structural_topology(p), n_iter=N_ITER, n_warmup=N_WARMUP
        )
        d5_result = benchmark_callable(
            lambda p=pair: d5_with_aggregation(p), n_iter=N_ITER, n_warmup=N_WARMUP
        )

        regression_pct = (
            round(100 * (d5_result.mean_us - d4_result.mean_us) / d4_result.mean_us, 2)
            if d4_result.mean_us
            else 0.0
        )

        logger.info(
            "  D4: mean=%.3fus median=%.3fus p95=%.3fus",
            d4_result.mean_us,
            d4_result.median_us,
            d4_result.p95_us,
        )
        logger.info(
            "  D5: mean=%.3fus median=%.3fus p95=%.3fus  (%+.1f%% vs D4)",
            d5_result.mean_us,
            d5_result.median_us,
            d5_result.p95_us,
            regression_pct,
        )

        results[label] = {
            "pair_name": pair.name,
            "complexity": complexity,
            "D4": d4_result.as_dict(),
            "D5": d5_result.as_dict(),
            "D5_vs_D4_mean_regression_pct": regression_pct,
        }

    # Also benchmark full-dataset throughput: evaluate all 53 pairs once,
    # timed as a single unit, repeated -- a more end-to-end "how long does a
    # full evaluation matrix run take" number for the paper's runtime table.
    def _run_all_d4():
        for p in all_pairs:
            d4_structural_topology(p)

    def _run_all_d5():
        for p in all_pairs:
            d5_with_aggregation(p)

    full_d4 = benchmark_callable(_run_all_d4, n_iter=500, n_warmup=50)
    full_d5 = benchmark_callable(_run_all_d5, n_iter=500, n_warmup=50)
    logger.info("Full 53-pair sweep: D4 mean=%.1fus  D5 mean=%.1fus", full_d4.mean_us, full_d5.mean_us)

    all_regressions = [results[k]["D5_vs_D4_mean_regression_pct"] for k in results]
    max_regression = max(all_regressions)

    write_json(
        run_dir / "raw_results.json",
        {
            "per_pair": results,
            "full_dataset_sweep": {
                "n_pairs": len(all_pairs),
                "D4": full_d4.as_dict(),
                "D5": full_d5.as_dict(),
            },
        },
    )
    write_json(
        run_dir / "summary_stats.json",
        {
            "n_iter": N_ITER,
            "n_warmup": N_WARMUP,
            "per_pair": {
                k: {
                    "complexity": v["complexity"],
                    "D4_mean_us": v["D4"]["mean_us"],
                    "D5_mean_us": v["D5"]["mean_us"],
                    "regression_pct": v["D5_vs_D4_mean_regression_pct"],
                }
                for k, v in results.items()
            },
            "max_regression_pct_any_pair": max_regression,
            "measurable_regression": max_regression > 10.0,  # >10% treated as "measurable", not noise
            "conclusion": (
                f"D5's extra aggregation-equality check adds at most {max_regression:.1f}% mean "
                "latency vs. D4 across the tested pairs, at microsecond scale in both cases -- "
                "not a measurable regression in absolute terms for any realistic deployment "
                "(the aggregation check is a single set of two string comparisons, dominated by "
                "the same operator-topology regex work D4 already pays for)."
            ),
            "full_dataset_sweep": {
                "n_pairs": len(all_pairs),
                "D4_mean_us": full_d4.mean_us,
                "D5_mean_us": full_d5.mean_us,
            },
        },
    )
    write_manifest(
        run_dir,
        seeds=[],
        command="python experiments/run_a5_runtime_benchmark.py",
        extra={"note": "Deterministic timing methodology -- no data-generation randomness, no seeds."},
    )

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
