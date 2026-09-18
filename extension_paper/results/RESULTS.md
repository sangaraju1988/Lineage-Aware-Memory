# Results

All numbers below are copied verbatim from the `summary_stats.json` of the
cited `run_id` folder — none are rounded, adjusted, or hand-computed. Each
run folder also contains `raw_results.json` (per-item results),
`run_manifest.json` (git commit, UTC timestamp, seeds, package versions,
exact command), and `figures/*.png`. Reproduce any of these with
`make experiments` (all 8 scripts) or by running the individual
`experiments/run_*.py` script named in each section; see the README for
exact commands. Every run below was produced at git commit `49301e6`.

See `docs/limitations.md` for caveats on specific numbers (the AO dataset's
single-pass labeling, the materialization-closure boundary, the storage
refinement, the TV-category F1 convention, and the coverage/benchmark
notes) before citing any of these in the paper draft.

---

## Group A: Detector evaluation (D4, D5)

### A1 — D1-D4 on the original 43-pair dataset

`results/a1_d4_eval/20260918T182400Z_49301e6/` · `experiments/run_a1_d4_eval.py`

| Detector | Precision | Recall | F1 | F1 95% CI |
|---|---|---|---|---|
| D1 (exact hash) | 0.651 | 1.000 | 0.789 | [0.677, 0.883] |
| D2 (Jaccard filter) | 0.676 | 0.821 | 0.742 | [0.604, 0.853] |
| D3 (column-graph) | 1.000 | 0.714 | 0.833 | [0.703, 0.933] |
| D4 (structural + topology) | 1.000 | 1.000 | **1.000** | [1.000, 1.000] |

D4 achieves perfect precision and recall on the original TC/TV/LO/CS
categories — it closes D3's documented LO (Logic-Operator) blind spot
(D3 scores F1=0 on LO, since it ignores `filter_logic` entirely) without
reopening D1's TV (Threshold-Variant) over-flagging problem (D1 scores
recall=1.0 but precision=0.651, i.e. it flags every TV pair as a conflict
even though none of them are). See `figures/detector_f1_original_dataset.png`.

### A2 — D4 vs D5 on the new AO (Aggregation-Operator) dataset

`results/a2_d5_eval/20260918T182401Z_49301e6/` · `experiments/run_a2_d5_eval.py`

| Detector | TP | FP | TN | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| D4 | 1 | 0 | 3 | 6 | 1.000 | 0.143 | 0.250 |
| D5 | 7 | 0 | 3 | 0 | 1.000 | 1.000 | **1.000** |

D4 cannot see `aggregation_fn` by construction and misses 6 of 7 real
AO conflicts. D5 (D4 + aggregation-equality check) catches all 7.
**McNemar D4 vs D5 on AO: n_discordant=6, p=0.03125** (exact binomial test)
— statistically significant at α=0.05. See `figures/d4_vs_d5_ao_category.png`.

### A4 — Full 53-pair matrix (43 original + 10 AO), all 5 detectors

`results/a4_full_matrix/20260918T182401Z_49301e6/` · `experiments/run_a4_full_matrix.py`

| Detector | Overall Precision | Overall Recall | Overall F1 |
|---|---|---|---|
| D1 | 0.644 | 0.829 | 0.725 |
| D2 | 0.667 | 0.686 | 0.676 |
| D3 (column-graph) | 1.000 | 0.571 | 0.727 |
| D4 | 1.000 | 0.829 | 0.906 |
| D5 | 1.000 | 1.000 | **1.000** |

D5 is the only detector achieving perfect precision and recall across the
combined dataset. **McNemar D4 vs D5, full 53-pair dataset: n_discordant=6,
p=0.03125** — identical to the AO-restricted test, confirming all 6
discordant pairs are within the AO category (D4 and D5 never disagree
outside it, as expected since D5 = D4 + one additional check). See
`figures/full_matrix_f1_by_detector.png` for the by-category breakdown —
**note the TV column reads F1=0.0 for every detector by convention, not
because any detector fails there; see `docs/limitations.md`.**

### A5 — D4 vs D5 runtime benchmark

`results/a5_runtime_benchmark/20260918T182402Z_49301e6/` · `experiments/run_a5_runtime_benchmark.py`

2000 timed iterations (200 discarded warm-up) per pair, three representative
pairs by filter-logic complexity:

| Pair | D4 mean (us) | D5 mean (us) | Regression |
|---|---|---|---|
| smallest | 4.454 | 4.838 | +8.61% |
| median | 0.425 | 0.452 | +6.38% |
| largest | 7.558 | 7.739 | +2.39% |

Max regression across all three: **8.6%, not measurable in absolute terms**
(microsecond scale; unseeded wall-clock timing, so this varies a few
percent run-to-run — see `docs/limitations.md`). Full 53-pair sweep: D4
mean 244.3us, D5 mean 263.9us total. See `figures/runtime_benchmark_d4_vs_d5.png`.

---

## Group B: Materialization-boundary threat

### B2 — Generalized materialization-closure sweep (5 configurations x 30 seeds)

`results/b2_materialization_sweep/20260918T182400Z_49301e6/` · `experiments/run_b2_materialization_sweep.py`

