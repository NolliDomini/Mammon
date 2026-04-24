import math
import math
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian


@dataclass
class TierPacket:
    tier_id: int
    signal_type: str
    monte_score: float
    tier_score: float
    trace: str = "CALL0SUM_V2_RUNTIME"

class Callosum:
    """
    Corpus Callosum: deterministic tier synthesis authority.
    Runtime contract: score_tier(pulse_type, frame)
    """
    def __init__(self, config: Dict[str, Any] = None, mode: str = "LIVE"):
        self.config = config or {}
        self.mode = mode
        self.librarian = librarian
        self.last_telemetry: Dict[str, Any] = {}

    def score_tier(self, pulse_type: str, frame: BrainFrame):
        """
        Deterministic synthesis:
          raw = (w_monte * monte_score) + (w_right * tier1_signal)
          tier_score = clamp(raw, 0.0, 1.0)
        """
        if frame is None:
            raise TypeError("score_tier requires frame")
        if pulse_type is None:
            raise TypeError("score_tier requires pulse_type")

        # Piece 14: Corpus authority only fires at ACTION
        if not enforce_pulse_gate(pulse_type, ["ACTION"], "Corpus"):
            return None

        pulse = str(pulse_type)
        monte_score, signal_strength = self._read_inputs(frame)
        w_monte, w_right = self._read_weights()
        raw_score = (monte_score * w_monte) + (signal_strength * w_right)
        tier_score = self._clamp(raw_score, 0.0, 1.0)

        # Callosum authority: synthesis-only write.
        frame.risk.tier_score = tier_score

        self.last_telemetry = {
            "trace": "CALL0SUM_V2_RUNTIME",
            "pulse_type": pulse,
            "mode": str(self.mode),
            "inputs": {
                "monte_score": monte_score,
                "tier1_signal": signal_strength,
            },
            "weights": {
                "w_monte": w_monte,
                "w_right": w_right,
            },
            "output": {
                "raw_tier_score": raw_score,
                "tier_score": tier_score,
            },
        }

        return TierPacket(
            tier_id=1,
            signal_type="AMBUSH",
            monte_score=monte_score,
            tier_score=tier_score,
            trace="CALL0SUM_V2_RUNTIME",
        )

    def _read_inputs(self, frame: BrainFrame) -> Tuple[float, float]:
        monte_raw = getattr(getattr(frame, "risk", None), "monte_score", 0.0)
        signal_raw = getattr(getattr(frame, "structure", None), "tier1_signal", 0.0)
        monte_score = self._sanitize_numeric(monte_raw, default=0.0)
        signal_strength = self._sanitize_numeric(signal_raw, default=0.0)
        return self._clamp(monte_score, 0.0, 1.0), self._clamp(signal_strength, 0.0, 1.0)

    def _read_weights(self) -> Tuple[float, float]:
        w_monte = self._sanitize_numeric(self.config.get("callosum_w_monte", 1.0), default=1.0)
        w_right = self._sanitize_numeric(self.config.get("callosum_w_right", 0.0), default=0.0)
        return max(0.0, w_monte), max(0.0, w_right)

    def _sanitize_numeric(self, value: Any, default: float) -> float:
        """Return bounded default on invalid input to fail closed."""
        try:
            parsed = float(value)
            if not math.isfinite(parsed):
                return float(default)
            return parsed
        except Exception:
            return float(default)

    def _clamp(self, value: float, low: float, high: float) -> float:
        if value < low:
            return low
        if value > high:
            return high
        return value

    def get_state(self):
        """Phase 4: Diagnostic visibility."""
        return {
            "last_telemetry": self.last_telemetry,
            "mode": self.mode
        }
