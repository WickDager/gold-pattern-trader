"""CSV data validation for Sierra-Chart exported 1-minute gold data."""

from __future__ import annotations

import pandas as pd


# Columns expected in every incoming data row.
REQUIRED_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "pattern_high",
    "pattern_low",
    "pattern_type",
    "cumulative_delta",
    "adr_value",
]


class DataValidator:
    """Validate and clean data frames loaded from the Sierra Chart CSV export."""

    @staticmethod
    def validate_row(row: pd.Series) -> bool:
        """Return ``True`` when *row* passes all sanity checks.

        Checks performed:

        * All required columns present and non-null.
        * OHLC internal consistency (low <= open/close <= high).
        * ``pattern_type`` is one of ``{-1, 0, 1}``.
        * Non-negative :attr:`pattern_high`, :attr:`pattern_low`,
          :attr:`volume`, and :attr:`adr_value`.
        """
        for col in REQUIRED_COLUMNS:
            if col not in row or pd.isna(row[col]):
                return False

        # OHLC consistency
        if not (row["low"] <= row["open"] <= row["high"] and
                row["low"] <= row["close"] <= row["high"]):
            return False

        if row["pattern_type"] not in (-1, 0, 1):
            return False

        if row["pattern_high"] < 0 or row["pattern_low"] < 0:
            return False

        if row["volume"] < 0 or row["adr_value"] < 0:
            return False

        return True

    @staticmethod
    def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Filter *df* to only valid rows and return a clean copy."""
        if df.empty:
            return df

        mask = df.apply(DataValidator.validate_row, axis=1)
        clean = df[mask].copy()

        dropped = len(df) - len(clean)
        if dropped:
            print(f"Filtered out {dropped} invalid rows")

        return clean
