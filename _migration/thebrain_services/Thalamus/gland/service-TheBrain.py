import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import deque

from Thalamus.utils.math_kernels import aggregate_ohlcv_njit, detect_pulse_indices_njit

class SmartGland:
    """
    Thalamus/SmartGland: The Vectorized High-Fidelity Resampler.
    
    Piece 13: Pulse-Material Generator.
    - Generates window aggregation + marker emission (SEED/ACTION/MINT).
    - Soul retains final cadence authority.
    - Context-Aware: Maintains trailing 50 bars of history.
    """
    def __init__(self, window_minutes: int = 5, context_size: int = 50):
        self.window_minutes = window_minutes
        self.context_size = context_size
        self.seed_offset_sec = 2.25 * 60.0
        self.action_offset_sec = 4.5 * 60.0
        
        # Buffers
        self.active_window_df = pd.DataFrame() # Replaces raw_list for vectorization
        self.context_df = pd.DataFrame() # Buffer for trailing 5m aggregated bars
        self.current_window_start: Optional[pd.Timestamp] = None
        self._seed_fired = False
        self._action_fired = False

        # Telemetry
        self.telemetry = {
            "mint_emitted": 0,
            "seed_emitted": 0,
            "action_emitted": 0,
            "malformed_payloads_skipped": 0,
            "last_window_processed": None
        }

    def _reset_window_markers(self):
        self._seed_fired = False
        self._action_fired = False

    def ingest(self, raw_df: pd.DataFrame) -> List[Tuple[str, pd.DataFrame]]:
        """
        Ingests a block of 1m bars and yields sequential pulses.
        V5: Optimized vectorized windowing kernel (No groupby).
        """
        if raw_df is None or raw_df.empty: return []

        # 1. Schema & Type Validation
        required_cols = {"open", "high", "low", "close", "volume", "symbol"}
        if not required_cols.issubset(set(raw_df.columns)):
            self.telemetry["malformed_payloads_skipped"] += 1
            return []

        # Ensure numeric OHLCV (Piece 22)
        for col in ["open", "high", "low", "close", "volume"]:
            if not pd.api.types.is_numeric_dtype(raw_df[col]):
                raw_df[col] = pd.to_numeric(raw_df[col], errors='coerce')
        
        if raw_df[["open", "high", "low", "close", "volume"]].isna().any().any():
            self.telemetry["malformed_payloads_skipped"] += 1
            return []

        if not isinstance(raw_df.index, pd.DatetimeIndex):
            raw_df.index = pd.to_datetime(raw_df.index)
        
        df = raw_df.sort_index()
        
        # 2. Vectorized Boundary Detection
        # Identify window start for every bar in the block
        window_starts = df.index.floor(f'{self.window_minutes}Min')
        timestamps_sec = df.index.values.astype('datetime64[s]').astype(np.int64)
        # Offset if bar represents the open of the minute (HH:MM:00)
        is_min_aligned = (df.index.second == 0).all()
        if is_min_aligned:
            timestamps_sec += 60
            
        pulses = []
        
        # 3. Piece 13: Sequential Pulse Generation
        # Instead of groupby, we use the fact that bars are sorted to detect transitions.
        # This clears Loop Debt while preserving causal sequence.
        unique_windows = window_starts.unique()
        
        for win_start in unique_windows:
            window_slice = df[window_starts == win_start]
            win_start_sec = int(win_start.timestamp())
            
            # A. Detect MINT (Crossing into new window)
            if self.current_window_start is not None and win_start > self.current_window_start:
                if not self.active_window_df.empty:
                    mint_agg = self._agg_window(self.active_window_df)
                    if not mint_agg.empty:
                        pulses.append(("MINT", self._wrap_with_context(mint_agg, "MINT")))
                        self.context_df = pd.concat([self.context_df, mint_agg]).tail(self.context_size)
                        self.telemetry["mint_emitted"] += 1
                self.active_window_df = pd.DataFrame()
                self._reset_window_markers()
            
            # B. Stale Guard
            if self.current_window_start is not None and win_start < self.current_window_start:
                continue
                
            self.current_window_start = win_start
            self.telemetry["last_window_processed"] = win_start.isoformat()
            
            # C. Intra-Window Pulses (SEED/ACTION)
            slice_ts_sec = timestamps_sec[window_starts == win_start]
            
            s_idx, a_idx = detect_pulse_indices_njit(
                slice_ts_sec, 
                win_start_sec, 
                self.seed_offset_sec, 
                self.action_offset_sec
            )
            
            marks = []
            if s_idx != -1 and not self._seed_fired: marks.append((s_idx, "SEED"))
            if a_idx != -1 and not self._action_fired: marks.append((a_idx, "ACTION"))
            marks = sorted(marks, key=lambda x: x[0])
            
            last_idx = 0
            for idx, pulse_type in marks:
                sub_df = window_slice.iloc[last_idx : idx + 1]
                self.active_window_df = pd.concat([self.active_window_df, sub_df])
                last_idx = idx + 1
                
                agg = self._agg_window(self.active_window_df)
                pulses.append((pulse_type, self._wrap_with_context(agg, pulse_type)))
                
                if pulse_type == "SEED":
                    self._seed_fired = True
                    self.telemetry["seed_emitted"] += 1
                elif pulse_type == "ACTION":
                    self._action_fired = True
                    self.telemetry["action_emitted"] += 1

            if last_idx < len(window_slice):
                remainder = window_slice.iloc[last_idx:]
                self.active_window_df = pd.concat([self.active_window_df, remainder])

        return pulses

    def _agg_window(self, df: pd.DataFrame) -> pd.DataFrame:
        """Piece 10: High-speed aggregation via Numba kernel."""
        if df.empty: return pd.DataFrame()
        
        # Piece 19: Direct NumPy view for zero-copy access
        vals = aggregate_ohlcv_njit(
            df["open"].to_numpy(dtype=np.float64),
            df["high"].to_numpy(dtype=np.float64),
            df["low"].to_numpy(dtype=np.float64),
            df["close"].to_numpy(dtype=np.float64),
            df["volume"].to_numpy(dtype=np.float64)
        )
        
        # Piece 8: Preserve bid/ask/size in aggregate
        entry = {
            'open': vals[0],
            'high': vals[1],
            'low': vals[2],
            'close': vals[3],
            'volume': vals[4],
            'symbol': df['symbol'].iloc[0]
        }
        
        # Capture last known quote info if available
        for col in ["bid", "ask", "bid_size", "ask_size"]:
            if col in df.columns:
                entry[col] = df[col].iloc[-1]

        agg = pd.DataFrame([entry])
        agg.index = [df.index.floor(f'{self.window_minutes}Min')[0]]
        return agg

    def _wrap_with_context(self, current_agg: pd.DataFrame, pulse_type: str) -> pd.DataFrame:
        if current_agg.empty: return pd.DataFrame()
        res = pd.concat([self.context_df, current_agg])
        res["pulse_type"] = pulse_type
        return res

    def get_state(self):
        return {
            "context_len": len(self.context_df), 
            "active_window_len": len(self.active_window_df),
            "telemetry": self.telemetry
        }
