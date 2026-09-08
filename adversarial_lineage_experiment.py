"""
Experiment 7: Transitive Lineage Closure Under Materialization Boundaries
==========================================================================

The paper's own roadmap (and RESULTS.md, "What NOT to claim yet") names the
open gap this experiment tests: lineage-aware gating is validated when
sensitivity is a clean column tag directly present in an AMU's recorded
lineage. It has not been tested against a *derived proxy* -- a materialized
intermediate that encodes a sensitive column without naming it.

The attack, concretely (a "lineage truncation at a materialization
boundary"):

  1. Finance computes `risk_score` from `customer_pii.income`. This AMU's
     lineage correctly records `income` -- the gate works, Marketing is
     correctly blocked from `risk_score` directly.
  2. `risk_score` is *materialized*: persisted as a column in a downstream
     table (a feature store, a reporting mart -- anywhere a computed value
     becomes an input to further queries, which is normal enterprise
     practice, not a workaround).
  3. A second AMU, `high_risk_customers`, is derived from `risk_score`
     ALONE. Its lineage is `{risk_score}` -- it never touches `income`.
     `sensitivity_tags` for this AMU is therefore empty.
  4. Marketing requests `high_risk_customers`. The stock gate sees no
     sensitive columns in the recorded lineage and serves it. Income has
     leaked through a materialization boundary without ever being named.

This is a real, mechanically exact instance of Assumption 1 (Complete
Lineage Recording) failing: the lineage recorded at step 3 is *complete*
with respect to what step 3's query touched, but incomplete with respect
to the metric's full provenance, because it doesn't know `risk_score`
itself has upstream sensitive lineage.

We test one candidate fix -- transitive lineage closure -- against the
stock gate on an identical seeded workload:

  STOCK:    LineageAwareSystem exactly as published, using each AMU's
            lineage as literally recorded.
  CLOSURE:  Before gating, expand any lineage step that references a
            materialized column against a MaterializationRegistry mapping
            (table, column) -> the upstream Lineage that produced it,
            recursively, and union in the upstream sensitive columns.

This experiment does not modify amu_governance or model.py/systems.py --
closure is implemented as a pure pre-processing step composed with the
published, unmodified LineageAwareSystem, so both conditions exercise the
real gate.

Honest framing (matching this repo's RESULTS.md convention): this is a
mechanism demo of the failure and one candidate fix, not a claim that
closure is the only or best fix, nor that this covers every proxy-leakage
vector (e.g. a materialized column that is a *statistical function* of a
sensitive column without any registered provenance link at all -- a
feature store that computes `income_bucket` outside this system entirely
-- is out of scope for closure, which can only close what has a recorded
provenance edge).
"""

import random
import statistics
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from amu_governance import AMU, Lineage, LineageStep, GovernancePolicy, LineageAwareSystem
from model import SENSITIVE_COLUMNS, DEPARTMENT_PERMISSIONS  # reuse the paper's schema

policy = GovernancePolicy(
    sensitive_columns=set(SENSITIVE_COLUMNS),
    department_permissions={k: set(v) for k, v in DEPARTMENT_PERMISSIONS.items()},
)

DEPARTMENTS = ["Finance", "Marketing", "Support"]
N_EPOCHS = 20
N_SEEDS = 30

# ── Two materialization chains: one income-derived (sensitive), one not ──

CHAINS = {
    "risk_score": {
        # Tier 0: base computation, correctly touches income -> sensitive.
        "base_lineage": Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "income")),),
            filter_logic="income-weighted risk model v1",
        ),
        "materialized_table": "derived_features",
        "materialized_column": "risk_score",
        "downstream_metric": "high_risk_customers",
        "downstream_filter": "risk_score > 0.8",
        "sensitive": True,
    },
    "txn_band": {
        # Tier 0: base computation, touches only transaction volume -> safe.
        "base_lineage": Lineage(
            steps=(LineageStep("transactions", ("customer_id", "amount")),),
            filter_logic="transaction-frequency banding",
        ),
        "materialized_table": "derived_features",
        "materialized_column": "txn_band",
        "downstream_metric": "active_band_customers",
        "downstream_filter": "txn_band = 'high'",
        "sensitive": False,
    },
}


class MaterializationRegistry:
    """Maps a materialized (table, column) to the Lineage that produced it."""

    def __init__(self):
        self._provenance: Dict[Tuple[str, str], Lineage] = {}

    def register(self, table: str, column: str, upstream: Lineage) -> None:
        self._provenance[(table, column)] = upstream

    def upstream_of(self, table: str, column: str) -> Optional[Lineage]:
        return self._provenance.get((table, column))


def close_lineage(lineage: Lineage, registry: MaterializationRegistry,
                   _depth: int = 0, _max_depth: int = 8) -> Lineage:
    """Recursively expand any step referencing a materialized column with
    its registered upstream lineage's steps, so downstream sensitivity
    checks see the full provenance chain, not just the immediate hop."""
    if _depth >= _max_depth:
        return lineage  # guard against a malformed cyclic registry

    extra_steps: List[LineageStep] = []
    for step in lineage.steps:
        for col in step.columns_used:
            upstream = registry.upstream_of(step.table, col)
            if upstream is not None:
                closed_upstream = close_lineage(upstream, registry, _depth + 1, _max_depth)
                extra_steps.extend(closed_upstream.steps)

    if not extra_steps:
        return lineage

    return Lineage(steps=lineage.steps + tuple(extra_steps), filter_logic=lineage.filter_logic)


