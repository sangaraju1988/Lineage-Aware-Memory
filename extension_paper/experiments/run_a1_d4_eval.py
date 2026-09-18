#!/usr/bin/env python3
"""
Group A1: evaluate D4 (structural gate + filter-logic operator-topology
diff) against the original 43-pair dataset, D1-D4 side by side.

D4 is the detector the original paper proposed but never evaluated. This
script is that evaluation: precision/recall/F1 per detector, overall and
per-category, with bootstrap 95% CIs -- confirming D4 achieves what D3
cannot (catching the LO category) without reopening what D1 over-flags (the
TV category). The combined 53-pair (with AO) matrix, and the D4-vs-D5
McNemar comparison, are Group A4's job (``run_a4_full_matrix.py``); this
script is scoped to D1-D4 on the original four categories, matching how
the build prompt separates A1 from A4.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.detectors import (  # noqa: E402
    d1_exact,
    d2_jaccard,
    d3_column_graph,
    d4_structural_topology,
    load_pairs,
)
from amu_ext.stats import bootstrap_ci, precision_recall_f1  # noqa: E402

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "conflict_dataset_43.json"

DETECTORS = {
    "D1_exact_hash": d1_exact,
    "D2_jaccard": d2_jaccard,
    "D3_column_graph": d3_column_graph,
    "D4_structural_topology": d4_structural_topology,
}


def main() -> int:
    run_dir = make_run_dir("a1_d4_eval")
    logger = setup_logging(run_dir, "run_a1_d4_eval")

    pairs = load_pairs(DATA_PATH)
    logger.info("Loaded %d pairs from %s", len(pairs), DATA_PATH.name)
    gt = [p.is_conflict for p in pairs]

    per_detector = {}
    for name, fn in DETECTORS.items():
        preds = [fn(p) for p in pairs]
        prf = precision_recall_f1(preds, gt)

        # Bootstrap CI resamples (pred, gt) pairs jointly.
        items = list(zip(preds, gt))

        def _f1_stat(resample, _fn=fn):
            r_preds = [x[0] for x in resample]
            r_gt = [x[1] for x in resample]
            return precision_recall_f1(r_preds, r_gt).f1

        ci = bootstrap_ci(items, _f1_stat, n_resamples=10_000, seed=42)

        by_category: dict = {}
        for cat in sorted({p.category for p in pairs}):
            cat_pairs = [(fn(p), p.is_conflict) for p in pairs if p.category == cat]
            cat_prf = precision_recall_f1([x[0] for x in cat_pairs], [x[1] for x in cat_pairs])
            by_category[cat] = cat_prf.as_dict()

        logger.info(
            "%-25s P=%.3f R=%.3f F1=%.3f [%.3f, %.3f]",
            name,
            prf.precision,
            prf.recall,
            prf.f1,
            ci.ci_lo,
            ci.ci_hi,
        )
        per_detector[name] = {**prf.as_dict(), "f1_bootstrap_ci": ci.as_dict(), "by_category": by_category}

    write_json(
        run_dir / "raw_results.json",
        {
            "n_pairs": len(pairs),
            "categories": sorted({p.category for p in pairs}),
            "predictions": {name: [fn(p) for p in pairs] for name, fn in DETECTORS.items()},
            "ground_truth": gt,
            "pair_names": [p.name for p in pairs],
            "pair_categories": [p.category for p in pairs],
        },
    )
    write_json(run_dir / "summary_stats.json", {"detectors": per_detector})
    write_manifest(run_dir, seeds=[42], command="python experiments/run_a1_d4_eval.py")

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
