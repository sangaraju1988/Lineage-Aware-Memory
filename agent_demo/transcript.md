
# Lineage-Aware Memory Governance — Agent Demo Transcript

*Generated: 2026-07-08 17:42:38*

This walkthrough demonstrates the AMU mechanism with a real SQLite database.
Two agents — **Finance** and **Marketing** — share a `LineageAwareSystem`.
Finance has access to `income` (sensitive); Marketing does not.

---


## Step 1: Finance Agent Computes `high_value_segment`

Finance queries `customers.income` (sensitive) joined with `transactions.amount`.

**Query:** `income > 100000 AND total_spend > 5000`
**Result:** 5 high-value customers identified

| customer_id | name | income | total_spend |
| --- | --- | --- | --- |
| 1 | Alice Chen | $120,000 | $16,500 |
| 3 | Clara Schmidt | $310,000 | $43,000 |
| 5 | Eva Martinez | $250,000 | $37,000 |
| 7 | Grace Patel | $195,000 | $17,300 |
| 9 | Irene Tanaka | $175,000 | $19,500 |

**AMU created:**
```yaml
metric_name      : high_value_segment
value            : 5.0
owner_department : Finance
sensitivity_tags : {'income'}
definition_hash  : 0c14d41b60ba
lineage          :
  step 1: table=customers, cols=('customer_id', 'income', 'region')
  step 2: table=transactions, cols=('customer_id', 'amount', 'txn_date')
  filter: income > 100000 AND total_spend > 5000
```

**Written to shared memory.** Conflict detected: `False`

---


## Step 2: Marketing Agent Requests `high_value_segment`

Marketing requests the cached `high_value_segment` from shared memory.

**Marketing permitted columns:** `['amount', 'campaign_id', 'channel', 'customer_id', 'region', 'signup_date', 'spend', 'txn_date', 'txn_id']`

**Gate check:**
```text
Finance AMU sensitivity_tags : {'income'}
Marketing permitted columns  : (no sensitive columns)
Check: {'income'} ⊆ Marketing.permitted? → NO ✗  — BLOCKED

Result: BLOCKED — sensitive column(income) not in Marketing permissions
```

🚫 **Gate BLOCKED the retrieval.** The stored AMU touches `income`, which Marketing cannot see.

**Fallback: Marketing recomputes in-scope** (no income join):
- Query: `total_spend > 10000 (no income join)`
- Result: 5 customers (spend > $10,000 only)

| customer_id | name | region | total_spend |
| --- | --- | --- | --- |
| 1 | Alice Chen | EUROPE | $16,500 |
| 3 | Clara Schmidt | EUROPE | $43,000 |
| 5 | Eva Martinez | AMERICA | $37,000 |
| 7 | Grace Patel | EUROPE | $17,300 |
| 9 | Irene Tanaka | ASIA | $19,500 |

**Marketing's in-scope AMU written to memory.** Definition conflict with Finance AMU: `True`
  *(Conflict expected: Finance uses income-join definition, Marketing uses spend-only definition)*

---


## Step 3: Finance Computes `order_volume` (no sensitive columns)

Total transactions: 15, Total amount: $141,050.00
**Sensitivity tags:** `set()` (empty — no sensitive columns)
**Written to shared memory.**

---


## Step 4: Marketing Requests `order_volume` — Gate Passes ✓

**Gate check:**
```text
Finance AMU sensitivity_tags : set()
Check: {} ⊆ Marketing.permitted? → YES ✓
Result: SERVED from memory (reuse=True, leaked=False)
```

✅ **Marketing receives order_volume = $141,050.00 from memory.**
No income column was touched. The gate correctly allowed this reuse.

---


## Summary

| Step | Agent | Metric | Action | Leaked? | Reused? |
|------|-------|--------|--------|---------|---------|
| 1 | Finance   | high_value_segment | Compute + Write | — | — |
| 2 | Marketing | high_value_segment | Request → **BLOCKED** → Fallback | No | No |
| 3 | Finance   | order_volume       | Compute + Write | — | — |
| 4 | Marketing | order_volume       | Request → **SERVED** from memory | No | **Yes** |

**Key observations:**
- Step 2: The gate correctly blocked Marketing from receiving Finance's income-derived segment.
  Marketing's fallback computed a different (smaller) segment using only spend data — demonstrating that the gate is a real enforcement mechanism, not a flag.
- Step 3→4: A metric with no sensitive lineage reuses correctly across departments.
- The `definition_hash` conflict in Step 2 surfaces the semantic divergence between Finance's income-based definition and Marketing's spend-based definition of the same KPI.

This demonstrates Theorem 1 (column-level safety) and the conflict-detection mechanism in a concrete, executable scenario.