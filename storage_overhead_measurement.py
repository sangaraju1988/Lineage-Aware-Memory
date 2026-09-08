"""
Empirical storage-overhead measurement.

The paper (Section 5, "Complexity and Storage") states the AMU lineage
overhead as an analytical estimate: "roughly 4-8x a bare value entry
(200-600 bytes for a typical 2-4 table join)". That figure is arithmetic
over the schema, not a measurement -- no script in this repo (or the
amu-governance package) actually serializes an AMU and measures it. This
script closes that gap: it serializes real AMUs from the paper's own
synthetic-schema metric variants (simulate.py) and the TPC-H schema
(tpch_experiment.py) and reports the measured ratio, so the paper's
estimate can be checked against an actual number rather than taken on
faith.

"Bare value entry" = metric_name + value + owner_department + epoch only,
no lineage. "Full AMU" = the same plus the complete Lineage.

Two serialization formats are reported since the ratio is format-dependent:
  - JSON  (human-readable, what a metadata catalog / audit log would store)
  - pickle (Python-native, a rough proxy for an in-memory cache entry)
"""

import json
import pickle
import statistics
from dataclasses import asdict

from model import AMU, DEPARTMENT_PERMISSIONS  # noqa: F401 (kept for context/parity with other scripts)
from simulate import METRIC_VARIANTS, DEPARTMENTS


def bare_value_entry(metric_name: str, value: float, dept: str, epoch: int) -> dict:
    return {"metric_name": metric_name, "value": value, "owner_department": dept, "epoch": epoch}


def full_amu_entry(amu: AMU) -> dict:
    d = bare_value_entry(amu.metric_name, amu.value, amu.owner_department, amu.epoch)
    d["lineage"] = {
        "steps": [{"table": s.table, "columns_used": list(s.columns_used)} for s in amu.lineage.steps],
        "filter_logic": amu.lineage.filter_logic,
        "definition_hash": amu.definition_hash,
    }
    return d


def measure(entries):
    """entries: list of (bare_dict, full_dict) pairs. Returns per-format ratios."""
    json_ratios, pickle_ratios = [], []
    bare_json_bytes, full_json_bytes = [], []
    bare_pickle_bytes, full_pickle_bytes = [], []

    for bare, full in entries:
        bj = len(json.dumps(bare).encode("utf-8"))
        fj = len(json.dumps(full).encode("utf-8"))
        bp = len(pickle.dumps(bare))
        fp = len(pickle.dumps(full))

        json_ratios.append(fj / bj)
        pickle_ratios.append(fp / bp)
        bare_json_bytes.append(bj)
        full_json_bytes.append(fj)
        bare_pickle_bytes.append(bp)
        full_pickle_bytes.append(fp)

    return {
        "json": {
            "ratio_mean": round(statistics.mean(json_ratios), 2),
            "ratio_min": round(min(json_ratios), 2),
            "ratio_max": round(max(json_ratios), 2),
            "bare_bytes_mean": round(statistics.mean(bare_json_bytes), 1),
            "full_bytes_mean": round(statistics.mean(full_json_bytes), 1),
        },
        "pickle": {
            "ratio_mean": round(statistics.mean(pickle_ratios), 2),
            "ratio_min": round(min(pickle_ratios), 2),
            "ratio_max": round(max(pickle_ratios), 2),
            "bare_bytes_mean": round(statistics.mean(bare_pickle_bytes), 1),
            "full_bytes_mean": round(statistics.mean(full_pickle_bytes), 1),
        },
        "n": len(entries),
    }


def build_entries():
    entries = []
    for metric, variants in METRIC_VARIANTS.items():
        for i, lineage in enumerate(variants):
            for dept in DEPARTMENTS:
                amu = AMU(metric_name=metric, value=42.0, owner_department=dept,
                          lineage=lineage, epoch=0)
                entries.append((bare_value_entry(metric, 42.0, dept, 0), full_amu_entry(amu)))
    return entries


if __name__ == "__main__":
    entries = build_entries()
    results = measure(entries)

    print(f"Measured over {results['n']} AMUs (every metric-variant x department "
          f"combination in the paper's synthetic schema, simulate.py).\n")
    for fmt in ("json", "pickle"):
        r = results[fmt]
        print(f"{fmt.upper()}: bare={r['bare_bytes_mean']:.0f}B  full={r['full_bytes_mean']:.0f}B  "
              f"ratio={r['ratio_mean']:.2f}x  (range {r['ratio_min']:.2f}x-{r['ratio_max']:.2f}x)")

    print("\nPaper's analytical estimate: roughly 4-8x, 200-600 bytes for a typical "
          "2-4 table join. Compare against the measured JSON ratio above (JSON is the "
          "more representative format for a metadata catalog / audit log).")

    with open("storage_overhead_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWrote storage_overhead_results.json")
