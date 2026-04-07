from dataclasses import dataclass
from typing import Dict, Any, Tuple
import math
from Hippocampus.Archivist.librarian import Librarian
from Cerebellum.Soul.brain_frame import BrainFrame


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
        self.librarian = Librarian()
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

        self._log_score(
            pulse_type=pulse,
            tier_id=1,
            signal_type="AMBUSH",
            monte=monte_score,
            tier=tier_score,
            signal_strength=signal_strength,
            trace="CALL0SUM_V2_RUNTIME",
            w_monte=w_monte,
            w_right=w_right,
        )
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
        try:
            parsed = float(value)
        except Exception:
            return float(default)
        if not math.isfinite(parsed):
            return float(default)
        return parsed

    def _clamp(self, value: float, low: float, high: float) -> float:
        if value < low:
            return low
        if value > high:
            return high
        return value

    def _log_score(
        self,
        *,
        pulse_type: str,
        tier_id: int,
        signal_type: str,
        monte: float,
        tier: float,
        signal_strength: float,
        trace: str,
        w_monte: float,
        w_right: float,
    ) -> None:
        try:
            self.librarian.dispatch("""
                INSERT INTO callosum_mint(
                    mode, tier_id, signal_type, monte_score, tier_score,
                    signal_strength, adx_val, weakness_val,
                    w_monte, w_right_hemi, w_adx_bias, w_weakness_bias, trace, pulse_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.mode,
                tier_id,
                signal_type,
                monte,
                tier,
                signal_strength,
                0.5,
                0.5,
                w_monte,
                w_right,
                float(self.config.get("callosum_w_adx", 0.0)),
                float(self.config.get("callosum_w_weak", 0.0)),
                trace,
                pulse_type
            ))
        except Exception:
            # Logging failure must not break runtime scoring.
            pass

    def get_state(self):
        return {}
