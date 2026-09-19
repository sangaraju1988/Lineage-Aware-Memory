#!/usr/bin/env python3
"""
Group A7 (peer-review revision): ablation asking whether the aggregation-
operator blind spot could have been closed by *just* adding aggregation_fn
to the definition hash's payload (amu_ext.aggregation.definition_hash_with_aggregation),
without D5's separate, explicit structural-gate-plus-topology-plus-
aggregation-equality design.

Defines one ablation detector, D1-ext ("extended-hash exact match"): conflict
iff definition_hash_with_aggregation(a) != definition_hash_with_aggregation(b).
This is D1 (exact hash) unchanged in its *comparison logic* -- flag a
conflict iff the hash differs -- with only the hash's *payload* extended to
include aggregation_fn. It is deliberately NOT D5: D1-ext has no separate
structural gate and no separate operator-topology comparison; it is a single
hash-equality test over a four-field payload.

Evaluated against the same 68-pair (43 + AO-25) combined dataset as
run_a6_ao25_eval.py, reporting overall and per-category precision/recall/F1
so the ablation's actual failure mode -- does it inherit D1's TV
false-positive problem even though it fixes AO recall? -- is visible
per-category, not just as one aggregate number.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.aggregation import definition_hash_with_aggregation  # noqa: E402
from amu_ext.detectors import DETECTORS, Pair, load_pairs  # noqa: E402
from amu_ext.stats import precision_recall_f1  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def d1_ext_hash(pair: Pair) -> bool:
    """D1-ext: exact-match comparison over the aggregation-extended hash.

    Same comparison logic as D1 (flag iff hash differs); only the hash
    payload changed. No structural gate, no topology comparison, no
    dedicated aggregation-equality check -- this isolates the effect of
    extending the hash alone.
    """
    ha = definition_hash_with_aggregation(pair.a.tables, pair.a.columns, pair.a.filter_logic, pair.a.aggregation_fn)
    hb = definition_hash_with_aggregation(pair.b.tables, pair.b.columns, pair.b.filter_logic, pair.b.aggregation_fn)
    return ha != hb


def load_combined_dataset_ao25() -> list[Pair]:
    original = load_pairs(DATA_DIR / "conflict_dataset_43.json")
    ao_10 = load_pairs(DATA_DIR / "conflict_dataset_ao_10.json")
    ao_15_new = load_pairs(DATA_DIR / "conflict_dataset_ao_15_new.json")
    return original + ao_10 + ao_15_new


def main() -> int:
    run_dir = make_run_dir("a7_hash_ablation")
    logger = setup_logging(run_dir, "run_a7_hash_ablation")

    pairs = load_combined_dataset_ao25()
    categories = sorted({p.category for p in pairs})
    gt = [p.is_conflict for p in pairs]

    detectors = {
        "D1_exact_hash": DETECTORS["D1_exact_hash"],
        "D1ext_hash_with_aggregation": d1_ext_hash,
        "D4_structural_topology": DETECTORS["D4_structural_topology"],
        "D5_with_aggregation": DETECTORS["D5_with_aggregation"],
    }

    per_detector_summary: dict[str, dict] = {}
    for name, fn in detectors.items():
        preds = [fn(p) for p in pairs]
        overall = precision_recall_f1(preds, gt)
        by_category = {}
        for cat in categories:
            idx = [i for i, p in enumerate(pairs) if p.category == cat]
            cat_preds = [preds[i] for i in idx]
            cat_gt = [gt[i] for i in idx]
            by_category[cat] = {**precision_recall_f1(cat_preds, cat_gt).as_dict(), "n": len(idx)}
        logger.info(
            "%-28s overall P=%.3f R=%.3f F1=%.3f", name, overall.precision, overall.recall, overall.f1
        )
        for cat in categories:
            c = by_category[cat]
            logger.info("  %-4s n=%2d P=%.3f R=%.3f F1=%.3f", cat, c["n"], c["precision"], c["recall"], c["f1"])
        per_detector_summary[name] = {"overall": overall.as_dict(), "by_category": by_category}

    write_json(
        run_dir / "summary_stats.json",
        {
            "n_pairs": len(pairs),
            "category_counts": {cat: sum(1 for p in pairs if p.category == cat) for cat in categories},
            "detectors": per_detector_summary,
            "note": (
                "D1ext_hash_with_aggregation isolates the effect of extending ONLY the hash "
                "payload (no structural gate, no topology comparison, no dedicated "
                "aggregation-equality check) -- contrast with D5, which adds the equality "
                "check on top of D4's structural-gate-plus-topology design."
            ),
        },
    )
    write_manifest(run_dir, seeds=[42], command="python experiments/run_a7_hash_ablation.py")

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
