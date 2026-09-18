#!/usr/bin/env python3
"""
Orchestrates every experiment in Section 3 (Groups A, B, C) in the build
prompt's suggested execution order, and writes a top-level manifest listing
every run this invocation produced. This is the ``make experiments`` target
-- the full, slow, statistical-power run, not part of default ``pytest``.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import RESULTS_ROOT, get_git_commit, write_json  # noqa: E402

# Suggested execution order (build_prompt.md Section 8): C1-C3 (build on
# merged PR #1 code) before B1-B3 (formalization + sweep + boundary test)
# before A1-A5 (largest, most self-contained chunk, run last).
EXPERIMENT_MODULES = [
    "run_c1_conformance",
    "run_c2_storage_overhead",
    "run_c3_sql_bugfix_demo",
    "run_b2_materialization_sweep",
    "run_a1_d4_eval",
    "run_a2_d5_eval",
    "run_a4_full_matrix",
    "run_a5_runtime_benchmark",
]


def main() -> int:
    print(f"amu_ext run_all: {len(EXPERIMENT_MODULES)} experiments, git commit {get_git_commit()}")
    t0 = time.perf_counter()
    outcomes = []

    for mod_name in EXPERIMENT_MODULES:
        print(f"\n{'=' * 70}\n{mod_name}\n{'=' * 70}")
        t_start = time.perf_counter()
        module = importlib.import_module(mod_name)
        rc = module.main()
        elapsed = time.perf_counter() - t_start
        outcomes.append({"module": mod_name, "return_code": rc, "elapsed_seconds": round(elapsed, 2)})
        if rc != 0:
            print(f"WARNING: {mod_name} returned non-zero exit code {rc}")

    total_elapsed = time.perf_counter() - t0
    manifest_path = RESULTS_ROOT / "run_all_manifest.json"
    write_json(
        manifest_path,
        {
            "git_commit": get_git_commit(),
            "total_elapsed_seconds": round(total_elapsed, 2),
            "experiments": outcomes,
        },
    )
    print(f"\nAll experiments complete in {total_elapsed:.1f}s. Manifest: {manifest_path}")

    failed = [o for o in outcomes if o["return_code"] != 0]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
