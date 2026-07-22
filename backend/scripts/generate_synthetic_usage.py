"""
generate_synthetic_usage.py
----------------------------
Bootstraps optimizer/calibration.py with synthetic training data, since
there are no real learners on this project yet and the calibration
mechanism needs *something* to fit against to be exercised end-to-end.

HONEST LABEL: every node this script writes is tagged :SyntheticOutcome,
kept structurally and semantically separate from real Resource/Rating
data. Weights calibrated from this data are a demonstration that the
calibration *mechanism* works, not a claim that the resulting weights
are correct for real usage. Delete all :SyntheticOutcome nodes
(``MATCH (o:SyntheticOutcome) DETACH DELETE o``) once real outcome data
exists and start calibrating from that instead.

The generation model: for each synthetic example, draw random component
scores and construct a label using an assumed "true" relationship
(rating matters most, then completeness, then recency) plus noise - this
lets you sanity-check that calibrate_quality_weights() recovers
something in the neighborhood of that assumed relationship, which is a
reasonable way to verify the mechanism without real data, not a way to
manufacture a "correct" answer.

Usage:
    python scripts/generate_synthetic_usage.py [count]
    (default count: 200)
"""

import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.database import get_driver
from optimizer.calibration import record_synthetic_outcome

# Assumed "true" relationship used only to generate a plausible synthetic
# label - NOT presented anywhere as a real, validated formula.
_TRUE_WEIGHT_RATING = 0.55
_TRUE_WEIGHT_RECENCY = 0.15
_TRUE_WEIGHT_COMPLETENESS = 0.30
_NOISE_STD = 0.08


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def generate_one(rng: random.Random) -> tuple[float, float, float, float]:
    rating = rng.random()
    recency = rng.random()
    completeness = rng.random()
    true_signal = (
        _TRUE_WEIGHT_RATING * rating
        + _TRUE_WEIGHT_RECENCY * recency
        + _TRUE_WEIGHT_COMPLETENESS * completeness
    )
    label = _clip01(true_signal + rng.gauss(0, _NOISE_STD))
    return rating, recency, completeness, label


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(42)  # fixed seed - reproducible synthetic runs

    driver = get_driver()
    written = 0
    with driver.session() as session:
        for _ in range(count):
            rating, recency, completeness, label = generate_one(rng)
            session.execute_write(
                record_synthetic_outcome,
                normalized_rating=rating,
                recency_score=recency,
                completeness_score=completeness,
                label=label,
            )
            written += 1

    print(f"Wrote {written} :SyntheticOutcome node(s).")
    print("Run the calibration job (or wait for the autonomous scheduler) to fit weights from this data.")
    print("Remember to delete these nodes once real outcome data exists:")
    print("  MATCH (o:SyntheticOutcome) DETACH DELETE o")


if __name__ == "__main__":
    main()
