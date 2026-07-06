"""
decay.py
Phase 2, Person A — Adaptive Re-Planning: decay/forgetting model.

HONESTY NOTE: There is no single verified "standard" decay formula for
skill forgetting. Spaced-repetition systems like Anki's SM-2 algorithm are
a real, documented reference point, but I am not confident enough in
reproducing SM-2's exact formula from memory to hand it to you as correct —
verify it yourself from Anki's official documentation if you specifically
want SM-2 rather than this simpler model.

What follows is a simple, original exponential decay function designed for
this project — a reasonable MVP choice, not a citation of existing research.
The DEFAULT_DECAY_RATE_PER_DAY constant is arbitrary and untested; tune it
based on how it feels in practice, not because it's derived from a source.
"""

import math
from datetime import datetime, timezone

DEFAULT_DECAY_RATE_PER_DAY = 0.03  # ~3%/day compounding decay — arbitrary starting value


def compute_decayed_confidence(
    base_confidence: float,
    last_practiced: datetime,
    now: datetime = None,
    decay_rate: float = DEFAULT_DECAY_RATE_PER_DAY,
) -> float:
    """
    decayed = base_confidence * e^(-decay_rate * days_elapsed)
    Clamped to [0.0, 1.0].
    """
    if now is None:
        now = datetime.now(timezone.utc)

    days_elapsed = (now - last_practiced).total_seconds() / 86400.0
    if days_elapsed < 0:
        # last_practiced in the future — bad input, don't decay
        return max(0.0, min(1.0, base_confidence))

    decayed = base_confidence * math.exp(-decay_rate * days_elapsed)
    return max(0.0, min(1.0, decayed))


def has_crossed_decay_threshold(
    base_confidence: float,
    last_practiced: datetime,
    threshold: float = 0.5,
    now: datetime = None,
    decay_rate: float = DEFAULT_DECAY_RATE_PER_DAY,
) -> bool:
    """
    True if decayed confidence has fallen below `threshold` — used as a
    Phase 2.3 re-planning trigger (Person B's track wires this in).
    """
    return compute_decayed_confidence(base_confidence, last_practiced, now, decay_rate) < threshold
