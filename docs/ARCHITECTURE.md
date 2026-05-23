# Architecture

## Overview

Gold Pattern Trader is a two-component system:

1. **Sierra Chart ACSIL study (C++)** — runs inside Sierra Chart, exports
   1-minute XAUUSD bar data with pattern markers to a CSV file.
2. **Python trading bot** — reads the CSV, tracks patterns, detects
   invalidation + divergence signals, and executes trades via MetaTrader 5.

```
┌─────────────────────────────────────────────────────────────┐
│                     Sierra Chart                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ GoldDataExporter (C++ ACSIL)                         │   │
│  │  • 1-min bar aggregation                              │   │
│  │  • Swing-high / swing-low detection (3-bar method)    │   │
│  │  • Rolling window (60 bars)                           │   │
│  │  • Reads ADR & Cumulative Delta from other studies    │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                          │ CSV export                        │
└──────────────────────────┼──────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Live_Gold_Data.csv    │
              └────────┬───────────────┘
                       │ poll every 10 s
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Python Trading Bot                                          │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Config   │  │ Data         │  │ PatternTracker       │   │
│  │ (JSON)   │──│ Validator    │──│ • High/low patterns   │   │
│  └──────────┘  └──────────────┘  │ • Expiry (4h)        │   │
│                                  │ • Dedup via UID       │   │
│  ┌──────────────────────────┐    └──────────┬───────────┘   │
│  │ XAUUSDLiveTrader         │               │               │
│  │ • Pattern invalidation   │◄──────────────┘               │
│  │ • Delta divergence check │                               │
│  │ • Trade placement (MT5)  │──► MetaTrader 5               │
│  │ • Breakeven SL mgmt      │                               │
│  └──────────────────────────┘                               │
│                                                              │
│  ┌──────────────────────────┐                                │
│  │ TradingManager (CLI)     │  manages N traders             │
│  └──────────────────────────┘                                │
└──────────────────────────────────────────────────────────────┘
```

## Trading Strategy

### Pattern Detection (Sierra Chart)

The C++ study uses a 3-bar swing detection method:

- **Swing high**: bar `i-1` has a higher high than both bar `i-2` and bar `i`
  → `pattern_type = 1`, value = `High[i-1]`
- **Swing low**: bar `i-1` has a lower low than both bar `i-2` and bar `i`
  → `pattern_type = -1`, value = `Low[i-1]`

This is evaluated on every completed bar, so patterns are always one bar
behind real-time.

### Invalidation + Divergence (Python)

The core trading logic follows the "Hoyo" approach:

1. **Track** active swing-high and swing-low patterns (up to N per type).
2. **Invalidation**: a high pattern is invalidated when price breaks *above*
   the highest tracked high. A low pattern is invalidated when price breaks
   *below* the lowest tracked low.
3. **Divergence**: on invalidation, check whether cumulative delta confirms
   the move. If price made a higher high but delta is falling (bearish
   divergence), a SELL signal is generated. If price made a lower low but
   delta is rising (bullish divergence), a BUY signal is generated.
4. **Trade entry**: market order with SL at ADR × `sl_multiplier` and TP
   at ADR × `tp_multiplier`. FOK (fill-or-kill) order type.
5. **Breakeven**: once price moves 1 ADR (or configured multiple) in the
   trade direction, SL is moved to entry price.

## Module Map

| Module | Responsibility |
|--------|---------------|
| `config.py` | Load/save JSON config, provide typed accessors |
| `logger.py` | Rotating file logger + emoji-safe console output |
| `data_validator.py` | Sanity-check incoming CSV rows (OHLC, pattern values) |
| `pattern_tracker.py` | Thread-safe pattern storage with expiry and deduplication |
| `connection_manager.py` | MT5 `initialize` with exponential-backoff retries |
| `account_manager.py` | Plain-JSON credential storage (not encrypted) |
| `trader.py` | Single-account trading loop, pattern logic, order placement |
| `manager.py` | Multi-account orchestration and interactive CLI |
| `main.py` | Package entry point |

## Threading Model

Each `XAUUSDLiveTrader` runs its own loop in a daemon thread.  The
`PatternTracker` uses an `RLock` to protect its pattern lists from concurrent
access.  Data loading (CSV reads) happens inside the trader thread — no
cross-thread file contention since the C++ study only *writes* and the
Python bot only *reads*.

## Configuration

Settings are stored in `config/trading_config.json` and managed through the
`TradingConfig` class.  All values have sensible defaults.  The config menu
inside the CLI provides a interactive editing interface.

## Data Flow

1. Sierra Chart calls `scsf_GoldDataExporter` on every new tick.
2. On completed bars, the study updates its rolling window and writes CSV.
3. The Python bot polls the CSV every 10 seconds (configurable).
4. New rows trigger pattern registration and invalidation checks.
5. Invalidations that pass the divergence test result in MT5 orders.
