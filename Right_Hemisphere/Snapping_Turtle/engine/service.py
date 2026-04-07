import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Any
from Cerebellum.Soul.brain_frame import BrainFrame

class SnappingTurtle:
    """
    Tier 1: The Snapping Turtle (FAST SLIDE).
    V3 Optimization: Zero-Copy state updates via BrainFrame.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.last_paint_event: Dict[str, Any] = {}

    def on_data_received(self, pulse_type: str, frame: BrainFrame):
        """
        Processes pulse by reading frame.market and updating frame.structure.
        """
        if frame is None:
            raise TypeError("on_data_received requires BrainFrame")

        df = frame.market.ohlcv
        active_gear = self._resolve_active_gear(frame)

        if active_gear <= 0:
            self._safe_reset(frame, active_gear, status="invalid_gear")
            return None, []

        if not isinstance(df, pd.DataFrame) or df.empty:
            self._safe_reset(frame, active_gear, status="empty_frame")
            return None, []

        required_cols = ("high", "low", "close")
        if not set(required_cols).issubset(set(df.columns)):
            self._safe_reset(frame, active_gear, status="schema_mismatch")
            return None, []

        try:
            highs = pd.to_numeric(df["high"], errors="raise").to_numpy(dtype=float)
            lows = pd.to_numeric(df["low"], errors="raise").to_numpy(dtype=float)
            closes = pd.to_numeric(df["close"], errors="raise").to_numpy(dtype=float)
        except Exception:
            self._safe_reset(frame, active_gear, status="non_numeric_ohlc")
            return None, []

        if len(df) < active_gear:
            self._safe_reset(frame, active_gear, status="insufficient_history")
            if len(closes) > 0:
                frame.structure.price = float(closes[-1])
            return None, []

        active_hi = np.max(highs[-active_gear:])
        active_lo = np.min(lows[-active_gear:])
        prev_active_hi = np.max(highs[-(active_gear + 1):-1]) if len(highs) > active_gear else highs[0]
        current_close = float(closes[-1])
        tier1_signal = 1 if current_close > prev_active_hi else 0

        frame.structure.active_hi = float(active_hi)
        frame.structure.active_lo = float(active_lo)
        frame.structure.gear = active_gear
        frame.structure.tier1_signal = int(tier1_signal)
        frame.structure.price = current_close

        strikes = []
        if tier1_signal == 1:
            strikes.append(
                {
                    "time_index": str(frame.market.ts),
                    "price": current_close,
                    "ceiling": float(prev_active_hi),
                    "floor": float(active_lo),
                    "gear": int(active_gear),
                    "pulse_type": str(pulse_type),
                }
            )

        self.last_paint_event = {
            "status": "painted",
            "pulse_type": str(pulse_type),
            "gear_used": int(active_gear),
            "signal_outcome": int(tier1_signal),
            "row_count": int(len(df)),
            "strike_count": int(len(strikes)),
        }
        return df, strikes

    def _resolve_active_gear(self, frame: BrainFrame) -> int:
        if "active_gear" in self.config:
            return int(self.config["active_gear"])
        if isinstance(frame.standards, dict) and "active_gear" in frame.standards:
            return int(frame.standards["active_gear"])
        return 0

    def _safe_reset(self, frame: BrainFrame, active_gear: int, *, status: str) -> None:
        frame.structure.active_hi = 0.0
        frame.structure.active_lo = 0.0
        frame.structure.gear = int(active_gear)
        frame.structure.tier1_signal = 0
        if frame.structure.price is None:
            frame.structure.price = 0.0
        self.last_paint_event = {
            "status": str(status),
            "pulse_type": str(frame.market.pulse_type),
            "gear_used": int(active_gear),
            "signal_outcome": 0,
            "row_count": int(len(frame.market.ohlcv)) if isinstance(frame.market.ohlcv, pd.DataFrame) else 0,
            "strike_count": 0,
        }

    def get_state(self):
        return {"last_paint_event": dict(self.last_paint_event)}
