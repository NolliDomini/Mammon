import sqlite3
import time
from pathlib import Path
from typing import Dict, Any
from Hippocampus.Archivist.librarian import Librarian

class Pineal:
    """
    Hippocampus/Pineal: The Circadian Ruler.
    V4 SQL Hardened: Uses Librarian for robust pruning.
    
    Role:
    - Purges all non-MINT rows from the Synapse silo.
    - Enforces aggressive retention on short-term memory (simulations, walks).
    - Preserves MINT synapse tickets (complete engine state) for 90 days.
    - Secrete Melatonin: The cleanup signal.
    """
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        
        self.memory_db = self.root / "Hippocampus" / "Archivist" / "Ecosystem_Memory.db"
        self.synapse_db = self.root / "Hippocampus" / "Archivist" / "Ecosystem_Synapse.db"
        self.optimizer_db = self.root / "Hippocampus" / "Archivist" / "Ecosystem_Optimizer.db"
        self.control_db = self.root / "Hospital" / "Memory_care" / "control_logs.db"
        
        # V3.2 STRICT: Tightened retention (hours)
        self.retention_map = {
            # Short-Term Memory (AGGRESSIVE)
            "council_mint": 6,               # Was 24h -> 6h
            "turtle_monte_mint": 1,          # Was 6h -> 1h (massive volume)
            "quantized_walk_mint": 6,        # Was 24h -> 6h
            # Long-Term Synapse (MINT-only, preserved)
            "synapse_mint": 2160,            # 90 days (24 * 90) -- MINT tickets are sacred
            # Control Logs
            "librarian_write_log": 24,       # Was 48h -> 24h
            "librarian_read_log": 24,
            # Optimizer Hygiene (1 hour retention)
            "walk_mutations": 1,
            "monte_candidates": 1,
            "lhs_candidates": 1,
            "bayesian_candidates": 1
        }

    def secrete_melatonin(self, pulse_type: str = "MINT"):
        """
        The Sleep Cycle.
        V3.2 STRICT: First purges all non-MINT rows, then prunes by age.
        """
        print("[PINEAL] Secreting Melatonin... (Strict Cleanup Cycle)")
        
        try:
            # PHASE 1: Purge non-MINT rows (surgical)
            self._purge_non_mint()
            
            # PHASE 2: Time-based retention (age pruning)
            # Short-Term Memory
            self._prune_vault(self.memory_db, ["council_mint", "turtle_monte_mint", "quantized_walk_mint"])
            
            # Long-Term Synapse (only MINT survives Phase 1)
            self._prune_vault(self.synapse_db, ["synapse_mint"])
            
            # Optimizer Furnace (Aggressive)
            self._prune_vault(self.optimizer_db, ["walk_mutations", "monte_candidates", "lhs_candidates", "bayesian_candidates"])
            
            # Control Logs
            self._prune_vault(self.control_db, ["librarian_write_log", "librarian_read_log"])
            
        except Exception as e:
            print(f"[PINEAL_ERROR] Melatonin secretion failed: {e}")

    def finalize_fornix_staging(self, pond, *, consumed_by_diamond: bool, run_id: str):
        """
        Finalize Fornix staging via Pineal authority.
        Archives staged history synapse tickets and only wipes staging/checkpoints
        when Diamond consumed the staged data successfully.
        """
        try:
            count = int(pond.get_synapse_count())
            if count <= 0:
                print("[PINEAL] No staged synapse tickets to finalize.")
                return

            archived = int(pond.archive_history_synapse(run_id=run_id))
            print(f"[PINEAL] Archived {archived:,} staged brainframes.")

            if consumed_by_diamond:
                pond.clear_history_synapse()
                print(
                    f"[PINEAL] Pineal wipe complete: cleared {count:,} staged synapse "
                    "tickets and checkpoints after Diamond consumption."
                )
            else:
                print("[PINEAL] Staged synapse retained (Diamond did not consume this run).")
        except Exception as e:
            print(f"[PINEAL_ERROR] finalize_fornix_staging failed: {e}")

    def _purge_non_mint(self):
        """
        V3.2 STRICT: Delete any row where pulse_type != 'MINT'.
        SEED and ACTION data is ephemeral -- it never needed to be saved.
        """
        # Purge from Synapse DB
        self._delete_non_mint(self.synapse_db, ["synapse_mint"])
        
        # Purge from Memory DB (council, monte, walk tables may have non-MINT rows)
        self._delete_non_mint(self.memory_db, ["council_mint", "turtle_monte_mint", "quantized_walk_mint"])

    def _delete_non_mint(self, db_path: Path, tables: list):
        """Deletes all non-MINT rows from the specified tables."""
        if not db_path.exists():
            return
        try:
            with Librarian.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing = {row[0] for row in cursor.fetchall()}
                
                for table in tables:
                    if table not in existing:
                        continue
                    try:
                        cursor.execute(f"DELETE FROM {table} WHERE pulse_type IS NOT NULL AND pulse_type != 'MINT'")
                        deleted = cursor.rowcount
                        if deleted > 0:
                            print(f"   [PINEAL] Purged {deleted} non-MINT rows from {table}")
                    except sqlite3.OperationalError:
                        pass  # Table may not have pulse_type column
                conn.commit()
        except Exception as e:
            print(f"[PINEAL_ERROR] Non-MINT purge failed on {db_path.name}: {e}")

    def _prune_vault(self, db_path: Path, tables: list):
        """Generic pruner for a SQLite vault."""
        if not db_path.exists():
            return
            
        try:
            with Librarian.get_connection(db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row[0] for row in cursor.fetchall()}
                
                for table in tables:
                    if table not in existing_tables:
                        continue
                        
                    hours = self.retention_map.get(table, 24)
                    params = (f"-{hours} hours",)
                    
                    try:
                        try:
                            sql = f"DELETE FROM {table} WHERE ts < datetime('now', ?)"
                            cursor.execute(sql, params)
                        except sqlite3.OperationalError:
                            try:
                                sql = f"DELETE FROM {table} WHERE created_at < datetime('now', ?)"
                                cursor.execute(sql, params)
                            except sqlite3.OperationalError:
                                sql = f"DELETE FROM {table} WHERE logged_at < datetime('now', ?)"
                                cursor.execute(sql, params)
                                
                        deleted = cursor.rowcount
                        if deleted > 0:
                            print(f"   [PINEAL] Pruned {deleted} rows from {table} (> {hours}h)")
                            
                    except Exception as e:
                         print(f"   [PINEAL_WARN] Could not prune table '{table}': {e}")
                
                conn.commit()
                
        except Exception as e:
            print(f"[PINEAL_ERROR] Failed to access {db_path.name}: {e}")

if __name__ == "__main__":
    gland = Pineal()
    gland.secrete_melatonin()
