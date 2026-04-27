from pathlib import Path
from typing import Dict, Any, Optional, Set
import math
from Cerebellum.Soul.brain_frame import BrainFrame
from Hippocampus.Archivist.synapse_scribe import SynapseScribe

class Amygdala:
    """
    Hippocampus/Amygdala: The State-Scribe.
    V3.1 AIRTIGHT: Direct isolation to the Synapse Silo.
    """
    def __init__(self, db_path: Path = None, scribe: SynapseScribe = None, config: Dict[str, Any] = None):
        self.config = config or {}
        archivist_dir = Path(__file__).resolve().parents[1] / "Archivist"
        self._primary_db_path = Path(
            db_path
            or self.config.get("synapse_db_path_primary")
            or (archivist_dir / "Ecosystem_Synapse.db")
        )
        self._backtest_db_path = Path(
            self.config.get("synapse_db_path_backtest")
            or (archivist_dir / "Ecosystem_Synapse_Backtest.db")
        )
        self.scribe = scribe or SynapseScribe(db_path=self._primary_db_path)
        self._scribes: Dict[str, SynapseScribe] = {"PRIMARY": self.scribe}
        configured_pulses = self.config.get("synapse_persist_pulse_types", ["SEED", "ACTION", "MINT"])
        if isinstance(configured_pulses, str):
            configured_pulses = [configured_pulses]
        self.persist_pulse_types: Set[str] = {
            str(p).strip().upper() for p in (configured_pulses or []) if str(p).strip()
        }
        if not self.persist_pulse_types:
            self.persist_pulse_types = {"MINT"}
        self.last_mint_ts = None
        self.mint_count = 0
        self.persist_count = 0
        self.last_machine_code = None
        self.last_target_db = str(self._primary_db_path)
        self.last_write_status = "IDLE"
        self.last_error_code = None
        self.last_error_message = None

    REQUIRED_KEYS = (
        "ts", "symbol", "pulse_type", "execution_mode",
        "open", "high", "low", "close", "volume",
        "price", "gear", "tier1_signal",
        "monte_score", "tier_score", "regime_id",
        "council_score", "atr", "decision", "approved",
    )

    def _normalize_scalar(self, value: Any):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, float):
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
        pulse = str(ticket.get("pulse_type") or "").upper()
        if pulse not in self.persist_pulse_types:
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

    def _get_scribe_for_mode(self, mode: str):
        mode_u = str(mode or "DRY_RUN").upper()
        if mode_u == "BACKTEST":
            if "BACKTEST" not in self._scribes:
                self._scribes["BACKTEST"] = SynapseScribe(db_path=self._backtest_db_path)
            return self._scribes["BACKTEST"], self._backtest_db_path
        primary = self.scribe if self.scribe is not None else self._scribes["PRIMARY"]
        self._scribes["PRIMARY"] = primary
        return primary, self._primary_db_path

    def mint_synapse_ticket(self, pulse_type: str, frame: BrainFrame):
        """
        Mints the unified ticket by flattening the BrainFrame into the isolated silo.
        Default behavior is MINT-only; decision-quality mode can persist SEED/ACTION too.
        """
        pulse_type_u = str(pulse_type or "").upper()
        if pulse_type_u not in self.persist_pulse_types:
            return

        try:
            raw_ticket = frame.to_synapse_dict()
            ticket = self._normalize_ticket(raw_ticket)
            ticket["pulse_type"] = pulse_type_u
            ticket["machine_code"] = self._compose_machine_code(ticket, pulse_type_u)
            mode = str(ticket.get("execution_mode") or "DRY_RUN").upper()
            err = self._validate_ticket(ticket)
            if err:
                self.last_write_status = "REJECTED"
                self.last_error_code = err
                self.last_error_message = "schema validation failure"
                return

            target_scribe, target_db = self._get_scribe_for_mode(mode)
            target_scribe.mint(ticket)
            if pulse_type_u == "MINT":
                self.last_mint_ts = ticket.get("ts")
                self.mint_count += 1
            self.persist_count += 1
            self.last_machine_code = ticket.get("machine_code")
            self.last_target_db = str(target_db)
            self.last_write_status = "SUCCESS"
            self.last_error_code = None
            self.last_error_message = None
            print(f"[AMYGDALA] {pulse_type_u} Synapse Isolated (Silo): {ticket.get('ts')}")
        except Exception as e:
            self.last_write_status = "ERROR"
            self.last_error_code = "WRITE_FAILURE"
            self.last_error_message = str(e)
            print(f"[AMYGDALA_ERROR] mint_synapse_ticket failed ({pulse_type_u}): {type(e).__name__}: {e}")

    def get_state(self):
        return {
            "mint_count": self.mint_count,
            "persist_count": self.persist_count,
            "last_ts": self.last_mint_ts,
            "last_machine_code": self.last_machine_code,
            "last_target_db": self.last_target_db,
            "persist_pulse_types": sorted(self.persist_pulse_types),
            "last_write_status": self.last_write_status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
        }
