"""Multi-account trading manager with interactive CLI menu."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, Optional

from .account_manager import AccountManager
from .config import TradingConfig
from .connection_manager import ConnectionManager
from .logger import TradingLogger
from .trader import XAUUSDLiveTrader


class TradingManager:
    """Manages multiple :class:`XAUUSDLiveTrader` instances and provides
    an interactive console menu for account management."""

    def __init__(self) -> None:
        self.config = TradingConfig()
        self._log = TradingLogger(self.config.get("log_file")).get_logger()
        self.traders: Dict[str, XAUUSDLiveTrader] = {}
        self.live_views: Dict[str, bool] = {}
        self.account_manager = AccountManager()
        self._load_stored_accounts()

    # ------------------------------------------------------------------
    # Account loading
    # ------------------------------------------------------------------

    def _load_stored_accounts(self) -> None:
        accounts = self.account_manager.get_all_accounts()
        for login, details in accounts.items():
            try:
                trader = XAUUSDLiveTrader(
                    login=int(login),
                    password=details["password"],
                    server=details["server"],
                    risk_percentage=details["risk_percentage"],
                    tp_multiplier=details["tp_multiplier"],
                    sl_multiplier=details.get("sl_multiplier", 1.0),
                    config=self.config,
                )
                self.traders[login] = trader
                self._log.info("Loaded account %s from storage", login)
            except Exception as exc:
                self._log.error(
                    "Error loading account %s: %s", login, exc
                )

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_credentials(login: str, password: str, server: str) -> bool:
        """Basic sanity check for MT5 credentials."""
        try:
            return int(login) > 0 and len(password) >= 1 and len(server) >= 1
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def add_account(self, save_to_file: bool = True) -> Optional[XAUUSDLiveTrader]:
        """Interactively add a new trading account."""
        print("\n" + "=" * 50)
        print("ADD NEW TRADING ACCOUNT")
        print("=" * 50)

        try:
            login = input("MT5 Login: ").strip()
            password = input("MT5 Password: ").strip()
            server = input("MT5 Server: ").strip()

            if not self.validate_credentials(login, password, server):
                print("Invalid credentials")
                return None

            risk = self._prompt_float("Risk percentage (0.01-5.0)", 0.1, 0.01, 5.0)
            tp = self._prompt_float("TP multiplier (1-20)", 5.0, 1.0, 20.0)
            sl = self._prompt_float("SL multiplier (0.5-10)", 1.0, 0.5, 10.0)
            be = self._prompt_float(
                "Breakeven ADR multiplier (0.5-3.0)", 1.0, 0.5, 3.0
            )

            print("Testing connection...")
            test = ConnectionManager(int(login), password, server, logger=self._log)
            if not test.connect():
                print("Failed to connect to MT5 with these credentials")
                test.disconnect()
                return None
            test.disconnect()
            print("Connection test successful")

            trader = XAUUSDLiveTrader(
                login=int(login),
                password=password,
                server=server,
                risk_percentage=risk,
                tp_multiplier=tp,
                sl_multiplier=sl,
                config=self.config,
            )
            self.config.set("breakeven_adr_multiplier", be)
            self.traders[login] = trader

            if save_to_file:
                self.account_manager.add_account(
                    login, password, server, risk, tp, sl
                )

            print(f"Account {login} added  "
                  f"Risk={risk}%  TP={tp}x  SL={sl}x  Breakeven={be}x")
            return trader

        except KeyboardInterrupt:
            print("\nCancelled")
            return None
        except Exception as exc:
            print(f"Error adding account: {exc}")
            self._log.error("Error adding account: %s", exc)
            return None

    def edit_account(self, login: str) -> None:
        """Interactively edit an existing account."""
        if login not in self.traders:
            print(f"Account {login} not found")
            return
        if self.traders[login].running:
            print("Stop trading before editing this account")
            return

        info = self.account_manager.get_account(login)
        if not info:
            print("Account not found in storage")
            return

        print(f"\nEDIT ACCOUNT: {login}")
        print("Leave blank to keep current value")

        pw = input(f"Password [{info['password']}]: ").strip()
        sv = input(f"Server [{info['server']}]: ").strip()

        risk = self._prompt_float(
            f"Risk percentage [{info['risk_percentage']}]",
            info["risk_percentage"], 0.01, 5.0,
            allow_blank=True,
        )
        tp = self._prompt_float(
            f"TP multiplier [{info['tp_multiplier']}]",
            info["tp_multiplier"], 1.0, 20.0,
            allow_blank=True,
        )
        sl = self._prompt_float(
            f"SL multiplier [{info.get('sl_multiplier', 1.0)}]",
            info.get("sl_multiplier", 1.0), 0.5, 10.0,
            allow_blank=True,
        )
        be = self._prompt_float(
            f"Breakeven ADR [{self.config.get('breakeven_adr_multiplier', 1.0)}]",
            self.config.get("breakeven_adr_multiplier", 1.0),
            0.5, 3.0, allow_blank=True,
        )

        updated = False
        if pw:
            info["password"] = pw
            updated = True
        if sv:
            info["server"] = sv
            updated = True

        if risk != info["risk_percentage"]:
            info["risk_percentage"] = risk
            self.traders[login].risk_percentage = risk
            updated = True
        if tp != info["tp_multiplier"]:
            info["tp_multiplier"] = tp
            self.traders[login].tp_multiplier = tp
            updated = True
        if sl != info.get("sl_multiplier", 1.0):
            info["sl_multiplier"] = sl
            self.traders[login].sl_multiplier = sl
            updated = True

        if be != self.config.get("breakeven_adr_multiplier", 1.0):
            self.config.set("breakeven_adr_multiplier", be)
            updated = True

        if updated:
            self.account_manager.update_account(login, **info)
            print("Account updated")
        else:
            print("No changes made")

    def remove_account(self, login: str) -> None:
        """Remove an account from the manager and storage."""
        if login not in self.traders:
            print(f"Account {login} not found")
            return
        self.stop_trading(login)
        del self.traders[login]
        self.live_views.pop(login, None)
        self.account_manager.remove_account(login)
        print(f"Removed account {login}")

    # ------------------------------------------------------------------
    # Trading control
    # ------------------------------------------------------------------

    def start_trading(self, login: str) -> None:
        """Start the trading thread for *login*."""
        if login not in self.traders:
            print(f"Account {login} not found")
            return
        try:
            self.traders[login].start()
            print(f"Started trading for account {login}")
        except Exception as exc:
            print(f"Error: {exc}")
            self._log.error("Error starting %s: %s", login, exc)

    def stop_trading(self, login: str) -> None:
        """Stop the trading thread for *login*."""
        if login not in self.traders:
            print(f"Account {login} not found")
            return
        try:
            self.traders[login].stop()
            print(f"Stopped trading for account {login}")
        except Exception as exc:
            print(f"Error: {exc}")
            self._log.error("Error stopping %s: %s", login, exc)

    # ------------------------------------------------------------------
    # Live view
    # ------------------------------------------------------------------

    def view_live_status(self, login: str) -> None:
        """Display a continuously updating status dashboard."""
        if login not in self.traders:
            print(f"Account {login} not found")
            return
        trader = self.traders[login]
        if not trader.running:
            print(f"Account {login} is not trading")
            return

        print(f"Live view for {login} (press 'q' to exit)")
        self.live_views[login] = True

        try:
            while self.live_views.get(login, False):
                status = trader.get_status()
                os.system("cls" if os.name == "nt" else "clear")
                print("\n" + "=" * 70)
                print(f"LIVE: {login}  {datetime.now():%Y-%m-%d %H:%M:%S}")
                print("=" * 70)
                print(
                    f"Connection: {'CONNECTED' if status.get('connected') else 'DISCONNECTED'}  "
                    f"Trading: {'ACTIVE' if status.get('running') else 'STOPPED'}"
                )
                print(
                    f"Equity: ${status.get('equity', 0):.2f}  "
                    f"Balance: ${status.get('balance', 0):.2f}  "
                    f"Free: ${status.get('margin_free', 0):.2f}"
                )
                print(f"Symbol: {status.get('symbol', 'N/A')}")
                print(
                    f"Risk: {status.get('risk_percentage', 0):.2f}%  "
                    f"TP: {status.get('tp_multiplier', 0):.1f}x  "
                    f"SL: {status.get('sl_multiplier', 1.0):.1f}x  "
                    f"Breakeven ADR: {status.get('breakeven_adr_multiplier', 1.0):.1f}x"
                )
                print(f"Magic: {status.get('magic_number', 'N/A')}")
                print(f"\nPatterns — High: {status.get('high_patterns', 0)}  "
                      f"Low: {status.get('low_patterns', 0)}  "
                      f"Traded: {status.get('traded_patterns', 0)}  "
                      f"Active trades: {status.get('active_trades', 0)}")
                print("\n" + "-" * 70)
                print("Press 'q' to exit  |  refreshes every 3 s")
                print("-" * 70)

                if os.name == "nt":
                    import msvcrt
                    if msvcrt.kbhit() and msvcrt.getch() in (b"q", b"Q"):
                        break
                time.sleep(3)
        except KeyboardInterrupt:
            pass
        finally:
            self.live_views.pop(login, None)
            print(f"\nExited live view for {login}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def show_accounts_summary(self) -> None:
        """Print a summary of all loaded accounts."""
        if not self.traders:
            print("No accounts configured")
            return

        print("\n" + "=" * 80)
        print("ACCOUNTS SUMMARY")
        print("=" * 80)

        for login, trader in self.traders.items():
            try:
                s = trader.get_status()
                conn = "CONNECTED" if s.get("connected") else "DISCONNECTED"
                tr = "RUNNING" if s.get("running") else "STOPPED"
                print(
                    f"\n{login}  {conn} / {tr}\n"
                    f"  Equity: ${s.get('equity', 0):.2f}  "
                    f"Free: ${s.get('margin_free', 0):.2f}\n"
                    f"  Risk: {s.get('risk_percentage', 0):.2f}%  "
                    f"TP: {s.get('tp_multiplier', 0):.1f}x  "
                    f"SL: {s.get('sl_multiplier', 1.0):.1f}x\n"
                    f"  Patterns: H={s.get('high_patterns', 0)}  "
                    f"L={s.get('low_patterns', 0)}  "
                    f"T={s.get('traded_patterns', 0)}  "
                    f"Trades: {s.get('active_trades', 0)}"
                )
            except Exception as exc:
                print(f"{login}: error — {exc}")

        print("=" * 80)

    # ------------------------------------------------------------------
    # Configuration menu
    # ------------------------------------------------------------------

    def show_config_menu(self) -> None:
        """Configuration sub-menu."""
        while True:
            print("\n" + "=" * 40)
            print("CONFIGURATION SETTINGS")
            print("=" * 40)
            print("1. View current settings")
            print("2. Edit data file path")
            print("3. Edit trading hours")
            print("4. Edit pattern settings")
            print("5. Edit breakeven settings")
            print("6. Edit spread settings")
            print("7. Edit symbol override")
            print("8. Back to main menu")

            choice = input("Select (1-8): ").strip()
            actions = {
                "1": self._show_config,
                "2": self._edit_data_path,
                "3": self._edit_trading_hours,
                "4": self._edit_pattern_settings,
                "5": self._edit_breakeven_settings,
                "6": self._edit_spread_settings,
                "7": self._edit_symbol_override,
                "8": None,
            }
            fn = actions.get(choice)
            if fn is None:
                if choice == "8":
                    break
                print("Invalid option")
            else:
                fn()

    def _show_config(self) -> None:
        print("\nCURRENT CONFIGURATION:")
        print("-" * 40)
        for key, value in self.config.config.items():
            if key == "symbol_variations":
                print(f"{key}: {len(value)} symbols")
            else:
                print(f"{key}: {value}")

    def _edit_data_path(self) -> None:
        current = self.config.get("data_file_path")
        print(f"Current: {current}")
        new = input("New path (Enter to keep): ").strip()
        if new:
            if os.path.exists(new) or input("Path not found. Use anyway? (y/N): ").lower() == "y":
                self.config.set("data_file_path", new)
                print("Updated")

    def _edit_trading_hours(self) -> None:
        start = self.config.get("trading_start_hour", 3)
        end = self.config.get("trading_end_hour", 18)
        print(f"Current hours: {start}:00 - {end}:00")
        try:
            s = input(f"Start hour [{start}]: ").strip()
            if s:
                self.config.set("trading_start_hour", int(s))
            e = input(f"End hour [{end}]: ").strip()
            if e:
                self.config.set("trading_end_hour", int(e))
            print("Updated")
        except ValueError:
            print("Invalid hour")

    def _edit_pattern_settings(self) -> None:
        print(f"Expiry: {self.config.get('pattern_expiry_hours', 4)}h  "
              f"Max/type: {self.config.get('max_patterns_per_type', 1)}  "
              f"Div tolerance: {self.config.get('divergence_tolerance', 4)}")
        try:
            v = input(f"Expiry hours [{self.config.get('pattern_expiry_hours', 4)}]: ").strip()
            if v:
                self.config.set("pattern_expiry_hours", float(v))
            v = input(f"Max patterns/type [{self.config.get('max_patterns_per_type', 1)}]: ").strip()
            if v:
                self.config.set("max_patterns_per_type", int(v))
            v = input(f"Divergence tolerance [{self.config.get('divergence_tolerance', 4)}]: ").strip()
            if v:
                self.config.set("divergence_tolerance", float(v))
            print("Updated")
        except ValueError:
            print("Invalid value")

    def _edit_breakeven_settings(self) -> None:
        v = self.config.get("breakeven_adr_multiplier", 1.0)
        print(f"Current ADR multiplier: {v}")
        try:
            new = input(f"New multiplier (0.5-3.0) [{v}]: ").strip()
            if new and 0.5 <= (x := float(new)) <= 3.0:
                self.config.set("breakeven_adr_multiplier", x)
                print("Updated")
            elif new:
                print("Must be 0.5-3.0")
        except ValueError:
            print("Invalid")

    def _edit_spread_settings(self) -> None:
        v = self.config.get("max_spread_points", 50)
        print(f"Current max spread: {v} pts")
        try:
            new = input(f"Max spread (10-200) [{v}]: ").strip()
            if new and 10 <= (x := int(new)) <= 200:
                self.config.set("max_spread_points", x)
                print("Updated")
            elif new:
                print("Must be 10-200")
        except ValueError:
            print("Invalid")

    def _edit_symbol_override(self) -> None:
        cur = self.config.get("symbol_override", "")
        print(f"Current: {cur or '(none)'}")
        new = input("New symbol (blank to clear): ").strip()
        self.config.set("symbol_override", new)
        print("Updated")

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------

    def show_menu(self) -> None:
        """Show the main interactive menu."""
        print(f"\nGOLD PATTERN TRADER v2.0")
        print(f"Config: {self.config.config_file}")
        print(f"Log: {self.config.get('log_file')}")
        print(f"Accounts: {len(self.traders)} loaded")

        actions = {
            "1": self.add_account,
            "2": lambda: self.start_trading(input("Account login: ").strip()),
            "3": lambda: self.stop_trading(input("Account login: ").strip()),
            "4": lambda: self.view_live_status(input("Account login: ").strip()),
            "5": self.show_accounts_summary,
            "6": lambda: self.remove_account(input("Account login: ").strip()),
            "7": lambda: self.edit_account(input("Account login: ").strip()),
            "8": self.show_config_menu,
        }

        while True:
            try:
                print("\n" + "=" * 50)
                print("MAIN MENU")
                print("=" * 50)
                print("1. Add new trading account")
                print("2. Start trading for an account")
                print("3. Stop trading for an account")
                print("4. View live trading status")
                print("5. Show accounts summary")
                print("6. Remove account")
                print("7. Edit account")
                print("8. Configuration settings")
                print("9. Exit")

                choice = input("\nSelect (1-9): ").strip()
                if choice == "9":
                    break

                fn = actions.get(choice)
                if fn:
                    fn()
                else:
                    print("Invalid option, select 1-9")

            except KeyboardInterrupt:
                print("\nInterrupted")
                break
            except Exception as exc:
                print(f"Error: {exc}")
                self._log.error("Menu error: %s", exc)

        print("\nStopping all traders...")
        for login in list(self.traders.keys()):
            self.stop_trading(login)
        print("Goodbye!")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_float(
        label: str,
        default: float,
        lo: float,
        hi: float,
        allow_blank: bool = False,
    ) -> float:
        """Prompt for a float within [*lo*, *hi*]."""
        while True:
            raw = input(f"{label}: ").strip()
            if not raw and allow_blank:
                return default
            if not raw:
                raw = str(default)
            try:
                val = float(raw)
                if lo <= val <= hi:
                    return val
                print(f"Must be between {lo} and {hi}")
            except ValueError:
                print("Invalid number")
