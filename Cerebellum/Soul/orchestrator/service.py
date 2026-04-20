import time
import pandas as pd
import json
import numpy as np
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime

from Cerebellum.Soul.brain_frame import BrainFrame
from Left_Hemisphere.Monte_Carlo.quantized_geometric_walk import QuantizedGeometricWalk
from Hospital.Optimizer_loop.volume_furnace_orchestrator import VolumeFurnaceOrchestrator
from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian
from Hippocampus.Archivist.librarian import librarian
from Hippocampus.amygdala import Amygdala
from Hippocampus.pineal import Pineal
from Hippocampus.Context.mner import emit_mner
from Pituitary.gland import PituitaryGland
from Cerebellum.Soul.utils.ward_manager import WardManager

try:
    from Hippocampus.crawler import ParamCrawler
except Exception:
    ParamCrawler = None

@dataclass
class LobeMetrics:
    name: str
    duration: float
    status: str
    deadline_met: bool
    pulse_type: str

class Orchestrator:
    """
    Cerebellum/Soul: The Orchestrator (NEURAL VELOCITY).
    Governs the Brain Frame lifecycle and Triple-Pulse rhythm.
    V6: Optical Tract Subscriber — processes data upon broadcast.
    """
    def __init__(self, config: Dict[str, Any] = None, optical_tract: Any = None):
        self.config = config or {}
        self.run_id = f"soul-{uuid.uuid4().hex[:8]}"
        self.deadlines = self.config.get("deadlines", {"Thalamus": 1.0, "Right_Hemisphere": 0.5, "Left_Hemisphere": 5.0, "Council": 0.5, "Corpus": 0.2, "Gatekeeper": 0.2, "Brain_Stem": 0.5})
        self.lobes: Dict[str, Any] = {}
        self.pulse_log: List[Dict[str, Any]] = []
        self.pulse_seq = 0
        
        # V3.1 BRAINTICK: Clean ward on boot
        WardManager().janitor_sweep()
        
        # Hot-table source of truth with file mirror fallback.
        self.vault_path = Path(__file__).resolve().parents[3] / "Hippocampus" / "hormonal_vault.json"
        self.librarian = librarian
        self.vault = self._load_vault()
        
        # Mirror Gold params and mode to the BrainFrame (Soul-Driven Canvas)
        self.frame = BrainFrame()
        self.frame.standards = self.vault.get("gold", {}).get("params", {})
        self.frame.market.execution_mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()
        
        print(f"[SOUL] {self.run_id} Hormonal Vault Source: hot-table (mammon:hormonal_vault)")
        print(f"[SOUL] {self.run_id} Hormonal Vault Mirror: {self.vault_path}")
        print(f"[SOUL] {self.run_id} Gold Mirror Active (ID: {self.vault.get('gold', {}).get('id', 'UNK')})")
        print(f"[SOUL] {self.run_id} Mode Canvas: {self.frame.market.execution_mode}")
        
        # Supporting Engines
        self.walk_engine = QuantizedGeometricWalk()
        # Live orchestrator must not run simulation ignition cadence.
        self.furnace = VolumeFurnaceOrchestrator(
            simulation_mode=False,
            execution_mode=str(self.config.get("execution_mode", "DRY_RUN")).upper(),
        )
        amygdala_config = {
            "synapse_persist_pulse_types": self.config.get("synapse_persist_pulse_types", ["MINT"]),
        }
        for key in ("synapse_db_path_primary", "synapse_db_path_backtest"):
            if key in self.config and self.config.get(key):
                amygdala_config[key] = self.config.get(key)
        self.amygdala = Amygdala(config=amygdala_config)
        self.pineal = Pineal(
            config={
                "synapse_preserve_pulse_types": amygdala_config.get("synapse_persist_pulse_types", ["MINT"])
            }
        )
        self.pituitary = PituitaryGland()
        self.crawler = None
        if ParamCrawler is not None:
            try:
                self.crawler = ParamCrawler()
            except Exception as ce:
                print(f"[SOUL_WARN] Crawler unavailable: {ce}")
        self.opt_lib = OptimizerLibrarian()
        self.active_strikes: List[Dict[str, Any]] = [] 
        self.last_action_ts: Optional[float] = None  # legacy wall-clock anchor
        self.last_action_market_ts: Optional[pd.Timestamp] = None

        # V6: Optical Tract Subscription
        self.optical_tract = optical_tract
        if self.optical_tract:
            self.optical_tract.subscribe(self)
            print(f"[SOUL] {self.run_id} Subscribed to Optical Tract")

    def set_execution_mode(self, mode: str):
        mode_u = str(mode or "DRY_RUN").upper()
        self.config["execution_mode"] = mode_u
        if hasattr(self.furnace, "set_execution_mode"):
            self.furnace.set_execution_mode(mode_u)
        for lobe in self.lobes.values():
            if hasattr(lobe, "mode"):
                lobe.mode = mode_u
            if hasattr(lobe, "set_execution_mode"):
                try:
                    lobe.set_execution_mode(mode_u)
                except Exception:
                    pass

    def on_data_received(self, data: pd.DataFrame):
        """
        Broadcaster Hook: Triggered when Optical Tract sprays data.
        Ensures the 'Whole Brain' uses the data without duplicate ingestion.
        """
        if data.empty: return
        self._process_frame(data)

    def register_lobe(self, name: str, instance: Any):
        # Inject Gold Standards if the lobe accepts config
        gold_params = self.vault.get("gold", {}).get("params", {})
        if hasattr(instance, "config"):
            if instance.config is None:
                instance.config = {}
            instance.config.update(gold_params)
            
            # V3 NEURAL VELOCITY: Strict Gold Enforcement
            if name == "Left_Hemisphere":
                instance.noise_scalar = float(gold_params.get("monte_noise_scalar", 0.35))
                instance.lane_weights = np.array([
                    gold_params.get("monte_w_worst", 0.15),
                    gold_params.get("monte_w_neutral", 0.35),
                    gold_params.get("monte_w_best", 0.50)
                ])
            elif name == "Right_Hemisphere":
                instance.config["active_gear"] = int(gold_params.get("active_gear", 5))

        self.lobes[name] = instance
        if hasattr(instance, "mode"):
            instance.mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()
        print(f"[SOUL] {self.run_id} Registered Lobe: {name} (Strict Gold Active)")

    def pulse(self, symbols: List[str], is_crypto: bool = True, data_override: pd.DataFrame = None):
        """The high-velocity heartbeat: Starts with Thalamus ingestion."""
        if data_override is not None:
            self._process_frame(data_override)
            return

        # 1. Thalamus (Data Ingestion)
        thal_start = time.perf_counter()
        try:
            # Note: Thalamus will spray to Optical Tract, which triggers on_data_received
            data = self.lobes["Thalamus"].pulse(symbols=symbols, is_crypto=is_crypto)
            
            # If Thalamus DOES NOT have an optical tract, we manually process here
            if not self.optical_tract and data is not None and not data.empty:
                self._process_frame(data)
                
            thal_dur = time.perf_counter() - thal_start
            self.pulse_log.append({"timestamp": datetime.now().isoformat(), "lobe": "Thalamus", "duration": thal_dur})
        except Exception as e:
            print(f"[SOUL_CRITICAL] Thalamus pulse failed: {e}")
            raise

    def _process_frame(self, data: pd.DataFrame):
        """
        The Core Neural Cycle: Processes a data frame through all lobes.
        Triggered either by pulse() or by Optical Tract broadcast.
        """
        pulse_start = time.perf_counter()
        metrics: List[LobeMetrics] = []
        pulse_type = data["pulse_type"].iloc[-1] if "pulse_type" in data.columns else "ACTION"
        symbol = data["symbol"].iloc[-1] if "symbol" in data.columns else "UNKNOWN"
        mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()

        try:
            # Prepare the Frame
            self.frame.reset_pulse(pulse_type)
            self.frame.market.ohlcv = data
            self.frame.market.ts = data.index[-1]
            self.frame.market.symbol = symbol
            self.frame.market.execution_mode = mode

            # 1. Trade Gate Evaluation (Soul Boundary)
            can_trade = True
            trade_gate_provider = self.config.get("trading_enabled_provider")
            if callable(trade_gate_provider):
                try:
                    can_trade = bool(trade_gate_provider())
                except Exception:
                    can_trade = False

            # 1b. Timing Guard Evaluation (Piece 16)
            timing_inhibited = False
            if pulse_type == "MINT":
                max_market_delay = float(self.config.get("action_to_mint_max_market_sec", 90.0))
                max_wall_delay = float(self.config.get("action_to_mint_max_wall_sec", 90.0))
                action_market_ts = getattr(self, "last_action_market_ts", None)
                mint_market_ts = pd.to_datetime(self.frame.market.ts, utc=True, errors="coerce")

                if action_market_ts is not None and pd.notna(mint_market_ts):
                    elapsed = float((mint_market_ts - action_market_ts).total_seconds())
                    if elapsed > max_market_delay:
                        timing_inhibited = True
                        print(
                            f"[SOUL] TIMING_INHIBIT: MINT arrived too late "
                            f"(pulse_dt={elapsed:.1f}s > {max_market_delay:.1f}s)"
                        )
                elif self.last_action_ts is not None:
                    elapsed = time.time() - self.last_action_ts
                    if elapsed > max_wall_delay:
                        timing_inhibited = True
                        print(
                            f"[SOUL] TIMING_INHIBIT: MINT arrived too late "
                            f"(wall_dt={elapsed:.1f}s > {max_wall_delay:.1f}s)"
                        )
                self.last_action_ts = None
                self.last_action_market_ts = None
            elif pulse_type == "ACTION":
                self.last_action_ts = time.time()
                action_market_ts = pd.to_datetime(self.frame.market.ts, utc=True, errors="coerce")
                self.last_action_market_ts = action_market_ts if pd.notna(action_market_ts) else None

            # 2. Right Hemisphere (Structure)
            self._run_lobe("Right_Hemisphere", self.lobes["Right_Hemisphere"].on_data_received, metrics, pulse_type, frame=self.frame)

            # 3. Council (Environment)
            self._run_lobe("Council", self.lobes["Council"].consult, metrics, pulse_type, frame=self.frame)

            # 4. Left Hemisphere (Risk Readiness)
            lh_ready = self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].on_data_received, metrics, pulse_type, frame=self.frame)
            
            # V3.1: Seed the Walk Engine
            walk_seed = None
            if lh_ready:
                walk_seed = self.walk_engine.build_seed(
                    council_state=self.lobes["Council"].get_state(),
                    pulse_type=pulse_type,
                    run_id=self.run_id,
                    frame=self.frame,
                )

            # 5. Continuous Volume Furnace Calibration (Piece 10)
            try:
                if hasattr(self.furnace, "handle_frame"):
                    self.furnace.handle_frame(
                        pulse_type=pulse_type,
                        frame=self.frame,
                        walk_seed=walk_seed
                    )
                else:
                    regime_id = getattr(self.frame.risk, "regime_id", "UNK")
                    if regime_id in {"", "UNK", "UNKNOWN", "NONE"} and walk_seed is not None:
                        regime_id = str(getattr(walk_seed, "regime_id", "UNK"))
                    self.furnace.handle_pulse(
                        pulse_type=pulse_type,
                        regime_id=regime_id,
                        price=self.frame.structure.price,
                        atr=self.frame.environment.atr,
                        stop_level=self.frame.structure.active_lo,
                        walk_seed=walk_seed,
                    )
            except Exception as fe:
                emit_mner(
                    "SOUL-E-P35-208",
                    "FURNACE_RUNTIME_FAILURE",
                    source="Cerebellum.Soul.orchestrator.service.Orchestrator._process_frame",
                    details={"error": str(fe), "pulse_type": pulse_type, "symbol": symbol},
                    echo=True,
                )

            # 6. Signal-Based Decisions
            if self.frame.structure.tier1_signal == 1:
                if pulse_type == "ACTION" and lh_ready:
                    self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].simulate, metrics, pulse_type, frame=self.frame, walk_seed=walk_seed)
                    self._run_lobe("Corpus", self.lobes["Corpus"].score_tier, metrics, pulse_type, frame=self.frame)
                    self._run_lobe("Gatekeeper", self.lobes["Gatekeeper"].decide, metrics, pulse_type, frame=self.frame)

                    # Final inhibit if trade gate is locked
                    if self.frame.command.ready_to_fire and not can_trade:
                        self.frame.command.approved = 0
                        self.frame.command.ready_to_fire = False
                        self.frame.command.reason = "Trading gate locked (FORNIX/WARMUP/LOCKED)"

                    if self.frame.command.ready_to_fire:
                        # V6: Whole Brain Engagement (Risk + Valuation Gates)
                        self._run_lobe("Brain_Stem", self.lobes["Brain_Stem"].load_and_hunt, metrics, pulse_type, 
                                      frame=self.frame, orchestrator=self, walk_engine=self.walk_engine, walk_seed=walk_seed)
                
                elif pulse_type == "SEED" and lh_ready:
                    self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].simulate, metrics, pulse_type, frame=self.frame, walk_seed=walk_seed)

            # MINT finalization path: execute deferred ACTION approvals and disable meanDev monitor.
            if pulse_type == "MINT" and "Brain_Stem" in self.lobes:
                # If MINT is too late, we must tell Brain Stem to cancel any pending intent
                if timing_inhibited:
                    # We can use a trick here: monkeypatch frame.command.approved temporarily
                    # so Brain Stem rejects the execution.
                    self.frame.command.ready_to_fire = False
                    self.frame.command.reason = f"TIMING_CANCEL (MINT delayed > {max_market_delay:.0f}s)"
                
                self._run_lobe(
                    "Brain_Stem",
                    self.lobes["Brain_Stem"].load_and_hunt,
                    metrics,
                    pulse_type,
                    frame=self.frame,
                    orchestrator=self,
                    walk_engine=self.walk_engine,
                    walk_seed=walk_seed
                )

            # 7. Final State Scribe (Maintenance Hooks in deterministic order)
            hook_status = {
                "amygdala": "skipped",
                "pineal": "skipped",
                "vault_reload": "skipped",
                "pituitary": "skipped",
                "crawler": "skipped",
            }
            try:
                self.amygdala.mint_synapse_ticket(pulse_type, self.frame)
                hook_status["amygdala"] = "ok"
            except Exception as e:
                hook_status["amygdala"] = f"error:{type(e).__name__}"
                print(f"[SOUL_WARN] Amygdala failed: {e}")
            
            # 8. Memory & Hormonal Management
            if pulse_type == "MINT":
                try:
                    self.pineal.secrete_melatonin(pulse_type)
                    hook_status["pineal"] = "ok"
                except Exception as e:
                    hook_status["pineal"] = f"error:{type(e).__name__}"
                    print(f"[SOUL_WARN] Pineal failed: {e}")
                try:
                    # V6 Piece 14: Finalize hot-reload rollout
                    self._check_vault_mutation()
                    hook_status["vault_reload"] = "ok"
                except Exception as e:
                    hook_status["vault_reload"] = f"error:{type(e).__name__}"
                    print(f"[SOUL_WARN] Vault reload failed: {e}")
            try:
                self.pituitary.secrete_growth_hormone(pulse_type)
                hook_status["pituitary"] = "ok"
            except Exception as e:
                hook_status["pituitary"] = f"error:{type(e).__name__}"
                print(f"[SOUL_WARN] Pituitary failed: {e}")
            if pulse_type == "MINT" and getattr(self, "crawler", None) is not None:
                try:
                    self.crawler.crawl(pulse_type, self.frame)
                    hook_status["crawler"] = "ok"
                except Exception as e:
                    hook_status["crawler"] = f"error:{type(e).__name__}"
                    print(f"[SOUL_WARN] Crawler failed: {e}")

        except Exception as e:
            print(f"[SOUL_CRITICAL] Cycle failed: {e}")
        
        # Piece 16 authority guard: lobe code cannot advance lifecycle pulse outside Soul.
        try:
            self.frame.market.pulse_type = pulse_type
            self.frame.market.execution_mode = mode
        except Exception:
            pass

        pulse_duration = time.perf_counter() - pulse_start
        self._log_pulse(metrics, pulse_duration, hook_status if "hook_status" in locals() else None)

    def _run_lobe(self, name: str, func: callable, metrics_list: List[LobeMetrics], pulse_type: str, *args, **kwargs):
        start = time.perf_counter()
        deadline = self.deadlines.get(name, 1.0)
        try:
            result = func(pulse_type, *args, **kwargs)
            duration = time.perf_counter() - start
            metrics_list.append(LobeMetrics(name, duration, "success", duration <= deadline, pulse_type))
            return result
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:50]}"
            metrics_list.append(LobeMetrics(name, time.perf_counter() - start, f"error: {err_msg}", False, pulse_type))
            print(f"[SOUL_LOBE_ERROR] lobe={name} run_id={self.run_id} pulse={pulse_type} error={err_msg}")
            raise e

    def _log_pulse(self, metrics: List[LobeMetrics], total_duration: float, hooks: Dict[str, str] = None):
        if not hasattr(self, "pulse_seq"):
            self.pulse_seq = 0
        self.pulse_seq += 1
        frame_obj = getattr(self, "frame", None)
        pulse_type = str(getattr(getattr(frame_obj, "market", None), "pulse_type", "UNKNOWN"))
        mode = str(getattr(getattr(frame_obj, "market", None), "execution_mode", "UNKNOWN"))
        symbol = str(getattr(getattr(frame_obj, "market", None), "symbol", "UNKNOWN"))
        lobe_names = [m.name for m in metrics]
        has_required_core = all(name in lobe_names for name in ["Right_Hemisphere", "Council", "Left_Hemisphere"])
        decision_summary = {
            "ready_to_fire": bool(getattr(getattr(frame_obj, "command", None), "ready_to_fire", False)),
            "approved": int(getattr(getattr(frame_obj, "command", None), "approved", 0)),
            "reason": str(getattr(getattr(frame_obj, "command", None), "reason", "")),
        }
        self.pulse_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "pulse_id": f"{self.run_id}:{self.pulse_seq}",
                "mode": mode,
                "pulse_type": pulse_type,
                "symbol": symbol,
                "total_duration": total_duration,
                "frame_completeness": {
                    "has_market_data": bool(getattr(getattr(frame_obj, "market", None), "ohlcv", pd.DataFrame()).shape[0] > 0),
                    "has_structure_price": float(getattr(getattr(frame_obj, "structure", None), "price", 0.0)) > 0.0,
                    "has_required_core_lobes": has_required_core,
                },
                "decision_summary": decision_summary,
                "hooks": hooks or {},
                "lobes": [m.__dict__ for m in metrics],
            }
        )

    def _check_vault_mutation(self):
        """
        Piece 14: Hot-Reload / Rollout.
        Reloads Gold parameters if the vault ID has changed.
        """
        try:
            new_vault = self._load_vault()
            
            new_id = new_vault.get("gold", {}).get("id")
            old_id = self.vault.get("gold", {}).get("id")
            
            if new_id != old_id:
                print(f"[SOUL] Mutation detected: {old_id} -> {new_id}. Hot-reloading lobes...")
                self.vault = new_vault
                gold_params = self.vault["gold"]["params"]
                self.frame.standards = gold_params
                
                # Update all registered lobes
                for name, lobe in self.lobes.items():
                    if hasattr(lobe, "config"):
                        if lobe.config is None:
                            lobe.config = {}
                        lobe.config.update(gold_params)
                        
                        # Apply specific overrides
                        if name == "Left_Hemisphere":
                            lobe.noise_scalar = float(gold_params.get("monte_noise_scalar", 0.35))
                            lobe.lane_weights = np.array([
                                gold_params.get("monte_w_worst", 0.15),
                                gold_params.get("monte_w_neutral", 0.35),
                                gold_params.get("monte_w_best", 0.50)
                            ])
                        elif name == "Right_Hemisphere":
                            lobe.config["active_gear"] = int(gold_params.get("active_gear", 5))
                
                print(f"[SOUL] Hot-reload complete for Gold Mirror ID: {new_id}")
        except Exception as e:
            print(f"[SOUL_ERROR] Hot-reload failed: {e}")

    def _load_vault(self) -> Dict[str, Any]:
        """
        Runtime source of truth is the Librarian hot table.
        Falls back to file mirror only if hot-table read is unavailable.
        """
        try:
            vault = self.librarian.get_hormonal_vault()
            if isinstance(vault, dict):
                return vault
        except Exception as e:
            print(f"[SOUL_WARN] Hot-table vault read failed: {e}")

        try:
            with open(self.vault_path, "r") as f:
                fallback = json.load(f)
            if isinstance(fallback, dict):
                print("[SOUL_WARN] Using file-mirror vault fallback.")
                return fallback
        except Exception as e:
            print(f"[SOUL_ERROR] File-mirror vault fallback failed: {e}")

        return {
            "gold": {
                "id": "UNKNOWN",
                "params": {},
                "fitness_snapshot": 0.0,
                "origin": "bootstrap_fallback",
            },
            "silver": [],
            "platinum": None,
            "titanium": None,
            "bronze_history": [],
            "diamond_rails": {"bounds": {}},
            "meta": {},
        }
