"""
Fuzzy Conflict-Detection Experiment (Extended Edition)
=======================================================

Extends the original 10-pair study to ~45 programmatically-constructed
lineage pairs across four categories:

  TC  — True Conflict: different join tables OR different column sets
        (semantically different metrics — should be flagged)
  TV  — Threshold Variant: same tables + columns, only a numeric threshold
        changed in filter_logic (same metric, recalibrated — should NOT flag)
  LO  — Logic-Operator Change: same tables + columns, but AND↔OR/NOT change
        in filter_logic. These ARE true semantic conflicts — different rows
        qualify — but D3's column-graph test cannot detect them.
  CS  — Column-Subset: one lineage uses a strict subset of the other's columns
        (still a conflict because derivation paths differ)

D1 — Exact hash   : conflict iff SHA-256(tables|cols|filter) differs
D2 — Jaccard      : if tables+cols match, conflict iff token-Jaccard(filter) < 0.70
D3 — Column-graph : conflict iff tables or column-sets differ
                    (ignores filter-logic entirely)

The LO category stress-tests D3: same tables, same columns, only AND↔OR/NOT
changes → D3 misses every case (FN). D1 catches them all (hash changes).
D2 depends on Jaccard of the filter strings (usually high similarity → also misses).

Bootstrap 95% confidence intervals are computed over 10,000 resamples.

Outputs:
  fuzzy_results_extended.json  — per-detector metrics + CI (does NOT overwrite
                                  the original fuzzy_results.json)
"""

import hashlib, re, random, json, statistics
from dataclasses import dataclass
from typing import Tuple, List, Dict

# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def def_hash(tables: Tuple[str, ...], cols: Tuple[str, ...], logic: str) -> str:
    payload = f"{sorted(tables)}|{sorted(cols)}|{logic}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]

def token_jaccard(a: str, b: str) -> float:
    ta = set(re.split(r'\W+', a.lower())) - {""}
    tb = set(re.split(r'\W+', b.lower())) - {""}
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


# ──────────────────────────────────────────────────────────────────────────
# Ground-truth pair dataset
# Each tuple: (name, tables_a, cols_a, logic_a, tables_b, cols_b, logic_b, is_tc, category)
# is_tc=True  → True Conflict (should be flagged)
# is_tc=False → Threshold Variant (should NOT be flagged)
# ──────────────────────────────────────────────────────────────────────────

