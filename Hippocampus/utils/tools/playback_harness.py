import pandas as pd
import sys
import os
import time

# Project root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from Corpus.Optical_Tract.spray import OpticalTract
from Right_Hemisphere.Snapping_Turtle.engine import SnappingTurtle
from Left_Hemisphere.Monte_Carlo.turtle_monte import TurtleMonte
from Corpus.callosum import Callosum
from Medulla.gatekeeper import Gatekeeper

class PlaybackHarness:
    """
    Hippocampus: Playback Harness.
    Feeds historical data bar-by-bar into the brain to simulate live market conditions.
    """
    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.ot = OpticalTract()
        self.snapper = SnappingTurtle()
        self.monte = TurtleMonte(n_steps=10, paths_per_lane=1000)
        self.corpus = Callosum()
        self.cerebellum = Gatekeeper()
        
        # Wire the nervous system
        self.ot.subscribe(self.snapper)
        
        # Data preparation
        self.df = pd.read_csv(csv_path)
        column_map = {'c': 'close', 'h': 'high', 'l': 'low', 'v': 'volume', 't': 'timestamp', 'vw': 'vwap'}
        self.df = self.df.rename(columns=column_map)
        
        if 'adx' not in self.df.columns:
            self.df['adx'] = 30.0

    def run(self, start_bar=60, end_bar=None):
        print(f"--- [HIPPOCAMPUS] Starting Playback: {self.csv_path} ---")
        
        end_bar = end_bar or len(self.df)
        
        for i in range(start_bar, end_bar):
            current_slice = self.df.iloc[:i+1]
            knowledge = self.snapper.on_data_received(current_slice)
            
            if knowledge is None:
                continue
                
            last_bar = knowledge.iloc[-1]
            
            if last_bar['tier1_signal']:
                price = last_bar['close']
                print(f"\n[!] T1 SIGNAL DETECTED at bar {i} | Price: {price}")
                
                print("    - Left Hemisphere: Running Monte Carlo Simulation...")
                survival_rates = self.monte.simulate(
                    current_price=last_bar['close'],
                    atr=last_bar['atr'],
                    gear_lookback=last_bar['gear_val'],
                    council_score=0.5,
                    direction=1
                )
                
                print("    - Corpus: Synthesizing Tier Score...")
                tier_packet = self.corpus.score_tier(
                    tier_id=1,
                    signal={'signal_type': 'LONG', 'strength': 1.0},
                    survival_rates=survival_rates
                )
                
                print("    - Cerebellum: Gatekeeper Consulting Council...")
                decision = self.cerebellum.decide(tier_packet, current_slice)
                
                if decision.ready_to_fire:
                    print(f"    - [FIRE] TRIGGER EXCITED: {decision.reason}")
                else:
                    print(f"    - [BLOCK] TRIGGER INHIBITED: {decision.reason}")
            
        print("\n--- [HIPPOCAMPUS] Playback Complete ---")

if __name__ == "__main__":

    hippo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    harness = PlaybackHarness(os.path.join(hippo_dir, "lurk_snap_test.csv"))

    harness.run(start_bar=60, end_bar=150)
