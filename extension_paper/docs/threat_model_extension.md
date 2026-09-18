# Threat Model Extension: Materialization-Boundary Attacks (Group B1)

This document formalizes the attack PR #1's `adversarial_lineage_experiment.py`
demonstrated empirically, states its relationship to the published paper's
threat model, and gives an informal safety argument for the transitive
lineage closure fix -- including precisely where that argument stops
holding.

## 1. The attack, formally

Let `income` be a sensitive column recorded in `SENSITIVE_COLUMNS`, and let
`P(d)` be the permitted-column set for department `d`, with `income ∉
P(Marketing)`.

**Step 1 -- correct baseline behavior.** Finance computes an AMU
`a₀ = (risk_score, L₀, Finance)` where `L₀` is a lineage that reads
`customer_pii.income`. By construction, `sensitivity_tags(a₀) = {income}`.
A `Marketing` request for `risk_score` is correctly gate-blocked: `{income}
⊄ P(Marketing)`.

**Step 2 -- materialization.** `risk_score` is persisted as a column in a
downstream table `derived_features.risk_score` -- an entirely ordinary
step in any real data-engineering pipeline (a feature store, a reporting
mart, a scheduled ETL job). This is not a workaround or an adversarial
maneuver by any actor; it is normal practice the published system's threat
model does not consider.

**Step 3 -- the boundary crossing.** A second AMU,
`a₁ = (high_risk_customers, L₁, d')`, is derived by reading
`derived_features.risk_score` alone. Its recorded lineage is
`L₁ = {(derived_features, {risk_score})}`. Critically,
`all_columns(L₁) = {risk_score}`, and `risk_score ∉ SENSITIVE_COLUMNS` --
the sensitivity registry has no entry for it, because sensitivity is
recorded per *source* column, and `risk_score` is a *derived* column one
hop downstream. Therefore `sensitivity_tags(a₁) = ∅`.

**Step 4 -- the leak.** `Marketing` requests `high_risk_customers`. The
stock gate checks `sensitivity_tags(a₁) ⊆ P(Marketing)`, i.e. `∅ ⊆
P(Marketing)`, which is trivially true. The AMU is served. `income` has
now reached `Marketing` -- not by name, but through one layer of
materialization -- despite the gate at Step 1 working exactly as designed
and specified.

## 2. Relationship to the paper's stated assumptions and Theorem 1

The published paper's safety guarantee (Theorem 1: the gate never serves an
AMU whose lineage's sensitive columns exceed the requester's permitted set)
is conditioned on **Assumption 1 (Complete Lineage Recording)**: an AMU's
recorded `Lineage` reflects every table/column its value was actually
derived from.

This attack is not a counterexample to Theorem 1 -- Theorem 1's proof is
still valid given its stated hypothesis. It is a demonstration that
**Assumption 1 is more load-bearing than the published paper's own framing
suggests**, and that it fails in a specific, structural way the paper does
not name: a materialization boundary. `L₁`'s recorded lineage is *locally*
complete (it accurately reflects every column touched by the query that
produced `a₁`) but *globally* incomplete (it does not reflect `a₁`'s full
transitive provenance back through `risk_score` to `income`).

We treat this as a **sharpened version of Assumption 1's scope**, not a new
threat vector requiring a new formal category: the paper's existing
"Complete Lineage Recording" assumption, read precisely, already requires
what closure restores -- it simply doesn't say so explicitly, and nothing
in the original implementation enforces it across a materialization
boundary. A future revision of the paper's Assumption 1 should say, in
words close to this: *"lineage recording is complete with respect to the
full transitive provenance of a value, including through any intermediate
materialized columns the pipeline persists — not merely with respect to
the immediate query that produced the AMU being written."*

## 3. The fix: transitive lineage closure

`close_lineage(lineage, registry)` (`amu_ext/materialization.py`, lifted
from PR #1's experiment): for every column `c` in a lineage step
`(table, columns)`, if `(table, c)` has a registered upstream `Lineage` in
a `MaterializationRegistry`, recursively close and union in that upstream
lineage's steps. The registry entry `(table, column) -> upstream_lineage`
is written at materialization time by whichever process persists the
derived column -- in the experiment, the same write step that produces
`a₀` also calls `registry.register("derived_features", "risk_score", L₀)`.

### 3.1 Informal safety argument

**Claim.** If every materialization boundary a downstream AMU's lineage
crosses has a corresponding registered provenance edge, then
`sensitivity_tags(close_lineage(L, registry)) ⊇ sensitivity_tags(L_true)`,
where `L_true` is the value's true, full transitive provenance -- i.e.
closure restores at least the safety-relevant part of Assumption 1.

**Sketch.** `close_lineage` is a fixed-point unrolling of the registry's
`(table, column) -> Lineage` edges, bounded by `_max_depth` (a cycle guard;
real provenance graphs in this system are acyclic by construction, since a
column can't be materialized from a value that is itself derived from that
same materialization without an infinite regress in the *actual* pipeline
too). By induction on chain depth: at depth 0, closure is the identity (no
registered edge, `L = L_true`'s immediate columns). At depth `k+1`, if the
column at the current step has a registered upstream edge, closure unions
in that upstream's (recursively closed) steps -- exactly the edge that
Step 3 above shows the stock gate is missing. Applying this at every step
of every hop means every registered materialization boundary the lineage
actually crosses is walked, and `all_columns(closed L) ⊇ all_columns(L_true)`
restricted to the registered subgraph. Intersecting with `SENSITIVE_COLUMNS`
preserves the superset relationship. QED (informal) for the registered
case.

### 3.2 Precisely where the guarantee does not hold

The claim's hypothesis -- "every materialization boundary ... has a
corresponding registered provenance edge" -- is doing all the work, and it
is not automatically true. Closure provably does **not** restore the
guarantee when:

1. **Unregistered materialization.** A process persists a derived column
   without calling `registry.register(...)` -- e.g. a batch job outside
   this system's write path, a manual `CREATE TABLE AS SELECT`, a cached
   view materialized by the warehouse engine itself. `close_lineage` has no
   edge to walk and returns the lineage unchanged; the leak from Section 1
   reproduces exactly. **This is the realistic common case, not an edge
   case** -- most enterprise data platforms have several such paths (ETL
   tools, warehouse materialized views, ad hoc `CTAS` statements) that this
   system does not instrument.
2. **Statistical / non-lineal derivation.** A materialized column that is
   a *function* of a sensitive column without a literal column-copy
   relationship -- e.g. a feature store computing `income_bucket =
   bucketize(income)`, or a model score that uses `income` as one of many
   inputs. Even a *registered* provenance edge for such a column would need
   to correctly declare `income` as an upstream dependency; if the
   registration itself under-reports (analogous to Assumption 1's original
   failure mode, just one level removed), closure inherits that gap.
3. **Cyclic or pathologically deep chains.** `_max_depth` bounds recursion
   depth to guard against a malformed registry; a legitimate chain deeper
   than this bound is truncated. In practice this system's chains are 1-2
   hops, so this is a defensive guard, not an active limitation observed
   in any experiment here -- but it is a real boundary of the guarantee,
   not merely a hypothetical one, and is worth stating plainly.

Group B3's regression test (`tests/regression/test_unregistered_materialization.py`)
constructs case (1) directly: an unregistered materialization edge, and
asserts `close_lineage` does **not** catch it (leak rate stays > 0),
because a claim this important should be backed by a real, executed
failing-to-close test, not just this document's prose. See
`docs/limitations.md` for how this bounds what the extension paper claims.
