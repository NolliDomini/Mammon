import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

from Hippocampus.Archivist.librarian import librarian

from Hospital.Optimizer_loop.optimizer_v2.service import PARAM_KEYS

class SynapseRefinery:
    """
    Pituitary/Refinery: The Synapse Harvester (v2.1 Multi-Transport).
    V3.2 ANALYTICAL: Harvests from DuckDB and grounds fitness in TimescaleDB PnL.
    Piece 220: Expanded to 46-D parameters.
    """
    def __init__(self, **kwargs):
        self.librarian = librarian

    def harvest_training_data(self, hours: int = 24) -> pd.DataFrame:
        """
        Target #75: PnL-Grounded Fitness.
        Joins synapse snapshots with actual realization fills.
        """
        print(f"[REFINERY] Harvesting synapse tickets from last {hours}h...")
        
        # 1. Pull analytical synapse tickets from DuckDB (Piece 101)
        # Piece 220: Ensure all 46 param columns are selected if they exist
        synapse_query = """
            SELECT * FROM synapse_mint 
            WHERE ts >= to_timestamp(?)
            AND pulse_type = 'MINT'
        """
        import time
        cutoff = int(time.time() - (hours * 3600))

        try:
            # Multi-Transport Fix: Use standardized librarian gateway
            rows = self.librarian.read(synapse_query, (cutoff,), transport="duckdb")
            if not rows:
                print("[REFINERY] Lake is empty. No training data available.")
                return pd.DataFrame()
            
            df = pd.DataFrame(rows)
            
            # Piece 221: Handle missing param columns gracefully (default to median of MINS/MAXS or 0.0)
            from Hospital.Optimizer_loop.bounds.service import MINS, MAXS
            for i, key in enumerate(PARAM_KEYS):
                if key not in df.columns:
                    # Fill missing columns with safe defaults
                    default_val = (MINS[i] + MAXS[i]) / 2.0
                    df[key] = default_val
            
            # 2. Pull actual realized PnL from TimescaleDB (Target #75)
            # Fetch most recent fills to correlate with synapse states
            pnl_query = "SELECT symbol, realized_pnl, updated_at FROM money_positions"
            pnl_rows = self.librarian.read(pnl_query, transport="timescale")
            pnl_map = {row[0]: float(row[1]) for row in pnl_rows} if pnl_rows else {}

            # 3. Calculate 'Surgical Fitness' (Multi-Factor Grounding)
            def _calc_realized_fitness(row):
                symbol = row.get("symbol")
                pnl = pnl_map.get(symbol, 0.0)
                
                # Base fitness from synthesis score
                base = float(row.get("tier_score", 0.5))
                
                # 1. PnL Factor (Profitability)
                # Normalize PnL: +100bps = +0.3 boost, -100bps = -0.3 penalty
                pnl_factor = np.tanh(pnl / 100.0) * 0.3
                
                # 2. Volatility Factor (Stability)
                # Penalize candidates that trade into extreme ATR
                atr = float(row.get("atr", 0.0))
                atr_avg = float(row.get("atr_avg", 1.0))
                vol_ratio = atr / (atr_avg + 1e-9)
                vol_factor = -0.1 if vol_ratio > 2.0 else 0.05 # Bonus for stability
                
                # 3. Decision Integrity (Conviction)
                # Bonus for high-confidence decisions that were profitable
                confidence = float(row.get("final_confidence", 0.5))
                integrity_bonus = 0.1 if (confidence > 0.7 and pnl > 0) else 0.0
                
                return float(np.clip(base + pnl_factor + vol_factor + integrity_bonus, 0.0, 1.0))

            df['realized_fitness'] = df.apply(_calc_realized_fitness, axis=1)
            
            print(f"[REFINERY] Harvested {len(df)} tickets. Matrix grounded in PnL (46-D).")
            return df
            
        except Exception as e:
            # Piece 92: Standardized MNER for refinery failure
            print(f"[PITU-E-P92-901] REFINERY_HARVEST_FAILED: {e}")
            return pd.DataFrame()

    def get_enriched_training_data(self, hours: int = 168) -> pd.DataFrame:
        """
        Target #76: Enriched Grounding for Bayesian Search.
        Relocated from DiamondGland to centralize data authority.
        """
        # 1. Harvest base tickets grounded in PnL
        data = self.harvest_training_data(hours=hours)
        
        # 2. Incorporate Silver candidates from vault (Historical 'Wins')
        vault = self.librarian.get_hormonal_vault()
        silver_list = vault.get("silver", [])
        if silver_list:
            silver_rows = []
            for s in silver_list:
                row = s.get("params", {}).copy()
                row["realized_fitness"] = s.get("fitness", 0.5)
                silver_rows.append(row)
            silver_df = pd.DataFrame(silver_rows)
            
            # Ensure all columns match for concat
            from Hospital.Optimizer_loop.bounds.service import MINS, MAXS
            for i, key in enumerate(PARAM_KEYS):
                if key not in silver_df.columns:
                    silver_df[key] = (MINS[i] + MAXS[i]) / 2.0
            
            data = pd.concat([data, silver_df], ignore_index=True)
            print(f"[REFINERY] Enriched data with {len(silver_list)} Silver candidates.")
            
        return data
