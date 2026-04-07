from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np
import hashlib
from datetime import datetime

@dataclass
class MarketDataSlot:
    ts: Any = None
    symbol: str = "UNKNOWN"
    ohlcv: pd.DataFrame = field(default_factory=pd.DataFrame)
    pulse_type: str = "NONE"
    execution_mode: str = "DRY_RUN"

@dataclass
class StructureSlot:
    active_hi: float = 0.0
    active_lo: float = 0.0
    gear: int = 0
    tier1_signal: int = 0
    price: float = 0.0

@dataclass
class RiskSlot:
    mu: float = 0.0
    sigma: float = 0.0
    p_jump: float = 0.0
    shocks: List[float] = field(default_factory=list)
    monte_score: float = 0.0
    tier_score: float = 0.0
    regime_id: str = "UNK"
    mutations: List[float] = field(default_factory=list)
    worst_survival: float = 0.0
    neutral_survival: float = 0.0
    best_survival: float = 0.0
    lane_survivals: List[float] = field(default_factory=list)

@dataclass
class EnvironmentSlot:
    confidence: float = 0.0
    atr: float = 0.0
    atr_avg: float = 0.0
    adx: float = 0.0
    volume_score: float = 0.0

@dataclass
class CommandSlot:
    approved: int = 0
    reason: str = "INIT"
    final_confidence: float = 0.0
    sizing_mult: float = 0.0
    ready_to_fire: bool = False

class BrainFrame:
    """
    Cerebellum/Soul: The Brain Frame.
    
    The single source of truth for the current pulse.
    Zero-copy architecture: Lobes update their slots by reference.
    """
    def __init__(self):
        self.market = MarketDataSlot()
        self.structure = StructureSlot()
        self.risk = RiskSlot()
        self.environment = EnvironmentSlot()
        self.command = CommandSlot()
        self.standards = {} # Mirrored Gold Params

    def reset_pulse(self, pulse_type: str):
        """Clears ephemeral decision state while preserving context."""
        self.market.pulse_type = pulse_type
        self.command.ready_to_fire = False
        self.command.approved = 0
        self.command.reason = "WAITING"

    def generate_machine_code(self) -> str:
        """
        Generates a deterministic identity for this frame snapshot.
        Includes mode, pulse, symbol, regime, decision, and normalized timestamp.
        """
        ts_str = ""
        if hasattr(self.market.ts, "isoformat"):
            ts_str = self.market.ts.isoformat()
        else:
            ts_str = str(self.market.ts)

        # Stable composition components
        components = [
            str(self.market.execution_mode),
            str(self.market.pulse_type),
            str(self.market.symbol),
            str(self.risk.regime_id),
            str(self.command.reason),
            ts_str
        ]
        raw_id = "|".join(components)
        return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
        
    def to_synapse_dict(self) -> Dict[str, Any]:
        """
        Flattens the frame for the Amygdala ticket.
        V3.2 COMPLETE STATE: Every MINT captures the full engine snapshot + price action.
        """
        return {
            # Meta
            "machine_code": self.generate_machine_code(),
            # Price Action (OHLCV)
            "ts": self.market.ts,
            "symbol": self.market.symbol,
            "pulse_type": self.market.pulse_type,
            "execution_mode": self.market.execution_mode,
            "open": self.market.ohlcv['open'].iloc[-1] if not self.market.ohlcv.empty else 0,
            "high": self.market.ohlcv['high'].iloc[-1] if not self.market.ohlcv.empty else 0,
            "low": self.market.ohlcv['low'].iloc[-1] if not self.market.ohlcv.empty else 0,
            "close": self.market.ohlcv['close'].iloc[-1] if not self.market.ohlcv.empty else 0,
            "volume": self.market.ohlcv['volume'].iloc[-1] if not self.market.ohlcv.empty else 0,
            # Structure (Right Hemisphere)
            "price": self.structure.price,
            "active_hi": self.structure.active_hi,
            "active_lo": self.structure.active_lo,
            "gear": self.structure.gear,
            "tier1_signal": self.structure.tier1_signal,
            # Risk (Left Hemisphere + Corpus)
            "mu": self.risk.mu,
            "sigma": self.risk.sigma,
            "p_jump": self.risk.p_jump,
            "monte_score": self.risk.monte_score,
            "tier_score": self.risk.tier_score,
            "regime_id": self.risk.regime_id,
            "worst_survival": self.risk.worst_survival,
            "neutral_survival": self.risk.neutral_survival,
            "best_survival": self.risk.best_survival,
            # Environment (Council)
            "council_score": self.environment.confidence,
            "atr": self.environment.atr,
            "atr_avg": self.environment.atr_avg,
            "adx": self.environment.adx,
            "volume_score": self.environment.volume_score,
            # Command (Gatekeeper)
            "decision": self.command.reason,
            "approved": self.command.approved,
            "final_confidence": self.command.final_confidence,
            "sizing_mult": self.command.sizing_mult,
            "ready_to_fire": int(self.command.ready_to_fire)
        }
