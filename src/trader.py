"""Core XAUUSD live trading logic.

The :class:`XAUUSDLiveTrader` reads 1-minute bar data (exported by the
Sierra Chart study), tracks swing-high / swing-low patterns, and places
trades when pattern invalidation coincides with cumulative-delta divergence.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from .config import TradingConfig
from .connection_manager import ConnectionManager
from .data_validator import DataValidator
from .logger import TradingLogger
from .pattern_tracker import PatternTracker


class XAUUSDLiveTrader:
    """A single-account trader that runs in its own thread.

    Parameters
    ----------
    login:
        MT5 account number.
    password:
        MT5 account password.
    server:
        MT5 server name.
    risk_percentage:
        Percentage of equity risked per trade (0.01 – 10).
    tp_multiplier:
        Take-profit distance as a multiple of ADR.
    sl_multiplier:
        Stop-loss distance as a multiple of ADR.
    config:
        Shared configuration instance.
    """

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        risk_percentage: float = 0.1,
        tp_multiplier: float = 5.0,
        sl_multiplier: float = 1.0,
        config: Optional[TradingConfig] = None,
    ) -> None:
        self.config = config or TradingConfig()
        self._log = TradingLogger(self.config.get("log_file")).get_logger()

        # Account details
        self.login = login
        self.password = password
        self.server = server
        self.risk_percentage = risk_percentage
        self.tp_multiplier = tp_multiplier
        self.sl_multiplier = sl_multiplier

        # Connection
        self.connection_manager = ConnectionManager(
            login,
            password,
            server,
            self.config.get("max_reconnect_attempts", 5),
            self._log,
        )

        # Symbol resolved at runtime
        self.symbol: Optional[str] = None
        self.symbol_info: Optional[mt5.TerminalInfo] = None

        # Pattern tracking
        self.pattern_tracker = PatternTracker(
            pattern_expiry_hours=self.config.get("pattern_expiry_hours", 4),
            max_patterns_per_type=self.config.get("max_patterns_per_type", 1),
            logger=self._log,
        )

        # Unique magic number per instance
        self.magic_number = self._generate_magic_number(self.login)

        # Thread control
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Trade tracking for breakeven management
        self.active_trades: Dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the trading loop in a daemon thread."""
        if self.running:
            self._log.info("Trading already running for account %s", self.login)
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log.info("Started trading thread for account %s", self.login)

    def stop(self) -> None:
        """Signal the trading loop to stop and wait for the thread."""
        if not self.running:
            self._log.info("Trading not running for account %s", self.login)
            return
        self._log.info("Stopping trading for account %s...", self.login)
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                self._log.warning("Thread did not stop gracefully")
        self.connection_manager.disconnect()
        self._log.info("Trading stopped for account %s", self.login)

    def get_status(self) -> Dict:
        """Return a snapshot dict of the current trader state."""
        try:
            account_info = (
                mt5.account_info() if self.connection_manager.connected else None
            )
            with self.pattern_tracker._lock:
                return {
                    "login": self.login,
                    "running": self.running,
                    "connected": self.connection_manager.connected,
                    "symbol": self.symbol,
                    "risk_percentage": self.risk_percentage,
                    "tp_multiplier": self.tp_multiplier,
                    "sl_multiplier": self.sl_multiplier,
                    "breakeven_adr_multiplier": self.config.get(
                        "breakeven_adr_multiplier", 1.0
                    ),
                    "equity": account_info.equity if account_info else 0,
                    "balance": account_info.balance if account_info else 0,
                    "margin_free": account_info.margin_free if account_info else 0,
                    "high_patterns": len(self.pattern_tracker.active_high_patterns),
                    "low_patterns": len(self.pattern_tracker.active_low_patterns),
                    "traded_patterns": len(self.pattern_tracker._traded_patterns),
                    "active_trades": len(self.active_trades),
                    "magic_number": self.magic_number,
                }
        except Exception as exc:
            self._log.error("Error getting status: %s", exc)
            return {"login": self.login, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal: main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main trading loop (runs in a background thread)."""
        if not self._validate_input_parameters():
            self._log.error("Invalid trading parameters, cannot start")
            return

        if not self.connection_manager.connect():
            self._log.error("Failed to connect to MT5, cannot start trading")
            return

        self.symbol = self._find_available_symbol()
        if not self.symbol:
            all_symbols = mt5.symbols_get()
            if all_symbols:
                names = [s.name for s in all_symbols]
                self._log.info("Available symbols: %s", ", ".join(names))
            self._log.error("No available GOLD symbol found, cannot start trading")
            return

        self.symbol_info = mt5.symbol_info(self.symbol)
        if not self.symbol_info:
            self._log.error("Failed to get symbol info")
            return

        spread = (self.symbol_info.ask - self.symbol_info.bid) / self.symbol_info.point
        self._log.info(
            "Symbol settings: Point=%g  Digits=%d  TradeStopsLevel=%d  Spread=%.1fpts",
            self.symbol_info.point,
            self.symbol_info.digits,
            self.symbol_info.trade_stops_level,
            spread,
        )
        self._log.info(
            "Trading started  Account=%s  Symbol=%s  Risk=%.2f%%  "
            "TP=%.1fx  SL=%.1fx  Magic=%d  BreakevenADR=%.1fx",
            self.login,
            self.symbol,
            self.risk_percentage,
            self.tp_multiplier,
            self.sl_multiplier,
            self.magic_number,
            self.config.get("breakeven_adr_multiplier", 1.0),
        )

        # Timing trackers
        last_processed = datetime(1970, 1, 1)
        last_cleanup = datetime.now()
        last_data_load = datetime.now()
        last_status = datetime.now()
        last_conn_check = datetime.now()
        last_be_check = datetime.now()
        consecutive_errors = 0
        max_errors = 10
        initial_data_processed = False

        while self.running and not self._stop_event.is_set():
            try:
                now = datetime.now()

                # --- periodic connection check -------------------------------
                if (now - last_conn_check).seconds > self.config.get(
                    "connection_check_seconds", 60
                ):
                    if not self.connection_manager.ensure_connection():
                        self._log.error("Connection lost and could not reconnect")
                        time.sleep(5)
                        continue
                    last_conn_check = now

                # --- load data ------------------------------------------------
                if (now - last_data_load).seconds > self.config.get(
                    "data_refresh_seconds", 10
                ):
                    data = self._load_data()
                    last_data_load = now
                else:
                    data = self._load_data()

                if data is None or data.empty:
                    time.sleep(1)
                    continue

                # Trim to last 5 rows on first pass
                if not initial_data_processed:
                    if len(data) > 5:
                        data = data.iloc[-5:]
                    initial_data_processed = True

                latest = data.iloc[-1]
                if latest["datetime"] <= last_processed:
                    time.sleep(0.3)
                    continue

                last_processed = latest["datetime"]

                # --- periodic maintenance ------------------------------------
                if (now - last_cleanup).seconds > self.config.get(
                    "cleanup_interval_minutes", 30
                ) * 60:
                    self.pattern_tracker.cleanup_expired_patterns()
                    last_cleanup = now

                if (now - last_be_check).seconds > 30:
                    self._check_open_positions()
                    last_be_check = now

                # --- pattern registration ------------------------------------
                if latest["pattern_high"] > 0 and latest["pattern_type"] == 1:
                    self.pattern_tracker.add_pattern(
                        "high",
                        latest["pattern_high"],
                        latest["cumulative_delta"],
                        latest["datetime"] - timedelta(minutes=1),
                    )

                if latest["pattern_low"] > 0 and latest["pattern_type"] == -1:
                    self.pattern_tracker.add_pattern(
                        "low",
                        latest["pattern_low"],
                        latest["cumulative_delta"],
                        latest["datetime"] - timedelta(minutes=1),
                    )

                # --- invalidation & trade entry ------------------------------
                self._process_pattern_invalidation(
                    latest["high"],
                    latest["low"],
                    latest["cumulative_delta"],
                    latest["adr_value"],
                    latest["datetime"],
                )

                # --- periodic status -----------------------------------------
                if (now - last_status).seconds > self.config.get(
                    "status_update_minutes", 1
                ) * 60:
                    self._print_status(latest)
                    last_status = now

                consecutive_errors = 0
                time.sleep(0.5)

            except Exception as exc:
                consecutive_errors += 1
                self._log.error(
                    "Error in trading loop (#%d): %s\n%s",
                    consecutive_errors,
                    exc,
                    traceback.format_exc(),
                )
                if consecutive_errors >= max_errors:
                    self._log.critical("Too many consecutive errors, stopping trader")
                    break
                time.sleep(min(consecutive_errors * 2, 30))

        self._log.info("Trading loop ended for account %s", self.login)
        self.connection_manager.disconnect()

    # ------------------------------------------------------------------
    # Symbol discovery
    # ------------------------------------------------------------------

    def _find_available_symbol(self) -> Optional[str]:
        """Return the first tradeable XAUUSD symbol found on the terminal."""
        override = self.config.get("symbol_override", "")
        if override and override.strip():
            self._log.info("Trying configured symbol override: %s", override)
            if self._validate_symbol(override):
                return override

        for sym in self.config.get("symbol_variations", ["XAUUSD"]):
            if self._validate_symbol(sym):
                return sym

        self._log.warning("No symbol in predefined list; searching with wildcards...")
        return self._find_symbol_with_wildcards()

    def _validate_symbol(self, symbol: str) -> bool:
        """Check whether *symbol* exists and is tradeable."""
        try:
            info = mt5.symbol_info(symbol)
            if info:
                if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                    self._log.warning("Symbol %s not in full trading mode", symbol)
                    return False
                if not info.visible:
                    if not mt5.symbol_select(symbol, True):
                        self._log.warning("Could not enable symbol %s", symbol)
                        return False
                self._log.info("Found existing symbol: %s", symbol)
                return True

            if mt5.symbol_select(symbol, True):
                info = mt5.symbol_info(symbol)
                if info and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                    self._log.info("Selected symbol: %s", symbol)
                    return True
            return False
        except Exception as exc:
            self._log.error("Error checking symbol %s: %s", symbol, exc)
            return False

    def _find_symbol_with_wildcards(self) -> Optional[str]:
        """Fallback: scan MT5 symbol list with glob patterns."""
        patterns = [
            "*GOLD*", "*XAU*", "*XAU/USD*", "*GOLD/USD*",
            "*GOLD_micro*", "*XAUUSD*",
        ]
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            self._log.error("Failed to get symbols list from MT5")
            return None

        self._log.info("Scanning %d symbols for GOLD pairs...", len(all_symbols))
        for pat in patterns:
            for info in all_symbols:
                import fnmatch
                if fnmatch.fnmatch(info.name, pat):
                    self._log.info("Pattern '%s' matched: %s", pat, info.name)
                    if info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                        if mt5.symbol_select(info.name, True):
                            self._log.info("Using discovered symbol: %s", info.name)
                            return info.name
        return None

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> Optional[pd.DataFrame]:
        """Load and validate the latest CSV export."""
        try:
            path = self.config.get("data_file_path")
            df = pd.read_csv(path, parse_dates=["datetime"])
            if df.empty:
                return None
            df = DataValidator.validate_dataframe(df)
            df = df.drop_duplicates("datetime", keep="last")
            df = df.sort_values("datetime")
            return df
        except Exception as exc:
            self._log.error("Error loading data: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input_parameters(self) -> bool:
        if not (0.01 <= self.risk_percentage <= 10):
            self._log.error("Invalid risk percentage: %s", self.risk_percentage)
            return False
        if not (0 < self.tp_multiplier <= 20):
            self._log.error("Invalid TP multiplier: %s", self.tp_multiplier)
            return False
        if not (0 < self.sl_multiplier <= 10):
            self._log.error("Invalid SL multiplier: %s", self.sl_multiplier)
            return False
        return True

    @staticmethod
    def _generate_magic_number(login: int) -> int:
        raw = f"{login}-{datetime.now().timestamp()}"
        return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16) % 1_000_000

    # ------------------------------------------------------------------
    # Trading helpers
    # ------------------------------------------------------------------

    def _is_trading_time(self, ts: datetime) -> bool:
        if ts.weekday() >= 5:  # weekend
            return False
        start = self.config.get("trading_start_hour", 3)
        end = self.config.get("trading_end_hour", 18)
        return start <= ts.hour < end

    def _round_price(self, price: float) -> float:
        if not self.symbol_info:
            return price
        pt = self.symbol_info.point
        digits = 3 if pt == 0.001 else (2 if pt >= 1 else abs(int(np.log10(pt))))
        return round(price, digits)

    def _calculate_lot_size(self, adr_value: float) -> float:
        """Compute position size based on account equity and ADR risk."""
        try:
            if not self.connection_manager.ensure_connection():
                return 0.0

            account_info = mt5.account_info()
            if not account_info:
                self._log.error("Failed to get account info")
                return 0.0

            min_equity = self.config.get("min_equity", 100)
            if account_info.equity < min_equity:
                self._log.error(
                    "Insufficient equity: $%.2f < $%.2f",
                    account_info.equity, min_equity,
                )
                return 0.0

            if not self.symbol_info:
                self._log.error("Symbol info not available")
                return 0.0

            equity = account_info.equity
            risk_amount = equity * (self.risk_percentage / 100)

            ticks_in_adr = adr_value / self.symbol_info.trade_tick_size
            risk_per_lot = ticks_in_adr * self.symbol_info.trade_tick_value
            if risk_per_lot <= 0:
                self._log.error("Invalid risk per lot calculation")
                return 0.0

            lots = risk_amount / risk_per_lot
            lots = max(
                self.symbol_info.volume_min,
                min(self.symbol_info.volume_max, lots),
            )
            lots = round(lots / self.symbol_info.volume_step) * self.symbol_info.volume_step

            self._log.info(
                "Lot size: Equity=%.2f  Risk=%.2f%%  ADR=%.5f  Lots=%.2f",
                equity, self.risk_percentage, adr_value, lots,
            )
            return lots
        except Exception as exc:
            self._log.error("Lot size calculation error: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Trade placement
    # ------------------------------------------------------------------

    def _place_trade(
        self, trade_type: str, adr_value: float, current_ts: datetime
    ) -> bool:
        """Place a BUY or SELL market order with retries.

        Returns ``True`` on successful fill.
        """
        for attempt in range(3):
            try:
                if not self._is_trading_time(current_ts):
                    self._log.warning("Trade blocked: outside trading hours")
                    return False
                if not self.connection_manager.ensure_connection():
                    return False
                if not self.symbol_info:
                    self._log.error("Symbol info not available")
                    return False

                tick = mt5.symbol_info_tick(self.symbol)
                if not tick:
                    self._log.error("Failed to get tick")
                    time.sleep(1)
                    continue

                # spread check
                max_spread = self.config.get("max_spread_points", 50)
                spread_pts = (tick.ask - tick.bid) / self.symbol_info.point
                if spread_pts > max_spread:
                    self._log.warning(
                        "Spread too wide: %.1f > %d", spread_pts, max_spread
                    )
                    time.sleep(1)
                    continue

                price = tick.ask if trade_type == "BUY" else tick.bid
                price = self._round_price(price)
                if price <= 0:
                    self._log.error("Invalid price: %s", price)
                    return False

                lots = self._calculate_lot_size(adr_value)
                if lots <= 0:
                    self._log.error("Invalid lot size, trade cancelled")
                    return False

                sl_dist = adr_value * self.sl_multiplier
                tp_dist = adr_value * self.tp_multiplier

                if trade_type == "BUY":
                    sl_price = self._round_price(price - sl_dist)
                    tp_price = self._round_price(price + tp_dist)
                    order_type = mt5.ORDER_TYPE_BUY
                else:
                    sl_price = self._round_price(price + sl_dist)
                    tp_price = self._round_price(price - tp_dist)
                    order_type = mt5.ORDER_TYPE_SELL

                # Validate SL direction
                if (trade_type == "BUY" and sl_price >= price) or \
                   (trade_type == "SELL" and sl_price <= price):
                    self._log.error(
                        "Invalid SL: SL=%s, Price=%s", sl_price, price
                    )
                    return False

                # Broker stop-level enforcement
                stops_level = self.symbol_info.trade_stops_level
                if stops_level > 0:
                    min_dist = self.symbol_info.point * stops_level
                    if trade_type == "BUY":
                        if sl_price > price - min_dist:
                            sl_price = price - min_dist
                        if tp_price < price + min_dist:
                            tp_price = price + min_dist
                    else:
                        if sl_price < price + min_dist:
                            sl_price = price + min_dist
                        if tp_price > price - min_dist:
                            tp_price = price - min_dist

                # Margin check
                margin = mt5.order_calc_margin(order_type, self.symbol, lots, price)
                if margin is None:
                    self._log.error("Failed to calculate margin")
                    time.sleep(1)
                    continue

                account_info = mt5.account_info()
                if account_info.margin_free < margin:
                    self._log.error(
                        "Insufficient margin: free=%.2f, required=%.2f",
                        account_info.margin_free, margin,
                    )
                    return False

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": lots,
                    "type": order_type,
                    "price": price,
                    "sl": sl_price,
                    "tp": tp_price,
                    "deviation": 20,
                    "magic": self.magic_number,
                    "comment": (
                        f"Risk:{self.risk_percentage}%|"
                        f"TPx{self.tp_multiplier}|"
                        f"SLx{self.sl_multiplier}|"
                        f"ADR:{adr_value:.5f}"
                    ),
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_FOK,
                }

                self._log.info(
                    "Placing %s: price=%.5f  SL=%.5f (%.1fx)  TP=%.5f (%.1fx)  lots=%.2f",
                    trade_type, price, sl_price, self.sl_multiplier,
                    tp_price, self.tp_multiplier, lots,
                )

                result = mt5.order_send(request)
                if result is None:
                    self._log.error(
                        "Trade attempt %d failed: %s",
                        attempt + 1, mt5.last_error(),
                    )
                    time.sleep(1)
                    continue

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.active_trades[result.order] = {
                        "entry_price": price,
                        "adr_value": adr_value,
                        "trade_type": trade_type,
                        "sl_moved_to_breakeven": False,
                    }
                    self._log.info("Trade successful: %s at %.5f", trade_type, price)
                    return True

                if result.retcode in (
                    mt5.TRADE_RETCODE_REQUOTE,
                    mt5.TRADE_RETCODE_PRICE_CHANGED,
                ):
                    self._log.warning(
                        "Price changed (attempt %d), retrying...", attempt + 1
                    )
                    time.sleep(0.5)
                    continue

                self._log.error(
                    "Trade attempt %d failed: %s",
                    attempt + 1,
                    result.comment,
                )
                return False

            except Exception as exc:
                self._log.error(
                    "Error placing trade (attempt %d): %s\n%s",
                    attempt + 1, exc, traceback.format_exc(),
                )
                time.sleep(1)

        return False

    # ------------------------------------------------------------------
    # Breakeven management
    # ------------------------------------------------------------------

    def _move_to_breakeven(self, position, adr_value: float) -> bool:
        """Move SL to entry price when profit >= ADR * multiplier."""
        try:
            tick = mt5.symbol_info_tick(self.symbol)
            if not tick:
                return False

            be_mult = self.config.get("breakeven_adr_multiplier", 1.0)
            required_profit = adr_value * be_mult

            if position.type == mt5.ORDER_TYPE_BUY:
                profit = tick.bid - position.price_open
                if profit >= required_profit and position.sl < position.price_open:
                    return self._modify_position(position, position.price_open)
            elif position.type == mt5.ORDER_TYPE_SELL:
                profit = position.price_open - tick.ask
                if profit >= required_profit and position.sl > position.price_open:
                    return self._modify_position(position, position.price_open)
            return False
        except Exception as exc:
            self._log.error("Error moving to breakeven: %s", exc)
            return False

    def _modify_position(self, position, new_sl: float) -> bool:
        """Update an open position's stop loss."""
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": self.symbol,
            "sl": new_sl,
            "tp": position.tp,
            "deviation": 20,
            "magic": self.magic_number,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            self._log.error("Failed to move SL to breakeven: %s",
                            result.comment if result else mt5.last_error())
            return False

        if position.ticket in self.active_trades:
            self.active_trades[position.ticket]["sl_moved_to_breakeven"] = True
        self._log.info(
            "Moved SL to breakeven for position %d at %.5f",
            position.ticket, new_sl,
        )
        return True

    def _check_open_positions(self) -> None:
        """Scan open positions and move SL to breakeven where eligible."""
        if not self.connection_manager.ensure_connection():
            return
        positions = mt5.positions_get(symbol=self.symbol, magic=self.magic_number)
        if positions is None:
            self._log.error("Failed to get open positions")
            return
        if not positions:
            return

        for pos in positions:
            t = pos.ticket
            if t in self.active_trades and self.active_trades[t].get("sl_moved_to_breakeven"):
                continue

            # Extract ADR from the order comment
            adr_value: Optional[float] = None
            for part in pos.comment.split("|"):
                if part.startswith("ADR:"):
                    try:
                        adr_value = float(part[4:])
                        break
                    except ValueError:
                        pass

            if adr_value is None and t in self.active_trades:
                adr_value = self.active_trades[t].get("adr_value")
            if adr_value is not None:
                self._move_to_breakeven(pos, adr_value)

    # ------------------------------------------------------------------
    # Pattern invalidation & divergence
    # ------------------------------------------------------------------

    def _check_divergence(self, pattern: Dict, current_delta: float) -> bool:
        """Return ``True`` if cumulative-delta divergence is detected."""
        pat_delta = pattern["delta"]
        tol = self.config.get("divergence_tolerance", 4)

        if pattern["type"] == "high":
            threshold = pat_delta + tol
            result = current_delta < threshold
            self._log.info(
                "BEARISH DIV: pattern=%.2f  current=%.2f  threshold=%.2f -> %s",
                pat_delta, current_delta, threshold,
                "YES" if result else "NO",
            )
            return result
        else:
            threshold = pat_delta - tol
            result = current_delta > threshold
            self._log.info(
                "BULLISH DIV: pattern=%.2f  current=%.2f  threshold=%.2f -> %s",
                pat_delta, current_delta, threshold,
                "YES" if result else "NO",
            )
            return result

    def _process_pattern_invalidation(
        self,
        current_high: float,
        current_low: float,
        current_delta: float,
        adr_value: float,
        current_ts: datetime,
    ) -> bool:
        """Evaluate pattern invalidation and place trades if divergence exists."""
        try:
            # ---- HIGH invalidation ----
            ip_high = self.pattern_tracker.get_invalidation_pattern("high")
            if ip_high and current_high > ip_high["value"]:
                self._log.info(
                    "HIGH PATTERN INVALIDATED  value=%.5f  current_high=%.5f",
                    ip_high["value"], current_high,
                )
                dp_high = self.pattern_tracker.get_divergence_pattern("high")
                if dp_high and self._check_divergence(dp_high, current_delta):
                    self._log.info("SELL SIGNAL: bearish divergence confirmed")
                    if self._place_trade("SELL", adr_value, current_ts):
                        self.pattern_tracker.mark_pattern_traded(dp_high)
                        if dp_high["uid"] != ip_high["uid"]:
                            self.pattern_tracker.discard_pattern(ip_high)
                        return True
                elif dp_high:
                    self._log.info("No bearish divergence — discarding high patterns")
                    self.pattern_tracker.discard_pattern(dp_high)
                    if dp_high["uid"] != ip_high["uid"]:
                        self.pattern_tracker.discard_pattern(ip_high)
                    return True

            # ---- LOW invalidation ----
            ip_low = self.pattern_tracker.get_invalidation_pattern("low")
            if ip_low and current_low < ip_low["value"]:
                self._log.info(
                    "LOW PATTERN INVALIDATED  value=%.5f  current_low=%.5f",
                    ip_low["value"], current_low,
                )
                dp_low = self.pattern_tracker.get_divergence_pattern("low")
                if dp_low and self._check_divergence(dp_low, current_delta):
                    self._log.info("BUY SIGNAL: bullish divergence confirmed")
                    if self._place_trade("BUY", adr_value, current_ts):
                        self.pattern_tracker.mark_pattern_traded(dp_low)
                        if dp_low["uid"] != ip_low["uid"]:
                            self.pattern_tracker.discard_pattern(ip_low)
                        return True
                elif dp_low:
                    self._log.info("No bullish divergence — discarding low patterns")
                    self.pattern_tracker.discard_pattern(dp_low)
                    if dp_low["uid"] != ip_low["uid"]:
                        self.pattern_tracker.discard_pattern(ip_low)
                    return True

            return False

        except Exception as exc:
            self._log.error("Error processing invalidation: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _print_status(self, latest_bar: pd.Series) -> None:
        """Log a formatted status snapshot."""
        try:
            info = mt5.account_info()
            lines = [
                "\n" + "=" * 60,
                f"STATUS: {datetime.now():%Y-%m-%d %H:%M:%S}",
                f"Account: {self.login}  Symbol: {self.symbol}",
                f"Last bar: {latest_bar['datetime']:%H:%M:%S}  "
                f"H={latest_bar['high']:.5f}  L={latest_bar['low']:.5f}",
                f"Trading hours: {'ACTIVE' if self._is_trading_time(latest_bar['datetime']) else 'INACTIVE'}",
                f"Risk: {self.risk_percentage}%  TP: {self.tp_multiplier}x  "
                f"SL: {self.sl_multiplier}x",
            ]
            if info:
                lines.append(
                    f"Equity: {info.equity:.2f}  Balance: {info.balance:.2f}  "
                    f"Free margin: {info.margin_free:.2f}"
                )

            with self.pattern_tracker._lock:
                hp = self.pattern_tracker.active_high_patterns
                lp = self.pattern_tracker.active_low_patterns
                traded = len(self.pattern_tracker._traded_patterns)

            lines.append(f"Active high patterns: {len(hp)}  low: {len(lp)}  "
                         f"traded: {traded}")
            lines.append(f"Active trades: {len(self.active_trades)}")
            lines.append("=" * 60)

            self._log.info("\n".join(lines))
        except Exception as exc:
            self._log.error("Error printing status: %s", exc)
