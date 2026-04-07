from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate
from Hippocampus.Archivist.librarian import librarian


class Amygdala:
    """
    Hippocampus/Amygdala: The State-Scribe.
    V3.2 ANALYTICAL: Direct isolation to the DuckDB Synapse.
    """
    def __init__(self, config: Dict[str, Any] = None, librarian_instance=None):
        self.config = config or {}
        self.librarian = librarian_instance or librarian
        self.scribe = _LibrarianScribe(self.librarian)
        self.last_mint_ts = None
        self.mint_count = 0
        self.last_machine_code = None
        self.last_target_db = None
        self.last_write_status = "IDLE"
        self.last_error_code = None
        self.last_error_message = None

        primary_db = self.config.get("synapse_db_path_primary")
        backtest_db = self.config.get("synapse_db_path_backtest")
        if primary_db:
            self.scribe.ensure_schema(str(primary_db))
        if backtest_db:
            self.scribe.ensure_schema(str(backtest_db))

    # Target #65: Reconciled with synapse_mint DuckDB schema
    REQUIRED_KEYS = (
        "ts", "symbol", "pulse_type", "execution_mode",
        "price", "gear", "tier1_signal",
        "mu", "sigma", "p_jump", "monte_score", "tier_score", "regime_id",
        "worst_survival", "neutral_survival", "best_survival",
        "council_score", "atr", "decision", "approved",
        "bid_ask_bps", "val_mean", "exec_total_cost_bps", "qty"
    )

    def _normalize_scalar(self, value: Any):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, float):
            import math
            if math.isnan(value) or math.isinf(value):
                return 0.0
        return value

    def _normalize_ticket(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        return {k: self._normalize_scalar(v) for k, v in (ticket or {}).items()}

    def _validate_ticket(self, ticket: Dict[str, Any]) -> Optional[str]:
        for key in self.REQUIRED_KEYS:
            if key not in ticket:
                return f"MISSING_KEY:{key}"
        if not str(ticket.get("symbol") or "").strip():
            return "INVALID_SYMBOL"
        if str(ticket.get("pulse_type") or "").upper() != "MINT":
            return "INVALID_PULSE_TYPE"
        return None

    def _compose_machine_code(self, ticket: Dict[str, Any], pulse_type: str) -> str:
        mode = str(ticket.get("execution_mode") or "DRY_RUN").upper()
        pulse = str(pulse_type or ticket.get("pulse_type") or "MINT").upper()
        symbol = str(ticket.get("symbol") or "UNKNOWN").upper().replace(" ", "")
        regime = str(ticket.get("regime_id") or "UNK").upper()
        decision = str(ticket.get("decision") or "WAITING").upper()
        ts_raw = ticket.get("ts")
        ts = str(self._normalize_scalar(ts_raw) or "0")
        return f"{mode}|{pulse}|{symbol}|{regime}|{decision}|{ts}"

    def mint_synapse_ticket(self, pulse_type: str, frame: BrainFrame):
        """
        Mints the unified ticket by flattening the BrainFrame into the isolated silo.
        V3.2 ANALYTICAL: Only MINT pulses are persisted to DuckDB.
        """
        # Piece 14: Scribing only happens at MINT
        if not enforce_pulse_gate(pulse_type, ["MINT"], "Amygdala"):
            return

        try:
            raw_ticket = frame.to_synapse_dict()
            ticket = self._normalize_ticket(raw_ticket)
            ticket["pulse_type"] = "MINT"
            ticket["machine_code"] = self._compose_machine_code(ticket, pulse_type)
            
            err = self._validate_ticket(ticket)
            if err:
                self.last_write_status = "REJECTED"
                self.last_error_code = err
                self.last_error_message = "schema validation failure"
                return

            mode = str(ticket.get("execution_mode") or "DRY_RUN").upper()
            
            # Target #23: Rapid Simulation Isolation
            # Skip physical write if mock_write is enabled during BACKTEST
            if mode == "BACKTEST" and self.config.get("backtest_mock_write", False):
                self.last_write_status = "MOCK_SUCCESS"
                self.mint_count += 1
                return

            primary_db = self.config.get("synapse_db_path_primary")
            backtest_db = self.config.get("synapse_db_path_backtest")
            target_db = None
            if mode == "BACKTEST" and backtest_db:
                target_db = str(backtest_db)
            elif primary_db:
                target_db = str(primary_db)

            # Piece 16: Atomic Analytical Write to DuckDB
            try:
                self.scribe.mint(ticket, target_db=target_db)
            except TypeError:
                # Legacy 1-arg scribe contract.
                self.scribe.mint(ticket)
            
            self.last_mint_ts = ticket.get("ts")
            self.last_machine_code = ticket.get("machine_code")
            self.last_target_db = target_db
            self.mint_count += 1
            self.last_write_status = "SUCCESS"
            self.last_error_code = None
            self.last_error_message = None
            print(f"[AMYGDALA] MINT Synapse Analytical (DuckDB): {self.last_mint_ts}")
        except Exception as e:
            # HIPP-E-P70-714: Synapse ticket write failure
            self.last_write_status = "ERROR"
            self.last_error_code = "WRITE_FAILURE"
            self.last_error_message = str(e)
            print(f"[HIPP-E-P70-714] AMYGDALA: mint_synapse_ticket failed: {e}")

    def get_state(self):
        return {
            "mint_count": self.mint_count,
            "last_ts": self.last_mint_ts,
            "last_machine_code": self.last_machine_code,
            "last_target_db": self.last_target_db,
            "last_write_status": self.last_write_status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
        }

    # --- Optimizer Audit Scribing (Relocated from Hospital) ---
    
    def log_stage_run(self, run_id: str, stage_name: str, status: str, regime_id: str = "", metrics: Dict = None, reason_code: str = ""):
        """Piece 162: Centralized Optimizer Stage Logging."""
        metrics_json = json.dumps(metrics or {}, sort_keys=True)
        self.librarian.log_stage_run(run_id, stage_name, status, regime_id, metrics_json, reason_code)

    def register_candidate(self, run_id: str, candidate_id: str, source_stage: str, params: Dict, 
                           regime_id: str = "", diversity_dist: float = 0.0, support_count: int = 0, 
                           kept: bool = True, reason_code: str = ""):
        """Piece 162: Centralized Candidate Library Persistence."""
        param_json = json.dumps(params, sort_keys=True)
        self.librarian.upsert_candidate_library(
            candidate_id=candidate_id,
            run_id=run_id,
            source_stage=source_stage,
            param_json=param_json,
            regime_id=regime_id,
            diversity_dist=diversity_dist,
            support_count=support_count,
            kept=1 if kept else 0,
            reason_code=reason_code,
        )


class _LibrarianScribe:
    def __init__(self, lib):
        self.lib = lib

    def mint(self, ticket: Dict[str, Any], target_db: Optional[str] = None):
        # Fast path: write through current librarian binding.
        if not target_db or not hasattr(self.lib, "duck_db_path"):
            self.lib.mint_synapse(ticket)
            return

        # Contract path: isolate write to requested DB path.
        original_path = getattr(self.lib, "duck_db_path", None)
        original_conn = getattr(self.lib, "_duck_conn", None)
        try:
            if original_conn is not None:
                try:
                    original_conn.close()
                except Exception:
                    pass
            self.lib._duck_conn = None
            self.lib.duck_db_path = Path(target_db)
            self.lib.setup_schema()
            self.lib.mint_synapse(ticket)
        finally:
            if getattr(self.lib, "_duck_conn", None) is not None:
                try:
                    self.lib._duck_conn.close()
                except Exception:
                    pass
            self.lib._duck_conn = None
            if original_path is not None:
                self.lib.duck_db_path = original_path

    def ensure_schema(self, target_db: str):
        if not target_db or not hasattr(self.lib, "duck_db_path"):
            return
        original_path = getattr(self.lib, "duck_db_path", None)
        original_conn = getattr(self.lib, "_duck_conn", None)
        try:
            if original_conn is not None:
                try:
                    original_conn.close()
                except Exception:
                    pass
            self.lib._duck_conn = None
            self.lib.duck_db_path = Path(target_db)
            self.lib.setup_schema()
        finally:
            if getattr(self.lib, "_duck_conn", None) is not None:
                try:
                    self.lib._duck_conn.close()
                except Exception:
                    pass
            self.lib._duck_conn = None
            if original_path is not None:
                self.lib.duck_db_path = original_path
