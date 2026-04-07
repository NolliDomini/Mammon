import os
import sys
import time
import pandas as pd
import duckdb
from datetime import datetime, timedelta, timezone
from pathlib import Path
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# --- CONFIGURATION ---
MAMMON_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = MAMMON_ROOT / "Hospital" / "Memory_care" / "duck.db"
START_DATE = datetime(2020, 1, 1, tzinfo=timezone.utc)
CHUNK_DAYS = 30 

# Extreme Diversity Batch (Commodities, FX, Bonds, Global, Sectors, Thematic, Tech, Crypto)
STOCK_SYMBOLS = [
    # Commodities & Materials
    "USO", "UNG", "DBA", "GDX", "XOP", "XME", "WOOD", "PICK", "GLD", "SLV", "DBC", "XLB", "LIT",
    # Currencies (ETFs)
    "UUP", "FXE", "FXY", "FXA", "FXB", "FXF", "FXC", "CYB",
    # Bonds & Fixed Income
    "TIPS", "TLT", "HYG", "LQD", "BND", "AGG", "SHY", "IEF", "JNK", "EMB",
    # Global / International
    "EEM", "EWZ", "FXI", "EWJ", "VGK", "INDA", "EFA", "VWO", "KWEB",
    # US Sectors (The "XL" suite)
    "XLP", "XLV", "VNQ", "XLF", "XLE", "XLU", "XLI", "XLY", "XLK", "XLRE",
    # Thematic & Innovation
    "ARKK", "SMH", "IBB", "ITA", "TAN", "BITO", "SVXY", "MOON",
    # High-Volume Tech & Growth
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "PLTR", "SQ", "SHOP",
    # Broad Market & Other
    "SPY", "QQQ", "IWM", "DIA", "VXX", "SPSM", "SIRI", "AMC", "HOOD", "COIN"
]

CRYPTO_SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "DOGE/USD", "DOT/USD", 
    "MATIC/USD", "LTC/USD", "LINK/USD", "BCH/USD", "SHIB/USD", "AVAX/USD",
    "NEAR/USD", "FIL/USD", "UNI/USD", "XRP/USD", "AAVE/USD", "GRT/USD",
    "MKR/USD", "SNX/USD", "CRV/USD", "ALGO/USD", "BAT/USD"
]

def _load_env_file():
    unlock_path = MAMMON_ROOT / ".mammon_unlock"
    env_path = MAMMON_ROOT / ".env"
    if not unlock_path.exists() or not env_path.exists():
        print("CRITICAL: .env or .mammon_unlock missing.")
        sys.exit(1)
    with open(unlock_path, "r") as f:
        if f.read().strip() != "MAMMON_INITIALIZE_LIVE_2026":
            print("CRITICAL: Invalid handshake.")
            sys.exit(1)
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

def hydrate():
    _load_env_file()
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    
    stock_client = StockHistoricalDataClient(api_key, api_secret)
    crypto_client = CryptoHistoricalDataClient(api_key, api_secret)
    db = duckdb.connect(str(DB_PATH))

    # Get already processed symbols to avoid duplication
    existing_symbols = [r[0] for r in db.execute("SELECT DISTINCT symbol FROM market_tape").fetchall()]
    
    all_targets = [(s, True) for s in CRYPTO_SYMBOLS] + [(s, False) for s in STOCK_SYMBOLS]
    
    for symbol, is_crypto in all_targets:
        clean_symbol = symbol.replace("/", "_") if is_crypto else symbol
        if clean_symbol in existing_symbols:
            print(f"Skipping {symbol} (already in lake).")
            continue

        print(f"\n--- HYDRATING DIVERSITY BATCH: {symbol} ---")
        current_start = START_DATE
        end_date = datetime.now(timezone.utc) - timedelta(days=1)
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=CHUNK_DAYS), end_date)
            print(f"  [FETCH] {symbol:<10} | {current_start.date()} -> {current_end.date()}...", end="\r")
            
            try:
                if is_crypto:
                    req = CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Minute, start=current_start, end=current_end)
                    bars = crypto_client.get_crypto_bars(req)
                else:
                    req = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Minute, start=current_start, end=current_end)
                    bars = stock_client.get_stock_bars(req)
                
                df = bars.df
                if df is not None and not df.empty:
                    df = df.reset_index()
                    if "symbol" not in df.columns: df["symbol"] = symbol
                    df["symbol"] = df["symbol"].str.replace("/", "_")
                    
                    final_df = df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()
                    final_df.columns = ["ts", "symbol", "open", "high", "low", "close", "volume"]
                    
                    db.execute("INSERT INTO market_tape SELECT * FROM final_df")
                    current_total = db.execute("SELECT count(*) FROM market_tape").fetchone()[0]
                    print(f"  [LAKE]  {symbol:<10} | Inserted {len(final_df):>6,} bars | Total Lake: {current_total:>12,} ")
                
                time.sleep(0.5) 
                
            except Exception as e:
                print(f"    ERROR on {symbol}: {e}")
                time.sleep(5) 
            
            current_start = current_end

    total = db.execute("SELECT count(*) FROM market_tape").fetchone()[0]
    print(f"\nHYDRATION COMPLETE. Total rows in lake: {total:,}")
    db.close()

if __name__ == "__main__":
    hydrate()
