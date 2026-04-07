import duckdb
from pathlib import Path

DB_PATH = Path("Hospital/Memory_care/duck.db")

def check_gaps():
    conn = duckdb.connect(str(DB_PATH))
    print("[DIAGNOSTIC] Checking for timestamp gaps in market_tape...")
    
    # Get all symbols
    symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM market_tape").fetchall()]
    
    results = []
    for sym in symbols:
        # gap_size 2 means 1 minute is missing (e.g. 10:00 to 10:02)
        query = f"""
        SELECT 
            gap_size,
            count(*) as gap_count
        FROM (
            SELECT 
                ts,
                lead(ts) OVER (ORDER BY ts) as next_ts,
                (epoch(lead(ts) OVER (ORDER BY ts)) - epoch(ts)) / 60 as gap_size
            FROM market_tape 
            WHERE symbol = '{sym}'
        ) 
        WHERE gap_size > 1
        GROUP BY gap_size
        ORDER BY gap_size ASC
        """
        try:
            gaps = conn.execute(query).fetchall()
            if gaps:
                results.append((sym, gaps))
        except Exception as e:
            print(f"Error on {sym}: {e}")
            
    print("\nGAP ANALYSIS PER SYMBOL:")
    print("-" * 60)
    for sym, gaps in results:
        one_min_gaps = sum(count for size, count in gaps if size == 2)
        larger_gaps = sum(count for size, count in gaps if size > 2)
        print(f"{sym:<10} | 1-min gaps: {one_min_gaps:>6} | 2+ min gaps: {larger_gaps:>6}")
        if larger_gaps > 0:
            examples = [g for g in gaps if g[0] > 2][:3]
            print(f"   Examples (size in mins): {examples}")

if __name__ == "__main__":
    check_gaps()
