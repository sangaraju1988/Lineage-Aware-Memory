"""
Fuzzy conflict detectors D1-D5, and the labeled-pair dataset schema they
operate on (Group A).

D1-D3 are faithful ports of the detectors already defined and evaluated in
the root repo's ``fuzzy_experiment.py`` (Exact Hash, Jaccard Filter,
Column-Graph) -- reimplemented here against the shared :class:`Pair` schema
so D4 and D5 can be evaluated by the exact same harness, on the exact same
43 original pairs plus the 10 new Aggregation-Operator (AO) pairs (Group
A3), without special-casing.

D4 (new, Group A1) is the detector the original paper proposed but never
evaluated: a *structural gate* (do the tables or columns differ at all --
identical to D3's logic) composed with a *filter-logic operator-topology
diff* for pairs that pass the structural gate unchanged. "Operator
topology" means the ordered sequence of logical/comparison operators
(``AND``, ``OR``, ``NOT``, ``IN``, ``BETWEEN``, ``>=``, ``<=``, ``!=``,
``=``, ``>``, ``<``) in the filter-logic string, with literal thresholds
(numbers, dates, numeric lists) normalized away. This is what lets D4 catch
the LO (Logic-Operator change) category that D3 is blind to -- AND-to-OR or
an added NOT changes the operator sequence even though the tables, columns,
and every literal value are unchanged -- while still correctly ignoring TV
(Threshold Variant) pairs, where only a literal threshold changed and the
operator sequence is identical.

D5 (new, Group A2) is D4 plus an aggregation-equality check: D4 flags a
conflict whenever it already would, or whenever the two lineages'
``aggregation_fn`` differ despite identical tables/columns/filter-topology.
This closes the aggregation-operator blind spot the AO dataset (Group A3)
is built to exercise -- D4 alone cannot see it, by construction, since
aggregation_fn is not part of D4's inputs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from amu_ext.aggregation import normalize_aggregation_fn

__all__ = [
    "LineageSpec",
    "Pair",
    "load_pairs",
    "save_pairs",
    "operator_topology",
    "d1_exact",
    "d2_jaccard",
    "d3_column_graph",
    "d4_structural_topology",
    "d5_with_aggregation",
    "DETECTORS",
]


@dataclass(frozen=True)
class LineageSpec:
    """One side of a conflict-detection pair: a minimal, detector-facing
    view of a lineage (no dependency on model.py's dataclasses, so this
    module has no import-order coupling to the root repo)."""

    tables: Tuple[str, ...]
    columns: Tuple[str, ...]
    filter_logic: str
    aggregation_fn: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> LineageSpec:
        return LineageSpec(
            tables=tuple(d["tables"]),
            columns=tuple(d["columns"]),
            filter_logic=d["filter_logic"],
            aggregation_fn=d.get("aggregation_fn"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tables": list(self.tables),
            "columns": list(self.columns),
            "filter_logic": self.filter_logic,
            "aggregation_fn": self.aggregation_fn,
        }


@dataclass(frozen=True)
class Pair:
    """A single labeled conflict-detection pair.

    Attributes:
        name: short human-readable identifier for the pair.
        category: one of ``TC`` (True Conflict), ``TV`` (Threshold Variant),
            ``LO`` (Logic-Operator change), ``CS`` (Column-Subset conflict),
            or ``AO`` (Aggregation-Operator conflict, Group A3's new
            category).
        a: the first lineage spec.
        b: the second lineage spec.
        is_conflict: ground-truth label -- should a correct detector flag
            this pair as a genuine metric-definition conflict?
        rationale: a short human-readable justification for the label.
    """

    name: str
    category: str
    a: LineageSpec
    b: LineageSpec
    is_conflict: bool
    rationale: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> Pair:
        return Pair(
            name=d["name"],
            category=d["category"],
            a=LineageSpec.from_dict(d["a"]),
            b=LineageSpec.from_dict(d["b"]),
            is_conflict=d["is_conflict"],
            rationale=d["rationale"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
            "is_conflict": self.is_conflict,
            "rationale": self.rationale,
        }


def load_pairs(path: Path) -> List[Pair]:
    """Load a list of :class:`Pair` from a dataset JSON file.

    The JSON file must be a list of pair objects (see :meth:`Pair.to_dict`
    for the exact shape), plus an optional leading ``_metadata`` object
    which is ignored here (kept for human/provenance context -- see
    ``data/conflict_dataset_ao_10.json``).

    Args:
        path: path to the dataset JSON file.

    Returns:
        The list of pairs, in file order.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ValueError: if the file's top-level JSON is not a list.
    """
    if not path.exists():
        raise FileNotFoundError(f"dataset file not found: {path}")
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        pairs_raw = raw["pairs"]
    elif isinstance(raw, list):
        pairs_raw = raw
    else:
        raise ValueError(f"{path}: expected a JSON list or an object with a 'pairs' key")
    return [Pair.from_dict(p) for p in pairs_raw]


def save_pairs(path: Path, pairs: Sequence[Pair], metadata: Optional[Dict[str, Any]] = None) -> None:
    """Write a list of :class:`Pair` to a dataset JSON file.

    Args:
        path: destination path.
        pairs: the pairs to write.
        metadata: optional provenance metadata written under a top-level
            ``"_metadata"`` key alongside ``"pairs"`` (e.g. labeling
            methodology, date, author -- see Group A3's limitations note).
    """
    payload: Dict[str, Any] = {"pairs": [p.to_dict() for p in pairs]}
    if metadata is not None:
        payload["_metadata"] = metadata
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


# ---------------------------------------------------------------------------
# D1: Exact Hash
# ---------------------------------------------------------------------------


def _legacy_hash(spec: LineageSpec) -> str:
    from amu_ext.aggregation import legacy_definition_hash

    return legacy_definition_hash(spec.tables, spec.columns, spec.filter_logic)


def d1_exact(pair: Pair) -> bool:
    """Exact hash: conflict iff the legacy definition_hash differs.

    Faithful port of ``fuzzy_experiment.py::d1_exact``. Does not consider
    ``aggregation_fn`` at all -- this is intentionally the *legacy* hash, so
    D1's blind spot on the AO category is exactly the blind spot Group A2's
    failing-test-first exercise demonstrates.
    """
    return _legacy_hash(pair.a) != _legacy_hash(pair.b)


# ---------------------------------------------------------------------------
# D2: Jaccard Filter Similarity
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\W+")


def _token_jaccard(a: str, b: str) -> float:
    ta = set(_WORD_RE.split(a.lower())) - {""}
    tb = set(_WORD_RE.split(b.lower())) - {""}
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def d2_jaccard(pair: Pair, threshold: float = 0.70) -> bool:
    """Jaccard filter similarity: faithful port of ``fuzzy_experiment.py::d2_jaccard``.

    If tables and columns match exactly, conflict iff the token-Jaccard
    similarity of the two filter_logic strings is below ``threshold``.
    Otherwise (tables or columns differ), always a conflict.
    """
    if set(pair.a.tables) == set(pair.b.tables) and set(pair.a.columns) == set(pair.b.columns):
        return _token_jaccard(pair.a.filter_logic, pair.b.filter_logic) < threshold
    return True


# ---------------------------------------------------------------------------
# D3: Column-Graph
# ---------------------------------------------------------------------------


def d3_column_graph(pair: Pair) -> bool:
    """Column-graph: faithful port of ``fuzzy_experiment.py::d3_column_graph``.

    Conflict iff tables differ OR column sets differ. Ignores filter_logic
    (and, by construction, aggregation_fn) entirely -- this is exactly what
    makes it blind to the LO and AO categories.
    """
    if set(pair.a.tables) != set(pair.b.tables):
        return True
    return set(pair.a.columns) != set(pair.b.columns)


# ---------------------------------------------------------------------------
# D4: Structural Gate + Filter-Logic Operator-Topology Diff  (Group A1, new)
# ---------------------------------------------------------------------------

# Longest-match-first alternation: multi-character comparison operators
# before single-character ones, and date/numeric normalization placeholders
# before the keyword scan.
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMLIST_RE = re.compile(r"\(\s*[\d.\s,]+\s*\)")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")

_TOPOLOGY_TOKEN_RE = re.compile(
    r"<DATE>|<NUM>|<NUMLIST>|>=|<=|!=|==|=|>|<|\bAND\b|\bOR\b|\bNOT\b|\bIN\b|\bBETWEEN\b",
    re.IGNORECASE,
)

_KEYWORD_CANON = {"AND": "AND", "OR": "OR", "NOT": "NOT", "IN": "IN", "BETWEEN": "BETWEEN"}


def operator_topology(filter_logic: str) -> Tuple[str, ...]:
    """Extract the ordered sequence of logical/comparison operators from a
    filter-logic description, with literal thresholds normalized away.

    Normalization order matters: dates are replaced before bare numbers (so
    a date's components are never partially matched by the number regex),
    and parenthesized numeric lists (e.g. ``"(1, 2, 3)"``, an ``IN``-list)
    are collapsed to a single ``<NUMLIST>`` placeholder *before* the bare-
    number pass, so that changing how many literal values are in a list
    (e.g. "priority IN (1, 2)" -> "priority IN (1, 2, 3)", a Threshold
    Variant, not a real conflict) does not change the token count.

    Args:
        filter_logic: the human-readable filter/derivation description.

    Returns:
        An ordered tuple of canonical operator tokens, e.g.
        ``("AND",)`` or ``(">=",)`` or ``("BETWEEN", "<DATE>", "AND", "<DATE>")``.
        Two filter_logic strings that differ only in literal
        thresholds/dates/list lengths produce identical topology tuples;
        two that differ in which logical/comparison operators are used, or
        in operator order, do not.
    """
    normalized = _DATE_RE.sub("<DATE>", filter_logic)
    normalized = _NUMLIST_RE.sub("(<NUMLIST>)", normalized)
    normalized = _NUM_RE.sub("<NUM>", normalized)

    tokens: List[str] = []
    for match in _TOPOLOGY_TOKEN_RE.finditer(normalized):
        raw = match.group(0)
        upper = raw.upper()
        tokens.append(_KEYWORD_CANON.get(upper, raw))
    return tuple(tokens)


def d4_structural_topology(pair: Pair) -> bool:
    """D4 = structural gate (D3's logic) + filter-logic operator-topology diff.

    Step 1 (structural gate): if tables or columns differ at all, it's a
    conflict -- identical to D3, and this alone is enough to correctly
    classify the TC and CS categories.

    Step 2 (only reached when tables and columns are identical): compare
    the two filter_logic strings' :func:`operator_topology`. A different
    topology (e.g. AND changed to OR, or a NOT was added/removed) is a
    conflict -- this is what catches the LO category that D3 is blind to.
    A pair that differs only in literal thresholds (the TV category)
    normalizes to the same topology and is correctly NOT flagged.

    D4 does not look at ``aggregation_fn`` at all -- see :func:`d5_with_aggregation`
    for the detector that closes that specific blind spot (Group A2/A3, the
    AO category).
    """
    if set(pair.a.tables) != set(pair.b.tables):
        return True
    if set(pair.a.columns) != set(pair.b.columns):
        return True
    return operator_topology(pair.a.filter_logic) != operator_topology(pair.b.filter_logic)


# ---------------------------------------------------------------------------
# D5: D4 + Aggregation-Equality Check  (Group A2, new)
# ---------------------------------------------------------------------------


def d5_with_aggregation(pair: Pair) -> bool:
    """D5 = D4, plus flag a conflict when ``aggregation_fn`` differs.

    Whenever D4 already flags a conflict, D5 agrees (D5 is strictly a
    superset of D4's flagged conflicts). When D4 says "no conflict"
    (identical tables, columns, and filter-logic topology), D5 additionally
    checks whether the two lineages' aggregation functions differ -- e.g.
    ``SUM(revenue)`` vs. ``AVG(revenue)`` over an otherwise-identical
    derivation. ``None`` and ``"IDENTITY"`` are treated as the same value
    (see :func:`amu_ext.aggregation.normalize_aggregation_fn`).

    This is the detector Group A3's AO (Aggregation-Operator) dataset is
    built to distinguish D4 from: D4 misses every AO pair by construction
    (aggregation_fn is not one of its inputs); D5 catches them via this
    added check.
    """
    if d4_structural_topology(pair):
        return True
    agg_a = normalize_aggregation_fn(pair.a.aggregation_fn)
    agg_b = normalize_aggregation_fn(pair.b.aggregation_fn)
    return agg_a != agg_b


#: Name -> detector function, in the order the paper's Table reports them.
DETECTORS: Dict[str, Callable[[Pair], bool]] = {
    "D1_exact_hash": d1_exact,
    "D2_jaccard": d2_jaccard,
    "D3_column_graph": d3_column_graph,
    "D4_structural_topology": d4_structural_topology,
    "D5_with_aggregation": d5_with_aggregation,
}
