#!/usr/bin/env python3
"""
Group C1: re-run the package-conformance check against the final merged
branch and record it with full provenance.

This is the "slow"/full-statistical-power counterpart to
``tests/integration/test_conformance.py`` (which runs the same check as
part of every CI build, but doesn't write a results artifact). Running this
script is what Section 6 ("results package") requires: a
``results/c1_conformance/<run_id>/`` folder with raw results, summary
stats, and a run manifest -- not just "the test suite is green".
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

import test_package_conformance as conformance  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-seeds",
        type=int,
        default=conformance.N_SEEDS,
        help="number of seeds to check (default: the root script's N_SEEDS)",
    )
    args = parser.parse_args(argv)

    run_dir = make_run_dir("c1_conformance")
    logger = setup_logging(run_dir, "run_c1_conformance")
    logger.info("Starting Group C1 conformance re-run: n_seeds=%d", args.n_seeds)

    new_variants = conformance._as_new_variants()
    mismatches = []
    per_seed = []
    t0 = time.perf_counter()

    for seed in range(args.n_seeds):
        import random

        random.seed(seed)
        events = conformance.generate_events()
        old_stats, old_flagged = conformance.run_old(events)

        random.seed(seed)
        events2 = conformance.generate_events()
        assert events == events2
        new_stats, new_flagged = conformance.run_new(events2, new_variants)

        seed_mismatches = []
        if old_flagged != new_flagged:
            seed_mismatches.append(("flagged_conflicts", old_flagged, new_flagged))
        for name in old_stats:
            for key in old_stats[name]:
                if old_stats[name][key] != new_stats[name][key]:
                    seed_mismatches.append((f"{name}.{key}", old_stats[name][key], new_stats[name][key]))

        logger.debug("seed=%d old=%s new=%s mismatches=%s", seed, old_stats, new_stats, seed_mismatches)
        if seed_mismatches:
            mismatches.extend((seed, *m) for m in seed_mismatches)
        per_seed.append(
            {
                "seed": seed,
                "old_stats": old_stats,
                "new_stats": new_stats,
                "old_flagged": old_flagged,
                "new_flagged": new_flagged,
                "mismatches": seed_mismatches,
            }
        )

    elapsed = time.perf_counter() - t0
    passed = not mismatches
    logger.info(
        "Conformance %s across %d seeds (%d mismatches, %.2fs)",
        "PASSED" if passed else "FAILED",
        args.n_seeds,
        len(mismatches),
        elapsed,
    )

    write_json(run_dir / "raw_results.json", {"per_seed": per_seed})
    write_json(
        run_dir / "summary_stats.json",
        {
            "passed": passed,
            "n_seeds": args.n_seeds,
            "n_mismatches": len(mismatches),
            "mismatches": mismatches[:50],
            "elapsed_seconds": round(elapsed, 3),
            "note": (
                "This check compares the amu_governance package against the root "
                "repo's model.py/systems.py -- the frozen artifact behind the "
                "published paper's numbers -- on the identical seeded workload "
                "simulate.py uses. A failure here is a real finding to report, "
                "not something to silently reconcile (see test_package_conformance.py)."
            ),
        },
    )
    write_manifest(run_dir, seeds=range(args.n_seeds), command="python experiments/run_c1_conformance.py")

    print(f"Wrote results to {run_dir}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
