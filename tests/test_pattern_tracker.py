"""Tests for the PatternTracker module."""

from __future__ import annotations

from datetime import datetime, timedelta
from src.pattern_tracker import PatternTracker


class TestPatternTracker:
    def setup_method(self) -> None:
        self.tracker = PatternTracker(
            pattern_expiry_hours=4, max_patterns_per_type=2
        )

    def test_add_and_get_high_pattern(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("high", 2055.0, 100.0, now)
        inval = self.tracker.get_invalidation_pattern("high")
        assert inval is not None
        assert inval["value"] == 2055.0

    def test_deduplication_against_traded(self) -> None:
        now = datetime.now()
        assert self.tracker.add_pattern("low", 2040.0, -50.0, now)
        p = self.tracker.get_invalidation_pattern("low")
        assert p is not None
        self.tracker.mark_pattern_traded(p)
        assert not self.tracker.add_pattern("low", 2040.0, -50.0, now)

    def test_max_patterns_per_type(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("high", 2050.0, 100.0, now)
        self.tracker.add_pattern("high", 2060.0, 120.0, now + timedelta(minutes=1))
        self.tracker.add_pattern("high", 2070.0, 140.0, now + timedelta(minutes=2))
        assert len(self.tracker.active_high_patterns) == 2
        # The oldest (2050.0) should have been evicted
        values = [p["value"] for p in self.tracker.active_high_patterns]
        assert 2050.0 not in values

    def test_mark_traded_removes_pattern(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("high", 2055.0, 100.0, now)
        p = self.tracker.get_invalidation_pattern("high")
        assert p is not None
        self.tracker.mark_pattern_traded(p)
        assert len(self.tracker.active_high_patterns) == 0
        assert p["uid"] in self.tracker._traded_patterns

    def test_discard_pattern(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("low", 2040.0, -50.0, now)
        p = self.tracker.get_invalidation_pattern("low")
        assert p is not None
        self.tracker.discard_pattern(p)
        assert len(self.tracker.active_low_patterns) == 0

    def test_cleanup_expired(self) -> None:
        old = datetime.now() - timedelta(hours=5)
        recent = datetime.now()
        self.tracker.add_pattern("high", 2050.0, 100.0, old)
        self.tracker.add_pattern("high", 2060.0, 120.0, recent)
        self.tracker.cleanup_expired_patterns()
        assert len(self.tracker.active_high_patterns) == 1
        assert self.tracker.active_high_patterns[0]["value"] == 2060.0

    def test_invalidation_returns_highest_high(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("high", 2050.0, 100.0, now)
        self.tracker.add_pattern("high", 2070.0, 120.0, now + timedelta(minutes=1))
        inval = self.tracker.get_invalidation_pattern("high")
        assert inval["value"] == 2070.0

    def test_invalidation_returns_lowest_low(self) -> None:
        now = datetime.now()
        self.tracker.add_pattern("low", 2040.0, -50.0, now)
        self.tracker.add_pattern("low", 2020.0, -80.0, now + timedelta(minutes=1))
        inval = self.tracker.get_invalidation_pattern("low")
        assert inval["value"] == 2020.0

    def test_divergence_returns_newest(self) -> None:
        now = datetime.now()
        # Add in reverse order
        self.tracker.add_pattern("high", 2070.0, 120.0, now + timedelta(minutes=5))
        self.tracker.add_pattern("high", 2050.0, 100.0, now)
        div = self.tracker.get_divergence_pattern("high")
        assert div["value"] == 2070.0

    def test_empty_tracker_returns_none(self) -> None:
        assert self.tracker.get_invalidation_pattern("high") is None
        assert self.tracker.get_divergence_pattern("low") is None
