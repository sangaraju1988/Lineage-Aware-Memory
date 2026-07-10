"""
amu_bridge.py
=============
Bridge between sqlglot lineage extraction and the AMU data model.

Converts  extract_lineage_from_sql() output  →  Lineage + AMU objects
using Northwind-specific sensitive column registry and permissions.

This module is the key integration point between:
  - The existing model.py / systems.py (paper's formal model)
  - The sqlglot-based automatic lineage extractor
  - The Northwind schema configuration
"""

from __future__ import annotations

import sys
import os
from typing import Any, Dict, List, Optional, Set, Tuple

# Import the paper's core model from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import AMU, Lineage, LineageStep

from .lineage_extractor import extract_lineage_from_sql
from .northwind_schema import NORTHWIND_SENSITIVE, NORTHWIND_PERMISSIONS


# ---------------------------------------------------------------------------
# Northwind-aware gate functions (mirror Algorithm 1 from the paper)
# ---------------------------------------------------------------------------

def get_sensitivity_tags(lineage: Lineage) -> Set[str]:
    """
    Compute S(a) = (∪ Ci) ∩ S for a given Lineage object.
    Mirrors the paper's sensitivity_tags property on AMU.
    Uses NORTHWIND_SENSITIVE instead of model.py's SENSITIVE_COLUMNS.
    """
    all_cols = lineage.all_columns()
    return all_cols & NORTHWIND_SENSITIVE


def gate_passes(amu: "NorthwindAMU", department: str) -> bool:
    """
    Return True iff S(amu) ⊆ P(department)  —  Algorithm 1 gate condition.
    A True result means the AMU can be safely served to this department.
    """
    permitted = NORTHWIND_PERMISSIONS.get(department, set())
    return amu.sensitivity_tags.issubset(permitted)


# ---------------------------------------------------------------------------
# NorthwindAMU — extends AMU with Northwind-specific sensitivity
# ---------------------------------------------------------------------------

class NorthwindAMU(AMU):
    """
    AMU subclass that uses NORTHWIND_SENSITIVE for sensitivity_tags instead
    of the synthetic SENSITIVE_COLUMNS from model.py.

    All other behaviour (definition_hash, lineage, epoch) is inherited.
    """

    @property
    def sensitivity_tags(self) -> Set[str]:
        return get_sensitivity_tags(self.lineage)


# ---------------------------------------------------------------------------
# Core factory: SQL string → NorthwindAMU
# ---------------------------------------------------------------------------

def sql_to_amu(
    sql: str,
    metric_name: str,
    value: float,
    department: str,
    epoch: int,
    filter_logic: Optional[str] = None,
    dialect: str = "sqlite",
) -> Tuple["NorthwindAMU", List[Dict[str, Any]]]:
    """
    Execute sqlglot lineage extraction on *sql* and construct a NorthwindAMU.

    Parameters
    ----------
    sql           : The executed SQL query string.
    metric_name   : Logical name of the metric (e.g. "revenue_by_category").
    value         : The scalar result or row count from the query.
    department    : Owning department (e.g. "Finance").
    epoch         : Timestamp/sequence number.
    filter_logic  : Optional human-readable filter description. If None,
                    the first 120 characters of the SQL are used.
    dialect       : SQL dialect for sqlglot parser (default "sqlite").

    Returns
    -------
    (NorthwindAMU, lineage_steps_raw)
    where lineage_steps_raw is the raw output of extract_lineage_from_sql()
    for logging / reporting purposes.
    """
    # Step 1: sqlglot extracts lineage automatically — no agent self-reporting
    raw_steps = extract_lineage_from_sql(sql, dialect=dialect)

    # Step 2: Convert to paper's LineageStep objects
    steps = tuple(
        LineageStep(
            table=step["table"],
            columns_used=tuple(step["columns"]),
        )
        for step in raw_steps
        if step["table"] != "unknown"  # skip unresolved unqualified references
    )

    # Step 3: Build Lineage
    lineage = Lineage(
        steps=steps,
        filter_logic=filter_logic or sql.strip()[:120].replace("\n", " "),
    )

    # Step 4: Build NorthwindAMU
    amu = NorthwindAMU(
        metric_name=metric_name,
        value=value,
        owner_department=department,
        lineage=lineage,
        epoch=epoch,
    )

    return amu, raw_steps


