"""
amu_ext: extension-paper code for Lineage-Aware Memory Governance.

This package holds all *new* code written for the follow-on paper: the D4/D5
fuzzy-conflict detectors, the aggregation-operator schema extension,
generalized materialization-boundary closure, and a regression harness
around the SQL-extraction bugfix in ``real_agent/amu_bridge.py``.

Nothing in ``extension_paper/`` modifies the root ``model.py`` / ``systems.py``
that produced the published paper's numbers, except for the single,
explicitly-documented Algorithm 1 diagnostic-flag correction (see
``results/RESULTS.md``, "Post-publication corrections").
"""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("amu-ext")
except _metadata.PackageNotFoundError:  # pragma: no cover - editable/dev install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
