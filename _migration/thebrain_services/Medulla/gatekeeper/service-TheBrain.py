from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import math
import time
from datetime import datetime

import numpy as np
import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian


@dataclass
class FiringSolution:
    """
    Medulla: Firing Solution.
    The final output of the Gatekeeper decision process.
    Consumed by Brain_Stem/trigger.py for order execution.
    """
    ready_to_fire: bool = False
    approved: int = 0
    reason: str = "PENDING"
    final_confidence: float = 0.0
    sizing_mult: float = 0.0
    tier_score: float = 0.0
    council_score: float = 0.0
    confidence_score: float = 0.0


class Gatekeeper:
    """
    Medulla: The Gatekeeper.
    V3 Optimization: Reads from frame.risk/environment, writes to frame.command.
    """
    def __init__(self, config: Dict[str, Any] = None, mode: str = "LIVE"):
        self.config = config or {}
        self.mode = mode
        self.librarian = librarian
        self.last_telemetry: Dict[str, Any] = {}

    def decide(self, pulse_type: str, frame: BrainFrame):
        """
        Final policy decision.
        Runtime contract: decide(pulse_type, frame).
        """
        if frame is None:
            raise TypeError("decide requires frame")
        if pulse_type is None:
            raise TypeError("decide requires pulse_type")
            
        # Piece 14: Gatekeeper authority only fires at ACTION
        if not enforce_pulse_gate(pulse_type, ["ACTION"], "Gatekeeper"):
            # Inhibit by writing back to frame
            frame.command.approved = 0
            frame.command.ready_to_fire = False
            frame.command.reason = "INHIBIT_PULSE_ILLEGAL"
            return FiringSolution(
                ready_to_fire=False,
                approved=0,
                reason=str(frame.command.reason),
                final_confidence=0.0,
                confidence_score=0.0,
                sizing_mult=0.0,
            )

        pulse = str(pulse_type).upper()
        mode = str(getattr(getattr(frame, "market", None), "execution_mode", self.mode) or self.mode).upper()

        tier_score = self._sanitize_numeric(getattr(getattr(frame, "risk", None), "tier_score", 0.0), default=0.0)
        council_score = self._sanitize_numeric(getattr(getattr(frame, "environment", None), "confidence", 0.0), default=0.0)
        tier_score = self._clamp(tier_score, 0.0, 1.0)
        council_score = self._clamp(council_score, 0.0, 1.0)

        min_tier = self._resolve_threshold("gatekeeper_min_monte", mode, default=0.6)
        min_council = self._resolve_threshold("gatekeeper_min_council", mode, default=0.5)
        cmp_mode = str(self.config.get("gatekeeper_threshold_cmp", ">")).strip()

        mode_ok = mode in {"DRY_RUN", "PAPER", "LIVE", "BACKTEST"}
        inputs_ok = math.isfinite(tier_score) and math.isfinite(council_score)

        if not mode_ok:
            ready = False
            reason = "INHIBIT_MODE_GATE"
        elif not inputs_ok:
            ready = False
            reason = "INHIBIT_SAFETY_GATE"
        else:
            tier_pass = self._passes_threshold(tier_score, min_tier, cmp_mode)
            council_pass = self._passes_threshold(council_score, min_council, cmp_mode)
            if tier_pass and council_pass:
                ready = True
                reason = "APPROVED"
            elif not tier_pass:
                ready = False
                reason = "INHIBIT_THRESHOLD_TIER"
            else:
                ready = False
                reason = "INHIBIT_THRESHOLD_COUNCIL"

        final_conf = self._clamp((tier_score + council_score) / 2.0, 0.0, 1.0)
        sizing = self._sizing_mult(ready, final_conf)

        # Gatekeeper write boundary: frame.command only.
        frame.command.ready_to_fire = bool(ready)
        frame.command.approved = 1 if ready else 0
        frame.command.reason = reason
        frame.command.final_confidence = final_conf
        frame.command.confidence_score = final_conf
        frame.command.sizing_mult = sizing

        self.last_telemetry = {
            "pulse_type": pulse,
            "mode": mode,
            "inputs": {
                "tier_score": tier_score,
                "council_score": council_score,
                "spread_regime": str(frame.environment.spread_regime),
                "total_cost_bps": float(frame.execution.total_cost_bps),
                "cost_adjusted_conviction": float(frame.command.cost_adjusted_conviction),
            },
            "thresholds": {
                "min_tier": min_tier,
                "min_council": min_council,
                "comparator": cmp_mode,
            },
            "result": {
                "ready_to_fire": bool(ready),
                "approved": int(frame.command.approved),
                "reason": reason,
                "final_confidence": final_conf,
                "sizing_mult": sizing,
            },
        }

        return FiringSolution(
            ready_to_fire=bool(frame.command.ready_to_fire),
            approved=int(frame.command.approved),
            reason=str(frame.command.reason),
            final_confidence=float(frame.command.final_confidence),
            confidence_score=float(frame.command.final_confidence),
            sizing_mult=float(frame.command.sizing_mult),
            tier_score=float(tier_score),
            council_score=float(council_score),
        )

    def _resolve_threshold(self, base_key: str, mode: str, default: float) -> float:
        mode_key = f"{base_key}_{mode.lower()}"
        raw = self.config.get(mode_key, self.config.get(base_key, default))
        return self._clamp(self._sanitize_numeric(raw, default=default), 0.0, 1.0)

    def _passes_threshold(self, value: float, threshold: float, cmp_mode: str) -> bool:
        if cmp_mode == ">=":
            return value >= threshold
        return value > threshold

    def _sizing_mult(self, approved: bool, final_conf: float) -> float:
        if not approved:
            return 0.0
        base = self._sanitize_numeric(self.config.get("gatekeeper_sizing_mult", 1.0), default=1.0)
        return self._clamp(base, 0.0, 1.0)

    def _sanitize_numeric(self, value: Any, default: float) -> float:
        try:
            parsed = float(value)
            if not math.isfinite(parsed):
                return float(default)
            return parsed
        except Exception as e:
            # Piece 58: Standardized MNER for sanitization failure
            print(f"[MEDU-E-P58-501] GATEKEEPER_NUMERIC_SANITIZATION_FAILURE: {e}")
            return float(default)

    def _clamp(self, value: float, low: float, high: float) -> float:
        if value < low:
            return low
        if value > high:
            return high
        return value

    def get_state(self):
        """Phase 5 Target: Diagnostic visibility."""
        return {
            "last_telemetry": self.last_telemetry,
            "mode": self.mode
        }
