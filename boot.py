import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Add root to sys.path for internal imports
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from Hippocampus.Archivist.librarian import librarian
from Hippocampus.schema_guard import run_schema_smoke_check

class MammonBootstrapper:
    """
    Mammon Bootstrapper (Piece 118).
    Handles the initial system handshake and readiness checks.
    """
    def __init__(self):
        print("🚀 [BOOT] Starting Mammon Neural Integration (v2.1)...")
        load_dotenv()

    def run_handshake(self) -> bool:
        """Executes all readiness checks. Fails fast if any critical component is missing."""
        try:
            # 1. Environment Validation
            self._check_env()
            
            # 2. Redis Handshake (Piece 114/115)
            self._check_redis()
            
            # 3. DuckDB & Timescale Handshake (Piece 100/101/116)
            self._check_librarian()
            
            # 4. Schema Smoke Check
            self._check_schemas()
            
            # 5. Phase 1 Engine Smoke Check (Piece 160)
            self._check_phase1_engines()
            
            print("✅ [BOOT] Handshake successful. System READY.")
            return True
            
        except Exception as e:
            print(f"❌ [BOOT_FATAL] Handshake failed: {e}")
            return False

    def _check_phase1_engines(self):
        """Smoke check for new Phase 1 execution friction and sizing engines."""
        try:
            from Cerebellum.council.spread_engine.service import SpreadEngine
            from Brain_Stem.pons_execution_cost.service import PonsExecutionCost
            from Medulla.allocation_gland.service import AllocationGland
            
            SpreadEngine()
            PonsExecutionCost()
            AllocationGland()
            print("   [BOOT] Phase 1 Engines (Spread, Pons, Alloc) verified.")
        except Exception as e:
            raise RuntimeError(f"Phase 1 engine verification failed: {e}")

    def _check_env(self):
        required = ["ALPACA_API_KEY", "ALPACA_API_SECRET", "REDIS_HOST", "TIMESCALE_HOST"]
        missing = [var for var in required if not os.getenv(var)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        print("   [BOOT] Environment variables loaded.")

    def _check_redis(self):
        try:
            redis_conn = librarian.get_redis_connection()
            redis_conn.ping()
            print(f"   [BOOT] Redis handshake successful: {os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}")
        except Exception as e:
            raise RuntimeError(f"Redis connection failed: {e}")

    def _check_librarian(self):
        try:
            # Check DuckDB
            duck = librarian.get_duck_connection()
            duck.execute("SELECT 1")
            print("   [BOOT] DuckDB analytical gateway active.")
            
            # Check Timescale
            timescale = librarian.get_timescale_connection()
            with timescale.cursor() as cur:
                cur.execute("SELECT 1")
            print(f"   [BOOT] TimescaleDB audit gateway active: {os.getenv('TIMESCALE_HOST', 'localhost')}")
            
        except Exception as e:
            raise RuntimeError(f"Librarian transport initialization failed: {e}")

    def _check_schemas(self):
        self._init_timescale_schema()
        report = run_schema_smoke_check(ROOT_DIR)
        if not report.get("ok"):
            print(f"   [BOOT_WARN] Schema drift detected: {len(report.get('critical_drift_issues', []))} critical issues.")
            # If we want to fail on drift, we'd raise an error here.
            # For now, we just log it as per standard Mammon behavior.
        print("   [BOOT] Schema smoke check complete.")

    def _init_timescale_schema(self):
        sql_path = ROOT_DIR / "scripts" / "migrations" / "timescale_init.sql"
        if not sql_path.exists():
            raise RuntimeError(f"Timescale init script missing: {sql_path}")

        sql_text = sql_path.read_text(encoding="utf-8")
        statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
        if not statements:
            raise RuntimeError(f"Timescale init script is empty: {sql_path}")

        conn = librarian.get_timescale_connection()
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        print("   [BOOT] Timescale schema initialization complete.")

if __name__ == "__main__":
    boot = MammonBootstrapper()
    if not boot.run_handshake():
        sys.exit(1)
