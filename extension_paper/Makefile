.PHONY: setup lint typecheck test experiments coverage figures all clean

PYTHON ?= python3

# ---------------------------------------------------------------------------
# setup: install the extension package (editable) plus its dev/runtime deps.
# ---------------------------------------------------------------------------
setup:
	$(PYTHON) -m pip install -e . --break-system-packages
	$(PYTHON) -m pip install -r requirements-extension.txt --break-system-packages

# ---------------------------------------------------------------------------
# lint / typecheck: fast, no network, run on every push (see
# .github/workflows/extension-ci.yml).
# ---------------------------------------------------------------------------
lint:
	black --check .
	ruff check .

typecheck:
	mypy

# ---------------------------------------------------------------------------
# test: the FAST tier only -- unit + integration-smoke, excludes anything
# marked `slow` (addopts in pyproject.toml already does `-m "not slow"`,
# this target is explicit for clarity and for CI).
# ---------------------------------------------------------------------------
test:
	$(PYTHON) -m pytest tests/ -v

coverage:
	$(PYTHON) -m pytest tests/ --cov=amu_ext --cov-report=term-missing --cov-report=html

# ---------------------------------------------------------------------------
# experiments: the SLOW tier -- full-statistical-power runs (10,000-resample
# bootstrap CIs, 30-seed materialization sweeps, the complete 53-pair
# detector matrix). Writes real results/<experiment>/<run_id>/ folders.
# Not part of the default `test` target or CI's fast gate, by design (see
# build prompt Section 4's "three test tiers").
# ---------------------------------------------------------------------------
experiments:
	$(PYTHON) experiments/run_all.py

figures:
	$(PYTHON) experiments/make_figures.py

# ---------------------------------------------------------------------------
# all: the full PR-readiness gate -- lint, typecheck, fast tests, then the
# real experiment runs and figure generation.
# ---------------------------------------------------------------------------
all: lint typecheck test experiments figures

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .hypothesis htmlcov .coverage
	find . -name "__pycache__" -type d -exec rm -rf {} +
