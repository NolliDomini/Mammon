from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


class SynapseScribe:
    """
    Isolated SQLite writer for synapse mint tickets.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS synapse_mint (
                machine_code TEXT PRIMARY KEY,
                ts TEXT,
                symbol TEXT,
                pulse_type TEXT,
                execution_mode TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                price REAL,
                gear REAL,
                tier1_signal REAL,
                monte_score REAL,
                tier_score REAL,
                regime_id TEXT,
                council_score REAL,
                atr REAL,
                decision TEXT,
                approved REAL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_synapse_mint_machine_code ON synapse_mint(machine_code)"
        )
        self.conn.commit()

    def _infer_sql_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "INTEGER"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        return "TEXT"

    def _normalize_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value)
        if isinstance(value, bool):
            return int(value)
        return value

    def _ensure_columns(self, ticket: Dict[str, Any]):
        existing = {
            row["name"] for row in self.conn.execute("PRAGMA table_info('synapse_mint')").fetchall()
        }
        for key, value in ticket.items():
            if key in existing:
                continue
            col_type = self._infer_sql_type(value)
            self.conn.execute(f'ALTER TABLE synapse_mint ADD COLUMN "{key}" {col_type}')
            existing.add(key)

    def mint(self, ticket: Dict[str, Any]):
        if not isinstance(ticket, dict):
            raise TypeError("ticket must be a dict")
        if not ticket.get("machine_code"):
            raise ValueError("ticket.machine_code is required")

        self._ensure_columns(ticket)

        cols = list(ticket.keys())
        vals = [self._normalize_value(ticket[c]) for c in cols]
        quoted_cols = [f'"{c}"' for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        update_cols = [c for c in cols if c != "machine_code"]
        update_sql = ", ".join([f'"{c}"=excluded."{c}"' for c in update_cols]) or '"machine_code"="machine_code"'

        sql = f"""
            INSERT INTO synapse_mint ({", ".join(quoted_cols)})
            VALUES ({placeholders})
            ON CONFLICT(machine_code) DO UPDATE SET {update_sql}
        """
        self.conn.execute(sql, vals)
        self.conn.commit()

