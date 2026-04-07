import time
from pathlib import Path
from typing import Any, Dict

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern

from Hippocampus.Archivist.librarian import librarian
from Hospital.Optimizer_loop.bounds import MAXS, MINS, normalize_weights
from Pituitary.refinery.service import SynapseRefinery

import pandas as pd  # M2 fix: was missing

from Hospital.Optimizer_loop.optimizer_v2.service import PARAM_KEYS
from Pituitary.gland.service import PituitaryGland


class DiamondGland:
    """
    Pituitary/Diamond: The Bayesian Governor (v2.1 Multi-Transport).
    Performs deep searches on historical synapse data to identify 
    high-fitness islands and update safety rails.
    
    V3.2 ANALYTICAL: Multi-Transport integration and PnL grounding.
    Piece 253: Silver integration. Piece 254: 46-D expansion.
    """
    def __init__(self):
        self.librarian = librarian
        self.refinery = SynapseRefinery()
        self.pituitary = PituitaryGland()

    def perform_deep_search(self, hours: int = 168):
        """
        Target #76: Bayesian Search on Multi-Transport Synapse.
        Identifies parameter clusters that yield high realized fitness.
        """
        print(f"\n=== [DIAMOND] STARTING DEEP BAYESIAN SEARCH ({hours}h History) ===")
        
        # 1. Harvest enriched training data via Refinery (Logic Drift Fixed)
        # Piece 220: Expanded to 46-D
        data = self.refinery.get_enriched_training_data(hours=hours)
        
        if data.empty or len(data) < 20: 
            print("[DIAMOND] Insufficient training data for Bayesian search. Aborting.")
            return

        # 2. Prepare X (Params) and y (Realized Fitness)
        # Piece 254: Use all 46 PARAM_KEYS
        available_cols = [c for c in PARAM_KEYS if c in data.columns]
        if len(available_cols) < 5:
            print("[DIAMOND] Data schema mismatch. Missing param columns.")
            return

        X = data[available_cols].to_numpy(dtype=np.float64)
        y = data["realized_fitness"].to_numpy(dtype=np.float64)

        # 3. Deep Bayesian Search (GPR)
        print(f"[DIAMOND] Training on {len(X)} tickets across {len(available_cols)} dimensions...")
        
        kernel = Matern(length_scale=np.ones(len(available_cols)), nu=1.5)
        gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=5, random_state=42)
        
        try:
            gp.fit(X, y)

            # 4. Extract Safety Rails (Scout 10000 candidates)
            # I2 fix: Use available_cols count, not full PARAM_KEYS, to match GPR training dims
            n_dims = len(available_cols)
            col_indices = [PARAM_KEYS.index(c) for c in available_cols if c in PARAM_KEYS]
            mins_subset = np.array([MINS[i] for i in col_indices])
            maxs_subset = np.array([MAXS[i] for i in col_indices])
            X_test = np.random.uniform(mins_subset, maxs_subset, (10000, n_dims))
            for i in range(len(X_test)): 
                X_test[i] = normalize_weights(X_test[i])
            
            y_mean, y_std = gp.predict(X_test, return_std=True)
            
            # Piece 255: Synthesize Titanium candidate (Best predicted param set)
            best_idx = np.argmax(y_mean)
            titanium_vec = X_test[best_idx]
            titanium_fitness = float(y_mean[best_idx])
            
            # Convert to dict using available_cols (not full PARAM_KEYS)
            titanium_params = dict(zip(available_cols, titanium_vec))
            
            # Piece 256: Validate Titanium through Integrity Gate
            if self.pituitary.validate_hormonal_integrity(titanium_params, repair=True):
                # Piece 257: Write Titanium to vault
                self._install_titanium(titanium_params, titanium_fitness, vault)
            
            # 5. Extract Rails
            safe_island = X_test[y_mean > 0.70] # Lowered threshold for 46-D
            if len(safe_island) == 0:
                print("[DIAMOND WARNING] No high-fitness island found. Using top 5th percentile.")
                safe_island = X_test[y_mean >= np.percentile(y_mean, 95)]
            
            # Absolute safety guard
            if len(safe_island) == 0:
                print("[DIAMOND ERROR] Critical: No candidates found for rails. Using full space.")
                safe_island = X_test

            rails = {}
            for i, col in enumerate(available_cols):
                rails[col] = {
                    "min": float(np.min(safe_island[:, i])),
                    "max": float(np.max(safe_island[:, i]))
                }

            # 6. Update the Vault
            self._update_vault(rails, vault)
            print("=== [DIAMOND] DEEP SEARCH COMPLETE. TITANIUM + RAILS MINTED. ===\n")
            
        except Exception as e:
            # PITU-E-P93-906: Bayesian search failure
            print(f"[PITU-E-P93-906] DIAMOND: Bayesian search failed: {e}")

    def _install_titanium(self, params: Dict[str, Any], fitness: float, vault: Dict[str, Any]):
        """Piece 257/258: Installs Titanium candidate for soak quarantine."""
        param_id = f"titanium_{int(time.time())}"
        titanium_entry = {
            "id": param_id,
            "params": params,
            "fitness_estimate": fitness,
            "soak_active": True,
            "soak_start": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "soak_scores": [],
            "soak_window": 12 # Piece 257
        }
        vault["titanium"] = titanium_entry
        self.librarian.set_hormonal_vault(vault)
        
        # Piece 258: Record in Param DB
        self.librarian.record_param_set(param_id, "TITANIUM", params, "GLOBAL", fitness, "DiamondML")
        print(f"[DIAMOND] Piece 257: Titanium Candidate installed: {param_id}")

    def _update_vault(self, rails: Dict[str, Any], vault: Dict[str, Any]):
        """Target #76: Atomic vault update via Librarian."""
        if "diamond_rails" not in vault:
            vault["diamond_rails"] = {}
            
        vault["diamond_rails"]["bounds"] = rails
        vault["diamond_rails"]["last_search_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        
        if "meta" not in vault: vault["meta"] = {}
        vault["meta"]["last_metabolism_ts"] = vault["diamond_rails"]["last_search_ts"]
        
        # Multi-Transport Fix: Standardized write
        self.librarian.set_hormonal_vault(vault)

if __name__ == "__main__":
    DiamondGland().perform_deep_search()
