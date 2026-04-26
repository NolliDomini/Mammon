import asyncio
import pandas as pd
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from alpaca.data.historical import (
    StockHistoricalDataClient,
    CryptoHistoricalDataClient
)
from alpaca.data.live import CryptoDataStream, StockDataStream
from alpaca.data.requests import (
    StockBarsRequest, 
    CryptoBarsRequest,
    StockSnapshotRequest,
    CryptoSnapshotRequest,
    StockLatestBarRequest,
    CryptoLatestBarRequest
)
from alpaca.data.timeframe import TimeFrame
from pathlib import Path
from Hippocampus.Archivist.librarian import Librarian
from Thalamus.gland import SmartGland

CANONICAL_COLS = ["open", "high", "low", "close", "volume", "symbol"]


class IngestionContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class Thalamus:
    """
    Thalamus: Centralized Data Entry.
    Utilizes the SmartGland for high-fidelity Triple-Pulse resampling and context buffering.
    V6: Expanded for "Any and All" Alpaca data classes via unified historical clients.
    """
    def __init__(self, api_key=None, api_secret=None, optical_tract=None, duck_pond=None):
        self.api_key = api_key
        self.api_secret = api_secret
        
        # Unified Clients (Support bars, latest, snapshots, quotes, and trades)
        self.stock_client = StockHistoricalDataClient(api_key, api_secret) if api_key else None
        self.crypto_client = CryptoHistoricalDataClient(api_key, api_secret) if api_key else CryptoHistoricalDataClient()
        
        # Live streams
        self.crypto_stream = CryptoDataStream(api_key, api_secret) if api_key else None
        self.stock_stream = StockDataStream(api_key, api_secret) if api_key else None

        self.optical_tract = optical_tract
        self.duck_pond = duck_pond
        self.lib = Librarian()
        self.gland = SmartGland(window_minutes=5)
        self.last_ingestion_event: Dict[str, Any] = {}

    def pulse(self, symbols, timeframe=TimeFrame.Minute, start=None, end=None, is_crypto=True, source="ALPACA"):
        if source == "DATABASE":
            df = self._pulse_from_db(symbols[0])
        elif source == "ALPACA":
            df = self._pulse_from_alpaca(symbols, timeframe, start, end, is_crypto)
        else:
            raise IngestionContractError("INGEST_SOURCE_UNSUPPORTED", f"unsupported source={source!r}")
        if self.optical_tract and not df.empty:
            self.optical_tract.spray(df)
        return df

    def get_snapshot(self, symbols: list, is_crypto=True):
        """
        Fetches the latest Snapshot (latest trade, latest quote, current daily bar).
        V6: Crucial for live 'Action' pulse validation.
        """
        client = self.crypto_client if is_crypto else self.stock_client
        if not client: raise ValueError("Client not initialized.")
        
        request = CryptoSnapshotRequest(symbol_or_symbols=symbols) if is_crypto else StockSnapshotRequest(symbol_or_symbols=symbols)
        return client.get_crypto_snapshot(request) if is_crypto else client.get_stock_snapshot(request)

    def get_latest_bar(self, symbol: str, is_crypto=True, retries=3, retry_delay=1.5):
        """Returns the single latest 1m bar available for a symbol."""
        if not (self.crypto_client if is_crypto else self.stock_client):
            raise ValueError("Client not initialized.")
        request = CryptoLatestBarRequest(symbol_or_symbols=[symbol]) if is_crypto else StockLatestBarRequest(symbol_or_symbols=[symbol])
        last_exc = None
        for attempt in range(retries):
            try:
                client = self.crypto_client if is_crypto else self.stock_client
                return client.get_crypto_latest_bar(request) if is_crypto else client.get_stock_latest_bar(request)
            except Exception as e:
                last_exc = e
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    self.crypto_client = CryptoHistoricalDataClient(self.api_key, self.api_secret) if self.api_key else CryptoHistoricalDataClient()
        raise last_exc

    def get_state(self) -> Dict[str, Any]:
        """Exposes ingestion events and SmartGland telemetry (Piece 13)."""
        return {
            "last_ingestion": self.last_ingestion_event,
            "smart_gland": self.gland.get_state()
        }

    def drip_pulse(self, raw_data: pd.DataFrame):
        """
        Main entry point for 'Operation Drip Drip'.
        Ingests raw 1m data and sprays Triple-Pulses (SEED, ACTION, MINT) via Optical Tract.
        V5: Saves raw bars to DuckPond data lake before processing (if connected).
        """
        normalized_raw = self._normalize_bars(raw_data, source="DRIP")

        # V5: Save raw bars to the data lake (dedup handled by DuckPond)
        if self.duck_pond:
            self.duck_pond.append_live_bars(normalized_raw)
        
        pulses = self.gland.ingest(normalized_raw)
        normalized_pulses = []
        for pulse_type, agg_df in pulses:
            normalized_agg = self._normalize_bars(
                agg_df,
                source="SMARTGLAND",
                passthrough_cols=["pulse_type"],
            )
            if pulse_type == "MINT" and self.duck_pond and not agg_df.empty:
                finalized_5m = normalized_agg.tail(1).copy()
                if "pulse_type" in finalized_5m.columns:
                    finalized_5m = finalized_5m.drop(columns=["pulse_type"])
                self.duck_pond.append_live_5m_bars(finalized_5m)
            if not normalized_agg.empty and self.optical_tract:
                self.optical_tract.spray(normalized_agg)
            normalized_pulses.append((pulse_type, normalized_agg))
        return normalized_pulses

    def _pulse_from_alpaca(self, symbols, timeframe, start, end, is_crypto):
        client = self.crypto_client if is_crypto else self.stock_client
        if not client: raise ValueError("Alpaca client not initialized.")
        
        request_params = {"symbol_or_symbols": symbols, "timeframe": timeframe, "start": start, "end": end}
        if is_crypto:
            bars = client.get_crypto_bars(CryptoBarsRequest(**request_params))
        else:
            bars = client.get_stock_bars(StockBarsRequest(**request_params))
        
        df = bars.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()
            if "timestamp" in df.columns and "ts" not in df.columns:
                df = df.rename(columns={"timestamp": "ts"})
        symbol_hint = symbols[0] if symbols else None
        return self._normalize_bars(df, source="ALPACA", symbol_hint=symbol_hint)

    def _pulse_from_db(self, symbol, limit=500):
        query = "SELECT ts, open, high, low, close, volume FROM master_test_key WHERE symbol = ? ORDER BY ts ASC LIMIT ?"
        data = self.lib.read_only(query, (symbol, limit))
        df = pd.DataFrame(data)
        if not df.empty:
            df["symbol"] = symbol
        return self._normalize_bars(df, source="DATABASE", symbol_hint=symbol)

    def _normalize_bars(
        self,
        raw_df: pd.DataFrame,
        *,
        source: str,
        symbol_hint: Optional[str] = None,
        passthrough_cols: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        passthrough_cols = passthrough_cols or []

        if raw_df is None:
            self._record_ingestion_event(source, symbol_hint, 0, "error", "INGEST_INPUT_NONE")
            raise IngestionContractError("INGEST_INPUT_NONE", "input bars cannot be None")

        df = raw_df.copy()
        if df.empty:
            self._record_ingestion_event(source, symbol_hint, 0, "ok")
            out = pd.DataFrame(columns=CANONICAL_COLS + passthrough_cols)
            out.index = pd.DatetimeIndex([], name="ts")
            return out

        if not isinstance(df.index, pd.DatetimeIndex):
            if "ts" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
                if df["ts"].isna().any():
                    self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_TS_INVALID")
                    raise IngestionContractError("INGEST_TS_INVALID", "one or more timestamps are invalid")
                df = df.set_index("ts")
            elif "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                if df["timestamp"].isna().any():
                    self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_TS_INVALID")
                    raise IngestionContractError("INGEST_TS_INVALID", "one or more timestamps are invalid")
                df = df.set_index("timestamp")
            else:
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_TS_MISSING")
                raise IngestionContractError("INGEST_TS_MISSING", "expected DatetimeIndex or ts/timestamp column")
        else:
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            if df.index.isna().any():
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_TS_INVALID")
                raise IngestionContractError("INGEST_TS_INVALID", "one or more index timestamps are invalid")

        if "symbol" not in df.columns:
            if symbol_hint:
                df["symbol"] = str(symbol_hint)
            else:
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_SYMBOL_MISSING")
                raise IngestionContractError("INGEST_SYMBOL_MISSING", "missing required column: symbol")

        missing = [c for c in CANONICAL_COLS if c not in df.columns]
        if missing:
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_SCHEMA_MISSING")
            raise IngestionContractError("INGEST_SCHEMA_MISSING", f"missing required columns: {missing}")

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[["open", "high", "low", "close", "volume"]].isna().any().any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_NUMERIC_INVALID")
            raise IngestionContractError("INGEST_NUMERIC_INVALID", "numeric OHLCV fields contain null/invalid values")
        if (df["volume"] < 0).any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_VOLUME_NEGATIVE")
            raise IngestionContractError("INGEST_VOLUME_NEGATIVE", "volume cannot be negative")

        df["symbol"] = df["symbol"].astype(str).str.strip()
        if (df["symbol"] == "").any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "INGEST_SYMBOL_INVALID")
            raise IngestionContractError("INGEST_SYMBOL_INVALID", "symbol cannot be blank")

        df = df.sort_index()
        if df.index.has_duplicates:
            df = df[~df.index.duplicated(keep="last")]

        keep_cols = CANONICAL_COLS + [c for c in passthrough_cols if c in df.columns]
        out = df[keep_cols].copy()
        out.index.name = "ts"
        self._record_ingestion_event(source, out["symbol"].iloc[-1] if not out.empty else symbol_hint, len(out), "ok")
        return out

    def warmup_context(self, symbols: list, is_crypto: bool = True) -> None:
        """Pull 60 min of historical 1m bars to prime SmartGland before live stream starts."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=60)
        try:
            df = self._pulse_from_alpaca(symbols, TimeFrame.Minute, start, end, is_crypto)
            if not df.empty:
                self.gland.ingest(df)
                # Reset live-window state so the first real bar opens a clean window
                # instead of triggering a spurious flush of the last warmup window.
                self.gland.current_window_start = None
                self.gland.raw_list = []
                self.gland._reset_window_markers()
                self.gland._live_mode = True
                print(f"   [THALAMUS] Warmup: {len(self.gland.context_df)} context bars loaded.")
            else:
                print("   [THALAMUS_WARN] Warmup returned no data. Context remains cold.")
        except Exception as e:
            print(f"[THAL-E-P26-105] Warmup context failed: {e}")

    async def connect_stream(self, symbols: list, is_crypto: bool = True, bar_callback=None) -> None:
        """Subscribe to Alpaca live 1m bar stream. bar_callback(bar) called for each closed bar."""
        stream = self.crypto_stream if is_crypto else self.stock_stream
        if not stream:
            raise RuntimeError("[THALAMUS] Stream client not initialized. Check credentials.")
        handler = bar_callback if bar_callback is not None else self._on_bar
        stream.subscribe_bars(handler, *symbols)
        await stream._run_forever()

    async def stop_stream(self, is_crypto: bool = True) -> None:
        stream = self.crypto_stream if is_crypto else self.stock_stream
        if stream:
            await stream.stop()

    async def _on_bar(self, bar) -> None:
        try:
            raw_dict = {
                "ts": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "symbol": bar.symbol,
            }
            df = pd.DataFrame([raw_dict])
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df = df.set_index("ts")
            self.drip_pulse(df)
        except Exception as e:
            print(f"[THAL-E-P25-103] Real-time bar processing failed: {e}")

    def _record_ingestion_event(
        self,
        source: str,
        symbol: Optional[str],
        row_count: int,
        status: str,
        error_code: Optional[str] = None,
    ) -> None:
        self.last_ingestion_event = {
            "source": str(source),
            "symbol": None if symbol is None else str(symbol),
            "row_count": int(row_count),
            "status": str(status),
            "error_code": error_code,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
