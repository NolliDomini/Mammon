import json
import sqlite3
import time
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern

from Hippocampus.Archivist.librarian import librarian
from Hospital.Optimizer_loop.bounds import MINS, MAXS, normalize_weights

# Canonical 23-D parameter key order (matches bounds.py)
PARAM_KEYS = [
    "active_gear",
    "monte_noise_scalar",
    "monte_w_worst", "monte_w_neutral", "monte_w_best",
    "council_w_atr", "council_w_adx", "council_w_vol", "council_w_vwap",
    "gatekeeper_min_monte", "gatekeeper_min_council",
    "callosum_w_monte", "callosum_w_right", "callosum_w_adx", "callosum_w_weak",
    "brain_stem_w_turtle", "brain_stem_w_council", "brain_stem_survival",
    "brain_stem_noise", "brain_stem_sigma", "brain_stem_bias",
    "stop_loss_mult", "breakeven_mult"
]

@dataclass
class Hormone:
    name: str # platinum, gold, silver, bronze
    params: Dict[str, Any]
    fitness: float
    source: str # e.g. "forge-123", "manual", "synapse-456"

class PituitaryGland:
    """
    Root Pituitary: The Master Hormonal Controller.
    Manages the hierarchy of trading genetics:
    1. Platinum: The bleeding-edge optimized set (Automated).
    2. Gold: The stable reference set (Manual).
    3. Silver: Historical high-performers (Synapse Memory).
    4. Bronze: The Fall-off list (Retired).

    V3.2 GROWTH HORMONE: Every 4th MINT, runs GP regression on
    Platinum/Gold/Silver to mathematically derive a new Gold standard.
    """
    def __init__(self):
        self.root = Path(__file__).resolve().parents[1]
        self.params_root = self.root / "params"
        self.platinum_path = self.params_root / "platinum_params.json"
        self.gold_path = self.params_root / "gold_params.json"
        self.bronze_path = self.params_root / "bronze_list.json"
        self.vault_path = self.root.parent / "Hippocampus" / "hormonal_vault.json"
        self.librarian = librarian

        # Database connection for Silver mining
        self.synapse_db = self.root.parent / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db"

        # V3.2 GROWTH HORMONE: MINT cadence tracking
        self.mint_count = 0
        self.gp_cadence = 4  # Fire GP every Nth MINT

    # ──────────────────────────────────────────────
    # V3.2 GROWTH HORMONE — GP Mutation Cycle
    # ──────────────────────────────────────────────

    def secrete_growth_hormone(self, pulse_type: str):
        """
        Called every pulse by the Soul Orchestrator.
        On every 4th MINT, runs GP regression on the three tiers
        (Platinum, Gold, Silver) to derive a new Gold standard.
        """
        if pulse_type != "MINT":
            return

        self.mint_count += 1

        if self.mint_count % self.gp_cadence != 0:
            print(f"[PITUITARY] MINT #{self.mint_count} — Accumulating ({self.mint_count % self.gp_cadence}/{self.gp_cadence})")
            return

        print(f"[PITUITARY] MINT #{self.mint_count} — GROWTH HORMONE CYCLE TRIGGERED")
        try:
            self._run_gp_mutation()
        except Exception as e:
            print(f"[PITUITARY_ERROR] GP mutation failed: {e}")
            import traceback
            traceback.print_exc()

    @staticmethod
    def _extract_fitness(entry: Dict[str, Any], default: float = 0.5) -> float:
        if not isinstance(entry, dict):
            return float(default)
        for key in ("fitness_snapshot", "fitness_estimate", "fitness"):
            try:
                if key in entry:
                    return float(entry.get(key))
            except Exception:
                continue
        return float(default)

    def _run_gp_mutation(self):
        """
        Core GP mutation logic.
        Loads Platinum/Gold/Silver, fits a Gaussian Process, and derives new Gold.
        """
        # 1. LOAD NORMALIZED VAULT TIERS FROM HOT TABLE
        vault = self.librarian.get_hormonal_vault()
        if not isinstance(vault, dict):
            vault = {}

        tiers = []  # List[(name, vector, fitness)]

        def add_tier(name: str, entry: Any, default_fitness: float = 0.5):
            if not isinstance(entry, dict):
                return
            params = entry.get("params")
            if not isinstance(params, dict):
                return
            vec = self._params_to_vector(params)
            if vec is None:
                return
            fitness = self._extract_fitness(entry, default_fitness)
            tiers.append((name, vec, fitness))
            print(f"   [GP] {name} loaded: fitness={fitness:.4f}")

        add_tier("Gold", vault.get("gold"), default_fitness=0.50)

        silver_entries = vault.get("silver", [])
        if isinstance(silver_entries, dict):
            silver_entries = [silver_entries]
        if not isinstance(silver_entries, list):
            silver_entries = []
        for i, silver_entry in enumerate(silver_entries):
            add_tier(f"Silver[{i}]", silver_entry, default_fitness=0.45)

        add_tier("Platinum", vault.get("platinum"), default_fitness=0.55)
        add_tier("Titanium", vault.get("titanium"), default_fitness=0.50)

        bronze_entries = vault.get("bronze_history", [])
        if isinstance(bronze_entries, dict):
            bronze_entries = [bronze_entries]
        if isinstance(bronze_entries, list):
            for i, bronze_entry in enumerate(bronze_entries[:5]):
                add_tier(f"Bronze[{i}]", bronze_entry, default_fitness=0.35)

        # Legacy fallback: include file-based platinum if vault lacks enough points.
        if len(tiers) < 2:
            plat_raw = self._load_json(self.platinum_path)
            add_tier("PlatinumFile", plat_raw, default_fitness=0.55)

        # 2. GUARD: Need at least 2 data points
        if len(tiers) < 2:
            print(f"[PITUITARY] Only {len(tiers)} tier(s) available. GP needs >= 2. Skipping.")
            return

        # 3. BUILD TRAINING DATA
        X_train = np.array([t[1] for t in tiers])
        y_train = np.array([t[2] for t in tiers])
        tier_names = [t[0] for t in tiers]
        print(f"   [GP] Training on {len(tiers)} tiers: {tier_names}")

        # 4. FIT GAUSSIAN PROCESS
        kernel = Matern(length_scale=np.ones(len(PARAM_KEYS)), nu=1.5)
        gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=3, alpha=1e-6)
        gp.fit(X_train, y_train)

        # 5. GENERATE CANDIDATES (500 bounded points)
        rng = np.random.default_rng()
        candidates = rng.uniform(MINS, MAXS, (500, len(PARAM_KEYS)))

        # Normalize weight groups for every candidate
        for i in range(len(candidates)):
            candidates[i] = normalize_weights(candidates[i])

        # 6. PREDICT FITNESS & SELECT BEST
        y_pred = gp.predict(candidates)
        best_idx = int(np.argmax(y_pred))
        best_vector = candidates[best_idx]
        best_fitness = float(y_pred[best_idx])

        print(f"   [GP] Best candidate: predicted_fitness={best_fitness:.4f} (idx={best_idx})")

        # 7. CLAMP TO DIAMOND SAFETY RAILS (if present)
        rails = vault.get("diamond_rails", {}).get("bounds", {})
        for param, bounds in rails.items():
            if param in PARAM_KEYS:
                idx = PARAM_KEYS.index(param)
                low = float(bounds.get("min", MINS[idx]))
                high = float(bounds.get("max", MAXS[idx]))
                best_vector[idx] = np.clip(best_vector[idx], low, high)

        # Final normalize after clamping
        best_vector = normalize_weights(best_vector)

        # 8. CONVERT BACK TO PARAM DICT
        new_params = self._vector_to_params(best_vector)

        # 8b. Piece 14 Safety Gate
        if not self.validate_hormonal_integrity(new_params):
            print("[PITUITARY_ERROR] Mutated params failed integrity check. Coronation aborted.")
            return

        # 9. CORONATION: Install new Gold, demote old
        old_gold = vault.get("gold", {})
        old_fitness = self._extract_fitness(old_gold, 0.0)

        print(f"   [GP] Old Gold fitness={old_fitness:.4f} -> New GP-derived fitness={best_fitness:.4f}")

        # Demote old Gold to bronze_history
        if isinstance(old_gold, dict) and "params" in old_gold:
            demoted = dict(old_gold)
            demoted["demoted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            demoted["demotion_reason"] = "gp_mutation"
            bronze = vault.get("bronze_history", [])
            if not isinstance(bronze, list):
                bronze = []
            bronze.insert(0, demoted)
            vault["bronze_history"] = bronze[:50]  # Rolling archive

        # Install new Gold
        vault["gold"] = {
            "id": f"gp_mutation_{int(time.time())}",
            "params": new_params,
            "fitness_snapshot": best_fitness,
            "coronated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "origin": "PituitaryGP",
            "training_tiers": tier_names
        }

        # Clear Silver (consumed by GP) and keep aliases aligned.
        vault["silver"] = []
        vault["bronze"] = vault.get("bronze_history", [])

        # Update meta
        meta = vault.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        meta["last_metabolism_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta["last_gp_mutation_ts"] = meta["last_metabolism_ts"]
        meta["last_gp_training_tier_count"] = len(tier_names)
        vault["meta"] = meta

        # 10. PERSIST
        self.librarian.set_hormonal_vault(vault)
        try:
            self.librarian.record_param_set(
                vault["gold"]["id"],
                "GOLD",
                new_params,
                "GLOBAL",
                best_fitness,
                "PituitaryGP",
            )
        except Exception as e:
            print(f"   [GP_WARN] Param DB write skipped: {e}")

        print(f"[PITUITARY] GROWTH HORMONE SECRETED — New Gold: {vault['gold']['id']}")
        print(f"   Derived from: {tier_names} | Predicted fitness: {best_fitness:.4f}")

    def _params_to_vector(self, params: Dict[str, Any]) -> Optional[np.ndarray]:
        """Converts a flat param dict to a 23-D numpy vector using PARAM_KEYS order."""
        try:
            vec = np.array([float(params[k]) for k in PARAM_KEYS])
            return vec
        except (KeyError, TypeError, ValueError) as e:
            print(f"   [GP_WARN] Failed to vectorize params: {e}")
            return None

    def _vector_to_params(self, vec: np.ndarray) -> Dict[str, Any]:
        """Converts a 23-D numpy vector back to a flat param dict."""
        params = {}
        for i, key in enumerate(PARAM_KEYS):
            val = float(vec[i])
            # active_gear must be an integer
            if key == "active_gear":
                val = int(round(val))
            params[key] = val
        return params

    def validate_hormonal_integrity(self, params: Dict[str, Any]) -> bool:
        """
        Piece 14 Safety Gate:
        Ensures all 23-D keys are present and values are within absolute MIN/MAX bounds.
        """
        for i, key in enumerate(PARAM_KEYS):
            if key not in params:
                return False
            val = float(params[key])
            if val < MINS[i] or val > MAXS[i]:
                return False
        return True

    # ──────────────────────────────────────────────
    # Existing Pituitary Methods
    # ──────────────────────────────────────────────

    def secrete_platinum(self, regime_id: str, new_params: Dict[str, Any], fitness: float) -> bool:
        """
        Attempts to update the Platinum standard. 
        If successful, the old Platinum is retired to Bronze.
        """
        vault = self.librarian.get_hormonal_vault()
        current_plat = vault.get("platinum", {})
        current_fitness = self._extract_fitness(current_plat, 0.0)
        
        if fitness > current_fitness:
            print(f"[PITUITARY] New Platinum Standard! ({fitness:.4f} > {current_fitness:.4f})")
            
            # Retire old Platinum to Bronze if it existed
            if current_plat:
                self._retire_to_bronze(current_plat, reason="dethroned_by_platinum")
            
            # Mint new Platinum
            param_id = f"forge_{regime_id}_{int(time.time())}"
            new_entry = {
                "id": param_id,
                "params": new_params,
                "fitness_estimate": fitness,
                "minted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "origin": "VolumeFurnace"
            }
            vault = self.librarian.get_hormonal_vault()
            vault["platinum"] = new_entry
            self.librarian.set_hormonal_vault(vault)
            try:
                self.librarian.record_param_set(param_id, "PLATINUM", new_params, regime_id, fitness, "VolumeFurnace")
            except Exception as e:
                print(f"[PITUITARY_WARN] Platinum Param DB write skipped: {e}")
            return True
            
        return False

    def recall_best_hormones(self) -> Dict[str, Any]:
        """
        Returns the single best parameter set available.
        Order of Precedence: Platinum > Gold > Silver (Best)
        """
        vault = self.librarian.get_hormonal_vault()

        # 1. Platinum
        plat = vault.get("platinum", {})
        if isinstance(plat, dict) and isinstance(plat.get("params"), dict):
            return plat["params"]

        # 2. Gold
        gold = vault.get("gold", {})
        if isinstance(gold, dict) and isinstance(gold.get("params"), dict):
            return gold["params"]

        # 3. Silver (highest fitness first due to vault normalization)
        silver = vault.get("silver", [])
        if isinstance(silver, list) and silver:
            best = silver[0]
            if isinstance(best, dict) and isinstance(best.get("params"), dict):
                return best["params"]

        return {}  # Fallback to defaults

    def _mine_silver(self) -> Optional[Dict[str, Any]]:
        """Queries Synapse DB for the highest conviction winning ticket."""
        if not self.synapse_db.exists(): return None
        
        try:
            with sqlite3.connect(str(self.synapse_db)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM synapse_mint 
                    WHERE pulse_type = 'MINT' AND final_confidence > 0.8 
                    ORDER BY ts DESC LIMIT 1
                """)
                row = cursor.fetchone()
                if row:
                    return dict(row) 
        except Exception as e:
            print(f"[PITUITARY_ERROR] Silver mining failed: {e}")
        return None

    def _retire_to_bronze(self, entry: Dict[str, Any], reason: str):
        """Moves an entry to the bronze lineage in the hot-table vault."""
        vault = self.librarian.get_hormonal_vault()
        bronze_list = vault.get("bronze_history", [])
        if not isinstance(bronze_list, list):
            bronze_list = []

        retired = dict(entry) if isinstance(entry, dict) else {}
        retired["retired_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        retired["retirement_reason"] = reason

        bronze_list.append(retired)
        if len(bronze_list) > 100:
            bronze_list = bronze_list[-100:]

        vault["bronze_history"] = bronze_list
        vault["bronze"] = bronze_list
        self.librarian.set_hormonal_vault(vault)

    def _load_json(self, path: Path) -> Any:
        if not path.exists(): return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[PITUITARY_ERROR] JSON load failed for {path.name}: {e}")
            return {}

    def _save_json(self, path: Path, data: Any):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[PITUITARY_ERROR] Save failed for {path.name}: {e}")
