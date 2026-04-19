import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
from Hippocampus.Archivist.librarian import Librarian

class SynapseRefinery:
    """
    Pituitary/Refinery: The Synapse Harvester.
    Aggregates 'Internal Monologue' tickets into training matrices for Diamond.
    """
    def __init__(self, synapse_db_path: Optional[Path] = None):
        self.db_path = synapse_db_path or Path(__file__).resolve().parents[2] / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db"
        self.librarian = Librarian(db_path=self.db_path)

    def _resolve_time_filter(self) -> tuple[str, str]:
        """
        Determine which timestamp column exists and how to filter it.
        """
        try:
            cols = self.librarian.read_only("PRAGMA table_info('synapse_mint')")
            names = {str(c.get("name", "")).lower() for c in cols if isinstance(c, dict)}
        except Exception:
            names = set()

        if "created_at" in names:
            return "created_at", "datetime(created_at) >= datetime('now', ?)"
        if "ts" in names:
            # ts is typically ISO-8601 text in this silo (e.g., 2026-04-18T21:25:00+00:00).
            return "ts", "datetime(replace(substr(ts, 1, 19), 'T', ' ')) >= datetime('now', ?)"
        return "", ""

    def harvest_training_data(self, hours: int = 24) -> pd.DataFrame:
        """
        Extracts recent synapse tickets and calculates a 'Realized Fitness' score.
        """
        print(f"[REFINERY] Harvesting synapse tickets from last {hours}h...")

        time_col, time_predicate = self._resolve_time_filter()
        lookback = f"-{int(hours)} hours"
        if time_col:
            query = f"""
                SELECT * FROM synapse_mint
                WHERE {time_predicate}
                AND pulse_type = 'MINT'
            """
            params = (lookback,)
        else:
            query = """
                SELECT * FROM synapse_mint
                WHERE pulse_type = 'MINT'
            """
            params = ()
        
        try:
            # V3.1: Use Librarian for unified access
            rows = self.librarian.read_only(query, params)
            df = pd.DataFrame(rows)
            
            if df.empty:
                print("[REFINERY] Lake is empty. No training data available.")
                return pd.DataFrame()

            # Calculate 'Surgical Fitness' (How well did the brain predict reality?)
            # 1. Price vs Active Bounds
            # 2. Approved Decision vs Final Confidence
            
            # Simple fitness proxy: (Close - active_lo) / (active_hi - active_lo) normalized
            # This is a placeholder; real fitness will correlate to P/L of the trade if approved.
            df['realized_fitness'] = np.where(
                (df['active_hi'] - df['active_lo']) > 0,
                (df['close'] - df['active_lo']) / (df['active_hi'] - df['active_lo']),
                0.5
            )
            
            # Penalize low confidence approved trades that failed
            # (Logic for more complex fitness mapping goes here)
            
            print(f"[REFINERY] Harvested {len(df)} tickets. Matrix ready.")
            return df
            
        except Exception as e:
            print(f"[REFINERY ERROR] Harvest failed: {e}")
            return pd.DataFrame()

if __name__ == "__main__":
    refinery = SynapseRefinery()
    data = refinery.harvest_training_data()
    if not data.empty:
        print(data[['ts', 'pulse_type', 'realized_fitness']].head())
