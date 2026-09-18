"""
Generalized materialization-boundary closure (Group B).

PR #1's ``adversarial_lineage_experiment.py`` (root repo) demonstrated the
materialization-boundary attack and a candidate fix -- transitive lineage
closure over a ``MaterializationRegistry`` -- on exactly two hardcoded
chains (``income -> risk_score``, ``transaction -> txn_band``) and three
departments. This module lifts that mechanism (``MaterializationRegistry``,
``close_lineage``) out of the experiment script, unchanged in its core
logic, and adds a configurable chain/topology generator so Group B2 can
sweep more than one point in the (chain count, department topology) space
-- see ``experiments/run_b2_materialization_sweep.py``.

Nothing here modifies ``amu_governance`` -- closure is still a pure
pre-processing step composed with the published, unmodified
``LineageAwareSystem``, exactly as PR #1's experiment does it. See
``docs/threat_model_extension.md`` for the formal write-up of what this
does and doesn't close.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from amu_governance import AMU, GovernancePolicy, Lineage, LineageAwareSystem, LineageStep

__all__ = [
    "MaterializationRegistry",
    "close_lineage",
    "ChainSpec",
    "Event",
    "build_chains",
    "DEPARTMENT_TOPOLOGIES",
    "generate_workload",
    "run_condition",
    "sweep_config",
]


class MaterializationRegistry:
    """Maps a materialized ``(table, column)`` to the :class:`Lineage` that produced it.

    Identical logic to PR #1's ``adversarial_lineage_experiment.py`` version
    -- reproduced here verbatim (not reimplemented) so Group B2/B3 exercise
    the exact same registry semantics the original experiment validated.
    """

    def __init__(self) -> None:
        self._provenance: Dict[Tuple[str, str], Lineage] = {}

    def register(self, table: str, column: str, upstream: Lineage) -> None:
        self._provenance[(table, column)] = upstream

    def upstream_of(self, table: str, column: str) -> Optional[Lineage]:
        return self._provenance.get((table, column))


def close_lineage(
    lineage: Lineage,
    registry: MaterializationRegistry,
    _depth: int = 0,
    _max_depth: int = 8,
) -> Lineage:
    """Recursively expand any step referencing a materialized column with its
    registered upstream lineage's steps.

    Identical algorithm to PR #1's version. See ``docs/threat_model_extension.md``
    for the safety argument and its precise boundary (this only closes
    provenance edges that were actually registered -- an unregistered or
    externally-computed materialization is untouched, by construction; see
    Group B3's regression test).
    """
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


# ---------------------------------------------------------------------------
# Configurable chain generation (Group B2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainSpec:
    """One materialization chain: a Tier-0 base computation, materialized as
    a column, consumed by a Tier-1 downstream metric."""

    name: str
    base_lineage: Lineage
    materialized_table: str
    materialized_column: str
    downstream_metric: str
    downstream_filter: str
    sensitive: bool  # ground truth: does the base computation touch a sensitive column?


#: Base-lineage pool the chain generator cycles through. Half sensitive
#: (touch a column in model.py's SENSITIVE_COLUMNS registry -- income, ssn,
#: email), half not, so an N-chain sweep always includes both kinds
#: regardless of N, matching PR #1's original 1-sensitive/1-safe design at
#: N=2 and extending it proportionally for larger N.
_SENSITIVE_BASES: Tuple[Tuple[str, Lineage], ...] = (
    (
        "income_risk",
        Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "income")),),
            filter_logic="income-weighted risk model v1",
        ),
    ),
    (
        "ssn_verified",
        Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "ssn")),),
            filter_logic="identity-verification flag",
        ),
    ),
    (
        "email_engagement",
        Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "email")),),
            filter_logic="email-engagement score",
        ),
    ),
)

_SAFE_BASES: Tuple[Tuple[str, Lineage], ...] = (
    (
        "txn_band",
        Lineage(
            steps=(LineageStep("transactions", ("customer_id", "amount")),),
            filter_logic="transaction-frequency banding",
        ),
    ),
    (
        "campaign_reach",
        Lineage(
            steps=(LineageStep("campaigns", ("customer_id", "channel")),), filter_logic="campaign-reach count"
        ),
    ),
    (
        "support_volume",
        Lineage(
            steps=(LineageStep("support_tickets", ("customer_id", "ticket_id")),),
            filter_logic="support-ticket volume",
        ),
    ),
)


def build_chains(n_chains: int) -> Dict[str, ChainSpec]:
    """Build ``n_chains`` materialization chains, deterministically.

    Chains alternate sensitive/safe base computations (sensitive first),
    cycling through :data:`_SENSITIVE_BASES` / :data:`_SAFE_BASES` when
    ``n_chains`` exceeds the pool size, so the generator supports an
    arbitrary chain count without repeating identical chain *names* (a
    numeric suffix is appended on wraparound).

    At ``n_chains=2`` this reproduces PR #1's exact two chains
    (``income_risk`` -> ``high_risk_customers`` and ``txn_band`` ->
    ``active_band_customers``), so the original 2-chain result stays
    directly reproducible -- see ``run_b2_materialization_sweep.py``.

    Args:
        n_chains: number of chains to build (>= 1).

    Returns:
        ``{chain_name: ChainSpec}``, in generation order.

    Raises:
        ValueError: if ``n_chains < 1``.
    """
    if n_chains < 1:
        raise ValueError(f"n_chains must be >= 1, got {n_chains}")

    chains: Dict[str, ChainSpec] = {}
    for i in range(n_chains):
        is_sensitive = i % 2 == 0
        pool = _SENSITIVE_BASES if is_sensitive else _SAFE_BASES
        base_name, base_lineage = pool[(i // 2) % len(pool)]
        wraparound = (i // 2) // len(pool)
        name = base_name if wraparound == 0 else f"{base_name}_{wraparound}"

        downstream_metric = (
            "high_risk_customers"
            if name == "income_risk"
            else ("active_band_customers" if name == "txn_band" else f"{name}_downstream")
        )
        materialized_column = (
            "risk_score" if name == "income_risk" else ("txn_band" if name == "txn_band" else f"{name}_score")
        )
        threshold = "0.8" if is_sensitive else "'high'"
        op = ">" if is_sensitive else "="

        chains[name] = ChainSpec(
            name=name,
            base_lineage=base_lineage,
            materialized_table="derived_features",
            materialized_column=materialized_column,
            downstream_metric=downstream_metric,
            downstream_filter=f"{materialized_column} {op} {threshold}",
            sensitive=is_sensitive,
        )
    return chains


# ---------------------------------------------------------------------------
# Configurable department topologies (Group B2)
# ---------------------------------------------------------------------------

_SENSITIVE_COLUMNS = {"ssn", "email", "income"}

_BASE_COLUMNS = {
    "customer_id",
    "region",
    "signup_date",
    "txn_id",
    "amount",
    "txn_date",
    "campaign_id",
    "channel",
    "spend",
    "ticket_id",
    "category",
}

#: Named department topologies, keyed by name. Each is a GovernancePolicy.
#: "3dept" reproduces PR #1's exact Finance/Marketing/Support setup;
#: "5dept" broadens the topology to five departments with graded access
#: (full, partial, none) to the sensitive registry, to test whether the
#: closure fix's leak/block tradeoff holds up under a more realistic org
#: chart than three uniform departments.
DEPARTMENT_TOPOLOGIES: Dict[str, GovernancePolicy] = {
    "3dept": GovernancePolicy(
        sensitive_columns=set(_SENSITIVE_COLUMNS),
        department_permissions={
            "Finance": _BASE_COLUMNS | _SENSITIVE_COLUMNS,
            "Marketing": set(_BASE_COLUMNS),
            "Support": set(_BASE_COLUMNS),
        },
    ),
    "5dept": GovernancePolicy(
        sensitive_columns=set(_SENSITIVE_COLUMNS),
        department_permissions={
            "Finance": _BASE_COLUMNS | _SENSITIVE_COLUMNS,
            "Compliance": _BASE_COLUMNS | _SENSITIVE_COLUMNS,  # audit role, full access
            "Marketing": set(_BASE_COLUMNS),
            "Support": set(_BASE_COLUMNS),
            "Analytics": _BASE_COLUMNS | {"income"},  # partial: income only, not ssn/email
        },
    ),
}


@dataclass(frozen=True)
class Event:
    epoch: int
    department: str
    chain: str
    requester: str


def generate_workload(chains: Dict[str, ChainSpec], departments: List[str], n_epochs: int) -> List[Event]:
    """Generate a seeded workload over an arbitrary chain set and department list.

    Must be called with ``random.seed(...)`` already set by the caller
    (matches PR #1's convention: the experiment script owns seeding, not
    this generator, so the exact same seed always reproduces the exact same
    workload for both the stock and closure conditions).
    """
    events = []
    chain_names = list(chains.keys())
    for epoch in range(n_epochs):
        chain = random.choice(chain_names)
        originator = random.choice(departments)
        requester = random.choice(departments)
        events.append(Event(epoch, originator, chain, requester))
    return events


def run_condition(
    chains: Dict[str, ChainSpec],
    policy: GovernancePolicy,
    events: List[Event],
    use_closure: bool,
) -> Dict[str, float]:
    """Replay ``events`` through a fresh :class:`LineageAwareSystem`, with or
    without transitive closure applied before each downstream write.

    Generalizes PR #1's ``run_condition`` to an arbitrary chain dict and
    :class:`GovernancePolicy` (arbitrary department topology), with
    identical per-event logic.
    """
    system = LineageAwareSystem(policy)
    registry = MaterializationRegistry()

    leaked = 0
    blocked = 0
    served_downstream = 0
    true_leaks_possible = 0

    for ev in events:
        spec = chains[ev.chain]

        base_amu = AMU(
            metric_name=f"{ev.chain}_base",
            value=1.0,
            owner_department=ev.department,
            lineage=spec.base_lineage,
            epoch=ev.epoch,
        )
        system.write(base_amu)

        registry.register(spec.materialized_table, spec.materialized_column, spec.base_lineage)

        downstream_lineage = Lineage(
            steps=(LineageStep(spec.materialized_table, (spec.materialized_column,)),),
            filter_logic=spec.downstream_filter,
        )
        if use_closure:
            downstream_lineage = close_lineage(downstream_lineage, registry)

        downstream_amu = AMU(
            metric_name=spec.downstream_metric,
            value=1.0,
            owner_department=ev.department,
            lineage=downstream_lineage,
            epoch=ev.epoch,
        )
        system.write(downstream_amu)

        if spec.sensitive:
            true_leaks_possible += 1

        result = system.request(spec.downstream_metric, ev.requester, downstream_amu)
        if result.reused:
            served_downstream += 1
        if result.blocked:
            blocked += 1

        true_sensitive_cols = spec.base_lineage.sensitive_columns(policy)
        permitted = policy.permitted_columns(ev.requester)
        would_leak = bool(true_sensitive_cols - permitted) and result.reused
        if would_leak:
            leaked += 1

    n = len(events)
    return {
        "leak_rate_pct": round(100 * leaked / n, 2) if n else 0.0,
        "block_rate_pct": round(100 * blocked / n, 2) if n else 0.0,
        "served_downstream_pct": round(100 * served_downstream / n, 2) if n else 0.0,
        "true_leaks_possible": true_leaks_possible,
        "leaked": leaked,
        "n_events": n,
    }


def sweep_config(
    chains: Dict[str, ChainSpec],
    policy: GovernancePolicy,
    departments: List[str],
    n_seeds: int,
    n_epochs: int = 20,
    seed_offset: int = 0,
) -> Dict[str, object]:
    """Run the stock-vs-closure comparison across ``n_seeds`` seeds for one
    (chains, topology) configuration.

    Args:
        chains: the chain set (see :func:`build_chains`).
        policy: the department topology (see :data:`DEPARTMENT_TOPOLOGIES`).
        departments: the department name list (``list(policy.department_permissions)``,
            passed explicitly so iteration order is caller-controlled and
            reproducible).
        n_seeds: number of seeds to sweep.
        n_epochs: events per seed (matches PR #1's ``N_EPOCHS=20`` default).
        seed_offset: starting seed value -- pass 0 to exactly reproduce PR
            #1's original ``range(30)`` seed range for the 2-chain case.

    Returns:
        A summary dict with per-condition means/SDs and the full per-seed
        detail, in the same shape as PR #1's ``sweep()``.
    """
    stock_leak: List[float] = []
    closure_leak: List[float] = []
    stock_block: List[float] = []
    closure_block: List[float] = []
    per_seed = []

    for i in range(n_seeds):
        seed = seed_offset + i
        random.seed(seed)
        events = generate_workload(chains, departments, n_epochs)
        stock = run_condition(chains, policy, events, use_closure=False)

        random.seed(seed)
        events2 = generate_workload(chains, departments, n_epochs)
        assert events == events2
        closure = run_condition(chains, policy, events2, use_closure=True)

        stock_leak.append(stock["leak_rate_pct"])
        closure_leak.append(closure["leak_rate_pct"])
        stock_block.append(stock["block_rate_pct"])
        closure_block.append(closure["block_rate_pct"])
        per_seed.append({"seed": seed, "stock": stock, "closure": closure})

    def _mean(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    def _pstdev(xs: List[float]) -> float:
        if not xs:
            return 0.0
        m = sum(xs) / len(xs)
        variance = sum((x - m) ** 2 for x in xs) / len(xs)
        return round(float(variance**0.5), 2)

    return {
        "n_chains": len(chains),
        "n_departments": len(departments),
        "n_seeds": n_seeds,
        "seed_range": [seed_offset, seed_offset + n_seeds - 1],
        "stock_gate": {
            "leak_rate_mean": _mean(stock_leak),
            "leak_rate_sd": _pstdev(stock_leak),
            "block_rate_mean": _mean(stock_block),
            "block_rate_sd": _pstdev(stock_block),
        },
        "closure_gate": {
            "leak_rate_mean": _mean(closure_leak),
            "leak_rate_sd": _pstdev(closure_leak),
            "block_rate_mean": _mean(closure_block),
            "block_rate_sd": _pstdev(closure_block),
        },
        "per_seed": per_seed,
    }
