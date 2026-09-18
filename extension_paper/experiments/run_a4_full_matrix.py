#!/usr/bin/env python3
"""
Group A4: full evaluation matrix -- 43 original pairs + 10 new AO pairs = 53
pairs, 5 categories (TC, TV, LO, CS, AO), 5 detectors (D1-D5).

Reports precision/recall/F1 per detector per category, with bootstrap 95%
CIs (10,000 resamples), to ``summary_stats.json``, and the full
per-pair/per-detector prediction matrix to ``raw_results.json``. Runs a
paired McNemar test comparing D4 vs D5 specifically on the AO category's
classification outcomes (D4 and D5 are, by construction, identical outside
AO -- see ``amu_ext.detectors.d5_with_aggregation`` -- so restricting the
comparison to AO is what isolates the aggregation-equality check's actual
effect, rather than diluting it with 43 pairs where the two detectors never
disagree).
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


def load_combined_dataset() -> list[Pair]:
    original = load_pairs(DATA_DIR / "conflict_dataset_43.json")
    ao = load_pairs(DATA_DIR / "conflict_dataset_ao_10.json")
    return original + ao


def main() -> int:
    run_dir = make_run_dir("a4_full_matrix")
    logger = setup_logging(run_dir, "run_a4_full_matrix")

    pairs = load_combined_dataset()
    categories = sorted({p.category for p in pairs})
    logger.info("Combined dataset: %d pairs, categories=%s", len(pairs), categories)
    assert len(pairs) == 53, f"expected 53 pairs (43 + 10), got {len(pairs)}"

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
            logger.debug(
                "  %-4s n=%2d P=%.3f R=%.3f F1=%.3f", cat, c["n"], c["precision"], c["recall"], c["f1"]
            )

        per_detector_summary[name] = {
            "overall": overall.as_dict(),
            "f1_bootstrap_ci": ci.as_dict(),
            "by_category": by_category,
        }

    # Paired McNemar: D4 vs D5, restricted to the AO category.
    ao_idx = [i for i, p in enumerate(pairs) if p.category == "AO"]
    d4_ao = [all_predictions["D4_structural_topology"][i] for i in ao_idx]
    d5_ao = [all_predictions["D5_with_aggregation"][i] for i in ao_idx]
    mcnemar_ao = mcnemar_test(d4_ao, d5_ao)
    logger.info(
        "McNemar D4 vs D5 (AO category, n=%d): statistic=%.3f p=%.6f",
        len(ao_idx),
        mcnemar_ao.statistic,
        mcnemar_ao.p_value,
    )

    # Also report it over the FULL 53-pair set for completeness/contrast --
    # expected to show fewer/no discordant pairs outside AO, since D4 and D5
    # agree everywhere else by construction.
    d4_full = all_predictions["D4_structural_topology"]
    d5_full = all_predictions["D5_with_aggregation"]
    mcnemar_full = mcnemar_test(d4_full, d5_full)
    logger.info(
        "McNemar D4 vs D5 (full 53-pair set): statistic=%.3f p=%.6f n_discordant=%d",
        mcnemar_full.statistic,
        mcnemar_full.p_value,
        mcnemar_full.n_discordant,
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
            "detectors": per_detector_summary,
            "mcnemar_D4_vs_D5_AO_category": {**mcnemar_ao.as_dict(), "n_ao_pairs": len(ao_idx)},
            "mcnemar_D4_vs_D5_full_dataset": mcnemar_full.as_dict(),
        },
    )
    write_manifest(run_dir, seeds=[42], command="python experiments/run_a4_full_matrix.py")

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
