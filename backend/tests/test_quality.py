"""
test_quality.py
Tests for marketplace/quality.py (quality scoring + trust-signal
corroboration; evolution-tracking has no dedicated test file here,
same as before consolidation - it's exercised via the marketplace
integration tests).

Consolidated from test_quality_scoring.py + test_trust_signal.py.
"""

from datetime import datetime, timedelta, timezone
from marketplace.quality import (
    compute_recency_score,
    compute_completeness_score,
    compute_quality_score,
    compute_crowd_corroboration,
)


# ===================================================================
# Quality scoring (pure math, deterministic)
# ===================================================================

def test_recency_score_high_for_new_resource():
    now = datetime.now(timezone.utc)
    score = compute_recency_score(now, now=now)
    assert abs(score - 1.0) < 1e-9


def test_recency_score_decreases_over_time():
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=100)
    score = compute_recency_score(old_date, now=now)
    assert 0.0 < score < 1.0


def test_completeness_score_full_match():
    assert compute_completeness_score(claimed_skill_count=5, confirmed_skill_count=5) == 1.0


def test_completeness_score_partial_match():
    score = compute_completeness_score(claimed_skill_count=5, confirmed_skill_count=2)
    assert abs(score - 0.4) < 1e-9


def test_completeness_score_zero_claimed_returns_zero():
    assert compute_completeness_score(claimed_skill_count=0, confirmed_skill_count=0) == 0.0


def test_completeness_score_capped_at_one():
    score = compute_completeness_score(claimed_skill_count=2, confirmed_skill_count=5)
    assert score == 1.0


def test_quality_score_within_bounds():
    now = datetime.now(timezone.utc)
    score = compute_quality_score(
        peer_rating_avg=4.5, upload_date=now,
        claimed_skill_count=5, confirmed_skill_count=4, now=now,
    )
    assert 0.0 <= score <= 1.0


def test_quality_score_higher_for_better_inputs():
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=365)

    good_score = compute_quality_score(
        peer_rating_avg=5.0, upload_date=now,
        claimed_skill_count=5, confirmed_skill_count=5, now=now,
    )
    worse_score = compute_quality_score(
        peer_rating_avg=1.0, upload_date=old_date,
        claimed_skill_count=5, confirmed_skill_count=1, now=now,
    )
    assert good_score > worse_score


# ===================================================================
# Trust signal (crowd corroboration)
# ===================================================================

class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeTx:
    """Returns a pre-set corroborating_author_count regardless of query specifics."""
    def __init__(self, fake_count):
        self.fake_count = fake_count

    def run(self, query, **params):
        return FakeResult([FakeRecord({"corroborating_author_count": self.fake_count})])


def test_compute_crowd_corroboration_returns_count():
    tx = FakeTx(fake_count=3)
    count = compute_crowd_corroboration(tx, "WEB004", "WEB006")
    assert count == 3


def test_compute_crowd_corroboration_zero_when_no_overlap():
    tx = FakeTx(fake_count=0)
    count = compute_crowd_corroboration(tx, "WEB004", "AI001")
    assert count == 0
