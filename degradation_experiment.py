"""
Lineage-Completeness Degradation Experiment
============================================

Models the impact of an agent under-reporting its own derivation columns —
a realistic failure covered by Threat T5 in the paper (malicious or buggy
lineage fabrication). At completeness < 1.0, a random fraction of each
AMU's lineage columns are silently dropped BEFORE the lineage is stored.
The gate check then uses the truncated lineage, causing false passes that
allow restricted columns to leak.

Completeness levels: 0.5, 0.75, 0.9, 0.95, 1.0
  1.0 = full honest reporting   (baseline, must reproduce paper result: 0% leak)
  0.5 = only half the columns reported (severe under-reporting)

Leak detection (accurate):
  We maintain a shadow store of the ORIGINAL full sensitivity_tags alongside
  each stored (truncated) AMU. A retrieval is counted as a LEAK when:
    (a) the truncated gate check passes (truncated sensitivity ⊆ permitted), AND
    (b) the ORIGINAL full sensitivity would have blocked it (full sensitivity ⊄ permitted)

At completeness=1.0 no columns are dropped, so (b) never fires → 0% leak,
matching the paper's formal safety guarantee.

Both schemas tested:
  - Synthetic 5-table (reusing simulate.py infrastructure)
  - TPC-H 8-table    (reusing tpch_experiment.py infrastructure)

30 seeds per (schema, completeness) combination, matching the paper's protocol.

Output: degradation_results.json
"""

import random
import statistics
import json
from dataclasses import dataclass
from typing import List, Dict, Set
from collections import defaultdict

# ── Synthetic schema imports ────────────────────────────────────────────
from model import (
    AMU, Lineage, LineageStep,
    SENSITIVE_COLUMNS, DEPARTMENT_PERMISSIONS,
)
from simulate import generate_workload

# ── TPC-H schema imports ────────────────────────────────────────────────
from tpch_experiment import (
    TAMU, TLineage, TLineageStep,
    TPCH_SENSITIVE, TPCH_DEPT_PERMISSIONS,
    generate_tpch_workload,
)

COMPLETENESS_LEVELS = [0.5, 0.75, 0.9, 0.95, 1.0]
N_SEEDS = 30


# ─────────────────────────────────────────────────────────────────────────
# Lineage truncation helpers
# ─────────────────────────────────────────────────────────────────────────

def truncate_lineage(lineage: Lineage, completeness: float, rng: random.Random) -> Lineage:
    """Return a new Lineage with only `completeness` fraction of columns retained.
    At least 1 column per step is always kept so the step isn't vacuous.
    """
    if completeness >= 1.0:
        return lineage
    new_steps = []
    for step in lineage.steps:
        cols = list(step.columns_used)
        k = max(1, round(len(cols) * completeness))
        kept = sorted(rng.sample(cols, k))
        new_steps.append(LineageStep(step.table, tuple(kept)))
    return Lineage(steps=tuple(new_steps), filter_logic=lineage.filter_logic)


def truncate_tlineage(lineage: TLineage, completeness: float, rng: random.Random) -> TLineage:
    if completeness >= 1.0:
        return lineage
    new_steps = []
    for step in lineage.steps:
        cols = list(step.columns_used)
        k = max(1, round(len(cols) * completeness))
        kept = sorted(rng.sample(cols, k))
        new_steps.append(TLineageStep(step.table, tuple(kept)))
    return TLineage(steps=tuple(new_steps), filter_logic=lineage.filter_logic)


# ─────────────────────────────────────────────────────────────────────────
# Degraded Lineage-Aware System (Synthetic schema)
# ─────────────────────────────────────────────────────────────────────────

