"""Tests for the two pipeline stages.

* Analysis (download → adjust → status) runs on the whole area without a
  heat source.
* Planning (network → results) connects only the buildings inside
  ``PipelineState.planning_area_gdf`` and needs a heat source.
* Every step stays runnable on its own.
"""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.errors import PipelineInputError
from fheat_core.orchestrator import (
    ANALYSIS_STEPS,
    PLANNING_STEPS,
    STEP_INPUT_PHASE,
    STEP_OUTPUT_PHASE,
    FHeatOrchestrator,
)
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import adjust, download, network, results, status

from tests.conftest import StubAdapter

CRS = "EPSG:25832"


@pytest.fixture
def no_source_adapter(buildings_gdf, streets_gdf, parcels_gdf, pipe_info_df, temperature_series):
    return StubAdapter(
        buildings_gdf, streets_gdf, parcels_gdf, None,
        pipe_info=pipe_info_df, temperature=temperature_series, holidays={},
    )


@pytest.fixture
def first_two_buildings_area():
    """Covers the buildings at x=0..10 and x=50..60, not the one at x=100..110."""
    return gpd.GeoDataFrame(geometry=[box(-20, -20, 70, 20)], crs=CRS)


def _cfg(tmp_path):
    return FHeatConfig(output_dir=str(tmp_path), buffer_distance=15.0)


class TestStepConstants:
    def test_stages_cover_all_steps_in_order(self):
        assert ANALYSIS_STEPS + PLANNING_STEPS == tuple(STEP_INPUT_PHASE)

    def test_output_phase_is_next_input_phase(self):
        steps = list(STEP_INPUT_PHASE)
        for current, following in zip(steps, steps[1:]):
            assert STEP_OUTPUT_PHASE[current] == STEP_INPUT_PHASE[following]


class TestAnalysisWithoutSource:
    def test_steps_run_without_source(self, no_source_adapter, tmp_path):
        cfg = _cfg(tmp_path)
        state = PipelineState()
        download.run(state, cfg, no_source_adapter)
        assert state.source_gdf is None
        adjust.run(state, cfg, no_source_adapter)
        status.run(state, cfg, no_source_adapter)
        assert state.phase == Phase.STATUS
        assert state.wld_gdf is not None

    def test_run_analysis_stops_after_status(self, no_source_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), no_source_adapter)
        orch.run_analysis()
        assert orch.state.phase == Phase.STATUS
        assert orch.state.net_gdf is None

    def test_run_analysis_resumes_from_current_phase(self, no_source_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), no_source_adapter)
        orch.run_step(Phase.INITIAL)
        orch.run_analysis()
        assert orch.state.phase == Phase.STATUS

    def test_network_without_source_raises(self, no_source_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), no_source_adapter)
        orch.run_analysis()
        with pytest.raises(PipelineInputError, match="heat source"):
            orch.run_step(Phase.STATUS)


