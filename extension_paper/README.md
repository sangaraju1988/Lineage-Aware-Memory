# Extension Paper: New Experiments for Lineage-Aware Memory Governance

This directory extends the published paper's codebase
([root README](../README.md)) with three groups of new, executed
experiments toward a follow-on paper (PeerJ Computer Science / arXiv), plus
two post-publication correctness fixes. Nothing here changes the published
IEEE Access paper's LaTeX/PDF — all numbers below are new work.

Read `results/RESULTS.md` first for the actual numbers and what they mean.
This README covers how to reproduce them.

## What's here

- **Group A — detector evaluation.** D4 (structural gate + filter-logic
  operator-topology diff) and D5 (D4 + aggregation-equality check): the
  original paper proposed D4 but never evaluated it. Both are evaluated
  against the original 43-pair dataset plus a new 10-pair
  Aggregation-Operator (AO) dataset, with bootstrap 95% CIs and a paired
  McNemar test.
- **Group B — materialization-boundary threat.** Formalizes the threat PR
  #1 introduced (`docs/threat_model_extension.md`), generalizes its
  2-chain closure experiment to 5 chain/topology configurations x 30 seeds
  (exactly reproducing PR #1's original case), and adds a regression test
  proving the closure fix does *not* catch an unregistered materialization
  edge.
- **Group C — reproducibility and correctness hardening.** Re-runs the
  package-conformance check (now wired into CI), re-measures storage
  overhead, builds a new SQL unqualified-column bugfix demonstration
  (leak rate before vs. after PR #1's fix — this never existed as a test
  before), and fixes a diagnostic-flag bug in Algorithm 1's retrieval gate
  (in both the root repo and the `amu-governance` package).

See `docs/limitations.md` for what was deliberately left out of scope, and
for caveats on specific numbers.

## Layout

```
extension_paper/
├── src/amu_ext/              # library code (detectors, aggregation schema,
│                              #  materialization closure, SQL extraction, stats)
├── tests/
│   ├── unit/                 # fast, no I/O
│   ├── integration/          # fast, wires in root-repo conformance + experiment smoke tests
│   └── regression/           # the two bugfixes + the B3 boundary proof
├── experiments/               # run_*.py: full-statistical-power scripts -> results/
│   └── make_figures.py        # regenerates figures/*.png from the latest results/ runs
├── data/                      # conflict_dataset_43.json (ported), conflict_dataset_ao_10.json (new)
├── docs/
│   ├── threat_model_extension.md
│   └── limitations.md
├── results/
│   ├── RESULTS.md             # the numbers, with pointers to run_id folders
│   └── <experiment>/<run_id>/ # raw_results.json, summary_stats.json, run_manifest.json, figures/
├── pyproject.toml
├── requirements-extension.txt
└── Makefile
```

## Reproduction

```bash
cd extension_paper
make setup         # pip install -e . plus dev/runtime deps (--break-system-packages)
make lint          # black --check . && ruff check .
make typecheck     # mypy --strict on src/amu_ext (see "Why mypy ignores the root repo" below)
make test          # fast tier only: unit + integration smoke tests (~1s, 102 tests)
make experiments   # slow tier: the real, full-statistical-power runs -> results/
make figures       # regenerate figures/*.png from the latest results/ runs
make all           # lint + typecheck + test + experiments + figures, in order
```

Or run a single experiment directly, e.g.:

```bash
python experiments/run_a4_full_matrix.py
```

Every script writes a fresh, timestamped `results/<experiment>/<run_id>/`
folder (never overwrites a previous run) containing `raw_results.json`,
`summary_stats.json`, `run_manifest.json` (git commit, UTC timestamp,
seeds, package versions, exact command line), and a `figures/` subfolder.

### Test tiers

Three tiers, matching the engineering bar this pass was built against:

1. **Fast unit tests** (`tests/unit/`) — no I/O, includes hypothesis
   property-based tests. Runs in `make test`.
2. **Fast integration/smoke tests** (`tests/integration/`) — exercise every
   experiment's core computational path on tiny toy inputs (a handful of
   pairs/seeds), confirming the wiring works, without writing to the real
   `results/` tree. Also runs in `make test`.
3. **Slow, full-statistical-power runs** (`experiments/run_*.py`) — 10,000-
   resample bootstrap CIs, 30-seed sweeps, the complete 53-pair detector
   matrix. Only via `make experiments`, never part of the default test
   tier or CI's fast gate.

### Why mypy ignores the root repo

`pyproject.toml`'s `[tool.mypy]` section scopes strict checking to
`src/amu_ext` only (`files = ["src/amu_ext"]`). The root repo's
`model.py` / `systems.py` / `real_agent/` / `simulate.py` are loose modules
without a `py.typed` marker or package structure — see
`test_package_conformance.py`'s own docstring, which explicitly documents
`model.py`/`systems.py` as *"the frozen artifact behind the published
results... not meant to be edited to match the package."* Extending strict
typing over those files would mean editing them to satisfy mypy, which
this pass deliberately avoids (the one exception, the Algorithm 1
diagnostic-flag fix in `systems.py`, is a correctness fix explicitly
called out as a post-publication correction — see `results/RESULTS.md`
Group C4 — not a style change).

### Why ruff excludes pyupgrade (`UP`) rules

The root repo's own modules consistently use `typing.List` / `Dict` /
`Set` / `Tuple` / `Optional` rather than builtin-generic (`list[str]`) or
PEP 604 (`X | None`) syntax. `[tool.ruff.lint]` deliberately excludes the
`UP` rule set so this codebase matches that existing convention instead of
silently modernizing past it.

## CI

`.github/workflows/extension-ci.yml` runs `make lint`, `make typecheck`,
and `make test` (the fast tiers only) on every push. `make experiments` is
not part of CI — it is a manual, explicit step for regenerating the actual
results package.
