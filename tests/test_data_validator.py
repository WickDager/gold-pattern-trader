"""Tests for the DataValidator module."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data_validator import DataValidator


class TestValidateRow:
    def test_valid_row(self) -> None:
        row = pd.Series({
            "datetime": "2024-01-01 10:00",
            "open": 2050.0,
            "high": 2055.0,
            "low": 2048.0,
            "close": 2052.0,
            "volume": 100,
            "pattern_high": 2055.0,
            "pattern_low": 0.0,
            "pattern_type": 1,
            "cumulative_delta": 50.0,
            "adr_value": 20.0,
        })
        assert DataValidator.validate_row(row)

    def test_missing_column(self) -> None:
        row = pd.Series({"open": 2050.0})
        assert not DataValidator.validate_row(row)

    def test_invalid_ohlc(self) -> None:
        row = pd.Series({
            "datetime": "2024-01-01 10:00",
            "open": 2050.0,
            "high": 2045.0,  # high < open
            "low": 2040.0,
            "close": 2042.0,
            "volume": 100,
            "pattern_high": 0.0,
            "pattern_low": 0.0,
            "pattern_type": 0,
            "cumulative_delta": 0.0,
            "adr_value": 20.0,
        })
        assert not DataValidator.validate_row(row)

    def test_invalid_pattern_type(self) -> None:
        row = pd.Series({
            "datetime": "2024-01-01 10:00",
            "open": 2050.0,
            "high": 2055.0,
            "low": 2048.0,
            "close": 2052.0,
            "volume": 100,
            "pattern_high": 0.0,
            "pattern_low": 0.0,
            "pattern_type": 99,  # invalid
            "cumulative_delta": 0.0,
            "adr_value": 20.0,
        })
        assert not DataValidator.validate_row(row)

    def test_negative_volume(self) -> None:
        row = pd.Series({
            "datetime": "2024-01-01 10:00",
            "open": 2050.0,
            "high": 2055.0,
            "low": 2048.0,
            "close": 2052.0,
            "volume": -1,
            "pattern_high": 0.0,
            "pattern_low": 0.0,
            "pattern_type": 0,
            "cumulative_delta": 0.0,
            "adr_value": 20.0,
        })
        assert not DataValidator.validate_row(row)


class TestValidateDataFrame:
    def test_empty_frame(self) -> None:
        df = pd.DataFrame()
        result = DataValidator.validate_dataframe(df)
        assert result.empty

    def test_mixed_rows(self) -> None:
        valid = {
            "datetime": "2024-01-01 10:00",
            "open": 2050.0, "high": 2055.0, "low": 2048.0, "close": 2052.0,
            "volume": 100, "pattern_high": 0.0, "pattern_low": 0.0,
            "pattern_type": 0, "cumulative_delta": 0.0, "adr_value": 20.0,
        }
        invalid = dict(valid)
        invalid["pattern_type"] = 99

        df = pd.DataFrame([valid, invalid])
        result = DataValidator.validate_dataframe(df)
        assert len(result) == 1
