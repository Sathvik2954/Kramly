"""
test_decay.py
Tests for the decay layer: the pure confidence-decay math (optimizer/decay.py)
and the Neo4j scanning logic that uses it to flag decayed skills
(app/decay_scanner.py). Consolidated from test_decay.py + test_decay_scanner.py
since both exercise the same "has this skill decayed" concept end-to-end.
"""

from datetime import datetime, timedelta, timezone

from optimizer.decay import compute_decayed_confidence, has_crossed_decay_threshold
from app.decay_scanner import scan_for_decayed_skills, _parse_timestamp


# ---------------------------------------------------------------------------
# compute_decayed_confidence / has_crossed_decay_threshold — pure math,
# no DB needed.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# scan_for_decayed_skills — uses a hand-written fake Neo4j tx (no live DB).
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Mimics a Neo4j record enough for dict(record) to work in the scanner."""
    pass


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeTx:
    """Mock transaction — returns pre-set fake data instead of hitting Neo4j."""
    def __init__(self, fake_states):
        self.fake_states = fake_states

    def run(self, query):
        return FakeResult([FakeRecord(s) for s in self.fake_states])


def test_flags_decayed_skill():
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=60)).isoformat()

    fake_states = [
        {"learner_id": "learner_001", "skill_id": "WEB004",
         "confidence": 1.0, "last_practiced": old_timestamp},
    ]
    tx = FakeTx(fake_states)

    flagged = scan_for_decayed_skills(tx, threshold=0.5, now=now)

    assert len(flagged) == 1
    assert flagged[0]["learner_id"] == "learner_001"
    assert flagged[0]["skill_id"] == "WEB004"
    assert flagged[0]["decayed_confidence"] < 0.5


def test_does_not_flag_recent_practice():
    now = datetime.now(timezone.utc)
    recent_timestamp = (now - timedelta(hours=2)).isoformat()

    fake_states = [
        {"learner_id": "learner_001", "skill_id": "WEB004",
         "confidence": 1.0, "last_practiced": recent_timestamp},
    ]
    tx = FakeTx(fake_states)

    flagged = scan_for_decayed_skills(tx, threshold=0.5, now=now)

    assert len(flagged) == 0


def test_skips_incomplete_records_without_crashing():
    now = datetime.now(timezone.utc)
    fake_states = [
        {"learner_id": "learner_001", "skill_id": "WEB004",
         "confidence": None, "last_practiced": None},
        {"learner_id": "learner_002", "skill_id": "WEB005",
         "confidence": 1.0, "last_practiced": (now - timedelta(days=60)).isoformat()},
    ]
    tx = FakeTx(fake_states)

    flagged = scan_for_decayed_skills(tx, threshold=0.5, now=now)

    # Only learner_002's valid record should be evaluated; learner_001's
    # incomplete record should be skipped, not crash the scan.
    assert len(flagged) == 1
    assert flagged[0]["learner_id"] == "learner_002"


def test_skips_malformed_timestamp_without_crashing():
    now = datetime.now(timezone.utc)
    fake_states = [
        {"learner_id": "learner_003", "skill_id": "WEB006",
         "confidence": 1.0, "last_practiced": "not-a-real-timestamp"},
    ]
    tx = FakeTx(fake_states)

    # Should not raise — malformed record is skipped with a warning printed.
    flagged = scan_for_decayed_skills(tx, threshold=0.5, now=now)
    assert flagged == []


def test_multiple_learners_multiple_skills():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=90)).isoformat()
    recent = (now - timedelta(hours=1)).isoformat()

    fake_states = [
        {"learner_id": "learner_A", "skill_id": "S1", "confidence": 1.0, "last_practiced": old},
        {"learner_id": "learner_A", "skill_id": "S2", "confidence": 1.0, "last_practiced": recent},
        {"learner_id": "learner_B", "skill_id": "S1", "confidence": 1.0, "last_practiced": old},
    ]
    tx = FakeTx(fake_states)

    flagged = scan_for_decayed_skills(tx, threshold=0.5, now=now)

    flagged_pairs = {(f["learner_id"], f["skill_id"]) for f in flagged}
    assert ("learner_A", "S1") in flagged_pairs
    assert ("learner_A", "S2") not in flagged_pairs
    assert ("learner_B", "S1") in flagged_pairs
    assert len(flagged) == 2


def test_parse_timestamp_handles_datetime_passthrough():
    now = datetime.now(timezone.utc)
    assert _parse_timestamp(now) == now


def test_parse_timestamp_handles_iso_string():
    now = datetime.now(timezone.utc)
    iso = now.isoformat()
    parsed = _parse_timestamp(iso)
    assert abs((parsed - now).total_seconds()) < 1
