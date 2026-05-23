# Gold Pattern Trader

Automated XAUUSD (Gold) trading bot that combines a **Sierra Chart ACSIL study**
for 1-minute data export with a **Python MetaTrader 5 bot** that detects pattern
invalidation and divergence signals to execute trades.

## Architecture

```
Sierra Chart (C++)              Python (MT5)
┌──────────────────┐           ┌─────────────────────┐
│ GoldDataExporter  │──CSV──►  │ XAUUSDLiveTrader    │
│ • 1-min bar export │          │ • Pattern detection  │
│ • Pattern detection│          │ • Invalidation logic │
│ • Rolling window   │          │ • Divergence checks  │
│ • ADR/Delta track  │          │ • Position management│
└──────────────────┘           └─────────────────────┘
```

## Components

| Component | Language | Purpose |
|-----------|----------|---------|
| `sierra_chart_study/GoldDataExporter.cpp` | C++ (ACSIL) | Sierra Chart study exporting 1-min XAUUSD data with pattern markers |
| `src/trader.py` | Python | Core trading logic: pattern invalidation, divergence, order placement |
| `src/manager.py` | Python | Multi-account management and CLI menu |
| `src/config.py` | Python | Configuration loader with JSON persistence |
| `src/pattern_tracker.py` | Python | Thread-safe pattern storage with expiry and deduplication |
| `src/connection_manager.py` | Python | MT5 connection with auto-reconnect and exponential backoff |
| `src/account_manager.py` | Python | Encrypted account credential storage |

## Quick Start

### Prerequisites

- Python 3.8+
- MetaTrader 5 terminal installed and configured
- Sierra Chart with XAUUSD 1-minute chart data
- Windows (required for MT5 and pywin32)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/gold-pattern-trader.git
cd gold-pattern-trader

# Install dependencies
pip install -r requirements.txt

# Copy and edit the example accounts file
cp config/trading_accounts.json.example config/trading_accounts.json
```

### Sierra Chart Setup

1. Copy `sierra_chart_study/GoldDataExporter.cpp` to your Sierra Chart `Data` folder.
2. Compile through Studies -> ACSIL -> Compile.
3. Add the study to a 1-minute XAUUSD chart.
4. Configure the ADR and Cumulative Delta subgraph inputs.

### Running the Bot

```bash
# Start the interactive trading manager
python -m src.main
```

## Configuration

The bot reads `config/trading_config.json` on startup. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `data_file_path` | `C:/trading_bot/Live_Gold_Data.csv` | Path to Sierra Chart CSV export |
| `pattern_expiry_hours` | `4` | How long tracked patterns remain active |
| `divergence_tolerance` | `4` | Tolerance for divergence detection |
| `trading_start_hour` | `3` | Trading session start (UTC) |
| `trading_end_hour` | `18` | Trading session end (UTC) |
| `breakeven_adr_multiplier` | `1.0` | ADR multiple before SL moves to breakeven |

## Trading Strategy

The bot implements a **pattern invalidation + divergence** strategy:

1. **Pattern Detection**: Swing highs/lowds are identified from the Sierra Chart
   data stream.
2. **Pattern Tracking**: Active patterns are stored with a 4-hour expiry window.
3. **Invalidation**: When price breaks beyond a tracked pattern level, the
   pattern is considered invalidated.
4. **Divergence Check**: On invalidation, the bot checks for cumulative delta
   divergence — if the delta doesn't confirm the price move, a trade is triggered.
5. **Position Management**: SL is moved to breakeven after price moves 1 ADR in
   the trade direction.

## Project Structure

```
gold-pattern-trader/
├── src/                        # Python package
│   ├── config.py               # Configuration management
│   ├── logger.py               # Logging setup
│   ├── data_validator.py       # CSV data validation
│   ├── pattern_tracker.py      # Pattern storage and expiry
│   ├── connection_manager.py   # MT5 connection handling
│   ├── account_manager.py      # Account credentials
│   ├── trader.py               # Core trading logic
│   ├── manager.py              # Multi-account CLI manager
│   └── main.py                 # Entry point
├── sierra_chart_study/         # Sierra Chart ACSIL study
│   ├── GoldDataExporter.cpp
│   └── README.md
├── config/                     # Configuration files
│   ├── trading_config.json
│   └── trading_accounts.json.example
├── tests/                      # Unit tests
├── docs/
│   └── ARCHITECTURE.md
├── requirements.txt
├── setup.py
└── pyproject.toml
```

## License

MIT
