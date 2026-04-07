import sys
import os
import numpy as np
import time
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

# Setup project root
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from Cerebellum.Soul.brain_frame import BrainFrame
from Brain_Stem.connection import Trigger

@dataclass
class WalkSeed:
    regime_id: str
    mu: float
    sigma: float
    p_jump: float
    jump_mu: float
    jump_sigma: float
    tail_mult: float
    confidence: float
    mode: str
    mutations: Optional[List[float]] = None

def verify():
    print("--- [VERIFY] Mean-Dev Kill Window (ACTION -> MINT) ---")
    
    config = {
        "execution_mode": "DRY_RUN",
        "brain_stem_mean_dev_cancel_sigma": 1.5, # Cancel if z >= 1.5
        "brain_stem_w_turtle": 0.5,
        "brain_stem_w_council": 0.5,
        "brain_stem_sigma": 0.1,  # sigma_mult
        "brain_stem_bias": 0.0,   # No bias to keep math simple
    }
    
    # Mocking treasury
    class MockTreasury:
        def record_intent(self, data):
            print(f"    [MOCK] Treasury recorded intent: {data['reason']}")
        def cancel_intent(self, id, symbol, reason):
            print(f"    [MOCK] Treasury canceled intent: {reason}")
        def fire_intent(self, *args, **kwargs):
            print(f"    [MOCK] Treasury fired intent!")

    trigger = Trigger(api_key="T", api_secret="S", paper=True, config=config)
    trigger.treasury = MockTreasury()
    
    # 1. ACTION pulse: Price = 100
    frame = BrainFrame()
    frame.market.symbol = "TEST_SYM"
    frame.structure.price = 100.0
    frame.structure.tier1_signal = 1
    frame.risk.monte_score = 0.8
    frame.environment.confidence = 0.8
    frame.environment.atr = 1.0
    frame.command.sizing_mult = 1.0
    
    # Seed with mu = 10.0 -> mean_price = 100 + (10.0 * 0.1) = 101.0
    # sigma_mult = 0.1, atr = 1.0 -> sigma = 0.1
    seed = WalkSeed(
        regime_id="TEST_REG", mu=10.0, sigma=1.0, p_jump=0, 
        jump_mu=0, jump_sigma=0, tail_mult=1, confidence=0.8, mode="TEST"
    )
    
    print("\n[STEP 1] ACTION Pulse (Arming)...")
    trigger.load_and_hunt("ACTION", frame, walk_seed=seed)
    assert trigger.pending_entry is not None, "FAILED: ACTION did not arm"
    assert trigger.mean_dev_monitor_active is True, "FAILED: Monitor not active"
    
    # 2. MINT pulse: Price = 101.2 (Reverted above Mean)
    # Mean = 101.0, Sigma = 0.1 -> z = (101.2 - 101.0) / 0.1 = 2.0
    # 2.0 >= 1.5 -> Should CANCEL
    frame.structure.price = 101.2
    
    print("\n[STEP 2] MINT Pulse (Reverted z=2.0, expect CANCEL)...")
    trigger.load_and_hunt("MINT", frame, walk_seed=seed)
    assert trigger.pending_entry is None, "FAILED: MINT did not cancel"
    assert trigger.last_exit_reason is not None and "MEAN_DEV_CANCEL" in trigger.last_exit_reason, f"FAILED: Unexpected reason {trigger.last_exit_reason}"
    
    # 3. Repeat for SUCCESS case
    print("\n[STEP 3] ACTION Pulse (Arming again)...")
    frame.structure.price = 100.0
    trigger.load_and_hunt("ACTION", frame, walk_seed=seed)
    
    # Price = 101.1 (Stable)
    # z = (101.1 - 101.0) / 0.1 = 1.0
    # 1.0 < 1.5 -> Should FIRE
    frame.structure.price = 101.1
    
    print("\n[STEP 4] MINT Pulse (Stable z=1.0, expect FIRE)...")
    trigger.load_and_hunt("MINT", frame, walk_seed=seed)
    assert trigger.pending_entry is None, "FAILED: MINT should clear pending"
    assert trigger.position is not None, "FAILED: MINT did not fire"
    
    print("\n--- [VERIFY] COMPLETE: PASS ---")

if __name__ == "__main__":
    verify()
