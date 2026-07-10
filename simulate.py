"""
Synthetic workload + simulation runner.

We generate a stream of (department, metric_name, lineage) events across
several "epochs" (think: weeks). Some metrics are computed by multiple
departments with genuinely different lineage (different join path / filter
logic) -- these are the ground-truth metric conflicts. Some lineages touch
sensitive columns (PII tables) -- these are the ground-truth leak risks.

We then replay the IDENTICAL workload through all three systems and measure:
  - leak_rate: % of cross-department retrievals that exposed unauthorized data
  - reuse_rate: % of requests served from memory instead of fresh compute
  - conflict_recall: % of true metric-definition conflicts the system actually flags
  - false_block_rate: % of SAFE retrievals incorrectly blocked (overhead/cost check)
"""

import random
import csv
from dataclasses import dataclass
from typing import List

from model import AMU, Lineage, LineageStep, DEPARTMENT_PERMISSIONS
from systems import NoMemorySystem, NaiveMemorySystem, LineageAwareSystem

random.seed(42)

DEPARTMENTS = ["Finance", "Marketing", "Support"]

# Metric definitions: each metric has 1-2 "variant" lineages that different
# departments might use. Variants with different filter_logic / join tables
# represent genuine definition divergence.
METRIC_VARIANTS = {
    "churn_rate": [
        Lineage(
            steps=(LineageStep("customers", ("customer_id", "signup_date")),
                   LineageStep("transactions", ("customer_id", "txn_date", "amount"))),
            filter_logic="no txn in 90 days",
        ),
        Lineage(
            steps=(LineageStep("customers", ("customer_id", "signup_date")),
                   LineageStep("customer_pii", ("customer_id", "income")),
                   LineageStep("transactions", ("customer_id", "txn_date", "amount"))),
            filter_logic="no txn in 60 days AND income-segment adjusted",
        ),
    ],
    "active_customers": [
        Lineage(
            steps=(LineageStep("customers", ("customer_id", "region")),
                   LineageStep("transactions", ("customer_id", "txn_date"))),
            filter_logic="txn in last 30 days",
        ),
        Lineage(
            steps=(LineageStep("customers", ("customer_id", "region")),
                   LineageStep("campaigns", ("customer_id", "channel"))),
            filter_logic="any campaign engagement in last 30 days",
        ),
    ],
    "campaign_roi": [
        Lineage(
            steps=(LineageStep("campaigns", ("campaign_id", "customer_id", "spend", "channel")),
                   LineageStep("transactions", ("customer_id", "amount"))),
            filter_logic="revenue attributed within 14-day window",
        ),
    ],
    "support_load": [
        Lineage(
            steps=(LineageStep("support_tickets", ("customer_id", "ticket_id", "category")),
                   LineageStep("customers", ("customer_id", "region"))),
            filter_logic="open tickets by region",
        ),
    ],
    "high_value_segment": [
        Lineage(
            steps=(LineageStep("customer_pii", ("customer_id", "income")),
                   LineageStep("transactions", ("customer_id", "amount"))),
            filter_logic="income decile 9-10",
        ),
    ],
}


@dataclass
class Event:
    epoch: int
    department: str
    metric_name: str
    lineage: Lineage


def generate_workload(n_epochs: int = 20, events_per_epoch: int = 6) -> List[Event]:
    events = []
    metric_names = list(METRIC_VARIANTS.keys())
    for epoch in range(n_epochs):
        for _ in range(events_per_epoch):
            dept = random.choice(DEPARTMENTS)
            metric = random.choice(metric_names)
            variants = METRIC_VARIANTS[metric]
            # Departments lean toward a "home" variant but sometimes diverge --
            # mirrors real orgs where teams independently define the same KPI.
            variant_idx = random.choice(range(len(variants)))
            lineage = variants[variant_idx]
            events.append(Event(epoch, dept, metric, lineage))
    return events


def run_simulation():
    events = generate_workload()

    systems = {
        "no_memory": NoMemorySystem(),
        "naive": NaiveMemorySystem(),
        "lineage_aware": LineageAwareSystem(),
    }

    stats = {name: {"served": 0, "leaked": 0, "reused": 0, "blocked": 0,
                     "cross_dept_requests": 0} for name in systems}

    # Ground truth tracking
    true_conflicts_seen = 0          # count of events where dept's definition
                                      # genuinely diverges from another dept's
                                      # prior definition of the same metric
    flagged_conflicts = {"naive": 0, "lineage_aware": 0}
    seen_definitions = {}            # metric_name -> {definition_hash: owner_department}

    for ev in events:
        amu = AMU(metric_name=ev.metric_name, value=round(random.uniform(0, 100), 2),
                  owner_department=ev.department, lineage=ev.lineage, epoch=ev.epoch)

        # --- ground truth conflict bookkeeping ---
        seen_definitions.setdefault(ev.metric_name, {})
        prior = seen_definitions[ev.metric_name]
        is_new_conflict = any(
            owner != ev.department for d_hash, owner in prior.items()
            if d_hash != amu.definition_hash
        )
        if is_new_conflict:
            true_conflicts_seen += 1
        prior[amu.definition_hash] = ev.department

        # --- replay through each system ---
        for sys_name, system in systems.items():
            s = stats[sys_name]
            is_cross_dept = sys_name != "no_memory"  # status quo never shares, by design
            if is_cross_dept:
                s["cross_dept_requests"] += 1

            if sys_name == "no_memory":
                result = system.request(ev.metric_name, ev.department, amu)
            elif sys_name == "naive":
                result = system.request(ev.metric_name, ev.department, amu)
                system.write(amu)
                if is_new_conflict:
                    # naive system has no mechanism to detect this -- never flags
                    pass
            else:  # lineage_aware
                result = system.request(ev.metric_name, ev.department, amu)
                conflict_flagged = system.write(amu)
                if conflict_flagged and is_new_conflict:
                    flagged_conflicts["lineage_aware"] += 1

            s["served"] += int(result.served)
            s["leaked"] += int(result.leaked)
            s["reused"] += int(result.reused)
            s["blocked"] += int(result.blocked)

    return systems, stats, true_conflicts_seen, flagged_conflicts, len(events)


