import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian
from Left_Hemisphere.Monte_Carlo.walk.service import QuantizedGeometricWalk


class TurtleMonte:
    """
    Tier 1 Risk Engine: The Quantized Monte.
    V3 Optimization: Reads from frame.structure/environment, writes to frame.risk.
    """
    def __init__(self, config: Dict[str, Any] = None, mode: str = "LIVE", **legacy_kwargs):
        self.config = config or {}
        # Legacy constructor compatibility.
        if "n_steps" in legacy_kwargs and "n_steps" not in self.config:
            self.config["n_steps"] = int(legacy_kwargs["n_steps"])
        if "paths_per_lane" in legacy_kwargs and "paths_per_lane" not in self.config:
            self.config["paths_per_lane"] = int(legacy_kwargs["paths_per_lane"])
        # Attributes noise_scalar and lane_weights are typically injected by Orchestrator
        self.noise_scalar = 0.35
        self.lane_weights = np.array([0.15, 0.35, 0.50], dtype=float)
        self.mode = mode.upper()
        self.librarian = librarian
        
        # Piece 28: Left Hemisphere owns the Walk Engine
        self.walk_engine = QuantizedGeometricWalk(mode=self.mode)
        
        self.rng = np.random.default_rng()
        self.legacy_simulation_calls = 0
        self.last_sim_event: Dict[str, Any] = {}

    def on_data_received(self, pulse_type: str, frame: BrainFrame):
        if frame is None:
            raise TypeError("on_data_received requires frame")
        
        # Piece 14: Risk engine remains aware across all pulses
        if not enforce_pulse_gate(pulse_type, ["SEED", "ACTION", "MINT"], "Left_Hemisphere"):
            # Contract: pulse ownership belongs to Soul; LH should not reject lifecycle ownership.
            return True

        # Piece 28: Paint priors before simulation ignites
        try:
            self.walk_engine.build_seed(
                pulse_type=pulse_type,
                frame=frame
            )
            return True
        except Exception as e:
            # LHMI-E-P41-357: Walk seeding failure
            print(f"[LHMI-E-P41-357] TURTLE: Walk seeding failed: {e}")
            return False

    def simulate(self, pulse_type: str = None, frame: BrainFrame = None, walk_seed=None, **legacy_kwargs):
        """Runs vectorized simulation and updates frame.risk."""
        # Piece 14: Simulation only fires at SEED and ACTION
        if not enforce_pulse_gate(pulse_type, ["SEED", "ACTION"], "Left_Hemisphere"):
            return 0.0

        if frame is None:
            raise TypeError("simulate requires frame for runtime path")

        pulse_start = time.perf_counter()
        try:
            current_price = float(getattr(frame.structure, "price", 0.0) or 0.0)
            stop_level = getattr(frame.structure, "active_lo", None)
            atr = float(getattr(frame.environment, "atr", 0.0) or 0.0)
            gear = getattr(frame.structure, "gear", None)

            if gear is None or int(gear) <= 0:
                self._safe_risk_reset(frame, reason="invalid_gear")
                return 0.0
            if stop_level is None or not np.isfinite(float(stop_level)):
                self._safe_risk_reset(frame, reason="invalid_stop_context")
                return 0.0
            if current_price <= 0.0:
                self._safe_risk_reset(frame, reason="invalid_price")
                return 0.0
            if atr <= 0.0:
                self._safe_risk_reset(frame, reason="invalid_atr")
                return 0.0
            
            stop_level = float(stop_level)
            effective_atr = atr
            
            n_steps = int(gear)
            paths_per_lane = int(self.config.get("paths_per_lane", 10000))
            total_paths = paths_per_lane * 3
            start_ts = datetime.now()

            # ... (Logic for Base Dynamics and Shock Injection)
            # 1. Base Dynamics
            mu_base = float(getattr(frame.risk, "mu", 0.0) or 0.0)
            sigma_mult = float(getattr(frame.risk, "sigma", 1.0) or 1.0)
            p_jump = float(getattr(frame.risk, "p_jump", 0.0) or 0.0)
            regime_id = str(getattr(frame.risk, "regime_id", "UNK") or "UNK")
            shocks = list(getattr(frame.risk, "shocks", []) or [])
            
            # V3 Lane Gradient: Worst (2.0x), Neutral (1.0x), Best (0.5x)
            lane_mults = np.repeat([2.0, 1.0, 0.5], paths_per_lane).reshape(-1, 1)
            
            # 2. Historical Shock Injection
            shock_source = "none"
            if shocks:
                shock_source = "frame_shocks"
                base = np.array(shocks, dtype=np.float64)
                indices = np.arange(total_paths * n_steps)
                noise = np.take(base, indices, mode='wrap').reshape(total_paths, n_steps)
                # Apply Walk drift (mu) to historical shocks
                noise = noise + mu_base
            else:
                pulse_seed = int(getattr(frame.market, "ts", datetime.now()).timestamp()) % (2**32)
                rng = np.random.default_rng(pulse_seed)
                # Use Walk-derived mu and sigma directly
                noise = rng.normal(mu_base, sigma_mult, (total_paths, n_steps))
                shock_source = "deterministic_fallback"

            if p_jump > 0.0:
                jump_rng = np.random.default_rng(pulse_seed + 1)
                jump_mask = jump_rng.random((total_paths, n_steps)) < np.clip(p_jump, 0.0, 1.0)
                jump_scale = max(effective_atr * sigma_mult, 1e-9)
                jumps = jump_rng.normal(0.0, jump_scale, (total_paths, n_steps))
                noise = noise + (jump_mask * jumps)

            # Apply volatility scaling (ATR) and lane gradients
            # Note: sigma_mult is already inside noise if using fallback, but we apply ATR here
            noise = noise * (effective_atr * self.noise_scalar) * lane_mults

            # 3. Vectorized Hit Stop
            paths = current_price + np.cumsum(noise, axis=1)
            hit_stop = np.any(paths <= stop_level, axis=1)
            rates = np.mean((~hit_stop).reshape(3, paths_per_lane), axis=1)

            # 4. Final State Scoring
            weights_default = self.lane_weights / np.sum(self.lane_weights)
            monte_score = float(np.sum(rates * weights_default))
            
            # 5. Update Brain Frame Slot
            frame.risk.monte_score = monte_score
            frame.risk.regime_id = regime_id
            frame.risk.worst_survival = float(rates[0])
            frame.risk.neutral_survival = float(rates[1])
            frame.risk.best_survival = float(rates[2])
            frame.risk.lane_survivals = [float(rates[0]), float(rates[1]), float(rates[2])]
            
            duration = time.perf_counter() - pulse_start
            self._log_simulation(pulse_type, start_ts, duration, n_steps, paths_per_lane, total_paths, current_price, atr, stop_level, frame.environment.confidence, rates, monte_score)
            self.last_sim_event = {
                "pulse_type": str(pulse_type),
                "shock_source": str(shock_source),
                "regime_id": str(regime_id),
                "n_steps": int(n_steps),
                "paths_per_lane": int(paths_per_lane),
                "score": float(monte_score),
            }
            return monte_score

        except Exception as e:
            # Phase 3 Target: Standardized MNER for simulation failure
            print(f"[LHMI-E-P44-355] MONTE_SIM_FAILURE: {e}")
            self._safe_risk_reset(frame, reason="sim_crash")
            return 0.0

    def _log_simulation(self, pulse_type, start_ts, duration, n_steps, paths_per_lane, total_paths, price, atr, stop, council, rates, score):
        """Piece 101: Analytical consolidation into DuckDB."""
        try:
            self.librarian.mint_monte({
                "ts": start_ts,
                "symbol": "FRAME_CONTEXT", # Placeholder for multi-symbol logic
                "pulse_type": pulse_type,
                "n_steps": n_steps,
                "paths_per_lane": paths_per_lane,
                "price": price,
                "atr": atr,
                "stop_level": stop,
                "monte_score": score,
                "worst_survival": rates[0],
                "neutral_survival": rates[1],
                "best_survival": rates[2]
            })
        except Exception as e:
            # LHMI-W-P41-358: simulation logging failure
            # Audit persistence must not influence runtime policy flow.
            print(f"[LHMI-W-P41-358] TURTLE: Simulation logging failed: {e}")
            pass

    def get_state(self):
        return {"last_sim_event": dict(self.last_sim_event), "legacy_simulation_calls": int(self.legacy_simulation_calls)}

    def _safe_risk_reset(self, frame: BrainFrame, *, reason: str):
        frame.risk.monte_score = 0.0
        frame.risk.worst_survival = 0.0
        frame.risk.neutral_survival = 0.0
        frame.risk.best_survival = 0.0
        frame.risk.lane_survivals = [0.0, 0.0, 0.0]
        self.last_sim_event = {"status": str(reason), "score": 0.0}
