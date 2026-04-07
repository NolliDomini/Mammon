from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import math
from Hippocampus.Archivist.librarian import Librarian
from Cerebellum.Soul.brain_frame import BrainFrame


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


@dataclass
class SignalPackage:
    """
    Medulla: Signal Package.
    Wraps signal data from the hemispheres for Gatekeeper consumption.
    """
    signal_type: str = "NONE"
    strength: float = 0.0
    tier_id: int = 0
    pulse_type: str = ""
    tier_score: float = 0.0
    monte_score: float = 0.0
    council_score: float = 0.0
    # Legacy compatibility fields
    tier: int = 0
    indicators: Dict[str, Any] = field(default_factory=dict)
    monte_survival_rates: Any = field(default_factory=list)
    df_context: Optional[pd.DataFrame] = None

class Gatekeeper:
    """
    Medulla: The Gatekeeper.
    V3 Optimization: Reads from frame.risk/environment, writes to frame.command.
    """
    def __init__(self, config: Dict[str, Any] = None, mode: str = "LIVE"):
        self.config = config or {}
        self.mode = mode
        self.librarian = Librarian()
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
        elif pulse != "ACTION":
            ready = False
            reason = "INHIBIT_PULSE_ILLEGAL"
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

        self._log_decision(frame.command, tier_score, council_score, min_tier, min_council, pulse)
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

    def evaluate(self, signal: SignalPackage):
        # Legacy API retained for compatibility tests only (not runtime path).
        if signal is None:
            return FiringSolution(reason="INHIBITED_NONE")
        council_score = float(getattr(signal, "council_score", 0.0) or 0.0)
        if council_score <= 0.0:
            df_context = getattr(signal, "df_context", None)
            if isinstance(df_context, pd.DataFrame) and not df_context.empty:
                try:
                    adx = float(df_context.get("adx", pd.Series([25.0])).iloc[-1])
                    vol = float(df_context.get("volume", pd.Series([1.0])).iloc[-1])
                    vol_avg = float(df_context.get("vol_avg", pd.Series([1.0])).iloc[-1])
                    adx_score = max(0.0, min(1.0, adx / 50.0))
                    vol_score = max(0.0, min(1.0, (vol / max(vol_avg, 1e-9)) / 2.0))
                    council_score = (adx_score * 0.6) + (vol_score * 0.4)
                except Exception:
                    council_score = 0.0

        rates = np.array(getattr(signal, "monte_survival_rates", []), dtype=float)
        if rates.size:
            tier_score = float(np.mean(rates))
        else:
            tier_score = float(getattr(signal, "tier_score", getattr(signal, "monte_score", 0.0)) or 0.0)

        min_tier = float(self.config.get("gatekeeper_min_monte", 0.6))
        min_council = float(self.config.get("gatekeeper_min_council", 0.5))
        approved = bool(tier_score > min_tier and council_score > min_council)
        conf = float((tier_score + council_score) / 2.0)
        return FiringSolution(
            ready_to_fire=approved,
            approved=1 if approved else 0,
            reason="APPROVED" if approved else "INHIBITED_ACTION",
            final_confidence=conf,
            confidence_score=conf,
            sizing_mult=conf if approved else 0.0,
            tier_score=tier_score,
            council_score=council_score,
        )

    def _log_decision(self, cmd, tier_score, council_score, min_tier, min_council, pulse_type):
        try:
            self.librarian.dispatch("""
                INSERT INTO gatekeeper_mint(
                    mode, tier_id, signal_type, tier_score, council_score,
                    min_tier_score, min_council_score,
                    approved, final_confidence, sizing_mult, reason, pulse_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (self.mode, 1, 'AMBUSH', tier_score, council_score, min_tier, min_council, cmd.approved, cmd.final_confidence, cmd.sizing_mult, cmd.reason, pulse_type))
        except Exception:
            pass

    def get_state(self): return {}
