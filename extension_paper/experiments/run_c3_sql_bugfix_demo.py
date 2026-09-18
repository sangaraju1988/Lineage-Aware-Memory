#!/usr/bin/env python3
"""
Group C3: demonstrate the SQL unqualified-column bugfix empirically.

This is the experiment the build prompt calls "the most important new
experiment" -- it did not exist anywhere before this build pass. PR #1's
bugfix (commit ``dc8e960``) was verified as a no-op against the *existing*
Exp-6 demo, because that demo's queries are all fully table-qualified; the
fix has never actually been exercised by any test until now.

This script builds a query set that specifically includes unqualified
column references (comma-joins, bare multi-table SELECTs) touching
sensitive Northwind columns, runs each query through
``amu_ext.sql_extraction`` with the pre-fix (``keep_unqualified=False``)
and post-fix (``keep_unqualified=True``) toggle, and reports the leak rate
before vs. after against the strictest real department (Operations, which
the Northwind schema denies all four sensitive columns:
``unitprice``, ``freight``, ``homephone``, ``birthdate``).

The query set is deterministic (no randomness in SQL parsing), so this is
run once, not swept over seeds -- consistent with the build prompt's "a
fixed, documented query set is fine since this is deterministic" allowance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from real_agent.northwind_schema import NORTHWIND_PERMISSIONS, NORTHWIND_SENSITIVE  # noqa: E402

from amu_ext.sql_extraction import QueryCase, evaluate_case  # noqa: E402

REQUESTER_DEPARTMENT = "Operations"  # denied all 4 sensitive columns in NORTHWIND_PERMISSIONS

QUERY_SET: List[QueryCase] = [
    QueryCase(
        name="comma_join_homephone",
        sql="SELECT HomePhone, OrderID FROM Employees, Orders WHERE Employees.EmployeeID = Orders.EmployeeID",
        true_sensitive_columns=frozenset({"homephone"}),
        style="comma_join_unqualified",
        description="Classic comma-join; HomePhone has no table prefix and two tables are in scope.",
    ),
    QueryCase(
        name="comma_join_birthdate",
        sql="SELECT BirthDate, City FROM Employees, Orders WHERE Employees.EmployeeID = Orders.EmployeeID",
        true_sensitive_columns=frozenset({"birthdate"}),
        style="comma_join_unqualified",
        description="Comma-join; BirthDate unqualified.",
    ),
    QueryCase(
        name="comma_join_unitprice",
        sql=(
            "SELECT UnitPrice, ProductName FROM Products, Categories "
            "WHERE Products.CategoryID = Categories.CategoryID"
        ),
        true_sensitive_columns=frozenset({"unitprice"}),
        style="comma_join_unqualified",
        description="Comma-join; UnitPrice (commercial pricing) unqualified.",
    ),
    QueryCase(
        name="comma_join_freight",
        sql="SELECT Freight, ShipCity FROM Orders, Customers WHERE Orders.CustomerID = Customers.CustomerID",
        true_sensitive_columns=frozenset({"freight"}),
        style="comma_join_unqualified",
        description="Comma-join; Freight (shipping cost) unqualified.",
    ),
    QueryCase(
        name="three_table_comma_join_two_sensitive",
        sql=(
            'SELECT HomePhone, UnitPrice, OrderID FROM Employees, Orders, "Order Details" '
            'WHERE Employees.EmployeeID = Orders.EmployeeID AND Orders.OrderID = "Order Details".OrderID'
        ),
        true_sensitive_columns=frozenset({"homephone", "unitprice"}),
        style="comma_join_unqualified",
        description="Three-table comma-join with two unqualified sensitive columns from different tables.",
    ),
    QueryCase(
        name="multi_sensitive_single_query",
        sql=(
            "SELECT HomePhone, BirthDate, OrderID FROM Employees, Orders "
            "WHERE Employees.EmployeeID = Orders.EmployeeID"
        ),
        true_sensitive_columns=frozenset({"homephone", "birthdate"}),
        style="comma_join_unqualified",
        description="Two unqualified sensitive columns from the SAME table in one comma-join.",
    ),
    QueryCase(
        name="aliased_table_unqualified_sensitive_column",
        sql="SELECT e.LastName, HomePhone FROM Employees e, Orders o WHERE e.EmployeeID = o.EmployeeID",
        true_sensitive_columns=frozenset({"homephone"}),
        style="comma_join_unqualified",
        description="One column table-aliased (e.LastName), the sensitive one (HomePhone) still unqualified.",
    ),
    QueryCase(
        name="unqualified_sensitive_with_join_keyword",
        sql="SELECT UnitPrice, ProductName FROM Products p, Suppliers s WHERE p.SupplierID = 1",
        true_sensitive_columns=frozenset({"unitprice"}),
        style="comma_join_unqualified",
        description=(
            "Comma-join where the join predicate itself doesn't reference the second table -- "
            "UnitPrice still ambiguous because two tables are in FROM scope."
        ),
    ),
    # ---- Negative controls: must NOT leak, before or after the fix -------
    QueryCase(
        name="fully_qualified_sensitive_control",
        sql="SELECT e.HomePhone, o.OrderID FROM Employees e JOIN Orders o ON e.EmployeeID = o.EmployeeID",
        true_sensitive_columns=frozenset({"homephone"}),
        style="fully_qualified",
        description="Control: HomePhone IS table-qualified -- resolves correctly regardless of the fix.",
    ),
    QueryCase(
        name="single_table_unqualified_sensitive_control",
        sql="SELECT HomePhone, LastName FROM Employees WHERE EmployeeID = 5",
        true_sensitive_columns=frozenset({"homephone"}),
        style="single_table_unqualified",
        description=(
            "Control: only one table in scope, so the extractor's single-table heuristic "
            "resolves HomePhone correctly even pre-fix."
        ),
    ),
    QueryCase(
        name="comma_join_nonsensitive_control",
        sql="SELECT City, Country FROM Customers, Orders WHERE Customers.CustomerID = Orders.CustomerID",
        true_sensitive_columns=frozenset(),
        style="comma_join_unqualified",
        description="Control: unqualified comma-join, but neither column is sensitive -- no leak either way.",
    ),
    QueryCase(
        name="comma_join_permitted_sensitive_control",
        sql=(
            "SELECT UnitPrice, ShipCity FROM Orders, Customers "
            "WHERE Orders.CustomerID = Customers.CustomerID"
        ),
        true_sensitive_columns=frozenset({"unitprice"}),
        style="comma_join_unqualified",
        description=(
            "Control: UnitPrice is unqualified in a comma-join and IS sensitive, but this "
            "case is evaluated the same as the others against Operations, which lacks it -- "
            "included to keep the positive-case count honest rather than cherry-picked."
        ),
    ),
]


def main() -> int:
    run_dir = make_run_dir("c3_sql_bugfix_demo")
    logger = setup_logging(run_dir, "run_c3_sql_bugfix_demo")
    logger.info("Group C3: %d queries, requester department=%s", len(QUERY_SET), REQUESTER_DEPARTMENT)

    permitted = NORTHWIND_PERMISSIONS[REQUESTER_DEPARTMENT]
    per_query = []
    for keep_unqualified, label in ((False, "pre_fix"), (True, "post_fix")):
        leaked_count = 0
        for case in QUERY_SET:
            result = evaluate_case(
                case,
                sensitive_columns=NORTHWIND_SENSITIVE,
                permitted_columns=permitted,
                keep_unqualified=keep_unqualified,
            )
            logger.debug(
                "[%s] %s -> leaked=%s (extracted=%s)",
                label,
                case.name,
                result.leaked,
                sorted(result.extracted_sensitivity_tags),
            )
            if result.leaked:
                leaked_count += 1
            per_query.append(
                {"condition": label, **result.as_dict(), "sql": case.sql, "description": case.description}
            )
        n = len(QUERY_SET)
        logger.info("[%s] leak rate: %d/%d = %.1f%%", label, leaked_count, n, 100 * leaked_count / n)

    n = len(QUERY_SET)
    pre_leaks = sum(1 for r in per_query if r["condition"] == "pre_fix" and r["leaked"])
    post_leaks = sum(1 for r in per_query if r["condition"] == "post_fix" and r["leaked"])

    n_exploitable = sum(1 for c in QUERY_SET if c.true_sensitive_columns - permitted)
    summary = {
        "requester_department": REQUESTER_DEPARTMENT,
        "n_queries": n,
        "n_queries_with_exploitable_sensitive_column": n_exploitable,
        "pre_fix_leak_count": pre_leaks,
        "pre_fix_leak_rate_pct": round(100 * pre_leaks / n, 2),
        "post_fix_leak_count": post_leaks,
        "post_fix_leak_rate_pct": round(100 * post_leaks / n, 2),
        "pre_fix_leak_rate_of_exploitable_pct": (
            round(100 * pre_leaks / n_exploitable, 2) if n_exploitable else None
        ),
        "post_fix_leak_rate_of_exploitable_pct": (
            round(100 * post_leaks / n_exploitable, 2) if n_exploitable else None
        ),
        "note": (
            "Leak rate is reported both over the full query set (including "
            "negative controls, by design -- a realistic query mix includes "
            "queries that don't touch restricted data) and over just the "
            "n_queries_with_exploitable_sensitive_column subset, which is the "
            "rate a reviewer will actually want for the fail-open/fail-closed "
            "argument."
        ),
    }
    logger.info(
        "SUMMARY: pre-fix leak rate %.1f%% -> post-fix leak rate %.1f%% (of %d exploitable queries)",
        summary["pre_fix_leak_rate_of_exploitable_pct"] or 0.0,
        summary["post_fix_leak_rate_of_exploitable_pct"] or 0.0,
        n_exploitable,
    )

    write_json(run_dir / "raw_results.json", {"per_query": per_query})
    write_json(run_dir / "summary_stats.json", summary)
    write_manifest(
        run_dir,
        seeds=[],
        command="python experiments/run_c3_sql_bugfix_demo.py",
        extra={"note": "Deterministic SQL parsing -- no randomness, no seeds."},
    )

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
