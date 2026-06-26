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
├── model.py               # AMU dataclass, Lineage, LineageStep, schema definitions
├── systems.py             # NoMemorySystem, NaiveMemorySystem, LineageAwareSystem
├── simulate.py            # Event generator, run_simulation(), run_seed_sweep(30)
│
├── gen_figures.py         # Generates all 4 paper figures (matplotlib)
├── tpch_experiment.py     # TPC-H 8-table schema, 30-seed sweep
├── fuzzy_experiment.py    # Fuzzy conflict-detection study (D1/D2/D3 detectors)
│
├── results.csv            # Single seed=42 simulation results
├── sweep_summary.csv      # 30-seed sweep summary (means ± std dev)
├── tpch_results.json      # TPC-H experiment: per-seed raw data + summary
├── fuzzy_results.json     # Fuzzy detection: TP/FP/TN/FN for D1, D2, D3
├── RESULTS.md             # Honest assessment of what the results do/don't show
│
└── Lineage-Aware-Memory-paper/
    ├── lineage_aware_memory.tex   # Full LaTeX source (article style, arXiv-ready)
    ├── references.bib             # 15 verified BibTeX entries
    ├── lineage_aware_memory.pdf   # Compiled paper (15 pages)
    ├── fig1_comparison_bars.png   # Figure 1 — per-metric bar chart
    ├── fig2_architecture.png      # Figure 2 — AMU architecture diagram
    ├── fig3_tradeoff.png          # Figure 3 — governance/efficiency scatter
    └── fig4_tpch_comparison.png   # Figure 4 — TPC-H vs synthetic comparison
```

---

## Reproducing the Results

All experiments are deterministic (seeded). Run in order:

```bash
# 1. Core simulation — reproduces results.csv and sweep_summary.csv
python simulate.py

# 2. TPC-H experiment — reproduces tpch_results.json
python tpch_experiment.py

# 3. Fuzzy conflict-detection study — reproduces fuzzy_results.json
python fuzzy_experiment.py

# 4. Regenerate all paper figures
python gen_figures.py
```

Dependencies: Python 3.8+, `matplotlib`, `numpy` (standard scientific stack).

---

## Key Results

| Experiment | Naive Shared Memory | Lineage-Aware |
|---|---|---|
| Leak rate — synthetic schema (30 seeds) | 18.8% ± 3.7% | **0.0% ± 0.0%** |
| Leak rate — TPC-H schema (30 seeds) | 25.5% ± 4.5% | **0.0% ± 0.0%** |
| Memory reuse — synthetic | 95.8% | **82.6% ± 2.3%** |
| Memory reuse — TPC-H | 95.8% | **81.5% ± 4.8%** |
| Conflict recall | 0.0% | **100.0%** |

| Conflict Detector | Precision | Recall | F₁ |
|---|---|---|---|
| D1 — Exact hash | 0.50 | 1.00 | 0.67 |
| D2 — Jaccard filter (τ=0.70) | 0.62 | 1.00 | 0.77 |
| **D3 — Column-graph** | **1.00** | **1.00** | **1.00** |

> The 0% leakage result is a **policy guarantee** (Theorem 1 in the paper), not an empirical finding.
> The key empirical finding is the naive baseline's structurally non-zero leak rate across all 60 seed runs.

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

MIT — see `LICENSE` for details.
