"""
Conformance check: does the amu_governance PyPI package (0.1.0,
policy-agnostic) reproduce identical behavior to this repo's root
model.py/systems.py (the code that produced the paper's published
synthetic-schema numbers) on the exact seeded workload from simulate.py?

This is a documentation/trust check, not a bugfix: model.py/systems.py is
the frozen artifact behind the published results and is not meant to be
edited to match the package. If this test ever fails, that is a real
finding (the package has diverged from what produced the paper's numbers)
and should be reported, not silently reconciled -- see the "Relationship
between this repository and the amu-governance package" section of
README.md.

Requires: pip install amu-governance
Run with: python test_package_conformance.py   (or: pytest test_package_conformance.py)
"""

import random
import sys

import model as old_model
import systems as old_systems

from amu_governance import AMU as NewAMU
from amu_governance import Lineage as NewLineage
from amu_governance import LineageStep as NewLineageStep
from amu_governance import GovernancePolicy
from amu_governance import LineageAwareSystem as NewLineageAwareSystem
from amu_governance import NaiveMemorySystem as NewNaiveMemorySystem
from amu_governance import NoMemorySystem as NewNoMemorySystem

from simulate import METRIC_VARIANTS, DEPARTMENTS

N_SEEDS = 30

policy = GovernancePolicy(
    sensitive_columns=set(old_model.SENSITIVE_COLUMNS),
    department_permissions={k: set(v) for k, v in old_model.DEPARTMENT_PERMISSIONS.items()},
)


def _as_new_variants():
    """Rebuild simulate.py's METRIC_VARIANTS using the package's Lineage/
    LineageStep classes instead of model.py's, from the same literal data."""
    out = {}
    for metric, variants in METRIC_VARIANTS.items():
        out[metric] = [
            NewLineage(
                steps=tuple(NewLineageStep(s.table, s.columns_used) for s in lineage.steps),
                filter_logic=lineage.filter_logic,
            )
            for lineage in variants
        ]
    return out


def generate_events(n_epochs=20, events_per_epoch=6):
    metric_names = list(METRIC_VARIANTS.keys())
    events = []
    for epoch in range(n_epochs):
        for _ in range(events_per_epoch):
            dept = random.choice(DEPARTMENTS)
            metric = random.choice(metric_names)
            variant_idx = random.choice(range(len(METRIC_VARIANTS[metric])))
            value = round(random.uniform(0, 100), 2)
            events.append((epoch, dept, metric, variant_idx, value))
    return events


def _stats_template():
    return {name: {"served": 0, "leaked": 0, "reused": 0, "blocked": 0, "cross": 0}
            for name in ("no_memory", "naive", "lineage_aware")}


def run_old(events):
    systems = {
        "no_memory": old_systems.NoMemorySystem(),
        "naive": old_systems.NaiveMemorySystem(),
        "lineage_aware": old_systems.LineageAwareSystem(),
    }
    stats = _stats_template()
    flagged = 0
    for epoch, dept, metric, variant_idx, value in events:
        lineage = METRIC_VARIANTS[metric][variant_idx]
        amu = old_model.AMU(metric_name=metric, value=value, owner_department=dept,
                             lineage=lineage, epoch=epoch)
        for name, system in systems.items():
            s = stats[name]
            if name != "no_memory":
                s["cross"] += 1
            if name == "naive":
                result = system.request(metric, dept, amu)
                system.write(amu)
            elif name == "lineage_aware":
                result = system.request(metric, dept, amu)
                if system.write(amu):
                    flagged += 1
            else:
                result = system.request(metric, dept, amu)
            s["served"] += int(result.served)
            s["leaked"] += int(result.leaked)
            s["reused"] += int(result.reused)
            s["blocked"] += int(result.blocked)
    return stats, flagged


def run_new(events, new_variants):
    systems = {
        "no_memory": NewNoMemorySystem(policy),
        "naive": NewNaiveMemorySystem(policy),
        "lineage_aware": NewLineageAwareSystem(policy),
    }
    stats = _stats_template()
    flagged = 0
    for epoch, dept, metric, variant_idx, value in events:
        lineage = new_variants[metric][variant_idx]
        amu = NewAMU(metric_name=metric, value=value, owner_department=dept,
                      lineage=lineage, epoch=epoch)
        for name, system in systems.items():
            s = stats[name]
            if name != "no_memory":
                s["cross"] += 1
            if name == "naive":
                result = system.request(metric, dept, amu)
                system.write(amu)
            elif name == "lineage_aware":
                result = system.request(metric, dept, amu)
                if system.write(amu):
                    flagged += 1
            else:
                result = system.request(metric, dept, amu)
            s["served"] += int(result.served)
            s["leaked"] += int(result.leaked)
            s["reused"] += int(result.reused)
            s["blocked"] += int(result.blocked)
    return stats, flagged


def test_package_matches_root_modules_across_seeds():
    new_variants = _as_new_variants()
    mismatches = []

    for seed in range(N_SEEDS):
        random.seed(seed)
        events = generate_events()
        old_stats, old_flagged = run_old(events)

        random.seed(seed)
        events2 = generate_events()
        assert events == events2, f"seed {seed}: RNG usage diverged before systems were even involved"
        new_stats, new_flagged = run_new(events2, new_variants)

        if old_flagged != new_flagged:
            mismatches.append((seed, "flagged_conflicts", old_flagged, new_flagged))
        for name in old_stats:
            for key in old_stats[name]:
                if old_stats[name][key] != new_stats[name][key]:
                    mismatches.append((seed, f"{name}.{key}", old_stats[name][key], new_stats[name][key]))

    assert not mismatches, (
        "amu_governance package diverged from the root model.py/systems.py that "
        f"produced the paper's published numbers ({len(mismatches)} mismatches):\n" +
        "\n".join(f"  seed={s} field={f} old={o} new={n}" for s, f, o, n in mismatches[:20])
    )


if __name__ == "__main__":
    try:
        test_package_matches_root_modules_across_seeds()
    except AssertionError as e:
        print("FAILED:", e)
        sys.exit(1)
    print(f"PASSED: amu_governance package matches root model.py/systems.py across {N_SEEDS} seeds.")
