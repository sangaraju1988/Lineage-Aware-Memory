# Limitations

This document has two parts: the scope boundaries the build prompt set for
this pass explicitly (things deliberately **not** attempted), and
limitations that surfaced during the build itself (things attempted, with
caveats a reviewer should know about).

## 1. Explicitly out of scope for this pass

These were excluded by design, not by oversight. A follow-on paper could
take any of them up, but none of them block Groups A/B/C below.

- **Threat T6 (differential-privacy-style aggregate inference)** is not
  addressed. The lineage gate in this codebase reasons about column-level
  sensitivity and provenance, not about statistical disclosure through
  repeated aggregate queries; closing T6 would need a different mechanism
  (e.g. query auditing or noise injection) that is a separate research
  contribution, not an extension of the conflict-detection and
  materialization-closure work here.
- **ABAC / NeMo Guardrails benchmarking** is not attempted. The
  `department_permissions` model in this codebase is a simple
  role-to-column allowlist; comparing it against a full attribute-based
  access control system or an LLM-guardrails framework would be evaluating
  a different design point, not extending this one.
- **Full BIRD-SQL / Spider validation** of the SQL lineage extractor is not
  attempted. Group C3's SQL bugfix demo (below) uses a small, deliberately
  hand-constructed query set targeting the specific unqualified-column
  failure mode; a full benchmark validation run is a much larger
  undertaking (dataset licensing, schema mapping, a real evaluation harness)
  that was explicitly scoped out so it would never block Groups A-C.
- **No changes to the published IEEE Access paper's LaTeX/PDF.** Every
  number and detector in this codebase is new work for the *extension*
  paper. Notational issues raised in the ICLR review of the original paper
  are text-only fixes for the new paper's prose, not code changes here.

## 2. Limitations surfaced during the build

- **AO (Aggregation-Operator) dataset labeling.** The 10-pair AO dataset
  (`data/conflict_dataset_ao_10.json`) was hand-labeled in a single pass by
  one author, unlike the original 43-pair dataset's provenance (which this
  extension does not have independent access to re-verify). No second
  labeler or adjudication process was used. The dataset is small (10
  pairs, 7 positive / 3 negative-control) and its purpose is narrow and
  mechanical — distinguishing `SUM` from `AVG`/`COUNT`/etc. over an
  otherwise-identical lineage — which bounds the risk of ambiguous labels,
  but this is a single-annotator dataset and should be described as such in
  any paper draft that cites it.
- **Materialization closure's boundary is real, not just documented.**
  `docs/threat_model_extension.md` states in prose that transitive closure
  only restores the safety guarantee for a *registered* materialization
  edge. `tests/regression/test_unregistered_materialization.py` makes this
  an executed assertion: an edge that was never passed to
  `MaterializationRegistry.register(...)` (the realistic case of an
  out-of-band ETL job or a warehouse-managed materialized view) reproduces
  the original leak exactly, with or without closure. This is not a bug in
  `close_lineage()` — closure cannot see an edge nobody told it about — but
  it is a real limit on what "closure fixes the materialization-boundary
  threat" is entitled to claim, and any paper draft should state the
  boundary alongside the result, not just the result.
- **Storage-overhead measurement is a refinement of the paper's estimate,
  not a strict confirmation.** Group C2 re-measured AMU JSON-serialization
  overhead at **3.93x** (range 3.44x-5.00x across 21 measured AMUs, see
  `results/c2_storage_overhead/`), against the published paper's analytical
  estimate of **4x-8x**. The measured ratio sits just below the estimate's
  lower bound rather than inside the stated range, though the measured
  absolute byte counts (bare ~91 bytes, governed ~357 bytes) do fall inside
  the paper's 200-600 byte estimate. Per the build prompt's explicit
  instruction, this number was not rounded or adjusted to fit the original
  estimate — it is reported as a refinement of an analytical estimate by an
  empirical measurement, which is expected to differ somewhat, not as a
  correction of an error.
- **F1 is 0.0 by convention on the all-negative TV category — this is not
  a detector failure.** For the TV (Threshold-Variant) category, every
  pair's ground truth is "not a conflict," so true-positive and
  false-negative counts are always zero regardless of detector accuracy.
  `precision_recall_f1()` defines precision and recall as 0.0 when their
  denominator is zero (matching the convention already used by the
  original paper's `fuzzy_experiment.py`), so a detector that correctly
  classifies every single TV pair (D3, D4, and D5 all achieve 15/15 true
  negatives, zero false positives, in `results/a1_d4_eval/` and
  `results/a4_full_matrix/`) still reports F1=0.0 on that category. Reading
  the by-category F1 table without this caveat would make D3/D4/D5 look
  like they fail on TV, when they in fact classify it perfectly; any figure
  or table built from `by_category` breakdowns should carry this note.
- **Coverage.** `src/amu_ext/` is at 99% line coverage overall
  (`pytest --cov=amu_ext`); the three files below 100% are each missing a
  single defensive line that no exercised code path reaches by
  construction, not an untested behavior:
  - `materialization.py:426` — an empty-list early-return guard inside a
    private stdev helper, unreachable because every caller already checks
    for a non-empty seed list first.
  - `sql_extraction.py:150` — one field in `CaseResult.as_dict()`'s
    returned mapping that no current experiment or test reads back out of
    the dict (the dataclass field itself is covered elsewhere).
  - `stats.py:227` — the `n == 0` short-circuit inside
    `_binom_cdf_two_sided_p`, unreachable because `mcnemar_test()` already
    returns early (without calling this helper) when `n_discordant == 0`.
- **Runtime-benchmark ordering.** In Group A5's three-pair benchmark
  (`results/a5_runtime_benchmark/`), the pair labeled `"smallest"` (lowest
  filter-logic token complexity) measured a *higher* mean latency (4.81us)
  than `"median"` (0.42us). This is measurement noise at microsecond scale
  (CPython attribute lookups, string interning, and GC timing dominate at
  this resolution, and only 2000 iterations with 200 warmup calls were
  used per pair) rather than a real complexity-latency relationship — see
  the same run's `full_dataset_sweep` for a more stable aggregate number
  (~257us for a full 53-pair sweep). The three-pair breakdown is reported
  exactly as measured, without smoothing.
