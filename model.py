"""
Core data model for the Lineage-Aware Memory Governance playground.

This is a synthetic simulation, not a real BI stack. It models just enough
structure to test the mechanism: can lineage-aware governance catch leakage
and metric conflicts that a naive shared-memory system misses?
"""

from dataclasses import dataclass, field
from typing import List, Set, Tuple
import hashlib


# ---------------------------------------------------------------------------
# Schema: tables, columns, and which columns are sensitive
# ---------------------------------------------------------------------------

# table -> set of columns
SCHEMA = {
    "customers": {"customer_id", "region", "signup_date"},
    "customer_pii": {"customer_id", "ssn", "email", "income"},
    "transactions": {"customer_id", "txn_id", "amount", "txn_date"},
    "campaigns": {"campaign_id", "customer_id", "channel", "spend"},
    "support_tickets": {"customer_id", "ticket_id", "category"},
}

# Columns that are sensitive regardless of which table they appear in
SENSITIVE_COLUMNS = {"ssn", "email", "income"}

# department -> set of columns they are permitted to see (post source-control)
DEPARTMENT_PERMISSIONS = {
    "Finance": {"ssn", "income", "email", "customer_id", "region", "signup_date",
                "txn_id", "amount", "txn_date", "campaign_id", "channel", "spend",
                "ticket_id", "category"},
    "Marketing": {"customer_id", "region", "signup_date", "campaign_id", "channel",
                  "spend", "txn_id", "amount", "txn_date"},  # no PII
    "Support": {"customer_id", "region", "ticket_id", "category", "signup_date"},  # no PII, no $ data
}


@dataclass(frozen=True)
class LineageStep:
    table: str
    columns_used: Tuple[str, ...]

    def sensitive_columns(self) -> Set[str]:
        return {c for c in self.columns_used if c in SENSITIVE_COLUMNS}


@dataclass(frozen=True)
class Lineage:
    steps: Tuple[LineageStep, ...]
    filter_logic: str  # human-readable filter description, also used for definition hashing

    def all_columns(self) -> Set[str]:
        cols = set()
        for s in self.steps:
            cols.update(s.columns_used)
        return cols

    def sensitive_columns(self) -> Set[str]:
        return {c for c in self.all_columns() if c in SENSITIVE_COLUMNS}

    def definition_hash(self) -> str:
        """Hash of join path + filter logic -> identifies *how* a metric was derived."""
        tables = tuple(sorted(s.table for s in self.steps))
        cols = tuple(sorted(self.all_columns()))
        payload = f"{tables}|{cols}|{self.filter_logic}"
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class AMU:
    """Analytical Memory Unit."""
    metric_name: str
    value: float
    owner_department: str
    lineage: Lineage
    epoch: int

    @property
    def sensitivity_tags(self) -> Set[str]:
        return self.lineage.sensitive_columns()

    @property
    def definition_hash(self) -> str:
        return self.lineage.definition_hash()
