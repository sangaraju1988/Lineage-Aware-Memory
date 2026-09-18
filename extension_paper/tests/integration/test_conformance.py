"""
Group C1: re-homed conformance check, wired into the default test suite.

PR #1 added ``test_package_conformance.py`` at the repo root as a
standalone script (``python test_package_conformance.py`` / manual
``pytest`` invocation) -- it verified the ``amu_governance`` package
matches the root ``model.py``/``systems.py`` on a 30-seed workload, but
nothing ran it automatically. This test module imports and runs that exact
check as part of the extension_paper suite, so it runs on every CI build
going forward (see ``.github/workflows/extension-ci.yml``), not just once
by hand.

We import the root script's test function directly rather than
reimplementing it, so there is exactly one copy of the conformance logic to
keep in sync -- this module is a CI trigger for it, not a fork of it.
"""

from __future__ import annotations

import test_package_conformance as root_conformance


def test_package_conformance_runs_on_every_ci_build() -> None:
    """Re-run PR #1's package-conformance check against the final merged
    branch (root modules vs. amu_governance, 30 seeds). Raises AssertionError
    with a detailed mismatch report if the two implementations diverge --
    see test_package_conformance.py's own docstring for why a failure here
    is a real finding to report, not something to silently reconcile by
    editing the frozen root modules."""
    root_conformance.test_package_matches_root_modules_across_seeds()
