import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Hippocampus.Archivist.librarian import MultiTransportLibrarian, librarian


class Telepathy:
    """
    Hippocampus/Telepathy: The Asynchronous Nervous System (v5).
    
    Piece 117: Redis Streams Integration.
    - Replaces in-memory queue with a durable Redis Stream.
    - Multi-Transport routing (DuckDB, TimescaleDB).
    - Vectorized batching via XREAD.
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
        self.librarian = librarian
        self.stream_key = "mammon:telepathy:stream"
        self.running = True
        self.batch_size = 500
        self.flush_interval = 0.5 
        
        # Telemetry Grid
        self.total_committed = 0
        self.dropped_items = 0
        self.last_commit_time = 0.0
        
        # Start the Scribe Daemon
        self.scribe_thread = threading.Thread(target=self._scribe_loop, daemon=True, name="ScribeDaemon")
        self.scribe_thread.start()
        print(f"[TELEPATHY] Scribe Daemon ignited (v5 Redis). Streaming to: {self.stream_key}")

    def transmit(self, sql: str, params: Any, transport: str = "auto"):
        """
        Piece 117: Fire-and-forget logging via Redis Streams.
        Durable and cross-process safe.
        """
        try:
            redis_conn = self.librarian.get_redis_connection()
            
            # Determine transport if 'auto'
            if transport == "auto":
                sql_l = sql.lower()
                if "money_" in sql_l or "audit" in sql_l:
                    transport = "timescale"
                elif "_mint" in sql_l:
                    transport = "duckdb"
                else:
                    transport = "duckdb" # Default analytical

            # Serialize payload
            payload = {
                "sql": sql,
                "params": self._serialize_params(params),
                "transport": transport
            }
            
            # XADD to stream (Max length 10k to prevent OOM)
            # Target #64: Track persistent drops in Redis
            try:
                redis_conn.xadd(self.stream_key, {"payload": json.dumps(payload)}, maxlen=10000, approximate=True)
            except Exception as e:
                # HIPP-W-P68-702: Stream XADD inner retry
                redis_conn.incr("mammon:telepathy:dropped_total")
                raise
            
        except Exception as e:
            # HIPP-E-P68-703: Outer transmit exception
            self.dropped_items += 1
            if self.dropped_items % 100 == 0:
                print(f"[HIPP-E-P68-703] TELEPATHY_TRANSMIT_FAILED: {e} (Dropped: {self.dropped_items})")

    def _serialize_params(self, params: Any) -> Any:
        def _ser(v):
            if hasattr(v, 'isoformat'):
                return v.isoformat()
            import math
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return 0.0
            return v

        if isinstance(params, dict):
            return {k: _ser(v) for k, v in params.items()}
        elif isinstance(params, (list, tuple)):
            return [_ser(x) for x in params]
        return _ser(params)

    def _scribe_loop(self):
        """Background loop to drain Redis Stream and commit to disk."""
        redis_conn = self.librarian.get_redis_connection()
        last_id = "0-0" # Start from beginning if not resuming
        
        while self.running:
            try:
                # 1. Read batch from Stream
                messages = redis_conn.xread({self.stream_key: last_id}, count=self.batch_size, block=int(self.flush_interval * 1000))
                
                if not messages:
                    continue

                # Parse messages: [[stream_key, [[id, {payload: ...}], ...]]]
                batch_data = messages[0][1]
                
                # 2. Group by transport (Target #63: Explicit Routing)
                transport_batches: Dict[str, List[Tuple[str, Any]]] = {
                    "duckdb": [],
                    "timescale": []
                }
                
                msg_ids = []
                for msg_id, data in batch_data:
                    payload = json.loads(data["payload"])
                    # Standardize on explicit 'transport' key from payload
                    t = payload.get("transport", "duckdb")
                    if t in transport_batches:
                        transport_batches[t].append((payload["sql"], payload["params"]))
                    msg_ids.append(msg_id)
                    last_id = msg_id

                # 3. Commit batches
                start_time = time.perf_counter()
                for transport, batch in transport_batches.items():
                    if not batch: continue
                    
                    try:
                        # Process batch sequentially through librarian
                        # (Future Piece could vectorize this further)
                        for sql, params in batch:
                            self.librarian.write_direct(sql, params, transport=transport)
                        
                        self.total_committed += len(batch)
                    except Exception as e:
                        print(f"[TELEPATHY_ERROR] Batch commit failed for {transport}: {e}")
                        self.dropped_items += len(batch)

                # 4. Cleanup (Acknowledge/Delete processed items)
                try:
                    redis_conn.xdel(self.stream_key, *msg_ids)
                except Exception as e:
                    print(f"[HIPP-E-P68-704] TELEPATHY_CLEANUP_FAILED: {e}")
                
                self.last_commit_time = (time.perf_counter() - start_time) * 1000.0

            except Exception as e:
                # Phase 7 Target: Standardized MNER for fatal scribe failure
                print(f"[HIPP-F-P68-701] TELEPATHY_SCRIBE_FATAL_FAILURE: {e}")
                time.sleep(1)

    def shutdown(self):
        print("[TELEPATHY] Shutdown requested.")
        self.running = False
        if self.scribe_thread.is_alive():
            self.scribe_thread.join(timeout=5.0)
