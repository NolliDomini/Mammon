import os
import sys
from pathlib import Path

# Add project root to sys.path
MAMMON_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MAMMON_ROOT))

def _load_env_file():
    unlock_path = MAMMON_ROOT / ".mammon_unlock"
    env_path = MAMMON_ROOT / ".env"
    
    # Handshake Check
    if not unlock_path.exists():
        print("CRITICAL: .mammon_unlock file missing. Handshake Step 1 failed.")
        return
    
    try:
        with open(unlock_path, "r") as f:
            if f.read().strip() != "MAMMON_INITIALIZE_LIVE_2026":
                print("CRITICAL: Invalid passkey in .mammon_unlock. Handshake Step 2 failed.")
                return
    except Exception as e:
        print(f"Handshake error: {e}")
        return

    # Load credentials if handshake passed
    if not env_path.exists():
        print(f"Warning: .env not found at {env_path}")
        return
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
        print("SUCCESS: Handshake complete. Credentials loaded.")
    except Exception as e:
        print(f"Error loading .env: {e}")

_load_env_file()

def test_alpaca_connection():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")

    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY and ALPACA_API_SECRET must be set in the environment.")
        return

    try:
        from Thalamus.relay import Thalamus
        print(f"Initializing Thalamus with key: {api_key[:4]}...{api_key[-4:]}")
        
        thalamus = Thalamus(api_key=api_key, api_secret=api_secret)
        
        symbol = "BTC/USD"
        print(f"Attempting to fetch latest bar for {symbol}...")
        
        # Test 1: Get Latest Bar
        latest_bar = thalamus.get_latest_bar(symbol, is_crypto=True)
        print(f"SUCCESS: Fetched latest bar: {latest_bar}")

        # Test 2: Get Snapshot
        print(f"Attempting to fetch snapshot for {symbol}...")
        snapshot = thalamus.get_snapshot([symbol], is_crypto=True)
        print(f"SUCCESS: Fetched snapshot: {snapshot}")

    except ImportError as e:
        print(f"ERROR: Could not import Thalamus or dependencies: {e}")
        print("Ensure you are running this in the Mammon environment.")
    except Exception as e:
        print(f"ERROR: Alpaca connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_alpaca_connection()
