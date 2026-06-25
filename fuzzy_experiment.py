"""
Fuzzy conflict-detection experiment for the paper.

The exact definition_hash approach flags any two lineages with different
(tables, columns, filter_logic) as conflicting.  This experiment asks:
when lineages differ only in numeric thresholds inside the filter string
(e.g. "no txn in 90 days" vs "no txn in 60 days"), is exact-hash matching
too strict, too loose, or about right?  We compare three detectors:

  D1 — Exact hash  : two AMUs conflict iff definition_hash differs
  D2 — Jaccard/token : two AMUs conflict iff token-Jaccard of filter_logic < 0.7
  D3 — Column-graph : two AMUs conflict iff they share ≥1 table but have
                       different column sets  (schema-level divergence only)

We build a small ground-truth dataset of lineage pairs labelled as
TRUE_CONFLICT (different join paths / semantically different metrics) or
THRESHOLD_VARIANT (same join path, only filter threshold changed —
arguably the same metric, just recalibrated).

The experiment measures precision and recall for each detector against
this ground truth, plus a combined measure.
"""

import hashlib, re, random, statistics
from dataclasses import dataclass
from typing import Set, Tuple, List, Dict

# ── Helpers ──────────────────────────────────────────────────────────────

def def_hash(tables: Tuple[str,...], cols: Tuple[str,...], logic: str) -> str:
    payload = f"{sorted(tables)}|{sorted(cols)}|{logic}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]

def token_jaccard(a: str, b: str) -> float:
    ta = set(re.split(r'\W+', a.lower()))
    tb = set(re.split(r'\W+', b.lower()))
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union) if union else 1.0

# ── Ground-truth pair types ───────────────────────────────────────────────
# Each pair: (name, tables_a, cols_a, logic_a, tables_b, cols_b, logic_b, is_true_conflict)
# TRUE_CONFLICT  : different join paths or different columns → genuine semantic split
# THRESHOLD_VARIANT: same schema, same columns, only a numeric threshold changed

