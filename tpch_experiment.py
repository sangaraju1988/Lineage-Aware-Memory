"""
TPC-H-inspired schema experiment for the Lineage-Aware Memory Governance paper.

Uses the TPC-H relational schema structure (LINEITEM, ORDERS, CUSTOMER, PART,
PARTSUPP, SUPPLIER, NATION, REGION) with realistic column-level permissions across
three enterprise departments: Finance, Sales, Operations.

This is NOT running the TPC-H benchmark queries — it uses TPC-H table/column
names to create a more realistic simulation than the toy 5-table synthetic schema,
providing a complementary data point for the paper.
"""

import random
import statistics
import json
import hashlib
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Dict, Optional
from collections import defaultdict

# ── TPC-H-inspired schema ────────────────────────────────────────────────

TPCH_SCHEMA = {
    "customer":   {"c_custkey", "c_name", "c_address", "c_nationkey",
                   "c_phone", "c_acctbal", "c_mktsegment", "c_comment"},
    "orders":     {"o_orderkey", "o_custkey", "o_orderstatus", "o_totalprice",
                   "o_orderdate", "o_orderpriority", "o_shippriority"},
    "lineitem":   {"l_orderkey", "l_partkey", "l_suppkey", "l_linenumber",
                   "l_quantity", "l_extendedprice", "l_discount", "l_tax",
                   "l_returnflag", "l_linestatus", "l_shipdate", "l_commitdate"},
    "part":       {"p_partkey", "p_name", "p_mfgr", "p_brand", "p_type",
                   "p_size", "p_retailprice"},
    "partsupp":   {"ps_partkey", "ps_suppkey", "ps_availqty", "ps_supplycost"},
    "supplier":   {"s_suppkey", "s_name", "s_address", "s_nationkey",
                   "s_phone", "s_acctbal"},
    "nation":     {"n_nationkey", "n_name", "n_regionkey"},
    "region":     {"r_regionkey", "r_name"},
}

# Columns considered sensitive in this schema
TPCH_SENSITIVE = {
    "c_acctbal",    # customer financial balance
    "c_phone",      # customer PII
    "c_address",    # customer PII
    "s_acctbal",    # supplier financial balance
    "s_phone",      # supplier PII
    "s_address",    # supplier PII
    "l_extendedprice",  # detailed pricing (commercially sensitive)
    "l_discount",       # discount terms (commercially sensitive)
    "o_totalprice",     # order value (commercially sensitive for some orgs)
}

# Department permissions — realistic enterprise scenario
TPCH_DEPT_PERMISSIONS = {
    "Finance": set.union(*TPCH_SCHEMA.values()),   # all columns
    "Sales": {
        # Sales sees most things but NOT financial balances or PII contact info
        "c_custkey", "c_name", "c_nationkey", "c_mktsegment",
        "o_orderkey", "o_custkey", "o_orderstatus", "o_orderdate",
        "o_orderpriority", "o_shippriority",
        "l_orderkey", "l_partkey", "l_suppkey", "l_linenumber",
        "l_quantity", "l_returnflag", "l_linestatus", "l_shipdate",
        "p_partkey", "p_name", "p_mfgr", "p_brand", "p_type",
        "p_size", "p_retailprice",
        "n_nationkey", "n_name", "n_regionkey",
        "r_regionkey", "r_name",
    },
    "Operations": {
        # Ops sees supply chain, part availability — NOT customer financials/PII,
        # NOT pricing details
        "p_partkey", "p_name", "p_mfgr", "p_brand", "p_type", "p_size",
        "ps_partkey", "ps_suppkey", "ps_availqty",  # NOT ps_supplycost
        "s_suppkey", "s_name", "s_nationkey",         # NOT s_acctbal, s_phone, s_address
        "l_orderkey", "l_partkey", "l_suppkey", "l_linenumber",
        "l_quantity", "l_returnflag", "l_linestatus", "l_shipdate", "l_commitdate",
        # NOT l_extendedprice, l_discount, l_tax
        "n_nationkey", "n_name", "n_regionkey",
        "r_regionkey", "r_name",
    },
}

