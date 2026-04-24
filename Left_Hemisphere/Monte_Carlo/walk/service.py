import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from Hippocampus.Archivist.librarian import librarian
from Hippocampus.Archivist.walk_scribe import WalkScribe

@dataclass
class WalkSeed:
    """
    Seed packet contract for the Turtle Monte engine.
    Carries regime-aware trajectory priors.
    """
    regime_id: str
    mu: float
    sigma: float
    p_jump: float
    jump_mu: float
    jump_sigma: float
    tail_mult: float
    confidence: float
    mode: str
    mutations: Optional[List[float]] = None

class QuantizedGeometricWalk:
    """
    Left Hemisphere: Quantized Geometric Walk.
    Converts Council environmental context into structured trajectory seeds.
    V3.1 HORMONAL: Discharges from the private Walk Silo.
    """
    def __init__(self, mode: str = "TEST"):
        self.mode = mode
        self.librarian = librarian
        self.scribe = None # Lazy Init with context
        self.last_walk_event: Dict[str, Any] = {}

    def calculate_regime_id(self, council_state: Dict[str, Any], price: float, atr: float) -> str:
        """Calculates the canonical regime ID from state."""
        inputs = council_state.get("inputs", {})
        close = inputs.get("close", price)
        avwap = inputs.get("avwap", close) 
        atr_curr = inputs.get("atr", atr)
        atr_avg = inputs.get("atr_avg", atr_curr)
        volume = inputs.get("volume", 0.0)
        vol_avg = inputs.get("vol_avg", volume if volume > 0 else 1.0)
        adx = inputs.get("adx", 25.0)

        dist_avwap = (close - avwap) / atr_curr if atr_curr > 0 else 0.0
        atr_ratio = atr_curr / atr_avg if atr_avg > 0 else 1.0
        vol_ratio = volume / vol_avg if vol_avg > 0 else 1.0
        trend_score = np.clip((adx - 15) / 35, 0, 1)

        bin_dist = self.bin_dist_avwap(dist_avwap)
        bin_atr = self.bin_atr_ratio(atr_ratio)
        bin_vol = self.bin_vol_ratio(vol_ratio)
        bin_trend = self.bin_trend_score(trend_score)

        return f"D{bin_dist}_A{bin_atr}_V{bin_vol}_T{bin_trend}"

    def build_seed(
        self,
        council_state: Dict[str, Any] = None,
        price: float = None,
        atr: float = None,
        pulse_type: str = "ACTION",
        run_id: str = "NA",
        frame=None,
    ) -> WalkSeed:
        """
        Ingests raw Council state and builds a calibrated WalkSeed.
        V3.1: Discharges from isolated Walk silo.
        """
        council_state = council_state or {}
        if frame is not None:
            price = float(getattr(frame.structure, "price", 0.0))
            atr = float(getattr(frame.environment, "atr", 0.0))
        price = float(price or 0.0)
        atr = float(atr or 0.0)

        regime_id = self.calculate_regime_id(council_state, price, atr)
        
        if self.scribe is None:
            self.scribe = WalkScribe(regime_id=regime_id, run_id=run_id)
        
        # Pull Derived Metrics
        inputs = council_state.get("inputs", {})
        close = inputs.get("close", price)
        atr_curr = inputs.get("atr", atr)
        atr_avg = inputs.get("atr_avg", atr_curr)
        volume = inputs.get("volume", 0.0)
        vol_avg = inputs.get("vol_avg", volume if volume > 0 else 1.0)
        adx = inputs.get("adx", 25.0)

        dist_avwap = (close - inputs.get("avwap", close)) / atr_curr if atr_curr > 0 else 0.0
        atr_ratio = atr_curr / atr_avg if atr_avg > 0 else 1.0
        vol_ratio = volume / vol_avg if vol_avg > 0 else 1.0
        trend_score = np.clip((adx - 15) / 35, 0, 1)

        mu = float((trend_score * 0.1) * (1.0 if dist_avwap > 0 else -0.2))
        sigma = float(1.0 * atr_ratio)
        p_jump = float(0.05 if (vol_ratio > 1.5 and atr_ratio > 1.2) else 0.01)

        mode = self.mode
        if frame is not None and hasattr(frame, "market"):
            mode = str(getattr(frame.market, "execution_mode", self.mode)).upper()

        mutations: List[float] = []
        shock_source = "none"
        frame_shocks = []
        if frame is not None and hasattr(frame, "risk"):
            frame_shocks = list(getattr(frame.risk, "shocks", []) or [])

        if mode == "BACKTEST" and frame_shocks:
            mutations = [float(x) for x in frame_shocks]
            shock_source = "frame_backtest"
        else:
            pulled = self.scribe.discharge(regime_id, limit=35000) if self.scribe else []
            if pulled:
                mutations = [float(x) for x in pulled]
                shock_source = "silo_discharge"
            elif frame_shocks:
                mutations = [float(x) for x in frame_shocks]
                shock_source = "frame_live"
            else:
                seed = abs(hash(f"{regime_id}|{mode}|{pulse_type}")) % (2**32)
                rng = np.random.default_rng(seed)
                mutations = rng.normal(loc=mu, scale=max(0.25, sigma), size=2048).astype(float).tolist()
                shock_source = "deterministic_fallback"
        
        seed = WalkSeed(
            regime_id=regime_id, mu=mu, sigma=sigma, p_jump=p_jump,
            jump_mu=0.0, jump_sigma=atr_curr * 2.0, tail_mult=1.0,
            confidence=float(council_state.get("confidence", 0.5)), mode=mode,
            mutations=mutations
        )

        self._mint_seed(seed, pulse_type)
        if frame is not None and hasattr(frame, "risk"):
            frame.risk.mu = seed.mu
            frame.risk.sigma = seed.sigma
            frame.risk.p_jump = seed.p_jump
            # Preserve Council's canonical regime_id and persist walk-specific key separately.
            frame.risk.walk_regime_id = seed.regime_id
            if not getattr(frame.risk, "regime_id", None):
                frame.risk.regime_id = seed.regime_id
            frame.risk.shocks = list(seed.mutations or [])
            frame.risk.mutations = list(seed.mutations or [])
        self.last_walk_event = {
            "pulse_type": str(pulse_type),
            "mode": str(mode),
            "regime_id": str(seed.regime_id),
            "mu": float(seed.mu),
            "sigma": float(seed.sigma),
            "p_jump": float(seed.p_jump),
            "shock_source": str(shock_source),
            "shock_count": int(len(seed.mutations or [])),
        }
        return seed

    def _mint_seed(self, seed: WalkSeed, pulse_type: str):
        # V3.1 OPTIMIZATION: Non-blocking Async Dispatch via Telepathy
        try:
            self.librarian.write("""
                INSERT INTO quantized_walk_mint (
                    ts, symbol, mode, regime_id, mu, sigma, p_jump, jump_mu, jump_sigma, 
                    tail_mult, confidence, pulse_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                None,
                seed.mode,
                seed.regime_id,
                seed.mu,
                seed.sigma,
                seed.p_jump,
                seed.jump_mu,
                seed.jump_sigma,
                seed.tail_mult,
                seed.confidence,
                pulse_type,
            ), transport="duckdb")
        except Exception:
            # Walk persistence is audit-only and must never block risk painting.
            pass

    def bin_dist_avwap(self, val: float) -> int:
        if val <= -1.5: return 0
        if val <= -0.5: return 1
        if val <= 0.5:  return 2
        if val <= 1.5:  return 3
        return 4

    def bin_atr_ratio(self, val: float) -> int:
        if val <= 0.8: return 0
        if val <= 1.2: return 1
        if val <= 1.8: return 2
        return 3

    def bin_vol_ratio(self, val: float) -> int:
        if val <= 0.9: return 0
        if val <= 1.2: return 1
        if val <= 2.0: return 2
        return 3

    def bin_trend_score(self, val: float) -> int:
        if val <= 0.25: return 0
        if val <= 0.6:  return 1
        return 2
