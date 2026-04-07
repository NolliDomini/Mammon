from Hippocampus.Archivist.librarian import librarian

class WardManager:
    """
    Cerebellum/Soul/Utils: The Ward Manager.
    Responsible for pre-flight memory hygiene and janitorial sweeps.
    """
    def __init__(self):
        self.librarian = librarian

    def janitor_sweep(self):
        """
        Clears stale ephemeral state on system boot.
        Specifically targets Redis BrainFrame keys to prevent cross-session contamination.
        """
        try:
            redis_conn = self.librarian.get_redis_connection()
            # Find all BrainFrame keys
            keys = redis_conn.keys("mammon:brain_frame:*")
            if keys:
                redis_conn.delete(*keys)
                print(f"[WARD_MANAGER] Janitor Sweep complete. Purged {len(keys)} stale BrainFrames from Redis.")
            else:
                print("[WARD_MANAGER] Janitor Sweep complete. Ward is clean.")
        except Exception as e:
            # SOUL-W-P35-215: Janitor sweep exception
            print(f"[SOUL-W-P35-215] WARD_MANAGER: Janitor Sweep failed: {e}")