# ── Lineage primitives (mirrors model.py) ────────────────────────────────

@dataclass(frozen=True)
class TLineageStep:
    table: str
    columns_used: Tuple[str, ...]

    def sensitive_columns(self) -> Set[str]:
        return {c for c in self.columns_used if c in TPCH_SENSITIVE}


@dataclass(frozen=True)
class TLineage:
    steps: Tuple[TLineageStep, ...]
    filter_logic: str

    def all_columns(self) -> Set[str]:
        cols = set()
        for s in self.steps:
            cols.update(s.columns_used)
        return cols

    def sensitive_columns(self) -> Set[str]:
        return {c for c in self.all_columns() if c in TPCH_SENSITIVE}

    def definition_hash(self) -> str:
        tables = tuple(sorted(s.table for s in self.steps))
        cols   = tuple(sorted(self.all_columns()))
        payload = f"{tables}|{cols}|{self.filter_logic}"
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class TAMU:
    metric_name: str
    value: float
    owner_department: str
    lineage: TLineage
    epoch: int

    @property
    def sensitivity_tags(self) -> Set[str]:
        return self.lineage.sensitive_columns()

    @property
    def definition_hash(self) -> str:
        return self.lineage.definition_hash()


# ── TPC-H-inspired metric variants ──────────────────────────────────────

TPCH_METRIC_VARIANTS = {
    "revenue_by_region": [
        TLineage(
            steps=(
                TLineageStep("lineitem",  ("l_orderkey","l_extendedprice","l_discount","l_shipdate")),
                TLineageStep("orders",    ("o_orderkey","o_custkey","o_orderdate")),
                TLineageStep("customer",  ("c_custkey","c_nationkey")),
                TLineageStep("nation",    ("n_nationkey","n_regionkey")),
                TLineageStep("region",    ("r_regionkey","r_name")),
            ),
            filter_logic="l_shipdate BETWEEN 1994-01-01 AND 1995-01-01",
        ),
        TLineage(
            steps=(
                TLineageStep("lineitem",  ("l_orderkey","l_extendedprice","l_discount","l_shipdate")),
                TLineageStep("orders",    ("o_orderkey","o_custkey","o_totalprice","o_orderdate")),
                TLineageStep("customer",  ("c_custkey","c_nationkey","c_acctbal")),
                TLineageStep("nation",    ("n_nationkey","n_regionkey")),
                TLineageStep("region",    ("r_regionkey","r_name")),
            ),
            filter_logic="l_shipdate BETWEEN 1994-01-01 AND 1995-01-01 AND c_acctbal > 0",
        ),
    ],
    "order_volume": [
        TLineage(
            steps=(
                TLineageStep("orders",   ("o_orderkey","o_orderdate","o_orderstatus")),
                TLineageStep("lineitem", ("l_orderkey","l_quantity","l_returnflag")),
            ),
            filter_logic="o_orderstatus = 'O'",
        ),
    ],
    "customer_ltv": [
        TLineage(
            steps=(
                TLineageStep("customer", ("c_custkey","c_mktsegment","c_acctbal")),
                TLineageStep("orders",   ("o_custkey","o_totalprice","o_orderdate")),
                TLineageStep("lineitem", ("l_orderkey","l_extendedprice","l_discount")),
            ),
            filter_logic="c_mktsegment = 'BUILDING' AND orders in last 2 years",
        ),
        TLineage(
            steps=(
                TLineageStep("customer", ("c_custkey","c_mktsegment")),
                TLineageStep("orders",   ("o_custkey","o_orderdate","o_shippriority")),
                TLineageStep("lineitem", ("l_orderkey","l_quantity","l_shipdate")),
            ),
            filter_logic="c_mktsegment = 'BUILDING' AND orders in last 2 years (no financials)",
        ),
    ],
    "part_availability": [
        TLineage(
            steps=(
                TLineageStep("part",    ("p_partkey","p_brand","p_type","p_size")),
                TLineageStep("partsupp",("ps_partkey","ps_suppkey","ps_availqty")),
                TLineageStep("supplier",("s_suppkey","s_name","s_nationkey")),
            ),
            filter_logic="p_brand NOT LIKE 'Brand#45' AND p_size IN (49,14,23,45,19,3,36,9)",
        ),
    ],
    "supplier_performance": [
        TLineage(
            steps=(
                TLineageStep("supplier",("s_suppkey","s_acctbal","s_name","s_nationkey")),
                TLineageStep("partsupp",("ps_suppkey","ps_partkey","ps_supplycost","ps_availqty")),
                TLineageStep("lineitem",("l_suppkey","l_orderkey","l_quantity","l_extendedprice")),
            ),
            filter_logic="supplier balance-adjusted performance, past 1 year",
        ),
        TLineage(
            steps=(
                TLineageStep("supplier",("s_suppkey","s_name","s_nationkey")),
                TLineageStep("partsupp",("ps_suppkey","ps_partkey","ps_availqty")),
                TLineageStep("lineitem",("l_suppkey","l_orderkey","l_quantity","l_linestatus")),
            ),
            filter_logic="on-time delivery rate, past 1 year (no financials)",
        ),
    ],
}