class DegradedLineageAwareSystem:
    """LineageAware system where each AMU's lineage is truncated to
    `completeness` fraction of its columns before being persisted.

    A shadow store tracks the ORIGINAL full sensitivity_tags so that
    leak detection can determine whether a gate false-pass caused a leak.

    At completeness=1.0, truncated == original → zero leaks (reproduces
    the paper's formal guarantee under honest lineage).
    """

    def __init__(self, completeness: float, rng: random.Random):
        self.completeness = completeness
        self.rng = rng
        self.store: Dict[str, list] = defaultdict(list)
        # Shadow: list of full sensitivity_tags parallel to self.store[metric]
        self.full_sensitivity: Dict[str, List[Set[str]]] = defaultdict(list)

    def write(self, amu: AMU) -> bool:
        truncated_lineage = truncate_lineage(amu.lineage, self.completeness, self.rng)
        truncated_amu = AMU(
            metric_name=amu.metric_name,
            value=amu.value,
            owner_department=amu.owner_department,
            lineage=truncated_lineage,
            epoch=amu.epoch,
        )
        # Conflict detection uses the truncated hash (reflects what the system sees)
        existing = self.store.get(amu.metric_name, [])
        conflict = any(
            e.owner_department != truncated_amu.owner_department
            and e.definition_hash != truncated_amu.definition_hash
            for e in existing
        )
        self.store[amu.metric_name].append(truncated_amu)
        # Shadow: store the FULL (original) sensitivity_tags in parallel
        self.full_sensitivity[amu.metric_name].append(amu.sensitivity_tags)
        return conflict

    def request(self, metric_name: str, requester_dept: str, fresh_amu: AMU) -> Dict:
        candidates = self.store.get(metric_name, [])
        full_sens_list = self.full_sensitivity.get(metric_name, [])
        permitted = DEPARTMENT_PERMISSIONS[requester_dept]
        blocked = False

        for idx in range(len(candidates) - 1, -1, -1):  # most-recent first
            amu = candidates[idx]
            truncated_sensitive = amu.sensitivity_tags

            if truncated_sensitive - permitted:
                # Even truncated check fails → definitely block
                blocked = True
                continue

            # Truncated gate passed — look up the original full sensitivity_tags
            original_sensitive = full_sens_list[idx] if idx < len(full_sens_list) else truncated_sensitive
            # Is this actually a leak? (original had restricted cols that truncation hid)
            is_leak = bool(original_sensitive - permitted)
            return {
                "reused": True,
                "blocked": False,
                "leaked": is_leak,
            }

        # No candidate passed → fresh compute (always safe)
        return {"reused": False, "blocked": blocked, "leaked": False}


# ─────────────────────────────────────────────────────────────────────────
# Degraded Lineage-Aware System (TPC-H schema)
# ─────────────────────────────────────────────────────────────────────────

class DegradedTLineageAwareSystem:

    def __init__(self, completeness: float, rng: random.Random):
        self.completeness = completeness
        self.rng = rng
        self.store: Dict[str, list] = defaultdict(list)
        self.full_sensitivity: Dict[str, List[Set[str]]] = defaultdict(list)

    def write(self, amu: TAMU) -> bool:
        truncated_lineage = truncate_tlineage(amu.lineage, self.completeness, self.rng)
        truncated_amu = TAMU(
            metric_name=amu.metric_name,
            value=amu.value,
            owner_department=amu.owner_department,
            lineage=truncated_lineage,
            epoch=amu.epoch,
        )
        existing = self.store.get(amu.metric_name, [])
        conflict = any(
            e.owner_department != truncated_amu.owner_department
            and e.definition_hash != truncated_amu.definition_hash
            for e in existing
        )
        self.store[amu.metric_name].append(truncated_amu)
        self.full_sensitivity[amu.metric_name].append(amu.sensitivity_tags)
        return conflict

    def request(self, metric_name: str, requester_dept: str, fresh_amu: TAMU) -> Dict:
        candidates = self.store.get(metric_name, [])
        full_sens_list = self.full_sensitivity.get(metric_name, [])
        permitted = TPCH_DEPT_PERMISSIONS[requester_dept]
        blocked = False

        for idx in range(len(candidates) - 1, -1, -1):
            amu = candidates[idx]
            if amu.sensitivity_tags - permitted:
                blocked = True
                continue
            original_sensitive = full_sens_list[idx] if idx < len(full_sens_list) else amu.sensitivity_tags
            is_leak = bool(original_sensitive - permitted)
            return {"reused": True, "blocked": False, "leaked": is_leak}

        return {"reused": False, "blocked": blocked, "leaked": False}


