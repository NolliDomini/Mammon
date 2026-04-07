import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import deque

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
        self.seed_offset_min = 2.25
        self.action_offset_min = 4.5
        
        # Buffers
        self.raw_list: List[dict] = [] # Efficient list-based accumulation
        self.context_df = pd.DataFrame() # Buffer for trailing 5m aggregated bars
        self.current_window_start: Optional[datetime] = None
        self._seed_fired = False
        self._action_fired = False

        # Telemetry (Piece 13)
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

    def _elapsed_minutes_for_marks(self, window_slice: pd.DataFrame, window_start: pd.Timestamp):
        """
        Computes elapsed minutes for pulse markers.
        If bars are minute-aligned (HH:MM:00), treat timestamps as bar-open times and
        shift by +1 minute to evaluate close-time offsets (enables 2.25/4.5 on 1m bars).
        """
        idx = window_slice.index
        if len(idx) == 0:
            return np.array([])
        is_minute_aligned = bool((idx.second == 0).all() and (idx.microsecond == 0).all())
        effective_idx = idx + pd.Timedelta(minutes=1) if is_minute_aligned else idx
        return (effective_idx - window_start).total_seconds() / 60.0

    def ingest(self, raw_df: pd.DataFrame) -> List[Tuple[str, pd.DataFrame]]:
        """
        Ingests a block of 1m bars and yields sequential pulses (VECTORIZED).
        """
        if raw_df is None or raw_df.empty: return []

        # 1. Schema Validation (Piece 13)
        required_cols = {"open", "high", "low", "close", "volume", "symbol"}
        if not required_cols.issubset(set(raw_df.columns)):
            self.telemetry["malformed_payloads_skipped"] += 1
            return []

        # Ensure numeric OHLCV
        for col in ["open", "high", "low", "close", "volume"]:
            if not pd.api.types.is_numeric_dtype(raw_df[col]):
                try:
                    raw_df[col] = pd.to_numeric(raw_df[col], errors='coerce')
                except Exception:
                    self.telemetry["malformed_payloads_skipped"] += 1
                    return []
        
        if raw_df[["open", "high", "low", "close", "volume"]].isna().any().any():
            self.telemetry["malformed_payloads_skipped"] += 1
            return []

        if (raw_df["volume"] < 0).any():
            self.telemetry["malformed_payloads_skipped"] += 1
            return []

        pulses = []
        if not isinstance(raw_df.index, pd.DatetimeIndex):
            raw_df.index = pd.to_datetime(raw_df.index)
        
        raw_df = raw_df.sort_index()
        
        # Vectorized pulse detection
        window_boundaries = raw_df.index.floor(f'{self.window_minutes}Min')

        # Iterate only through the block's unique windows
        unique_windows = window_boundaries.unique()
        
        for window_start in unique_windows:
            window_mask = (window_boundaries == window_start)
            window_slice = raw_df[window_mask]
            
            # 1. Detect MINT (Crossing boundary into new window)
            if self.current_window_start is not None and window_start > self.current_window_start:
                if self.raw_list:
                    # Materialize ONLY for aggregation
                    temp_mint_df = pd.DataFrame([x[1:] for x in self.raw_list], index=[x[0] for x in self.raw_list], columns=window_slice.columns)
                    mint_agg = self._agg_window(temp_mint_df)
                    if not mint_agg.empty:
                        pulses.append(("MINT", self._wrap_with_context(mint_agg, "MINT")))
                        self.context_df = pd.concat([self.context_df, mint_agg]).tail(self.context_size)
                        self.telemetry["mint_emitted"] += 1
                self.raw_list = []
                self._reset_window_markers()
            
            # 2. Update window tracking
            if self.current_window_start is not None and window_start < self.current_window_start:
                # Ignore stale bars from an already finalized window.
                continue
            self.current_window_start = window_start
            self.telemetry["last_window_processed"] = window_start.isoformat()
            
            # 3. Detect SEED (>=2.25m) and ACTION (>=4.5m) with once-per-window guards.
            slice_elapsed = self._elapsed_minutes_for_marks(window_slice, window_start)
            all_marks = []

            if not self._seed_fired:
                seed_marks = window_slice.index[slice_elapsed >= self.seed_offset_min]
                if len(seed_marks) > 0:
                    all_marks.append((seed_marks[0], "SEED"))

            if not self._action_fired:
                action_marks = window_slice.index[slice_elapsed >= self.action_offset_min]
                if len(action_marks) > 0:
                    all_marks.append((action_marks[0], "ACTION"))

            all_marks = sorted(all_marks, key=lambda x: x[0])
            
            # Process pulses within this window slice
            last_ts = None
            for mark_ts, pulse_type in all_marks:
                # Add bars from this slice up to the pulse mark
                sub_slice = window_slice.loc[window_slice.index <= mark_ts]
                if last_ts is not None:
                    sub_slice = sub_slice.loc[sub_slice.index > last_ts]
                
                # V3 NEURAL VELOCITY: Zero iterrows. Append directly to list.
                if not sub_slice.empty:
                    self.raw_list.extend(list(sub_slice.itertuples(index=True, name=None)))
                
                last_ts = mark_ts
                
                # Materialize current window state for aggregation
                temp_df = pd.DataFrame([x[1:] for x in self.raw_list], index=[x[0] for x in self.raw_list], columns=window_slice.columns)
                agg = self._agg_window(temp_df)
                pulses.append((pulse_type, self._wrap_with_context(agg, pulse_type)))
                if pulse_type == "SEED":
                    self._seed_fired = True
                    self.telemetry["seed_emitted"] += 1
                elif pulse_type == "ACTION":
                    self._action_fired = True
                    self.telemetry["action_emitted"] += 1

            # Finally, add the remainder of the window_slice to raw_list
            remainder = window_slice
            if last_ts is not None:
                remainder = remainder.loc[remainder.index > last_ts]
            
            if not remainder.empty:
                self.raw_list.extend(list(remainder.itertuples(index=True, name=None)))

        return pulses

    def _agg_window(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregates raw 1m bars into a single 5m row."""
        if df.empty: return pd.DataFrame()
        
        agg = pd.DataFrame([{
            'open': df['open'].iloc[0],
            'high': df['high'].max(),
            'low': df['low'].min(),
            'close': df['close'].iloc[-1],
            'volume': df['volume'].sum(),
            'symbol': df['symbol'].iloc[0]
        }])
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
            "raw_buffer_len": len(self.raw_list),
            "telemetry": self.telemetry
        }