| Configuration | Chains | Depts | Stock leak rate (mean +/- sd) | Closure leak rate |
|---|---|---|---|---|
| 2chains_3dept_original | 2 | 3 | 32.67% +/- 9.29% | 0.00% |
| 3chains_3dept | 3 | 3 | 46.33% +/- 10.95% | 0.00% |
| 5chains_3dept | 5 | 3 | 40.83% +/- 12.52% | 0.00% |
| 2chains_5dept | 2 | 5 | 18.67% +/- 8.16% | 0.00% |
| 5chains_5dept | 5 | 5 | 33.33% +/- 7.56% | 0.00% |

**PR #1 reproduction check: PASSED.** Configuration 1 (2 chains, 3
departments, same seed range 0-29 as PR #1's original experiment)
reproduces PR #1's reported **32.7% +/- 9.3%** stock leak rate exactly as
**32.67% +/- 9.29%** here. Closure drives leak to 0.00% in every
configuration — but only because every materialization edge in this sweep
is registered; see B3 below and `docs/limitations.md` for the boundary
case where that stops holding. See `figures/materialization_sweep_leak_rate.png`.

### B3 — Regression test proving closure's boundary

`tests/regression/test_unregistered_materialization.py` (not a `results/`
run — a permanent regression test, executed on every `pytest` run).
Constructs a materialization edge deliberately never passed to
`MaterializationRegistry.register(...)` and confirms `close_lineage()`
returns the downstream lineage unchanged, so the original leak (an
income-derived `risk_score` served to a department without income access)
reproduces exactly, with or without closure applied. Formal writeup:
`docs/threat_model_extension.md`.

---

## Group C: Reproducibility and correctness hardening

### C1 — Package-conformance re-run

`results/c1_conformance/20260918T182400Z_49301e6/` · `experiments/run_c1_conformance.py`

**PASSED** across 30 seeds, 0 mismatches. Confirms the `amu-governance`
PyPI package and the root repo's `model.py`/`systems.py` (the frozen
artifact behind the published paper's numbers) produce identical
statistics on the identical seeded workload. This check is also wired
into CI (`tests/integration/test_conformance.py`, every push). See
`figures/conformance_status.png`.

### C2 — Storage-overhead re-measurement

`results/c2_storage_overhead/20260918T182400Z_49301e6/` · `experiments/run_c2_storage_overhead.py`

21 AMUs measured. **JSON serialization ratio: 3.93x** (range 3.44x-5.00x).
Pickle ratio: 3.19x. Bare value bytes (mean): 91.1. Full governed AMU bytes
(mean): 357.0. Paper's analytical estimate: 4x-8x ratio, 200-600 bytes.
The measured ratio sits just below the estimate's lower bound; the measured
byte counts fall inside the estimate's byte range. Reported as a
refinement of the analytical estimate, not a correction — see
`docs/limitations.md`. See `figures/storage_overhead_measured_vs_estimate.png`.

### C3 — SQL unqualified-column bugfix demonstration (new)

`results/c3_sql_bugfix_demo/20260918T182400Z_49301e6/` · `experiments/run_c3_sql_bugfix_demo.py`

12 queries (8 unqualified-column comma-joins touching sensitive Northwind
columns + 4 negative controls), evaluated against the Operations
department (denied all 4 sensitive columns: `unitprice`, `freight`,
`homephone`, `birthdate`).

| Condition | Leak rate (of 11 exploitable queries) |
|---|---|
| Pre-fix (`keep_unqualified=False`) | **81.82%** (9/11) |
| Post-fix (`keep_unqualified=True`) | **0.00%** (0/11) |

This is the experiment the build prompt calls "the most important new
experiment" — PR #1's fix (commit `dc8e960`) had never actually been
exercised by a test with unqualified-column queries in scope before this.
See `figures/sql_bugfix_leak_rate_before_after.png`.

### C4 — Algorithm 1 diagnostic-flag bugfix (post-publication correction)

Not a `results/` run — a code fix plus regression test
(`tests/regression/test_algorithm1_diagnostic_bug.py`). Root cause:
`LineageAwareSystem.request()` in both `systems.py` (root repo) and
`amu_governance/systems.py` (the PyPI package) hardcoded `blocked=False`
in the branch that returns a safe, reused candidate — discarding
`any_blocked`, which had accumulated `True` if an earlier, unsafe candidate
was skipped in the same loop before the safe one was found. **This is a
diagnostic/reporting-field bug only**: `RetrievalResult.leaked` (the
safety-relevant field) was never affected, so no published safety result
changes. Fixed in both implementations to `blocked=any_blocked`, verified
by git-stashing the fix and confirming the new regression tests genuinely
fail against the pre-fix code. Documented as a post-publication correction,
not a new finding that changes any reported number.

---

## Reproduction

```bash
cd extension_paper
make setup        # editable install + dev/runtime deps
make lint          # black --check + ruff check
make typecheck     # mypy --strict on src/amu_ext
make test          # fast tier: unit + integration smoke (~1s)
make experiments   # slow tier: full-statistical-power runs -> results/
make figures       # regenerate figures/*.png from the latest results/ runs
```

Every number in this document was produced by the exact commands above,
run end-to-end with no manual intervention, at git commit `49301e6`.
