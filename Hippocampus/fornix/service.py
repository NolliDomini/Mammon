"""
Hippocampus/Fornix: The Historical Memory Replay Engine.

Named after the fornix — the nerve bundle that carries memories FROM the 
hippocampus TO the rest of the brain. This gland replays stored historical 
data through the real Mammon engine pipeline, minting full synapse tickets 
that ground the optimizer to historical truth.

V4 FORNIX:
  - Feeds DuckDB market_tape bars through SmartGland → Orchestrator
  - Mints BrainFrame synapse tickets at every MINT pulse
  - Keeps optimizer cadence under Soul orchestration contract
  - Configurable Test Pulse for overnight fidelity control
  - Checkpoint/resume for long runs
  - Clears history_synapse after Diamond consumes it (no eternal stacking)
"""

import sys
import time
import json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np

from Hippocampus.duck_pond import DuckPond
from Thalamus.gland import SmartGland
from Cerebellum.Soul.orchestrator import Orchestrator
from Cerebellum.council import Council
from Right_Hemisphere.Snapping_Turtle.engine import SnappingTurtle
from Left_Hemisphere.Monte_Carlo.turtle_monte import TurtleMonte
from Corpus.callosum import Callosum
from Medulla.gatekeeper import Gatekeeper
from Hippocampus.pineal import Pineal
from Pituitary.diamond_deep_search import DiamondGland
from Brain_Stem.connection import Trigger


# ------------------------------------------------------------------ #
#  TEST PULSE CONFIGURATIONS                                          #
# ------------------------------------------------------------------ #
TEST_PULSE_25 = {
    "monte_scale": 0.25,
    "paths_per_lane": 2500,              # TurtleMonte: 25% of 10000
    "risk_gate_paths_per_lane": 83,       # Brain Stem risk: 25% of 333
    "valuation_paths": 2500,              # Brain Stem valuation: 25% of 10000
    "max_hours": 8,
    "checkpoint_interval": 1000,          # Checkpoint every 1000 MINTs
    "optimizer_interval_bars": 75,        # 15 sim-minutes = 75 1-minute bars
    "chunk_size": 500,                    # Bars per SmartGland chunk
}

TEST_PULSE_FULL = {
    "monte_scale": 1.0,
    "paths_per_lane": 10000,
    "risk_gate_paths_per_lane": 333,
    "valuation_paths": 10000,
    "max_hours": 24,
    "checkpoint_interval": 500,
    "optimizer_interval_bars": 75,
    "chunk_size": 500,
}


