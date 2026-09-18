"""Unit tests for amu_ext.sql_extraction (Group C3)."""

from __future__ import annotations

from amu_ext.sql_extraction import (
    lineage_steps_from_sql,
    sensitivity_tags_from_steps,
    would_leak,
)

_SENSITIVE = {"homephone", "birthdate", "unitprice", "freight"}
_OPERATIONS_PERMITTED = {"orderid", "customerid", "quantity", "productname"}  # excludes all 4 sensitive cols

_COMMA_JOIN_SQL = (
    "SELECT HomePhone, OrderID FROM Employees, Orders WHERE Employees.EmployeeID = Orders.EmployeeID"
)
_QUALIFIED_SQL = "SELECT e.HomePhone, o.OrderID FROM Employees e JOIN Orders o ON e.EmployeeID = o.EmployeeID"
_SINGLE_TABLE_SQL = "SELECT HomePhone, LastName FROM Employees WHERE EmployeeID = 5"


class TestLineageStepsFromSql:
    def test_post_fix_keeps_unknown_bucket(self) -> None:
        steps = lineage_steps_from_sql(_COMMA_JOIN_SQL, keep_unqualified=True)
        tables = {s["table"] for s in steps}
        assert "unknown" in tables
        unknown_step = next(s for s in steps if s["table"] == "unknown")
        assert "homephone" in unknown_step["columns"]

    def test_pre_fix_drops_unknown_bucket(self) -> None:
        steps = lineage_steps_from_sql(_COMMA_JOIN_SQL, keep_unqualified=False)
        tables = {s["table"] for s in steps}
        assert "unknown" not in tables
        all_cols = {c for s in steps for c in s["columns"]}
        assert (
            "homephone" not in all_cols
        ), "pre-fix behavior must silently drop the unqualified sensitive column"

    def test_fully_qualified_query_unaffected_by_toggle(self) -> None:
        pre = lineage_steps_from_sql(_QUALIFIED_SQL, keep_unqualified=False)
        post = lineage_steps_from_sql(_QUALIFIED_SQL, keep_unqualified=True)
        assert pre == post, "a fully-qualified query has no 'unknown' bucket, so the toggle is a no-op"

    def test_single_table_query_unaffected_by_toggle(self) -> None:
        pre = lineage_steps_from_sql(_SINGLE_TABLE_SQL, keep_unqualified=False)
        post = lineage_steps_from_sql(_SINGLE_TABLE_SQL, keep_unqualified=True)
        assert (
            pre == post
        ), "single-table queries resolve via the extractor's own heuristic, not the 'unknown' bucket"


class TestSensitivityTagsFromSteps:
    def test_picks_up_unknown_bucket_columns(self) -> None:
        steps = lineage_steps_from_sql(_COMMA_JOIN_SQL, keep_unqualified=True)
        tags = sensitivity_tags_from_steps(steps, _SENSITIVE)
        assert tags == {"homephone"}

    def test_misses_when_unknown_bucket_dropped(self) -> None:
        steps = lineage_steps_from_sql(_COMMA_JOIN_SQL, keep_unqualified=False)
        tags = sensitivity_tags_from_steps(steps, _SENSITIVE)
        assert tags == set()


class TestWouldLeak:
    def test_leak_when_extraction_misses_unpermitted_sensitive_column(self) -> None:
        assert (
            would_leak(
                {"homephone"}, extracted_sensitivity_tags=set(), permitted_columns=_OPERATIONS_PERMITTED
            )
            is True
        )

    def test_no_leak_when_extraction_catches_it(self) -> None:
        assert (
            would_leak(
                {"homephone"},
                extracted_sensitivity_tags={"homephone"},
                permitted_columns=_OPERATIONS_PERMITTED,
            )
            is False
        )

    def test_no_leak_when_requester_is_permitted_anyway(self) -> None:
        assert (
            would_leak(
                {"quantity"}, extracted_sensitivity_tags=set(), permitted_columns=_OPERATIONS_PERMITTED
            )
            is False
        )

    def test_no_leak_when_no_sensitive_columns_touched(self) -> None:
        assert (
            would_leak(set(), extracted_sensitivity_tags=set(), permitted_columns=_OPERATIONS_PERMITTED)
            is False
        )

    def test_partial_extraction_still_leaks(self) -> None:
        """Extracting SOME but not all truly-unpermitted sensitive columns is
        still a leak -- any missed column is a leak of that column."""
        assert (
            would_leak(
                {"homephone", "birthdate"},
                extracted_sensitivity_tags={"homephone"},
                permitted_columns=_OPERATIONS_PERMITTED,
            )
            is True
        )
