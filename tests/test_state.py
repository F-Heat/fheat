"""Tests for fheat_core.state.

Covers:
- Phase enum values match the documented contract.
- Phase order constants used by the orchestrator.
- PipelineState defaults (everything None except phase).
- PipelineState field assignment.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from fheat_core.state import Phase, PipelineState


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------


class TestPhase:
    def test_phase_values(self):
        assert Phase.INITIAL.value == "initial"
        assert Phase.DOWNLOADED.value == "downloaded"
        assert Phase.ADJUSTED.value == "adjusted"
        assert Phase.STATUS.value == "status"
        assert Phase.NETWORK.value == "network"
        assert Phase.RESULTS.value == "results"

    def test_phase_is_string_enum(self):
        """Phase inherits from str, so values are usable as plain strings."""
        assert isinstance(Phase.INITIAL, str)
        assert Phase.INITIAL == "initial"

    def test_phase_count(self):
        assert len(list(Phase)) == 6

    def test_phase_uniqueness(self):
        values = [p.value for p in Phase]
        assert len(set(values)) == len(values)


# ---------------------------------------------------------------------------
# PipelineState
# ---------------------------------------------------------------------------


class TestPipelineStateDefaults:
    def test_default_phase_is_initial(self):
        state = PipelineState()
        assert state.phase == Phase.INITIAL

    def test_all_frames_default_to_none(self):
        state = PipelineState()
        assert state.buildings_gdf is None
        assert state.streets_gdf is None
        assert state.parcels_gdf is None
        assert state.source_gdf is None
        assert state.wld_gdf is None
        assert state.polygons_gdf is None
        assert state.net_gdf is None

    def test_results_default_to_none(self):
        state = PipelineState()
        assert state.load_profile_df is None
        assert state.result_summary is None


class TestPipelineStateAssignment:
    def test_assign_input_frames(self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf):
        state = PipelineState()
        state.buildings_gdf = buildings_gdf
        state.streets_gdf = streets_gdf
        state.parcels_gdf = parcels_gdf
        state.source_gdf = source_gdf
        assert state.buildings_gdf is buildings_gdf
        assert state.streets_gdf is streets_gdf
        assert state.parcels_gdf is parcels_gdf
        assert state.source_gdf is source_gdf

    def test_phase_transitions(self):
        state = PipelineState()
        for phase in (Phase.DOWNLOADED, Phase.ADJUSTED, Phase.STATUS, Phase.NETWORK, Phase.RESULTS):
            state.phase = phase
            assert state.phase == phase

    def test_construct_with_explicit_phase(self):
        state = PipelineState(phase=Phase.STATUS)
        assert state.phase == Phase.STATUS

    def test_construct_with_prefilled_frames(self, buildings_gdf):
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        assert state.phase == Phase.DOWNLOADED
        assert state.buildings_gdf is buildings_gdf

    def test_assign_summary_dict(self):
        state = PipelineState()
        state.result_summary = {"total_buildings": 3}
        assert state.result_summary == {"total_buildings": 3}

    def test_assign_load_profile_df(self):
        state = PipelineState()
        df = pd.DataFrame({"a": [1]})
        state.load_profile_df = df
        assert state.load_profile_df is df
