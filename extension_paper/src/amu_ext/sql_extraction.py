"""
Thin wrapper / regression harness around the ``real_agent/amu_bridge.py``
SQL unqualified-column fix (Group C3).

The bug (root repo commit ``dc8e960``): ``extract_lineage_from_sql()``
buckets an unqualified column reference in a multi-table query (a
comma-join, or any query where the table can't be resolved from a single
FROM target) under the synthetic table name ``"unknown"``. Before the fix,
``amu_bridge.sql_to_amu()`` filtered out every step where
``table == "unknown"`` before building the ``Lineage`` object -- silently
dropping that column from lineage entirely. If the dropped column was
sensitive, the gate never saw it and would serve the result to a requester
who shouldn't see it: a real, exploitable leak, and the opposite of the
module's documented fail-closed design.

This module does not reimplement the extractor. It calls the real,
currently-merged ``real_agent.lineage_extractor.extract_lineage_from_sql``
(sqlglot-based parsing) and applies the *documented* pre-fix filtering step
as an explicit, named parameter -- ``keep_unqualified=False`` reproduces the
buggy behavior exactly (drop the "unknown" bucket), ``keep_unqualified=True``
(the default, matching current ``main``) reproduces the fix. This is the
"parameter toggle" option the build prompt allows in place of checking out
the pre-fix commit, and it keeps both conditions exercising the one real,
current parser rather than two divergent copies of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Set, Union

from real_agent.lineage_extractor import extract_lineage_from_sql

__all__ = [
    "QueryCase",
    "lineage_steps_from_sql",
    "sensitivity_tags_from_steps",
    "would_leak",
    "evaluate_case",
]


@dataclass(frozen=True)
class QueryCase:
    """One SQL query in the C3 regression harness's query set.

    Attributes:
        name: short identifier.
        sql: the SQL text.
        true_sensitive_columns: the columns this query genuinely reads that
            are in the sensitive registry -- ground truth, established by
            construction (we wrote the query), independent of what any
            extractor manages to resolve.
        style: a short tag describing the SQL construct under test (e.g.
            ``"comma_join_unqualified"``, ``"fully_qualified"``,
            ``"single_table_unqualified"``) -- used to group results.
        description: one-line human-readable summary of what the query does
            and why it's included.
    """

    name: str
    sql: str
    true_sensitive_columns: FrozenSet[str]
    style: str
    description: str


def lineage_steps_from_sql(
    sql: str, *, dialect: str = "sqlite", keep_unqualified: bool = True
) -> List[Dict[str, Any]]:
    """Extract lineage steps from SQL, with the pre-/post-fix behavior selectable.

    Args:
        sql: the SQL query text.
        dialect: sqlglot dialect (default "sqlite", matching amu_bridge.py).
        keep_unqualified: if True (default, matches current ``main`` /
            commit ``dc8e960``), unresolved ("unknown"-table) column
            references are kept as their own lineage step. If False,
            reproduces the pre-fix bug: the "unknown" bucket is dropped
            entirely before lineage is built.

    Returns:
        A list of ``{"table": str, "columns": List[str]}`` dicts, exactly
        as ``real_agent.lineage_extractor.extract_lineage_from_sql`` returns
        them, minus the "unknown" bucket when ``keep_unqualified=False``.
    """
    raw_steps: List[Dict[str, Any]] = extract_lineage_from_sql(sql, dialect=dialect)
    if keep_unqualified:
        return raw_steps
    return [step for step in raw_steps if step["table"] != "unknown"]


def sensitivity_tags_from_steps(steps: List[Dict[str, Any]], sensitive_columns: Set[str]) -> Set[str]:
    """Union every step's columns and intersect with the sensitive registry.

    Mirrors ``amu_bridge.get_sensitivity_tags`` / ``NorthwindAMU.sensitivity_tags``:
    sensitivity is computed by column NAME only, independent of which table
    (including the synthetic "unknown" table) the column's step is attached
    to -- this is exactly why keeping the "unknown" step is sufficient to
    fix the leak, without needing to actually resolve which real table the
    column came from.
    """
    all_columns: Set[str] = set()
    for step in steps:
        all_columns.update(step["columns"])
    return all_columns & sensitive_columns


def would_leak(
    true_sensitive_columns: Union[FrozenSet[str], Set[str]],
    extracted_sensitivity_tags: Set[str],
    permitted_columns: Union[FrozenSet[str], Set[str]],
) -> bool:
    """Would a lineage-aware gate leak this query's result to this requester?

    A leak occurs when the query genuinely touches a sensitive column the
    requester is not permitted to see (``true_sensitive_columns -
    permitted_columns`` is non-empty), but the *extracted* sensitivity tags
    fail to cover at least one such column -- i.e. the gate, working only
    from what the extractor reported, would see nothing to block and would
    serve the result.

    Args:
        true_sensitive_columns: ground-truth sensitive columns the query
            actually reads.
        extracted_sensitivity_tags: what the extractor (pre- or post-fix)
            reported as sensitive.
        permitted_columns: the requester's permitted-column set.

    Returns:
        True iff at least one truly-unpermitted sensitive column was missed
        by extraction.
    """
    truly_unpermitted = true_sensitive_columns - permitted_columns
    if not truly_unpermitted:
        return False
    return bool(truly_unpermitted - extracted_sensitivity_tags)


@dataclass(frozen=True)
class CaseResult:
    name: str
    style: str
    true_sensitive_columns: FrozenSet[str]
    extracted_sensitivity_tags: FrozenSet[str]
    truly_unpermitted: FrozenSet[str]
    leaked: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "style": self.style,
            "true_sensitive_columns": sorted(self.true_sensitive_columns),
            "extracted_sensitivity_tags": sorted(self.extracted_sensitivity_tags),
            "truly_unpermitted": sorted(self.truly_unpermitted),
            "leaked": self.leaked,
        }


def evaluate_case(
    case: QueryCase,
    *,
    sensitive_columns: Set[str],
    permitted_columns: Set[str],
    keep_unqualified: bool,
    dialect: str = "sqlite",
) -> CaseResult:
    """Run one :class:`QueryCase` through extraction and the leak check.

    Args:
        case: the query case to evaluate.
        sensitive_columns: the full sensitive-column registry (e.g.
            ``NORTHWIND_SENSITIVE``).
        permitted_columns: the requesting department's permitted-column set
            (e.g. ``NORTHWIND_PERMISSIONS["Operations"]``).
        keep_unqualified: pre-/post-fix toggle, see :func:`lineage_steps_from_sql`.
        dialect: sqlglot dialect.

    Returns:
        A :class:`CaseResult`.
    """
    steps = lineage_steps_from_sql(case.sql, dialect=dialect, keep_unqualified=keep_unqualified)
    extracted = sensitivity_tags_from_steps(steps, sensitive_columns)
    truly_unpermitted = case.true_sensitive_columns - permitted_columns
    leaked = would_leak(case.true_sensitive_columns, extracted, permitted_columns)
    return CaseResult(
        name=case.name,
        style=case.style,
        true_sensitive_columns=frozenset(case.true_sensitive_columns),
        extracted_sensitivity_tags=frozenset(extracted),
        truly_unpermitted=frozenset(truly_unpermitted),
        leaked=leaked,
    )
