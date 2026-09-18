"""
Aggregation-operator schema extension (Group A2).

The published paper's ``definition_hash`` (``model.py::Lineage.definition_hash``,
mirrored in ``fuzzy_experiment.py`` and the ``amu-governance`` package) is a
hash of ``(tables touched, columns touched, filter_logic string)``. It has no
notion of *aggregation function*: ``SUM(revenue)`` and ``AVG(revenue)``,
computed over an identical join path, identical columns, and identical
filter logic, hash identically today. That is a real metric-definition
conflict a lineage-aware system would currently miss -- two departments
could each cache "revenue" under the same metric_name, one meaning the sum
and one meaning the average, and the naive-vs-lineage-aware comparison would
never surface it because it isn't a *lineage* difference in the schema as
published.

This module adds an ``aggregation_fn`` field to the hash payload and
provides both the legacy (pre-extension) hash and the extended hash side by
side, so the blind spot and the fix can both be demonstrated and regression-
tested (see ``tests/unit/test_aggregation.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import FrozenSet, Optional

__all__ = [
    "KNOWN_AGGREGATION_FUNCTIONS",
    "normalize_aggregation_fn",
    "legacy_definition_hash",
    "definition_hash_with_aggregation",
]

#: Aggregation functions this schema extension recognizes. ``IDENTITY``
#: stands in for "no aggregation" (a row-level / already-scalar value),
#: which is what ``None`` normalizes to -- see :func:`normalize_aggregation_fn`.
KNOWN_AGGREGATION_FUNCTIONS: FrozenSet[str] = frozenset({"SUM", "AVG", "COUNT", "MIN", "MAX", "IDENTITY"})


def normalize_aggregation_fn(aggregation_fn: Optional[str]) -> str:
    """Normalize an aggregation-function label to its canonical uppercase form.

    ``None`` (no aggregation function recorded / not applicable) normalizes
    to ``"IDENTITY"`` so it participates in hashing and equality checks like
    any other value, rather than requiring special-cased ``None`` handling
    at every call site.

    Args:
        aggregation_fn: a raw aggregation label (``"sum"``, ``"SUM"``,
            ``None``, ...), as it might appear in hand-authored dataset JSON.

    Returns:
        The canonical uppercase label.

    Raises:
        ValueError: if the (uppercased) label is not one of
            :data:`KNOWN_AGGREGATION_FUNCTIONS`.
    """
    label = "IDENTITY" if aggregation_fn is None else aggregation_fn.strip().upper()
    if label not in KNOWN_AGGREGATION_FUNCTIONS:
        raise ValueError(
            f"unrecognized aggregation_fn {aggregation_fn!r}; expected one of "
            f"{sorted(KNOWN_AGGREGATION_FUNCTIONS)} or None"
        )
    return label


def legacy_definition_hash(tables: Sequence[str], columns: Sequence[str], filter_logic: str) -> str:
    """The pre-extension definition hash: identical to ``model.py``'s.

    Hashes ``(sorted(tables), sorted(columns), filter_logic)`` only. This is
    kept, verbatim in logic, specifically so
    ``tests/unit/test_aggregation.py`` can demonstrate the aggregation-
    operator blind spot against the *exact* hash the paper published, not a
    reconstruction of it.

    Args:
        tables: table names touched by the lineage.
        columns: column names touched by the lineage.
        filter_logic: the human-readable filter/derivation description.

    Returns:
        A 12-hex-character SHA-256 prefix, matching ``model.py``'s truncation.
    """
    payload = f"{tuple(sorted(tables))}|{tuple(sorted(columns))}|{filter_logic}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def definition_hash_with_aggregation(
    tables: Sequence[str],
    columns: Sequence[str],
    filter_logic: str,
    aggregation_fn: Optional[str] = None,
) -> str:
    """The schema-extended definition hash: adds ``aggregation_fn`` to the payload.

    Two lineages identical in every respect except aggregation function now
    hash to different values, closing the blind spot in
    :func:`legacy_definition_hash`.

    Args:
        tables: table names touched by the lineage.
        columns: column names touched by the lineage.
        filter_logic: the human-readable filter/derivation description.
        aggregation_fn: the aggregation function applied (``"SUM"``,
            ``"AVG"``, ``"COUNT"``, ``"MIN"``, ``"MAX"``), or ``None`` for
            "no aggregation" (normalized to ``"IDENTITY"``).

    Returns:
        A 12-hex-character SHA-256 prefix.
    """
    normalized = normalize_aggregation_fn(aggregation_fn)
    payload = f"{tuple(sorted(tables))}|{tuple(sorted(columns))}|{filter_logic}|{normalized}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