# ─────────────────────────────────────────────────────────────────────────
# Run one simulation at a given completeness level
# ─────────────────────────────────────────────────────────────────────────

def run_synthetic_degraded(completeness: float, seed: int) -> Dict:
    rng = random.Random(seed)
    random.seed(seed)
    events = generate_workload()
    system = DegradedLineageAwareSystem(completeness=completeness, rng=rng)

    leaked = reused = blocked = total = 0

    for ev in events:
        amu = AMU(
            metric_name=ev.metric_name,
            value=round(rng.uniform(0, 100), 2),
            owner_department=ev.department,
            lineage=ev.lineage,
            epoch=ev.epoch,
        )
        result = system.request(ev.metric_name, ev.department, amu)
        system.write(amu)
        total += 1
        reused  += int(result["reused"])
        leaked  += int(result["leaked"])
        blocked += int(result["blocked"])

    return {
        "leak_rate":  round(100 * leaked  / max(total, 1), 2),
        "reuse_rate": round(100 * reused  / max(total, 1), 2),
        "leaked": leaked, "reused": reused, "total": total,
    }


def run_tpch_degraded(completeness: float, seed: int) -> Dict:
    rng = random.Random(seed)
    random.seed(seed)
    events = generate_tpch_workload()
    system = DegradedTLineageAwareSystem(completeness=completeness, rng=rng)

    leaked = reused = blocked = total = 0

    for ev in events:
        amu = TAMU(
            metric_name=ev.metric_name,
            value=round(rng.uniform(0, 1e6), 2),
            owner_department=ev.department,
            lineage=ev.lineage,
            epoch=ev.epoch,
        )
        result = system.request(ev.metric_name, ev.department, amu)
        system.write(amu)
        total += 1
        reused  += int(result["reused"])
        leaked  += int(result["leaked"])
        blocked += int(result["blocked"])

    return {
        "leak_rate":  round(100 * leaked  / max(total, 1), 2),
        "reuse_rate": round(100 * reused  / max(total, 1), 2),
        "leaked": leaked, "reused": reused, "total": total,
    }


# ─────────────────────────────────────────────────────────────────────────
# Full sweep: completeness levels × seeds × schemas
# ─────────────────────────────────────────────────────────────────────────

def run_full_sweep() -> Dict:
    results = {"synthetic": {}, "tpch": {}}

    print("=== Lineage-Completeness Degradation Experiment ===\n")
    print(f"{'Schema':12s} {'Completeness':>14s} {'Leak % (mean±sd)':>22s} {'Reuse % (mean±sd)':>22s}")
    print("-" * 76)

    for schema_name, run_fn in [("synthetic", run_synthetic_degraded),
                                 ("tpch",      run_tpch_degraded)]:
        results[schema_name] = {}
        for c in COMPLETENESS_LEVELS:
            seed_results = [run_fn(c, s) for s in range(N_SEEDS)]
            leak_vals  = [r["leak_rate"]  for r in seed_results]
            reuse_vals = [r["reuse_rate"] for r in seed_results]

            summary = {
                "completeness": c,
                "leak_mean":  round(statistics.mean(leak_vals),   2),
                "leak_sd":    round(statistics.pstdev(leak_vals),  2),
                "reuse_mean": round(statistics.mean(reuse_vals),  2),
                "reuse_sd":   round(statistics.pstdev(reuse_vals), 2),
                "per_seed":   seed_results,
            }
            results[schema_name][str(c)] = summary
            print(f"{schema_name:12s} {c:>14.2f} "
                  f"{summary['leak_mean']:>7.1f} ± {summary['leak_sd']:<8.1f}"
                  f"{summary['reuse_mean']:>7.1f} ± {summary['reuse_sd']:<6.1f}")

    return results


if __name__ == "__main__":
    results = run_full_sweep()

    with open("degradation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved degradation_results.json")
    print("\nSanity check — completeness=1.0 leak rates (must be 0.0):")
    for schema in ["synthetic", "tpch"]:
        v = results[schema]["1.0"]["leak_mean"]
        status = "✓" if v == 0.0 else f"✗ UNEXPECTED: {v}"
        print(f"  {schema}: {v}%  {status}")