PAIRS: List[Tuple] = [

    # ── TC: Original 5 True Conflicts (different tables or columns) ──────
    (
        "churn_rate: txn-only vs pii-adjusted",
        ("customers", "transactions"),
        ("customer_id", "signup_date", "txn_date", "amount"),
        "no txn in 90 days",
        ("customers", "customer_pii", "transactions"),
        ("customer_id", "signup_date", "income", "txn_date", "amount"),
        "no txn in 60 days AND income-segment adjusted",
        True, "TC",
    ),
    (
        "active_customers: txn-based vs campaign-based",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 30 days",
        ("customers", "campaigns"),
        ("customer_id", "region", "channel"),
        "any campaign engagement in last 30 days",
        True, "TC",
    ),
    (
        "revenue: gross vs net-of-discount",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01 net of discount",
        True, "TC",
    ),
    (
        "customer_ltv: financial vs engagement-only",
        ("customer", "orders", "lineitem"),
        ("c_custkey", "c_mktsegment", "c_acctbal", "o_totalprice",
         "l_extendedprice", "l_discount"),
        "c_mktsegment = 'BUILDING' AND orders in last 2 years",
        ("customer", "orders", "lineitem"),
        ("c_custkey", "c_mktsegment", "o_orderdate", "l_quantity", "l_shipdate"),
        "c_mktsegment = 'BUILDING' AND orders in last 2 years (no financials)",
        True, "TC",
    ),
    (
        "supplier_perf: balance-adjusted vs on-time only",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_acctbal", "s_name", "ps_supplycost", "ps_availqty",
         "l_quantity", "l_extendedprice"),
        "supplier balance-adjusted performance, past 1 year",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_name", "ps_availqty", "l_quantity", "l_linestatus"),
        "on-time delivery rate, past 1 year (no financials)",
        True, "TC",
    ),

    # ── TC: 10 additional True Conflicts ─────────────────────────────────
    (
        "campaign_roi: spend+revenue vs spend-only",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "revenue attributed within 14-day window",
        ("campaigns",),
        ("campaign_id", "spend", "channel"),
        "spend only, no revenue attribution",
        True, "TC",
    ),
    (
        "support_load: ticket+region vs ticket-only",
        ("support_tickets", "customers"),
        ("customer_id", "ticket_id", "category", "region"),
        "open tickets by region",
        ("support_tickets",),
        ("customer_id", "ticket_id", "category"),
        "open tickets (no region breakdown)",
        True, "TC",
    ),
    (
        "high_value_segment: income+txn vs txn-only",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "income decile 9-10",
        ("transactions",),
        ("customer_id", "amount"),
        "top 10% by transaction volume only",
        True, "TC",
    ),
    (
        "part_availability: with supplier vs without",
        ("part", "partsupp", "supplier"),
        ("p_partkey", "p_brand", "ps_availqty", "s_name", "s_nationkey"),
        "available parts by supplier region",
        ("part", "partsupp"),
        ("p_partkey", "p_brand", "ps_availqty"),
        "available parts count only",
        True, "TC",
    ),
    (
        "order_volume: with returns vs without returnflag",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity", "l_returnflag"),
        "order volume including return flag",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity"),
        "order volume excluding return flag column",
        True, "TC",
    ),
    (
        "churn: 3-table join vs 2-table join",
        ("customers", "customer_pii", "transactions"),
        ("customer_id", "email", "txn_date"),
        "no txn in 90 days, email-verified only",
        ("customers", "transactions"),
        ("customer_id", "txn_date"),
        "no txn in 90 days",
        True, "TC",
    ),
    (
        "revenue_by_region: nation join vs market segment",
        ("lineitem", "orders", "customer", "nation", "region"),
        ("l_extendedprice", "l_discount", "o_custkey",
         "c_nationkey", "n_regionkey", "r_name"),
        "revenue by region via nation lookup",
        ("lineitem", "orders", "customer"),
        ("l_extendedprice", "l_discount", "o_custkey", "c_mktsegment"),
        "revenue by market segment (no region)",
        True, "TC",
    ),
    (
        "customer_ltv: with PII contact vs without",
        ("customer", "orders"),
        ("c_custkey", "c_acctbal", "c_phone", "o_totalprice"),
        "lifetime value including account balance and contact PII",
        ("customer", "orders"),
        ("c_custkey", "c_mktsegment", "o_totalprice"),
        "lifetime value by market segment only",
        True, "TC",
    ),
    (
        "supplier_cost: with discount vs without",
        ("partsupp", "lineitem"),
        ("ps_supplycost", "ps_availqty", "l_extendedprice", "l_discount"),
        "net supplier cost after discount",
        ("partsupp", "lineitem"),
        ("ps_supplycost", "ps_availqty", "l_extendedprice"),
        "gross supplier cost (no discount column)",
        True, "TC",
    ),
    (
        "active_customers: campaign+txn vs txn only",
        ("customers", "campaigns", "transactions"),
        ("customer_id", "region", "channel", "txn_date"),
        "active via either campaign or transaction in 30 days",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "active via transaction only in 30 days",
        True, "TC",
    ),

    # ── TV: Original 5 Threshold Variants ────────────────────────────────
    (
        "churn_rate: 90-day vs 60-day window (same cols)",
        ("customers", "transactions"),
        ("customer_id", "signup_date", "txn_date", "amount"),
        "no txn in 90 days",
        ("customers", "transactions"),
        ("customer_id", "signup_date", "txn_date", "amount"),
        "no txn in 60 days",
        False, "TV",
    ),
    (
        "active_customers: 30-day vs 14-day window",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 30 days",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 14 days",
        False, "TV",
    ),
    (
        "high_value_segment: income decile 9-10 vs 8-10",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "income decile 9-10",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "income decile 8-10",
        False, "TV",
    ),
    (
        "revenue: 1994 window vs 1993 window (same cols)",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "o_orderdate"),
        "l_shipdate BETWEEN 1993-01-01 AND 1994-01-01",
        False, "TV",
    ),
    (
        "campaign_roi: 14-day vs 7-day attribution window",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "revenue attributed within 14-day window",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "revenue attributed within 7-day window",
        False, "TV",
    ),

    # ── TV: 10 additional Threshold Variants ─────────────────────────────
    (
        "churn_rate: 120-day vs 90-day window",
        ("customers", "transactions"),
        ("customer_id", "signup_date", "txn_date", "amount"),
        "no txn in 120 days",
        ("customers", "transactions"),
        ("customer_id", "signup_date", "txn_date", "amount"),
        "no txn in 90 days",
        False, "TV",
    ),
    (
        "high_value_segment: top 5% vs top 10% by spend",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "top 5% by spend",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "top 10% by spend",
        False, "TV",
    ),
    (
        "order_volume: 2023 vs 2024 year filter",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity", "l_returnflag"),
        "o_orderdate >= 2023-01-01",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity", "l_returnflag"),
        "o_orderdate >= 2024-01-01",
        False, "TV",
    ),
    (
        "part_availability: min qty 100 vs 50",
        ("part", "partsupp"),
        ("p_partkey", "p_brand", "ps_availqty"),
        "ps_availqty >= 100",
        ("part", "partsupp"),
        ("p_partkey", "p_brand", "ps_availqty"),
        "ps_availqty >= 50",
        False, "TV",
    ),
    (
        "supplier_performance: 6-month vs 12-month window",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_name", "ps_availqty", "l_quantity", "l_linestatus"),
        "on-time delivery rate, past 6 months",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_name", "ps_availqty", "l_quantity", "l_linestatus"),
        "on-time delivery rate, past 12 months",
        False, "TV",
    ),
    (
        "revenue: discount threshold 0.05 vs 0.10",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "l_discount < 0.05",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "l_discount < 0.10",
        False, "TV",
    ),
    (
        "campaign_roi: min spend 500 vs 1000",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "spend >= 500",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "spend >= 1000",
        False, "TV",
    ),
    (
        "support_load: priority 1-2 vs 1-3",
        ("support_tickets", "customers"),
        ("customer_id", "ticket_id", "category", "region"),
        "priority IN (1, 2)",
        ("support_tickets", "customers"),
        ("customer_id", "ticket_id", "category", "region"),
        "priority IN (1, 2, 3)",
        False, "TV",
    ),
    (
        "active_customers: 60-day vs 90-day window",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 60 days",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 90 days",
        False, "TV",
    ),
    (
        "customer_ltv: 1-year vs 2-year lookback",
        ("customer", "orders", "lineitem"),
        ("c_custkey", "c_mktsegment", "o_orderdate", "l_quantity", "l_shipdate"),
        "orders in last 1 year",
        ("customer", "orders", "lineitem"),
        ("c_custkey", "c_mktsegment", "o_orderdate", "l_quantity", "l_shipdate"),
        "orders in last 2 years",
        False, "TV",
    ),

    # ── LO: Logic-Operator Changes (AND→OR / NOT added) — TRUE CONFLICTS ─
    # Same tables, same columns, but Boolean operator changes which rows qualify.
    # D3 cannot detect (same cols + same tables); D1 catches all (filter hash changes).
    # D2 typically misses (Jaccard of filter strings is high: only one token differs).
    (
        "churn: AND→OR on no-txn + no-engagement (same cols)",
        ("customers", "transactions", "campaigns"),
        ("customer_id", "txn_date", "channel"),
        "no txn in 90 days AND no campaign engagement",
        ("customers", "transactions", "campaigns"),
        ("customer_id", "txn_date", "channel"),
        "no txn in 90 days OR no campaign engagement",
        True, "LO",
    ),
    (
        "high_value: AND→OR on income + spend (same cols)",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "income decile 9-10 AND spend > 10000",
        ("customer_pii", "transactions"),
        ("customer_id", "income", "amount"),
        "income decile 9-10 OR spend > 10000",
        True, "LO",
    ),
    (
        "active_customers: AND→OR on txn + region (same cols)",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 30 days AND region = EUROPE",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "txn in last 30 days OR region = EUROPE",
        True, "LO",
    ),
    (
        "order_volume: NOT returned vs all returned (same cols)",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity", "l_returnflag"),
        "l_returnflag = N (not returned)",
        ("orders", "lineitem"),
        ("o_orderkey", "o_orderdate", "l_quantity", "l_returnflag"),
        "l_returnflag IN (N, R) includes returned",
        True, "LO",
    ),
    (
        "supplier_perf: AND→OR on delivery+quality (same cols)",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_name", "ps_availqty", "l_quantity", "l_linestatus"),
        "on-time AND in-full delivery, past 12 months",
        ("supplier", "partsupp", "lineitem"),
        ("s_suppkey", "s_name", "ps_availqty", "l_quantity", "l_linestatus"),
        "on-time OR in-full delivery, past 12 months",
        True, "LO",
    ),
    (
        "revenue: AND→OR on date+discount filter (same cols)",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "l_shipdate >= 1994-01-01 AND l_discount < 0.05",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "l_shipdate >= 1994-01-01 OR l_discount < 0.05",
        True, "LO",
    ),
    (
        "campaign_roi: AND→OR on channel+spend (same cols)",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "channel = email AND spend >= 500",
        ("campaigns", "transactions"),
        ("campaign_id", "customer_id", "spend", "channel", "amount"),
        "channel = email OR spend >= 500",
        True, "LO",
    ),
    (
        "support_load: NOT escalated vs all categories (same cols)",
        ("support_tickets", "customers"),
        ("customer_id", "ticket_id", "category", "region"),
        "category != escalated",
        ("support_tickets", "customers"),
        ("customer_id", "ticket_id", "category", "region"),
        "all categories including escalated",
        True, "LO",
    ),

    # ── CS: Column-Subset conflicts ───────────────────────────────────────
    # One lineage uses a strict subset of the other's columns.
    # Both D1 and D3 catch these; D2 also catches (different cols).
    (
        "customer_ltv: with vs without acctbal (subset)",
        ("customer", "orders"),
        ("c_custkey", "c_mktsegment", "c_acctbal", "o_totalprice"),
        "lifetime value with account balance",
        ("customer", "orders"),
        ("c_custkey", "c_mktsegment", "o_totalprice"),
        "lifetime value without account balance",
        True, "CS",
    ),
    (
        "revenue: with vs without discount col (subset)",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "l_discount", "o_orderdate"),
        "revenue with discount column",
        ("lineitem", "orders"),
        ("l_orderkey", "l_extendedprice", "o_orderdate"),
        "revenue without discount column",
        True, "CS",
    ),
    (
        "churn_rate: with vs without email (subset)",
        ("customers", "customer_pii", "transactions"),
        ("customer_id", "email", "txn_date"),
        "churn with email verification",
        ("customers", "customer_pii", "transactions"),
        ("customer_id", "txn_date"),
        "churn without email column",
        True, "CS",
    ),
    (
        "part_availability: with brand+type vs key only (subset)",
        ("part", "partsupp"),
        ("p_partkey", "p_brand", "p_type", "ps_availqty"),
        "availability by brand and type",
        ("part", "partsupp"),
        ("p_partkey", "ps_availqty"),
        "availability count only",
        True, "CS",
    ),
    (
        "active_customers: region+date vs date only (subset)",
        ("customers", "transactions"),
        ("customer_id", "region", "txn_date"),
        "active by region last 30 days",
        ("customers", "transactions"),
        ("customer_id", "txn_date"),
        "active last 30 days (no region split)",
        True, "CS",
    ),
]

