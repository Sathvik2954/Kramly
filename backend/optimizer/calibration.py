"""
calibration.py
---------------
Turns the static quality-score weights in Settings.quality_weight_* from
constants someone typed once into values fitted from outcome data.

HONEST SCOPE FLAG: there are no real learners using Kramly yet, so this
module has no real outcome data to fit against. What it fits against
instead is data written by scripts/generate_synthetic_usage.py, clearly
labeled :SyntheticOutcome in the graph — never mixed with real Resource/
Rating data. Calibrated weights this module produces from synthetic data
are mechanically real (the regression genuinely runs and genuinely
changes the weights) but are NOT evidence that the resulting weights are
better than the static defaults in the real world. They become
meaningful once synthetic outcomes are replaced by real ones: track
whether a resource's component scores (rating, recency, completeness)
predicted whether it stayed active vs. got superseded/abandoned, and feed
that into record_synthetic_outcome's real-data equivalent instead.

What the fit actually does
~~~~~~~~~~~~~~~~~~~~~~~~~~
Ordinary least squares, no intercept, 3 features (normalized_rating,
recency_score, completeness_score) predicting a single label in [0, 1]
("did this resource stay active / get a strong outcome"). This mirrors
the existing quality-score formula's own structure (a weighted sum of
exactly these three components), so the fitted coefficients slot
directly back in as replacement weights. Solved via the 3x3 normal
equations (X^T X) w = X^T y, in pure Python — no numpy dependency added
just for a 3x3 solve. Weights are clipped to >= 0 and renormalized to
sum to 1, since the original design assumes a bounded, sane composite
score.
"""

import datetime as _dt
from typing import Optional


def record_synthetic_outcome(
    tx,
    normalized_rating: float,
    recency_score: float,
    completeness_score: float,
    label: float,
):
    """Writes one synthetic training example. Only called by
    scripts/generate_synthetic_usage.py — never by real request-handling
    code."""
    query = """
    CREATE (o:SyntheticOutcome {
        normalized_rating: $normalized_rating,
        recency_score: $recency_score,
        completeness_score: $completeness_score,
        label: $label,
        created_at: $created_at
    })
    """
    tx.run(
        query,
        normalized_rating=normalized_rating,
        recency_score=recency_score,
        completeness_score=completeness_score,
        label=label,
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def _fetch_outcomes(tx) -> list[tuple[float, float, float, float]]:
    query = """
    MATCH (o:SyntheticOutcome)
    RETURN o.normalized_rating AS rating, o.recency_score AS recency,
           o.completeness_score AS completeness, o.label AS label
    """
    result = tx.run(query)
    return [
        (r["rating"], r["recency"], r["completeness"], r["label"])
        for r in result
    ]


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> Optional[list[float]]:
    """Solves a 3x3 linear system via Gaussian elimination with partial
    pivoting. Returns None if the matrix is singular (degenerate/too
    little variance in the outcome data to fit anything meaningful)."""
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    n = 3

    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot_row][col]) < 1e-10:
            return None
        a[col], a[pivot_row] = a[pivot_row], a[col]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]

    return [a[i][n] / a[i][i] for i in range(n)]


def _fit_weights_ols(outcomes: list[tuple[float, float, float, float]]) -> Optional[tuple[float, float, float]]:
    """Fits (w_rating, w_recency, w_completeness) via ordinary least
    squares, no intercept. Returns None if the system is degenerate."""
    # Build X^T X (3x3) and X^T y (3x1) directly rather than materializing
    # the full design matrix - there are only 3 features, so this is a
    # handful of sums, not worth pulling in numpy for.
    xtx = [[0.0] * 3 for _ in range(3)]
    xty = [0.0, 0.0, 0.0]

    for rating, recency, completeness, label in outcomes:
        x = [rating, recency, completeness]
        for i in range(3):
            xty[i] += x[i] * label
            for j in range(3):
                xtx[i][j] += x[i] * x[j]

    solved = _solve_3x3(xtx, xty)
    if solved is None:
        return None

    # Clip negative weights to 0 (a negative weight would mean "higher
    # rating predicts worse outcome", which we treat as noise/overfit on
    # a small sample rather than a real inverse relationship) and
    # renormalize so the three weights sum to 1, matching the static
    # defaults' implicit constraint.
    clipped = [max(0.0, w) for w in solved]
    total = sum(clipped)
    if total <= 0:
        return None
    return tuple(w / total for w in clipped)


def calibrate_quality_weights(tx) -> Optional[tuple[float, float, float]]:
    """Fits and persists calibrated quality weights from SyntheticOutcome
    data, if there's enough of it (Settings.calibration_min_samples).

    Returns (w_peer_rating, w_recency, w_completeness), or None if there
    isn't enough outcome data yet or the fit was degenerate - callers
    should keep using Settings.quality_weight_* in that case.
    """
    from app.config import settings

    outcomes = _fetch_outcomes(tx)
    if len(outcomes) < settings.calibration_min_samples:
        return None

    fitted = _fit_weights_ols(outcomes)
    if fitted is None:
        return None

    w_rating, w_recency, w_completeness = fitted

    query = """
    MERGE (c:CalibrationState {id: 'quality_weights'})
    SET c.weight_peer_rating = $w_rating,
        c.weight_recency = $w_recency,
        c.weight_completeness = $w_completeness,
        c.sample_count = $sample_count,
        c.calibrated_at = $calibrated_at,
        c.source = 'synthetic'
    """
    tx.run(
        query,
        w_rating=w_rating,
        w_recency=w_recency,
        w_completeness=w_completeness,
        sample_count=len(outcomes),
        calibrated_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )

    return fitted


def get_active_quality_weights(tx) -> tuple[float, float, float]:
    """Returns the weights quality.compute_quality_score() should use
    right now: the persisted calibration if one exists, otherwise the
    static Settings.quality_weight_* defaults.
    """
    from app.config import settings

    query = """
    MATCH (c:CalibrationState {id: 'quality_weights'})
    RETURN c.weight_peer_rating AS w_rating, c.weight_recency AS w_recency,
           c.weight_completeness AS w_completeness, c.source AS source
    """
    result = tx.run(query)
    record = result.single()
    if record is None:
        return (
            settings.quality_weight_peer_rating,
            settings.quality_weight_recency,
            settings.quality_weight_completeness,
        )
    return (record["w_rating"], record["w_recency"], record["w_completeness"])
