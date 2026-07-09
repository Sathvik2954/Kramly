"""
test_trust_signal.py
Phase 6, Person A — tests for trust_signal.py using a hand-rolled mock,
same caveat as prior test files: adapt to your real conftest.py pattern.
"""

from marketplace.trust_signal import compute_crowd_corroboration


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
