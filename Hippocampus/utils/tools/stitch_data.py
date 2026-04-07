import pandas as pd
import os

def stitch_samples():
    hippo_path = str(Path(__file__).resolve().parents[2])
    # We use a limit on BCH to keep the stitched file manageable
    files = [
        ("ADA_USD_raw.csv", "ADA/USD", None),
        ("BCH_USD_raw.csv", "BCH/USD", 5000),
        ("DOGEUSD_raw.csv", "DOGE/USD", None)
    ]
    
    dfs = []
    for f, symbol, nrows in files:
        f_path = os.path.join(hippo_path, f)
        print(f"Reading {f}...")
        df = pd.read_csv(f_path, nrows=nrows)
        df['symbol'] = symbol
        dfs.append(df)
    
    print("Stitching datasets...")
    combined_df = pd.concat(dfs, ignore_index=True)
    
    # Standardize columns for Brain Frame
    column_map = {'c': 'close', 'h': 'high', 'l': 'low', 'o': 'open', 'v': 'volume', 't': 'timestamp', 'vw': 'vwap'}
    combined_df = combined_df.rename(columns=column_map)
    
    # Add ADX placeholder
    combined_df['adx'] = 30.0
    
    output_path = os.path.join(hippo_path, "stitched_samples.csv")
    print(f"Saving to {output_path}...")
    combined_df.to_csv(output_path, index=False)
    print("Done.")

if __name__ == "__main__":
    stitch_samples()
