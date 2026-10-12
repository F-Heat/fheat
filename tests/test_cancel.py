"""Tests for the cooperative cancellation (fheat_core.cancel).

The expert mode's interrupt of HiGHS is tested in test_network_expert.py.
"""
from __future__ import annotations

import time

import pytest

from fheat_core import cancel
from fheat_core.cancel import CalculationCancelled, cancellable, current_check, raise_if_cancelled
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import network as network_step


def _stop_from_call(n):
    """A should_stop that answers True from its n-th call on, and counts its calls."""
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) >= n

    should_stop.calls = calls
    return should_stop


# ---------------------------------------------------------------------------
# The module
# ---------------------------------------------------------------------------


def test_without_a_check_nothing_is_cancelled():
    assert current_check() is None
    raise_if_cancelled()


def test_the_check_applies_inside_the_block_only():
    with cancellable(lambda: True):
        with pytest.raises(CalculationCancelled):
            raise_if_cancelled()
    raise_if_cancelled()
    assert current_check() is None


def test_none_keeps_the_check_of_the_enclosing_block():
    outer = lambda: True  # noqa: E731
    with cancellable(outer):
        with cancellable(None):
            assert current_check() is outer
        with cancellable(lambda: False):
            raise_if_cancelled()
        assert current_check() is outer


def test_except_exception_does_not_swallow_a_cancel():
    """Downloads and optional layers catch Exception; a cancel must get through."""
    with cancellable(lambda: True):
        with pytest.raises(CalculationCancelled):
            try:
                raise_if_cancelled()
            except Exception:  # noqa: BLE001 — the point of the test
                pytest.fail("CalculationCancelled was caught as an Exception")


def test_sleep_ends_early_once_cancelled():
    should_stop = _stop_from_call(2)
    start = time.monotonic()
    with cancellable(should_stop):
        with pytest.raises(CalculationCancelled):
            cancel.sleep(30)
    assert time.monotonic() - start < 5


def test_sleep_waits_the_whole_time_without_a_cancel():
    start = time.monotonic()
    with cancellable(lambda: False):
        cancel.sleep(0.2)
    assert time.monotonic() - start >= 0.2


# ---------------------------------------------------------------------------
# Orchestrator and NETWORK step
# ---------------------------------------------------------------------------


def test_the_orchestrator_asks_before_every_step(tmp_path):
    # the adapter is never used: the step does not start
    orchestrator = FHeatOrchestrator(
        FHeatConfig(output_dir=str(tmp_path)), adapter=None, should_stop=lambda: True
    )
    with pytest.raises(CalculationCancelled):
        orchestrator.run_step(Phase.INITIAL)
    assert orchestrator.state.phase == Phase.INITIAL


def test_the_orchestrator_hands_its_check_to_the_step(
    tmp_path, buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter
):
    state = PipelineState(
        phase=Phase.STATUS, buildings_gdf=buildings_gdf, streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf, source_gdf=source_gdf,
    )
    should_stop = _stop_from_call(2)  # the orchestrator's own check passes
    orchestrator = FHeatOrchestrator(
        FHeatConfig(output_dir=str(tmp_path)), stub_adapter, state=state, should_stop=should_stop
    )
    with pytest.raises(CalculationCancelled):
        orchestrator.run_step(Phase.STATUS)
    assert len(should_stop.calls) == 2
    assert state.net_gdf is None


def test_a_cancel_inside_the_shortest_path_backend_stops_the_step(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter
):
    state = PipelineState(
        phase=Phase.STATUS, buildings_gdf=buildings_gdf, streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf, source_gdf=source_gdf,
    )
    # passes the step's checkpoint before the backend, stops in the backend
    should_stop = _stop_from_call(2)
    with cancellable(should_stop):
        with pytest.raises(CalculationCancelled):
            network_step.run(state, FHeatConfig(), stub_adapter)
    assert state.net_gdf is None


def test_without_a_cancel_the_step_runs_as_before(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter
):
    state = PipelineState(
        phase=Phase.STATUS, buildings_gdf=buildings_gdf, streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf, source_gdf=source_gdf,
    )
    with cancellable(lambda: False):
        out = network_step.run(state, FHeatConfig(), stub_adapter)
    assert out.phase == Phase.NETWORK
    assert not out.net_gdf.empty
