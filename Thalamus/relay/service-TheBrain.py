import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List
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

from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian
from Thalamus.gland.service import SmartGland

CANONICAL_COLS = ["open", "high", "low", "close", "volume", "symbol", "bid", "ask", "bid_size", "ask_size", "pulse_type"]


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
        
        # Live Streams (Target #25)
        self.crypto_stream = CryptoDataStream(api_key, api_secret) if api_key else None
        self.stock_stream = StockDataStream(api_key, api_secret) if api_key else None
        
        self.optical_tract = optical_tract
        self.duck_pond = duck_pond 
        self.lib = librarian
        self.gland = SmartGland(window_minutes=5)
        self.last_ingestion_event: Dict[str, Any] = {}

    async def connect_stream(self, symbols: List[str], is_crypto: bool = True):
        """
        Target #25: WebSocket Stream Wiring.
        Subscribes to 1m bars and starts the real-time websocket thread.
        """
        stream = self.crypto_stream if is_crypto else self.stock_stream
        if not stream:
            print("[THALAMUS_ERROR] Stream client not initialized. Check credentials.")
            return

        print(f"[THALAMUS] Wiring Real-time Stream for {symbols}...")
        
        # Subscribe to bars
        if is_crypto:
            stream.subscribe_bars(self._on_bar, *symbols)
        else:
            stream.subscribe_bars(self._on_bar, *symbols)

        # Run the stream (This is typically blocking or async)
        # Note: In a production environment, this should run in its own event loop or thread.
        await stream._run_forever()

    async def stop_stream(self, is_crypto: bool = True):
        stream = self.crypto_stream if is_crypto else self.stock_stream
        if stream:
            await stream.stop()

    async def _on_bar(self, bar: Any):
        """
        Target #25: Stream Callback.
        Receives raw 1m bar, normalizes, and drips into the pulse engine.
        """
        try:
            # Convert Alpaca Bar object to DataFrame
            raw_dict = {
                "ts": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "symbol": bar.symbol
            }
            df = pd.DataFrame([raw_dict])
            df = df.set_index("ts")
            
            # Piece 10: Fetch Snapshot for Bid/Ask in stream callback
            try:
                is_crypto = "/" in bar.symbol or len(bar.symbol) > 6
                snapshot = self.get_snapshot([bar.symbol], is_crypto=is_crypto)
                quote = getattr(snapshot.get(bar.symbol), "latest_quote", None)
                if quote:
                    df["bid"] = float(quote.bid_price)
                    df["ask"] = float(quote.ask_price)
                    df["bid_size"] = float(quote.bid_size)
                    df["ask_size"] = float(quote.ask_size)
                else:
                    df["bid"] = df["close"]
                    df["ask"] = df["close"]
                    df["bid_size"] = 0.0
                    df["ask_size"] = 0.0
            except Exception as e:
                # THAL-E-P9-103: STREAM_QUOTE_FETCH_FAILURE
                print(f"[THAL-E-P9-103] THALAMUS: Stream snapshot failed: {e}")
                df["bid"] = df["close"]
                df["ask"] = df["close"]
                df["bid_size"] = 0.0
                df["ask_size"] = 0.0

            # Target #25 handoff: Drip the real-time bar into the resampler
            self.drip_pulse(df)
            
        except Exception as e:
            # THAL-E-P25-103: Real-time bar processing failure
            print(f"[THAL-E-P25-103] THALAMUS: Real-time bar processing failed: {e}")

    def _pulse_from_db(self, symbol: str, limit: int = 50) -> pd.DataFrame:
        """
        Target #16: Logic Drift Fix.
        Restores DB pulse capability using canonical market_tape and Multi-Transport Librarian.
        """
        try:
            query = "SELECT * FROM market_tape WHERE symbol = ? ORDER BY ts DESC LIMIT ?"
            rows = self.lib.read_only(query, (symbol, limit), transport="duckdb")
            
            if not rows:
                return pd.DataFrame()
                
            # Convert DuckDB tuples back to DataFrame
            df = pd.DataFrame(rows)
            # Re-apply standard schema
            return self._normalize_bars(df, source="DATABASE", symbol_hint=symbol)
            
        except Exception as e:
            # THAL-E-P16-104: DB pulse fetch failure
            print(f"[THAL-E-P16-104] THALAMUS: DB pulse fetch failed: {e}")
            return pd.DataFrame()

    def warmup_context(self, symbols: List[str], is_crypto: bool = True):
        """
        Target #26: Buffer Warmup.
        Pulls 60m of historical 1m bars to prime the SmartGland context.
        """
        print(f"[THALAMUS] Warming up context for {symbols} (60m historical)...")
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=60)
        
        try:
            # 1. Fetch historical bars
            df = self._pulse_from_alpaca(symbols, TimeFrame.Minute, start, end, is_crypto)
            
            if not df.empty:
                # 2. Ingest into SmartGland to fill context_df
                # We ignore the returned pulses during warmup to prevent premature execution
                self.gland.ingest(df)
                print(f"   [THALAMUS] Warmup successful. Context bars: {len(self.gland.context_df)}")
            else:
                print("   [THALAMUS_WARN] Warmup returned no data. Context remains cold.")
                
        except Exception as e:
            # THAL-E-P26-105: Warmup context failure
            print(f"[THAL-E-P26-105] THALAMUS: Warmup context failed: {e}")

    def pulse(self, symbols: List[str], timeframe=TimeFrame.Minute, start=None, end=None, is_crypto=True, source="ALPACA", pulse_type="ACTION"):
        """Target #23: Timing Invariant check."""
        if not enforce_pulse_gate(pulse_type, ["SEED", "ACTION", "MINT"], "Thalamus"):
            return pd.DataFrame()

        if source == "DATABASE":
            df = self._pulse_from_db(symbols[0])
        elif source == "ALPACA":
            df = self._pulse_from_alpaca(symbols, timeframe, start, end, is_crypto)
        else:
            raise IngestionContractError("THAL-E-P21-103", f"INGEST_SOURCE_UNSUPPORTED: {source!r}")
        
        if not df.empty:
            df["pulse_type"] = pulse_type
            
            # Piece 4: Fetch Snapshot for Bid/Ask (if not historical/DB)
            if source == "ALPACA":
                try:
                    # Determine crypto status from librarian or symbols
                    snapshot = self.get_snapshot(symbols, is_crypto=is_crypto)
                    for sym in symbols:
                        quote = getattr(snapshot.get(sym), "latest_quote", None)
                        mask = df["symbol"] == sym
                        if quote:
                            df.loc[mask, "bid"] = float(quote.bid_price)
                            df.loc[mask, "ask"] = float(quote.ask_price)
                            df.loc[mask, "bid_size"] = float(quote.bid_size)
                            df.loc[mask, "ask_size"] = float(quote.ask_size)
                        else:
                            # Piece 9: Fallback
                            df.loc[mask, "bid"] = df.loc[mask, "close"]
                            df.loc[mask, "ask"] = df.loc[mask, "close"]
                            df.loc[mask, "bid_size"] = 0.0
                            df.loc[mask, "ask_size"] = 0.0
                except Exception as e:
                    # THAL-E-P4-103: QUOTE_FETCH_FAILURE (Piece 9)
                    print(f"[THAL-E-P4-103] THALAMUS: Snapshot fetch failed: {e}")
                    df["bid"] = df["close"]
                    df["ask"] = df["close"]
                    df["bid_size"] = 0.0
                    df["ask_size"] = 0.0

            if self.optical_tract:
                self.optical_tract.spray(df)
        return df

    def get_snapshot(self, symbols: List[str], is_crypto=True):
        """
        Fetches the latest Snapshot (latest trade, latest quote, current daily bar).
        V6: Crucial for live 'Action' pulse validation.
        """
        client = self.crypto_client if is_crypto else self.stock_client
        if not client: raise IngestionContractError("THAL-F-P25-101", "ALPACA_CLIENT_UNINITIALIZED")
        
        request = CryptoSnapshotRequest(symbol_or_symbols=symbols) if is_crypto else StockSnapshotRequest(symbol_or_symbols=symbols)
        return client.get_crypto_snapshot(request) if is_crypto else client.get_stock_snapshot(request)

    def get_latest_bar(self, symbol: str, is_crypto=True):
        """Returns the single latest 1m bar available for a symbol."""
        client = self.crypto_client if is_crypto else self.stock_client
        if not client: raise IngestionContractError("THAL-F-P25-101", "ALPACA_CLIENT_UNINITIALIZED")
        
        request = CryptoLatestBarRequest(symbol_or_symbols=[symbol]) if is_crypto else StockLatestBarRequest(symbol_or_symbols=[symbol])
        return client.get_crypto_latest_bar(request) if is_crypto else client.get_stock_latest_bar(request)

    def get_state(self) -> Dict[str, Any]:
        """Exposes ingestion events and SmartGland telemetry."""
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
        print(f"DEBUG: drip_pulse got {len(pulses)} pulses: {[p[0] for p in pulses]}")
        normalized_pulses = []
        for pulse_type, agg_df in pulses:
            # Target #23: Timing Invariant check
            if not enforce_pulse_gate(pulse_type, ["SEED", "ACTION", "MINT"], "Thalamus"):
                continue

            normalized_agg = self._normalize_bars(
                agg_df,
                source="SMARTGLAND",
                passthrough_cols=["pulse_type"],
            )

            # Piece 4: Fetch Snapshot for Bid/Ask in live drip
            if not normalized_agg.empty:
                try:
                    symbol = normalized_agg["symbol"].iloc[-1]
                    # Logic to determine is_crypto - typically stored in Thalamus state or symbol-based
                    # For Piece 4, we use symbol-based heuristic if not explicit
                    is_crypto = "/" in symbol or len(symbol) > 6 
                    snapshot = self.get_snapshot([symbol], is_crypto=is_crypto)
                    quote = getattr(snapshot.get(symbol), "latest_quote", None)
                    if quote:
                        normalized_agg["bid"] = float(quote.bid_price)
                        normalized_agg["ask"] = float(quote.ask_price)
                        normalized_agg["bid_size"] = float(quote.bid_size)
                        normalized_agg["ask_size"] = float(quote.ask_size)
                    else:
                        # Piece 9: Fallback
                        normalized_agg["bid"] = normalized_agg["close"]
                        normalized_agg["ask"] = normalized_agg["close"]
                        normalized_agg["bid_size"] = 0.0
                        normalized_agg["ask_size"] = 0.0
                except Exception as e:
                    # THAL-E-P9-103: QUOTE_FETCH_FAILURE (Piece 9)
                    print(f"[THAL-E-P9-103] THALAMUS: Drip snapshot failed: {e}")
                    normalized_agg["bid"] = normalized_agg["close"]
                    normalized_agg["ask"] = normalized_agg["close"]
                    normalized_agg["bid_size"] = 0.0
                    normalized_agg["ask_size"] = 0.0
            
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
        if not client: raise IngestionContractError("THAL-F-P25-101", "ALPACA_CLIENT_UNINITIALIZED")
        
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

    def _normalize_bars(
        self,
        raw_df: pd.DataFrame,
        *,
        source: str,
        symbol_hint: Optional[str] = None,
        passthrough_cols: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        passthrough_cols = passthrough_cols or []

        if raw_df is None:
            self._record_ingestion_event(source, symbol_hint, 0, "error", "THAL-E-P21-104")
            raise IngestionContractError("THAL-E-P21-104", "INGEST_INPUT_NONE: input bars cannot be None")

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
                    self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-105")
                    raise IngestionContractError("THAL-E-P21-105", "INGEST_TS_INVALID: one or more timestamps are invalid")
                df = df.set_index("ts")
            elif "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                if df["timestamp"].isna().any():
                    self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-105")
                    raise IngestionContractError("THAL-E-P21-105", "INGEST_TS_INVALID: one or more timestamps are invalid")
                df = df.set_index("timestamp")
            else:
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-106")
                raise IngestionContractError("THAL-E-P21-106", "INGEST_TS_MISSING: expected DatetimeIndex or ts/timestamp column")
        else:
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            if df.index.isna().any():
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-105")
                raise IngestionContractError("THAL-E-P21-105", "INGEST_TS_INVALID: one or more index timestamps are invalid")

        if "symbol" not in df.columns:
            if symbol_hint:
                df["symbol"] = str(symbol_hint)
            else:
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-107")
                raise IngestionContractError("THAL-E-P21-107", "INGEST_SYMBOL_MISSING: missing required column: symbol")

        missing = [c for c in CANONICAL_COLS if c not in df.columns]
        if missing:
            # Piece 9: Fill missing bid/ask if other canonicals are present
            price_cols = ["bid", "ask", "bid_size", "ask_size"]
            if all(c in df.columns for c in ["open", "high", "low", "close", "volume", "symbol"]):
                for pc in price_cols:
                    if pc not in df.columns:
                        if pc in ["bid", "ask"]:
                            df[pc] = df["close"]
                        else:
                            df[pc] = 0.0
                if "pulse_type" not in df.columns:
                    df["pulse_type"] = "NONE"
            
            # Re-check missing
            missing = [c for c in CANONICAL_COLS if c not in df.columns]
            if missing:
                self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-108")
                raise IngestionContractError("THAL-E-P21-108", f"INGEST_SCHEMA_MISSING: missing required columns: {missing}")

        for col in ("open", "high", "low", "close", "volume"):
            if not pd.api.types.is_numeric_dtype(df[col]):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        if df[["open", "high", "low", "close", "volume"]].isna().any().any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-109")
            raise IngestionContractError("THAL-E-P21-109", "INGEST_NUMERIC_INVALID: numeric OHLCV fields contain null/invalid values")
        
        if (df["volume"] < 0).any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-110")
            raise IngestionContractError("THAL-E-P21-110", "INGEST_VOLUME_NEGATIVE: volume cannot be negative")

        df["symbol"] = df["symbol"].astype(str).str.strip()
        if (df["symbol"] == "").any():
            self._record_ingestion_event(source, symbol_hint, len(df), "error", "THAL-E-P21-111")
            raise IngestionContractError("THAL-E-P21-111", "INGEST_SYMBOL_INVALID: symbol cannot be blank")

        df = df.sort_index()
        if df.index.has_duplicates:
            # Piece 24: Use standardized Numba kernel for high-velocity aggregation
            print(f"[THALAMUS] Vectorized aggregation of {df.index.duplicated().sum()} duplicate timestamps.")
            
            unique_ts = df.index.unique()
            agg_rows = []
            
            # Using direct indexing for speed
            for ts in unique_ts:
                group = df.loc[[ts]]
                if len(group) == 1:
                    agg_rows.append(group.iloc[0])
                    continue
                
                vals = aggregate_ohlcv_njit(
                    group["open"].to_numpy(dtype=np.float64),
                    group["high"].to_numpy(dtype=np.float64),
                    group["low"].to_numpy(dtype=np.float64),
                    group["close"].to_numpy(dtype=np.float64),
                    group["volume"].to_numpy(dtype=np.float64)
                )
                res = group.iloc[-1].copy()
                res["open"], res["high"], res["low"], res["close"], res["volume"] = vals
                agg_rows.append(res)
            
            df = pd.DataFrame(agg_rows)
            df = df.set_index("ts") if "ts" in df.columns else df

        keep_cols = CANONICAL_COLS + [c for c in passthrough_cols if c in df.columns]
        out = df[keep_cols].copy()
        out.index.name = "ts"
        self._record_ingestion_event(source, out["symbol"].iloc[-1] if not out.empty else symbol_hint, len(out), "ok")
        return out

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