# ---------------------------------------------------------------------------
# Northwind-aware LineageAwareSystem
# ---------------------------------------------------------------------------

from collections import defaultdict


class NorthwindLineageSystem:
    """
    LineageAwareSystem adapted for Northwind experiments.

    Uses NORTHWIND_PERMISSIONS for the gate check instead of the synthetic
    DEPARTMENT_PERMISSIONS from model.py.

    Structurally identical to systems.LineageAwareSystem — same Algorithm 1.
    """

    name = "Lineage-Aware Governed Memory (Northwind, sqlglot-extracted lineage)"

    def __init__(self):
        self.store: Dict[str, List[NorthwindAMU]] = defaultdict(list)
        self._write_log: List[Dict] = []
        self._retrieval_log: List[Dict] = []

    def write(self, amu: NorthwindAMU, raw_steps: List[Dict] = None) -> bool:
        """
        Write an AMU; return True if a definition conflict is detected.
        A conflict = same metric_name, different definition_hash, different department.
        """
        existing = self.store.get(amu.metric_name, [])
        conflict = any(
            e.owner_department != amu.owner_department
            and e.definition_hash != amu.definition_hash
            for e in existing
        )
        self.store[amu.metric_name].append(amu)
        self._write_log.append({
            "metric_name": amu.metric_name,
            "department": amu.owner_department,
            "sensitivity_tags": sorted(amu.sensitivity_tags),
            "definition_hash": amu.definition_hash,
            "conflict_detected": conflict,
            "lineage_steps": raw_steps or [],
        })
        return conflict

    def request(
        self,
        metric_name: str,
        requester_dept: str,
        fresh_amu: Optional[NorthwindAMU] = None,
        fresh_raw_steps: List[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Algorithm 1: Lineage-gated retrieval.

        Returns a result dict with:
          served          : bool — did the requester receive an answer
          reused          : bool — served from memory (True) or fresh compute (False)
          blocked         : bool — at least one candidate was gate-blocked
          leaked          : bool — always False by construction
          conflict_flagged: bool — definition conflict written for fresh AMU
          source_dept     : str  — which department's AMU was served (or "fresh")
          blocking_tags   : set  — which sensitive columns caused the block
        """
        candidates = self.store.get(metric_name, [])
        permitted = NORTHWIND_PERMISSIONS.get(requester_dept, set())

        safe_candidate = None
        any_blocked = False
        blocking_tags_union: Set[str] = set()

        # Most recent first — favour fresh definitions
        for amu in reversed(candidates):
            blocking = amu.sensitivity_tags - permitted
            if blocking:
                any_blocked = True
                blocking_tags_union |= blocking
                continue
            safe_candidate = amu
            break

        if safe_candidate is not None:
            result = {
                "served": True, "reused": True, "blocked": any_blocked,
                "leaked": False, "conflict_flagged": False,
                "source_dept": safe_candidate.owner_department,
                "blocking_tags": blocking_tags_union,
                "value": safe_candidate.value,
                "definition_hash": safe_candidate.definition_hash,
            }
        else:
            # Fall back to fresh compute; write fresh AMU if provided
            conflict = False
            if fresh_amu is not None:
                conflict = self.write(fresh_amu, fresh_raw_steps)
            result = {
                "served": True, "reused": False, "blocked": any_blocked,
                "leaked": False, "conflict_flagged": conflict,
                "source_dept": "fresh",
                "blocking_tags": blocking_tags_union,
                "value": fresh_amu.value if fresh_amu else None,
                "definition_hash": fresh_amu.definition_hash if fresh_amu else None,
            }

        self._retrieval_log.append({
            "metric_name": metric_name,
            "requester": requester_dept,
            **result,
            "blocking_tags": sorted(blocking_tags_union),
        })
        return result
