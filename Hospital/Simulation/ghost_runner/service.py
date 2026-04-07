import duckdb
import pandas as pd
import numpy as np
from numba import jit
import time
import os
from pathlib import Path
from typing import Dict

# JIT-Compiled "Dream Loop"
@jit(nopython=True)
def run_dream_loop(
    closes: np.ndarray,
    atrs: np.ndarray,
    means: np.ndarray,
    upper_bands: np.ndarray,
    lower_bands: np.ndarray,
    risk_threshold: float = 0.5
):
    """
    The High-Speed Engine. 
    Processes millions of bars in milliseconds by stripping away Python overhead.
    """
    n = len(closes)
    trades_entry = []
    trades_exit = []
    trades_pnl = []
    
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    
    # Pre-allocate for speed (estimation)
    # Using lists in Numba is okay for append, but explicit arrays are faster if we knew size.
    # We'll use lists and convert later or just print for now.
    
    for i in range(100, n):
        price = closes[i]
        
        # 1. READ SENSORS (Pre-calculated in Cortex)
        current_atr = atrs[i]
        lower = lower_bands[i]
        upper = upper_bands[i]
        mean = means[i]
        
        # 2. DECISION LOGIC
        if not in_position:
            # ENTRY: Price < Lower Band (Undervalued)
            # Note: We simulate "Risk Score" passing. In a full version, we'd pass a 'risk_scores' array too.
            if price < lower:
                 in_position = True
                 entry_price = price
                 entry_idx = i
        
        else:
            # EXIT: Price > Upper Band (Take Profit) OR Stop Loss
            stop_loss = entry_price - (current_atr * 2.0)
            
            should_sell = False
            exit_reason = 0 # 1=Take, 2=Stop
            
            if price > upper:
                should_sell = True
                exit_reason = 1
            elif price < stop_loss:
                should_sell = True
                exit_reason = 2
                
            if should_sell:
                pnl = price - entry_price
                trades_entry.append(entry_idx)
                trades_exit.append(i)
                trades_pnl.append(pnl)
                in_position = False
                
    return trades_entry, trades_exit, trades_pnl

class GhostRunner:
    """
    Hospital/GhostRunner: The Simulation Daemon.
    """
    def __init__(self, db_path=None):
        if db_path is None:
            env_path = os.environ.get("MAMMON_DUCK_DB")
            if env_path and str(env_path).strip():
                db_path = env_path
            else:
                db_path = str(Path(__file__).resolve().parents[2] / "Hospital" / "Memory_care" / "duck.db")
        self.conn = duckdb.connect(db_path, read_only=True)
        
    def run_backtest(self, symbol: str):
        print(f"[GHOST] Warming up engine for {symbol}...")
        
        # 1. LOAD (Zero-Copy Arrow -> Numpy)
        start_load = time.time()
        # Fetch columns as numpy arrays directly
        # Note: We need to handle potential NULLs from window functions (first 100 rows)
        df = self.conn.execute("""
            SELECT close, atr_14, mean_100, upper_band, lower_band 
            FROM cortex_precalc 
            WHERE symbol = ? AND atr_14 IS NOT NULL
            ORDER BY ts ASC
        """, [symbol]).df()
        
        closes = df['close'].to_numpy()
        atrs = df['atr_14'].to_numpy()
        means = df['mean_100'].to_numpy()
        uppers = df['upper_band'].to_numpy()
        lowers = df['lower_band'].to_numpy()
        
        print(f"   Loaded {len(closes)} bars in {time.time()-start_load:.4f}s")
        
        # 2. EXECUTE (JIT)
        start_run = time.time()
        entries, exits, pnls = run_dream_loop(closes, atrs, means, uppers, lowers)
        elapsed = time.time() - start_run
        
        # 3. REPORT
        n_trades = len(pnls)
        total_pnl = sum(pnls)
        print(f"[GHOST] SIMULATION COMPLETE")
        print(f"   Bars Processed: {len(closes)}")
        print(f"   Engine Time:    {elapsed:.6f}s ({(len(closes)/elapsed)/1_000_000:.2f} M bars/sec)")
        print(f"   Trades:         {n_trades}")
        print(f"   Total PnL:      {total_pnl:.4f}")

if __name__ == "__main__":
    runner = GhostRunner()
    # runner.run_backtest("AMC")
