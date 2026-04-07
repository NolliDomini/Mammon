import pandas as pd
import sys
import os
import numpy as np

# Project root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from Right_Hemisphere.Snapping_Turtle.engine import SnappingTurtle
from Left_Hemisphere.Monte_Carlo.turtle_monte import TurtleMonte
from Corpus.callosum import Callosum
from Medulla.gatekeeper import Gatekeeper
from Hippocampus.polygraph_mint import PolygraphMint

class MintPress:
    """
    MintPress: The 'Factory'. Optimized for Batch Processing.
    """
    def __init__(self, csv_path, output_dir):
        self.df = pd.read_csv(csv_path)
        self.output_dir = output_dir
        
        self.snapper = SnappingTurtle()
        self.monte = TurtleMonte()
        self.corpus = Callosum()
        self.cerebellum = Gatekeeper()

    def run(self):
        grouped = self.df.groupby('symbol')
        
        for symbol, group in grouped:
            print(f"Minting Asset: {symbol} (Batch Mode)...")
            safe_symbol = symbol.replace('/','_')
            output_file = os.path.join(self.output_dir, f"{safe_symbol}_mint.jsonl")
            polygraph = PolygraphMint(output_file)
            
            # BATCH OPTIMIZATION:
            # Instead of feeding bar-by-bar, feed the whole history once.
            # The Engine calculates indicators for the entire timeline vectorized.
            processed_df = self.snapper.on_data_received(group)
            
            if processed_df is None:
                print(f"Skipping {symbol} (Insufficient Data)")
                continue
                
            # Iterate the PROCESSED dataframe which already has signals
            records = processed_df.to_dict('records')
            
            for i, row in enumerate(records):
                # Skip warm-up period
                if i < 60: continue
                
                # 1. State from Right Hemi (Already calculated)
                # We reconstruct the 'state' dict from the row columns
                # matching the structure expected by get_state() logic
                right_state = {
                    "tier_id": 1,
                    "indicators": {
                        "atr": float(row.get('atr', 0)),
                        "atr_avg": float(row.get('atr_avg', 0)),
                        "vol_avg": float(row.get('vol_avg', 0))
                    },
                    "gates": {
                        "volatility": bool(row.get('v_gate', False)),
                        "volume": bool(row.get('vol_gate', False)),
                        "snap": bool(row.get('snap_ready', False))
                    },
                    "logic": {
                        "gear": int(row.get('gear_val', 20)),
                        "lurk_count": int(row.get('lurk_count', 0)),
                        "breakout": bool(row.get('breakout_long', False))
                    },
                    "signal": bool(row.get('tier1_signal', False))
                }
                
                left_state = {}
                corpus_state = {}
                cerebellum_state = {}
                
                # 2. Left Brain & Logic (Triggered only on Signal)
                if right_state['signal']:
                    # Monte Carlo simulation still needs to run per-signal (Random walks)
                    survival_rates = self.monte.simulate(
                        current_price=row['close'],
                        atr=row['atr'],
                        gear_lookback=right_state['logic']['gear'],
                        council_score=0.5, # Placeholder
                        direction=1
                    )
                    left_state = self.monte.get_state()
                    
                    tier_packet = self.corpus.score_tier(1, {'signal_type': 'LONG'}, survival_rates)
                    corpus_state = self.corpus.get_state()
                    
                    # Create context slice for Council (needs rolling window)
                    # This is the only "slow" part left, but only runs on signals
                    current_slice = processed_df.iloc[:i+1]
                    self.cerebellum.decide(tier_packet, current_slice)
                    cerebellum_state = self.cerebellum.get_state()
                
                # 3. MINT
                snapshot = {
                    "bar_index": i,
                    "symbol": symbol,
                    "price": row['close'],
                    "right_hemisphere": right_state,
                    "left_hemisphere": left_state,
                    "corpus": corpus_state,
                    "cerebellum": cerebellum_state
                }
                polygraph.mint_bar(snapshot)
                
        print("Minting Complete.")

if __name__ == "__main__":
    hippo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(os.path.dirname(hippo_dir), "stitched_samples.csv")
    data_dir = os.path.join(os.path.dirname(hippo_dir), "data")
    
    press = MintPress(csv_path, data_dir)
    press.run()
