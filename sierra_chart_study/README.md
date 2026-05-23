# Sierra Chart Study: GoldDataExporter

## Overview

This Sierra Chart ACSIL study exports live 1-minute XAUUSD (Gold) data to a CSV
file that the Python trading bot consumes. It performs real-time pattern detection
(local highs/lows) and tracks ADR and cumulative delta values.

## Installation

1. Copy `GoldDataExporter.cpp` to your Sierra Chart `Data` folder.
2. Compile the study through Sierra Chart (Studies -> ACSIL -> Compile).
3. Add the study to a 1-minute XAUUSD chart.

## Configuration

The study requires three inputs:

- **ADR Study Subgraph** — Reference to the ADR indicator study/subgraph.
- **Cumulative Delta Subgraph** — Reference to the Cumulative Delta study/subgraph.
- **Output File Path** — Full path for the exported CSV
  (default: `C:\trading_bot\Live_Gold_Data.csv`).

## How It Works

1. On initialization, the study processes the last 15 completed bars to warm up
   the rolling window.
2. On each new tick, it processes completed bars, detecting swing highs and
   swing lows using a strict higher-high/lower-low comparison across 3 bars.
3. Pattern data (high/low type, cumulative delta, ADR value) is appended to a
   60-bar rolling window and written to the CSV file.

## CSV Format

```
datetime,open,high,low,close,volume,pattern_high,pattern_low,pattern_type,cumulative_delta,adr_value
```

- `pattern_type`: `1` = swing high, `-1` = swing low, `0` = no pattern
- `pattern_high` / `pattern_low`: the price level where the pattern was detected
