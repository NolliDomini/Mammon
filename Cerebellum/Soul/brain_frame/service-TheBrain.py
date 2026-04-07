import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from Hippocampus.Archivist.librarian import librarian


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
    bid_ask_bps: float = 0.0 # Piece 20
    spread_score: float = 0.0 # Piece 21
    spread_regime: str = "UNKNOWN" # Piece 22
    spread_inputs: dict = field(default_factory=dict) # Piece 23

@dataclass
class ValuationSlot:
    """Piece 24: Mean-Reversion Valuation Metrics."""
    mean: float = 0.0
    std_dev: float = 0.0
    upper_band: float = 0.0
    lower_band: float = 0.0
    z_distance: float = 0.0
    valuation_source: str = "NONE"

@dataclass
class ExecutionSlot:
    """Piece 26: Pre-trade Friction (Pons)."""
    expected_slippage_bps: float = 0.0
    expected_fee_bps: float = 0.0
    total_cost_bps: float = 0.0
    cost_inputs: dict = field(default_factory=dict)

@dataclass
class CommandSlot:
    approved: int = 0
    reason: str = "INIT"
    final_confidence: float = 0.0
    sizing_mult: float = 0.0
    ready_to_fire: bool = False
    qty: float = 0.0 # Piece 28
    notional: float = 0.0 # Piece 29
    size_reason: str = "NONE" # Piece 30
    risk_used: float = 0.0 # Piece 31
    cost_adjusted_conviction: float = 0.0 # Piece 32

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
        self.valuation = ValuationSlot() # Piece 25
        self.execution = ExecutionSlot() # Piece 27
        self.command = CommandSlot()
        self.standards = {} # Mirrored Gold Params

    def reset_pulse(self, pulse_type: str):
        """Clears ephemeral decision state while preserving context."""
        self.market.pulse_type = pulse_type
        
        # Piece 33: Reset spread fields
        self.environment.bid_ask_bps = 0.0
        self.environment.spread_score = 0.0
        self.environment.spread_regime = "UNKNOWN"
        self.environment.spread_inputs = {}
        
        # Piece 33: Reset new slots
        self.valuation = ValuationSlot()
        self.execution = ExecutionSlot()
        
        # Piece 33: Reset allocation fields
        self.command.ready_to_fire = False
        self.command.approved = 0
        self.command.reason = "WAITING"
        self.command.qty = 0.0
        self.command.notional = 0.0
        self.command.size_reason = "NONE"
        self.command.risk_used = 0.0
        self.command.cost_adjusted_conviction = 0.0

    def check_in(self):
        """Piece 114: Sub-millisecond Redis Check-In."""
        redis = librarian.get_redis_connection()
        mode = str(self.market.execution_mode).upper()
        symbol = str(self.market.symbol).upper()
        key = f"mammon:brain_frame:{mode}:{symbol}"
        
        # Flatten for Redis (excluding DataFrames which need special handling)
        payload = self.to_synapse_dict()
        
        # Convert timestamp to ISO for JSON
        if hasattr(payload.get("ts"), "isoformat"):
            payload["ts"] = payload["ts"].isoformat()
            
        redis.set(key, json.dumps(payload))
        # Set a 60s TTL - BrainFrame is highly ephemeral
        redis.expire(key, 60)

    @classmethod
    def check_out(cls, symbol: str, mode: str) -> Optional['BrainFrame']:
        """Piece 114: Sub-millisecond Redis Check-Out."""
        redis = librarian.get_redis_connection()
        mode = str(mode).upper()
        symbol = str(symbol).upper()
        key = f"mammon:brain_frame:{mode}:{symbol}"
        
        data_json = redis.get(key)
        if not data_json:
            return None
            
        payload = json.loads(data_json)
        frame = cls()
        
        # Hydrate Market Slot
        frame.market.symbol = payload.get("symbol", "UNKNOWN")
        frame.market.execution_mode = payload.get("execution_mode", "DRY_RUN")
        frame.market.pulse_type = payload.get("pulse_type", "NONE")
        frame.market.ts = payload.get("ts")
        
        # Hydrate Structure Slot
        frame.structure.price = float(payload.get("price", 0.0))
        frame.structure.active_hi = float(payload.get("active_hi", 0.0))
        frame.structure.active_lo = float(payload.get("active_lo", 0.0))
        frame.structure.gear = int(payload.get("gear", 0))
        frame.structure.tier1_signal = int(payload.get("tier1_signal", 0))
        
        # Hydrate Risk Slot
        frame.risk.mu = float(payload.get("mu", 0.0))
        frame.risk.sigma = float(payload.get("sigma", 0.0))
        frame.risk.p_jump = float(payload.get("p_jump", 0.0))
        frame.risk.monte_score = float(payload.get("monte_score", 0.0))
        frame.risk.tier_score = float(payload.get("tier_score", 0.0))
        frame.risk.regime_id = str(payload.get("regime_id", "UNK"))
        frame.risk.worst_survival = float(payload.get("worst_survival", 0.0))
        frame.risk.neutral_survival = float(payload.get("neutral_survival", 0.0))
        frame.risk.best_survival = float(payload.get("best_survival", 0.0))
        
        # Hydrate Environment Slot
        frame.environment.confidence = float(payload.get("council_score", 0.0))
        frame.environment.atr = float(payload.get("atr", 0.0))
        frame.environment.atr_avg = float(payload.get("atr_avg", 0.0))
        frame.environment.adx = float(payload.get("adx", 0.0))
        frame.environment.volume_score = float(payload.get("volume_score", 0.0))
        frame.environment.bid_ask_bps = float(payload.get("bid_ask_bps", 0.0)) # Piece 41
        frame.environment.spread_score = float(payload.get("spread_score", 0.0)) # Piece 41
        frame.environment.spread_regime = str(payload.get("spread_regime", "UNKNOWN")) # Piece 41
        
        # Hydrate Valuation Slot (Piece 41)
        frame.valuation.mean = float(payload.get("val_mean", 0.0))
        frame.valuation.std_dev = float(payload.get("val_std_dev", 0.0))
        frame.valuation.z_distance = float(payload.get("val_z_distance", 0.0))
        
        # Hydrate Execution Slot (Piece 41)
        frame.execution.expected_slippage_bps = float(payload.get("exec_expected_slippage_bps", 0.0))
        frame.execution.total_cost_bps = float(payload.get("exec_total_cost_bps", 0.0))
        
        # Hydrate Command Slot
        frame.command.reason = str(payload.get("decision", "INIT"))
        frame.command.approved = int(payload.get("approved", 0))
        frame.command.final_confidence = float(payload.get("final_confidence", 0.0))
        frame.command.sizing_mult = float(payload.get("sizing_mult", 0.0))
        frame.command.ready_to_fire = bool(payload.get("ready_to_fire", False))
        frame.command.qty = float(payload.get("qty", 0.0)) # Piece 41
        frame.command.notional = float(payload.get("notional", 0.0)) # Piece 41
        frame.command.cost_adjusted_conviction = float(payload.get("cost_adjusted_conviction", 0.0)) # Piece 41
        
        return frame

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
        last_bar = {}
        if self.market.ohlcv is not None and not self.market.ohlcv.empty:
            last_row = self.market.ohlcv.iloc[-1]
            last_bar = {
                "open": float(last_row.get("open", 0.0)),
                "high": float(last_row.get("high", 0.0)),
                "low": float(last_row.get("low", 0.0)),
                "close": float(last_row.get("close", 0.0)),
                "volume": float(last_row.get("volume", 0.0)),
                # I6 fix: passthrough bid/ask for DuckDB persistence
                "bid": float(last_row.get("bid", 0.0)),
                "ask": float(last_row.get("ask", 0.0)),
                "bid_size": float(last_row.get("bid_size", 0.0)),
                "ask_size": float(last_row.get("ask_size", 0.0)),
            }

        return {
            # Meta
            "machine_code": self.generate_machine_code(),
            # Price Action (OHLCV)
            "ts": self.market.ts,
            "symbol": self.market.symbol,
            "pulse_type": self.market.pulse_type,
            "execution_mode": self.market.execution_mode,
            **last_bar,
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
            "bid_ask_bps": self.environment.bid_ask_bps, # Piece 40
            "spread_score": self.environment.spread_score, # Piece 40
            "spread_regime": self.environment.spread_regime, # Piece 40
            # Valuation (Piece 40)
            "val_mean": self.valuation.mean,
            "val_std_dev": self.valuation.std_dev,
            "val_z_distance": self.valuation.z_distance,
            # Execution (Piece 40)
            "exec_expected_slippage_bps": self.execution.expected_slippage_bps,
            "exec_total_cost_bps": self.execution.total_cost_bps,
            # Command (Gatekeeper)
            "decision": self.command.reason,
            "approved": self.command.approved,
            "final_confidence": self.command.final_confidence,
            "sizing_mult": self.command.sizing_mult,
            "ready_to_fire": int(self.command.ready_to_fire),
            "qty": self.command.qty, # Piece 40
            "notional": self.command.notional, # Piece 40
            "cost_adjusted_conviction": self.command.cost_adjusted_conviction # Piece 40
        }
