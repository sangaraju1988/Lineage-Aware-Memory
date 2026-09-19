#!/usr/bin/env python3
"""
Group A6 (peer-review revision): re-run the full detector matrix with the
AO category expanded from 10 to 25 pairs (data/conflict_dataset_ao_10.json
+ data/conflict_dataset_ao_15_new.json), giving a 68-pair, five-category
combined dataset (43 original + 25 AO). Reports the same per-detector,
per-category precision/recall/F1 (with bootstrap 95% CIs) as
run_a4_full_matrix.py, plus the paired McNemar test comparing D4 vs D5
restricted to the now-25-pair AO category, so the original 10-pair result
can be checked for stability under a larger, more domain-diverse sample
rather than superseded silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.detectors import DETECTORS, Pair, load_pairs  # noqa: E402
from amu_ext.stats import bootstrap_ci, mcnemar_test, precision_recall_f1  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_combined_dataset_ao25() -> list[Pair]:
    original = load_pairs(DATA_DIR / "conflict_dataset_43.json")
    ao_10 = load_pairs(DATA_DIR / "conflict_dataset_ao_10.json")
    ao_15_new = load_pairs(DATA_DIR / "conflict_dataset_ao_15_new.json")
    return original + ao_10 + ao_15_new


def main() -> int:
    run_dir = make_run_dir("a6_ao25_eval")
    logger = setup_logging(run_dir, "run_a6_ao25_eval")

    pairs = load_combined_dataset_ao25()
    categories = sorted({p.category for p in pairs})
    logger.info("Combined AO-25 dataset: %d pairs, categories=%s", len(pairs), categories)
    assert len(pairs) == 68, f"expected 68 pairs (43 + 10 + 15), got {len(pairs)}"
    ao_count = sum(1 for p in pairs if p.category == "AO")
    assert ao_count == 25, f"expected 25 AO pairs, got {ao_count}"

    gt = [p.is_conflict for p in pairs]
    all_predictions: dict[str, list[bool]] = {}
    per_detector_summary: dict[str, dict] = {}

    for name, fn in DETECTORS.items():
        preds = [fn(p) for p in pairs]
        all_predictions[name] = preds
        overall = precision_recall_f1(preds, gt)

        items = list(zip(preds, gt))

        def _f1_stat(resample):
            return precision_recall_f1([x[0] for x in resample], [x[1] for x in resample]).f1

        ci = bootstrap_ci(items, _f1_stat, n_resamples=10_000, seed=42)

        by_category = {}
        for cat in categories:
            idx = [i for i, p in enumerate(pairs) if p.category == cat]
            cat_preds = [preds[i] for i in idx]
            cat_gt = [gt[i] for i in idx]
            by_category[cat] = {**precision_recall_f1(cat_preds, cat_gt).as_dict(), "n": len(idx)}

        logger.info(
            "%-25s overall P=%.3f R=%.3f F1=%.3f [%.3f, %.3f]",
            name,
            overall.precision,
            overall.recall,
            overall.f1,
            ci.ci_lo,
            ci.ci_hi,
        )
        for cat in categories:
            c = by_category[cat]
            logger.info(
                "  %-4s n=%2d P=%.3f R=%.3f F1=%.3f", cat, c["n"], c["precision"], c["recall"], c["f1"]
            )

        per_detector_summary[name] = {
            "overall": overall.as_dict(),
            "f1_bootstrap_ci": ci.as_dict(),
            "by_category": by_category,
        }

    ao_idx = [i for i, p in enumerate(pairs) if p.category == "AO"]
    d4_ao = [all_predictions["D4_structural_topology"][i] for i in ao_idx]
    d5_ao = [all_predictions["D5_with_aggregation"][i] for i in ao_idx]
    mcnemar_ao25 = mcnemar_test(d4_ao, d5_ao)
    logger.info(
        "McNemar D4 vs D5 (AO-25 category, n=%d): statistic=%.3f p=%.6f n_discordant=%d",
        len(ao_idx),
        mcnemar_ao25.statistic,
        mcnemar_ao25.p_value,
        mcnemar_ao25.n_discordant,
    )

    write_json(
        run_dir / "raw_results.json",
        {
            "n_pairs": len(pairs),
            "categories": categories,
            "pair_names": [p.name for p in pairs],
            "pair_categories": [p.category for p in pairs],
            "ground_truth": gt,
            "predictions": all_predictions,
        },
    )
    write_json(
        run_dir / "summary_stats.json",
        {
            "n_pairs": len(pairs),
            "category_counts": {cat: sum(1 for p in pairs if p.category == cat) for cat in categories},
            "ao_positive": sum(1 for p in pairs if p.category == "AO" and p.is_conflict),
            "ao_negative": sum(1 for p in pairs if p.category == "AO" and not p.is_conflict),
            "detectors": per_detector_summary,
            "mcnemar_D4_vs_D5_AO25_category": {**mcnemar_ao25.as_dict(), "n_ao_pairs": len(ao_idx)},
        },
    )
    write_manifest(run_dir, seeds=[42], command="python experiments/run_a6_ao25_eval.py")

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
