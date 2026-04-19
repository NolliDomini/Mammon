import uuid
from typing import Any, Dict, Optional

from Hospital.Optimizer_loop.optimizer_v2 import OptimizerV2Engine, V2Budget
from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian


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

        self.opt_lib = OptimizerLibrarian()
        self.opt_lib.setup_schema()
        self.budget = V2Budget()
        self.engine = OptimizerV2Engine(
            run_id=self.run_id,
            librarian=self.opt_lib,
            seed=self._seed_from_run_id(self.run_id),
            budget=self.budget,
        )

        print(
            f"[FURNACE_V2] event=init run_id={self.run_id} "
            f"execution_mode={self.execution_mode} simulation_mode={self.simulation_mode} "
            f"external_cadence={self.external_cadence} "
            f"mode=STAGE_A_H_ACTIVE"
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

    def _coerce_context(
        self,
        *,
        regime_id: str,
        price: float,
        atr: float,
        stop_level: float,
    ) -> tuple[str, float, float, float, list[str]]:
        """
        Normalize runtime context so warmup frames do not suppress cadence execution.
        """
        fallback_flags: list[str] = []

        regime = str(regime_id or "").strip()
        if regime.upper() in {"", "UNK", "UNKNOWN", "NONE"}:
            regime = "GLOBAL"
            fallback_flags.append("REGIME_FALLBACK")

        p = float(price or 0.0)
        a = float(atr or 0.0)
        s = float(stop_level or 0.0)

        if p > 0.0 and a <= 0.0:
            # Use a conservative 0.10% ATR proxy until Council warmup completes.
            a = max(p * 0.001, 1e-6)
            fallback_flags.append("ATR_FALLBACK")
        if p > 0.0 and s <= 0.0 and a > 0.0:
            # Derive a synthetic stop floor from price and ATR proxy.
            s = max(p - (1.5 * a), 1e-6)
            fallback_flags.append("STOP_FALLBACK")

        return regime, p, a, s, fallback_flags

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
        if price <= 0.0:
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
        mode = self.execution_mode
        self.pulse_count += 1
        if pulse_type == "MINT":
            self.mint_count += 1

        regime_ctx, price_ctx, atr_ctx, stop_ctx, fallback_flags = self._coerce_context(
            regime_id=str(regime_id or ""),
            price=float(price),
            atr=float(atr),
            stop_level=float(stop_level),
        )

        reason = self._validate_context(
            pulse_type=pulse_type,
            mode=mode,
            regime_id=regime_ctx,
            price=price_ctx,
            atr=atr_ctx,
            stop_level=stop_ctx,
            support_floor_ok=True,
        )
        if reason:
            self._record_decision(
                reason,
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                context_fallbacks=fallback_flags,
            )
            return

        cadence_reason = self._cadence_gate()
        if cadence_reason:
            self._record_decision(
                cadence_reason,
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                context_fallbacks=fallback_flags,
            )
            return

        allow_bayesian = (self.activation_count % 4) == 0
        mutations = walk_seed.mutations if walk_seed else None

        try:
            summary = self.engine.run_pipeline(
                regime_id=regime_ctx,
                price=price_ctx,
                atr=atr_ctx,
                stop_level=stop_ctx,
                allow_bayesian=allow_bayesian,
                mutations=mutations,
            )
            self.last_summary = summary if isinstance(summary, dict) else {"result": summary}
            self.last_error = None
            self._record_decision(
                "EXECUTED",
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                allow_bayesian=allow_bayesian,
                context_fallbacks=fallback_flags,
                promotion_decision=self.last_summary.get("promotion_decision")
                or self.last_summary.get("reason"),
            )
            print(
                f"[FURNACE_V2] event=pipeline_complete run_id={self.run_id} "
                f"mint={self.mint_count} activation={self.activation_count} "
                f"regime_id={regime_ctx} summary={summary}"
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.last_summary = {}
            self._record_decision(
                "PIPELINE_ERROR",
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                error=str(exc),
                context_fallbacks=fallback_flags,
            )
            print(
                f"[FURNACE_V2] event=pipeline_error run_id={self.run_id} "
                f"mint={self.mint_count} activation={self.activation_count} "
                f"regime_id={regime_ctx} error={exc}"
            )

    def handle_frame(self, *, pulse_type: str, frame: Any, walk_seed: Any = None):
        """
        Frame-truth entrypoint used by Soul/ForNix orchestration.
        """
        mode = str(getattr(frame.market, "execution_mode", self.execution_mode) or self.execution_mode).upper()
        self.set_execution_mode(mode)

        regime_id = str(getattr(frame.risk, "regime_id", "") or "")
        if regime_id in {"", "UNK", "UNKNOWN", "NONE"} and walk_seed is not None:
            regime_id = str(getattr(walk_seed, "regime_id", "") or "")

        mutations = None
        if walk_seed is not None and hasattr(walk_seed, "mutations"):
            mutations = getattr(walk_seed, "mutations")
        elif hasattr(frame.risk, "mutations"):
            mutations = getattr(frame.risk, "mutations")
        elif hasattr(frame.risk, "shocks"):
            mutations = getattr(frame.risk, "shocks")

        support_floor_ok = bool(getattr(walk_seed, "support_floor_ok", True))
        self.pulse_count += 1
        if pulse_type == "MINT":
            self.mint_count += 1

        regime_ctx, price_ctx, atr_ctx, stop_ctx, fallback_flags = self._coerce_context(
            regime_id=regime_id,
            price=float(getattr(frame.structure, "price", 0.0) or 0.0),
            atr=float(getattr(frame.environment, "atr", 0.0) or 0.0),
            stop_level=float(getattr(frame.structure, "active_lo", 0.0) or 0.0),
        )

        reason = self._validate_context(
            pulse_type=pulse_type,
            mode=mode,
            regime_id=regime_ctx,
            price=price_ctx,
            atr=atr_ctx,
            stop_level=stop_ctx,
            support_floor_ok=support_floor_ok,
        )
        if reason:
            self._record_decision(
                reason,
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                context_fallbacks=fallback_flags,
            )
            return

        cadence_reason = self._cadence_gate()
        if cadence_reason:
            self._record_decision(
                cadence_reason,
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                context_fallbacks=fallback_flags,
            )
            return

        allow_bayesian = (self.activation_count % 4) == 0
        try:
            summary = self.engine.run_pipeline(
                regime_id=regime_ctx,
                price=price_ctx,
                atr=atr_ctx,
                stop_level=stop_ctx,
                allow_bayesian=allow_bayesian,
                mutations=mutations,
            )
            self.last_summary = summary if isinstance(summary, dict) else {"result": summary}
            self.last_error = None
            self._record_decision(
                "EXECUTED",
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                allow_bayesian=allow_bayesian,
                mode_context=mode,
                context_fallbacks=fallback_flags,
                promotion_decision=self.last_summary.get("promotion_decision")
                or self.last_summary.get("reason"),
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.last_summary = {}
            self._record_decision(
                "PIPELINE_ERROR",
                pulse_type=pulse_type,
                regime_id=regime_ctx,
                error=str(exc),
                context_fallbacks=fallback_flags,
            )

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
