"""
decay.py
Adaptive re-planning: decay/forgetting model.

HONESTY NOTE: There is no single verified "standard" decay formula for
skill forgetting. Spaced-repetition systems like Anki's SM-2 algorithm are
a real, documented reference point, but I am not confident enough in
reproducing SM-2's exact formula from memory to hand it to you as correct —
verify it yourself from Anki's official documentation if you specifically
want SM-2 rather than this simpler model.

What follows is a simple, original exponential decay function designed for
this project — a reasonable MVP choice, not a citation of existing research.
The decay rate is configurable via Settings.decay_rate_per_day (see
app/config.py) rather than hardcoded here; the default there is the same
arbitrary starting value this module always used. Making it configurable
doesn't make it correct — it makes it adjustable once optimizer/calibration.py
has real outcome data to fit it against.
"""

import math
from datetime import datetime, timezone
from typing import Optional


def _default_decay_rate() -> float:
    from app.config import settings
    return settings.decay_rate_per_day


def _default_decay_threshold() -> float:
    from app.config import settings
    return settings.decay_threshold


def compute_decayed_confidence(
    base_confidence: float,
    last_practiced: datetime,
    now: datetime = None,
    decay_rate: Optional[float] = None,
) -> float:
    """
    decayed = base_confidence * e^(-decay_rate * days_elapsed)
    Clamped to [0.0, 1.0].

    decay_rate defaults to Settings.decay_rate_per_day when not given
    explicitly (tests pass an explicit value to stay deterministic).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if decay_rate is None:
        decay_rate = _default_decay_rate()

    days_elapsed = (now - last_practiced).total_seconds() / 86400.0
    if days_elapsed < 0:
        # last_practiced in the future — bad input, don't decay
        return max(0.0, min(1.0, base_confidence))

    decayed = base_confidence * math.exp(-decay_rate * days_elapsed)
    return max(0.0, min(1.0, decayed))


def has_crossed_decay_threshold(
    base_confidence: float,
    last_practiced: datetime,
    threshold: Optional[float] = None,
    now: datetime = None,
    decay_rate: Optional[float] = None,
) -> bool:
    """
    True if decayed confidence has fallen below `threshold` — used as the
    re-planning trigger the agent layer wires in.

    threshold defaults to Settings.decay_threshold when not given explicitly.
    """
    if threshold is None:
        threshold = _default_decay_threshold()
    return compute_decayed_confidence(base_confidence, last_practiced, now, decay_rate) < threshold