TPCH_DEPARTMENTS = ["Finance", "Sales", "Operations"]


@dataclass
class TEvent:
    epoch: int
    department: str
    metric_name: str
    lineage: TLineage


def generate_tpch_workload(n_epochs=20, events_per_epoch=6) -> List[TEvent]:
    events = []
    metric_names = list(TPCH_METRIC_VARIANTS.keys())
    for epoch in range(n_epochs):
        for _ in range(events_per_epoch):
            dept    = random.choice(TPCH_DEPARTMENTS)
            metric  = random.choice(metric_names)
            variants = TPCH_METRIC_VARIANTS[metric]
            lineage  = random.choice(variants)
            events.append(TEvent(epoch, dept, metric, lineage))
    return events


# ── Systems (same logic as systems.py, parameterised) ────────────────────

class TRetrievalResult:
    def __init__(self, leaked, reused, blocked):
        self.leaked = leaked
        self.reused = reused
        self.blocked = blocked


class TNaiveSystem:
    def __init__(self):
        self.store: Dict[str, List[TAMU]] = defaultdict(list)

    def write(self, amu: TAMU):
        self.store[amu.metric_name].append(amu)

    def request(self, metric, dept, fresh_amu) -> TRetrievalResult:
        candidates = self.store.get(metric, [])
        if not candidates:
            self.write(fresh_amu)
            return TRetrievalResult(leaked=False, reused=False, blocked=False)
        amu = candidates[-1]
        leaked = bool(amu.sensitivity_tags - TPCH_DEPT_PERMISSIONS[dept])
        return TRetrievalResult(leaked=leaked, reused=True, blocked=False)


class TLineageAwareSystem:
    def __init__(self):
        self.store: Dict[str, List[TAMU]] = defaultdict(list)

    def write(self, amu: TAMU) -> bool:
        existing = self.store.get(amu.metric_name, [])
        conflict = any(
            e.owner_department != amu.owner_department and e.definition_hash != amu.definition_hash
            for e in existing
        )
        self.store[amu.metric_name].append(amu)
        return conflict

    def request(self, metric, dept, fresh_amu) -> TRetrievalResult:
        candidates = self.store.get(metric, [])
        permitted  = TPCH_DEPT_PERMISSIONS[dept]
        blocked = False
        for amu in reversed(candidates):
            if amu.sensitivity_tags - permitted:
                blocked = True
                continue
            return TRetrievalResult(leaked=False, reused=True, blocked=False)
        return TRetrievalResult(leaked=False, reused=False, blocked=blocked)


