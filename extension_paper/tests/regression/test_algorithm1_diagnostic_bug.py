"""
Regression test for the Algorithm 1 diagnostic-flag bug (Group C4).

Bug: in ``LineageAwareSystem.request()`` (Algorithm 1's retrieval gate, in
both the root repo's ``systems.py`` and the ``amu_governance`` package), the
branch taken when a safe candidate *is* found hardcoded
``RetrievalResult(..., blocked=False)``, discarding the ``any_blocked`` flag
that had already been set ``True`` earlier in the same loop if an unsafe
(gate-blocking) candidate was skipped before an older, safe candidate was
found.

This never affected safety: ``leaked`` was correctly ``False`` in that
branch either way (a safe candidate was, definitionally, served). It did
undercount the ``blocked`` statistic -- any retrieval that *should* have
reported "at least one candidate was blocked by governance, but an older
safe one covered the request" instead silently reported no blocking at all.
That statistic feeds directly into the block-rate numbers ``simulate.py``,
``degradation_experiment.py``, and this extension's Group B experiments
report.

This test constructs the exact scenario the bug required: write an unsafe
(gate-blocking) AMU for a metric, then a newer safe AMU for the same
metric, then request it as a department that cannot see the unsafe one --
the safe, newer AMU is served (reused=True, leaked=False), but ``blocked``
must be True, since an unsafe candidate *was* encountered and skipped along
the way.
"""

from __future__ import annotations

from amu_governance import AMU as NewAMU
from amu_governance import GovernancePolicy
from amu_governance import Lineage as NewLineage
from amu_governance import LineageAwareSystem as NewLineageAwareSystem
from amu_governance import LineageStep as NewLineageStep
from model import AMU, DEPARTMENT_PERMISSIONS, SENSITIVE_COLUMNS, Lineage, LineageStep
from systems import LineageAwareSystem


def _build_scenario_root():
    """Two AMUs for the same metric: an OLDER one that touches `income`
    (blocked for Marketing), then a NEWER one that does not (servable).
    `request()` scans most-recent-first, so it must skip the blocked one
    before landing on the safe one -- setting any_blocked=True along the way."""
    system = LineageAwareSystem()

    blocked_lineage = Lineage(
        steps=(LineageStep("customer_pii", ("customer_id", "income")),),
        filter_logic="income-adjusted variant",
    )
    blocked_amu = AMU(
        metric_name="risk_metric",
        value=1.0,
        owner_department="Finance",
        lineage=blocked_lineage,
        epoch=0,
    )

    safe_lineage = Lineage(
        steps=(LineageStep("transactions", ("customer_id", "amount")),),
        filter_logic="transaction-only variant",
    )
    safe_amu = AMU(
        metric_name="risk_metric",
        value=2.0,
        owner_department="Finance",
        lineage=safe_lineage,
        epoch=1,
    )

    system.write(blocked_amu)  # older
    system.write(safe_amu)  # newer -- reversed(candidates) visits this FIRST... see note below

    return system


class TestAlgorithm1DiagnosticFlag:
    def test_blocked_true_when_unsafe_candidate_precedes_safe_one(self) -> None:
        """The bug requires the SAFE candidate to be found *after* skipping
        an unsafe one in the reversed (most-recent-first) scan. `write()`
        appends, and `request()` iterates `reversed(candidates)`, so the
        unsafe candidate must be the MORE RECENT of the two for the scan to
        hit it first and set any_blocked=True before reaching the safe,
        older one."""
        system = LineageAwareSystem()

        safe_lineage = Lineage(
            steps=(LineageStep("transactions", ("customer_id", "amount")),),
            filter_logic="transaction-only variant",
        )
        safe_amu = AMU(
            metric_name="risk_metric",
            value=1.0,
            owner_department="Finance",
            lineage=safe_lineage,
            epoch=0,
        )

        blocked_lineage = Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "income")),),
            filter_logic="income-adjusted variant",
        )
        blocked_amu = AMU(
            metric_name="risk_metric",
            value=2.0,
            owner_department="Finance",
            lineage=blocked_lineage,
            epoch=1,
        )

        system.write(safe_amu)  # older, written first
        system.write(blocked_amu)  # newer, written second -- scanned FIRST by reversed()

        fresh = AMU(
            metric_name="risk_metric",
            value=3.0,
            owner_department="Marketing",
            lineage=safe_lineage,
            epoch=2,
        )
        result = system.request("risk_metric", "Marketing", fresh)

        assert result.reused is True, "the safe (older) candidate should still be served"
        assert result.leaked is False, "safety was never affected by this bug"
        assert result.blocked is True, (
            "the newer, unsafe candidate was skipped along the way -- `blocked` "
            "must report that, not silently discard it because a safe candidate "
            "was eventually found"
        )

    def test_amu_governance_package_has_the_same_fix(self) -> None:
        """Mirrors the test above against the amu_governance package, to
        confirm the fix was applied there too (not just root systems.py) --
        this is the conformance-adjacent check C4 asks for."""
        policy = GovernancePolicy(
            sensitive_columns=set(SENSITIVE_COLUMNS),
            department_permissions={k: set(v) for k, v in DEPARTMENT_PERMISSIONS.items()},
        )
        system = NewLineageAwareSystem(policy)

        safe_lineage = NewLineage(
            steps=(NewLineageStep("transactions", ("customer_id", "amount")),),
            filter_logic="transaction-only variant",
        )
        safe_amu = NewAMU(
            metric_name="risk_metric",
            value=1.0,
            owner_department="Finance",
            lineage=safe_lineage,
            epoch=0,
        )

        blocked_lineage = NewLineage(
            steps=(NewLineageStep("customer_pii", ("customer_id", "income")),),
            filter_logic="income-adjusted variant",
        )
        blocked_amu = NewAMU(
            metric_name="risk_metric",
            value=2.0,
            owner_department="Finance",
            lineage=blocked_lineage,
            epoch=1,
        )

        system.write(safe_amu)
        system.write(blocked_amu)

        fresh = NewAMU(
            metric_name="risk_metric",
            value=3.0,
            owner_department="Marketing",
            lineage=safe_lineage,
            epoch=2,
        )
        result = system.request("risk_metric", "Marketing", fresh)

        assert result.reused is True
        assert result.leaked is False
        assert result.blocked is True

    def test_still_false_when_no_candidate_was_ever_blocked(self) -> None:
        """Negative control: when no unsafe candidate was ever skipped,
        blocked must remain False -- the fix must not turn `blocked` into
        an always-True flag."""
        system = LineageAwareSystem()
        safe_lineage = Lineage(
            steps=(LineageStep("transactions", ("customer_id", "amount")),),
            filter_logic="transaction-only variant",
        )
        amu = AMU(
            metric_name="clean_metric", value=1.0, owner_department="Finance", lineage=safe_lineage, epoch=0
        )
        system.write(amu)

        fresh = AMU(
            metric_name="clean_metric", value=2.0, owner_department="Marketing", lineage=safe_lineage, epoch=1
        )
        result = system.request("clean_metric", "Marketing", fresh)

        assert result.reused is True
        assert result.blocked is False
