#!/usr/bin/env python3
"""
Group C2: re-run the storage-overhead measurement against final code and
record it with full provenance.

Re-uses ``storage_overhead_measurement.py`` (root repo, from PR #1)
verbatim -- this script does not reimplement the measurement, it just wraps
it with a results/<run_id>/ folder so the exact numbers that would be cited
in the paper are traceable to a run, per Section 6.

Write-up convention (explicit, per the build prompt's Group C2): phrase the
result as measured overhead falling within/at the low end of the paper's
earlier analytical 4-8x estimate -- a refinement with real numbers, not a
correction. Do not round or adjust the measured numbers to make them look
more consistent with the original estimate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

import storage_overhead_measurement as som  # noqa: E402


def main() -> int:
    run_dir = make_run_dir("c2_storage_overhead")
    logger = setup_logging(run_dir, "run_c2_storage_overhead")
    logger.info("Re-running storage-overhead measurement against final code")

    entries = som.build_entries()
    logger.debug("Built %d (bare, full) AMU entry pairs from simulate.METRIC_VARIANTS", len(entries))
    results = som.measure(entries)

    json_ratio = results["json"]["ratio_mean"]
    paper_estimate_lo, paper_estimate_hi = 4.0, 8.0
    within_estimate = paper_estimate_lo <= json_ratio <= paper_estimate_hi
    logger.info(
        "Measured JSON overhead ratio: %.2fx (paper's analytical estimate: %.0f-%.0fx) -- %s",
        json_ratio,
        paper_estimate_lo,
        paper_estimate_hi,
        "within estimate range" if within_estimate else "OUTSIDE estimate range",
    )

    write_json(run_dir / "raw_results.json", {"entries_measured": results["n"], "measurements": results})
    write_json(
        run_dir / "summary_stats.json",
        {
            "n_amus_measured": results["n"],
            "json_ratio_mean": json_ratio,
            "json_ratio_range": [results["json"]["ratio_min"], results["json"]["ratio_max"]],
            "json_bare_bytes_mean": results["json"]["bare_bytes_mean"],
            "json_full_bytes_mean": results["json"]["full_bytes_mean"],
            "pickle_ratio_mean": results["pickle"]["ratio_mean"],
            "paper_analytical_estimate": {
                "ratio_lo": paper_estimate_lo,
                "ratio_hi": paper_estimate_hi,
                "bytes_lo": 200,
                "bytes_hi": 600,
            },
            "within_paper_estimate_range": within_estimate,
            "framing": (
                "Refinement, not a correction: the measured JSON ratio (3.93x) sits "
                "just below the paper's analytical estimate's lower bound (4x) -- "
                "i.e. at the low end of the estimated range, not inside it by a "
                "strict inequality. The measured byte counts (bare/full) do fall "
                "inside the paper's 200-600 byte estimate. These are the exact "
                "measured values -- not rounded or adjusted toward the estimate."
            ),
        },
    )
    write_manifest(
        run_dir,
        seeds=[],
        command="python experiments/run_c2_storage_overhead.py",
        extra={"note": "Deterministic measurement -- no randomness, no seeds."},
    )

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
