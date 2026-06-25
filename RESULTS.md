# Playground Results: Lineage-Aware Memory Governance

## What this is

A synthetic simulation, not a real BI deployment. It tests one thing: given
identical workloads, does gating memory retrieval on **lineage** (which
tables/columns/join logic produced a stored insight) catch leakage and metric
conflicts that gating on **content/access tags alone** misses?

Three systems, same workload, same random seeds:

| System | Represents |
|---|---|
| No Memory | Status quo before any shared agent memory |
| Naive Shared Memory | Current published work: Oracle AI Agent Memory, the production Governed Memory architecture, SSGM, Zep, MemGPT, A-MEM — all gate on content/tags, not derivation |
| Lineage-Aware Governed Memory | Proposed: AMU schema + lineage-gated retrieval + lineage-hash conflict detection |

## Setup

- 3 departments (Finance, Marketing, Support) with different column-level permissions (Marketing and Support cannot see `ssn`, `income`, `email`)
- 5 shared business metrics, some with multiple genuinely different lineage variants (different join paths / filter logic) to model real cross-team definition drift
- 120 events per run (20 epochs × 6 events), replayed identically across all three systems
- 30 random seeds to check the result isn't a fluke of one workload draw

## Results (mean ± std dev over 30 seeds)

| Metric | No Memory | Naive Shared Memory | Lineage-Aware |
|---|---|---|---|
| Leak rate | 0.0% | **18.8% ± 3.7%** | **0.0% ± 0.0%** |
| Memory reuse rate | 0.0% | 95.8% ± 0.0% | 82.6% ± 2.3% |
| Metric-conflict recall | n/a | 0.0% ± 0.0% | 100.0% ± 0.0% |

See `results_chart.png`.

## Reading the results honestly

**Leak rate (the headline number):** naive content-gated memory leaks
unauthorized columns to ~1 in 5 cross-department retrievals, consistently,
across all 30 seeds. Lineage-aware gating drives this to zero — but it does
so by construction (it checks the same sensitivity tags the leak metric is
computed from). **This demonstrates the mechanism is logically sound, not
that it generalizes.** The real empirical question a reviewer will ask: does
lineage-aware gating still work when sensitivity isn't a clean column tag —
e.g. a derived feature that *encodes* income without naming the column? This
playground doesn't test that yet. That's the next experiment, not a result
to claim now.

**Reuse rate cost:** lineage-aware governance isn't free. It blocks 15 of 120
retrievals (in the seed=42 run) where the only cached answer touched a
restricted column, forcing a fresh recompute instead. That's the real
tradeoff to report in the paper — governance costs ~13 points of reuse rate
in this workload. Worth varying the proportion of sensitive-vs-safe lineage
variants to show how this tradeoff scales; right now it's a single
operating point.

**Conflict recall = 100.0% ± 0.0% every time:** be upfront that this is
**partly tautological** in the current setup — the ground-truth "is this a
real conflict" check and the detector's "did you flag it" check both compare
the same `definition_hash` derived from join tables + filter string. A
detector built this way cannot fail to find what it's defined to find. The
naive system's 0% isn't because it's bad at detection — it's because it has
*no mechanism at all*, which is the actually-true and useful claim. The
conflict-recall number as currently computed should not go in the paper as
evidence of detection accuracy; it should be reframed as "a mechanism exists
vs. doesn't," with a follow-up experiment using near-duplicate but
non-identical lineages (e.g. same tables, slightly different filter
thresholds, or semantically equivalent but differently-written logic) to
test whether definition-hash matching is too strict or too loose in
practice.

## What this playground is good for in the paper

- A concrete, runnable existence proof that the AMU schema + lineage gate
  works as a mechanism, with a clean before/after comparison table
- The leak-rate result is the strongest one to lead with — it's not
  tautological in the same way, since "leaked" is computed independently
  from "blocked" (the naive system has no blocking logic at all, so its leak
  number is a genuine behavioral outcome, not a constructed identity)
- A template for a much larger and more realistic follow-up: real schema
  with dozens of tables, fuzzy/semantic conflict detection instead of exact
  hash matching, and an adversarial workload generator that specifically
  tries to construct queries that smuggle sensitive joins past the lineage
  check

## What NOT to claim yet

- Don't report conflict recall as "100% accurate conflict detection" in the
  paper without the caveat above — a reviewer who reads `simulate.py` will
  find the tautology in about two minutes
- Don't generalize the 18.8% leak rate as a real-world estimate — it's a
  property of this synthetic workload's mix of sensitive vs. safe lineage
  variants, not a measured fact about real enterprise systems
- This is a mechanism demo, not a benchmark yet — turning it into one
  (adversarial queries, real schema complexity, fuzzy conflict matching) is
  the actual next work item before this is submission-ready
