"""
test_quality_scoring.py
Phase 6, Person A — tests for quality_scoring.py's pure-math functions.
No mocking needed for compute_recency_score/compute_completeness_score/
compute_quality_score — these are deterministic given fixed inputs.
"""

from datetime import datetime, timedelta, timezone
from marketplace.quality_scoring import (
    compute_recency_score,
    compute_completeness_score,
    compute_quality_score,
)


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
    # confirmed > claimed shouldn't happen normally, but shouldn't exceed 1.0 if it does
    score = compute_completeness_score(claimed_skill_count=2, confirmed_skill_count=5)
    assert score == 1.0


def test_quality_score_within_bounds():
    now = datetime.now(timezone.utc)
    score = compute_quality_score(
        peer_rating_avg=4.5,
        upload_date=now,
        claimed_skill_count=5,
        confirmed_skill_count=4,
        now=now,
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
