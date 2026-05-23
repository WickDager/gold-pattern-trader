"""Account credential storage backed by a JSON file.

.. warning::
   Passwords are stored in **plain text** inside the JSON file.  Consider
   encrypting the file or using environment variables in production.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

ACCOUNTS_FILE = "trading_accounts.json"
DEFAULT_ACCOUNTS: Dict = {"accounts": {}}


class AccountManager:
    """Load, save and manage trading account credentials.

    Parameters
    ----------
    filename:
        Path to the JSON file that holds account data.
    """

    def __init__(self, filename: str = ACCOUNTS_FILE) -> None:
        self.filename = filename
        self.accounts: Dict = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_account(
        self,
        login: str,
        password: str,
        server: str,
        risk_percentage: float,
        tp_multiplier: float,
        sl_multiplier: float,
    ) -> None:
        """Register a new trading account."""
        self.accounts[login] = {
            "password": password,
            "server": server,
            "risk_percentage": risk_percentage,
            "tp_multiplier": tp_multiplier,
            "sl_multiplier": sl_multiplier,
        }
        self._save()

    def update_account(self, login: str, **kwargs: str) -> bool:
        """Update fields of an existing account.  Returns ``False`` if unknown."""
        if login not in self.accounts:
            return False
        for key, value in kwargs.items():
            if key in self.accounts[login]:
                self.accounts[login][key] = value
        self._save()
        return True

    def remove_account(self, login: str) -> bool:
        """Remove *login* from storage.  Returns ``False`` if unknown."""
        if login in self.accounts:
            del self.accounts[login]
            self._save()
            return True
        return False

    def get_account(self, login: str) -> Optional[Dict]:
        """Return the account dict for *login*, or ``None``."""
        return self.accounts.get(login)

    def get_all_accounts(self) -> Dict:
        """Return a copy of every stored account."""
        return self.accounts.copy()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if os.path.exists(self.filename):
                with open(self.filename, "r") as f:
                    self.accounts = json.load(f).get("accounts", {})
            else:
                self.accounts = DEFAULT_ACCOUNTS["accounts"].copy()
                self._save()
        except Exception as exc:
            print(f"Error loading accounts: {exc}")
            self.accounts = DEFAULT_ACCOUNTS["accounts"].copy()

    def _save(self) -> None:
        try:
            with open(self.filename, "w") as f:
                json.dump({"accounts": self.accounts}, f, indent=4)
        except Exception as exc:
            print(f"Error saving accounts: {exc}")
