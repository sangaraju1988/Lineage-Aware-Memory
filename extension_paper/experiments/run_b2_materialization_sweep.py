#!/usr/bin/env python3
"""
Group B2: broadened materialization-boundary sweep.

PR #1's ``adversarial_lineage_experiment.py`` used exactly two chains and
three departments. This script sweeps 5 distinct (chain count, department
topology) configurations x 30 seeds each, using ``amu_ext.materialization``'s
generalized chain/topology generator, and reports leak-rate / block-rate
mean +/- SD per configuration for both the stock gate and the transitive-
closure fix.

Configuration 1 (2 chains, 3 departments, seeds 0-29) is an exact
reproduction of PR #1's original experiment -- same seed range, same
underlying chain semantics (see ``amu_ext.materialization.build_chains``'s
docstring) -- so that result stays directly comparable, per the build
prompt's explicit instruction not to silently change it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_ext.materialization import DEPARTMENT_TOPOLOGIES, build_chains, sweep_config  # noqa: E402

#: (config_name, n_chains, topology_name, seed_offset)
CONFIGS = [
    ("2chains_3dept_original", 2, "3dept", 0),  # exact PR #1 reproduction
    ("3chains_3dept", 3, "3dept", 0),
    ("5chains_3dept", 5, "3dept", 0),
    ("2chains_5dept", 2, "5dept", 0),
    ("5chains_5dept", 5, "5dept", 0),
]

N_SEEDS = 30
N_EPOCHS = 20


def main() -> int:
    run_dir = make_run_dir("b2_materialization_sweep")
    logger = setup_logging(run_dir, "run_b2_materialization_sweep")
    logger.info("Group B2: %d configurations x %d seeds", len(CONFIGS), N_SEEDS)

    all_results: Dict[str, object] = {}
    summary_rows: List[Dict[str, object]] = []

    for config_name, n_chains, topology_name, seed_offset in CONFIGS:
        chains = build_chains(n_chains)
        policy = DEPARTMENT_TOPOLOGIES[topology_name]
        departments = list(policy.department_permissions)

        logger.info(
            "Running config=%s n_chains=%d topology=%s (%d depts) seeds=%d..%d",
            config_name,
            n_chains,
            topology_name,
            len(departments),
            seed_offset,
            seed_offset + N_SEEDS - 1,
        )
        result = sweep_config(
            chains, policy, departments, n_seeds=N_SEEDS, n_epochs=N_EPOCHS, seed_offset=seed_offset
        )
        result["config_name"] = config_name
        result["topology_name"] = topology_name
        result["chain_names"] = list(chains.keys())
        result["n_sensitive_chains"] = sum(1 for c in chains.values() if c.sensitive)
        all_results[config_name] = result

        logger.debug(
            "config=%s stock=%s closure=%s", config_name, result["stock_gate"], result["closure_gate"]
        )
        logger.info(
            "  stock:   leak=%.2f%% +/- %.2f%%  block=%.2f%%",
            result["stock_gate"]["leak_rate_mean"],
            result["stock_gate"]["leak_rate_sd"],
            result["stock_gate"]["block_rate_mean"],
        )
        logger.info(
            "  closure: leak=%.2f%% +/- %.2f%%  block=%.2f%%",
            result["closure_gate"]["leak_rate_mean"],
            result["closure_gate"]["leak_rate_sd"],
            result["closure_gate"]["block_rate_mean"],
        )

        summary_rows.append(
            {
                "config_name": config_name,
                "n_chains": n_chains,
                "n_departments": len(departments),
                "topology": topology_name,
                "stock_leak_rate_mean": result["stock_gate"]["leak_rate_mean"],
                "stock_leak_rate_sd": result["stock_gate"]["leak_rate_sd"],
                "closure_leak_rate_mean": result["closure_gate"]["leak_rate_mean"],
                "closure_leak_rate_sd": result["closure_gate"]["leak_rate_sd"],
                "stock_block_rate_mean": result["stock_gate"]["block_rate_mean"],
                "closure_block_rate_mean": result["closure_gate"]["block_rate_mean"],
            }
        )

    original_config = all_results["2chains_3dept_original"]
    reproduction_check = {
        "matches_pr1_leak_rate": abs(original_config["stock_gate"]["leak_rate_mean"] - 32.7) < 0.5,
        "matches_pr1_leak_sd": abs(original_config["stock_gate"]["leak_rate_sd"] - 9.3) < 0.5,
        "measured_leak_mean": original_config["stock_gate"]["leak_rate_mean"],
        "measured_leak_sd": original_config["stock_gate"]["leak_rate_sd"],
        "pr1_reported_leak_mean": 32.7,
        "pr1_reported_leak_sd": 9.3,
    }
    logger.info("PR #1 reproduction check: %s", reproduction_check)

    write_json(run_dir / "raw_results.json", {"configs": all_results})
    write_json(
        run_dir / "summary_stats.json",
        {
            "n_configs": len(CONFIGS),
            "n_seeds_per_config": N_SEEDS,
            "rows": summary_rows,
            "pr1_reproduction_check": reproduction_check,
            "note": (
                "closure_leak_rate is 0.0% +/- 0.0% in every configuration by "
                "construction (closure sees every registered provenance edge, "
                "and every chain here IS registered -- see Group B3's regression "
                "test for the unregistered case, where this stops being true)."
            ),
        },
    )
    write_manifest(
        run_dir,
        seeds=range(N_SEEDS),
        command="python experiments/run_b2_materialization_sweep.py",
        extra={"configs": [c[0] for c in CONFIGS]},
    )

    print(f"Wrote results to {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
