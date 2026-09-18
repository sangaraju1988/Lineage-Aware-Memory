"""
Regression test for the unqualified-SQL-column leak (Group C3).

This is the permanent CI guard for the bug PR #1 fixed in
``real_agent/amu_bridge.py`` (commit ``dc8e960``): if a future edit ever
reintroduces the ``if step["table"] != "unknown"`` filter (or otherwise
drops unresolved lineage steps before sensitivity tagging), this test fails
immediately, rather than silently regressing the way the original fix went
unexercised until this build pass.
"""

from __future__ import annotations

from real_agent.northwind_schema import NORTHWIND_PERMISSIONS, NORTHWIND_SENSITIVE

from amu_ext.sql_extraction import QueryCase, evaluate_case

_CASE = QueryCase(
    name="comma_join_homephone_regression",
    sql="SELECT HomePhone, OrderID FROM Employees, Orders WHERE Employees.EmployeeID = Orders.EmployeeID",
    true_sensitive_columns=frozenset({"homephone"}),
    style="comma_join_unqualified",
    description="Regression fixture: unqualified sensitive column in a comma-join.",
)


def test_current_main_does_not_leak_the_comma_join_case() -> None:
    """Exercises the ACTUAL currently-merged extractor (no toggle override
    at the amu_bridge layer -- amu_ext.sql_extraction's default,
    keep_unqualified=True, mirrors what real_agent/amu_bridge.py does on
    main today). If this ever fails, the fix regressed."""
    result = evaluate_case(
        _CASE,
        sensitive_columns=NORTHWIND_SENSITIVE,
        permitted_columns=NORTHWIND_PERMISSIONS["Operations"],
        keep_unqualified=True,
    )
    assert result.leaked is False


def test_pre_fix_toggle_reproduces_the_original_bug() -> None:
    """Confirms the pre-fix toggle genuinely reproduces the bug (a
    meta-regression-test: if this ever starts passing with leaked=False, the
    toggle itself has stopped exercising the bug, which would silently
    defang test_current_main_does_not_leak_the_comma_join_case above)."""
    result = evaluate_case(
        _CASE,
        sensitive_columns=NORTHWIND_SENSITIVE,
        permitted_columns=NORTHWIND_PERMISSIONS["Operations"],
        keep_unqualified=False,
    )
    assert result.leaked is True
