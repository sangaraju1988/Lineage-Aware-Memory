"""
Three competing memory systems, evaluated on the same workload:

A) NoMemorySystem        - every request recomputed fresh by the requester's own
                            department (the status quo before any shared memory).
B) NaiveMemorySystem      - shared AMU store, retrieval by metric_name match only.
                            This represents existing governed-memory work (Oracle
                            AI Agent Memory, the production Governed Memory paper,
                            SSGM, Zep, MemGPT, A-MEM): governance happens at the
                            CONTENT/access-tag level, not the lineage level.
C) LineageAwareSystem     - shared AMU store, retrieval gated on lineage: blocks
                            a retrieval if the AMU's derivation touches a column
                            the requesting department isn't permitted to see,
                            and flags metric-definition conflicts via lineage hash.
"""

from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from model import AMU, DEPARTMENT_PERMISSIONS


class RetrievalResult:
    def __init__(self, served: bool, leaked: bool, reused: bool, blocked: bool,
                 conflict_flagged: bool = False):
        self.served = served          # did the requester get an answer at all
        self.leaked = leaked           # did the answer expose unauthorized columns
        self.reused = reused           # was it served from memory (vs fresh compute)
        self.blocked = blocked         # was a memory hit blocked by governance
        self.conflict_flagged = conflict_flagged


class NoMemorySystem:
    """Baseline: no shared memory. Each request is recomputed fresh, in-scope,
    by the requesting department. Structurally leak-free, but zero reuse and
    zero conflict visibility (departments never see each other's definitions)."""

    name = "No Memory (status quo)"

    def __init__(self):
        pass

    def write(self, amu: AMU):
        pass  # nothing persists

    def request(self, metric_name: str, requester_dept: str, fresh_amu: AMU) -> RetrievalResult:
        # Always "recomputed fresh" within the requester's own permission scope.
        # We model this as never leaking (by construction) and never reusing.
        return RetrievalResult(served=True, leaked=False, reused=False, blocked=False)


class NaiveMemorySystem:
    """Shared memory, retrieval keyed on metric_name only. No lineage check at
    retrieval time. This is the current state of the art: content/tag-based
    governance, not derivation-aware governance."""

    name = "Naive Shared Memory (content-gated)"

    def __init__(self):
        self.store: Dict[str, List[AMU]] = defaultdict(list)

    def write(self, amu: AMU):
        self.store[amu.metric_name].append(amu)

    def request(self, metric_name: str, requester_dept: str, fresh_amu: AMU) -> RetrievalResult:
        candidates = self.store.get(metric_name, [])
        if not candidates:
            self.write(fresh_amu)
            return RetrievalResult(served=True, leaked=False, reused=False, blocked=False)

        amu = candidates[-1]  # most recent, naive "best match"
        permitted = DEPARTMENT_PERMISSIONS[requester_dept]
        leaked = bool(amu.sensitivity_tags - permitted)  # exposes columns requester can't see
        return RetrievalResult(served=True, leaked=leaked, reused=True, blocked=False)


class LineageAwareSystem:
    """Shared memory, retrieval gated on lineage. Blocks (falls back to fresh
    compute) when the stored AMU's derivation touches a column outside the
    requester's permitted set. Also flags metric-definition conflicts by
    comparing definition_hash across AMUs sharing the same metric_name."""

    name = "Lineage-Aware Governed Memory (proposed)"

    def __init__(self):
        self.store: Dict[str, List[AMU]] = defaultdict(list)

    def write(self, amu: AMU) -> bool:
        """Returns True if writing this AMU surfaces a NEW conflict with an
        existing definition of the same metric (different lineage/definition_hash
        from a different owning department)."""
        existing = self.store.get(amu.metric_name, [])
        conflict = any(
            e.owner_department != amu.owner_department and e.definition_hash != amu.definition_hash
            for e in existing
        )
        self.store[amu.metric_name].append(amu)
        return conflict

    def request(self, metric_name: str, requester_dept: str, fresh_amu: AMU) -> RetrievalResult:
        candidates = self.store.get(metric_name, [])
        permitted = DEPARTMENT_PERMISSIONS[requester_dept]

        # Try to find a candidate this requester is actually allowed to see
        safe_candidate = None
        any_blocked = False
        for amu in reversed(candidates):  # most recent first
            if amu.sensitivity_tags - permitted:
                any_blocked = True
                continue
            safe_candidate = amu
            break

        if safe_candidate is not None:
            return RetrievalResult(served=True, leaked=False, reused=True, blocked=False)

        # No safe candidate in memory -> fall back to fresh compute (in-scope, safe)
        return RetrievalResult(served=True, leaked=False, reused=False, blocked=any_blocked)
