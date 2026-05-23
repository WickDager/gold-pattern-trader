"""MetaTrader 5 connection management with auto-reconnect."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5


class ConnectionManager:
    """Maintains an MT5 terminal connection with exponential-backoff retries.

    Parameters
    ----------
    login:
        MT5 account login number.
    password:
        MT5 account password.
    server:
        MT5 server name.
    max_attempts:
        Maximum connection attempts before giving up.
    logger:
        Optional external logger.
    """

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        max_attempts: int = 5,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self.max_attempts = max_attempts
        self._log = logger or logging.getLogger(__name__)
        self.connected: bool = False
        self.last_check = datetime.now()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish an MT5 connection.

        Retries up to :attr:`max_attempts` times with exponential backoff.
        """
        for attempt in range(self.max_attempts):
            try:
                if not mt5.initialize(
                    login=self.login,
                    password=self.password,
                    server=self.server,
                ):
                    error = mt5.last_error()
                    self._log.error(
                        "MT5 init failed (attempt %d): %s", attempt + 1, error
                    )
                    if attempt < self.max_attempts - 1:
                        time.sleep(2 ** attempt)
                    continue

                account_info = mt5.account_info()
                if not account_info:
                    self._log.error(
                        "Failed to get account info (attempt %d)", attempt + 1
                    )
                    mt5.shutdown()
                    if attempt < self.max_attempts - 1:
                        time.sleep(2 ** attempt)
                    continue

                self.connected = True
                self.last_check = datetime.now()
                self._log.info(
                    "Connected to MT5: %s (%s)", account_info.login, account_info.server
                )
                return True

            except Exception as exc:
                self._log.error(
                    "Connection error (attempt %d): %s", attempt + 1, exc
                )
                if attempt < self.max_attempts - 1:
                    time.sleep(2 ** attempt)

        self.connected = False
        return False

    def check_connection(self) -> bool:
        """Return ``True`` if the MT5 terminal is still responsive."""
        try:
            if mt5.account_info() is None:
                self.connected = False
                return False
            self.last_check = datetime.now()
            return True
        except Exception as exc:
            self._log.error("Connection check failed: %s", exc)
            self.connected = False
            return False

    def ensure_connection(self) -> bool:
        """Reconnect if the current connection is dead.

        Returns ``True`` when a working connection exists (or was re-established).
        """
        try:
            if not self.connected or not self.check_connection():
                self._log.warning("Connection lost, reconnecting...")
                mt5.shutdown()
                time.sleep(1)
                return self.connect()
            return True
        except Exception as exc:
            self._log.error("ensure_connection error: %s", exc)
            return self.connect()

    def disconnect(self) -> None:
        """Shut down the MT5 connection cleanly."""
        try:
            mt5.shutdown()
            self.connected = False
            self._log.info("Disconnected from MT5")
        except Exception as exc:
            self._log.error("Error during disconnect: %s", exc)
