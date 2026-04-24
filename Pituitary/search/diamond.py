import sys
import numpy as np
import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, Any
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern

# Setup project root
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from Pituitary.refinery.service import SynapseRefinery
from Hippocampus.Archivist.diamond_scribe import DiamondScribe
from Hippocampus.Archivist.librarian import Librarian
from Hospital.Optimizer_loop.bounds import MINS, MAXS, normalize_weights

class DiamondGland:
    """
    Pituitary/Diamond: The Slow-Brain Bayesian Governor.
    V3.1 HORMONAL: Discharges from the private Diamond Silo.
    """
    def __init__(self):
        self.vault_path = project_root / "Hippocampus" / "hormonal_vault.json"
        self.refinery = SynapseRefinery()
        self.scribe = DiamondScribe()

    def perform_deep_search(self):
        print("\n=== [DIAMOND] STARTING DEEP BAYESIAN SEARCH (500 ITERATIONS) ===")
        
        # 1. Harvest and Isolate Training Data
        data = self.refinery.harvest_training_data(hours=24)
        if data.empty or len(data) < 50:
            print("[DIAMOND] Insufficient synapse data. Aborting.")
            return

        # V3.1: Dump to private refinery silo
        self.scribe.dump(list(data.itertuples(index=False, name=None)))

        # 2. Extract X (Params) and y (Realized Fitness) from SILO
        param_cols = [
            "active_gear", "monte_noise_scalar", "monte_w_worst", "monte_w_neutral", "monte_w_best",
            "council_w_atr", "council_w_adx", "council_w_vol", "council_w_vwap",
            "gatekeeper_min_monte", "gatekeeper_min_council",
            "callosum_w_monte", "callosum_w_right",
            "brain_stem_w_turtle", "brain_stem_w_council", "brain_stem_sigma", "brain_stem_bias",
            "brain_stem_entry_max_z", "brain_stem_mean_dev_cancel_sigma",
            "brain_stem_stale_price_cancel_bps", "brain_stem_mean_rev_target_sigma",
            "stop_loss_mult", "breakeven_mult"
        ]
        
        with Librarian.get_connection(self.scribe.db_path) as conn:
            col_str = "realized_fitness, " + ", ".join(param_cols)
            cursor = conn.execute(f"SELECT {col_str} FROM training_matrix")
            rows = np.array(cursor.fetchall())

        if len(rows) < 10:
            print("[DIAMOND] Silo discharge failed or too small. Aborting.")
            return

        y = rows[:, 0]
        X = rows[:, 1:]

        # 3. Deep Bayesian Search
        print(f"[DIAMOND] Training on {len(X)} tickets across {len(param_cols)} dimensions...")
        
        kernel = Matern(length_scale=np.ones(len(param_cols)), nu=1.5)
        gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=5)
        gp.fit(X, y)

        # 4. Extract Safety Rails
        X_test = np.random.uniform(MINS[:len(param_cols)], MAXS[:len(param_cols)], (5000, len(param_cols)))
        for i in range(len(X_test)): X_test[i] = normalize_weights(X_test[i])
        
        y_mean = gp.predict(X_test)
        safe_island = X_test[y_mean > 0.75]
        
        if len(safe_island) == 0:
            print("[DIAMOND WARNING] No high-fitness island found. Using broader bounds.")
            safe_island = X_test[y_mean > np.percentile(y_mean, 90)]

        rails = {}
        for i, col in enumerate(param_cols):
            rails[col] = {
                "min": float(np.min(safe_island[:, i])),
                "max": float(np.max(safe_island[:, i]))
            }

        # 5. Update the Vault
        self._update_vault(rails)
        print("=== [DIAMOND] DEEP SEARCH COMPLETE. RAILS MINTED. ===\n")

    def _update_vault(self, rails: Dict[str, Any]):
        with open(self.vault_path, "r") as f:
            vault = json.load(f)
            
        vault["diamond_rails"]["bounds"] = rails
        vault["diamond_rails"]["last_search_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        vault["meta"]["last_metabolism_ts"] = vault["diamond_rails"]["last_search_ts"]
        
        with open(self.vault_path, "w") as f:
            json.dump(vault, f, indent=2)

if __name__ == "__main__":
    DiamondGland().perform_deep_search()
