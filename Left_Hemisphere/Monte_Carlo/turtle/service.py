import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import numpy as np
import pandas as pd
from Hippocampus.Archivist.librarian import Librarian
from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian
from Cerebellum.Soul.brain_frame import BrainFrame
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
        self.mode = mode
        self.librarian = Librarian()
        self.walk = QuantizedGeometricWalk(mode=mode)
        self.rng = np.random.default_rng()
        self.legacy_simulation_calls = 0
        self.last_sim_event: Dict[str, Any] = {}

    def on_data_received(self, pulse_type: str, frame: BrainFrame):
        if frame is None:
            raise TypeError("on_data_received requires frame")
        return True

    def simulate(self, pulse_type: str = None, frame: BrainFrame = None, walk_seed=None, **legacy_kwargs):
        """Runs vectorized simulation and updates frame.risk."""
        # Legacy compatibility path:
        # simulate(current_price=..., atr=..., gear_lookback=..., confidence_score|council_score=..., direction=1)
        if frame is None and ("current_price" in legacy_kwargs or (pulse_type is not None and not isinstance(pulse_type, str))):
            return self._simulate_legacy(pulse_type, frame, **legacy_kwargs)

        if frame is None:
            raise TypeError("simulate requires frame for runtime path")

        pulse_start = time.perf_counter()
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

        # Populate frame.risk with regime-aware walk parameters before reading them below.
        try:
            _council_state = {
                "confidence": frame.environment.confidence,
                "inputs": {
                    "close": current_price,
                    "avwap": current_price,
                    "atr": atr,
                    "atr_avg": float(getattr(frame.environment, "atr_avg", atr) or atr),
                    "volume": 0.0,
                    "vol_avg": 1.0,
                    "adx": float(getattr(frame.environment, "adx", 25.0) or 25.0),
                },
            }
            self.walk.build_seed(
                council_state=_council_state,
                pulse_type=str(pulse_type or "ACTION"),
                run_id=str(getattr(frame.market, "symbol", "NA")),
                frame=frame,
            )
        except Exception:
            pass  # Walk failures must never block simulation.

        n_steps = int(gear)
        paths_per_lane = int(self.config.get("paths_per_lane", 10000))
        total_paths = paths_per_lane * 3
        start_ts = datetime.now()

        # 1. Base Dynamics
        mu_base = float(getattr(frame.risk, "mu", 0.0) or 0.0)
        sigma_mult = float(getattr(frame.risk, "sigma", 1.0) or 1.0)
        p_jump = float(getattr(frame.risk, "p_jump", 0.0) or 0.0)
        regime_id = str(getattr(frame.risk, "regime_id", "UNK") or "UNK")
        shocks = list(getattr(frame.risk, "shocks", []) or [])
        if walk_seed is not None:
            # Compatibility fallback for transitional call sites.
            if regime_id in ("", "UNK"):
                regime_id = str(getattr(walk_seed, "regime_id", "UNK"))
            if not shocks:
                shocks = list(getattr(walk_seed, "mutations", []) or [])
            if mu_base == 0.0:
                mu_base = float(getattr(walk_seed, "mu", 0.0) or 0.0)
            if sigma_mult == 1.0:
                sigma_mult = float(getattr(walk_seed, "sigma", 1.0) or 1.0)
            if p_jump == 0.0:
                p_jump = float(getattr(walk_seed, "p_jump", 0.0) or 0.0)
        
        # V3 Lane Gradient: Worst (2.0x), Neutral (1.0x), Best (0.5x)
        lane_mults = np.repeat([2.0, 1.0, 0.5], paths_per_lane).reshape(-1, 1)
        
        # 2. Historical Shock Injection
        required_size = total_paths * n_steps
        shock_source = "none"
        if shocks:
            shock_source = "frame_shocks"
            base = np.array(shocks, dtype=float)
            tiled = np.resize(base, required_size)
            noise = tiled.reshape(total_paths, n_steps)
        else:
            # Deterministic fallback when mutation buffers are missing.
            seed = abs(hash(f"{regime_id}|{pulse_type}|{n_steps}|{paths_per_lane}")) % (2**32)
            rng = np.random.default_rng(seed)
            noise = rng.normal(mu_base, 1.0, (total_paths, n_steps))
            shock_source = "deterministic_fallback"

        if p_jump > 0.0:
            jump_seed = abs(hash(f"jump|{regime_id}|{pulse_type}|{n_steps}|{paths_per_lane}")) % (2**32)
            jump_rng = np.random.default_rng(jump_seed)
            jump_mask = jump_rng.random((total_paths, n_steps)) < np.clip(p_jump, 0.0, 1.0)
            jump_scale = max(effective_atr * sigma_mult, 1e-9)
            jumps = jump_rng.normal(0.0, jump_scale, (total_paths, n_steps))
            noise = noise + (jump_mask * jumps)

        # Apply volatility scaling and lane gradients
        noise = noise * (effective_atr * self.noise_scalar * sigma_mult) * lane_mults

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

    def _simulate_legacy(self, *args, **kwargs):
        self.legacy_simulation_calls += 1
        # Support positional legacy call: simulate(price, atr, gear, confidence, direction)
        if len(args) >= 5 and not isinstance(args[0], str):
            current_price = float(args[0])
            atr = float(args[1])
            gear_lookback = int(args[2])
            confidence_score = float(args[3])
            direction = int(args[4])
        else:
            current_price = float(kwargs.get("current_price", 0.0))
            atr = float(kwargs.get("atr", 0.0))
            gear_lookback = int(kwargs.get("gear_lookback", self.config.get("n_steps", 10)))
            confidence_score = float(kwargs.get("confidence_score", kwargs.get("council_score", 0.5)))
            direction = int(kwargs.get("direction", 1))

        base = np.clip(confidence_score, 0.0, 1.0)
        vol_penalty = np.clip((atr / max(current_price, 1e-9)) * 1.0, 0.0, 0.2)
        direction_boost = 0.05 if direction >= 0 else -0.05
        core = np.clip(base - vol_penalty + direction_boost, 0.0, 1.0)
        # Legacy 5-lane output contract.
        lanes = np.array(
            [
                np.clip(core - 0.20, 0.0, 1.0),
                np.clip(core - 0.10, 0.0, 1.0),
                np.clip(core, 0.0, 1.0),
                np.clip(core + 0.05, 0.0, 1.0),
                np.clip(core + 0.10, 0.0, 1.0),
            ],
            dtype=float,
        )
        return lanes

    def _log_simulation(self, pulse_type, start_ts, duration, n_steps, paths_per_lane, total_paths, price, atr, stop, council, rates, score):
        try:
            self.librarian.mint_monte({
                "ts": start_ts.isoformat(),
                "symbol": None,
                "pulse_type": pulse_type,
                "n_steps": n_steps,
                "paths_per_lane": paths_per_lane,
                "price": price,
                "atr": atr,
                "stop_level": stop,
                "monte_score": score,
                "worst_survival": rates[0],
                "neutral_survival": rates[1],
                "best_survival": rates[2],
            })
        except Exception:
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
