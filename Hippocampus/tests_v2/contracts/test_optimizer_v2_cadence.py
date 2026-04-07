from Hospital.Optimizer_loop.volume_furnace_orchestrator import VolumeFurnaceOrchestrator


def test_live_cadence_runs_every_third_mint():
    f = VolumeFurnaceOrchestrator(simulation_mode=False, external_cadence=False)
    calls = []
    f.engine.run_pipeline = lambda **kwargs: calls.append(kwargs) or {"status": "ok"}  # type: ignore[method-assign]

    for _ in range(9):
        f.handle_pulse("MINT", regime_id="R1", price=100.0, atr=1.0, stop_level=99.0)

    # 9 MINTs -> 3 scheduled activations (every third mint), all should execute in live mode.
    assert len(calls) == 3


def test_fornix_external_cadence_backtest_25_mode():
    f = VolumeFurnaceOrchestrator(execution_mode="BACKTEST", external_cadence=True)
    calls = []
    f.engine.run_pipeline = lambda **kwargs: calls.append(kwargs) or {"status": "ok"}  # type: ignore[method-assign]

    for _ in range(12):
        # Caller controls cadence (e.g. Fornix optimizer_interval_bars gate),
        # so each call is a scheduled optimizer activation opportunity.
        f.handle_pulse("MINT", regime_id="R2", price=100.0, atr=1.0, stop_level=99.0)

    # BACKTEST 25% mode: execute every 4th scheduled activation.
    assert len(calls) == 3