# Verify counts
_tc  = sum(1 for p in PAIRS if p[7] and p[8] == "TC")
_tv  = sum(1 for p in PAIRS if not p[7])
_lo  = sum(1 for p in PAIRS if p[7] and p[8] == "LO")
_cs  = sum(1 for p in PAIRS if p[7] and p[8] == "CS")
assert len(PAIRS) == _tc + _tv + _lo + _cs, \
    f"Count mismatch: {len(PAIRS)} != {_tc}+{_tv}+{_lo}+{_cs}"


# ──────────────────────────────────────────────────────────────────────────
# Detectors (identical logic to original fuzzy_experiment.py)
# ──────────────────────────────────────────────────────────────────────────

def d1_exact(row) -> bool:
    """Exact hash: conflict iff definition_hash differs."""
    _, ta, ca, la, tb, cb, lb, gt, cat = row
    return def_hash(ta, ca, la) != def_hash(tb, cb, lb)

def d2_jaccard(row, threshold: float = 0.70) -> bool:
    """Jaccard: if tables+cols match, conflict iff token-Jaccard(filter) < threshold."""
    _, ta, ca, la, tb, cb, lb, gt, cat = row
    if set(ta) == set(tb) and set(ca) == set(cb):
        return token_jaccard(la, lb) < threshold
    return True  # different tables or columns → always conflict