@dataclass
class Event:
    epoch: int
    department: str
    chain: str  # "risk_score" or "txn_band"
    requester: str  # department requesting the downstream metric


def generate_workload(n_epochs: int = N_EPOCHS) -> List[Event]:
    events = []
    chain_names = list(CHAINS.keys())
    for epoch in range(n_epochs):
        chain = random.choice(chain_names)
        originator = random.choice(DEPARTMENTS)
        requester = random.choice(DEPARTMENTS)
        events.append(Event(epoch, originator, chain, requester))
    return events


def run_condition(events: List[Event], use_closure: bool):
    system = LineageAwareSystem(policy)
    registry = MaterializationRegistry()

    leaked = 0
    blocked = 0
    served_downstream = 0
    true_leaks_possible = 0  # events where the downstream metric IS income-derived

    for ev in events:
        spec = CHAINS[ev.chain]

        # Step 1: originator computes and writes the Tier-0 (base) AMU.
        base_amu = AMU(metric_name=f"{ev.chain}_base", value=1.0,
                        owner_department=ev.department, lineage=spec["base_lineage"], epoch=ev.epoch)
        system.write(base_amu)

        # Step 2: originator materializes it as a derived column, and we
        # record the provenance edge regardless of condition (the registry
        # itself is not the fix -- whether the GATE consults it is).
        registry.register(spec["materialized_table"], spec["materialized_column"], spec["base_lineage"])

        downstream_lineage = Lineage(
            steps=(LineageStep(spec["materialized_table"], (spec["materialized_column"],)),),
            filter_logic=spec["downstream_filter"],
        )
        if use_closure:
            downstream_lineage = close_lineage(downstream_lineage, registry)

        downstream_amu = AMU(metric_name=spec["downstream_metric"], value=1.0,
                              owner_department=ev.department, lineage=downstream_lineage, epoch=ev.epoch)
        system.write(downstream_amu)

        # Step 3: a (possibly different) department requests the downstream
        # metric -- this is the request that should be blocked iff the
        # chain is income-derived and the requester lacks income access.
        if spec["sensitive"]:
            true_leaks_possible += 1

        result = system.request(spec["downstream_metric"], ev.requester, downstream_amu)
        if result.reused:
            served_downstream += 1
        if result.blocked:
            blocked += 1

        # Ground truth: did this request expose income-derived data to a
        # department without income access? We check the ORIGINAL base
        # lineage's sensitivity against the requester's real permissions,
        # independent of what the gate under test actually recorded.
        true_sensitive_cols = spec["base_lineage"].sensitive_columns(policy)
        permitted = policy.permitted_columns(ev.requester)
        would_leak = bool(true_sensitive_cols - permitted) and result.reused
        if would_leak:
            leaked += 1

    n = len(events)
    return {
        "leak_rate_pct": round(100 * leaked / n, 2),
        "block_rate_pct": round(100 * blocked / n, 2),
        "served_downstream_pct": round(100 * served_downstream / n, 2),
        "true_leaks_possible": true_leaks_possible,
        "leaked": leaked,
        "n_events": n,
    }


def sweep(n_seeds: int = N_SEEDS):
    stock_leak, closure_leak = [], []
    stock_block, closure_block = [], []
    per_seed = []

    for seed in range(n_seeds):
        random.seed(seed)
        events = generate_workload()
        stock = run_condition(events, use_closure=False)

        random.seed(seed)
        events2 = generate_workload()
        assert events == events2
        closure = run_condition(events2, use_closure=True)

        stock_leak.append(stock["leak_rate_pct"])
        closure_leak.append(closure["leak_rate_pct"])
        stock_block.append(stock["block_rate_pct"])
        closure_block.append(closure["block_rate_pct"])
        per_seed.append({"seed": seed, "stock": stock, "closure": closure})

    summary = {
        "stock_gate": {
            "leak_rate_mean": round(statistics.mean(stock_leak), 2),
            "leak_rate_sd": round(statistics.pstdev(stock_leak), 2),
            "block_rate_mean": round(statistics.mean(stock_block), 2),
        },
        "closure_gate": {
            "leak_rate_mean": round(statistics.mean(closure_leak), 2),
            "leak_rate_sd": round(statistics.pstdev(closure_leak), 2),
            "block_rate_mean": round(statistics.mean(closure_block), 2),
        },
        "n_seeds": n_seeds,
        "per_seed": per_seed,
    }
    return summary


if __name__ == "__main__":
    random.seed(42)
    single = {
        "stock (no closure)": run_condition(generate_workload(), use_closure=False),
        "with transitive closure": run_condition(generate_workload(), use_closure=True),
    }
    print("=== Single seed=42 run ===")
    for name, r in single.items():
        print(f"{name:28s}  leak_rate={r['leak_rate_pct']:5.1f}%  "
              f"block_rate={r['block_rate_pct']:5.1f}%  "
              f"true_leaks_possible={r['true_leaks_possible']}")

    print("\n=== 30-seed sweep ===")
    results = sweep(N_SEEDS)
    print(f"Stock gate    — leak: {results['stock_gate']['leak_rate_mean']:.1f} "
          f"± {results['stock_gate']['leak_rate_sd']:.1f}%   "
          f"block: {results['stock_gate']['block_rate_mean']:.1f}%")
    print(f"Closure gate  — leak: {results['closure_gate']['leak_rate_mean']:.1f} "
          f"± {results['closure_gate']['leak_rate_sd']:.1f}%   "
          f"block: {results['closure_gate']['block_rate_mean']:.1f}%")

    with open("adversarial_lineage_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWrote adversarial_lineage_results.json")
