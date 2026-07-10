"""
trust_weighting.py
------------------
Phase 6 — Crowd-Confidence-Aware Edge Weighting.

Adjusts edge traversal costs using crowd confidence scores provided by
Person A's trust-signal pipeline.  This module never *computes* crowd
confidence — it only *consumes* the values.

Design decisions
~~~~~~~~~~~~~~~~
1. **Configurable weighting formula.**
   The mapping from ``(base_weight, crowd_confidence)`` to ``final_weight``
   is a callable (``WeightingFormula``).  The default formula is
   ``inverse_confidence_weighting``, but any function with the same
   signature can be injected — no code change needed.

2. **Two built-in formulas.**
   - ``inverse_confidence_weighting``: High confidence → lower cost →
     preferred edge.  ``final = base_weight / (confidence + epsilon)``.
   - ``linear_discount_weighting``: Scales base weight down linearly by
     confidence.  ``final = base_weight * (1 - discount_factor * confidence)``.

   Both avoid division-by-zero via an ``epsilon`` floor and clamp to
   ``[min_weight, ∞)`` to prevent zero-cost or negative-cost edges.

3. **Batch processing.**
   ``apply_trust_weights`` processes an entire list of edges at once,
   producing a list of ``TrustWeightedEdge`` models.  This is the
   primary integration point — the planner calls it once with all edges
   rather than per-edge, keeping the hot path allocation-efficient.

4. **Pure functions — zero state.**
   Every function in this module is pure (same inputs → same outputs).
   No caching, no singletons, no side-effects.  This makes it trivially
   testable and thread-safe.

Integration with previous phases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Consumes crowd confidence values from Person A (Phase 6).
- Produces ``TrustWeightedEdge`` models defined in ``agent.models``
  (Phase 6 — Step 1).
- Used by the planner (Step 4) to optionally switch from unweighted to
  trust-weighted edge traversal.

Future extensions
~~~~~~~~~~~~~~~~~
- Learner-specific confidence (personalised trust signals).
- Time-decayed confidence (newer reviews weighted more).
- Multi-signal weighting (combine crowd confidence with expert ratings).
"""

import logging
from typing import Callable, Optional

from agent.models import TrustWeightedEdge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type alias for the weighting formula
# ---------------------------------------------------------------------------

# (base_weight, crowd_confidence) -> final_weight
WeightingFormula = Callable[[float, float], float]


# ---------------------------------------------------------------------------
# Built-in weighting formulas
# ---------------------------------------------------------------------------

# Small constant to prevent division-by-zero and zero-cost edges.
_DEFAULT_EPSILON: float = 0.01

# Floor for the final weight — prevents degenerate zero-cost edges.
_DEFAULT_MIN_WEIGHT: float = 0.01


def inverse_confidence_weighting(
    base_weight: float,
    crowd_confidence: float,
    *,
    epsilon: float = _DEFAULT_EPSILON,
    min_weight: float = _DEFAULT_MIN_WEIGHT,
) -> float:
    """Inverse weighting: high confidence → low traversal cost.

    Formula::

        final_weight = base_weight / (crowd_confidence + epsilon)

    This produces a *cost* metric where edges with strong community
    agreement become cheaper to traverse.

    Parameters
    ----------
    base_weight : float
        Original edge weight from the knowledge graph (≥ 0).
    crowd_confidence : float
        Person A's crowd confidence score (0.0–1.0).
    epsilon : float
        Small constant added to the denominator to avoid division by zero.
    min_weight : float
        Floor value — the result is clamped to ``max(result, min_weight)``.

    Returns
    -------
    float
        Adjusted traversal cost.

    Examples
    --------
    >>> inverse_confidence_weighting(1.0, 1.0)   # high confidence
    0.99...  (≈ 1.0 / 1.01)
    >>> inverse_confidence_weighting(1.0, 0.1)   # low confidence
    9.09...  (≈ 1.0 / 0.11)
    """
    raw = base_weight / (crowd_confidence + epsilon)
    return max(raw, min_weight)