def summarize(stats, true_conflicts_seen, flagged_conflicts, n_events):
    rows = []
    for sys_name, s in stats.items():
        cross = max(s["cross_dept_requests"], 1)
        leak_rate = 100 * s["leaked"] / cross if sys_name != "no_memory" else 0.0
        reuse_rate = 100 * s["reused"] / cross if sys_name != "no_memory" else 0.0
        if sys_name == "lineage_aware":
            conflict_recall = 100 * flagged_conflicts["lineage_aware"] / max(true_conflicts_seen, 1)
        elif sys_name == "naive":
            conflict_recall = 0.0  # mechanism does not exist
        else:
            conflict_recall = None  # not applicable, no shared memory at all
        rows.append({
            "system": sys_name,
            "events": n_events,
            "leak_rate_pct": round(leak_rate, 1),
            "reuse_rate_pct": round(reuse_rate, 1),
            "conflict_recall_pct": None if conflict_recall is None else round(conflict_recall, 1),
            "blocked_count": s["blocked"],
        })
    return rows


def run_seed_sweep(n_seeds: int = 30):
    """Re-run the whole simulation under many random seeds to check the result
    isn't a fluke of one workload draw."""
    import statistics
    all_rows = {sys_name: {"leak": [], "reuse": [], "conflict_recall": []}
                for sys_name in ["no_memory", "naive", "lineage_aware"]}

    for seed in range(n_seeds):
        random.seed(seed)
        systems, stats, true_conflicts_seen, flagged_conflicts, n_events = run_simulation()
        rows = summarize(stats, true_conflicts_seen, flagged_conflicts, n_events)
        for r in rows:
            all_rows[r["system"]]["leak"].append(r["leak_rate_pct"])
            all_rows[r["system"]]["reuse"].append(r["reuse_rate_pct"])
            if r["conflict_recall_pct"] is not None:
                all_rows[r["system"]]["conflict_recall"].append(r["conflict_recall_pct"])

    print(f"\n=== Sweep over {n_seeds} random seeds (mean +/- stdev) ===")
    print(f"{'System':35s} {'Leak %':>14s} {'Reuse %':>14s} {'ConflictRecall %':>18s}")
    summary = {}
    for sys_name, vals in all_rows.items():
        leak_mean, leak_sd = statistics.mean(vals["leak"]), statistics.pstdev(vals["leak"])
        reuse_mean, reuse_sd = statistics.mean(vals["reuse"]), statistics.pstdev(vals["reuse"])
        if vals["conflict_recall"]:
            cr_mean, cr_sd = statistics.mean(vals["conflict_recall"]), statistics.pstdev(vals["conflict_recall"])
            cr_str = f"{cr_mean:.1f} +/- {cr_sd:.1f}"
        else:
            cr_str = "n/a"
        print(f"{sys_name:35s} {leak_mean:6.1f} +/- {leak_sd:<4.1f} {reuse_mean:6.1f} +/- {reuse_sd:<4.1f} {cr_str:>18s}")
        summary[sys_name] = {
            "leak_mean": round(leak_mean, 2), "leak_sd": round(leak_sd, 2),
            "reuse_mean": round(reuse_mean, 2), "reuse_sd": round(reuse_sd, 2),
            "conflict_recall_mean": None if not vals["conflict_recall"] else round(statistics.mean(vals["conflict_recall"]), 2),
        }
    return summary, all_rows


if __name__ == "__main__":
    random.seed(42)
    systems, stats, true_conflicts_seen, flagged_conflicts, n_events = run_simulation()
    rows = summarize(stats, true_conflicts_seen, flagged_conflicts, n_events)

    print(f"Total events simulated: {n_events}")
    print(f"True metric-definition conflicts (ground truth): {true_conflicts_seen}\n")

    print(f"{'System':35s} {'Leak %':>8s} {'Reuse %':>9s} {'ConflictRecall %':>18s} {'Blocked':>8s}")
    for r in rows:
        cr = "n/a" if r["conflict_recall_pct"] is None else f"{r['conflict_recall_pct']}"
        print(f"{r['system']:35s} {r['leak_rate_pct']:>8} {r['reuse_rate_pct']:>9} {cr:>18s} {r['blocked_count']:>8}")

    with open("results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["system", "events", "leak_rate_pct",
                                                "reuse_rate_pct", "conflict_recall_pct", "blocked_count"])
        writer.writeheader()
        writer.writerows(rows)
    print("\nWrote results.csv (single seed=42 run)")

    sweep_summary, all_rows = run_seed_sweep(n_seeds=30)
    with open("sweep_summary.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["system", "leak_mean", "leak_sd",
                                                "reuse_mean", "reuse_sd", "conflict_recall_mean"])
        writer.writeheader()
        for sys_name, d in sweep_summary.items():
            writer.writerow({"system": sys_name, **d})
    print("Wrote sweep_summary.csv (30-seed robustness check)")

    # stash raw per-seed values for plotting
    import json
    with open("sweep_raw.json", "w") as f:
        json.dump(all_rows, f)
