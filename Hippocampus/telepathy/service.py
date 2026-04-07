import threading
import queue
import time
from pathlib import Path
from typing import Tuple, List, Any
import sqlite3
from Hippocampus.Archivist.librarian import Librarian

class Telepathy:
    """
    Hippocampus/Telepathy: The Asynchronous Nervous System.
    
    V4 SQL Reliability: 
    - Centralized Connection Factory (Librarian.get_connection)
    - WAL/Timeout hardened
    - Bounded Exponential Backoff for lock contention
    - Enhanced Telemetry and Queue Overflow protection
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Telepathy, cls).__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.queue = queue.Queue(maxsize=10000)
        self.running = True
        self.batch_size = 500
        self.flush_interval = 0.5 
        
        # Telemetry Grid
        self.high_watermark = 0
        self.dropped_items = 0
        self.total_committed = 0
        self.last_commit_time = 0.0
        self.retry_count = 0
        
        # Resolve paths relative to this file for portability
        archivist_dir = Path(__file__).resolve().parents[1] / "Archivist"
        self.vaults = {
            "MEMORY": archivist_dir / "Ecosystem_Memory.db",
            "SYNAPSE": archivist_dir / "Ecosystem_Synapse.db"
        }
        
        # Start the Scribe Daemon
        self.scribe_thread = threading.Thread(target=self._scribe_loop, daemon=True, name="ScribeDaemon")
        self.scribe_thread.start()
        print("[TELEPATHY] Scribe Daemon ignited (V4 Hardened). Routing to: MEMORY, SYNAPSE.")

    def transmit(self, sql: str, params: Any):
        """Fire-and-forget logging. Returns instantly."""
        qsize = self.queue.qsize()
        if qsize > self.high_watermark:
            self.high_watermark = qsize
            if qsize > 2000:
                print(f"[TELEPATHY_METRIC] event=queue_high_watermark count={qsize}")
        
        # V3.1: OOM Guard (Drop Oldest if queue is saturated)
        if self.queue.full():
            try:
                # Discard the oldest item to make room for fresh signal
                _ = self.queue.get_nowait()
                self.dropped_items += 1
                if self.dropped_items % 100 == 0:
                    print(f"[TELEPATHY_CRITICAL] event=queue_saturated_drop dropped_total={self.dropped_items} qsize={qsize}")
            except queue.Empty:
                pass

        self.queue.put((sql, params))

    def _scribe_loop(self):
        """Background loop to drain the queue and commit to disk."""
        while self.running or not self.queue.empty():
            try:
                # 1. Collect a batch (Grouped by Vault)
                vault_batches = {"MEMORY": [], "SYNAPSE": []}
                count = 0
                
                try:
                    # Wait for first item
                    timeout = self.flush_interval if self.running else 0.01
                    item = self.queue.get(timeout=timeout)
                    sql, params = item
                    # Route to synapse if specifically requested, else memory
                    target = "SYNAPSE" if "synapse_mint" in sql.lower() or "history_synapse" in sql.lower() else "MEMORY"
                    vault_batches[target].append((sql, params))
                    count += 1
                    
                    # Drain remainder up to batch size
                    while count < self.batch_size:
                        try:
                            sql, params = self.queue.get_nowait()
                            target = "SYNAPSE" if "synapse_mint" in sql.lower() or "history_synapse" in sql.lower() else "MEMORY"
                            vault_batches[target].append((sql, params))
                            count += 1
                        except queue.Empty:
                            break
                except queue.Empty:
                    if not self.running: break # Final exit if drained
                    continue

                # 2. Commit batches to respective Vaults
                for vault_key, batch in vault_batches.items():
                    if batch:
                        start_time = time.perf_counter()
                        success = self._commit_batch_with_retry(self.vaults[vault_key], batch)
                        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                        
                        if success:
                            self.total_committed += len(batch)
                            self.last_commit_time = elapsed_ms
                            if elapsed_ms > 500: # Slow commit telemetry (threshold increased for WAL)
                                print(f"[TELEPATHY_METRIC] event=slow_commit vault={vault_key} batch={len(batch)} elapsed_ms={elapsed_ms:.2f}")
                        else:
                            self.dropped_items += len(batch)
                            
                        for _ in range(len(batch)):
                            self.queue.task_done()

            except Exception as e:
                print(f"[TELEPATHY CRITICAL] Scribe failure: {e}")
                time.sleep(1)
        print(f"[TELEPATHY] Scribe Daemon extinguished. Total committed: {self.total_committed}, Dropped: {self.dropped_items}, Retries: {self.retry_count}")

    def _commit_batch_with_retry(self, db_path: Path, batch: List[Tuple[str, Any]], max_retries: int = 5) -> bool:
        """Commits a batch with bounded exponential backoff for lock contention."""
        for attempt in range(max_retries):
            try:
                self._commit_batch(db_path, batch)
                return True
            except sqlite3.OperationalError as e:
                err_str = str(e).lower()
                if "locked" in err_str or "busy" in err_str:
                    self.retry_count += 1
                    # Bounded exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                    wait = (2 ** attempt) * 0.1
                    print(f"[TELEPATHY_RETRY] vault={db_path.name} error={e} attempt={attempt+1} wait={wait:.1f}s qsize={self.queue.qsize()}")
                    time.sleep(wait)
                    continue
                else:
                    print(f"[TELEPATHY_ERROR] Permanent SQLite error in vault={db_path.name}: {e}")
                    return False
            except Exception as e:
                print(f"[TELEPATHY_ERROR] Batch commit failed in vault={db_path.name}: {e}")
                return False
        
        print(f"[TELEPATHY_FATAL] Exhausted retries for vault={db_path.name}. Dropping batch of {len(batch)}.")
        return False

    def _commit_batch(self, db_path: Path, batch: List[Tuple[str, Any]]):
        """Low-level batch commit via Librarian factory."""
        with Librarian.get_connection(db_path) as conn:
            cursor = conn.cursor()
            # Explicit transaction management
            conn.execute("BEGIN IMMEDIATE") 
            
            def _serialize(v):
                # Handle pandas.Timestamp, datetime, and NaN
                if hasattr(v, 'isoformat'):
                    return v.isoformat()
                import math
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return 0.0
                return v

            for sql, params in batch:
                if isinstance(params, dict):
                    safe_params = {k: _serialize(v) for k, v in params.items()}
                else:
                    safe_params = tuple(_serialize(x) for x in params)
                cursor.execute(sql, safe_params)
            
            conn.commit()

    def shutdown(self):
        """Graceful shutdown for the Scribe with drain timeout."""
        print(f"[TELEPATHY] Shutdown requested. Draining {self.queue.qsize()} items...")
        self.running = False
        if self.scribe_thread.is_alive():
            self.scribe_thread.join(timeout=10.0)