def d3_column_graph(row) -> bool:
    """Column-graph: conflict iff tables differ OR column sets differ."""
    _, ta, ca, la, tb, cb, lb, gt, cat = row
    if set(ta) != set(tb):
        return True
    return set(ca) != set(cb)


# ──────────────────────────────────────────────────────────────────────────
# Evaluation helpers
# ──────────────────────────────────────────────────────────────────────────

def compute_prf(tp, fp, tn, fn):
    p  = tp / (tp + fp) if (tp + fp) else 0.0
    r  = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return round(p, 3), round(r, 3), round(f1, 3)

def evaluate(detector_fn, pairs):
    tp = fp = tn = fn = 0
    for row in pairs:
        gt   = row[7]
        pred = detector_fn(row)
        if pred and gt:       tp += 1
        elif pred and not gt: fp += 1
        elif not pred and gt: fn += 1
        else:                  tn += 1
    p, r, f1 = compute_prf(tp, fp, tn, fn)
    return {"TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": p, "recall": r, "f1": f1}

def bootstrap_ci(detector_fn, pairs, n_boot: int = 10_000, seed: int = 42):
    """Bootstrap 95% CI on P/R/F1 via resampling with replacement."""
    rng   = random.Random(seed)
    n     = len(pairs)
    vals  = {"precision": [], "recall": [], "f1": []}
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        tp = fp = tn = fn = 0
        for row in sample:
            gt   = row[7]
            pred = detector_fn(row)
            if pred and gt:       tp += 1
            elif pred and not gt: fp += 1
            elif not pred and gt: fn += 1
            else:                  tn += 1
        p, r, f1 = compute_prf(tp, fp, tn, fn)
        vals["precision"].append(p)
        vals["recall"].append(r)
        vals["f1"].append(f1)
    ci = {}
    for key, v in vals.items():
        v.sort()
        ci[key] = {
            "mean":   round(statistics.mean(v), 3),
            "ci_lo":  round(v[int(0.025 * n_boot)], 3),
            "ci_hi":  round(v[int(0.975 * n_boot)], 3),
        }
    return ci

