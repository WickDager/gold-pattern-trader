"""Entry point for the Gold Pattern Trader."""

from __future__ import annotations

import logging
import sys


def main() -> None:
    """Initialize the trading manager and show the interactive menu."""
    try:
        # Avoid "chcp" call at module level — let the console handler deal with it.
        from .manager import TradingManager

        print("Initializing Gold Pattern Trader...")
        manager = TradingManager()
        manager.show_menu()
    except Exception as exc:
        print(f"Critical error: {exc}")
        logging.error("Critical error in main: %s", exc)
    finally:
        print("Program terminated")


if __name__ == "__main__":
    main()
