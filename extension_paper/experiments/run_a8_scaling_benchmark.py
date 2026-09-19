#!/usr/bin/env python3
"""
Group A8 (peer-review revision): runtime scaling of the two mechanisms this
paper extends, along the two dimensions each one actually varies with --
requested during peer review as "how do the runtime/storage numbers scale
with lineage depth and number of registered materializations."

Part 1 -- materialization-closure runtime vs. chain depth. Builds a genuine
linear materialization chain of depth D (tier_0 -> materialized column_1 ->
tier_1 -> materialized column_2 -> ... -> tier_D), registers every edge,
and times ``close_lineage`` on the final downstream lineage at
D in {1, 2, 4, 8, 16, 32, 64}. ``close_lineage``'s recursion guard
(``_max_depth``, default 8 in materialization.py) is passed explicitly here
as ``D + 2`` so depths above the *default* are not silently truncated --
this benchmark is also what surfaces, as a real and previously undocumented
implementation detail, that the default guard would otherwise cap closure
at depth 8.

Part 2 -- D4/D5 runtime vs. lineage size. D4/D5 operate on a flat
(tables, columns, filter_logic, aggregation_fn) tuple, not a chain, so
"depth" does not apply to them the way it does to closure; the dimension
that actually drives their runtime is the number of tables/columns touched
and the length of the filter-logic string (operator_topology parses it).
Benchmarks D4 and D5 on synthetic pairs at n_tables/n_columns in
{1, 2, 4, 8, 16, 32}, filter-logic length scaled proportionally.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_repo_on_path, make_run_dir, setup_logging, write_json, write_manifest  # noqa: E402

ensure_repo_on_path()

from amu_governance import Lineage, LineageStep  # noqa: E402

from amu_ext.detectors import LineageSpec, Pair, d4_structural_topology, d5_with_aggregation  # noqa: E402
from amu_ext.materialization import MaterializationRegistry, close_lineage  # noqa: E402
from amu_ext.stats import benchmark_callable  # noqa: E402

DEPTHS = [1, 2, 4, 8, 16, 32, 64]
SIZES = [1, 2, 4, 8, 16, 32]


def build_chain(depth: int) -> tuple[Lineage, MaterializationRegistry]:
    """Build a depth-D linear materialization chain and its registry.

    tier_0 touches base table/column (customer_pii, income). Each
    subsequent tier k (1..depth) is a materialized column
    (derived_k, feature_k) whose registered upstream is tier k-1's lineage.
    The lineage returned is the final (deepest) tier's *downstream*
    lineage, which references only the immediately-preceding materialized
    column -- exactly the shape the materialization-boundary threat
    describes (a downstream metric's own recorded lineage touches only the
    materialized column, one hop removed from the sensitive source).
    """
    registry = MaterializationRegistry()
    upstream = Lineage(
        steps=(LineageStep("customer_pii", ("customer_id", "income")),), filter_logic="tier_0 base"
    )
    for k in range(1, depth + 1):
        table, col = f"derived_{k}", f"feature_{k}"
        registry.register(table, col, upstream)
        upstream = Lineage(steps=(LineageStep(table, (col,)),), filter_logic=f"tier_{k}")
    return upstream, registry


def build_pair(n: int) -> Pair:
    """Build a synthetic Pair with n tables/columns and a proportionally
    longer filter-logic string, differing only in aggregation_fn (worst
    case for D4: it must fully evaluate the structural gate as "no
    difference" before reaching D5's aggregation check)."""
    tables = tuple(f"t{i}" for i in range(n))
    columns = tuple(f"c{i}" for i in range(n))
    filt = " AND ".join(f"c{i} > {i}" for i in range(n)) or "1=1"
    a = LineageSpec(tables=tables, columns=columns, filter_logic=filt, aggregation_fn="SUM")
    b = LineageSpec(tables=tables, columns=columns, filter_logic=filt, aggregation_fn="AVG")
    return Pair(
        name=f"scaling_n{n}", category="AO", a=a, b=b, is_conflict=True, rationale="scaling benchmark"
    )


def main() -> int:
    run_dir = make_run_dir("a8_scaling_benchmark")
    logger = setup_logging(run_dir, "run_a8_scaling_benchmark")

    closure_results = []
    for depth in DEPTHS:
        lineage, registry = build_chain(depth)
        result = benchmark_callable(
            lambda lineage=lineage, registry=registry, depth=depth: close_lineage(
                lineage, registry, _max_depth=depth + 2
            ),
            n_iter=2000,
            n_warmup=200,
        )
        closed = close_lineage(lineage, registry, _max_depth=depth + 2)
        closure_results.append(
            {"depth": depth, "n_steps_after_closure": len(closed.steps), **result.as_dict()}
        )
        logger.info(
            "closure depth=%3d  mean=%.3f us  n_steps_after=%d", depth, result.mean_us, len(closed.steps)
        )

    default_guard_lineage, default_guard_registry = build_chain(16)
    closed_default = close_lineage(default_guard_lineage, default_guard_registry)  # _max_depth defaults to 8
    default_guard_capped = len(closed_default.steps) < 16

    detector_results: dict[str, list] = {"D4_structural_topology": [], "D5_with_aggregation": []}
    for n in SIZES:
        pair = build_pair(n)
        for name, fn in (
            ("D4_structural_topology", d4_structural_topology),
            ("D5_with_aggregation", d5_with_aggregation),
        ):
            result = benchmark_callable(lambda p=pair, f=fn: f(p), n_iter=2000, n_warmup=200)
            detector_results[name].append({"n_tables_columns": n, **result.as_dict()})
            logger.info("%s n=%3d  mean=%.3f us", name, n, result.mean_us)

    write_json(
        run_dir / "summary_stats.json",
        {
            "closure_vs_depth": closure_results,
            "default_max_depth_guard": {
                "value": 8,
                "tested_chain_depth": 16,
                "chain_truncated_by_default_guard": default_guard_capped,
                "note": (
                    "close_lineage()'s _max_depth parameter defaults to 8 in "
                    "materialization.py. A 16-tier chain closed WITHOUT explicitly "
                    "overriding _max_depth is silently truncated at 8 registered hops "
                    "-- steps beyond the guard are not unioned in. This benchmark is "
                    "what surfaced this as a real, previously undocumented boundary "
                    "of the closure defense, distinct from the registered/unregistered "
                    "edge boundary already reported."
                ),
            },
            "detector_runtime_vs_input_size": detector_results,
        },
    )
    write_manifest(run_dir, seeds=[], command="python experiments/run_a8_scaling_benchmark.py")

    print(f"Wrote results to {run_dir}")
    print(f"Default _max_depth=8 truncates a 16-tier chain: {default_guard_capped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