def evaluate_by_category(detector_fn, pairs):
    cats: Dict[str, Dict] = {}
    for row in pairs:
        cat = row[8]
        cats.setdefault(cat, {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
        gt   = row[7]
        pred = detector_fn(row)
        if pred and gt:       cats[cat]["tp"] += 1
        elif pred and not gt: cats[cat]["fp"] += 1
        elif not pred and gt: cats[cat]["fn"] += 1
        else:                  cats[cat]["tn"] += 1
    return cats


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    n_total = len(PAIRS)
    n_tc    = sum(1 for p in PAIRS if p[7] and p[8] == "TC")
    n_tv    = sum(1 for p in PAIRS if not p[7])
    n_lo    = sum(1 for p in PAIRS if p[7] and p[8] == "LO")
    n_cs    = sum(1 for p in PAIRS if p[7] and p[8] == "CS")

    print(f"Extended dataset: {n_total} pairs total")
    print(f"  TC (True Conflict, diff tables/cols) : {n_tc}")
    print(f"  TV (Threshold Variant, same schema)  : {n_tv}")
    print(f"  LO (Logic-Operator change, same cols): {n_lo}")
    print(f"  CS (Column-Subset conflict)          : {n_cs}")
    print()

    detectors = [
        ("Exact Hash (D1)",              d1_exact),
        ("Jaccard Filter (D2, τ=0.70)",  d2_jaccard),
        ("Column-Graph (D3)",            d3_column_graph),
    ]

    results = {}
    for det_name, fn in detectors:
        r      = evaluate(fn, PAIRS)
        ci     = bootstrap_ci(fn, PAIRS)
        by_cat = evaluate_by_category(fn, PAIRS)
        results[det_name] = {**r, "bootstrap_ci": ci, "by_category": by_cat}

        print(f"{'─'*70}")
        print(f"{det_name}")
        print(f"  Overall — P={r['precision']:.3f}  R={r['recall']:.3f}  "
              f"F1={r['f1']:.3f}  "
              f"(TP={r['TP']} FP={r['FP']} TN={r['TN']} FN={r['FN']})")
        print(f"  Bootstrap 95% CI (10k resamples):")
        for metric in ["precision", "recall", "f1"]:
            c = ci[metric]
            print(f"    {metric:12s}: {c['mean']:.3f}  [{c['ci_lo']:.3f}, {c['ci_hi']:.3f}]")
        print(f"  By category:")
        for cat in ["TC", "TV", "LO", "CS"]:
            if cat not in by_cat:
                continue
            d = by_cat[cat]
            correct = d["tp"] + d["tn"]
            total   = sum(d.values())
            print(f"    {cat}: {correct}/{total} correct  "
                  f"(TP={d['tp']} FP={d['fp']} TN={d['tn']} FN={d['fn']})")

    print(f"\n{'─'*70}")
    print("Per-pair predictions  [GT / D1 / D2 / D3]:")
    for row in PAIRS:
        name_, gt, cat = row[0], row[7], row[8]
        p1, p2, p3 = d1_exact(row), d2_jaccard(row), d3_column_graph(row)
        m1 = "✓" if p1 == gt else "✗"
        m2 = "✓" if p2 == gt else "✗"
        m3 = "✓" if p3 == gt else "✗"
        lbl = "TC" if (gt and cat == "TC") else cat
        print(f"  [{lbl}] {name_[:55]:55s}  D1{m1} D2{m2} D3{m3}")

    lo_d3_fn = results["Column-Graph (D3)"]["by_category"].get("LO", {}).get("fn", 0)
    lo_d1_tp = results["Exact Hash (D1)"]["by_category"].get("LO", {}).get("tp", 0)
    print(f"\nKey finding — LO (AND→OR) category:")
    print(f"  D3 FN: {lo_d3_fn}/{n_lo}  (column-graph blind to operator changes)")
    print(f"  D1 TP: {lo_d1_tp}/{n_lo}  (hash change catches every operator change)")
    print(f"  Implication: production deployment needs D3 + filter-logic check for full coverage.")

    output = {
        "dataset_stats": {
            "total": n_total, "TC": n_tc, "TV": n_tv,
            "LO": n_lo, "CS": n_cs,
        },
        "detectors": results,
    }
    with open("fuzzy_results_extended.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\nSaved fuzzy_results_extended.json")
    print("fuzzy_results.json is unchanged.")
