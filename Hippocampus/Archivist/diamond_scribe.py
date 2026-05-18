from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "Hospital" / "Memory_care" / "diamond_silo.db"


class DiamondScribe:
    """
    Private reset-on-write silo for Diamond Bayesian training data.
    Each dump() wipes the previous training_matrix and replaces it with fresh rows.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def dump(self, df) -> None:
        """Reset silo and write fresh training rows from a DataFrame."""
        if df is None or df.empty:
            return

        cols = list(df.columns)
        col_defs = ", ".join(f'"{c}" REAL' for c in cols)
        placeholders = ", ".join("?" * len(cols))
        rows = [tuple(row) for row in df.itertuples(index=False, name=None)]

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DROP TABLE IF EXISTS training_matrix")
            conn.execute(f"CREATE TABLE training_matrix ({col_defs})")
            conn.executemany(f"INSERT INTO training_matrix VALUES ({placeholders})", rows)
            conn.commit()

        print(f"[DIAMOND_SCRIBE] Silo reset — {len(rows):,} rows, {len(cols)} cols.")
