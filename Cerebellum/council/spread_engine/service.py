import numpy as np
import pandas as pd
from typing import Dict, Any

from Hippocampus.Context.mner import emit_mner

class SpreadEngine:
    """
    Cerebellum/Council: Spread Engine (Piece 44).
    The 5th indicator. Evaluates bid/ask friction.
    """
    def __init__(self):
        self.last_telemetry = {}

    def evaluate(self, pulse_type: str, frame: Any) -> Dict[str, Any]:
        """
        Piece 44: Core evaluation contract.
        Writes to frame.environment and returns telemetry dict.
        """
        try:
            # Piece 45: Pulse Gate
            if pulse_type not in ["SEED", "ACTION"]:
                return {"status": "skipped", "reason": "pulse_gate"}

            # Piece 46: Read bid/ask from ohlcv passthrough
            df = frame.market.ohlcv
            if df.empty or "bid" not in df.columns or "ask" not in df.columns:
                return self._apply_atr_fallback(frame, "missing_inputs")

            last_row = df.iloc[-1]
            bid = float(last_row.get("bid", 0.0))
            ask = float(last_row.get("ask", 0.0))
            close = float(last_row.get("close", 0.0))
            
            # Piece 48: Invalid Quote Detection
            if bid <= 0 or ask <= 0 or ask < bid:
                # Piece 56: MNER COUNCIL-E-SPR-701
                emit_mner(
                    "COUNCIL-E-SPR-701",
                    "SPREAD_ENGINE_INVALID_QUOTE",
                    source="Cerebellum.council.spread_engine.service.SpreadEngine.evaluate",
                    details={"bid": bid, "ask": ask},
                    echo=True,
                )
                return self._apply_atr_fallback(frame, "invalid_quote")

            # Live Path
            mid = (bid + ask) / 2.0
            spread_bps = self._raw_spread_bps(bid, ask, mid)
            return self._finalize_metrics(frame, spread_bps, mid, "live_quote")
        except Exception as e:
            # Piece 59: MNER COUNCIL-E-SPR-704
            emit_mner(
                "COUNCIL-E-SPR-704",
                "SPREAD_ENGINE_RUNTIME_ERROR",
                source="Cerebellum.council.spread_engine.service.SpreadEngine.evaluate",
                details={"error": str(e)},
                echo=True,
            )
            self.last_telemetry = {"status": "error", "reason": "runtime_error"}
            # Piece 125: Neutral guard
            frame.environment.spread_score = 0.0
            return self.last_telemetry

    def _apply_atr_fallback(self, frame: Any, reason: str) -> Dict[str, Any]:
        """Piece 49: ATR Fallback logic."""
        close = float(frame.market.ohlcv["close"].iloc[-1]) if not frame.market.ohlcv.empty else 0.0
        atr = frame.environment.atr
        spread_atr_ratio = frame.standards.get("spread_atr_ratio", 0.10)
        
        atr_bps = (atr / close) * 10000.0 if close > 0 else 0.0
        spread_bps = atr_bps * spread_atr_ratio
        
        return self._finalize_metrics(frame, spread_bps, close, f"atr_fallback:{reason}")

    def _finalize_metrics(self, frame: Any, spread_bps: float, price: float, status: str) -> Dict[str, Any]:
        """Calculates final score/regime and writes to frame."""
        try:
            close = float(frame.market.ohlcv["close"].iloc[-1]) if not frame.market.ohlcv.empty else price
            atr = frame.environment.atr
            atr_bps = (atr / close) * 10000.0 if close > 0 else 0.0
            
            scalar = frame.standards.get("spread_score_scalar", 1.0)
            score = self._calculate_score(spread_bps, atr_bps, scalar)
            regime = self._calculate_regime(spread_bps, frame.standards)
            
            # Piece 53: Write to BrainFrame
            frame.environment.bid_ask_bps = float(spread_bps)
            frame.environment.spread_score = float(score)
            frame.environment.spread_regime = str(regime)
            
            self.last_telemetry = {
                "status": status,
                "spread_bps": spread_bps,
                "atr_bps": atr_bps,
                "score": score,
                "regime": regime,
                "price": price
            }
            frame.environment.spread_inputs = self.last_telemetry
            return self.last_telemetry
        except Exception as e:
            # Piece 58: MNER COUNCIL-E-SPR-703
            emit_mner(
                "COUNCIL-E-SPR-703",
                "SPREAD_ENGINE_NORMALIZATION_FAILURE",
                source="Cerebellum.council.spread_engine.service.SpreadEngine._finalize_metrics",
                details={"error": str(e)},
                echo=True,
            )
            return {"status": "error", "reason": "normalization_failure"}

    def _raw_spread_bps(self, bid: float, ask: float, mid: float) -> float:
        """Piece 47: Calculate basis point spread."""
        if mid <= 0: return 0.0
        return ((ask - bid) / mid) * 10000.0

    def _calculate_score(self, spread_bps: float, atr_bps: float, scalar: float) -> float:
        """Piece 50: Calculate normalized spread score."""
        if atr_bps <= 0: return 0.5  # M3 fix: neutral under unknown conditions
        ratio = spread_bps / (atr_bps * scalar)
        return float(1.0 - np.clip(ratio, 0.0, 1.0))

    def _calculate_regime(self, spread_bps: float, thresholds: Dict[str, float]) -> str:
        """Piece 51: Categorize the current spread friction."""
        tight = thresholds.get("spread_tight_threshold_bps", 5.0)
        normal = thresholds.get("spread_normal_threshold_bps", 15.0)
        wide = thresholds.get("spread_wide_threshold_bps", 50.0)
        
        if spread_bps <= tight: return "TIGHT"
        if spread_bps <= normal: return "NORMAL"
        if spread_bps <= wide: return "WIDE"
        return "STRESSED"

    def get_state(self) -> Dict[str, Any]:
        return self.last_telemetry
