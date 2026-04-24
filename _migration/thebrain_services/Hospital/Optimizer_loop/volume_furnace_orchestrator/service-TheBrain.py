import uuid
from typing import Any, Dict, Optional

from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian
from Hospital.Optimizer_loop.optimizer_v2 import OptimizerV2Engine, V2Budget


class VolumeFurnaceOrchestrator:
    """
    Runtime cadence orchestrator for the Stage A-H optimizer v2 pipeline.
    """

    VALID_MODES = {"DRY_RUN", "PAPER", "LIVE", "BACKTEST"}

    def __init__(
        self,
        simulation_mode: bool = False,
        external_cadence: bool = False,
        execution_mode: str = "DRY_RUN",
    ):
        self.run_id = f"forge-v2-{uuid.uuid4().hex[:8]}"
        self.execution_mode = str(execution_mode or "DRY_RUN").upper()
        self.simulation_mode = bool(simulation_mode) or self.execution_mode == "BACKTEST"
        self.external_cadence = external_cadence
        self.shutdown_requested = False
        self.pulse_count = 0
        self.mint_count = 0
        self.activation_count = 0
        self.last_decision = "INIT"
        self.last_summary: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.telemetry: list[Dict[str, Any]] = []
        self.telemetry_limit = 200

        self.opt_lib = librarian
        self.budget = V2Budget()
        
        # Piece 209: Split Optimization - Initialize 5 domain-specific engines
        self.domains = ["RISK", "STRATEGY", "COUNCIL", "SYNTHESIS", "EXECUTION"]
        self.engines: Dict[str, OptimizerV2Engine] = {
            domain: OptimizerV2Engine(
                run_id=f"{self.run_id}-{domain}",
                librarian=self.opt_lib,
                seed=self._seed_from_run_id(f"{self.run_id}-{domain}"),
                budget=self.budget,
                domain=domain
            ) for domain in self.domains
        }
        
        # Primary engine pointer (legacy compatibility)
        self.engine = self.engines["RISK"]

        print(
            f"[FURNACE_V4] event=init run_id={self.run_id} "
            f"execution_mode={self.execution_mode} simulation_mode={self.simulation_mode} "
            f"mode=SPLIT_DOMAINS_ACTIVE domains={self.domains}"
        )

    def set_execution_mode(self, execution_mode: str):
        mode = str(execution_mode or "DRY_RUN").upper()
        self.execution_mode = mode
        self.simulation_mode = mode == "BACKTEST"

    def _record_decision(self, decision: str, **fields: Any):
        self.last_decision = decision
        evt = {
            "decision": decision,
            "mode": self.execution_mode,
            "mint": self.mint_count,
            "activation": self.activation_count,
        }
        evt.update(fields)
        self.telemetry.append(evt)
        if len(self.telemetry) > self.telemetry_limit:
            self.telemetry = self.telemetry[-self.telemetry_limit :]

    def _validate_context(
        self,
        *,
        pulse_type: str,
        mode: str,
        regime_id: str,
        price: float,
        atr: float,
        stop_level: float,
        support_floor_ok: bool,
    ) -> Optional[str]:
        if self.shutdown_requested:
            return "SHUTDOWN"
        if pulse_type != "MINT":
            return "CADENCE_GATE"
        if mode not in self.VALID_MODES:
            return "MODE_GATE"
        if not support_floor_ok:
            return "SUPPORT_FLOOR"
        if not regime_id or str(regime_id).upper() in {"", "UNK", "UNKNOWN", "NONE"}:
            return "MISSING_CONTEXT"
        if atr <= 0.0 or price <= 0.0 or stop_level <= 0.0:
            return "MISSING_CONTEXT"
        return None

    def _cadence_gate(self) -> Optional[str]:
        # Live cadence policy: every 3rd MINT unless caller supplies external cadence.
        if not self.external_cadence and (self.mint_count % 3 != 0):
            return "CADENCE_GATE"
        self.activation_count += 1

        # BACKTEST/simulation policy: execute every 4th scheduled activation.
        if self.simulation_mode and (self.activation_count % 4 != 0):
            return "CADENCE_GATE"
        return None

    def handle_pulse(
        self,
        pulse_type: str,
        regime_id: str,
        price: float = 0.0,
        atr: float = 0.0,
        stop_level: float = 0.0,
        walk_seed: Any = None,
    ):
        """
        Cadence-aligned Stage A-H execution.
        """
        # Piece 14: Furnace only fires at MINT
        if not enforce_pulse_gate(pulse_type, ["MINT"], "Hospital"):
            return

        mode = self.execution_mode
        self.pulse_count += 1
        if pulse_type == "MINT":
            self.mint_count += 1

        reason = self._validate_context(
            pulse_type=pulse_type,
            mode=mode,
            regime_id=str(regime_id or ""),
            price=float(price),
            atr=float(atr),
            stop_level=float(stop_level),
            support_floor_ok=True,
        )
        if reason:
            self._record_decision(reason, pulse_type=pulse_type, regime_id=regime_id)
            return

        cadence_reason = self._cadence_gate()
        if cadence_reason:
            self._record_decision(cadence_reason, pulse_type=pulse_type, regime_id=regime_id)
            return

        allow_bayesian = (self.activation_count % 4) == 0
        mutations = walk_seed.mutations if walk_seed else None

        try:
            summary = self.engine.run_pipeline(
                regime_id=regime_id,
                price=float(price),
                atr=float(atr),
                stop_level=float(stop_level),
                allow_bayesian=allow_bayesian,
                mutations=mutations,
            )
            self.last_summary = summary if isinstance(summary, dict) else {"result": summary}
            self.last_error = None
            self._record_decision(
                "EXECUTED",
                pulse_type=pulse_type,
                regime_id=regime_id,
                allow_bayesian=allow_bayesian,
                promotion_decision=self.last_summary.get("promotion_decision")
                or self.last_summary.get("reason"),
            )
            print(
                f"[FURNACE_V2] event=pipeline_complete run_id={self.run_id} "
                f"mint={self.mint_count} activation={self.activation_count} "
                f"regime_id={regime_id} summary={summary}"
            )
        except Exception as exc:
            # HOSP-E-P84-802: handle_pulse pipeline failure
            self.last_error = f"[HOSP-E-P84-802] {exc}"
            self.last_summary = {}
            self._record_decision("PIPELINE_ERROR", pulse_type=pulse_type, regime_id=regime_id, error=str(exc))
            print(
                f"[FURNACE_V2] event=pipeline_error run_id={self.run_id} "
                f"mint={self.mint_count} activation={self.activation_count} "
                f"regime_id={regime_id} error={exc}"
            )

    def handle_frame(self, *, pulse_type: str, frame: Any, walk_seed: Any = None, stage_group: str = "AUTO"):
        """
        Frame-truth entrypoint used by Soul/ForNix orchestration.
        Supports deterministic 15m cadence (SCOUT -> PRIME -> CALCULATE).
        """
        # Piece 14: Furnace ONLY fires on MINT
        if not enforce_pulse_gate(pulse_type, ["MINT"], "Hospital"):
            return

        mode = str(getattr(frame.market, "execution_mode", self.execution_mode) or self.execution_mode).upper()
        self.set_execution_mode(mode)

        regime_id = str(getattr(frame.risk, "regime_id", "") or "")
        mutations = getattr(walk_seed, "mutations", getattr(frame.risk, "mutations", None))
        support_floor_ok = bool(getattr(walk_seed, "support_floor_ok", True))
        
        self.pulse_count += 1
        self.mint_count += 1

        reason = self._validate_context(
            pulse_type=pulse_type,
            mode=mode,
            regime_id=regime_id,
            price=float(getattr(frame.structure, "price", 0.0) or 0.0),
            atr=float(getattr(frame.environment, "atr", 0.0) or 0.0),
            stop_level=float(getattr(frame.structure, "active_lo", 0.0) or 0.0),
            support_floor_ok=support_floor_ok,
        )
        if reason:
            self._record_decision(reason, pulse_type=pulse_type, regime_id=regime_id)
            return

        # Deterministic 15m Cadence (3 MINT pulses)
        # MINT 1: SCOUT (Stages A-C)
        # MINT 2: PRIME (Stages D-E)
        # MINT 3: CALCULATE (Stages F-H)
        
        # Piece 210: Auto-dispatch based on mint_count
        if stage_group == "AUTO":
            cycle_pos = self.mint_count % 3
            if cycle_pos == 1:
                target_stage = "SCOUT"
            elif cycle_pos == 2:
                target_stage = "PRIME"
            else: # pos 0
                target_stage = "CALCULATE"
        else:
            target_stage = stage_group

        try:
            domain_summaries = {}
            for domain in self.domains:
                engine = self.engines[domain]
                summary = engine.run_stage_group(
                    group=target_stage,
                    regime_id=regime_id,
                    price=float(getattr(frame.structure, "price", 0.0) or 0.0),
                    atr=float(getattr(frame.environment, "atr", 0.0) or 0.0),
                    stop_level=float(getattr(frame.structure, "active_lo", 0.0) or 0.0),
                    mutations=mutations
                )
                domain_summaries[domain] = summary

            self.last_summary = domain_summaries.get("RISK", {})
            self.last_error = None
            self._record_decision(
                "EXECUTED_PARALLEL",
                pulse_type=pulse_type,
                regime_id=regime_id,
                mode_context=mode,
                stage=target_stage,
                domain_count=len(domain_summaries),
            )
            
        except Exception as exc:
            # [HOSP-E-P84-803] handle_frame pipeline failure
            msg = f"[HOSP-E-P84-803] FURNACE_FAILURE: {exc}"
            self.last_error = msg
            self.last_summary = {}
            self._record_decision("PIPELINE_ERROR", pulse_type=pulse_type, regime_id=regime_id, error=str(exc))
            print(msg)

    def get_state(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "execution_mode": self.execution_mode,
            "simulation_mode": self.simulation_mode,
            "external_cadence": self.external_cadence,
            "pulse_count": self.pulse_count,
            "mint_count": self.mint_count,
            "activation_count": self.activation_count,
            "last_decision": self.last_decision,
            "last_summary": self.last_summary,
            "last_error": self.last_error,
            "telemetry_tail": self.telemetry[-20:],
        }

    def shutdown(self):
        self.shutdown_requested = True
        print(f"[FURNACE_V2] event=shutdown run_id={self.run_id}")

    @staticmethod
    def _seed_from_run_id(run_id: str) -> int:
        seed = 0
        for ch in run_id:
            seed = ((seed * 33) + ord(ch)) & 0xFFFFFFFF
        return int(seed)
