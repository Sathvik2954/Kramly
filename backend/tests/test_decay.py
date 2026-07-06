"""
test_decay.py
Phase 2, Person A — unit tests for decay.py.

NOTE: your project already has conftest.py with Neo4j mocking fixtures
(per project_structure.md). This file's tests don't need a DB at all
(decay.py is pure math), so no mocking is required here — but check that
this test file's naming/location matches your existing pytest config.
"""

from datetime import datetime, timedelta, timezone
from optimizer.decay import compute_decayed_confidence, has_crossed_decay_threshold


def test_no_decay_at_zero_days():
    now = datetime.now(timezone.utc)
    result = compute_decayed_confidence(base_confidence=1.0, last_practiced=now, now=now)
    assert abs(result - 1.0) < 1e-9


def test_decay_decreases_over_time():
    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=10)
    result = compute_decayed_confidence(base_confidence=1.0, last_practiced=ten_days_ago, now=now)
    assert 0.0 < result < 1.0


def test_decay_clamped_to_zero_minimum():
    now = datetime.now(timezone.utc)
    very_old = now - timedelta(days=100000)
    result = compute_decayed_confidence(base_confidence=1.0, last_practiced=very_old, now=now)
    assert result >= 0.0


def test_future_timestamp_does_not_decay():
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=5)
    result = compute_decayed_confidence(base_confidence=0.8, last_practiced=future, now=now)
    assert abs(result - 0.8) < 1e-9


def test_threshold_crossing_detected():
    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(days=60)
    crossed = has_crossed_decay_threshold(base_confidence=1.0, last_practiced=long_ago, threshold=0.5, now=now)
    assert crossed is True


def test_threshold_not_crossed_recently_practiced():
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=1)
    crossed = has_crossed_decay_threshold(base_confidence=1.0, last_practiced=recent, threshold=0.5, now=now)
    assert crossed is False
