import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

_UI_DB = Path(__file__).resolve().parent / "Ecosystem_UI.db"


class UiScribe:
    """
    Hippocampus/Archivist: Writes per-MINT snapshots to Ecosystem_UI.db.
    Provides the live data feed for the UI dashboard and PnL tray.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db = Path(db_path or _UI_DB)
        self._schema_ready = False
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        try:
            with sqlite3.connect(self._db, timeout=10) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ui_pulse_tape (
                        ts          TEXT NOT NULL,
                        symbol      TEXT NOT NULL,
                        price       REAL,
                        decision    TEXT,
                        approved    INTEGER,
                        council_score REAL,
                        monte_score   REAL,
                        tier1_signal  INTEGER,
                        regime_id     TEXT,
                        adx           REAL,
                        atr           REAL,
                        active_hi     REAL,
                        active_lo     REAL,
                        final_confidence REAL,
                        qty           REAL,
                        notional      REAL,
                        PRIMARY KEY (ts, symbol)
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ui_ts ON ui_pulse_tape(ts DESC)"
                )
            self._schema_ready = True
        except Exception as exc:
            print(f"[UI_SCRIBE] _init_schema deferred: {exc}")
            self._schema_ready = False

    def write_mint(self, frame: Any):
        """Flatten the key BrainFrame fields into ui_pulse_tape on every MINT."""
        if not self._schema_ready:
            self._init_schema()
            if not self._schema_ready:
                return
        try:
            ts = str(getattr(getattr(frame, "market", None), "ts", "") or "")
            symbol = str(getattr(getattr(frame, "market", None), "symbol", "") or "")
            if not ts or not symbol:
                return
            with sqlite3.connect(self._db, timeout=5) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO ui_pulse_tape
                           (ts, symbol, price, decision, approved,
                            council_score, monte_score, tier1_signal, regime_id,
                            adx, atr, active_hi, active_lo,
                            final_confidence, qty, notional)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ts,
                        symbol,
                        float(getattr(getattr(frame, "structure", None), "price", 0.0) or 0.0),
                        str(getattr(getattr(frame, "command", None), "reason", "WAITING") or "WAITING"),
                        int(getattr(getattr(frame, "command", None), "approved", 0) or 0),
                        float(getattr(getattr(frame, "environment", None), "confidence", 0.0) or 0.0),
                        float(getattr(getattr(frame, "risk", None), "monte_score", 0.0) or 0.0),
                        int(getattr(getattr(frame, "structure", None), "tier1_signal", 0) or 0),
                        str(getattr(getattr(frame, "risk", None), "regime_id", "") or ""),
                        float(getattr(getattr(frame, "environment", None), "adx", 0.0) or 0.0),
                        float(getattr(getattr(frame, "environment", None), "atr", 0.0) or 0.0),
                        float(getattr(getattr(frame, "structure", None), "active_hi", 0.0) or 0.0),
                        float(getattr(getattr(frame, "structure", None), "active_lo", 0.0) or 0.0),
                        float(getattr(getattr(frame, "command", None), "final_confidence", 0.0) or 0.0),
                        float(getattr(getattr(frame, "command", None), "qty", 0.0) or 0.0),
                        float(getattr(getattr(frame, "command", None), "notional", 0.0) or 0.0),
                    ),
                )
        except Exception as exc:
            print(f"[UI_SCRIBE] write_mint failed: {exc}")
