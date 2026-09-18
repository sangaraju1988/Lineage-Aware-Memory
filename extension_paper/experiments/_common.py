"""
Shared run-orchestration helpers for the experiments/run_*.py scripts.

Not part of ``amu_ext`` (the library code under test) on purpose: this is
runner glue -- git/timestamp/package-version bookkeeping and results-folder
layout -- not a statistical or governance mechanism, so it doesn't belong
under ``src/amu_ext/`` or count toward its coverage target. Every
``run_*.py`` script imports this module to get identical, comparable
``run_manifest.json`` provenance (Section 6 of the build prompt: git commit
hash, UTC timestamp, seeds, package versions, command line).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = EXTENSION_ROOT / "results"

_TRACKED_PACKAGES = ("numpy", "scipy", "matplotlib", "sqlglot", "amu-governance", "hypothesis")


def get_git_commit(short: bool = True) -> str:
    """Return the current git commit hash, or "unknown" outside a git repo."""
    try:
        args = ["git", "rev-parse", "--short", "HEAD"] if short else ["git", "rev-parse", "HEAD"]
        out = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:  # pragma: no cover - defensive: only hit outside a git checkout
        return "unknown"


def get_package_versions() -> Dict[str, str]:
    """Return {package_name: version} for the packages experiment results
    depend on, so a `run_manifest.json` fully pins its own reproducibility."""
    versions: Dict[str, str] = {"python": sys.version.split()[0]}
    for pkg in _TRACKED_PACKAGES:
        try:
            versions[pkg] = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:  # pragma: no cover
            versions[pkg] = "not installed"
    return versions


def new_run_id() -> str:
    """UTC timestamp + short git commit hash, per Section 2's folder layout."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{get_git_commit()}"


def make_run_dir(experiment_name: str, run_id: Optional[str] = None) -> Path:
    """Create (and return) results/<experiment_name>/<run_id>/figures/."""
    run_id = run_id or new_run_id()
    run_dir = RESULTS_ROOT / experiment_name / run_id
    (run_dir / "figures").mkdir(parents=True, exist_ok=True)
    return run_dir


def write_manifest(
    run_dir: Path,
    *,
    seeds: Iterable[int],
    command: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write run_manifest.json: git commit, UTC timestamp, seeds, package
    versions, and the exact command line invoked, per Section 6."""
    manifest = {
        "git_commit": get_git_commit(),
        "git_commit_full": get_git_commit(short=False),
        "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        "seeds": sorted(set(seeds)),
        "n_seeds": len(set(seeds)),
        "package_versions": get_package_versions(),
        "command": command,
    }
    if extra:
        manifest.update(extra)
    path = run_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def setup_logging(run_dir: Path, name: str) -> logging.Logger:
    """Configure a logger that writes INFO to stdout and DEBUG (per-seed
    detail) to run_dir/<name>.log, per the engineering-bar logging
    requirement (Section 4)."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.INFO)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S"))
    logger.addHandler(stream)

    file_handler = logging.FileHandler(run_dir / f"{name}.log", mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def ensure_repo_on_path() -> None:
    """Loose modules at the repo root (model.py, systems.py, simulate.py,
    real_agent/) aren't an installed package -- add the repo root to
    sys.path, matching the convention already used by
    test_package_conformance.py and adversarial_lineage_experiment.py."""
    for p in (str(REPO_ROOT), str(EXTENSION_ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