PAIRS = [
    # --- TRUE CONFLICTS (different tables/cols) ---
    (
        "churn_rate: txn-only vs pii-adjusted",
        ("customers","transactions"),
        ("customer_id","signup_date","txn_date","amount"),
        "no txn in 90 days",
        ("customers","customer_pii","transactions"),
        ("customer_id","signup_date","income","txn_date","amount"),
        "no txn in 60 days AND income-segment adjusted",
        True,
    ),
    (
        "active_customers: txn-based vs campaign-based",
        ("customers","transactions"),
        ("customer_id","region","txn_date"),
        "txn in last 30 days",
        ("customers","campaigns"),
        ("customer_id","region","channel"),
        "any campaign engagement in last 30 days",
        True,
    ),
    (
        "revenue: gross vs net-of-discount",
        ("lineitem","orders"),
        ("l_orderkey","l_extendedprice","o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01",
        ("lineitem","orders"),
        ("l_orderkey","l_extendedprice","l_discount","o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01 net of discount",
        True,
    ),
    (
        "customer_ltv: financial vs engagement-only",
        ("customer","orders","lineitem"),
        ("c_custkey","c_mktsegment","c_acctbal","o_totalprice","l_extendedprice","l_discount"),
        "c_mktsegment = 'BUILDING' AND orders in last 2 years",
        ("customer","orders","lineitem"),
        ("c_custkey","c_mktsegment","o_orderdate","l_quantity","l_shipdate"),
        "c_mktsegment = 'BUILDING' AND orders in last 2 years (no financials)",
        True,
    ),
    (
        "supplier_perf: balance-adjusted vs on-time only",
        ("supplier","partsupp","lineitem"),
        ("s_suppkey","s_acctbal","s_name","ps_supplycost","ps_availqty","l_quantity","l_extendedprice"),
        "supplier balance-adjusted performance, past 1 year",
        ("supplier","partsupp","lineitem"),
        ("s_suppkey","s_name","ps_availqty","l_quantity","l_linestatus"),
        "on-time delivery rate, past 1 year (no financials)",
        True,
    ),

    # --- THRESHOLD VARIANTS (same schema, only numeric threshold changed) ---
    (
        "churn_rate: 90-day vs 60-day window (same columns)",
        ("customers","transactions"),
        ("customer_id","signup_date","txn_date","amount"),
        "no txn in 90 days",
        ("customers","transactions"),
        ("customer_id","signup_date","txn_date","amount"),
        "no txn in 60 days",
        False,   # NOT a true conflict — same schema, just recalibrated
    ),
    (
        "active_customers: 30-day vs 14-day window",
        ("customers","transactions"),
        ("customer_id","region","txn_date"),
        "txn in last 30 days",
        ("customers","transactions"),
        ("customer_id","region","txn_date"),
        "txn in last 14 days",
        False,
    ),
    (
        "high_value_segment: income decile 9-10 vs 8-10",
        ("customer_pii","transactions"),
        ("customer_id","income","amount"),
        "income decile 9-10",
        ("customer_pii","transactions"),
        ("customer_id","income","amount"),
        "income decile 8-10",
        False,
    ),
    (
        "revenue: 1994 window vs 1993 window (same cols)",
        ("lineitem","orders"),
        ("l_orderkey","l_extendedprice","o_orderdate"),
        "l_shipdate BETWEEN 1994-01-01 AND 1995-01-01",
        ("lineitem","orders"),
        ("l_orderkey","l_extendedprice","o_orderdate"),
        "l_shipdate BETWEEN 1993-01-01 AND 1994-01-01",
        False,
    ),
    (
        "campaign_roi: 14-day vs 7-day attribution window",
        ("campaigns","transactions"),
        ("campaign_id","customer_id","spend","channel","amount"),
        "revenue attributed within 14-day window",
        ("campaigns","transactions"),
        ("campaign_id","customer_id","spend","channel","amount"),
        "revenue attributed within 7-day window",
        False,
    ),
]


# ── Detectors ─────────────────────────────────────────────────────────────

def d1_exact(row) -> bool:
    """Exact hash: conflict iff definition_hash differs."""
    name, ta, ca, la, tb, cb, lb, gt = row
    ha = def_hash(ta, ca, la)
    hb = def_hash(tb, cb, lb)
    return ha != hb

def d2_jaccard(row, threshold=0.70) -> bool:
    """Jaccard token similarity on filter_logic: conflict if similarity < threshold."""
    name, ta, ca, la, tb, cb, lb, gt = row
    # Same tables AND same columns? Then only the filter differs — check Jaccard
    if set(ta) == set(tb) and set(ca) == set(cb):
        return token_jaccard(la, lb) < threshold
    # Different tables or columns → always a conflict
    return True

def d3_column_graph(row) -> bool:
    """Schema divergence: conflict if same tables but different column sets."""
    name, ta, ca, la, tb, cb, lb, gt = row
    if set(ta) != set(tb):
        return True   # different join paths → conflict
    return set(ca) != set(cb)   # same tables, different columns → conflict


def evaluate(detector_fn, pairs):
    tp = fp = tn = fn = 0
    for row in pairs:
        gt = row[7]
        pred = detector_fn(row)
        if pred and gt:     tp += 1
        elif pred and not gt: fp += 1
        elif not pred and gt: fn += 1
        else:                 tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2*precision*recall / (precision+recall) if (precision+recall) else 0.0
    return {"TP":tp,"FP":fp,"TN":tn,"FN":fn,
            "precision":round(precision,3),
            "recall":round(recall,3),
            "f1":round(f1,3)}


if __name__ == "__main__":
    import json

    results = {}
    for name, fn in [("Exact Hash (D1)", d1_exact),
                     ("Jaccard Filter (D2, τ=0.70)", d2_jaccard),
                     ("Column-Graph (D3)", d3_column_graph)]:
        r = evaluate(fn, PAIRS)
        results[name] = r
        print(f"{name:35s}  P={r['precision']:.2f}  R={r['recall']:.2f}  "
              f"F1={r['f1']:.2f}  (TP={r['TP']} FP={r['FP']} TN={r['TN']} FN={r['FN']})")

    # print pair-level breakdown for transparency
    print("\nPer-pair predictions (GT / D1 / D2 / D3):")
    for row in PAIRS:
        name = row[0]; gt = row[7]
        p1=d1_exact(row); p2=d2_jaccard(row); p3=d3_column_graph(row)
        match1 = "✓" if p1==gt else "✗"
        match2 = "✓" if p2==gt else "✗"
        match3 = "✓" if p3==gt else "✗"
        label = "TC" if gt else "TV"
        print(f"  [{label}] {name[:55]:55s}  D1{match1} D2{match2} D3{match3}")

    with open("fuzzy_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved fuzzy_results.json")
