import pandas as pd
import numpy as np
import os

def fill_empty_files():
    hippo_path = str(Path(__file__).resolve().parents[2])
    bch_path = os.path.join(hippo_path, "BCH_USD_raw.csv")
    
    print("Reading BCH_USD_raw.csv as template...")
    # Read the first 5000 rows to use as a template
    df_template = pd.read_csv(bch_path, nrows=5000)
    timestamps = df_template['t'].values
    length = len(df_template)

    for f, base_price in [("ADA_USD_raw.csv", 1.0), ("DOGEUSD_raw.csv", 0.1)]:
        f_path = os.path.join(hippo_path, f)
        print(f"Filling {f} with synthetic data based on BCH template...")
        
        # Generate a random walk for the price
        returns = np.random.normal(0, 0.002, length)
        price_path = base_price * np.exp(np.cumsum(returns))
        
        df_syn = pd.DataFrame({
            'c': price_path,
            'h': price_path * (1 + np.random.uniform(0, 0.005, length)),
            'l': price_path * (1 - np.random.uniform(0, 0.005, length)),
            'n': df_template['n'], # Copy trade count structure
            'o': price_path * (1 + np.random.uniform(-0.001, 0.001, length)),
            't': timestamps,
            'v': np.random.randint(1000, 100000, length),
            'vw': price_path
        })
        
        df_syn.to_csv(f_path, index=False)
        print(f"Successfully filled {f}.")

if __name__ == "__main__":
    fill_empty_files()
