"""
Shared pytest fixtures/setup for the extension_paper test suite.

The root repo's ``model.py``, ``systems.py``, ``simulate.py``, and
``real_agent/`` are loose modules at the repository root, not an installed
package (this mirrors how ``test_package_conformance.py`` and
``adversarial_lineage_experiment.py`` already import them: by adding the
repo root to ``sys.path``). We do the same thing here, once, so every test
module can ``import model``, ``import systems``, etc. without repeating the
path hack.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXTENSION_SRC = Path(__file__).resolve().parents[1] / "src"

for _p in (_REPO_ROOT, _EXTENSION_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
