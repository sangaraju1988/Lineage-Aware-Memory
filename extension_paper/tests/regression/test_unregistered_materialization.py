"""
Regression test for Group B3: proving the boundary of the closure guarantee,
not just the fix.

``docs/threat_model_extension.md`` Section 3.2 states, in prose, that
transitive closure only restores the safety guarantee for *registered*
materialization edges -- an unregistered one (a materialized column
produced outside this system's write path, e.g. a warehouse-managed
materialized view or an ad hoc `CREATE TABLE AS SELECT`) reproduces the
original leak exactly, closure or no closure. This test makes that a real,
executed assertion instead of a claim resting on prose alone: it
constructs a materialization edge that is deliberately never registered,
and confirms ``close_lineage`` does not (cannot) catch it.
"""

from __future__ import annotations

from amu_governance import AMU, GovernancePolicy, Lineage, LineageAwareSystem, LineageStep

from amu_ext.materialization import MaterializationRegistry, close_lineage

_POLICY = GovernancePolicy(
    sensitive_columns={"income"},
    department_permissions={
        "Finance": {"customer_id", "income", "risk_score"},
        "Marketing": {"customer_id"},  # no income access
    },
)


def _build_income_derived_risk_score() -> Lineage:
    return Lineage(
        steps=(LineageStep("customer_pii", ("customer_id", "income")),),
        filter_logic="income-weighted risk model v1",
    )


class TestUnregisteredMaterializationBoundary:
    def test_closure_does_not_catch_an_unregistered_edge(self) -> None:
        """The materialization DID happen (risk_score really is
        income-derived) -- but nobody called registry.register(...) for it,
        the realistic case of an out-of-band ETL job or warehouse-managed
        materialized view. close_lineage has nothing to expand against, so
        the downstream AMU's lineage is returned unchanged, and the leak
        from Section 1 of the threat model doc reproduces exactly."""
        registry = MaterializationRegistry()
        # Deliberately NOT registered:
        #   base_lineage = _build_income_derived_risk_score()
        #   registry.register("derived_features", "risk_score", base_lineage)

        downstream_lineage = Lineage(
            steps=(LineageStep("derived_features", ("risk_score",)),),
            filter_logic="risk_score > 0.8",
        )
        closed = close_lineage(downstream_lineage, registry)

        assert (
            closed == downstream_lineage
        ), "closure must be a no-op when there is no registered edge to walk"
        assert closed.sensitive_columns(_POLICY) == set(), (
            "without a registered provenance edge, the closed lineage still "
            "has no way to know risk_score is income-derived"
        )

    def test_leak_rate_stays_above_zero_end_to_end(self) -> None:
        """Full end-to-end version of the same point, through the real
        LineageAwareSystem: Marketing requests the downstream metric and IS
        served it, because even WITH closure applied, an unregistered edge
        gives closure nothing to close."""
        system = LineageAwareSystem(_POLICY)
        registry = MaterializationRegistry()

        base_lineage = _build_income_derived_risk_score()
        base_amu = AMU(
            metric_name="risk_score_base",
            value=1.0,
            owner_department="Finance",
            lineage=base_lineage,
            epoch=0,
        )
        system.write(base_amu)
        # No registry.register call here -- this is the point of the test.

        downstream_lineage = close_lineage(
            Lineage(
                steps=(LineageStep("derived_features", ("risk_score",)),), filter_logic="risk_score > 0.8"
            ),
            registry,
        )
        downstream_amu = AMU(
            metric_name="high_risk_customers",
            value=1.0,
            owner_department="Finance",
            lineage=downstream_lineage,
            epoch=0,
        )
        system.write(downstream_amu)

        result = system.request("high_risk_customers", "Marketing", downstream_amu)

        assert result.reused is True, "the gate has no signal to block on, so it serves the request"
        assert result.leaked is False, (
            "note: LineageAwareSystem.leaked is always False by construction "
            "(RetrievalResult.leaked reflects the gate's OWN bookkeeping, not "
            "ground truth) -- the actual leak is verified independently below "
            "against ground truth, exactly as adversarial_lineage_experiment.py "
            "does it, since 'leaked' as the gate reports it is not the right "
            "ground-truth signal here."
        )

        true_sensitive_cols = base_lineage.sensitive_columns(_POLICY)
        permitted = _POLICY.permitted_columns("Marketing")
        would_actually_leak = bool(true_sensitive_cols - permitted) and result.reused
        assert would_actually_leak is True, (
            "ground truth: Marketing does not have income access, income WAS "
            "used to derive the served value, and the value WAS served -- "
            "this is a real leak that closure, with an unregistered edge, "
            "cannot close. This is the experiment that substantiates the "
            "limitation sentence in docs/limitations.md."
        )

    def test_registered_edge_for_comparison_does_close(self) -> None:
        """Positive control, side by side with the negative case above: the
        SAME scenario, but with the edge registered, closes correctly --
        confirming the difference in the two tests above is really about
        registration, not some other variable."""
        system = LineageAwareSystem(_POLICY)
        registry = MaterializationRegistry()

        base_lineage = _build_income_derived_risk_score()
        base_amu = AMU(
            metric_name="risk_score_base",
            value=1.0,
            owner_department="Finance",
            lineage=base_lineage,
            epoch=0,
        )
        system.write(base_amu)
        registry.register("derived_features", "risk_score", base_lineage)  # the only difference

        downstream_lineage = close_lineage(
            Lineage(
                steps=(LineageStep("derived_features", ("risk_score",)),), filter_logic="risk_score > 0.8"
            ),
            registry,
        )
        downstream_amu = AMU(
            metric_name="high_risk_customers",
            value=1.0,
            owner_department="Finance",
            lineage=downstream_lineage,
            epoch=0,
        )
        system.write(downstream_amu)

        result = system.request("high_risk_customers", "Marketing", downstream_amu)

        assert (
            result.reused is False
        ), "the registered edge lets the gate see income and block the stale/unsafe path"
        assert result.blocked is True
