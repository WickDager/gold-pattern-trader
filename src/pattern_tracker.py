"""Thread-safe pattern tracking with expiry and deduplication.

The :class:`PatternTracker` maintains two lists of active patterns (swing-high
and swing-low).  Patterns expire after a configurable time window and are
deduplicated via a unique-identifier set to prevent re-trading the same signal.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class PatternTracker:
    """Track swing-high and swing-low patterns with thread-safe access.

    Parameters
    ----------
    pattern_expiry_hours:
        How long a pattern remains active before being eligible for cleanup.
    max_patterns_per_type:
        Maximum number of active patterns kept per type (high / low).  When
        the limit is exceeded the *oldest* pattern is evicted.
    logger:
        Optional external logger.  A module-level logger is used when omitted.
    """

    def __init__(
        self,
        pattern_expiry_hours: int = 4,
        max_patterns_per_type: int = 1,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._pattern_expiry = timedelta(hours=pattern_expiry_hours)
        self._max_per_type = max_patterns_per_type

        self.active_high_patterns: List[Dict] = []
        self.active_low_patterns: List[Dict] = []
        self._traded_patterns: set = set()
        self._lock = threading.RLock()
        self._log = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_pattern(
        self,
        pattern_type: str,
        value: float,
        delta: float,
        origin_time: datetime,
    ) -> bool:
        """Register a new pattern.

        Returns ``False`` when the pattern has already been traded (deduplicated).
        """
        with self._lock:
            uid = self._make_uid(pattern_type, value, origin_time)

            if uid in self._traded_patterns:
                self._log.info(
                    "Skipping already traded %s pattern", pattern_type.upper()
                )
                return False

            pattern: Dict = {
                "type": pattern_type,
                "value": value,
                "delta": delta,
                "origin_time": origin_time,
                "uid": uid,
            }

            target = (
                self.active_high_patterns
                if pattern_type == "high"
                else self.active_low_patterns
            )

            target.append(pattern)
            target.sort(key=lambda p: p["origin_time"])

            while len(target) > self._max_per_type:
                removed = target.pop(0)
                self._log.info(
                    "Replaced oldest %s pattern from %s",
                    pattern_type.upper(),
                    removed["origin_time"],
                )

            self._log.info(
                "NEW %s PATTERN: %s | Value: %.5f | Delta: %.2f | "
                "Active %s patterns: %d",
                pattern_type.upper(), origin_time, value, delta,
                pattern_type, len(target),
            )
            return True

    def get_invalidation_pattern(self, pattern_type: str) -> Optional[Dict]:
        """Return the pattern used for invalidation checks.

        For *high* patterns this is the *highest-value* active pattern; for
        *low* patterns it is the *lowest-value* active pattern.
        """
        with self._lock:
            if pattern_type == "high" and self.active_high_patterns:
                return max(self.active_high_patterns, key=lambda p: p["value"])
            if pattern_type == "low" and self.active_low_patterns:
                return min(self.active_low_patterns, key=lambda p: p["value"])
            return None

    def get_divergence_pattern(self, pattern_type: str) -> Optional[Dict]:
        """Return the *newest* active pattern for divergence checking."""
        with self._lock:
            if pattern_type == "high" and self.active_high_patterns:
                return max(self.active_high_patterns, key=lambda p: p["origin_time"])
            if pattern_type == "low" and self.active_low_patterns:
                return max(self.active_low_patterns, key=lambda p: p["origin_time"])
            return None

    def mark_pattern_traded(self, pattern: Dict) -> None:
        """Mark *pattern* as traded and remove it from the active list."""
        with self._lock:
            self._traded_patterns.add(pattern["uid"])

            target = (
                self.active_high_patterns
                if pattern["type"] == "high"
                else self.active_low_patterns
            )
            self._remove_from_list(target, pattern["uid"])
            self._log.info(
                "Pattern %s marked as traded and removed", pattern["type"].upper()
            )

    def discard_pattern(self, pattern: Dict) -> None:
        """Remove *pattern* from the active list without trading."""
        with self._lock:
            target = (
                self.active_high_patterns
                if pattern["type"] == "high"
                else self.active_low_patterns
            )
            self._remove_from_list(target, pattern["uid"])
            self._log.info(
                "Pattern %s discarded (no divergence)", pattern["type"].upper()
            )

    def cleanup_expired_patterns(self) -> None:
        """Remove patterns that have exceeded the expiry window."""
        with self._lock:
            now = datetime.now()
            before_high = len(self.active_high_patterns)
            before_low = len(self.active_low_patterns)
            before_traded = len(self._traded_patterns)

            self.active_high_patterns = [
                p for p in self.active_high_patterns
                if (now - p["origin_time"]) < self._pattern_expiry
            ]
            self.active_low_patterns = [
                p for p in self.active_low_patterns
                if (now - p["origin_time"]) < self._pattern_expiry
            ]

            removed_high = before_high - len(self.active_high_patterns)
            removed_low = before_low - len(self.active_low_patterns)
            removed_traded = before_traded - len(self._traded_patterns)

            if removed_high or removed_low or removed_traded:
                self._log.info(
                    "Cleaned %d high, %d low, %d traded patterns",
                    removed_high, removed_low, removed_traded,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_uid(pattern_type: str, value: float, origin_time: datetime) -> str:
        """Deterministic short hash used for deduplication."""
        raw = f"{pattern_type}-{value:.8f}-{origin_time.strftime('%Y%m%d_%H%M%S_%f')}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _remove_from_list(lst: List[Dict], uid: str) -> None:
        for i, p in enumerate(lst):
            if p["uid"] == uid:
                lst.pop(i)
                break
