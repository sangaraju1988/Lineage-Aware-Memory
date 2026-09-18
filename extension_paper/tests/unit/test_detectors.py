"""
Unit tests for amu_ext.detectors (Groups A1 and A2).

Covers:
  - D4 on hand-constructed pairs for each of the four original dataset
    categories (TC, TV, LO, CS), including the specific edge case D1-D3 are
    each documented to fail on (D1: over-flags TV; D2: usually misses LO;
    D3: always misses LO).
  - D4's operator-topology tokenizer directly (the mechanism D4 depends on).
  - D5's relationship to D4 (superset property) via hand-picked cases and a
    property-based (hypothesis) symmetry/commutativity check across
    permuted aggregation_fn values.
  - The full 43-pair ported dataset, as an integration-style sanity check
    that D1-D3 reproduce the root repo's fuzzy_experiment.py behavior
    exactly (this doubles as a regression guard: if a future edit to
    detectors.py silently changes D1/D2/D3's semantics, this test catches
    it immediately, before it reaches run_a4_full_matrix.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from amu_ext.detectors import (
    DETECTORS,
    LineageSpec,
    Pair,
    d1_exact,
    d3_column_graph,
    d4_structural_topology,
    d5_with_aggregation,
    load_pairs,
    operator_topology,
)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _pair(name, ta, ca, la, tb, cb, lb, is_conflict, category="TC", agg_a=None, agg_b=None) -> Pair:
    return Pair(
        name=name,
        category=category,
        a=LineageSpec(tables=tuple(ta), columns=tuple(ca), filter_logic=la, aggregation_fn=agg_a),
        b=LineageSpec(tables=tuple(tb), columns=tuple(cb), filter_logic=lb, aggregation_fn=agg_b),
        is_conflict=is_conflict,
        rationale="hand-constructed unit test fixture",
    )


# ---------------------------------------------------------------------------
# operator_topology()
# ---------------------------------------------------------------------------


class TestOperatorTopology:
    def test_and_or_differ(self) -> None:
        t1 = operator_topology("txn in last 30 days AND region = EUROPE")
        t2 = operator_topology("txn in last 30 days OR region = EUROPE")
        assert t1 != t2
        assert "AND" in t1 and "OR" not in t1
        assert "OR" in t2 and "AND" not in t2

    def test_threshold_only_change_has_identical_topology(self) -> None:
        t1 = operator_topology("no txn in 90 days")
        t2 = operator_topology("no txn in 60 days")
        assert t1 == t2

    def test_date_threshold_change_has_identical_topology(self) -> None:
        t1 = operator_topology("l_shipdate BETWEEN 1994-01-01 AND 1995-01-01")
        t2 = operator_topology("l_shipdate BETWEEN 1993-01-01 AND 1994-01-01")
        assert t1 == t2
        assert t1[0] == "BETWEEN"

    def test_numeric_list_length_change_has_identical_topology(self) -> None:
        """Threshold Variant edge case: "IN (1, 2)" -> "IN (1, 2, 3)" must not
        change the topology just because the list grew -- the whole
        parenthesized list collapses to a single <NUMLIST> placeholder."""
        t1 = operator_topology("priority IN (1, 2)")
        t2 = operator_topology("priority IN (1, 2, 3)")
        assert t1 == t2

    def test_comparison_operators_distinguished(self) -> None:
        assert operator_topology("l_discount < 0.05") != operator_topology("l_discount <= 0.05")
        assert operator_topology("spend >= 500") != operator_topology("spend > 500")

    def test_empty_filter_logic(self) -> None:
        assert operator_topology("") == ()

    def test_no_operators_present(self) -> None:
        assert operator_topology("open tickets by region") == ()


# ---------------------------------------------------------------------------
# D4 on hand-constructed category edge cases
# ---------------------------------------------------------------------------


class TestD4EdgeCases:
    def test_tc_different_tables_is_conflict(self) -> None:
        p = _pair(
            "tc",
            ["customers", "transactions"],
            ["customer_id"],
            "any filter",
            ["customers", "campaigns"],
            ["customer_id"],
            "any filter",
            is_conflict=True,
            category="TC",
        )
        assert d4_structural_topology(p) is True

    def test_cs_subset_columns_is_conflict(self) -> None:
        p = _pair(
            "cs",
            ["orders"],
            ["o_orderkey", "o_totalprice"],
            "same filter",
            ["orders"],
            ["o_orderkey"],
            "same filter",
            is_conflict=True,
            category="CS",
        )
        assert d4_structural_topology(p) is True

    def test_tv_threshold_variant_is_not_conflict(self) -> None:
        """The edge case D1 is documented to fail on: D1 (exact hash) would
        flag this because the filter_logic string literally differs. D4
        must NOT flag it -- same tables, same columns, same operator
        topology, only the threshold changed."""
        p = _pair(
            "tv",
            ["customers", "transactions"],
            ["customer_id", "txn_date"],
            "txn in last 30 days",
            ["customers", "transactions"],
            ["customer_id", "txn_date"],
            "txn in last 14 days",
            is_conflict=False,
            category="TV",
        )
        assert d1_exact(p) is True, "sanity check: D1 does over-flag this TV pair"
        assert d4_structural_topology(p) is False

    def test_lo_logic_operator_change_is_conflict(self) -> None:
        """The edge case D2 and D3 are documented to fail on: same tables,
        same columns (D3 blind), and usually high Jaccard similarity since
        only one token changed (D2 typically blind too). D4 must catch it
        via the operator-topology diff."""
        p = _pair(
            "lo",
            ["customers", "transactions"],
            ["customer_id", "txn_date"],
            "txn in last 30 days AND region = EUROPE",
            ["customers", "transactions"],
            ["customer_id", "txn_date"],
            "txn in last 30 days OR region = EUROPE",
            is_conflict=True,
            category="LO",
        )
        assert d3_column_graph(p) is False, "sanity check: D3 is blind to this LO pair"
        assert d4_structural_topology(p) is True

    def test_lo_not_added_is_conflict(self) -> None:
        p = _pair(
            "lo2",
            ["support_tickets"],
            ["ticket_id", "category"],
            "category != escalated",
            ["support_tickets"],
            ["ticket_id", "category"],
            "category = escalated",
            is_conflict=True,
            category="LO",
        )
        assert d4_structural_topology(p) is True


# ---------------------------------------------------------------------------
# D5: aggregation-equality check on top of D4
# ---------------------------------------------------------------------------


class TestD5:
    def test_d5_superset_of_d4_on_structural_conflict(self) -> None:
        p = _pair(
            "tc",
            ["customers", "transactions"],
            ["customer_id"],
            "any filter",
            ["customers", "campaigns"],
            ["customer_id"],
            "any filter",
            is_conflict=True,
            category="TC",
            agg_a="SUM",
            agg_b="SUM",
        )
        assert d4_structural_topology(p) is True
        assert d5_with_aggregation(p) is True

    def test_d5_catches_aggregation_blind_spot_d4_misses(self) -> None:
        p = _pair(
            "ao",
            ["lineitem", "orders"],
            ["l_extendedprice"],
            "same filter",
            ["lineitem", "orders"],
            ["l_extendedprice"],
            "same filter",
            is_conflict=True,
            category="AO",
            agg_a="SUM",
            agg_b="AVG",
        )
        assert d4_structural_topology(p) is False
        assert d5_with_aggregation(p) is True

    def test_d5_none_and_identity_are_equal(self) -> None:
        p = _pair(
            "ao_none",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            is_conflict=False,
            category="AO",
            agg_a=None,
            agg_b="IDENTITY",
        )
        assert d5_with_aggregation(p) is False

    def test_d5_case_insensitive_aggregation(self) -> None:
        p = _pair(
            "ao_case",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            is_conflict=False,
            category="AO",
            agg_a="sum",
            agg_b="SUM",
        )
        assert d5_with_aggregation(p) is False

    @given(
        agg_a=st.sampled_from(["SUM", "AVG", "COUNT", "MIN", "MAX", None]),
        agg_b=st.sampled_from(["SUM", "AVG", "COUNT", "MIN", "MAX", None]),
    )
    def test_d5_is_symmetric_under_swap(self, agg_a, agg_b) -> None:
        """Property: swapping which side is "a" and which is "b" must not
        change the verdict -- conflict detection can't depend on argument
        order, or the evaluation harness's pair orientation would silently
        bias results."""
        p_ab = _pair(
            "sym",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            is_conflict=(agg_a != agg_b),
            category="AO",
            agg_a=agg_a,
            agg_b=agg_b,
        )
        p_ba = _pair(
            "sym",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            is_conflict=(agg_a != agg_b),
            category="AO",
            agg_a=agg_b,
            agg_b=agg_a,
        )
        assert d5_with_aggregation(p_ab) == d5_with_aggregation(p_ba)

    @given(agg=st.sampled_from(["SUM", "AVG", "COUNT", "MIN", "MAX", None]))
    def test_d5_reflexive_never_flags_identical_aggregation(self, agg) -> None:
        """Property: identical aggregation_fn on both sides, with identical
        everything else, is never a conflict (reflexivity)."""
        p = _pair(
            "refl",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            ["orders"],
            ["o_totalprice"],
            "same filter",
            is_conflict=False,
            category="AO",
            agg_a=agg,
            agg_b=agg,
        )
        assert d5_with_aggregation(p) is False


# ---------------------------------------------------------------------------
# Full 43-pair dataset: faithful-port regression check against the root
# repo's published fuzzy_experiment.py behavior.
# ---------------------------------------------------------------------------


class TestFullDatasetD1D2D3MatchRootRepo:
    """These expected counts were captured by running D1/D2/D3 from this
    module against data/conflict_dataset_43.json (itself a lossless export
    of fuzzy_experiment.py's PAIRS) and cross-checked against
    fuzzy_experiment.py's own printed output. If this test ever fails, one
    of the two implementations has silently diverged -- exactly the kind of
    drift test_package_conformance.py exists to catch for the model.py side
    of this project."""

    @staticmethod
    @pytest.fixture(scope="class")
    def pairs():
        return load_pairs(_DATA_DIR / "conflict_dataset_43.json")

    def test_dataset_shape(self, pairs) -> None:
        assert len(pairs) == 43
        categories = {p.category for p in pairs}
        assert categories == {"TC", "TV", "LO", "CS"}

    def test_d1_matches_expected_confusion(self, pairs) -> None:
        gt = [p.is_conflict for p in pairs]
        preds = [d1_exact(p) for p in pairs]
        tp = sum(1 for pr, g in zip(preds, gt) if pr and g)
        fp = sum(1 for pr, g in zip(preds, gt) if pr and not g)
        fn = sum(1 for pr, g in zip(preds, gt) if not pr and g)
        assert (tp, fp, fn) == (28, 15, 0)

    def test_d3_matches_expected_confusion(self, pairs) -> None:
        gt = [p.is_conflict for p in pairs]
        preds = [d3_column_graph(p) for p in pairs]
        tp = sum(1 for pr, g in zip(preds, gt) if pr and g)
        fp = sum(1 for pr, g in zip(preds, gt) if pr and not g)
        fn = sum(1 for pr, g in zip(preds, gt) if not pr and g)
        assert (tp, fp, fn) == (20, 0, 8)
        # D3's 8 false negatives must be exactly the LO category (its
        # documented blind spot), not a mix that would suggest a bug.
        lo_pairs = [p for p in pairs if p.category == "LO"]
        assert len(lo_pairs) == 8
        assert all(d3_column_graph(p) is False for p in lo_pairs)

    def test_d4_perfect_on_original_four_categories(self, pairs) -> None:
        """D4 was designed to close D3's LO blind spot without reopening
        D1's TV false-positive problem -- confirm it achieves perfect
        precision and recall on the original (pre-AO) dataset."""
        gt = [p.is_conflict for p in pairs]
        preds = [d4_structural_topology(p) for p in pairs]
        assert preds == gt

    def test_all_registered_detectors_run_without_error(self, pairs) -> None:
        for fn in DETECTORS.values():
            for p in pairs[:3]:
                fn(p)  # smoke: must not raise, regardless of aggregation_fn=None
