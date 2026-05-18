import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
_MONEY_DB  = _ROOT / "runtime" / ".tmp_test_local" / "compat_librarian.db"
_SYNAPSE_DB = _ROOT / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db"
_UI_DB      = _ROOT / "Hippocampus" / "Archivist" / "Ecosystem_UI.db"


class PnlTrayReader:
    """
    Direct SQLite reader for the left PnL tray.
    No engine dependency — safe to call from the UI at any time.
    Each method opens, reads, and closes its own connection.
    """

    def __init__(
        self,
        money_db: Optional[Path] = None,
        synapse_db: Optional[Path] = None,
        ui_db: Optional[Path] = None,
    ):
        self._money   = Path(money_db   or _MONEY_DB)
        self._synapse = Path(synapse_db or _SYNAPSE_DB)
        self._ui      = Path(ui_db      or _UI_DB)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _query(self, db: Path, sql: str, params: tuple = ()) -> List[Dict]:
        if not db.exists():
            return []
        try:
            with sqlite3.connect(db, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except Exception as exc:
            print(f"[PNL_TRAY] query failed ({db.name}): {exc}")
            return []

    def _scalar(self, db: Path, sql: str, params: tuple = (), default=0.0):
        rows = self._query(db, sql, params)
        if rows:
            val = list(rows[0].values())[0]
            return val if val is not None else default
        return default

    # ------------------------------------------------------------------ #
    #  Position / PnL                                                      #
    # ------------------------------------------------------------------ #

    def get_open_positions(self) -> List[Dict]:
        return self._query(
            self._money,
            """SELECT symbol, mode, qty, avg_price, market_price,
                      unrealized_pnl, realized_pnl, updated_at
               FROM money_positions
               WHERE qty != 0
               ORDER BY updated_at DESC""",
        )

    def get_all_positions(self) -> List[Dict]:
        return self._query(
            self._money,
            """SELECT symbol, mode, qty, avg_price, market_price,
                      unrealized_pnl, realized_pnl, updated_at
               FROM money_positions
               ORDER BY updated_at DESC""",
        )

    def get_realized_pnl_today(self) -> float:
        today_start = float(int(time.time() / 86400) * 86400)
        return float(
            self._scalar(
                self._money,
                "SELECT SUM(realized_pnl) FROM money_positions WHERE updated_at >= ?",
                (today_start,),
                default=0.0,
            )
            or 0.0
        )

    # ------------------------------------------------------------------ #
    #  Orders                                                              #
    # ------------------------------------------------------------------ #

    def get_recent_orders(self, n: int = 20) -> List[Dict]:
        return self._query(
            self._money,
            """SELECT intent_id, ts, symbol, side, qty, mode, status,
                      price_ref, confidence, reason
               FROM money_orders
               ORDER BY ts DESC
               LIMIT ?""",
            (n,),
        )

    def get_filled_orders(self, n: int = 50) -> List[Dict]:
        return self._query(
            self._money,
            """SELECT intent_id, ts, symbol, side, qty, mode,
                      price_ref, confidence, reason
               FROM money_orders
               WHERE status = 'FILLED'
               ORDER BY ts DESC
               LIMIT ?""",
            (n,),
        )

    # ------------------------------------------------------------------ #
    #  Last pulse (from synapse)                                           #
    # ------------------------------------------------------------------ #

    def get_last_pulse(self) -> Dict[str, Any]:
        rows = self._query(
            self._synapse,
            """SELECT ts, symbol, decision, approved, council_score, monte_score,
                      tier1_signal, regime_id, price, final_confidence, adx, atr,
                      active_hi, active_lo
               FROM synapse_mint
               WHERE pulse_type = 'MINT'
               ORDER BY ts DESC
               LIMIT 1""",
        )
        return rows[0] if rows else {}

    def get_recent_pulses(self, n: int = 20) -> List[Dict]:
        return self._query(
            self._synapse,
            """SELECT ts, symbol, price, decision, approved,
                      council_score, monte_score, regime_id, tier1_signal
               FROM synapse_mint
               WHERE pulse_type = 'MINT'
               ORDER BY ts DESC
               LIMIT ?""",
            (n,),
        )

    # ------------------------------------------------------------------ #
    #  UI tape (from Ecosystem_UI.db written by UiScribe)                  #
    # ------------------------------------------------------------------ #

    def get_ui_tape(self, n: int = 100) -> List[Dict]:
        return self._query(
            self._ui,
            """SELECT ts, symbol, price, decision, approved,
                      council_score, monte_score, tier1_signal, regime_id,
                      adx, atr, active_hi, active_lo, final_confidence,
                      qty, notional
               FROM ui_pulse_tape
               ORDER BY ts DESC
               LIMIT ?""",
            (n,),
        )

    # ------------------------------------------------------------------ #
    #  Summary (the tray payload)                                          #
    # ------------------------------------------------------------------ #

    def get_pnl_summary(self) -> Dict[str, Any]:
        positions   = self.get_all_positions()
        open_pos    = [p for p in positions if p.get("qty", 0) != 0]
        unrealized  = sum(p.get("unrealized_pnl", 0.0) or 0.0 for p in open_pos)
        realized    = sum(p.get("realized_pnl",   0.0) or 0.0 for p in positions)
        last_pulse  = self.get_last_pulse()

        return {
            "unrealized_pnl":  round(unrealized, 4),
            "realized_pnl":    round(realized,   4),
            "total_pnl":       round(unrealized + realized, 4),
            "open_positions":  open_pos,
            "position_count":  len(open_pos),
            "last_ts":         last_pulse.get("ts"),
            "last_price":      last_pulse.get("price"),
            "last_decision":   last_pulse.get("decision"),
            "council_score":   last_pulse.get("council_score"),
            "monte_score":     last_pulse.get("monte_score"),
            "regime_id":       last_pulse.get("regime_id"),
            "tier1_signal":    last_pulse.get("tier1_signal"),
        }