def run_tpch_simulation():
    events = generate_tpch_workload()
    naive  = TNaiveSystem()
    la     = TLineageAwareSystem()

    stats = {
        "naive": {"leaked":0,"reused":0,"blocked":0,"cross":0},
        "la":    {"leaked":0,"reused":0,"blocked":0,"cross":0},
    }
    true_conflicts = 0
    flagged_la = 0
    seen_defs: Dict[str, Dict[str, str]] = {}

    for ev in events:
        amu = TAMU(metric_name=ev.metric_name, value=round(random.uniform(0,1e6),2),
                   owner_department=ev.department, lineage=ev.lineage, epoch=ev.epoch)

        seen_defs.setdefault(ev.metric_name, {})
        prior = seen_defs[ev.metric_name]
        is_conflict = any(owner != ev.department
                          for h, owner in prior.items() if h != amu.definition_hash)
        if is_conflict:
            true_conflicts += 1
        prior[amu.definition_hash] = ev.department

        for sys_name, system in [("naive", naive), ("la", la)]:
            s = stats[sys_name]
            s["cross"] += 1
            r = system.request(ev.metric_name, ev.department, amu)
            s["leaked"]  += int(r.leaked)
            s["reused"]  += int(r.reused)
            s["blocked"] += int(r.blocked)
            if sys_name == "la":
                cf = system.write(amu)
                if cf and is_conflict:
                    flagged_la += 1
            else:
                system.write(amu)

    def pct(num, den): return round(100*num/max(den,1), 1)

    return {
        "naive": {
            "leak_pct":    pct(stats["naive"]["leaked"], stats["naive"]["cross"]),
            "reuse_pct":   pct(stats["naive"]["reused"], stats["naive"]["cross"]),
            "conflict_recall": 0.0,
        },
        "la": {
            "leak_pct":    pct(stats["la"]["leaked"], stats["la"]["cross"]),
            "reuse_pct":   pct(stats["la"]["reused"], stats["la"]["cross"]),
            "conflict_recall": pct(flagged_la, true_conflicts) if true_conflicts else 100.0,
        },
        "true_conflicts": true_conflicts,
    }


def sweep_tpch(n_seeds=30):
    all_naive_leak, all_la_leak   = [], []
    all_naive_reuse, all_la_reuse = [], []
    all_la_cr = []

    for seed in range(n_seeds):
        random.seed(seed)
        r = run_tpch_simulation()
        all_naive_leak.append(r["naive"]["leak_pct"])
        all_la_leak.append(r["la"]["leak_pct"])
        all_naive_reuse.append(r["naive"]["reuse_pct"])
        all_la_reuse.append(r["la"]["reuse_pct"])
        all_la_cr.append(r["la"]["conflict_recall"])

    return {
        "naive": {
            "leak_mean":  round(statistics.mean(all_naive_leak),  2),
            "leak_sd":    round(statistics.pstdev(all_naive_leak), 2),
            "reuse_mean": round(statistics.mean(all_naive_reuse), 2),
            "reuse_sd":   round(statistics.pstdev(all_naive_reuse),2),
        },
        "la": {
            "leak_mean":  round(statistics.mean(all_la_leak),  2),
            "leak_sd":    round(statistics.pstdev(all_la_leak), 2),
            "reuse_mean": round(statistics.mean(all_la_reuse), 2),
            "reuse_sd":   round(statistics.pstdev(all_la_reuse),2),
            "cr_mean":    round(statistics.mean(all_la_cr), 2),
            "cr_sd":      round(statistics.pstdev(all_la_cr), 2),
        },
        "raw": {
            "naive_leak": all_naive_leak, "la_leak": all_la_leak,
            "naive_reuse": all_naive_reuse, "la_reuse": all_la_reuse,
        }
    }


if __name__ == "__main__":
    random.seed(42)
    results = sweep_tpch(30)
    print("=== TPC-H-inspired schema (30 seeds) ===")
    print(f"Naive  — leak: {results['naive']['leak_mean']:.1f} ± {results['naive']['leak_sd']:.1f}%  "
          f"reuse: {results['naive']['reuse_mean']:.1f} ± {results['naive']['reuse_sd']:.1f}%")
    print(f"LA     — leak: {results['la']['leak_mean']:.1f} ± {results['la']['leak_sd']:.1f}%  "
          f"reuse: {results['la']['reuse_mean']:.1f} ± {results['la']['reuse_sd']:.1f}%  "
          f"conflict recall: {results['la']['cr_mean']:.1f} ± {results['la']['cr_sd']:.1f}%")
    with open("tpch_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved tpch_results.json")
