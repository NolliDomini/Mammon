"""
Mammon Data Doctor: Temporal Stitching Engine (Piece 18+)

Instruction:
1. Delete large gaps (2 minutes or bigger).
2. Reduce them "down to 1 bar" and "fix the gap" (fill with synthetic candle).

Strategy:
- For each symbol, we rebuild the timeline.
- Every "real" bar is preserved.
- Any gap between real bars (whether 1 min or 1000 mins) is replaced by exactly ONE synthetic candle.
- The resulting timeline is perfectly contiguous (1-minute intervals).
- This "deletes" the large gaps and "fixes" the remaining 1-bar holes.
"""

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta

DB_PATH = Path("Hospital/Memory_care/duck.db")

def fix_data():
    conn = duckdb.connect(str(DB_PATH))
    print("[DATA_DOCTOR] Starting temporal stitching and bridging...")
    
    # Get symbols and their first timestamp to maintain some reality
    symbol_info = conn.execute("SELECT symbol, min(ts) as start_ts FROM market_tape GROUP BY symbol").fetchall()
    
    for sym, start_ts in symbol_info:
        print(f"  [STITCH] {sym}...")
        
        # 1. Load real data
        df = conn.execute(f"SELECT * FROM market_tape WHERE symbol = '{sym}' ORDER BY ts ASC").df()
        if df.empty: continue
        
        real_bars = df.to_dict('records')
        repaired_rows = []
        
        current_ts = pd.to_datetime(start_ts)
        last_real_ts = None
        
        for i, bar in enumerate(real_bars):
            bar_ts = pd.to_datetime(bar['ts'])
            
            if last_real_ts is not None:
                diff_mins = (bar_ts - last_real_ts).total_seconds() / 60.0
                
                if diff_mins > 1.0:
                    # WE HAVE A GAP (Small or Large)
                    # "dow to 1 bar and fix the gap"
                    # Create one synthetic bridging candle using previous real bar values
                    bridge_bar = real_bars[i-1].copy()
                    bridge_bar['ts'] = current_ts
                    bridge_bar['volume'] = 0.0 # Synthetic bridge has no volume
                    repaired_rows.append(bridge_bar)
                    current_ts += timedelta(minutes=1)
            
            # Place the real bar into the new continuous timeline
            bar['ts'] = current_ts
            repaired_rows.append(bar)
            
            last_real_ts = bar_ts
            current_ts += timedelta(minutes=1)
            
        if repaired_rows:
            final_df = pd.DataFrame(repaired_rows)
            # Cleanup for DuckDB insertion
            final_df = final_df[["ts", "symbol", "open", "high", "low", "close", "volume"]]
            
            # 2. Atomic Update
            conn.execute(f"DELETE FROM market_tape WHERE symbol = '{sym}'")
            conn.register("stitched_batch", final_df)
            conn.execute("INSERT INTO market_tape SELECT ts, symbol, open, high, low, close, volume FROM stitched_batch")
            conn.unregister("stitched_batch")
            print(f"    [OK] {sym} | Stitched rows: {len(final_df):,}")

    print("[DATA_DOCTOR] Temporal stitching complete. DuckPond is now gap-free.")
    conn.execute("CHECKPOINT")
    conn.close()

if __name__ == "__main__":
    fix_data()
