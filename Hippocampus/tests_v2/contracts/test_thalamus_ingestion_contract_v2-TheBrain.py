from unittest.mock import MagicMock

import pandas as pd
import pytest

from Thalamus.relay import Thalamus, IngestionContractError
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv


def _assert_canonical(df: pd.DataFrame):
    assert isinstance(df.index, pd.DatetimeIndex)
    # Piece 4: Extended 11-column canonical schema
    expected = ["open", "high", "low", "close", "volume", "symbol", "bid", "ask", "bid_size", "ask_size", "pulse_type"]
    assert list(df.columns) == expected
    assert df.index.name == "ts"
    assert pd.api.types.is_string_dtype(df["symbol"])
    for c in ("open", "high", "low", "close", "volume", "bid", "ask"):
        assert pd.api.types.is_numeric_dtype(df[c])


def test_ingress_paths_emit_canonical_dataframe_contract():
    t = Thalamus(optical_tract=MagicMock())

    alpaca_df = synthetic_ohlcv(periods=4).copy()
    bars = MagicMock()
    bars.df = alpaca_df
    t.crypto_client = MagicMock()
    t.crypto_client.get_crypto_bars = MagicMock(return_value=bars)
    
    # Mock get_snapshot to avoid network calls
    t.get_snapshot = MagicMock(return_value={"bid": 1.0, "ask": 1.0, "bid_size": 1.0, "ask_size": 1.0})
    
    out_a = t.pulse(["BTC/USD"], is_crypto=True, source="ALPACA")

    rows = [
        {"ts": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
        {"ts": "2026-01-01T00:01:00Z", "open": 2, "high": 3, "low": 1, "close": 2, "volume": 20},
    ]
    t.lib = MagicMock()
    t.lib.read_only = MagicMock(return_value=rows)
    out_b = t.pulse(["BTC/USD"], source="DATABASE")

    _assert_canonical(out_a)
    _assert_canonical(out_b)


def test_pulse_fetch_path_injects_pulse_type():
    t = Thalamus()
    bars = MagicMock()
    bars.df = synthetic_ohlcv(periods=3).copy()
    t.crypto_client = MagicMock()
    t.crypto_client.get_crypto_bars = MagicMock(return_value=bars)
    t.get_snapshot = MagicMock(return_value={"bid": 1.0, "ask": 1.0, "bid_size": 1.0, "ask_size": 1.0})

    out = t.pulse(["BTC/USD"], is_crypto=True, source="ALPACA")
    assert "pulse_type" in out.columns


def test_malformed_payload_fails_with_deterministic_error_contract():
    t = Thalamus()
    bad = pd.DataFrame(
        [{"ts": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": -1, "symbol": "BTC/USD"}]
    )
    with pytest.raises(IngestionContractError) as exc:
        t._normalize_bars(bad, source="TEST")
    # Piece 110: MNER code for negative volume
    assert exc.value.code == "THAL-E-P21-110"
    assert t.last_ingestion_event["status"] == "error"
    assert t.last_ingestion_event["error_code"] == "THAL-E-P21-110"
