import sqlite3
import time
import json
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).resolve().parent / "control_logs.db"


class ControlLogScribe:
    """
    Hospital: Persistent audit log for non-approved engine decisions.
    Writes INHIBIT, REJECT, and operational events to control_logs.db.
    Designed for safe concurrent access — opens, writes, closes per call.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db = Path(db_path or _DB_PATH)
        self._init_schema()

    def _init_schema(self):
        with sqlite3.connect(self._db, timeout=5) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS control_logs (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts      REAL    NOT NULL,
                    symbol  TEXT,
                    pulse_type TEXT,
                    decision   TEXT NOT NULL,
                    reason     TEXT,
                    source     TEXT,
                    details_json TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ctrl_ts ON control_logs(ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ctrl_decision ON control_logs(decision)"
            )

    def log(
        self,
        decision: str,
        reason: str,
        source: str,
        symbol: Optional[str] = None,
        pulse_type: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        try:
            with sqlite3.connect(self._db, timeout=5) as conn:
                conn.execute(
                    """INSERT INTO control_logs
                           (ts, symbol, pulse_type, decision, reason, source, details_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        time.time(),
                        symbol,
                        pulse_type,
                        str(decision),
                        str(reason),
                        str(source),
                        json.dumps(details) if details else None,
                    ),
                )
        except Exception as exc:
            print(f"[CONTROL_LOG_SCRIBE] write failed: {exc}")
