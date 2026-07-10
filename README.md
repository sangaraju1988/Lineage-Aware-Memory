# Lineage-Aware Memory Governance for Enterprise AI Agents

> **Paper:** *Lineage-Aware Memory Governance for Enterprise AI Agents — A Derivation-Gated Approach to Privacy Isolation and Metric-Definition Consistency in Multi-Department Analytics*
> **Authors:** Venkata Sangaraju · Sudhir Vissa (SAGE7 AI)
> **Date:** June 2026 

---

## Overview

Shared memory across AI agents offers efficiency gains in enterprise analytics but introduces two underexplored failure modes:

1. **Column-level data leakage** — an agent retrieves an insight derived from columns it is not permitted to see.
2. **Silent metric-definition conflicts** — two teams compute the same KPI through divergent derivation paths and the wrong definition propagates silently.

This repository contains the full simulation code, experiment scripts, result data, and paper source for a proposed solution: the **Analytical Memory Unit (AMU)** schema and **lineage-gated retrieval** policy.

---

## Repository Structure

```
Lineage-Aware-Memory/
│
├── model.py                    # AMU dataclass, Lineage, LineageStep, schema definitions
├── systems.py                  # NoMemorySystem, NaiveMemorySystem, LineageAwareSystem
├── simulate.py                 # Event generator, run_simulation(), run_seed_sweep(30)
│
├── gen_figures.py              # Generates all paper figures (matplotlib)
├── tpch_experiment.py          # TPC-H 8-table schema, 30-seed sweep
├── fuzzy_experiment.py         # Fuzzy conflict-detection study (D1/D2/D3 + extended)
├── degradation_experiment.py   # Lineage-completeness degradation sweep
├── benchmark_runtime.py        # Empirical runtime benchmarks (µs-level)
├── stats_analysis.py           # Bootstrap CI + Mann-Whitney U significance tests
│
├── results.csv                 # Single seed=42 simulation results
├── sweep_summary.csv           # 30-seed sweep summary (means ± std dev)
├── tpch_results.json           # TPC-H experiment: per-seed raw data + summary
├── fuzzy_results.json          # Original 10-pair fuzzy detection results
├── fuzzy_results_extended.json # Extended 43-pair fuzzy study with bootstrap CI
├── degradation_results.json    # Completeness sweep: leak rate vs. reporting fraction
├── benchmark_results.json      # Runtime measurements in µs across operation types
├── stats_results.json          # Bootstrap CI + Mann-Whitney p-values
├── RESULTS.md                  # Honest assessment of what the results do/don't show
│
├── agent_demo/
│   ├── demo.py                 # End-to-end walkthrough: SQLite DB + two agent functions
│   └── transcript.md           # Auto-generated readable case-study transcript
│
└── Lineage-Aware-Memory-paper/
    ├── lineage_aware_memory.tex   # Full LaTeX source (article style, arXiv-ready)
    ├── references.bib             # 15 verified BibTeX entries
    ├── lineage_aware_memory.pdf   # Compiled paper (15 pages)
    ├── fig1_comparison_bars.png   # Figure 1 — per-metric bar chart
    ├── fig2_architecture.png      # Figure 2 — AMU architecture diagram
    ├── fig3_tradeoff.png          # Figure 3 — governance/efficiency scatter
    ├── fig4_tpch_comparison.png   # Figure 4 — TPC-H vs synthetic comparison
    └── fig5_degradation.png       # Figure 5 — leak rate vs. lineage completeness
```

---

## Reproducing the Results

Install dependencies first:

```bash
pip install -r requirements.txt
```

All experiments are deterministic (seeded). Run in order:

```bash
# 1. Core simulation — reproduces results.csv and sweep_summary.csv
python simulate.py

# 2. TPC-H schema experiment — reproduces tpch_results.json
python tpch_experiment.py

# 3. Fuzzy conflict-detection study — extended 43-pair dataset
#    Produces fuzzy_results_extended.json (fuzzy_results.json unchanged)
python fuzzy_experiment.py

# 4. Lineage-completeness degradation sweep
#    Tests what happens when agents under-report their derivation columns
#    Completeness levels: 0.5, 0.75, 0.9, 0.95, 1.0 × 30 seeds × 2 schemas
python degradation_experiment.py

# 5. Runtime benchmark (2000 iterations per configuration)
#    Measures sensitivity-tag derivation, definition-hash, retrieve (n=1–50),
#    write/conflict-detection — all in µs
python benchmark_runtime.py

# 6. Statistical significance testing
#    Bootstrap 95% CI + Mann-Whitney U on all naive-vs-lineage-aware comparisons
python stats_analysis.py

# 7. Regenerate all paper figures (including new Figure 5: degradation)
python gen_figures.py

# 8. Agent demo — end-to-end walkthrough with a real SQLite database
#    Finance + Marketing agents through LineageAwareSystem
#    Generates agent_demo/transcript.md
python agent_demo/demo.py
```

---

## Key Results

### Core Simulation (Paper §5.1–5.2)

