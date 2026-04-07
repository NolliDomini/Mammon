import time
import pandas as pd
import json
import numpy as np
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import deque

from Hippocampus.Archivist.librarian import librarian
from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.ward_manager import WardManager
from Hospital.Optimizer_loop.volume_furnace_orchestrator import VolumeFurnaceOrchestrator
from Hippocampus.amygdala.service import Amygdala
from Hippocampus.pineal.service import Pineal
from Pituitary.gland.service import PituitaryGland
from Brain_Stem.pons_execution_cost.service import PonsExecutionCost
from Medulla.allocation_gland.service import AllocationGland
from Hippocampus.crawler.service import ParamCrawler


@dataclass
class LobeMetrics:
    lobe: str
    duration: float
    status: str
    success: bool
    pulse: str

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
        self.pulse_log = deque(maxlen=200) # Memory Leak Fix
        self.pulse_seq = 0
        self.librarian = librarian
        
        # V3.1 BRAINTICK: Clean ward on boot
        WardManager().janitor_sweep()
        
        # Load Hormonal Vault (Piece 115: Sourced from Redis HASH)
        self.vault = self.librarian.get_hormonal_vault()
        
        # Mirror Gold params and mode to the BrainFrame (Soul-Driven Canvas)
        self.frame = BrainFrame()
        self.frame.standards = self.vault.get("gold", {}).get("params", {})
        self.frame.market.execution_mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()
        
        print(f"[SOUL] {self.run_id} Gold Mirror Active (ID: {self.vault.get('gold', {}).get('id', 'UNK')})")
        print(f"[SOUL] {self.run_id} Mode Canvas: {self.frame.market.execution_mode}")
        
        # Supporting Engines
        self.furnace = VolumeFurnaceOrchestrator(
            simulation_mode=False,
            execution_mode=str(self.config.get("execution_mode", "DRY_RUN")).upper(),
        )
        self.amygdala = Amygdala()
        self.pineal = Pineal()
        self.pituitary = PituitaryGland()
        self.crawler = ParamCrawler()
        
        # Phase 1: Execution Friction Engines
        self.pons = PonsExecutionCost()
        self.allocation_gland = AllocationGland()
        
        self.active_strikes: List[Dict[str, Any]] = [] 
        self.last_action_ts: Optional[float] = None # V6: 30s Kill Window
        
        # Phase 2: Interleaving & Context Freeze
        self.mint_cadence_count = 0 
        self.stable_frame: Optional[BrainFrame] = None

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
                except Exception as e:
                    # SOUL-W-P35-206: Lobe rebind failure
                    print(f"[SOUL-W-P35-206] Lobe rebind failed for {lobe}: {e}")
                    pass

    def on_data_received(self, data: pd.DataFrame):
        if data.empty: return
        self._process_frame(data)

    def spray(self, data: pd.DataFrame):
        self.on_data_received(data)

    def register_lobe(self, name: str, instance: Any):
        gold_params = self.vault.get("gold", {}).get("params", {})
        if hasattr(instance, "config"):
            if instance.config is None:
                instance.config = {}
            instance.config.update(gold_params)
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
        if data_override is not None:
            self._process_frame(data_override)
            return
        thal_start = time.perf_counter()
        try:
            data = self.lobes["Thalamus"].pulse(symbols=symbols, is_crypto=is_crypto)
            if not self.optical_tract and data is not None and not data.empty:
                self._process_frame(data)
            thal_dur = time.perf_counter() - thal_start
            self.pulse_log.append({"timestamp": datetime.now().isoformat(), "lobe": "Thalamus", "duration": thal_dur})
        except Exception as e:
            print(f"[SOUL-F-P32-201] SOUL_THALAMUS_PULSE_FAILED: {e}")
            raise

    def _process_frame(self, data: pd.DataFrame):
        """
        The Core Neural Cycle: Phase 1 Deterministic Sequence.
        """
        if not hasattr(self, "mint_cadence_count"):
            self.mint_cadence_count = 0
        if not hasattr(self, "stable_frame"):
            self.stable_frame = None
        if not hasattr(self, "pons"):
            self.pons = None
        if not hasattr(self, "allocation_gland"):
            self.allocation_gland = None
        if not hasattr(self, "crawler"):
            self.crawler = None

        pulse_start = time.perf_counter()
        metrics: List[LobeMetrics] = []
        pulse_cell = data["pulse_type"] if "pulse_type" in data.columns else "ACTION"
        if isinstance(pulse_cell, pd.DataFrame):
            pulse_type = pulse_cell.iloc[-1, -1]
        elif isinstance(pulse_cell, pd.Series):
            pulse_type = pulse_cell.iloc[-1]
        else:
            pulse_type = pulse_cell
        symbol = data["symbol"].iloc[-1] if "symbol" in data.columns else "UNKNOWN"
        pulse_type = str(pulse_type).upper()
        mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()

        try:
            # 0. RESET & HYDRATE
            self.frame.reset_pulse(pulse_type)
            self.frame.market.ohlcv = data
            self.frame.market.ts = data.index[-1]
            self.frame.market.symbol = symbol
            self.frame.market.execution_mode = mode

            # 1. TRADE GATE
            can_trade = True
            trade_gate_provider = self.config.get("trading_enabled_provider")
            if callable(trade_gate_provider):
                try:
                    can_trade = bool(trade_gate_provider())
                except Exception as e:
                    print(f"[SOUL-W-P35-207] SOUL: Trade gate provider failed: {e}")
                    can_trade = False

            # 1b. TIMING GUARD
            timing_inhibited = False
            if pulse_type == "MINT":
                if self.last_action_ts is not None:
                    elapsed = time.time() - self.last_action_ts
                    if elapsed > 30.0:
                        timing_inhibited = True
                        print(f"[SOUL] TIMING_INHIBIT: MINT delayed ({elapsed:.1f}s > 30s).")
                self.last_action_ts = None
            elif pulse_type == "ACTION":
                self.last_action_ts = time.time()

            if timing_inhibited:
                self.frame.command.ready_to_fire = False
                self.frame.command.reason = "TIMING_CANCEL (MINT > 30s)"

            # 2. STRUCTURE (Right Hemi)
            self._run_lobe("Right_Hemisphere", self.lobes["Right_Hemisphere"].on_data_received, metrics, pulse_type, frame=self.frame)

            # 3. ENVIRONMENT (Council + SpreadEngine)
            self._run_lobe("Council", self.lobes["Council"].consult, metrics, pulse_type, frame=self.frame)

            # 4. RISK READINESS (LH)
            lh_ready = self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].on_data_received, metrics, pulse_type, frame=self.frame)
            
            # 5. FURNACE (MINT Interleaving)
            if pulse_type == "MINT":
                try:
                    grounding_frame = self.stable_frame or self.frame
                    if self.mint_cadence_count == 1:
                        self.furnace.handle_frame(pulse_type="MINT", frame=grounding_frame, stage_group="SCOUT")
                    elif self.mint_cadence_count == 2:
                        self.furnace.handle_frame(pulse_type="MINT", frame=grounding_frame, stage_group="PRIME")
                    elif self.mint_cadence_count == 0:
                        self.furnace.handle_frame(pulse_type="MINT", frame=grounding_frame, stage_group="CALCULATE")
                        self.stable_frame = None
                except Exception as fe:
                    print(f"[SOUL-E-P35-208] Interleaved Furnace failed: {fe}")

            # 6. GATED DECISIONS (ACTION)
            if self.frame.structure.tier1_signal == 1:
                if pulse_type == "ACTION" and lh_ready:
                    # a. LH Simulation
                    self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].simulate, metrics, pulse_type, frame=self.frame)
                    # b. Callosum Synthesis
                    self._run_lobe("Corpus", self.lobes["Corpus"].score_tier, metrics, pulse_type, frame=self.frame)
                    # c. Gatekeeper Decision
                    self._run_lobe("Gatekeeper", self.lobes["Gatekeeper"].decide, metrics, pulse_type, frame=self.frame)

                    # d. Brain Stem & Valuation
                    if self.frame.command.ready_to_fire:
                        self._run_lobe("Brain_Stem", self.lobes["Brain_Stem"].load_and_hunt, metrics, pulse_type, 
                                      frame=self.frame, orchestrator=self)
                        
                        # e. Pons Cost Estimation
                        if self.pons is not None and hasattr(self.pons, "estimate"):
                            self._run_lobe("Pons", self.pons.estimate, metrics, pulse_type, frame=self.frame)
                        
                        # f. Allocation Sizing
                        if self.allocation_gland is not None and hasattr(self.allocation_gland, "allocate"):
                            self._run_lobe("Allocation", self.allocation_gland.allocate, metrics, pulse_type, frame=self.frame)

                    # g. Final Inhibit
                    if self.frame.command.ready_to_fire and not can_trade:
                        self.frame.command.approved = 0
                        self.frame.command.ready_to_fire = False
                        self.frame.command.reason = "Trading gate locked"
                
                elif pulse_type == "SEED" and lh_ready:
                    self._run_lobe("Left_Hemisphere", self.lobes["Left_Hemisphere"].simulate, metrics, pulse_type, frame=self.frame)

            # 7. EXECUTION (MINT)
            if pulse_type == "MINT":
                self.mint_cadence_count = (self.mint_cadence_count + 1) % 3
                if self.mint_cadence_count == 1:
                    import copy
                    self.stable_frame = copy.deepcopy(self.frame)
                
                if "Brain_Stem" in self.lobes:
                    if timing_inhibited:
                        self.frame.command.ready_to_fire = False
                        self.frame.command.reason = "TIMING_CANCEL (MINT > 30s)"
                    self._run_lobe("Brain_Stem", self.lobes["Brain_Stem"].load_and_hunt, metrics, pulse_type, 
                                  frame=self.frame, orchestrator=self)

            # 8. MAINTENANCE
            hook_status = {"amygdala": "skipped", "pineal": "skipped", "vault_reload": "skipped", "pituitary": "skipped", "crawler": "skipped"}
            try:
                self.amygdala.mint_synapse_ticket(pulse_type, self.frame)
                hook_status["amygdala"] = "ok"
            except Exception as e:
                hook_status["amygdala"] = f"error:{type(e).__name__}"
                print(f"[SOUL-E-P33-205] maintenance error: {e}")
            
            if pulse_type == "MINT":
                try: self.pineal.secrete_melatonin(pulse_type); hook_status["pineal"] = "ok"
                except: pass
                try: self._check_vault_mutation(); hook_status["vault_reload"] = "ok"
                except: pass
            try: self.pituitary.secrete_growth_hormone(pulse_type); hook_status["pituitary"] = "ok"
            except: pass
            if self.crawler is not None and hasattr(self.crawler, "crawl"):
                try: 
                    self.crawler.crawl(pulse_type, self.frame)
                    hook_status["crawler"] = "ok"
                except Exception as ce:
                    print(f"[SOUL-E-P35-210] crawler error: {ce}")

            # Canonical lifecycle pulse is Soul-owned and must not drift from lobe mutations.
            self.frame.market.pulse_type = pulse_type

        except Exception as e:
            print(f"[SOUL-F-P35-209] SOUL_CRITICAL: Cycle failed: {e}")

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
            print(f"[SOUL_LOBE_ERROR] lobe={name} error={err_msg}")
            raise e

    def _log_pulse(self, metrics: List[LobeMetrics], total_duration: float, hooks: Dict[str, str] = None):
        if not hasattr(self, "pulse_seq"): self.pulse_seq = 0
        self.pulse_seq += 1
        f = self.frame
        decision_summary = {
            "ready_to_fire": bool(f.command.ready_to_fire),
            "approved": int(f.command.approved),
            "reason": str(f.command.reason),
            "qty": float(f.command.qty),
            "size_reason": str(f.command.size_reason),
        }
        friction_summary = {
            "bid_ask_bps": float(f.environment.bid_ask_bps),
            "spread_score": float(f.environment.spread_score),
            "total_cost_bps": float(f.execution.total_cost_bps),
            "z_distance": float(f.valuation.z_distance),
        }
        self.pulse_log.append({
            "timestamp": datetime.now().isoformat(),
            "pulse_id": f"{self.run_id}:{self.pulse_seq}",
            "mode": str(f.market.execution_mode),
            "pulse_type": str(f.market.pulse_type),
            "symbol": str(f.market.symbol),
            "total_duration": total_duration,
            "decision_summary": decision_summary,
            "friction_summary": friction_summary,
            "hooks": hooks or {},
            "lobes": [m.__dict__ for m in metrics],
        })

    def simulate_hot_reload(self):
        """
        Piece 212: Manual/Simulated Hot-Reload.
        Relocated from Fornix to centralize orchestration authority.
        """
        try:
            from Hippocampus.Archivist.librarian import librarian
            vault = librarian.get_hormonal_vault()
            gold = (vault or {}).get("gold", {}).get("params", {}) if isinstance(vault, dict) else {}
            
            if gold:
                self.frame.standards = gold
                # piece 212: propagate to registered lobes
                for lobe in self.lobes.values():
                    if hasattr(lobe, "config") and lobe.config is not None:
                        lobe.config.update(gold)
                print(f"[SOUL] event=sim_hot_reload status=success")
        except Exception as e:
            # [SOUL-E-P14-213] Sim-hot-reload failed
            print(f"[SOUL-E-P14-213] SIM_HOT_RELOAD_FAILED: {e}")

    def _check_vault_mutation(self):
        try:
            vault = self.librarian.get_hormonal_vault()
            new_id = vault.get("gold", {}).get("id")
            if new_id != self.vault.get("gold", {}).get("id"):
                print(f"[SOUL] Gold Mutation: {new_id}. Hot-reloading...")
                self.vault = vault
                self.frame.standards = vault["gold"]["params"]
                for lobe in self.lobes.values():
                    if hasattr(lobe, "config") and lobe.config is not None:
                        lobe.config.update(self.frame.standards)
        except Exception as e:
            print(f"[SOUL-E-P14-212] Hot-reload failed: {e}")
