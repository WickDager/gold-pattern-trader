"""Tests for the TradingConfig module."""

from __future__ import annotations

import json
import os
import tempfile

from src.config import TradingConfig


class TestTradingConfig:
    def test_default_values(self) -> None:
        cfg = TradingConfig(config_file="nonexistent.json")
        assert cfg.get("pattern_expiry_hours") == 4
        assert cfg.get("max_reconnect_attempts") == 5
        assert cfg.get("symbol_override") == ""

    def test_set_and_get(self) -> None:
        cfg = TradingConfig(config_file="nonexistent.json")
        cfg.set("trading_start_hour", 6)
        assert cfg.get("trading_start_hour") == 6

    def test_get_with_default(self) -> None:
        cfg = TradingConfig(config_file="nonexistent.json")
        assert cfg.get("missing_key", "fallback") == "fallback"

    def test_get_missing_returns_none(self) -> None:
        cfg = TradingConfig(config_file="nonexistent.json")
        assert cfg.get("missing_key") is None

    def test_round_trip_persistence(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp = f.name

        try:
            cfg = TradingConfig(config_file=tmp)
            orig = cfg.get("data_refresh_seconds")
            cfg.set("data_refresh_seconds", 99)

            # Create a new instance reading the same file
            cfg2 = TradingConfig(config_file=tmp)
            assert cfg2.get("data_refresh_seconds") == 99
            cfg2.set("data_refresh_seconds", orig)  # restore
        finally:
            os.unlink(tmp)