class TestPlanning:
    def test_run_planning_needs_analysis(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        with pytest.raises(PipelineInputError, match="analysis"):
            orch.run_planning()

    def test_source_set_after_analysis(self, no_source_adapter, source_gdf, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), no_source_adapter)
        orch.run_analysis()
        orch.state.source_gdf = source_gdf
        orch.run_planning()
        assert orch.state.phase == Phase.RESULTS
        assert orch.state.result_summary["total_buildings"] == 3

    def test_planning_area_limits_connected_buildings(
        self, stub_adapter, first_two_buildings_area, tmp_path,
    ):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        orch.state.planning_area_gdf = first_two_buildings_area
        orch.run_planning()
        s = orch.state
        assert s.result_summary["total_buildings"] == 2
        assert s.result_summary["total_heat_demand_mwh_a"] == pytest.approx(40.0)
        assert s.net_gdf[cols.N_BUILDINGS].max() == 2
        # connect flags of the whole frame stay untouched
        assert (s.buildings_gdf[cols.CONNECT] == 1).all()
        assert len(s.buildings_gdf) == 3

    def test_analysis_ignores_planning_area(self, stub_adapter, first_two_buildings_area, tmp_path):
        """WLD is computed for all buildings, also when a planning area is set."""
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.state.planning_area_gdf = first_two_buildings_area
        orch.run_analysis()
        assert orch.state.wld_gdf[cols.HEAT_DEMAND].sum() == pytest.approx(75000.0)

    def test_source_outside_planning_area_is_connected(
        self, stub_adapter, tmp_path,
    ):
        """The route to a source outside the area follows the complete street net."""
        area = gpd.GeoDataFrame(geometry=[box(90, -20, 130, 20)], crs=CRS)  # only x=100..110
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        orch.state.planning_area_gdf = area
        orch.run_planning()
        net = orch.state.net_gdf
        assert orch.state.result_summary["total_buildings"] == 1
        # the network reaches from the source (x=-10) to the building (x≈105)
        assert net.total_bounds[0] == pytest.approx(-10.0)
        assert net.total_bounds[2] >= 100.0

    def test_empty_selection_raises(self, stub_adapter, tmp_path):
        area = gpd.GeoDataFrame(geometry=[box(500, 500, 600, 600)], crs=CRS)
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        orch.state.planning_area_gdf = area
        with pytest.raises(PipelineInputError, match="planning area"):
            orch.run_step(Phase.STATUS)

    def test_planning_area_in_other_crs(self, stub_adapter, first_two_buildings_area, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        orch.state.planning_area_gdf = first_two_buildings_area.to_crs("EPSG:4326")
        orch.run_planning()
        assert orch.state.result_summary["total_buildings"] == 2


class TestSingleSteps:
    def test_each_step_on_its_own(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        for step in ANALYSIS_STEPS + PLANNING_STEPS:
            orch.run_step(STEP_INPUT_PHASE[step])
            assert orch.state.phase == STEP_OUTPUT_PHASE[step]

    def test_step_without_earlier_frames_raises(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        with pytest.raises(PipelineInputError, match="buildings_gdf"):
            orch.run_step(Phase.ADJUSTED)

    def test_results_without_network_raises(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        with pytest.raises(PipelineInputError, match="net_gdf"):
            orch.run_step(Phase.NETWORK)

    def test_results_step_function_without_network_raises(self, stub_adapter, tmp_path):
        state = PipelineState()
        cfg = _cfg(tmp_path)
        download.run(state, cfg, stub_adapter)
        with pytest.raises(PipelineInputError, match="network"):
            results.run(state, cfg, stub_adapter)

    def test_run_until_rejects_past_phase(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        with pytest.raises(ValueError, match="already past"):
            orch.run_until(Phase.DOWNLOADED)


class TestSaveOutputsSelection:
    def test_layers_after_analysis(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        orch.run_analysis()
        saved = orch.save_outputs(layers=["wld", "eignungspolygone"])
        assert set(saved) <= {"wld", "eignungspolygone"}
        assert "wld" in saved

    def test_unknown_layer_rejected(self, stub_adapter, tmp_path):
        orch = FHeatOrchestrator(_cfg(tmp_path), stub_adapter)
        with pytest.raises(ValueError, match="Unknown layers"):
            orch.save_outputs(layers=["nope"])

    def test_clip_to_planning_area(self, stub_adapter, first_two_buildings_area, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_language="raw")
        orch = FHeatOrchestrator(cfg, stub_adapter)
        orch.run_analysis()
        orch.state.planning_area_gdf = first_two_buildings_area
        orch.run_planning()
        saved = orch.save_outputs(clip_to_planning_area=True)
        assert len(gpd.read_file(saved["buildings"])) == 2
        assert len(gpd.read_file(saved["parcels"])) == 1
        # network stays complete
        assert len(gpd.read_file(saved["netz"])) == len(orch.state.net_gdf)