class Fornix:
    """
    Hippocampus/Fornix: The Historical Memory Replay Engine.
    
    Replays historical bars through the REAL Mammon pipeline,
    minting full synapse tickets that ground the system to truth.
    """
    
    def __init__(self, test_pulse: Dict[str, Any] = None, db_path: str = None,
                 progress_callback=None):
        self.config = test_pulse or TEST_PULSE_25
        self.pond = DuckPond(db_path=db_path)
        self.pineal = Pineal()
        self.start_time = None
        self.run_id = f"fornix-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.progress_callback = progress_callback  # Dashboard hook
        
        # Metrics
        self.total_bars_processed = 0
        self.total_mints = 0
        self.total_signals = 0
        self.total_trades = 0
        self.shutdown_requested = False
        
        # Diamond output path
        self.diamond_path = project_root / "Pituitary" / "diamond.json"
        
        print(f"\n{'='*60}")
        print(f"[FORNIX] Historical Memory Replay Engine")
        print(f"[FORNIX] Run ID: {self.run_id}")
        print(f"[FORNIX] Monte Scale: {self.config['monte_scale']} "
              f"({self.config['paths_per_lane']} paths/lane)")
        print(f"[FORNIX] Max Hours: {self.config['max_hours']}")
        print(f"{'='*60}\n")
    
    # ------------------------------------------------------------------ #
    #  MAIN RUN LOOP                                                      #
    # ------------------------------------------------------------------ #
    def run(self, symbols: List[str] = None, resume: bool = True):
        """
        Main entry point. Replays all symbols (or specified subset) through 
        the engine, minting synapse tickets.
        """
        self.start_time = time.time()
        
        available = self.pond.get_symbol_list()
        if not available:
            print("[FORNIX] ERROR: No symbols in market_tape. Ingest CSVs first.")
            return
        
        targets = symbols if symbols else available
        targets = [s for s in targets if s in available]
        
        total_bars = sum(self.pond.get_bar_count(s) for s in targets)
        print(f"[FORNIX] Targets: {len(targets)} symbols, {total_bars:,} total bars")
        print(f"[FORNIX] Symbols: {', '.join(targets)}")
        print()
        
        for idx, symbol in enumerate(targets):
            if self.shutdown_requested:
                print(f"\n[FORNIX] SHUTDOWN REQUESTED. Stopping at {idx}/{len(targets)} symbols.")
                break

            if self._time_exceeded():
                print(f"\n[FORNIX] TIME LIMIT ({self.config['max_hours']}h) reached. "
                      f"Stopping after {idx}/{len(targets)} symbols.")
                break
            
            self._process_symbol(symbol, idx + 1, len(targets), resume=resume)
        
        # Run Diamond deep search on the accumulated historical data
        consumed_by_diamond = self._run_diamond()
        
        # Archive staged brainframes, then wipe only if Diamond consumed them.
        self._finalize_synapse_staging(consumed_by_diamond)
        
        # Final report
        self._print_report()
    
    # ------------------------------------------------------------------ #
    #  SYMBOL PROCESSING                                                  #
    # ------------------------------------------------------------------ #
    def _process_symbol(self, symbol: str, sym_idx: int, sym_total: int, resume: bool):
        """Processes all bars for a single symbol through the full pipeline."""
        
        # Check checkpoint for resume
        after_ts = None
        bars_offset = 0
        mints_offset = 0
        if resume:
            ckpt = self.pond.get_checkpoint(symbol)
            if ckpt:
                after_ts = ckpt["last_ts"]
                bars_offset = ckpt["bars_processed"]
                mints_offset = ckpt["mints_generated"]
                print(f"[FORNIX] Resuming {symbol} from {after_ts} "
                      f"(bars: {bars_offset:,}, mints: {mints_offset:,})")
        
        # Load bars from DuckDB
        bars_df = self.pond.get_bars_for_symbol(symbol, after_ts=after_ts)
        if bars_df.empty:
            print(f"[FORNIX] {symbol}: No bars to process. Skipping.")
            return
        
        bar_count = len(bars_df)
        print(f"\n[FORNIX] [{sym_idx}/{sym_total}] {symbol}: {bar_count:,} bars")
        
        # Initialize pipeline components (fresh per symbol)
        gland, soul = self._build_pipeline(symbol)
        
        # Tracking
        sym_bars = bars_offset
        sym_mints = mints_offset
        sym_signals = 0
        sym_start = time.time()
        ticket_buffer = []
        last_ts = after_ts
        
        # Chunk-based processing
        chunk_size = self.config["chunk_size"]
        
        for chunk_start in range(0, bar_count, chunk_size):
            if self.shutdown_requested or self._time_exceeded():
                break
            
            chunk_end = min(chunk_start + chunk_size, bar_count)
            chunk = bars_df.iloc[chunk_start:chunk_end].copy()
            
            # Convert to SmartGland format (needs DatetimeIndex)
            chunk.index = pd.to_datetime(chunk["ts"])
            chunk = chunk.drop(columns=["ts"], errors="ignore")
            
            # Feed through SmartGland → get pulses
            pulses = gland.ingest(chunk)
            
            for pulse_type, pulse_data in pulses:
                if pulse_data.empty:
                    continue
                
                # Route through canonical Soul orchestration authority.
                ticket = self._route_pulse_through_soul(
                    pulse_type=pulse_type,
                    pulse_data=pulse_data,
                    symbol=symbol,
                    soul=soul,
                )
                
                if pulse_type == "MINT" and ticket:
                    ticket_buffer.append(ticket)
                    sym_mints += 1
                    
                    if soul.frame.structure.tier1_signal == 1:
                        sym_signals += 1
            
            sym_bars += (chunk_end - chunk_start)
            last_ts = str(chunk.index[-1])
            
            # Flush ticket buffer
            if len(ticket_buffer) >= 100:
                self.pond.write_synapse_batch(ticket_buffer)
                ticket_buffer = []
            
            # Checkpoint
            if sym_mints % self.config["checkpoint_interval"] == 0 and sym_mints > 0:
                self.pond.save_checkpoint(symbol, last_ts, sym_bars, sym_mints)
            
            # Progress report every 10 chunks
            if (chunk_start // chunk_size) % 10 == 0 and chunk_start > 0:
                elapsed = time.time() - sym_start
                rate = sym_bars / max(elapsed, 0.01)
                remaining = (bar_count - (chunk_start + chunk_size)) / max(rate, 1)
                print(f"  [{symbol}] {sym_bars:,}/{bar_count:,} bars "
                      f"({sym_bars/bar_count*100:.1f}%) | "
                      f"{rate:,.0f} bars/s | "
                      f"MINTs: {sym_mints:,} | Signals: {sym_signals:,} | "
                      f"ETA: {remaining/60:.1f}m")
                
                # Dashboard progress hook
                if self.progress_callback:
                    try:
                        self.progress_callback(
                            symbol=symbol, bars_done=sym_bars,
                            total_bars=bar_count, mints=sym_mints,
                            signals=sym_signals, bars_per_sec=rate,
                            eta_minutes=remaining / 60
                        )
                    except Exception:
                        pass
        
        # Flush remaining tickets
        if ticket_buffer:
            self.pond.write_synapse_batch(ticket_buffer)
        
        # Final checkpoint
        if last_ts:
            self.pond.save_checkpoint(symbol, last_ts, sym_bars, sym_mints)
        
        elapsed = time.time() - sym_start
        print(f"  [{symbol}] COMPLETE: {sym_bars:,} bars in {elapsed:.1f}s "
              f"({sym_bars/max(elapsed,0.01):,.0f} bars/s) | "
              f"MINTs: {sym_mints:,} | Signals: {sym_signals:,}")
        
        # Accumulate totals
        self.total_bars_processed += sym_bars
        self.total_mints += sym_mints
        self.total_signals += sym_signals

    # ------------------------------------------------------------------ #
    #  PIPELINE CONSTRUCTION                                              #
    # ------------------------------------------------------------------ #
    def _build_pipeline(self, symbol: str):
        """Constructs a canonical Soul replay pipeline for a symbol."""

        # Load Gold params from vault
        vault_path = project_root / "Hippocampus" / "hormonal_vault.json"
        with open(vault_path, "r") as f:
            vault = json.load(f)
        gold_params = vault["gold"]["params"]

        # Overlay test pulse config onto gold params.
        config = dict(gold_params)
        config.update({
            "paths_per_lane": self.config["paths_per_lane"],
            "risk_gate_paths_per_lane": self.config["risk_gate_paths_per_lane"],
            "valuation_paths": self.config["valuation_paths"],
            "execution_mode": "BACKTEST",
        })

        # Replay input source and canonical orchestrator authority.
        gland = SmartGland(window_minutes=5, context_size=50)
        soul = Orchestrator(config={"execution_mode": "BACKTEST"})

        turtle = SnappingTurtle(config=config)
        council = Council(config=config, mode="BACKTEST")
        monte = TurtleMonte(config=config, mode="BACKTEST")

        # Keep explicit Monte standards for replay-fidelity scaling.
        monte.noise_scalar = float(config.get("monte_noise_scalar", 0.35))
        monte.lane_weights = np.array([
            config.get("monte_w_worst", 0.15),
            config.get("monte_w_neutral", 0.35),
            config.get("monte_w_best", 0.50),
        ])

        callosum = Callosum(config=config, mode="BACKTEST")
        gatekeeper = Gatekeeper(config=config, mode="BACKTEST")
        trigger = Trigger(
            api_key="BACKTEST_MODE",
            api_secret="BACKTEST_MODE",
            paper=True,
            config=config,
        )

        soul.register_lobe("Right_Hemisphere", turtle)
        soul.register_lobe("Council", council)
        soul.register_lobe("Left_Hemisphere", monte)
        soul.register_lobe("Corpus", callosum)
        soul.register_lobe("Gatekeeper", gatekeeper)
        soul.register_lobe("Brain_Stem", trigger)
        soul.set_execution_mode("BACKTEST")

        return gland, soul

    # ------------------------------------------------------------------ #
    #  ORCHESTRATED PULSE ROUTING                                         #
    # ------------------------------------------------------------------ #
    def _route_pulse_through_soul(
        self,
        pulse_type: str,
        pulse_data: pd.DataFrame,
        symbol: str,
        soul: Orchestrator,
    ) -> Optional[dict]:
        """
        Routes one replay pulse through canonical Soul orchestration.
        Returns MINT snapshot for DuckDB replay staging.
        """
        try:
            payload = pulse_data.copy()
            payload["pulse_type"] = str(pulse_type).upper()
            payload["symbol"] = symbol
            soul._process_frame(payload)

            if pulse_type == "MINT":
                if soul.frame.command.ready_to_fire:
                    self.total_trades += 1
                return soul.frame.to_synapse_dict()
        except Exception as e:
            print(f"  [FORNIX_ERROR] pulse={pulse_type} symbol={symbol} error={e}")
            traceback.print_exc()
        return None
    
    # ------------------------------------------------------------------ #
    #  DIAMOND OUTPUT & PINEAL CLEANUP                                    #
    # ------------------------------------------------------------------ #
    def _run_diamond(self):
        """
        Runs Diamond deep search on the accumulated historical synapse data.
        Writes grounded parameters to diamond.json.
        """
        synapse_count = self.pond.get_synapse_count()
        if synapse_count < 50:
            print(f"[FORNIX] Only {synapse_count} synapse tickets. "
                  f"Skipping Diamond (need >= 50).")
            return False
        
        print(f"\n[FORNIX] Running Diamond Deep Search on {synapse_count:,} tickets...")
        try:
            diamond = DiamondGland()
            diamond.perform_deep_search()
            
            # Save Fornix metadata to diamond.json
            diamond_data = {
                "fornix_run_id": self.run_id,
                "minted_at": datetime.now().isoformat(),
                "total_bars": self.total_bars_processed,
                "total_mints": self.total_mints,
                "total_signals": self.total_signals,
                "total_trades": self.total_trades,
                "test_pulse": self.config,
            }
            
            # Append to or create diamond.json
            existing = {}
            if self.diamond_path.exists():
                with open(self.diamond_path, "r") as f:
                    existing = json.load(f)
            
            existing["last_fornix_run"] = diamond_data
            
            with open(self.diamond_path, "w") as f:
                json.dump(existing, f, indent=2)
            
            print(f"[FORNIX] Diamond output written to {self.diamond_path}")
            return True
            
        except Exception as e:
            print(f"[FORNIX_ERROR] Diamond search failed: {e}")
            traceback.print_exc()
            return False
    
    def _finalize_synapse_staging(self, consumed_by_diamond: bool):
        """
        Delegate finalization authority to Pineal.
        """
        self.pineal.finalize_fornix_staging(
            self.pond,
            consumed_by_diamond=consumed_by_diamond,
            run_id=self.run_id,
        )
    
    # ------------------------------------------------------------------ #
    #  UTILITIES                                                          #
    # ------------------------------------------------------------------ #
    def _time_exceeded(self) -> bool:
        """Checks if the max hour limit has been reached."""
        if self.start_time is None:
            return False
        elapsed_hours = (time.time() - self.start_time) / 3600
        return elapsed_hours >= self.config["max_hours"]
    
    def _print_report(self):
        """Prints the final run report."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        print(f"\n{'='*60}")
        print(f"[FORNIX] HISTORICAL REPLAY COMPLETE")
        print(f"{'='*60}")
        print(f"  Run ID:          {self.run_id}")
        print(f"  Duration:        {elapsed/3600:.2f} hours ({elapsed:.0f}s)")
        print(f"  Bars Processed:  {self.total_bars_processed:,}")
        print(f"  MINTs Minted:    {self.total_mints:,}")
        print(f"  Signals (Tier1): {self.total_signals:,}")
        print(f"  Trades Fired:    {self.total_trades:,}")
        if elapsed > 0:
            print(f"  Throughput:      {self.total_bars_processed/elapsed:,.0f} bars/sec")
        print(f"  Diamond Output:  {self.diamond_path}")
        print(f"{'='*60}\n")


# ------------------------------------------------------------------ #
#  ENTRY POINT                                                        #
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fornix: Historical Memory Replay")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to process (default: all)")
    parser.add_argument("--full", action="store_true", help="Full fidelity (no test pulse reduction)")
    parser.add_argument("--hours", type=float, default=8.0, help="Max run hours (default: 8)")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh (ignore checkpoints)")
    parser.add_argument("--db", default=None, help="DuckDB path (default: Hospital/Memory_care/duck.db)")
    
    args = parser.parse_args()
    
    pulse = TEST_PULSE_FULL if args.full else TEST_PULSE_25
    pulse["max_hours"] = args.hours
    
    fornix = Fornix(test_pulse=pulse, db_path=args.db)
    fornix.run(symbols=args.symbols, resume=not args.no_resume)
