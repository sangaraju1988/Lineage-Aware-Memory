"""
Integration smoke tests: every experiment's core computational path runs
end-to-end on a deliberately tiny config (few seeds, few pairs), in well
under a minute total, as part of the default (fast) pytest tier.

These deliberately do NOT invoke each ``experiments/run_*.py`` script's
``main()`` directly: ``main()`` writes a full, real
``results/<experiment>/<run_id>/`` folder via ``_common.make_run_dir``, and
running that on every ``pytest`` invocation would litter the results/
directory with throwaway runs on every CI build. Instead, each test below
exercises the same underlying ``amu_ext`` functions each script's ``main()``
calls, with tiny hand-built inputs, to confirm the wiring works -- the real,
full-statistical-power runs (which populate the actual results/ folders
these tests intentionally don't touch) are ``make experiments``'s job, a
separate, explicit, non-default target (see the Makefile).

The one exception is ``run_c1_conformance.main()``, which we DO invoke
directly, since Group C1 has a proper ``--n-seeds`` CLI flag for exactly
this purpose -- reusing it here is simpler and more faithful than
reimplementing its internals a second time.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "experiments"
sys.path.insert(0, str(_EXPERIMENTS_DIR))

from amu_governance import GovernancePolicy  # noqa: E402

from amu_ext.detectors import (  # noqa: E402
    LineageSpec,
    Pair,
    d1_exact,
    d4_structural_topology,
    d5_with_aggregation,
)  # noqa: E402
from amu_ext.materialization import build_chains, sweep_config  # noqa: E402
from amu_ext.sql_extraction import QueryCase, evaluate_case  # noqa: E402
from amu_ext.stats import benchmark_callable, bootstrap_ci, mcnemar_test, precision_recall_f1  # noqa: E402


def _tiny_pair(name: str, is_conflict: bool, agg_a=None, agg_b=None) -> Pair:
    return Pair(
        name=name,
        category="AO" if agg_a != agg_b else "TV",
        a=LineageSpec(tables=("t",), columns=("c",), filter_logic="f", aggregation_fn=agg_a),
        b=LineageSpec(tables=("t",), columns=("c",), filter_logic="f", aggregation_fn=agg_b),
        is_conflict=is_conflict,
        rationale="smoke",
    )


class TestGroupASmoke:
    """Mirrors run_a1/a2/a4/a5's core path on a 2-pair toy dataset."""

    def test_detector_matrix_and_bootstrap_ci(self) -> None:
        pairs = [_tiny_pair("p1", False, "SUM", "SUM"), _tiny_pair("p2", True, "SUM", "AVG")]
        gt = [p.is_conflict for p in pairs]
        for fn in (d1_exact, d4_structural_topology, d5_with_aggregation):
            preds = [fn(p) for p in pairs]
            prf = precision_recall_f1(preds, gt)
            assert 0.0 <= prf.f1 <= 1.0

        items = list(zip([d5_with_aggregation(p) for p in pairs], gt))
        ci = bootstrap_ci(
            items,
            lambda r: precision_recall_f1([x[0] for x in r], [x[1] for x in r]).f1,
            n_resamples=50,
            seed=1,
        )
        assert ci.ci_lo <= ci.ci_hi

    def test_mcnemar_smoke(self) -> None:
        result = mcnemar_test([True, False, True], [False, False, True])
        assert 0.0 <= result.p_value <= 1.0

    def test_runtime_benchmark_smoke(self) -> None:
        pair = _tiny_pair("p1", True, "SUM", "AVG")
        result = benchmark_callable(lambda: d5_with_aggregation(pair), n_iter=20, n_warmup=5)
        assert result.mean_us > 0
        assert result.n_iter == 20


class TestGroupBSmoke:
    """Mirrors run_b2's core path with 2 chains, 2 seeds."""

    def test_materialization_sweep_tiny(self) -> None:
        chains = build_chains(2)
        policy = GovernancePolicy(
            sensitive_columns={"income"},
            department_permissions={
                "Finance": {"customer_id", "income", "amount"},
                "Marketing": {"customer_id", "amount"},
            },
        )
        result = sweep_config(chains, policy, ["Finance", "Marketing"], n_seeds=2, n_epochs=4, seed_offset=0)
        assert result["n_seeds"] == 2
        assert "leak_rate_mean" in result["stock_gate"]
        assert result["closure_gate"]["leak_rate_mean"] <= result["stock_gate"]["leak_rate_mean"]


class TestGroupCSmoke:
    def test_conformance_tiny_via_cli_entrypoint(self, tmp_path, monkeypatch) -> None:
        """The one script we call end-to-end, via its real --n-seeds flag.

        ``main()`` writes a real results/<run_id>/ folder via
        ``_common.make_run_dir`` -- redirect ``_common.RESULTS_ROOT`` to a
        pytest tmp_path first, so this (which runs on every ``pytest``
        invocation, unlike the other Group C/A/B smoke tests here) doesn't
        litter the real results/c1_conformance/ with a 2-seed run on every
        CI build, the same pollution this module's docstring says the other
        tests were written to avoid.
        """
        import _common
        import run_c1_conformance

        monkeypatch.setattr(_common, "RESULTS_ROOT", tmp_path)
        rc = run_c1_conformance.main(["--n-seeds", "2"])
        assert rc == 0
        assert (tmp_path / "c1_conformance").exists()

    def test_storage_overhead_tiny(self) -> None:
        import storage_overhead_measurement as som

        entries = som.build_entries()[:2]
        result = som.measure(entries)
        assert result["n"] == 2
        assert result["json"]["ratio_mean"] > 1.0

    def test_sql_bugfix_demo_tiny(self) -> None:
        case = QueryCase(
            name="smoke",
            sql="SELECT HomePhone FROM Employees, Orders WHERE Employees.EmployeeID = Orders.EmployeeID",
            true_sensitive_columns=frozenset({"homephone"}),
            style="comma_join_unqualified",
            description="smoke",
        )
        pre = evaluate_case(
            case, sensitive_columns={"homephone"}, permitted_columns=set(), keep_unqualified=False
        )
        post = evaluate_case(
            case, sensitive_columns={"homephone"}, permitted_columns=set(), keep_unqualified=True
        )
        assert pre.leaked is True
        assert post.leaked is False
