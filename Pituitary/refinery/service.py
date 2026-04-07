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

    def harvest_training_data(self, hours: int = 24) -> pd.DataFrame:
        """
        Extracts recent synapse tickets and calculates a 'Realized Fitness' score.
        """
        print(f"[REFINERY] Harvesting synapse tickets from last {hours}h...")
        
        query = f"""
            SELECT * FROM synapse_mint 
            WHERE created_at >= datetime('now', '-{hours} hours')
            AND pulse_type = 'MINT'
        """
        
        try:
            # V3.1: Use Librarian for unified access
            rows = self.librarian.read_only(query)
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