def linear_discount_weighting(
    base_weight: float,
    crowd_confidence: float,
    *,
    discount_factor: float = 0.5,
    min_weight: float = _DEFAULT_MIN_WEIGHT,
) -> float:
    """Linear discount: confidence reduces the cost proportionally.

    Formula::

        final_weight = base_weight * (1 - discount_factor * crowd_confidence)

    With ``discount_factor=0.5`` and full confidence (1.0), the cost is
    halved.  With zero confidence, the cost equals ``base_weight``.

    Parameters
    ----------
    base_weight : float
        Original edge weight from the knowledge graph (≥ 0).
    crowd_confidence : float
        Person A's crowd confidence score (0.0–1.0).
    discount_factor : float
        Maximum fraction of the base weight that can be discounted
        (0.0–1.0).  Higher values give more weight to confidence.
    min_weight : float
        Floor value — the result is clamped to ``max(result, min_weight)``.

    Returns
    -------
    float
        Adjusted traversal cost.

    Examples
    --------
    >>> linear_discount_weighting(1.0, 1.0, discount_factor=0.5)
    0.5
    >>> linear_discount_weighting(1.0, 0.0, discount_factor=0.5)
    1.0
    """
    raw = base_weight * (1.0 - discount_factor * crowd_confidence)
    return max(raw, min_weight)


# ---------------------------------------------------------------------------
# Single-edge computation
# ---------------------------------------------------------------------------

def calculate_edge_weight(
    base_weight: float,
    crowd_confidence: float,
    *,
    formula: Optional[WeightingFormula] = None,
) -> float:
    """Compute the final traversal cost for a single edge.

    This is the primary public API for one-off edge weight calculations.
    For batch processing, prefer ``apply_trust_weights`` which also
    produces ``TrustWeightedEdge`` models.

    Parameters
    ----------
    base_weight : float
        Original edge weight from the knowledge graph.
    crowd_confidence : float
        Person A's crowd confidence score (0.0–1.0).
    formula : WeightingFormula, optional
        Custom weighting function.  Defaults to
        ``inverse_confidence_weighting``.

    Returns
    -------
    float
        Adjusted edge weight (traversal cost).
    """
    weighting_fn = formula or inverse_confidence_weighting
    final = weighting_fn(base_weight, crowd_confidence)

    logger.debug(
        "Edge weight: base=%.4f, confidence=%.4f → final=%.4f",
        base_weight, crowd_confidence, final,
    )
    return final


# ---------------------------------------------------------------------------
# Batch processing — the main integration point for the planner
# ---------------------------------------------------------------------------

# Expected dict shape from the graph for edges with trust metadata:
#   {
#       "source_skill": str,
#       "target_skill": str,
#       "base_weight": float,          # defaults to 1.0 if absent
#       "crowd_confidence": float,     # defaults to 1.0 if absent
#   }


def apply_trust_weights(
    edges: list[dict],
    *,
    formula: Optional[WeightingFormula] = None,
) -> list[TrustWeightedEdge]:
    """Apply trust weighting to a batch of edges.

    This is the primary integration point used by the planner's
    trust-aware mode.  It converts raw edge dicts (from the graph
    service) into ``TrustWeightedEdge`` models with computed
    ``final_weight`` values.

    Parameters
    ----------
    edges : list[dict]
        Raw edge dicts with at least ``source_skill`` and ``target_skill``.
        ``base_weight`` and ``crowd_confidence`` default to ``1.0`` if
        absent.
    formula : WeightingFormula, optional
        Custom weighting function.  Defaults to
        ``inverse_confidence_weighting``.

    Returns
    -------
    list[TrustWeightedEdge]
        Edges augmented with computed ``final_weight``.

    Examples
    --------
    >>> edges = [
    ...     {"source_skill": "web03", "target_skill": "web04",
    ...      "base_weight": 1.0, "crowd_confidence": 0.9},
    ... ]
    >>> weighted = apply_trust_weights(edges)
    >>> weighted[0].final_weight < 1.1  # high confidence → low cost
    True
    """
    logger.info("Applying trust weights to %d edge(s).", len(edges))

    weighting_fn = formula or inverse_confidence_weighting
    weighted_edges: list[TrustWeightedEdge] = []

    for edge in edges:
        source = edge["source_skill"]
        target = edge["target_skill"]
        base = float(edge.get("base_weight", 1.0))
        confidence = float(edge.get("crowd_confidence", 1.0))

        final = weighting_fn(base, confidence)

        weighted_edges.append(
            TrustWeightedEdge(
                source_skill=source,
                target_skill=target,
                base_weight=base,
                crowd_confidence=confidence,
                final_weight=final,
            )
        )

    logger.debug(
        "Trust weighting complete: %d edge(s) processed.",
        len(weighted_edges),
    )
    return weighted_edges
