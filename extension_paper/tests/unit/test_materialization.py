"""Unit tests for amu_ext.materialization (Group B)."""

from __future__ import annotations

from amu_governance import Lineage, LineageStep

from amu_ext.materialization import (
    DEPARTMENT_TOPOLOGIES,
    MaterializationRegistry,
    build_chains,
    close_lineage,
    generate_workload,
)


class TestMaterializationRegistry:
    def test_register_and_lookup(self) -> None:
        registry = MaterializationRegistry()
        lineage = Lineage(steps=(LineageStep("t", ("c",)),), filter_logic="f")
        registry.register("derived", "col", lineage)
        assert registry.upstream_of("derived", "col") is lineage

    def test_unregistered_lookup_returns_none(self) -> None:
        registry = MaterializationRegistry()
        assert registry.upstream_of("nope", "nope") is None


class TestCloseLineage:
    def test_no_op_when_no_materialized_columns(self) -> None:
        registry = MaterializationRegistry()
        lineage = Lineage(steps=(LineageStep("transactions", ("customer_id", "amount")),), filter_logic="f")
        assert close_lineage(lineage, registry) == lineage

    def test_expands_one_hop(self) -> None:
        registry = MaterializationRegistry()
        upstream = Lineage(steps=(LineageStep("customer_pii", ("income",)),), filter_logic="base")
        registry.register("derived", "risk_score", upstream)

        downstream = Lineage(steps=(LineageStep("derived", ("risk_score",)),), filter_logic="downstream")
        closed = close_lineage(downstream, registry)

        assert set(closed.all_columns()) == {"risk_score", "income"}
        assert closed.filter_logic == "downstream"  # filter_logic of the OUTER lineage is preserved

    def test_expands_two_hops_recursively(self) -> None:
        registry = MaterializationRegistry()
        tier0 = Lineage(steps=(LineageStep("customer_pii", ("income",)),), filter_logic="tier0")
        registry.register("derived", "risk_score", tier0)
        tier1 = Lineage(steps=(LineageStep("derived", ("risk_score",)),), filter_logic="tier1")
        registry.register("derived2", "risk_bucket", tier1)

        downstream = Lineage(steps=(LineageStep("derived2", ("risk_bucket",)),), filter_logic="tier2")
        closed = close_lineage(downstream, registry)

        assert set(closed.all_columns()) == {"risk_bucket", "risk_score", "income"}

    def test_max_depth_guard_prevents_infinite_recursion(self) -> None:
        """A cyclic registry (which should never occur in a real pipeline,
        but the guard exists for robustness) must not hang."""
        registry = MaterializationRegistry()
        a = Lineage(steps=(LineageStep("b_table", ("b_col",)),), filter_logic="a")
        b = Lineage(steps=(LineageStep("a_table", ("a_col",)),), filter_logic="b")
        registry.register("a_table", "a_col", a)
        registry.register("b_table", "b_col", b)

        result = close_lineage(a, registry, _max_depth=4)
        assert isinstance(result, Lineage)  # must terminate, not raise/hang


class TestBuildChains:
    def test_single_chain(self) -> None:
        chains = build_chains(1)
        assert len(chains) == 1
        assert next(iter(chains.values())).sensitive is True  # chain 0 is always sensitive

    def test_two_chains_reproduces_pr1_semantics(self) -> None:
        chains = build_chains(2)
        assert len(chains) == 2
        sensitive_chains = [c for c in chains.values() if c.sensitive]
        safe_chains = [c for c in chains.values() if not c.sensitive]
        assert len(sensitive_chains) == 1
        assert len(safe_chains) == 1
        assert sensitive_chains[0].materialized_column == "risk_score"
        assert sensitive_chains[0].downstream_metric == "high_risk_customers"
        assert sensitive_chains[0].downstream_filter == "risk_score > 0.8"
        assert safe_chains[0].materialized_column == "txn_band"
        assert safe_chains[0].downstream_filter == "txn_band = 'high'"

    def test_alternates_sensitive_and_safe(self) -> None:
        chains = list(build_chains(6).values())
        for i, c in enumerate(chains):
            assert c.sensitive == (i % 2 == 0)

    def test_chain_names_unique(self) -> None:
        chains = build_chains(10)
        assert len(chains) == len(set(chains.keys())) == 10

    def test_invalid_n_chains_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            build_chains(0)


class TestDepartmentTopologies:
    def test_3dept_topology(self) -> None:
        policy = DEPARTMENT_TOPOLOGIES["3dept"]
        assert set(policy.department_permissions) == {"Finance", "Marketing", "Support"}
        assert "income" in policy.permitted_columns("Finance")
        assert "income" not in policy.permitted_columns("Marketing")

    def test_5dept_topology_has_graded_access(self) -> None:
        policy = DEPARTMENT_TOPOLOGIES["5dept"]
        assert len(policy.department_permissions) == 5
        # Analytics: partial access (income only, not ssn/email)
        analytics = policy.permitted_columns("Analytics")
        assert "income" in analytics
        assert "ssn" not in analytics
        assert "email" not in analytics


class TestGenerateWorkload:
    def test_deterministic_given_seed(self) -> None:
        import random

        chains = build_chains(3)
        departments = ["Finance", "Marketing", "Support"]

        random.seed(7)
        events_a = generate_workload(chains, departments, n_epochs=10)
        random.seed(7)
        events_b = generate_workload(chains, departments, n_epochs=10)
        assert events_a == events_b

    def test_event_count_matches_epochs(self) -> None:
        import random

        chains = build_chains(2)
        random.seed(1)
        events = generate_workload(chains, ["Finance", "Marketing"], n_epochs=15)
        assert len(events) == 15
