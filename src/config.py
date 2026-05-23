"""Configuration management with JSON persistence."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "data_file_path": "C:/trading_bot/Live_Gold_Data.csv",
    "log_file": "trading_bot.log",
    "pattern_expiry_hours": 4,
    "max_patterns_per_type": 1,
    "divergence_tolerance": 4,
    "trading_start_hour": 3,
    "trading_end_hour": 18,
    "data_refresh_seconds": 10,
    "cleanup_interval_minutes": 30,
    "status_update_minutes": 1,
    "connection_check_seconds": 60,
    "max_reconnect_attempts": 5,
    "min_equity": 100,
    "symbol_variations": [
        "XAUUSD", "GOLD", "GOLD.", "XAU/USD", "XAUUSD.", "XAUUSDC",
        "XAUUSD.c", "XAUUSD.raw", "XAUUSD-", "XAUUSD#", "XAUUSD.a",
        "XAUUSD.e", "XAUUSD.m", "XAUUSD.i", "XAUUSDX", "XAUUSD.std",
        "XAUUSD.ecn", "XAUUSD.pro", "XAUUSD-Z", "XAUUSD-z", "XAUUSD!",
        "XAUUSD_", "XAUUSD.mini", "XAUUSD.n", "XAUUSD+", "XAUUSD_USD",
        "XAUUSD.sx", "XAUUSD.lmx", "XAUUSD.bbo", "XAUUSD1", "XAUUSD.opt",
        "XAUUSDT", "XAUUSD...", "XAUUSD?",
    ],
    "breakeven_adr_multiplier": 1.0,
    "max_spread_points": 50,
    "symbol_override": "",
}


class TradingConfig:
    """Loads, persists and provides access to trading configuration.

    On instantiation the class reads *config_file* from disk, merging any
    user-supplied values with the built-in defaults.  Missing files are
    created automatically with default values.
    """

    def __init__(self, config_file: str = "trading_config.json") -> None:
        self.config_file = config_file
        self.config: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configuration value (or *default* when the key is missing)."""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Assign *value* to *key* and persist to disk immediately."""
        self.config[key] = value
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    self.config = {**DEFAULT_CONFIG, **loaded}
            else:
                self._save()
        except Exception as exc:
            print(f"Error loading config, using defaults: {exc}")
            self.config = DEFAULT_CONFIG.copy()

    def _save(self) -> None:
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as exc:
            print(f"Error saving config: {exc}")
