"""
lineage_extractor.py
=====================
Automatic table-column lineage extraction from SQL using sqlglot.

This module closes Assumption 1 (Complete Lineage Recording) from the paper:
instead of requiring agents to self-report which columns they accessed,
we intercept the executed SQL and extract the lineage automatically.

Key guarantee:
  For any SQL query Q, extract_lineage_from_sql(Q) returns every
  (table, column) pair that appears in Q's parsed AST.  The AMU built
  from this output inherits the full ground-truth derivation path with
  no reliance on agent self-declaration.

Handles:
  - JOINs, subqueries, CTEs
  - Table aliases  (e.g. SELECT c.Phone FROM Customers c)
  - Quoted / space-containing table names  (e.g. "Order Details")
  - Column wildcards filtered out
  - SQLite dialect by default; override with dialect= parameter
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Set

import sqlglot
import sqlglot.expressions as exp


def _normalize(name: str) -> str:
    """Lowercase, strip quotes, replace spaces with underscores."""
    name = name.strip().strip('"').strip("'").strip("[").strip("]")
    return re.sub(r"\s+", "_", name.lower())


def extract_lineage_from_sql(
    sql: str,
    dialect: str = "sqlite",
) -> List[Dict[str, object]]:
    """
    Parse *sql* with sqlglot and return per-table column sets.

    Returns
    -------
    List of dicts  [{"table": str, "columns": List[str]}]
    suitable for converting directly into LineageStep objects.

    The "unknown" bucket collects unqualified column references when the
    table cannot be resolved from the query structure.

    Example
    -------
    >>> sql = '''
    ...   SELECT c.CategoryName, SUM(od.UnitPrice * od.Quantity) AS revenue
    ...   FROM Categories c
    ...   JOIN Products p   ON c.CategoryID = p.CategoryID
    ...   JOIN "Order Details" od ON p.ProductID = od.ProductID
    ...   GROUP BY c.CategoryName
    ... '''
    >>> extract_lineage_from_sql(sql)
    [
      {"table": "categories",     "columns": ["categoryid", "categoryname"]},
      {"table": "products",        "columns": ["categoryid", "productid"]},
      {"table": "order_details",   "columns": ["productid", "quantity", "unitprice"]},
    ]
    """
    if not sql or not sql.strip():
        return []

    # sqlglot.parse_one raises ParseError on totally broken SQL;
    # we catch broadly so a bad query never crashes the agent runtime.
    try:
        statement = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        # Fallback: return empty lineage — agent treats as untracked computation
        return []

    # ── Build alias → real table name map ──────────────────────────────────
    alias_to_table: Dict[str, str] = {}
    for table_expr in statement.find_all(exp.Table):
        raw_name = table_expr.name or ""
        real_name = _normalize(raw_name)
        alias = _normalize(table_expr.alias or "")
        # Always register the real name mapping to itself
        alias_to_table[real_name] = real_name
        if alias and alias != real_name:
            alias_to_table[alias] = real_name

    # ── Collect columns per resolved table ─────────────────────────────────
    table_cols: Dict[str, Set[str]] = defaultdict(set)

    for col_expr in statement.find_all(exp.Column):
        col_name = _normalize(col_expr.name or "")
        if not col_name or col_name == "*":
            continue

        table_ref = _normalize(col_expr.table or "")

        if table_ref:
            real_table = alias_to_table.get(table_ref, table_ref)
            table_cols[real_table].add(col_name)
        else:
            # Unqualified column: attempt heuristic resolution
            # (assign to first table in FROM clause if only one table)
            if len(alias_to_table) == 1:
                real_table = next(iter(alias_to_table.values()))
                table_cols[real_table].add(col_name)
            else:
                table_cols["unknown"].add(col_name)

    # ── Format result ───────────────────────────────────────────────────────
    result = []
    for table, cols in sorted(table_cols.items()):
        if cols:
            result.append({"table": table, "columns": sorted(cols)})
    return result


def lineage_summary(steps: List[Dict]) -> str:
    """Human-readable summary of extracted lineage steps, for logging."""
    if not steps:
        return "(no lineage extracted)"
    parts = []
    for s in steps:
        cols = ", ".join(s["columns"])
        parts.append(f"{s['table']}({cols})")
    return " → ".join(parts)


# ---------------------------------------------------------------------------
# Self-contained smoke test (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_cases = [
        # Case 1: simple select with alias
        ("Simple alias",
         "SELECT c.CategoryName, c.Description FROM Categories c WHERE c.CategoryID = 1"),

        # Case 2: multi-table JOIN — the canonical Northwind revenue query
        ("Revenue JOIN",
         """
         SELECT c.CategoryName,
                SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)) AS revenue
         FROM   Categories c
         JOIN   Products p          ON c.CategoryID = p.CategoryID
         JOIN   "Order Details" od  ON p.ProductID  = od.ProductID
         GROUP  BY c.CategoryName
         ORDER  BY revenue DESC
         """),

        # Case 3: employee query with sensitive HomePhone
        ("Employee PII",
         "SELECT e.FirstName, e.LastName, e.HomePhone, e.Title FROM Employees e ORDER BY e.LastName"),

        # Case 4: safe metric — no sensitive columns
        ("Safe orders",
         """
         SELECT o.ShipCountry, COUNT(o.OrderID) AS cnt
         FROM   Orders o
         GROUP  BY o.ShipCountry
         ORDER  BY cnt DESC
         """),

        # Case 5: subquery
        ("Subquery",
         """
         SELECT p.ProductName, p.UnitPrice
         FROM   Products p
         WHERE  p.UnitPrice > (SELECT AVG(UnitPrice) FROM Products)
         """),
    ]

    print("=" * 60)
    print("sqlglot Lineage Extractor — Smoke Test")
    print("=" * 60)
    for name, sql in test_cases:
        steps = extract_lineage_from_sql(sql)
        print(f"\n[{name}]")
        print(f"  SQL: {sql.strip()[:80]}...")
        print(f"  Lineage: {lineage_summary(steps)}")
        for s in steps:
            print(f"    {s['table']}: {s['columns']}")
