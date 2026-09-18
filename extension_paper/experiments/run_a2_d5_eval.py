#!/usr/bin/env python3
"""
Group A2: evaluate D5 (D4 + aggregation-equality check) against the
Aggregation-Operator (AO) dataset, D4 vs D5 side by side.

Demonstrates the aggregation-operator blind spot directly: D4 cannot see
``aggregation_fn`` at all (by construction -- it is not one of D4's
inputs), so it necessarily under-performs on the AO category; D5 adds the
one check needed to close it. The combined-dataset McNemar significance
test for D4 vs D5 specifically is Group A4's job; this script isolates the
AO category on its own, since that is where the two detectors provably
diverge.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.detectors import d4_structural_topology, d5_with_aggregation, load_pairs  # noqa: E402
from amu_ext.stats import bootstrap_ci, mcnemar_test, precision_recall_f1  # noqa: E402

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "conflict_dataset_ao_10.json"


def main() -> int:
    run_dir = make_run_dir("a2_d5_eval")
    logger = setup_logging(run_dir, "run_a2_d5_eval")

    pairs = load_pairs(DATA_PATH)
    logger.info("Loaded %d AO pairs from %s", len(pairs), DATA_PATH.name)
    gt = [p.is_conflict for p in pairs]

    d4_preds = [d4_structural_topology(p) for p in pairs]
    d5_preds = [d5_with_aggregation(p) for p in pairs]

    d4_prf = precision_recall_f1(d4_preds, gt)
    d5_prf = precision_recall_f1(d5_preds, gt)

    items = list(zip(d5_preds, gt))

    def _f1_stat(resample):
        return precision_recall_f1([x[0] for x in resample], [x[1] for x in resample]).f1

    d5_ci = bootstrap_ci(items, _f1_stat, n_resamples=10_000, seed=42)

    mcnemar = mcnemar_test(d4_preds, d5_preds)

    logger.info(
        "D4 on AO category: P=%.3f R=%.3f F1=%.3f (blind spot expected)",
        d4_prf.precision,
        d4_prf.recall,
        d4_prf.f1,
    )
    logger.info(
        "D5 on AO category: P=%.3f R=%.3f F1=%.3f [%.3f, %.3f]",
        d5_prf.precision,
        d5_prf.recall,
        d5_prf.f1,
        d5_ci.ci_lo,
        d5_ci.ci_hi,
    )
    logger.info(
        "McNemar D4 vs D5 on AO: n_discordant=%d statistic=%.3f p=%.6f",
        mcnemar.n_discordant,
        mcnemar.statistic,
        mcnemar.p_value,
    )

    for p, d4p, d5p, g in zip(pairs, d4_preds, d5_preds, gt):
        logger.debug("%-55s gt=%-5s D4=%-5s D5=%-5s", p.name[:55], g, d4p, d5p)

    write_json(
        run_dir / "raw_results.json",
        {
            "pair_names": [p.name for p in pairs],
            "ground_truth": gt,
            "d4_predictions": d4_preds,
            "d5_predictions": d5_preds,
        },
    )
    write_json(
        run_dir / "summary_stats.json",
        {
            "n_pairs": len(pairs),
            "D4": {
                **d4_prf.as_dict(),
                "note": "D4 cannot see aggregation_fn -- this is the blind spot Group A2/A3 demonstrate",
            },
            "D5": {**d5_prf.as_dict(), "f1_bootstrap_ci": d5_ci.as_dict()},
            "mcnemar_D4_vs_D5": mcnemar.as_dict(),
        },
    )
    write_manifest(run_dir, seeds=[42], command="python experiments/run_a2_d5_eval.py")

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
