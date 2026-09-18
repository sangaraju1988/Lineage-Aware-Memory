# Extension paper: D4/D5 detectors, materialization-boundary hardening, SQL bugfix demo, and two post-publication corrections

**Branch:** `extension-paper` → `main` (branched after PR #1 was merged, so PR #1's changes — the SQL unqualified-column fix, the conformance check, and the adversarial materialization experiment — are already fully incorporated, not built on top of an unmerged branch)

## Summary

This PR adds `extension_paper/`, a self-contained package of new, executed
experiments extending the published IEEE Access paper's codebase toward a
follow-on paper (PeerJ Computer Science / arXiv target). Every number in
`extension_paper/results/RESULTS.md` is real and reproducible via
`make experiments` — nothing is a placeholder or a hand-computed estimate.
It also includes two post-publication correctness corrections, applied to
both the root repo and the `amu-governance` package.

**This PR does not touch the published paper's LaTeX/PDF.** All work here
is new code and new results for the extension paper only.

### Group A — Detector evaluation (D4, D5)

The original paper proposed a structural-gate-plus-operator-topology
detector (D4) but never evaluated it. This PR implements and evaluates it,
plus a new D5 (D4 + aggregation-equality check) that closes an
aggregation-operator blind spot the original detector set couldn't catch:

- D4 achieves perfect precision/recall (F1=1.000) on the original 43-pair
  dataset, closing D3's LO (logic-operator) blind spot without reopening
  D1's TV (threshold-variant) false-positive problem.
- A new 10-pair Aggregation-Operator (AO) dataset shows D4's designed blind
  spot directly: F1=0.250 (recall=0.143 — it misses 6 of 7 real AO
  conflicts because `aggregation_fn` isn't one of its inputs). D5 closes it:
  F1=1.000. **McNemar D4 vs D5: p=0.03125** (significant at α=0.05).
- Full 53-pair matrix (43 original + 10 AO), all 5 detectors: D5 is the
  only one with perfect precision and recall overall.
- Runtime benchmark: D5's extra check costs at most ~8.6% mean latency vs.
  D4 across representative pairs, both at microsecond scale — not a
  measurable regression for any realistic deployment.

### Group B — Materialization-boundary threat (building on PR #1)

- `docs/threat_model_extension.md` formalizes the threat PR #1's
  `adversarial_lineage_experiment.py` demonstrated, relates it to the
  paper's Assumption 1 / Theorem 1, and states the safety argument's
  precise boundary.
- The closure experiment is generalized from PR #1's single 2-chain case to
  5 chain-count/department-topology configurations × 30 seeds each.
  **Configuration 1 exactly reproduces PR #1's reported 32.7% ± 9.3%
  leak rate** (measured here: 32.67% ± 9.29%), confirming the
  generalization didn't silently change the original result. Broader
  configurations show stock leak rates from 18.67% to 46.33% depending on
  topology; closure drives every configuration to 0.00%.
- A new regression test (`test_unregistered_materialization.py`) proves
  the boundary of that guarantee: closure cannot catch a materialization
  edge that was never registered (e.g. an out-of-band ETL job or
  warehouse-managed materialized view) — the original leak reproduces
  exactly regardless of closure.

### Group C — Reproducibility and correctness hardening

- The package-conformance check (root repo vs. `amu-governance`) is
  re-run with full provenance and wired into CI on every push.
- Storage overhead is re-measured: 3.93x JSON serialization ratio (21 AMUs
  measured), just below the paper's analytical estimate's 4x-8x range.
  Reported as a refinement of the estimate, not a correction — the exact
  measured numbers are used, not adjusted to fit.
- **New: SQL unqualified-column bugfix demonstration**
  (`run_c3_sql_bugfix_demo.py`). PR #1's fix (commit `dc8e960`) had never
  actually been exercised by unqualified-column queries in any existing
  test or demo. This PR builds a 12-query set (8 unqualified comma-joins
  touching sensitive Northwind columns + 4 negative controls) and shows
  **81.82% → 0.00% leak rate** (of 11 exploitable queries) before vs.
  after the fix, against a department denied all 4 sensitive columns.

### Post-publication corrections (both flagged explicitly, neither changes a published safety result)

1. **Algorithm 1 diagnostic-flag bug** (`systems.py` and
   `amu_governance/systems.py`): `LineageAwareSystem.request()` hardcoded
   `blocked=False` in the branch that returns a safe, reused candidate,
   discarding `any_blocked` even when an earlier unsafe candidate had been
   skipped in the same loop. This is a **diagnostic/reporting field only**
   — `RetrievalResult.leaked` (the safety-relevant field) was never
   affected, so **no published safety number changes**. Fixed in both
   implementations (kept in sync to avoid a false conformance-test
   failure), with a regression test verified via git-stash to genuinely
   fail against the pre-fix code.
2. **SQL unqualified-column leak** — already fixed by PR #1 (`dc8e960`);
   this PR adds the first test that actually exercises it (see Group C3
   above).

## What's in `extension_paper/`

```
extension_paper/
├── src/amu_ext/                # detectors, aggregation schema, materialization
│                                #  closure, SQL extraction, stats (mypy --strict clean)
├── tests/{unit,integration,regression}/  # 102 tests, 99% coverage on src/amu_ext/
├── experiments/run_*.py        # 8 full-statistical-power experiment scripts + make_figures.py
├── data/                       # conflict_dataset_43.json (ported), conflict_dataset_ao_10.json (new)
├── docs/{threat_model_extension,limitations}.md
├── results/                    # RESULTS.md + 8x raw_results/summary_stats/run_manifest/figures
├── README.md, Makefile, pyproject.toml
└── (repo root) .github/workflows/extension-ci.yml
```

Full details and every cited number: `extension_paper/results/RESULTS.md`.
Explicit scope-out list (T6/DP, ABAC/Guardrails benchmarking, full
BIRD-SQL/Spider validation — none of these block Groups A-C) and build-time
caveats: `extension_paper/docs/limitations.md`.

## Engineering bar

- `mypy --strict` clean on `src/amu_ext/` (scoped there deliberately — see
  README's "Why mypy ignores the root repo").
- `black` + `ruff` zero warnings, matching the root repo's existing
  `typing.List/Dict/Optional` convention (ruff's `UP`/pyupgrade rules are
  deliberately excluded — see README).
- 99% line coverage on `src/amu_ext/` (102 tests); the 3 uncovered lines
  are documented in `docs/limitations.md` as defensive guards no exercised
  path reaches.
- Three test tiers: fast unit + fast integration/smoke in the default
  `pytest` run (~0.6s), slow full-statistical-power runs only via
  `make experiments`.
- CI (`.github/workflows/extension-ci.yml`) runs lint + typecheck + the
  fast test tier on every push.
- Every experiment writes real, timestamped, git-commit-tagged results —
  `make experiments && make figures` regenerates the entire results
  package end-to-end with no manual intervention.

## Testing

```bash
cd extension_paper
make setup && make lint && make typecheck && make test && make experiments && make figures
```

All pass cleanly from a fresh checkout of this branch.