| Experiment | Naive Shared Memory | Lineage-Aware | Significance |
|---|---|---|---|
| Leak rate — synthetic schema (30 seeds) | 18.8% ± 3.7% | **0.0% ± 0.0%** | p < 0.001 |
| Leak rate — TPC-H schema (30 seeds) | 25.5% ± 4.5% | **0.0% ± 0.0%** | p < 0.001 |
| Memory reuse — synthetic | 95.8% ± 0.0% | **82.6% ± 2.3%** | p < 0.001 |
| Memory reuse — TPC-H | 95.8% ± 0.0% | **81.5% ± 4.8%** | p < 0.001 |
| Conflict recall | 0.0% | **100.0%** | — |

All comparisons: Mann-Whitney U, p < 0.001 (bootstrap 95% CI excludes zero).
The 0% leakage result is a **formal guarantee** (Theorem 1), not an empirical finding.

### Fuzzy Conflict Detection — Extended Study (43 pairs: TC/TV/LO/CS)

| Detector | Precision | Recall | F₁ | 95% CI (F₁) | LO category |
|---|---|---|---|---|---|
| D1 — Exact hash | 0.651 | 1.000 | 0.789 | [0.677, 0.883] | TP: 8/8 |
| D2 — Jaccard (τ=0.70) | 0.676 | 0.821 | 0.742 | [0.604, 0.853] | TP: 3/8 |
| D3 — Column-graph | **1.000** | 0.714 | **0.833** | [0.703, 0.933] | FN: 8/8 |

**New finding (LO category):** D3's perfect precision/recall on the original 10 pairs does not generalise.
Logic-operator changes (AND→OR) with identical column sets are true semantic conflicts that D3 misses entirely.
D1 catches all 8 LO cases; D2 catches 3/8. A production deployment needs D3 + filter-logic check.

### Lineage-Completeness Degradation (New — `degradation_experiment.py`)

| Schema | Completeness | Leak Rate (mean ± sd) | vs. full lineage |
|---|---|---|---|
| Synthetic | 0.50 | 16.3% ± 3.3% | p < 0.001* |
| Synthetic | 0.75 | 0.0% ± 0.0% | not sig. |
| Synthetic | 1.00 | **0.0% ± 0.0%** | baseline |
| TPC-H | 0.50 | 10.3% ± 4.7% | p < 0.001* |
| TPC-H | 0.75 | 0.9% ± 1.1% | p < 0.001* |
| TPC-H | 1.00 | **0.0% ± 0.0%** | baseline |

At completeness=0.50, incomplete lineage reporting causes ~10–16% leak rate — matching
the naive baseline. TPC-H is more sensitive (sensitive columns spread across more join steps).
The safety guarantee requires completeness=1.0 (Assumption 1 in the paper).

### Runtime Benchmarks (New — `benchmark_runtime.py`, 2000 iterations)

| Operation | Mean (µs) | Notes |
|---|---|---|
| Sensitivity-tag derivation | 0.36 | O(k·c), cached at write time |
| Definition-hash (SHA-256) | 1.20 | O(k·c), cached at write time |
| Gate-check predicate (set diff) | 0.09 | Sub-microsecond |
| Retrieve — best-case (n=1–50) | ~0.64 | O(1): first candidate safe |
| Retrieve — worst-case n=1 | 0.66 | All blocked: linear scan begins |
| Retrieve — worst-case n=50 | 13.82 | 21× vs n=1 — confirms O(n) |
| Write/conflict-detect (early exit) | 2.37 | O(1): conflict found on first pair |
| Write/conflict-detect (full scan, n=50) | 1.63 | O(n): no conflict, scans all |

O(n) worst-case scaling confirmed empirically. At n ≤ 5 (realistic production), retrieve
worst-case is < 2 µs — negligible against any real analytics query (typically ms–seconds).

---

## Paper

The compiled PDF and full LaTeX source are in `Lineage-Aware-Memory-paper/`.
To recompile from source (requires a TeX Live installation):

```bash
cd Lineage-Aware-Memory-paper
pdflatex lineage_aware_memory.tex
bibtex lineage_aware_memory
pdflatex lineage_aware_memory.tex
pdflatex lineage_aware_memory.tex
```

---

## Citation

```bibtex
@article{sangaraju2026lineage,
  author  = {Venkata Sangaraju and Sudhir Vissa},
  title   = {Lineage-Aware Memory Governance for Enterprise {AI} Agents},
  year    = {2026},
  note    = {Preprint, June 2026}
}
```

---

## License

**Code (`.py` files):** MIT — see `LICENSE-CODE` for details. This covers all
Python source files in the repository root and `agent_demo/`.

**Paper text and figures** (`Lineage-Aware-Memory-paper/` directory, including
`lineage_aware_memory.tex`, `lineage_aware_memory.pdf`, and all `.png`/`.pdf`
figures): These are under the authors' copyright and are **not** covered by the
MIT license. They are provided for academic reference purposes only. Reuse,
redistribution, or derivative works of the paper text require explicit written
permission from the authors.
