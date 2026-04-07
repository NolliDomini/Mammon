import pandas as pd
import numpy as np
import os
from pathlib import Path

def generate_lurk_snap_data(filename=None):
    if filename is None:
        filename = str(Path(__file__).resolve().parents[2] / "lurk_snap_test.csv")
    n = 150
    dates = pd.date_range(start="2026-01-01", periods=n, freq="min")
    
    # Baseline
    high = [105.0] * n
    low = [95.0] * n
    close = [100.0] * n
    volume = [1000.0] * n
    
    # 1. Volatility setup (Seed ATR)
    for i in range(50):
        high[i] = 110.0
        low[i] = 90.0

    # 2. The 'Lurk' (Bars 100-110): Compression
    for i in range(100, 111):
        high[i] = 100.5
        low[i] = 99.5
        close[i] = 100.0

    # 3. The 'Snap' (Bar 111): Breakout
    high[111] = 140.0
    close[111] = 135.0
    volume[111] = 5000.0
    
    df = pd.DataFrame({
        'h': high, 'l': low, 'c': close, 'v': volume,
        'adx': [40.0] * n,
        'vw': [95.0] * n
    }, index=dates)
    
    df.to_csv(filename, index=False)
    print(f"Synthetic 'Lurk & Snap' data saved to {filename}")

if __name__ == "__main__":
    generate_lurk_snap_data()
