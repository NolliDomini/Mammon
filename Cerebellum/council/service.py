import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from Cerebellum.council.utils.math_kernels import (calculate_adx_njit,
                                                   calculate_atr_njit,
                                                   calculate_vwap_njit)
from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Cerebellum.council.spread_engine import SpreadEngine
from Hippocampus.Archivist.librarian import librarian
from Hippocampus.Context.mner import emit_mner


class Council:
    """
    Cerebellum: The Council.
    Piece 12: Environment Intelligence Authority.
    - Deterministic indicator synthesis.
    - Restricted writes to frame.environment.
    """
    def __init__(self, config: Dict[str, Any] = None, mode: str = "LIVE"):
        self.config = config or {}
        self.mode = mode
        self.librarian = librarian
        self._last_results = {}
        self._last_confidence = 0.5
        self.spread_engine = SpreadEngine() # Piece 55
        
        # Telemetry (Piece 12)
        self.telemetry = {
            "last_pulse": None,
            "input_rows": 0,
            "confidence_out": 0.5,
            "status": "IDLE"
        }

    def consult(self, pulse_type: str = None, frame: BrainFrame = None):
        # Legacy compatibility: consult(df_context) -> confidence score
        if frame is None and isinstance(pulse_type, pd.DataFrame):
            return self._consult_legacy_df(pulse_type)

        if frame is None:
            raise TypeError("consult requires frame for runtime path")

        # Piece 14: Council processes all pulses for continuous situational awareness
        if not enforce_pulse_gate(pulse_type, ["SEED", "ACTION", "MINT"], "Council"):
            return 0.5

        df = frame.market.ohlcv
        row_count = len(df)
        self.telemetry["input_rows"] = row_count
        self.telemetry["last_pulse"] = str(pulse_type)

        if row_count < 2:
            self.telemetry["status"] = "INSUFFICIENT_HISTORY"
            return 0.5

        # 1. SEQUENTIAL DISPATCH (V3 OPTIMIZATION)
        results = {}
        try:
            # Piece 55: Spread Engine must run first to populate frame.environment.spread_score
            results["spread"] = self.spread_engine.evaluate(pulse_type, frame)
            
            results["atr"] = self._calculate_atr_score(df)
            results["adx"] = self._calculate_adx_score(df)
            results["vol"] = self._calculate_vol_score(df)
            results["vwap"] = self._calculate_vwap_score(df)
            self.telemetry["status"] = "SUCCESS"
        except Exception as e:
            # SOUL-E-P30-213: Main calculation failure
            emit_mner(
                "SOUL-E-P30-213",
                "COUNCIL_SEQUENTIAL_CALC_FAILED",
                source="Cerebellum.council.service.Council.consult",
                details={"error": str(e)},
                echo=True,
            )
            self.telemetry["status"] = f"ERROR:{type(e).__name__}"
            # Fallback for safety
            results = {
                "atr": {"score": 0.5, "val": 0.0, "avg": 0.0},
                "adx": {"score": 0.5, "val": 25.0, "avg": 25.0},
                "vol": {"score": 0.5, "val": 0.0, "avg": 0.0},
                "vwap": {"score": 0.5, "val": 0.0, "avg": 0.0}
            }

        # 2. INTEGRATE RESULTS (Weighted Sum)
        regime_id = self._generate_regime_id(results)
        
        # Target #88: Regime-Keyed Weight Overrides
        vault = self.librarian.get_hormonal_vault()
        weight_table = vault.get("regime_weight_table", {})
        
        override = weight_table.get(regime_id)
        if not override:
            for prefix, weights in weight_table.items():
                if regime_id.startswith(prefix):
                    override = weights
                    break
        
        if override:
            w_atr = float(override.get("w_atr", self.config.get("council_w_atr", 0.06)))
            w_adx = float(override.get("w_adx", self.config.get("council_w_adx", 0.60)))
            w_vol = float(override.get("w_vol", self.config.get("council_w_vol", 0.30)))
            w_vwap = float(override.get("w_vwap", self.config.get("council_w_vwap", 0.04)))
            w_spread = float(override.get("w_spread", self.config.get("council_w_spread", 0.15))) # Piece 54
            if override.get("trace"):
                print(f"   [COUNCIL] Applied regime override: {regime_id} -> {override['trace']}")
        else:
            w_atr = float(self.config.get("council_w_atr", 0.06))
            w_adx = float(self.config.get("council_w_adx", 0.60))
            w_vol = float(self.config.get("council_w_vol", 0.30))
            w_vwap = float(self.config.get("council_w_vwap", 0.04))
            w_spread = float(self.config.get("council_w_spread", 0.15)) # Piece 54

        # Piece 54: Blend spread_score into confidence
        spread_score = frame.environment.spread_score
        
        confidence_score = (
            (results["atr"]["score"] * w_atr) + 
            (results["adx"]["score"] * w_adx) + 
            (results["vol"]["score"] * w_vol) + 
            (results["vwap"]["score"] * w_vwap) +
            (spread_score * w_spread) # Piece 54
        )
        
        # Normalize sum
        total_w = w_atr + w_adx + w_vol + w_vwap + w_spread
        if total_w > 0:
            confidence_score /= total_w
            
        # Clamp Piece 12
        confidence_score = max(0.0, min(1.0, float(confidence_score)))

        # Update Brain Frame Slot (Piece 12 Write Boundary)
        frame.environment.confidence = confidence_score
        frame.environment.atr = float(results["atr"]["val"])
        frame.environment.atr_avg = float(results["atr"]["avg"])
        frame.environment.adx = float(results["adx"]["val"])
        frame.environment.volume_score = float(results["vol"]["score"])
        
        # Piece 11 Handoff: Write Regime ID to Risk Slot
        frame.risk.regime_id = regime_id
        
        # Cache for get_state
        self._last_results = results
        self._last_confidence = confidence_score
        self.telemetry["confidence_out"] = confidence_score

        return confidence_score

    def _generate_regime_id(self, results: Dict[str, Any]) -> str:
        """
        Piece 11: Canonical 16-character D_A_V_T Regime ID logic.
        D: Dist AVWAP | A: ATR Ratio | V: Vol Ratio | T: Trend (ADX)
        """
        # 1. D: Distance from AVWAP (Scaled -1.0 to 1.0)
        d_val = results["vwap"]["score"] # Already clamped [0,1], shifted from 0.5
        d_bin = self._bin_scaled(d_val - 0.5, bins=[-0.05, 0.0, 0.05])
        
        # 2. A: ATR Ratio (Volatility)
        a_val = results["atr"]["score"] # Ratio - 0.5
        a_bin = self._bin_scaled(a_val, bins=[0.1, 0.3, 0.6])
        
        # 3. V: Volume Ratio
        v_val = results["vol"]["score"] # Ratio / 2.0
        v_bin = self._bin_scaled(v_val, bins=[0.2, 0.4, 0.7])
        
        # 4. T: Trend Strength (ADX)
        t_val = results["adx"]["score"] # ADX / 50.0
        t_bin = self._bin_scaled(t_val, bins=[0.25, 0.5, 0.75])
        
        return f"D{d_bin}_A{a_bin}_V{v_bin}_T{t_bin}"

    def _bin_scaled(self, val: float, bins: List[float]) -> int:
        """Helper to bin scores into discrete levels [0, 1, 2, 3]."""
        for i, threshold in enumerate(bins):
            if val < threshold:
                return i
        return len(bins)

    def _consult_legacy_df(self, df: pd.DataFrame) -> float:
        if df is None or df.empty:
            return 0.0
        try:
            adx = float(df.get("adx", pd.Series([25.0])).iloc[-1])
            vol = float(df.get("volume", pd.Series([1.0])).iloc[-1])
            vol_avg = float(df.get("vol_avg", pd.Series([1.0])).iloc[-1])
            atr = float(df.get("atr", pd.Series([0.0])).iloc[-1])
            atr_avg = float(df.get("atr_avg", pd.Series([atr if atr > 0 else 1.0])).iloc[-1])

            adx_score = np.clip(adx / 50.0, 0.0, 1.0)
            vol_score = np.clip((vol / max(vol_avg, 1e-9)) / 2.0, 0.0, 1.0)
            atr_score = np.clip((atr / max(atr_avg, 1e-9)) - 0.5, 0.0, 1.0)
            confidence = float((adx_score * 0.6) + (vol_score * 0.3) + (atr_score * 0.1))
            self._last_confidence = confidence
            return confidence
        except Exception as e:
            # SOUL-W-P30-214: Council internal math fallback
            emit_mner(
                "SOUL-W-P30-214",
                "COUNCIL_LEGACY_FALLBACK",
                source="Cerebellum.council.service.Council._consult_legacy_df",
                details={"error": str(e)},
                echo=True,
            )
            return 0.0

    def get_state(self) -> Dict[str, Any]:
        """Returns the current environmental state mirrored from frame contract (Piece 12)."""
        return {
            "confidence": float(self._last_confidence),
            "atr": float(self._last_results.get("atr", {}).get("val", 0.0)),
            "atr_avg": float(self._last_results.get("atr", {}).get("avg", 0.0)),
            "adx": float(self._last_results.get("adx", {}).get("val", 25.0)),
            "volume_score": float(self._last_results.get("vol", {}).get("score", 0.5)),
            "telemetry": self.telemetry
        }

    def calculate_cortex_cache(self):
        """
        Piece 12: Centralized Indicator Authority.
        Populates the high-speed DuckDB precalc cache directly from the raw tape.
        """
        conn = self.librarian.get_duck_connection()
        conn.execute("DELETE FROM cortex_precalc")
        query = """
        INSERT INTO cortex_precalc
        WITH tr_calc AS (
            SELECT ts, symbol, close, high, low,
                GREATEST(high - low, ABS(high - LAG(close) OVER (PARTITION BY symbol ORDER BY ts)), ABS(low - LAG(close) OVER (PARTITION BY symbol ORDER BY ts))) as tr
            FROM market_tape
        )
        SELECT ts, symbol, close,
            avg(tr) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) as atr_14,
            avg(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) as mean_100,
            avg(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) + (2.0 * stddev(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW)) as upper_band,
            avg(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) - (1.5 * stddev(close) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW)) as lower_band,
            CASE WHEN (high - low) > (avg(high - low) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) * 2.0) THEN 'HighVol' ELSE 'Normal' END as regime_tag
        FROM tr_calc
        """
        conn.execute(query)

    def _calculate_atr_score(self, df: pd.DataFrame):
        # Piece 10: Use standardized Numba kernel
        window = int(self.config.get("atr_window", 14))
        avg_window = int(self.config.get("atr_avg_window", 50))

        if len(df) < avg_window: 
            return {"score": 0.0, "val": 0.0, "avg": 0.0}

        high_arr = df["high"].to_numpy(dtype=np.float64)
        low_arr = df["low"].to_numpy(dtype=np.float64)
        close_arr = df["close"].to_numpy(dtype=np.float64)
        
        atr_series = calculate_atr_njit(high_arr, low_arr, close_arr, window)
        last_atr = float(atr_series[-1])
        avg_atr = float(np.mean(atr_series[-avg_window:]))
        
        ratio = (last_atr / avg_atr) if avg_atr > 0 else 0.0
        return {"score": float(np.clip(ratio - 0.5, 0, 1)), "val": last_atr, "avg": avg_atr}

    def _calculate_adx_score(self, df: pd.DataFrame):
        # Piece 10: Use standardized Numba kernel
        window = int(self.config.get("adx_window", 14))
        if len(df) < (window * 2) + 1: 
            return {"score": 0.5, "val": 25.0, "avg": 25.0}
        
        high_arr = df["high"].to_numpy(dtype=np.float64)
        low_arr = df["low"].to_numpy(dtype=np.float64)
        close_arr = df["close"].to_numpy(dtype=np.float64)
        
        adx_series = calculate_adx_njit(high_arr, low_arr, close_arr, window)
        current_adx = float(adx_series[-1])
        
        trend_score = np.clip(current_adx / 50.0, 0, 1)
        return {"score": float(trend_score), "val": current_adx, "avg": 25.0}

    def _calculate_vol_score(self, df: pd.DataFrame):
        """Volume relative to 50-bar SMA."""
        if len(df) < 50: 
            return {"score": 0.5, "val": float(df["volume"].iloc[-1]), "avg": 1000.0}
        
        volumes = df["volume"].to_numpy(dtype=np.float64)
        last_vol = float(volumes[-1])
        avg_vol = float(np.mean(volumes[-50:]))
        ratio = (last_vol / avg_vol) if avg_vol > 0 else 1.0
        
        return {"score": float(np.clip(ratio / 2.0, 0, 1)), "val": last_vol, "avg": avg_vol}

    def _calculate_vwap_score(self, df: pd.DataFrame):
        # Piece 10: Use standardized Numba kernel
        gear = int(self.config.get("active_gear", 5))
        subset = df.tail(gear)
        
        close_arr = subset["close"].to_numpy(dtype=np.float64)
        vol_arr = subset["volume"].to_numpy(dtype=np.float64)
        
        vwap_series = calculate_vwap_njit(close_arr, vol_arr)
        vwap = float(vwap_series[-1])
        
        current_close = float(close_arr[-1])
        dist = (current_close - vwap) / (current_close * 0.01 + 1e-9)
        return {"score": float(np.clip(0.5 + dist, 0, 1)), "val": vwap, "avg": vwap}

