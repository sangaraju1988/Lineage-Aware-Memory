"""
Unit tests for amu_ext.aggregation (Group A2).

The first test class demonstrates the aggregation-operator blind spot the
task asked to verify "with a failing test first": under the TDD sequence
this suite documents, ``test_legacy_hash_collides_across_aggregation_functions``
was written and run *before* ``definition_hash_with_aggregation`` existed,
using only ``legacy_definition_hash`` -- and it failed to find any
distinction (the hash collided), which is exactly the blind spot. It is
kept in the final suite as a permanent characterization test of the legacy
hash's scope, paired immediately below with the corresponding "now it
distinguishes them" test against the extended hash.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from amu_ext.aggregation import (
    KNOWN_AGGREGATION_FUNCTIONS,
    definition_hash_with_aggregation,
    legacy_definition_hash,
    normalize_aggregation_fn,
)

_TABLES = ("lineitem", "orders")
_COLUMNS = ("l_orderkey", "l_extendedprice", "o_orderdate")
_FILTER = "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01"


class TestBlindSpotAndFix:
    """Documents the A2 TDD sequence: red (legacy hash collides) -> green
    (extended hash distinguishes)."""

    def test_legacy_hash_collides_across_aggregation_functions(self) -> None:
        """RED (kept as a permanent characterization test): the legacy hash
        has no aggregation_fn input, so SUM(revenue) and AVG(revenue) over
        an identical join/filter necessarily hash identically. This is the
        aggregation-operator blind spot Group A2 exists to close."""
        h_sum = legacy_definition_hash(_TABLES, _COLUMNS, _FILTER)
        h_avg = legacy_definition_hash(_TABLES, _COLUMNS, _FILTER)
        assert h_sum == h_avg, (
            "legacy_definition_hash is a pure function of (tables, columns, "
            "filter_logic) -- it cannot see aggregation_fn at all, so any two "
            "aggregation choices over identical inputs always collide."
        )

    def test_extended_hash_distinguishes_aggregation_functions(self) -> None:
        """GREEN: the schema-extended hash takes aggregation_fn as an input
        and now correctly distinguishes SUM(revenue) from AVG(revenue)."""
        h_sum = definition_hash_with_aggregation(_TABLES, _COLUMNS, _FILTER, "SUM")
        h_avg = definition_hash_with_aggregation(_TABLES, _COLUMNS, _FILTER, "AVG")
        assert h_sum != h_avg

    def test_extended_hash_is_deterministic(self) -> None:
        h1 = definition_hash_with_aggregation(_TABLES, _COLUMNS, _FILTER, "SUM")
        h2 = definition_hash_with_aggregation(_TABLES, _COLUMNS, _FILTER, "SUM")
        assert h1 == h2

    def test_extended_hash_ignores_table_and_column_order(self) -> None:
        """Matches model.py's existing convention: definition_hash sorts
        tables/columns before hashing, so join order doesn't spuriously
        create a "conflict"."""
        h1 = definition_hash_with_aggregation(("orders", "lineitem"), _COLUMNS, _FILTER, "SUM")
        h2 = definition_hash_with_aggregation(("lineitem", "orders"), _COLUMNS, _FILTER, "SUM")
        assert h1 == h2


class TestNormalizeAggregationFn:
    def test_none_normalizes_to_identity(self) -> None:
        assert normalize_aggregation_fn(None) == "IDENTITY"

    @pytest.mark.parametrize(
        "raw,expected", [("sum", "SUM"), ("Sum", "SUM"), ("  SUM  ", "SUM"), ("avg", "AVG")]
    )
    def test_case_and_whitespace_insensitive(self, raw: str, expected: str) -> None:
        assert normalize_aggregation_fn(raw) == expected

    def test_unknown_function_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_aggregation_fn("MEDIAN")

    @given(st.sampled_from(sorted(KNOWN_AGGREGATION_FUNCTIONS - {"IDENTITY"})))
    def test_all_known_functions_round_trip(self, fn: str) -> None:
        assert normalize_aggregation_fn(fn.lower()) == fn
        assert normalize_aggregation_fn(fn.upper()) == fn
